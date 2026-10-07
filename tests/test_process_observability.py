import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from medflow.domain.enums import ConsentType, ClaimSupportStatus
from medflow.domain.models import TranscriptRecord, TranscriptUtterance
from security_guardrails import SecureLLMGateway, set_gateway
from tests import test_consultation_websocket as ws_fixture
from app.main import create_app
from app.services.booking_flow import BookingFlow


class ProcessObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        settings, self.setup, self.patient, self.user, self.actor, self.context = ws_fixture.ConsultationWebSocketTests()._ready_context(Path(self.temp.name))
        self.setup.consent_service.capture_bundle(encounter_id=self.context.encounter.encounter_id,
            decisions={ConsentType.AUDIO_RECORDING:True,ConsentType.AI_TRANSCRIPTION:True,ConsentType.AI_DOCUMENTATION:True,ConsentType.AUDIO_RETENTION:False},
            consent_text_version='CONSENT-V1',capture_method='SYNTHETIC_TEST',actor=self.actor)
        set_gateway(SecureLLMGateway(provider='mock'))
        self.client=TestClient(create_app(settings));self.client.__enter__()
        self.client.post('/api/auth/login',json={'email':'websocket@example.test','password':'SyntheticPass123!'})
        self.c=self.client.app.state.container

    def tearDown(self):
        self.client.__exit__(None,None,None);set_gateway(None);self.temp.cleanup()

    def capture(self):
        with self.client.websocket_connect('/ws') as ws:
            ws.send_json({'type':'start','auto_soap':True,'patient_id':self.patient.patient_id,'workflow_id':self.context.workflow.workflow_id,'encounter_id':self.context.encounter.encounter_id,'capture_id':'SYNTHETIC-TRACE','sample_rate':16000})
            self.assertEqual(ws.receive_json()['type'],'recording_started')
            ws.send_bytes(bytes(64000));ws.send_json({'type':'stop'})
            events=[]
            while True:
                item=ws.receive_json()
                if item['type']=='process_event':events.append(item)
                if item['type'] in {'soap_note','error'}:return item,events

    def test_durable_trace_and_patient_access(self):
        note,events=self.capture();self.assertEqual(note['type'],'soap_note')
        completed=[e for e in events if e['status']=='complete']
        self.assertEqual([e['stage'] for e in completed],['audio','speech','roles','translation','draft','validation'])
        self.assertEqual([e['sequence'] for e in events],list(range(1,len(events)+1)))
        self.assertTrue(all(e['duration_ms']>=0 for e in completed))
        context=self.client.get('/api/workflows/context/'+self.patient.patient_id).json()
        self.assertEqual(len(context['process_trace']['events']),len(events))
        self.assertIsNone(completed[2]['artifact']['distinct_voices'])
        self.c.auth_repository.create_doctor('Other','other@test.example','OtherPass123!')
        self.client.post('/api/auth/login',json={'email':'other@test.example','password':'OtherPass123!'})
        self.assertEqual(self.client.get('/api/workflows/context/'+self.patient.patient_id).status_code,403)

    def test_failure_is_persisted_at_actual_stage(self):
        with patch.object(self.c.documentation_service,'transcribe',side_effect=RuntimeError('test provider failure')):
            result,events=self.capture()
        self.assertEqual(result['type'],'error')
        self.assertEqual(events[-1]['stage'],'speech');self.assertEqual(events[-1]['status'],'failed')
        saved=self.client.get('/api/workflows/context/'+self.patient.patient_id).json()['process_trace']
        self.assertEqual(saved['events'][-1]['status'],'failed')
        self.assertNotIn('test provider failure',json.dumps(saved))

    def test_claim_mapping_does_not_borrow_all_evidence(self):
        transcript=TranscriptRecord(transcript_id='TRN-SYNTH',patient_id=self.patient.patient_id,encounter_id=self.context.encounter.encounter_id,utterances=[TranscriptUtterance(transcript_id='TRN-SYNTH',utterance_id='U1',original_text='Fever for three days.'),TranscriptUtterance(transcript_id='TRN-SYNTH',utterance_id='U2',original_text='Return tomorrow.')])
        soap={'subjective':'Fever for three days.','plan':'Return tomorrow.','evidence':[{'utterance_id':'U1'},{'utterance_id':'U2'}], 'claim_sources':{'subjective':[{'text':'Fever for three days.','evidence_ids':['U1']}],'plan':[{'text':'Return tomorrow.','evidence_ids':['U2']}]}}
        mapped=self.c.documentation_service.build_structured_soap('NOTE-SYNTH',soap,transcript)
        self.assertEqual(mapped.subjective[0].evidence_ids,['U1']);self.assertEqual(mapped.plan[0].evidence_ids,['U2'])
        self.assertEqual(mapped.objective[0].evidence_ids,[])
        self.assertEqual(mapped.subjective[0].status,ClaimSupportStatus.REVIEW_REQUIRED)
        soap['claim_sources']['subjective'][0]['evidence_ids']=['U999']
        with self.assertRaisesRegex(Exception,'unknown transcript evidence'):
            self.c.documentation_service.build_structured_soap('NOTE-SYNTH',soap,transcript)

    def test_role_revision_preserves_old_transcript_and_note_identity(self):
        result,_=self.capture();note_id=result['note_id']
        old=self.client.get('/api/notes/'+note_id).json();old_transcript=self.c.note_repository.get_version(self.c.note_repository.get(note_id).current_version_id).transcript_id
        turn=old['transcript'][0]['utterance_id']
        response=self.client.post('/api/notes/'+note_id+'/correct-roles',json={'expected_version':old['version'],'corrections':[{'utterance_id':turn,'speaker':'ATTENDANT','speaker_relation':'Mother'}]})
        self.assertEqual(response.status_code,200,response.text)
        revised=response.json();self.assertEqual(revised['note_id'],note_id);self.assertEqual(revised['version'],old['version']+1)
        self.assertEqual(revised['transcript'][0]['speaker'],'Attendant')
        report=revised['soap']['evidence_report']
        self.assertEqual(report['version'],revised['version'])
        self.assertEqual(report['state'],'AI_DRAFT')
        self.assertIsNone(report['approval'])
        self.assertTrue(all(source['speaker']=='ATTENDANT' for row in report['claims'] for source in row['sources'] if source['utterance_id']==turn))
        self.assertNotEqual(self.c.note_repository.get_version(self.c.note_repository.get(note_id).current_version_id).transcript_id,old_transcript)
        self.assertEqual(self.c.transcript_repository.get(old_transcript).utterances[0].speaker.value.upper(),old['transcript'][0]['speaker'].upper())
        stale=self.client.post('/api/notes/'+note_id+'/correct-roles',json={'expected_version':old['version'],'corrections':[{'utterance_id':turn,'speaker':'PATIENT'}]})
        self.assertNotEqual(stale.status_code,200)

    def test_booking_state_reports_pending_not_saved(self):
        flow=BookingFlow();view=flow.process_state()
        self.assertEqual(view['current_field'],'name');self.assertFalse(view['saved']);self.assertFalse(view['confirmed'])

    def test_phone_booking_uses_shared_flow_and_persists_real_handoff(self):
        from app.services.inbound_call_service import LiveCallSession
        from tests import test_demo_call_finish as fixture
        helper=fixture.DemoCallFinishTests();helper.setUp()
        self.addCleanup(helper.doCleanups)
        slot=helper._first_open_slot()
        # Save at the phone entry point with the same confirmed state as a browser call.
        history=helper._full_call(slot)
        phone=helper.client.app.state.container.inbound_call_service
        session=LiveCallSession(call_control_id='SYNTHETIC-PHONE',from_number='03000000000',to_number='03000000001')
        session.booking_history=history
        phone._sessions[session.call_control_id]=session
        helper.service._extract=lambda flow,text:fixture.YES
        reply=phone._booking_reply(session.call_control_id,'yes')
        self.assertTrue(reply)
        self.assertTrue(session.booking_result['saved'])
        self.assertEqual(session.booking_result['booking']['status'],'REQUESTED')
        self.assertTrue(session.booking_result['booking']['appointment']['appointment_id'])
        first=session.booking_result['booking']['appointment']['appointment_id']
        phone._booking_reply(session.call_control_id,'yes')
        self.assertEqual(session.booking_result['booking']['appointment']['appointment_id'],first)

    def test_short_voice_answers_are_not_discarded_as_garbled(self):
        from app.services.demo_stt import looks_garbled_urdu
        for reply in ('جی', 'ہاں', 'نہیں', 'yes', 'no', '22', '۲۲', 'احمد', 'Ahmed Khan'):
            with self.subTest(reply=reply):
                self.assertFalse(looks_garbled_urdu(reply))
        self.assertTrue(looks_garbled_urdu(''))
        self.assertTrue(looks_garbled_urdu('...'))
