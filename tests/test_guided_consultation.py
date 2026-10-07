"""Guided mode holds SOAP until review and retains exact visit/revision on retries."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import create_app
from medflow.domain.enums import ConsentType, WorkflowState
from medflow.orchestration import WorkflowAction
from security_guardrails import SecureLLMGateway, set_gateway
from tests import test_consultation_websocket as fixture


class GuidedConsultationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        settings,setup,self.patient,self.user,self.actor,self.visit=fixture.ConsultationWebSocketTests()._ready_context(Path(self.temp.name))
        setup.consent_service.capture_bundle(encounter_id=self.visit.encounter.encounter_id,decisions={kind:kind!=ConsentType.AUDIO_RETENTION for kind in ConsentType},consent_text_version='CONSENT-V1',capture_method='SYNTHETIC_TEST',actor=self.actor)
        set_gateway(SecureLLMGateway(provider='mock'))
        self.client=TestClient(create_app(settings));self.client.__enter__()
        self.client.post('/api/auth/login',json={'email':'websocket@example.test','password':'SyntheticPass123!'})
        self.c=self.client.app.state.container
        self.path='/api/workflows/'+self.visit.workflow.workflow_id

    def tearDown(self):
        self.client.__exit__(None,None,None);set_gateway(None);self.temp.cleanup()

    def capture(self,auto=False):
        with self.client.websocket_connect('/ws') as ws:
            ws.send_json({'type':'start','patient_id':self.patient.patient_id,'workflow_id':self.visit.workflow.workflow_id,'encounter_id':self.visit.encounter.encounter_id,'capture_id':'SYNTHETIC-GUIDED','sample_rate':16000,'auto_soap':auto})
            self.assertEqual(ws.receive_json()['type'],'recording_started')
            ws.send_bytes(bytes(64000));ws.send_json({'type':'stop'})
            events=[]
            while True:
                item=ws.receive_json()
                if item['type']=='process_event':events.append(item)
                if item['type'] in {'conversation_ready','soap_note','error'}:return item,events

    def context(self):
        response=self.client.get('/api/workflows/context/'+self.patient.patient_id)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def revision(self):
        review=self.context()['conversation_review']
        return {'expected_revision':review['revision'],'transcript_id':review['transcript_id']}

    def test_default_capture_stops_at_saved_transcript_without_soap(self):
        with patch.object(self.c.documentation_service,'generate_draft',wraps=self.c.documentation_service.generate_draft) as generated:
            result,events=self.capture()
            self.assertEqual(result['type'],'conversation_ready')
            self.assertEqual(generated.call_count,0)
            context=self.context()
            self.assertEqual(context['workflow']['state'],'TRANSCRIPT_REVIEW')
            self.assertIsNone(context['note'])
            self.assertEqual([e['stage'] for e in events if e['status']=='complete'],['audio','speech','roles','translation'])
            self.assertEqual(context['conversation_review']['transcript_id'],result['conversation_review']['transcript_id'])
            self.assertEqual(context['encounter']['encounter_id'],self.visit.encounter.encounter_id)
            body=self.revision()
            first=self.client.post(self.path+'/generate-soap',json=body)
            self.assertEqual(first.status_code,200,first.text)
            second=self.client.post(self.path+'/generate-soap',json=body)
            self.assertEqual(second.status_code,200,second.text)
            self.assertEqual(first.json()['note']['note_id'],second.json()['note']['note_id'])
            self.assertEqual(generated.call_count,1)

    def test_corrections_saved_before_generation_and_old_revision_preserved(self):
        self.capture();body=self.revision()
        source=self.c.transcript_repository.get(body['transcript_id'])
        turn=source.utterances[0]
        corrected={**body,'corrections':[{'utterance_id':turn.utterance_id,'speaker':'PATIENT','original_text':'Synthetic corrected original wording.','clinical_english':'Synthetic corrected patient statement.'}]}
        response=self.client.patch(self.path+'/conversation',json=corrected)
        self.assertEqual(response.status_code,200,response.text)
        review=response.json()['conversation_review']
        self.assertEqual(review['revision'],2)
        self.assertNotEqual(review['transcript_id'],body['transcript_id'])
        self.assertEqual(review['utterances'][0]['original_text'],'Synthetic corrected original wording.')
        self.assertEqual(review['utterances'][0]['clinical_english'],'Synthetic corrected patient statement.')
        self.assertEqual(self.c.transcript_repository.get(body['transcript_id']).model_dump(),source.model_dump())
        self.assertIsNone(response.json()['note'])
        self.assertEqual(self.client.post(self.path+'/generate-soap',json=body).status_code,409)
        self.assertEqual(self.client.patch(self.path+'/conversation',json=corrected).status_code,409)
        draft=self.client.post(self.path+'/generate-soap',json=self.revision()).json()['note']
        self.assertEqual(draft['transcript'][0]['clinical_english'],'Synthetic corrected patient statement.')
        self.assertEqual(self.c.note_repository.get_version(self.c.note_repository.get(draft['note_id']).current_version_id).transcript_id,review['transcript_id'])

    def test_generation_failure_retries_from_same_transcript(self):
        self.capture();body=self.revision()
        with patch.object(self.c.documentation_service,'generate_draft',side_effect=RuntimeError('Synthetic generation failure')):
            failed=self.client.post(self.path+'/generate-soap',json=body)
        self.assertEqual(failed.status_code,503,failed.text)
        context=self.context()
        self.assertEqual(context['workflow']['state'],'TRANSCRIPT_REVIEW')
        self.assertEqual(context['conversation_review']['status'],'SOAP_FAILED')
        self.assertEqual(context['conversation_review']['transcript_id'],body['transcript_id'])
        response=self.client.post(self.path+'/generate-soap',json=body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['encounter']['encounter_id'],self.visit.encounter.encounter_id)

    def test_concurrent_generation_has_one_provider_request(self):
        self.capture();body=self.revision();entered=threading.Event();release=threading.Event()
        original=self.c.documentation_service.generate_draft
        def blocking(**kwargs):
            entered.set();release.wait(10);return original(**kwargs)
        results=[]
        with patch.object(self.c.documentation_service,'generate_draft',side_effect=blocking) as generated:
            worker=threading.Thread(target=lambda:results.append(self.client.post(self.path+'/generate-soap',json=body)))
            worker.start();self.assertTrue(entered.wait(5))
            try:
                second=self.client.post(self.path+'/generate-soap',json=body)
                self.assertEqual(second.status_code,409,second.text)
                self.assertEqual(self.context()['conversation_review']['status'],'GENERATING')
            finally:release.set();worker.join(10)
            self.assertEqual(results[0].status_code,200,results[0].text)
            self.assertEqual(generated.call_count,1)

    def test_translation_failure_can_retry_saved_original(self):
        with patch.object(self.c.documentation_service,'translate',side_effect=RuntimeError('Synthetic translation failure')):
            result,_=self.capture()
        self.assertEqual(result['type'],'error')
        context=self.context();self.assertEqual(context['conversation_review']['status'],'TRANSLATION_FAILED')
        response=self.client.post(self.path+'/retry-translation',json=self.revision())
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['workflow']['state'],'TRANSCRIPT_REVIEW')
        self.assertIsNone(response.json()['note'])

    def test_unknown_blank_and_cross_patient_corrections_are_rejected(self):
        self.capture();body=self.revision()
        unknown=self.client.patch(self.path+'/conversation',json={**body,'corrections':[{'utterance_id':'U999','speaker':'PATIENT'}]})
        self.assertEqual(unknown.status_code,400)
        blank=self.client.patch(self.path+'/conversation',json={**body,'corrections':[{'utterance_id':'U1','original_text':' '} ]})
        self.assertEqual(blank.status_code,422)
        self.c.auth_repository.create_doctor('Other','other@example.test','SyntheticPass123!')
        self.client.post('/api/auth/login',json={'email':'other@example.test','password':'SyntheticPass123!'})
        self.assertEqual(self.client.post(self.path+'/generate-soap',json=body).status_code,403)
        self.assertEqual(self.client.get('/api/workflows/context/'+self.patient.patient_id).status_code,403)

    def test_explicit_rerecord_supersedes_failed_checkpoint_without_deleting_source(self):
        with patch.object(self.c.documentation_service,'translate',side_effect=RuntimeError('Synthetic failure')):
            self.capture()
        transcript_id=self.revision()['transcript_id']
        response=self.client.post(self.path+'/retry-documentation')
        self.assertEqual(response.status_code,200,response.text)
        self.assertIsNone(response.json()['conversation_review'])
        self.assertIsNotNone(self.c.transcript_repository.get(transcript_id))
        result,_=self.capture()
        self.assertEqual(result['type'],'conversation_ready')
        self.assertNotEqual(self.revision()['transcript_id'],transcript_id)

    def test_server_restart_releases_abandoned_generation_lease(self):
        self.capture();body=self.revision()
        self.c.consultation_review._claim(self.visit.workflow.workflow_id,body['expected_revision'],body['transcript_id'],'GENERATING',{'TRANSCRIPT_REVIEW'})
        workflow=self.c.workflow_repository.get(self.visit.workflow.workflow_id)
        self.c.workflow_orchestrator.perform_action(workflow.workflow_id,WorkflowAction.GENERATE_DOCUMENTATION,actor=self.actor,expected_version=workflow.version)
        self.c.consultation_review.recover_interrupted()
        self.assertEqual(self.context()['conversation_review']['status'],'SOAP_FAILED')
        self.assertEqual(self.client.post(self.path+'/generate-soap',json=body).status_code,200)

    def test_optional_automatic_mode_still_generates(self):
        result,events=self.capture(auto=True)
        self.assertEqual(result['type'],'soap_note')
        self.assertEqual([e['stage'] for e in events if e['status']=='complete'],['audio','speech','roles','translation','draft','validation'])
        self.assertEqual(self.context()['conversation_review']['status'],'SOAP_READY')

    def test_restart_reconciles_checkpoint_and_workflow_writes(self):
        self.capture()
        workflow_id=self.visit.workflow.workflow_id
        # Crash after the workflow advanced but before the checkpoint was marked ready.
        self.c.consultation_review.store.change(workflow_id,lambda row:{**row,'status':'TRANSLATING'})
        self.c.consultation_review.recover_interrupted()
        self.assertEqual(self.context()['conversation_review']['status'],'TRANSCRIPT_REVIEW')
        # Retry translation saved its result, then crashed before advancing the workflow.
        workflow=self.c.workflow_repository.get(workflow_id)
        self.c.workflow_orchestrator.perform_action(workflow_id,WorkflowAction.GENERATE_DOCUMENTATION,actor=self.actor,expected_version=workflow.version)
        self.c.consultation_review.recover_interrupted()
        self.assertEqual(self.context()['workflow']['state'],'TRANSCRIPT_REVIEW')
        self.assertEqual(self.client.post(self.path+'/generate-soap',json=self.revision()).status_code,200)
