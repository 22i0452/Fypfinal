"""Owned, durable demo reports and a bounded disposable scenario subprocess."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import uuid

from app.testing.catalog import PACK_VERSION, catalog

ROOT = Path(__file__).resolve().parents[2]


def runner_diagnostics(code, stderr='', event=None):
    """Expose bounded exception identifiers, never raw provider logs or secrets."""
    event=event or {}
    result={'exit_code':code}
    error_type=event.get('error_type','')
    if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',str(error_type)):
        result['error_type']=error_type
    module=event.get('missing_module')
    if not module:
        match=re.search(r"ModuleNotFoundError: No module named '([A-Za-z0-9_.]{1,120})'",stderr)
        module=match.group(1) if match else None
    if module and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]{0,119}',str(module)):
        result.update(error_type='ModuleNotFoundError',missing_module=module)
    if code is not None and code<0:result['signal']=-code
    return result


def runner_failure_message(diagnostics):
    module=diagnostics.get('missing_module')
    if module:
        return (f"Test runner cannot import '{module}'. Install the app dependencies with "
                'python -m pip install -r requirements.txt, then restart the app and run a new report. '
                'Completed results are retained.')
    code=diagnostics.get('exit_code')
    suffix=f' (exit code {code})' if code is not None else ''
    return ('Test runner exited before all scenarios finished'+suffix+
            '. Completed results are retained. Inspect Run details for the startup diagnostic.')


def now():
    return datetime.now(timezone.utc).isoformat()


class DemoReportError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code=code


def source_fingerprint():
    digest=hashlib.sha256()
    for folder in ('app','medflow','security_guardrails','scribe'):
        for path in sorted((ROOT/folder).rglob('*.py')):
            digest.update(str(path.relative_to(ROOT)).encode());digest.update(path.read_bytes())
    return digest.hexdigest()


def totals(report):
    rows=report['cases']
    return {key.lower():sum(row['status']==key for row in rows)
            for key in ('PASSED','FAILED','ERROR','SKIPPED','RUNNING','PENDING')} | {'total':len(rows)}


class DemoReportService:
    def __init__(self, database, settings):
        self.database=database
        self.settings=settings
        self._lock=threading.RLock()
        self._processes={}
        self._threads=[]

    def initialize(self):
        with self.database.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS demo_test_reports (run_id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS demo_reports_owner ON demo_test_reports(owner_id, created_at)')

    def recover_interrupted(self):
        # The existing deployment uses one application worker. Never present a
        # vanished process as a successful or still-running test after restart.
        with self.database.connection() as db:
            rows=db.execute("SELECT run_id,payload FROM demo_test_reports WHERE status='RUNNING'").fetchall()
            for row in rows:
                report=json.loads(row['payload'])
                self._end(report,'INTERRUPTED','Server restarted before this run finished.')
                self._write(db,report)

    def capabilities(self):
        return {'enabled':self.settings.demo_testing_enabled,'pack_version':PACK_VERSION,
                'live_text_enabled':self.settings.demo_live_text_enabled and bool(self.settings.openrouter_api_key),
                'live_text_reason':None if self.settings.demo_live_text_enabled and self.settings.openrouter_api_key else 'Live text checks require DEMO_LIVE_TEXT_ENABLED=true and the existing OPENROUTER_API_KEY.',
                'modes':{'synthetic':catalog(),'live_text':catalog('live_text')},
                'unassessed':['Physical microphone and live ASR accuracy','Clinical correctness and coding catalog validity','Calibrated confidence and speaker diarization accuracy'],
                'history_limit':50}

    @staticmethod
    def _write(db,report):
        report['totals']=totals(report)
        db.execute('UPDATE demo_test_reports SET status=?,payload=? WHERE run_id=?',
                   (report['status'],json.dumps(report,ensure_ascii=False),report['run_id']))

    @staticmethod
    def _end(report,status,reason=None):
        report['status']=status;report['finished_at']=now();report['message']=reason
        report['duration_ms']=round((datetime.fromisoformat(report['finished_at'])-datetime.fromisoformat(report['started_at'])).total_seconds()*1000,2)
        for row in report['cases']:
            if row['status'] in {'PENDING','RUNNING'}:
                row['status']='SKIPPED';row['error']={'message':reason or 'This scenario did not finish.'}

    def get(self,run_id,owner_id):
        with self.database.connection() as db:
            row=db.execute('SELECT payload FROM demo_test_reports WHERE run_id=? AND owner_id=?',(run_id,owner_id)).fetchone()
        if not row:raise DemoReportError('REPORT_NOT_FOUND','Test report was not found.')
        return json.loads(row[0])

    def list(self,owner_id):
        with self.database.connection() as db:
            rows=db.execute('SELECT payload FROM demo_test_reports WHERE owner_id=? ORDER BY created_at DESC LIMIT 50',(owner_id,)).fetchall()
        return [{key:report.get(key) for key in ('run_id','mode','status','started_at','finished_at','duration_ms','totals','pack_version')}
                for report in (json.loads(row[0]) for row in rows)]

    def start(self,owner_id,mode,confirm_live=False):
        if not self.settings.demo_testing_enabled:raise DemoReportError('FEATURE_DISABLED','Demo testing is disabled for this deployment.')
        if mode not in {'synthetic','live_text'}:raise DemoReportError('INVALID_TEST_MODE','Unknown test mode.')
        if mode=='live_text' and (not confirm_live or not self.capabilities()['live_text_enabled']):
            raise DemoReportError('LIVE_TEST_UNAVAILABLE','Enable live text checks and explicitly acknowledge real provider requests.')
        timestamp=now()
        report={'run_id':'QA-'+uuid.uuid4().hex,'owner_id':owner_id,'pack_version':PACK_VERSION,
                'mode':mode,'status':'RUNNING','started_at':timestamp,'finished_at':None,'duration_ms':None,
                'timing_scope':'Real provider and application wall time' if mode=='live_text' else 'Synthetic scenario and application wall time; not provider speed',
                'environment':{'application':'Current server code','source_sha256':source_fingerprint(),'python':sys.version.split()[0],
                               'provider':'OpenRouter' if mode=='live_text' else 'Controlled fixtures; outbound network blocked',
                               'model':self.settings.openrouter_llm_model if mode=='live_text' else None,
                               'reception_model':'openai/gpt-4o-mini' if mode=='live_text' else None,
                               'database':'Temporary isolated clinic; no working-clinic patient IDs accepted'},
                'unassessed':self.capabilities()['unassessed'],
                'cases':[{**item,'status':'PENDING','checks':[],'steps':[],'duration_ms':None,'error':None} for item in catalog(mode)]}
        report['totals']=totals(report)
        with self.database.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM demo_test_reports WHERE status='RUNNING' LIMIT 1").fetchone():
                raise DemoReportError('ACTION_IN_PROGRESS','A test run is already active. Wait for it to finish or stop your current run.')
            db.execute('INSERT INTO demo_test_reports VALUES (?,?,?,?,?)',(report['run_id'],owner_id,'RUNNING',timestamp,json.dumps(report,ensure_ascii=False)))
            db.execute("DELETE FROM demo_test_reports WHERE owner_id=? AND status!='RUNNING' AND run_id NOT IN (SELECT run_id FROM demo_test_reports WHERE owner_id=? ORDER BY created_at DESC LIMIT 50)",(owner_id,owner_id))
        worker=threading.Thread(target=self._run,args=(report['run_id'],owner_id,mode),daemon=True)
        with self._lock:self._threads=[thread for thread in self._threads if thread.is_alive()];self._threads.append(worker)
        worker.start()
        return report

    def _event(self,run_id,owner_id,event):
        with self.database.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM demo_test_reports WHERE run_id=? AND owner_id=?',(run_id,owner_id)).fetchone()
            report=json.loads(row[0])
            if report['status']!='RUNNING':return
            case=next((item for item in report['cases'] if item['id']==event.get('id')),None)
            if case is None:raise ValueError('Unknown scenario event')
            if event['type']=='case_started':
                if case['status']!='PENDING':raise ValueError('Duplicate scenario start')
                case['status']='RUNNING';case['started_at']=now()
            elif event['type']=='case_finished':
                if case['status']!='RUNNING' or event['status'] not in {'PASSED','FAILED','ERROR'}:raise ValueError('Invalid scenario completion')
                # A success must actually contain passing assertions.
                checks=event.get('checks',[])
                duration=event.get('duration_ms')
                if not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<0:
                    raise ValueError('Missing measured duration')
                if any(check.get('status') not in {'PASSED','FAILED'} or (check['status']=='PASSED')!=(check.get('expected')==check.get('actual')) for check in checks):
                    raise ValueError('Inconsistent assertion result')
                if event['status']=='PASSED' and (not checks or any(check.get('status')!='PASSED' or check.get('expected')!=check.get('actual') for check in checks)):
                    raise ValueError('Unmeasured success')
                for key in ('status','checks','steps','duration_ms','error'):case[key]=event.get(key)
                case['finished_at']=now()
            else:raise ValueError('Unknown event')
            self._write(db,report)

    def _finish(self,run_id,owner_id,status,reason=None,diagnostics=None):
        with self.database.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM demo_test_reports WHERE run_id=? AND owner_id=?',(run_id,owner_id)).fetchone()
            report=json.loads(row[0])
            if report['status']!='RUNNING':return report
            if diagnostics is not None:report['runner_diagnostics']=diagnostics
            self._end(report,status,reason);self._write(db,report)
        return report

    def _environment(self,root,mode):
        # Do not forward arbitrary environment variables, live DB paths,
        # credentials or service tokens to the child. dotenv is disabled there.
        env={key:os.environ[key] for key in ('PATH','SYSTEMROOT','WINDIR','LD_LIBRARY_PATH','LANG','LC_ALL','PYTHONPATH') if key in os.environ}
        # Launchers can add package directories to sys.path without setting
        # PYTHONPATH. Reuse the running app's imports, never its credentials.
        env['PYTHONPATH']=os.pathsep.join(dict.fromkeys(
            str(Path(path or ROOT).resolve()) for path in sys.path if isinstance(path,str)))
        env.update(PYTHONUNBUFFERED='1',PYTHON_DOTENV_DISABLED='1',TMPDIR=str(root))
        if mode=='live_text':
            env['OPENROUTER_API_KEY']=self.settings.openrouter_api_key
            env['OPENROUTER_LLM_MODEL']=self.settings.openrouter_llm_model
        return env

    def _run(self,run_id,owner_id,mode):
        process=None;timer=None;stderr_thread=None;timed_out=threading.Event()
        stderr_tail=bytearray();startup_error=None
        temporary=tempfile.TemporaryDirectory(prefix='medflow-qa-')
        try:
            directory=temporary.name
            root=Path(directory)
            if self.get(run_id,owner_id)['status']!='RUNNING':return
            process=subprocess.Popen([sys.executable,'-m','app.testing.worker',mode,str(root)],cwd=ROOT,
                env=self._environment(root,mode),stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                text=True,encoding='utf-8')
            # Drain both pipes to avoid deadlock; retain only a small log tail.
            # Raw logs are never stored in reports or exposed to the browser.
            def drain_stderr():
                stream=getattr(process,'stderr',None)
                if stream is None:return
                while True:
                    chunk=stream.read(4096)
                    if not chunk:break
                    stderr_tail.extend(chunk.encode('utf-8',errors='replace'))
                    del stderr_tail[:-16384]
            stderr_thread=threading.Thread(target=drain_stderr,daemon=True);stderr_thread.start()
            with self._lock:self._processes[run_id]=process
            if self.get(run_id,owner_id)['status']!='RUNNING':process.terminate()
            def timeout():
                timed_out.set()
                if process.poll() is None:process.kill()
            timer=threading.Timer(180 if mode=='live_text' else 90,timeout);timer.daemon=True;timer.start()
            finished=False;bytes_read=0
            while True:
                line=process.stdout.readline(65537)
                if not line:break
                bytes_read+=len(line)
                if len(line)>65536 or bytes_read>2_000_000:raise ValueError('Scenario output limit exceeded')
                if not line.startswith('MEDFLOW_QA_EVENT '):continue
                event=json.loads(line[len('MEDFLOW_QA_EVENT '):])
                if event['type']=='finished':finished=True
                elif event['type']=='runner_error':startup_error=event
                else:self._event(run_id,owner_id,event)
            code=process.wait(timeout=5)
            stderr_thread.join(timeout=1)
            diagnostic=runner_diagnostics(code,stderr_tail.decode('utf-8',errors='replace'),startup_error)
            report=self.get(run_id,owner_id)
            if report['status']=='RUNNING':
                if timed_out.is_set():self._finish(run_id,owner_id,'ERROR','Test runner reached its time limit. Unfinished cases were not counted as passes.')
                elif startup_error or code!=0 or not finished or any(row['status'] in {'PENDING','RUNNING'} for row in report['cases']):
                    self._finish(run_id,owner_id,'ERROR',runner_failure_message(diagnostic),diagnostic)
                else:
                    status='ERROR' if any(row['status']=='ERROR' for row in report['cases']) else 'FAILED' if any(row['status']=='FAILED' for row in report['cases']) else 'PASSED'
                    self._finish(run_id,owner_id,status)
        except Exception as exc:
            diagnostic=runner_diagnostics(None,event={'error_type':type(exc).__name__})
            self._finish(run_id,owner_id,'ERROR','Test runner could not finish. Check app dependencies and retry; completed results are retained.',diagnostic)
        finally:
            if timer:timer.cancel()
            if process:
                if process.poll() is None:process.kill()
                process.wait(timeout=5);process.stdout.close()
                if stderr_thread:stderr_thread.join(timeout=1)
                if getattr(process,'stderr',None):process.stderr.close()
            with self._lock:self._processes.pop(run_id,None)
            temporary.cleanup()

    def cancel(self,run_id,owner_id):
        self.get(run_id,owner_id)  # Verify ownership before touching a process.
        report=self._finish(run_id,owner_id,'CANCELLED','Stopped by the user. Unfinished scenarios were not evaluated.')
        with self._lock:
            process=self._processes.get(run_id)
            if process and process.poll() is None:process.terminate()
        return report

    def shutdown(self):
        with self.database.connection() as db:
            rows=db.execute("SELECT run_id,owner_id FROM demo_test_reports WHERE status='RUNNING'").fetchall()
        for row in rows:
            self._finish(row['run_id'],row['owner_id'],'INTERRUPTED','Server stopped before the test finished.')
        with self._lock:
            for process in self._processes.values():
                if process.poll() is None:process.terminate()
            threads=list(self._threads)
        for thread in threads:
            if thread.is_alive():thread.join(timeout=3)
