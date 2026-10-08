"""Fixed scenario runner. Only launched in a disposable, separate process.

stdout contains a prefixed event protocol; library logs go to discarded stderr.
Synthetic runs block outbound sockets and never inherit provider credentials.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import sys
import time

from app.testing.catalog import catalog

PREFIX = 'MEDFLOW_QA_EVENT '


def emit(event):
    sys.__stdout__.write(PREFIX + json.dumps(event, ensure_ascii=False) + '\n')
    sys.__stdout__.flush()


class Probe:
    def __init__(self):
        self.checks = []
        self.steps = []

    def check(self, label, expected, actual):
        self.checks.append({'label': label, 'expected': expected, 'actual': actual,
                            'status': 'PASSED' if expected == actual else 'FAILED'})

    def call(self, label, function):
        started = time.perf_counter()
        try:
            return function()
        finally:
            self.steps.append({'label': label, 'duration_ms': round((time.perf_counter()-started)*1000, 2)})


def bootstrap(root, mode):
    # Disable dotenv before importing any application settings/components.
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
    os.environ.update(APP_ENV='test', DEVELOPMENT_QUICK_START_ENABLED='false', SHOW_DEV_OTP='false',
        MEDFLOW_DATABASE_PATH=str(root/'default.db'), MEDFLOW_PATIENT_RECORDS_DIR=str(root/'default-patients'),
        MEDFLOW_GENERATED_NOTES_DIR=str(root/'default-notes'), PRIMARY_DOCTOR_EMAIL='',
        MEDFLOW_TEST_REPORT_WORKER='1', SESSION_SECRET='synthetic-report-session-secret-at-least-32-characters',
        OTP_SECRET='synthetic-report-otp-secret-at-least-32-characters', TEST_OTP_CODE='123456')
    if mode == 'synthetic':
        for key in list(os.environ):
            if any(marker in key.upper() for marker in ('API_KEY','TOKEN','PASSWORD','SECRET')):
                os.environ.pop(key,None)
        os.environ['SESSION_SECRET']='synthetic-report-session-secret-at-least-32-characters'
        os.environ['OTP_SECRET']='synthetic-report-otp-secret-at-least-32-characters'
        import socket
        def blocked(*args, **kwargs):
            raise RuntimeError('Outbound network is disabled in synthetic QA')
        socket.socket.connect = blocked
        socket.create_connection = blocked
    from app.services.inbound_call_service import FastUrduTTS
    FastUrduTTS.warmup = lambda *args, **kwargs: None
    # Call media and imported default-app repositories are redirected too.
    import app.container as container_module
    container_module.ROOT_DIR = root


class Clinic:
    def __init__(self, root, mode='synthetic'):
        from app.config import Settings, ROOT_DIR
        from app.main import create_app
        from fastapi.testclient import TestClient
        from security_guardrails import SecureLLMGateway, set_gateway
        settings = Settings(app_env='test', database_path=root/'clinic.db',
            session_secret='synthetic-report-session-secret-at-least-32-characters',
            session_cookie_name='report_sandbox', session_max_age_seconds=3600,
            mock_otp_enabled=True, show_dev_otp=False, otp_secret='synthetic-report-otp-secret-at-least-32-characters',
            test_otp_code='123456', otp_expiry_seconds=300, otp_lock_seconds=900,
            otp_resend_cooldown_seconds=60, otp_max_attempts=5, otp_max_resends=5,
            clinic_seed_path=ROOT_DIR/'app/data/clinic_seed.json', patient_records_dir=root/'patients',
            generated_notes_dir=root/'notes', icd_coding_enabled=True,
            receptionist_service_token='synthetic-report-reception-token-at-least-32-characters')
        self.gateway = SecureLLMGateway(provider='openrouter' if mode == 'live_text' else 'mock')
        set_gateway(self.gateway)
        if mode == 'synthetic':
            self.gateway._adapter('mock').set_response('soap_generation', {
                'subjective':'Patient reports cough for two days.', 'objective':'Not documented.',
                'assessment':'Not documented.', 'plan':'Not documented.',
                'evidence':[{'utterance_id':'U1','quote':'cough for two days'}],
                'claim_sources':{'subjective':[{'text':'Patient reports cough for two days.','evidence_ids':['U1']}],
                                 'objective':[], 'assessment':[], 'plan':[]}})
        self.client = TestClient(create_app(settings))
        self.client.__enter__()
        self.c = self.client.app.state.container
        self.user = self.c.auth_repository.create_doctor('Dr. Fictional QA', 'qa@example.test', 'SyntheticQA123!')
        self.client.post('/api/auth/login', json={'email':'qa@example.test','password':'SyntheticQA123!'})

    def close(self):
        self.client.__exit__(None, None, None)

    def intake(self, suffix='one'):
        from app.services import ReceptionistIntake
        token = 'synthetic-report-intake-token-' + suffix.ljust(12, 'x')
        return ReceptionistIntake(name='Fictional QA Patient', age_text='23', phone_number='03000000001',
            first_visit='Yes', past_medical_history='None', current_complaint='Cough for two days',
            intake_token=token, revision=1, confirmed_revision=1)

    def booking(self, intake, saved, start=None):
        from datetime import date, timedelta, datetime
        from app.services import ReceptionistBooking
        profile = self.c.clinic_repository.get_practitioner(self.user.practitioner_id)
        slots = self.c.receptionist_integration_service.availability(practitioner_id=self.user.practitioner_id,
            visit_type_id='VISIT-NEW', start_date=date.today()+timedelta(days=2))['slots']
        start = start or slots[0]['start_at']
        return ReceptionistBooking(patient_id=saved['patient_id'], workflow_id=saved['workflow_id'],
            department_id=profile['department_id'], practitioner_id=self.user.practitioner_id,
            visit_type_id='VISIT-NEW', start_at=datetime.fromisoformat(start),
            idempotency_key=intake.intake_token+'-booking', intake_token=intake.intake_token, revision=1)

    def ready(self, consent=True):
        from medflow.orchestration import WorkflowAction
        from medflow.domain.enums import ConsentType
        from security_guardrails import Actor
        intake=self.intake(); saved=self.c.receptionist_integration_service.create_intake(intake)
        booking=self.c.receptionist_integration_service.book(self.booking(intake,saved))
        self.patient=self.c.patient_repository.get(saved['patient_id'])
        self.actor=Actor(str(self.user.user_id),'doctor',{self.patient.patient_id},self.patient.patient_id)
        workflow=self.c.workflow_repository.get(saved['workflow_id'])
        workflow=self.c.workflow_orchestrator.perform_action(workflow.workflow_id,WorkflowAction.VERIFY_PATIENT,
            actor=self.actor,expected_version=workflow.version)
        workflow=self.c.lifecycle_service.complete_existing_intake(workflow.workflow_id,actor=self.actor)
        self.visit=self.c.lifecycle_service.check_in(workflow.workflow_id,actor=self.actor)
        self.path='/api/workflows/'+workflow.workflow_id
        if consent:
            self.c.consent_service.capture_bundle(encounter_id=self.visit.encounter.encounter_id,
                decisions={kind:kind!=ConsentType.AUDIO_RETENTION for kind in ConsentType},
                consent_text_version='CONSENT-V1',capture_method='SYNTHETIC_REPORT',actor=self.actor)
        return booking

    def capture(self):
        with self.client.websocket_connect('/ws') as ws:
            ws.send_json({'type':'start','patient_id':self.patient.patient_id,'workflow_id':self.visit.workflow.workflow_id,
                'encounter_id':self.visit.encounter.encounter_id,'capture_id':'REPORT-SYNTHETIC-PCM',
                'sample_rate':16000,'auto_soap':False})
            started=ws.receive_json()
            if started['type']=='error':return started
            ws.send_bytes(bytes(64000));ws.send_json({'type':'stop'})
            while True:
                item=ws.receive_json()
                if item['type'] in {'conversation_ready','soap_note','error'}:return item

    def checkpoint(self):
        # Fixed, human-authored source for SOAP checks; no implied ASR accuracy.
        from medflow.domain.models import TranscriptUtterance
        from medflow.domain.enums import Speaker
        transcript=self.c.documentation_service.save_transcript(transcript_id='TR-FICTIONAL-QA',
            patient_id=self.patient.patient_id,encounter_id=self.visit.encounter.encounter_id,
            utterances=[TranscriptUtterance(transcript_id='TR-FICTIONAL-QA',utterance_id='U1',speaker=Speaker.PATIENT,
                original_text='مجھے دو دن سے کھانسی ہے',clinical_english='Patient reports cough for two days.')])
        self.c.lifecycle_service.start_consultation(self.visit.workflow.workflow_id,actor=self.actor)
        self.c.lifecycle_service.start_documentation(self.visit.workflow.workflow_id,actor=self.actor)
        run=self.c.process_trace.start(self.patient.patient_id,self.visit.encounter.encounter_id,'REPORT-TEXT')
        self.c.consultation_review.prepare(self.visit.workflow.workflow_id,transcript,run,None,False)
        self.c.consultation_review.ready(self.visit.workflow.workflow_id,self.actor)
        return transcript

    def context(self):
        return self.client.get('/api/workflows/context/'+self.patient.patient_id).json()

    def revision(self):
        review=self.context()['conversation_review']
        return {'expected_revision':review['revision'],'transcript_id':review['transcript_id']}

    def generate(self):
        return self.client.post(self.path+'/generate-soap',json=self.revision())


def extraction(key, value, **extra):
    return {'intent':'answer','fields':{key:{'ur':value,'en':value}},'fix':[],**extra}


def run_case(case_id, p, root):
    from unittest.mock import patch
    from app.services.demo_call_service import DemoCallService
    from app.services.booking_flow import BookingFlow
    from app.services.coding_service import CodingCandidate
    if case_id in {'short-confirmation','short-age','short-phone','department-repeat','age-correction','unclear-answer'}:
        service=DemoCallService(groq_api_key='',groq_llm_model='',openrouter_api_key='')
        if case_id=='short-confirmation':
            flow=BookingFlow({'current':'age','step':'confirm','pending':{'key':'age','ur':'23','en':'23'},'values':{'name':{'ur':'Fictional QA Patient','en':'Fictional QA Patient'}}});text='جی'
        elif case_id=='short-age':flow=BookingFlow({'current':'age'});text='۲۳'
        elif case_id=='short-phone':flow=BookingFlow({'current':'phone'});text='۰۳۰۰۰۰۰۰۰۰۱'
        elif case_id=='department-repeat':flow=BookingFlow({'current':'department','values':{key:{'ur':value,'en':value} for key,value in {'name':'Fictional QA Patient','age':'23','phone':'03000000001','first_visit':'Yes','history':'None','complaint':'Cough'}.items()}});text='جنرل میڈیسن جنرل میڈیسن'
        elif case_id=='age-correction':flow=BookingFlow({'current':'age','step':'confirm','pending':{'key':'age','ur':'22','en':'22'},'values':{'name':{'ur':'Fictional QA Patient','en':'Fictional QA Patient'}}});text='نہیں، 23'
        else:flow=BookingFlow({'current':'phone','values':{'age':{'ur':'23','en':'23'}}});text='uncertain fictional answer'
        stub=extraction('age','23',fix=['age']) if case_id=='age-correction' else {'needs_review':True,'fields':{},'interpretation':{'ur':text,'en':''}}
        with patch.object(service,'_extract',return_value=stub) as extractor:
            result=p.call('Process receptionist turn',lambda:service.turn(scenario_id='in-new-booking',history=[flow.state_message()],user_message=text))
        after=BookingFlow.from_history(result['history'])
        if case_id=='short-confirmation':
            p.check('Confirmed age','23',after.values.get('age',{}).get('en'));p.check('Next field','phone',after.current);p.check('Model calls',0,extractor.call_count)
        elif case_id in {'short-age','short-phone'}:
            key='age' if case_id=='short-age' else 'phone';value='23' if key=='age' else '03000000001'
            p.check('Held value',value,(after.pending or {}).get('en'));p.check('Read-back required','confirm',after.step);p.check('Model calls',0,extractor.call_count)
        elif case_id=='department-repeat':
            p.check('Department','General Medicine',after.values.get('department',{}).get('en'));p.check('Next field','doctor',after.current)
        elif case_id=='age-correction':
            p.check('Correction read back before acceptance','confirm',after.step)
            confirmed=service.turn(scenario_id='in-new-booking',history=result['history'],user_message='جی')
            after=BookingFlow.from_history(confirmed['history']);p.check('Corrected age','23',after.values.get('age',{}).get('en'));p.check('Confirmation required',True,after.current=='phone')
        else:
            p.check('Preserved age',flow.values['age'],after.values.get('age'));p.check('Still collecting phone','phone',after.current);p.check('Held for review',True,result['understanding']['needs_review'])
        p.steps.append({'label':'Saved turn state','data':{'current':after.current,'step':after.step,'values':after.values,'last_answer':after.last_answer}})
        return
    fixture=Clinic(root)
    try:
        c=fixture.c;client=fixture.client;integration=c.receptionist_integration_service
        if case_id in {'doctor-selection','intake-repeat','slot-conflict','doctor-handoff'}:
            if case_id=='doctor-selection':
                flow=BookingFlow({'current':'doctor','values':{'department':{'ur':'جنرل میڈیسن','en':'General Medicine'}}})
                service=c.demo_call_service;choices=service._doctor_choices(flow,fixture.user.practitioner_id)
                result=p.call('Select displayed doctor',lambda:service.turn(scenario_id='in-new-booking',history=[flow.state_message()],user_message='1',preferred_practitioner_id=fixture.user.practitioner_id))
                selected=BookingFlow.from_history(result['history']).values.get('doctor',{})
                p.check('Exact practitioner',choices[0]['practitioner_id'],selected.get('practitioner_id'));p.check('Name matches catalog',choices[0]['display_name'],selected.get('en'))
                return
            intake=fixture.intake();saved=p.call('Save intake',lambda:integration.create_intake(intake))
            if case_id=='intake-repeat':
                repeated=p.call('Repeat intake save',lambda:integration.create_intake(intake))
                p.check('Same patient',saved['patient_id'],repeated['patient_id']);p.check('Same workflow',saved['workflow_id'],repeated['workflow_id']);p.check('Patient count',1,len(c.patient_repository.list()));return
            request=fixture.booking(intake,saved);booked=p.call('Request appointment',lambda:integration.book(request))
            if case_id=='slot-conflict':
                second_intake=fixture.intake('two');second=integration.create_intake(second_intake)
                unavailable=p.call('Request occupied slot',lambda:integration.book(fixture.booking(second_intake,second,request.start_at.isoformat())))
                p.check('Alternative response','ALTERNATIVES_REQUIRED',unavailable['status']);p.check('No second appointment',None,c.workflow_repository.get(second['workflow_id']).appointment_id);p.check('Saved intake retained',True,c.patient_repository.get(second['patient_id']) is not None);p.check('Alternatives available',True,bool(unavailable.get('alternatives')))
            else:
                response=p.call('Open doctor context API',lambda:client.get('/api/workflows/context/'+saved['patient_id']))
                p.check('Authorized context response',200,response.status_code);context=response.json();p.check('Same workflow',saved['workflow_id'],context['workflow']['workflow_id']);p.check('Same appointment',booked['appointment']['appointment_id'],context['appointment']['appointment_id']);p.check('Pending request visible','REQUESTED',context['appointment']['status'])
            p.steps.append({'label':'Stored receipt','data':{'patient_id':saved['patient_id'],'workflow_id':saved['workflow_id'],'appointment_id':booked['appointment']['appointment_id']}});return
        fixture.ready(consent=case_id!='consent-gate')
        if case_id=='consent-gate':
            result=p.call('Attempt capture without consent',fixture.capture);p.check('Capture rejected','error',result['type']);p.check('Reason','REQUIRED_CONSENT_MISSING',result.get('code'));p.check('No draft',None,fixture.context()['note']);return
        if case_id=='transcript-checkpoint':
            with patch.object(c.documentation_service,'generate_draft',wraps=c.documentation_service.generate_draft) as draft:
                result=p.call('Capture with synthetic providers',fixture.capture)
            context=fixture.context();p.check('Stopped at transcript','conversation_ready',result['type']);p.check('Saved checkpoint','TRANSCRIPT_REVIEW',context['workflow']['state']);p.check('SOAP calls',0,draft.call_count);p.check('Same encounter',fixture.visit.encounter.encounter_id,context['encounter']['encounter_id']);return
        transcript=fixture.checkpoint()
        if case_id=='soap-retry':
            with patch.object(c.documentation_service,'generate_draft',side_effect=RuntimeError('Injected synthetic failure')):
                failed=p.call('Injected SOAP failure',fixture.generate)
            p.check('Failure response',503,failed.status_code);p.check('Transcript retained',transcript.transcript_id,fixture.revision()['transcript_id'])
            retried=p.call('Retry SOAP',fixture.generate);p.check('Retry succeeds',200,retried.status_code);p.check('Same encounter',fixture.visit.encounter.encounter_id,retried.json()['encounter']['encounter_id']);return
        if case_id=='transcript-correction':
            before=fixture.revision();changed=p.call('Save corrected turn',lambda:client.patch(fixture.path+'/conversation',json={**before,'corrections':[{'utterance_id':'U1','speaker':'PATIENT','original_text':'مجھے تین دن سے کھانسی ہے','clinical_english':'Patient reports cough for three days.'}]}))
            p.check('Correction saved',200,changed.status_code);p.check('New revision',2,fixture.revision()['expected_revision']);p.check('Original still stored',True,c.transcript_repository.get(before['transcript_id']) is not None)
            stale=client.post(fixture.path+'/generate-soap',json=before);p.check('Old revision rejected',409,stale.status_code);return
        generated=p.call('Generate saved SOAP',fixture.generate);p.check('SOAP response',200,generated.status_code)
        note=generated.json()['note'];note_id=note['note_id']
        class SourceProvider:
            def suggest(self,version):
                return [CodingCandidate('R05.9','Synthetic candidate for source checks',None,[version.soap.subjective[0].claim_id],method='QA_SYNTHETIC')]
        c.coding_service.provider=SourceProvider();codes=client.post('/api/notes/'+note_id+'/code-suggestions').json()['suggestions'];code_id=codes[0]['code_suggestion_id']
        if case_id=='patient-access':
            c.auth_repository.create_doctor('Dr. Other Fictional','other-qa@example.test','SyntheticQA123!');client.post('/api/auth/login',json={'email':'other-qa@example.test','password':'SyntheticQA123!'})
            p.check('Conversation access denied',403,client.get('/api/workflows/context/'+fixture.patient.patient_id).status_code);p.check('Code evidence denied',403,client.get('/api/code-suggestions/'+code_id+'/evidence').status_code);return
        old_source=client.get('/api/code-suggestions/'+code_id+'/evidence').json()
        updated=p.call('Save SOAP amendment',lambda:client.patch('/api/notes/'+note_id,json={'soap':{'subjective':'Patient reports cough for three days.','objective':'Not documented.','assessment':'Not documented.','plan':'Not documented.'},'change_reason':'Fictional QA amendment'}))
        p.check('Amendment saved',200,updated.status_code);source=client.get('/api/code-suggestions/'+code_id+'/evidence').json();p.check('Old source stale',True,source['stale']);p.check('Original source unchanged',old_source['claims'],source['claims']);p.check('Old code approval blocked',409,client.post('/api/code-suggestions/'+code_id+'/approve').status_code)
        fresh=p.call('Generate for amended version',lambda:client.post('/api/notes/'+note_id+'/code-suggestions'))
        p.check('Current generation succeeds',200,fresh.status_code);p.check('New source version',c.note_repository.get(note_id).current_version_id,fresh.json()['suggestions'][0]['note_version_id'])
    finally:
        fixture.close()


def run_live(case_id, p, root):
    from app.services.demo_call_service import DemoCallService
    from app.services.booking_flow import BookingFlow
    if case_id in {'live-correction','live-uncertainty'}:
        service=DemoCallService(groq_api_key='',groq_llm_model='',openrouter_api_key=os.environ['OPENROUTER_API_KEY'])
        state={'current':'age','step':'confirm','pending':{'key':'age','ur':'22','en':'22'}} if case_id=='live-correction' else {'current':'phone'}
        text='نہیں، میری عمر 23 سال ہے' if case_id=='live-correction' else 'مجھے اپنا نمبر یاد نہیں'
        result=p.call('OpenRouter text extraction',lambda:service._extract(BookingFlow(state),text))
        p.check('Provider completed without fallback',False,result.get('_process_metadata',{}).get('fallback',True))
        if case_id=='live-correction':p.check('Corrected age','23',result.get('fields',{}).get('age',{}).get('en'))
        else:p.check('No invented phone',False,bool(result.get('fields',{}).get('phone')))
        p.steps.append({'label':'Provider interpretation','data':{'fields':result.get('fields',{}),'interpretation':result.get('interpretation',{}),'method':result.get('_process_metadata',{})}});return
    fixture=Clinic(root,'live_text')
    try:
        fixture.ready();fixture.checkpoint();result=p.call('Real SOAP provider and saved draft',fixture.generate)
        p.check('SOAP saved',200,result.status_code)
        if result.status_code==200:
            note=result.json()['note'];soap=note['soap'];subjective=soap['subjective'].casefold()
            p.check('Stated symptom retained',True,'cough' in subjective)
            objective_rows=[claim for claim in soap['evidence_report']['claims'] if claim['section']=='objective']
            p.check('Objective recognized as undocumented',True,bool(objective_rows) and all(claim['status']=='missing' for claim in objective_rows))
            version=fixture.c.note_repository.get_version(fixture.c.note_repository.get(note['note_id']).current_version_id);known={'U1'}
            claims=[claim for section in ('subjective','objective','assessment','plan') for claim in getattr(version.soap,section)]
            p.check('Source IDs belong to supplied conversation',True,all(set(claim.evidence_ids)<=known for claim in claims))
            trace=fixture.c.process_trace.latest(fixture.visit.encounter.encounter_id,fixture.patient.patient_id)
            artifacts=[event.get('artifact',{}) for event in trace['events'] if event['stage']=='draft' and event['status']=='complete']
            mode=artifacts[-1].get('generation_mode') if artifacts else None
            p.check('Model result, not fallback',True,mode in {'MODEL_VALIDATED','MODEL_SALVAGED'})
            p.steps.append({'label':'Fictional saved SOAP','data':{'soap':soap,'generation_mode':mode}})
    finally:fixture.close()


def main():
    mode=sys.argv[1];root=Path(sys.argv[2]).resolve()
    if mode not in {'synthetic','live_text'}:raise ValueError('Unsupported mode')
    with contextlib.redirect_stdout(sys.stderr):
        bootstrap(root,mode)
        for index,scenario in enumerate(catalog(mode)):
            emit({'type':'case_started','id':scenario['id']})
            probe=Probe();started=time.perf_counter();status='ERROR';error=None
            try:
                (run_live if mode=='live_text' else run_case)(scenario['id'],probe,root/str(index))
                status='PASSED' if probe.checks and all(item['status']=='PASSED' for item in probe.checks) else 'FAILED'
            except Exception as exc:
                # Provider exceptions can contain credentials/URLs. Report only
                # bounded class/code; expected/actual checks remain inspectable.
                error={'type':type(exc).__name__,'code':str(getattr(exc,'code','SCENARIO_ERROR'))[:64],
                       'message':'Scenario could not finish. Inspect the completed checks and retry.'}
            emit({'type':'case_finished','id':scenario['id'],'status':status,'checks':probe.checks,
                  'steps':probe.steps,'duration_ms':round((time.perf_counter()-started)*1000,2),'error':error})
        emit({'type':'finished'})


if __name__=='__main__':main()
