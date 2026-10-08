"""Report ownership, isolation, truthful failures and the actual scenario process."""
import json
import os
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import create_app
from app.testing.catalog import catalog
from app.services.demo_report_service import DemoReportError, runner_diagnostics
from tests.test_central_app_auth import _settings


class DemoReportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.warmup=patch('app.services.inbound_call_service.FastUrduTTS.warmup',return_value=None);self.warmup.start()
        self.app=create_app(_settings(self.root));self.client=TestClient(self.app);self.client.__enter__()
        self.c=self.app.state.container;self.s=self.c.demo_report_service
        self.user=self.c.auth_repository.create_doctor('Dr. Report QA','reports@example.test','SyntheticQA123!')
        self.client.post('/api/auth/login',json={'email':'reports@example.test','password':'SyntheticQA123!'})
        self.base='/api/demo-testing/runs'
    def tearDown(self):
        self.client.__exit__(None,None,None);self.warmup.stop();self.temp.cleanup()
    def paused(self,mode='synthetic',confirm=False):
        with patch.object(self.s,'_run'):
            return self.s.start(self.user.user_id,mode,confirm)
    def test_complete_process_has_measured_checks_and_leaves_clinic_unchanged(self):
        from medflow.domain.models import Patient
        self.c.patient_repository.save(Patient(patient_id='PT-WORKING-CLINIC-SENTINEL',name='Working clinic sentinel',phone_number='03000000009',current_complaint='Untouched sentinel record'))
        before_patients=self.c.patient_repository.list();before_notes=self.c.note_repository.list()
        response=self.client.post(self.base,json={});self.assertEqual(response.status_code,202,response.text)
        run_id=response.json()['run_id'];deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            report=self.client.get(self.base+'/'+run_id).json()
            if report['status']!='RUNNING':break
            time.sleep(.05)
        self.assertEqual(report['status'],'PASSED',json.dumps(report['cases']))
        self.assertEqual(report['totals']['passed'],len(catalog()))
        self.assertGreater(report['duration_ms'],0)
        for case in report['cases']:
            self.assertTrue(case['checks']);self.assertGreaterEqual(case['duration_ms'],0)
            self.assertTrue(all(check['expected']==check['actual'] for check in case['checks']))
        self.assertEqual(self.c.patient_repository.list(),before_patients)
        self.assertEqual(self.c.note_repository.list(),before_notes)
        with self.c.database.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM appointments').fetchone()[0],0)
        export=self.client.get(self.base+'/'+run_id+'/export');self.assertEqual(export.status_code,200)
        self.assertIn('attachment;',export.headers['content-disposition']);self.assertEqual(export.json()['cases'],report['cases'])
        pdf=self.client.get(self.base+'/'+run_id+'/export.pdf');self.assertEqual(pdf.status_code,200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))
    def test_authentication_ownership_and_export_boundary(self):
        report=self.paused();self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get(self.base).status_code,401)
        self.assertEqual(self.client.get('/testing',follow_redirects=False).headers['location'],'/consultation/login?next=/testing')
        other=self.c.auth_repository.create_doctor('Other','other-reports@example.test','SyntheticQA123!')
        self.client.post('/api/auth/login',json={'email':'other-reports@example.test','password':'SyntheticQA123!'})
        self.assertEqual(self.client.get(self.base).json()['runs'],[])
        for suffix in ('','/export','/export.pdf'):
            self.assertEqual(self.client.get(self.base+'/'+report['run_id']+suffix).status_code,404)
        self.assertEqual(self.client.post(self.base+'/'+report['run_id']+'/cancel',json={}).status_code,404)
        self.assertEqual(self.s.get(report['run_id'],self.user.user_id)['status'],'RUNNING')
    def test_fixed_inputs_cross_site_and_live_acknowledgement(self):
        self.assertEqual(self.client.post(self.base,json={'patient_id':'REAL-PATIENT'}).status_code,422)
        self.assertEqual(self.client.post(self.base,json={'mode':'shell-command'}).status_code,422)
        self.assertEqual(self.client.post(self.base,json={},headers={'Origin':'https://other.example'}).status_code,403)
        self.assertEqual(self.client.post(self.base,json={},headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)
        self.assertEqual(self.client.post(self.base,json={'mode':'live_text','confirm_live':True}).status_code,400)
        self.s.settings=replace(self.s.settings,demo_live_text_enabled=True,openrouter_api_key='synthetic-provider-key')
        self.assertTrue(self.s.capabilities()['live_text_enabled'])
        with self.assertRaises(DemoReportError):self.paused('live_text',False)
        report=self.paused('live_text',True);self.assertEqual(len(report['cases']),len(catalog('live_text')))
    def test_database_lease_prevents_a_second_run(self):
        first=self.paused()
        with self.assertRaises(DemoReportError) as raised:self.paused()
        self.assertEqual(raised.exception.code,'ACTION_IN_PROGRESS')
        self.s.cancel(first['run_id'],self.user.user_id)
        second=self.paused();self.assertNotEqual(first['run_id'],second['run_id'])
    def test_cancel_preserves_completed_checks_and_ignores_late_events(self):
        report=self.paused();rid=report['run_id'];owner=self.user.user_id
        self.s._event(rid,owner,{'type':'case_started','id':'short-age'})
        result={'type':'case_finished','id':'short-age','status':'FAILED','checks':[{'label':'Age','expected':'23','actual':'22','status':'FAILED'}],'steps':[],'duration_ms':2,'error':None}
        self.s._event(rid,owner,result)
        cancelled=self.s.cancel(rid,owner);self.assertEqual(cancelled['status'],'CANCELLED')
        self.assertEqual(cancelled['totals']['failed'],1);self.assertEqual(cancelled['totals']['skipped'],len(catalog())-1)
        self.s._event(rid,owner,{'type':'case_started','id':'short-phone'})
        self.assertEqual(self.s.get(rid,owner),cancelled)
    def test_unmeasured_success_is_rejected_and_failures_are_retained(self):
        report=self.paused();rid=report['run_id'];owner=self.user.user_id
        self.s._event(rid,owner,{'type':'case_started','id':'short-age'})
        with self.assertRaises(ValueError):self.s._event(rid,owner,{'type':'case_finished','id':'short-age','status':'PASSED','checks':[]})
        with self.assertRaises(ValueError):self.s._event(rid,owner,{'type':'case_finished','id':'short-age','status':'PASSED','checks':[{'status':'PASSED','expected':23,'actual':22}]})
        self.s._event(rid,owner,{'type':'case_finished','id':'short-age','status':'FAILED','checks':[{'label':'Age','status':'FAILED','expected':23,'actual':22}],'steps':[],'duration_ms':5,'error':None})
        self.assertEqual(self.s.get(rid,owner)['totals']['failed'],1)
    def test_restart_marks_unfinished_run_interrupted(self):
        report=self.paused();self.s.recover_interrupted();loaded=self.s.get(report['run_id'],self.user.user_id)
        self.assertEqual(loaded['status'],'INTERRUPTED');self.assertEqual(loaded['totals']['skipped'],len(catalog()))
        self.assertIn('restarted',loaded['message'])
    def test_launch_failure_is_error_and_never_passes(self):
        with patch('app.services.demo_report_service.subprocess.Popen',side_effect=OSError('synthetic-start-error')):
            report=self.s.start(self.user.user_id,'synthetic')
            for thread in list(self.s._threads):thread.join(5)
        result=self.s.get(report['run_id'],self.user.user_id)
        self.assertEqual(result['status'],'ERROR');self.assertEqual(result['totals']['passed'],0);self.assertEqual(result['totals']['skipped'],len(catalog()))
    def test_time_limit_marks_unfinished_scenarios_unevaluated(self):
        import io
        class Process:
            stdout=io.StringIO('')
            killed=False
            def poll(self):return 0 if self.killed else None
            def kill(self):self.killed=True
            def wait(self,timeout=None):return 0
        class Timer:
            def __init__(self,seconds,callback):self.callback=callback
            def start(self):self.callback()
            def cancel(self):pass
        process=Process()
        with patch('app.services.demo_report_service.subprocess.Popen',return_value=process),patch('app.services.demo_report_service.threading.Timer',Timer):
            report=self.s.start(self.user.user_id,'synthetic')
            for thread in list(self.s._threads):thread.join(5)
        loaded=self.s.get(report['run_id'],self.user.user_id)
        self.assertEqual(loaded['status'],'ERROR');self.assertEqual(loaded['totals']['skipped'],len(catalog()))
        self.assertIn('time limit',loaded['message']);self.assertTrue(process.killed)
    def test_synthetic_environment_excludes_secrets_and_live_paths(self):
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'do-not-forward','MEDFLOW_DATABASE_PATH':'working-clinic.db','MEDFLOW_RECEPTIONIST_SERVICE_TOKEN':'do-not-forward'}):
            env=self.s._environment(self.root,'synthetic')
        self.assertNotIn('OPENROUTER_API_KEY',env);self.assertNotIn('MEDFLOW_DATABASE_PATH',env)
        self.assertNotIn('MEDFLOW_RECEPTIONIST_SERVICE_TOKEN',env);self.assertNotIn('HOME',env)
        self.assertEqual(env['PYTHON_DOTENV_DISABLED'],'1')
    def test_child_retains_launcher_added_dependencies_without_pythonpath(self):
        dependency=self.root/'launcher-packages';dependency.mkdir()
        (dependency/'qa_launcher_probe.py').write_text('VALUE = 23\n')
        with patch.object(sys,'path',[str(dependency),*sys.path]),patch.dict(os.environ,{'PYTHONPATH':'','OPENROUTER_API_KEY':'do-not-forward'}):
            env=self.s._environment(self.root,'synthetic')
            result=subprocess.run([sys.executable,'-c','import qa_launcher_probe; print(qa_launcher_probe.VALUE)'],
                env=env,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'23')
        self.assertNotIn('OPENROUTER_API_KEY',env)
    def test_startup_failure_reports_missing_dependency_without_raw_logs(self):
        class Process:
            stdout=io.StringIO('')
            stderr=io.StringIO("secret-provider-value\nModuleNotFoundError: No module named 'httpx'\n")
            def poll(self):return 1
            def wait(self,timeout=None):return 1
        with patch('app.services.demo_report_service.subprocess.Popen',return_value=Process()):
            report=self.s.start(self.user.user_id,'synthetic')
            for thread in list(self.s._threads):thread.join(5)
        result=self.s.get(report['run_id'],self.user.user_id)
        self.assertEqual(result['status'],'ERROR')
        self.assertEqual(result['totals']['passed'],0)
        self.assertEqual(result['totals']['skipped'],len(catalog()))
        self.assertEqual(result['runner_diagnostics']['missing_module'],'httpx')
        self.assertIn('requirements.txt',result['message'])
        self.assertNotIn('secret-provider-value',json.dumps(result))
    def test_bootstrap_emits_safe_diagnostic_before_any_scenario(self):
        from app.testing.worker import main, PREFIX
        out=io.StringIO()
        missing=ModuleNotFoundError('sensitive-url-and-key',name='dotenv')
        with patch.object(sys,'argv',['worker','synthetic',str(self.root)]),patch.object(sys,'__stdout__',out),patch('app.testing.worker.bootstrap',side_effect=missing):
            self.assertEqual(main(),1)
        event=json.loads(out.getvalue().removeprefix(PREFIX))
        self.assertEqual(event,{'type':'runner_error','error_type':'ModuleNotFoundError','missing_module':'dotenv'})
        self.assertNotIn('sensitive',out.getvalue())
    def test_diagnostics_reject_arbitrary_text_and_explain_signal(self):
        diagnostic=runner_diagnostics(-9,'secret-token',{'error_type':'RuntimeError: secret','missing_module':'url?key=secret'})
        self.assertEqual(diagnostic,{'exit_code':-9,'signal':9})
    def test_live_text_requires_actual_provider_response_and_does_not_score_fallback(self):
        from app.testing.worker import run_live, Probe
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'synthetic-provider-key'}):
            with patch('app.services.demo_call_service.DemoCallService._completion',return_value=json.dumps({'intent':'answer','fields':{'age':{'ur':'23','en':'23'}},'fix':['age']})):
                probe=Probe();run_live('live-correction',probe,self.root/'live-correction')
                self.assertTrue(all(check['status']=='PASSED' for check in probe.checks))
            with patch('app.services.demo_call_service.DemoCallService._completion',return_value=json.dumps({'intent':'unclear','fields':{},'needs_review':True})):
                probe=Probe();run_live('live-uncertainty',probe,self.root/'live-uncertainty')
                self.assertTrue(all(check['status']=='PASSED' for check in probe.checks))
            with patch('app.services.demo_call_service.DemoCallService._completion',side_effect=RuntimeError('synthetic-provider-failure')):
                probe=Probe();run_live('live-correction',probe,self.root/'live-failure')
                self.assertEqual(probe.checks[0]['status'],'FAILED')
    def test_live_soap_checklist_path_with_mock_provider(self):
        from app.testing.worker import run_live, Probe, Clinic
        from security_guardrails import set_gateway
        try:
            with patch('app.testing.worker.Clinic',side_effect=lambda root,mode:Clinic(root,'synthetic')):
                probe=Probe();run_live('live-soap',probe,self.root/'live-soap')
            self.assertTrue(all(check['status']=='PASSED' for check in probe.checks),probe.checks)
            self.assertTrue(any(check['label']=='Model result, not fallback' for check in probe.checks))
        finally:set_gateway(None)
    def test_history_is_bounded_and_disabled_configuration_is_explicit(self):
        for _ in range(52):
            report=self.paused();self.s.cancel(report['run_id'],self.user.user_id)
        self.assertEqual(len(self.s.list(self.user.user_id)),50)
        self.s.settings=replace(self.s.settings,demo_testing_enabled=False)
        self.assertEqual(self.client.get('/api/demo-testing/configuration').status_code,503)
        self.assertEqual(self.client.post(self.base,json={}).status_code,503)


if __name__=='__main__':unittest.main()
