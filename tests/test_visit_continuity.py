from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi.testclient import TestClient
from app.main import create_app
from medflow.domain.enums import AppointmentStatus, EncounterStatus, NoteStatus, WorkflowState, SummaryLanguage
from medflow.domain.models import ClinicalClaim, SOAPNote, SOAPNoteVersion, StructuredSOAP
from medflow.orchestration import WorkflowAction
from security_guardrails import Actor
from tests import test_consultation_websocket as fixtures
from tests import test_clinic_extensions as summary_fixtures


class VisitContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        helper = fixtures.ConsultationWebSocketTests()
        settings, self.setup, self.patient, self.user, self.actor, self.context = helper._ready_context(Path(self.temp.name))
        self.app = create_app(settings)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.client.post('/api/auth/login', json={'email': 'websocket@example.test', 'password': 'SyntheticPass123!'})

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def _approved_note(self):
        c = self.app.state.container
        note_id = 'NOTE-CONTINUITY-001'
        version = c.note_repository.save_version(SOAPNoteVersion(
            note_version_id='NV-CONTINUITY-001', note_id=note_id, version_number=1,
            status=NoteStatus.APPROVED_BY_DOCTOR,
            soap=StructuredSOAP(subjective=[ClinicalClaim(claim_id='CLM-CONTINUITY-001', text='Synthetic doctor-approved statement.')]),
            created_by_actor_id=str(self.user.user_id),
        ))
        c.note_repository.save(SOAPNote(note_id=note_id, patient_id=self.patient.patient_id,
            encounter_id=self.context.encounter.encounter_id, current_version_id=version.note_version_id,
            state=NoteStatus.APPROVED_BY_DOCTOR, approved_by_doctor_id=str(self.user.user_id)))
        workflow = c.workflow_repository.get(self.context.workflow.workflow_id)
        c.workflow_repository.save(workflow.model_copy(update={'state':WorkflowState.NOTE_APPROVED,'note_id':note_id,'version':workflow.version+1}), expected_version=workflow.version)
        appointment = c.appointment_repository.get(workflow.appointment_id)
        c.appointment_repository.save(appointment.model_copy(update={'status':AppointmentStatus.IN_PROGRESS,'version':appointment.version+1}))
        return note_id

    def test_opening_patient_context_does_not_advance_or_create_visits(self):
        c = self.app.state.container
        before = c.workflow_repository.get(self.context.workflow.workflow_id).model_dump()
        appointment = c.appointment_repository.get(self.context.appointment.appointment_id).model_dump()
        for _ in range(2):
            response = self.client.get('/api/workflows/context/'+self.patient.patient_id)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['workflow']['workflow_id'], self.context.workflow.workflow_id)
        self.assertEqual(c.workflow_repository.get(self.context.workflow.workflow_id).model_dump(), before)
        self.assertEqual(c.appointment_repository.get(self.context.appointment.appointment_id).model_dump(), appointment)
        self.assertEqual(len(c.workflow_repository.list(patient_id=self.patient.patient_id)), 1)

    def test_context_denies_other_doctor_and_unknown_note(self):
        response = self.client.get('/api/workflows/context/'+self.patient.patient_id+'?note_id=NOTE-OTHER')
        self.assertEqual(response.status_code,404)
        c = self.app.state.container
        c.auth_repository.create_doctor('Other doctor','other@example.test','SyntheticPass123!')
        self.client.post('/api/auth/login',json={'email':'other@example.test','password':'SyntheticPass123!'})
        self.assertEqual(self.client.get('/api/workflows/context/'+self.patient.patient_id).status_code,403)

    def test_legacy_shortcut_is_unavailable_outside_enabled_development(self):
        self.assertEqual(self.client.post('/api/workflows/prepare-consultation',json={'patient_id':self.patient.patient_id}).status_code,404)

    def test_completing_unapproved_visit_is_rejected_without_mutation(self):
        workflow_id=self.context.workflow.workflow_id
        self.assertEqual(self.client.post('/api/workflows/'+workflow_id+'/complete').status_code,409)
        self.assertEqual(self.app.state.container.workflow_repository.get(workflow_id).state,WorkflowState.CONSULTATION_READY)

    def test_completed_visit_reopens_same_note_and_repeated_completion_is_idempotent(self):
        note_id=self._approved_note()
        workflow_id=self.context.workflow.workflow_id
        for _ in range(2):
            response=self.client.post('/api/workflows/'+workflow_id+'/complete')
            self.assertEqual(response.status_code,200,response.text)
            payload=response.json()
            self.assertEqual(payload['workflow']['state'],'ENCOUNTER_COMPLETED')
            self.assertEqual(payload['appointment']['status'],'COMPLETED')
            self.assertEqual(payload['encounter']['status'],'COMPLETED')
        reopened=self.client.get('/api/workflows/context/'+self.patient.patient_id+'?note_id='+note_id).json()
        self.assertEqual(reopened['workflow']['workflow_id'],workflow_id)
        self.assertEqual(reopened['note']['note_id'],note_id)

    def test_a_stale_patient_summary_is_not_returned_after_note_amendment(self):
        helper=summary_fixtures.ClinicExtensionTests()
        helper.setUp()
        try:
            note,_=helper._note('NOTE-SUMMARY-CONTINUITY',NoteStatus.APPROVED_BY_DOCTOR,'Synthetic approved content')
            service=helper.container.after_visit_summary_service
            service.generate(note_id=note.note_id,language=SummaryLanguage.ENGLISH,actor=helper.doctor)
            self.assertIsNotNone(service.get_for_encounter(encounter_id=note.encounter_id,actor=helper.doctor))
            helper.container.note_lifecycle_service.edit_legacy_sections(note.note_id,sections={'subjective':'Synthetic amended content.','objective':'Not documented.','assessment':'Not documented.','plan':'Not documented.'},actor=helper.doctor,change_reason='Synthetic amendment')
            self.assertIsNone(service.get_for_encounter(encounter_id=note.encounter_id,actor=helper.doctor))
        finally:
            helper.tearDown()

    def test_failed_documentation_retry_preserves_encounter_and_permissions(self):
        c=self.app.state.container
        workflow_id=self.context.workflow.workflow_id
        response=self.client.post('/api/consents',json={'encounter_id':self.context.encounter.encounter_id,'audio_recording':True,'ai_transcription':True,'ai_documentation':True,'audio_retention':False,'consent_text_version':'CONSENT-V1','capture_method':'DOCTOR_ATTESTATION'})
        self.assertEqual(response.status_code,200,response.text)
        c.lifecycle_service.start_consultation(workflow_id,actor=self.actor)
        c.lifecycle_service.start_documentation(workflow_id,actor=self.actor)
        c.workflow_orchestrator.perform_action(workflow_id,WorkflowAction.MARK_FAILED,actor=Actor.system('system_agent',self.patient.patient_id),error_code='SYNTHETIC_FAILURE')
        response=self.client.post('/api/workflows/'+workflow_id+'/retry-documentation')
        self.assertEqual(response.status_code,200,response.text)
        payload=response.json()
        self.assertEqual(payload['workflow']['state'],'CONSULTATION_ACTIVE')
        self.assertEqual(payload['encounter']['encounter_id'],self.context.encounter.encounter_id)
        self.assertEqual(payload['appointment']['appointment_id'],self.context.appointment.appointment_id)
        self.assertTrue(any(x['consent_type']=='AI_DOCUMENTATION' and x['decision'] for x in payload['consents']))
        self.assertEqual(self.client.post('/api/workflows/'+workflow_id+'/retry-documentation').status_code,409)
        self.assertEqual(len(c.workflow_repository.list(patient_id=self.patient.patient_id)),1)

    def test_retry_rejects_approved_record_and_other_doctor(self):
        self._approved_note()
        workflow_id=self.context.workflow.workflow_id
        self.assertEqual(self.client.post('/api/workflows/'+workflow_id+'/retry-documentation').status_code,409)
        c=self.app.state.container
        c.auth_repository.create_doctor('Other doctor','other@example.test','SyntheticPass123!')
        self.client.post('/api/auth/login',json={'email':'other@example.test','password':'SyntheticPass123!'})
        self.assertEqual(self.client.post('/api/workflows/'+workflow_id+'/retry-documentation').status_code,403)

    def test_transcription_failure_and_silence_leave_a_recoverable_bound_visit(self):
        workflow_id=self.context.workflow.workflow_id
        self.client.post('/api/consents',json={'encounter_id':self.context.encounter.encounter_id,'audio_recording':True,'ai_transcription':True,'ai_documentation':True,'audio_retention':False,'consent_text_version':'CONSENT-V1','capture_method':'DOCTOR_ATTESTATION'})
        for failure in (RuntimeError('Synthetic transcription failure'),None):
            with patch.object(self.app.state.container.documentation_service,'transcribe',side_effect=failure,return_value=''):
                with self.client.websocket_connect('/ws') as socket:
                    socket.send_json({'type':'start','patient_id':self.patient.patient_id,'workflow_id':workflow_id,'encounter_id':self.context.encounter.encounter_id,'capture_id':'capture-continuity-test','sample_rate':16000})
                    self.assertEqual(socket.receive_json()['type'],'recording_started')
                    socket.send_bytes(bytes(32000));socket.send_json({'type':'stop'})
                    while True:
                        event=socket.receive_json()
                        self.assertEqual(event['patient_id'],self.patient.patient_id)
                        self.assertEqual(event['capture_id'],'capture-continuity-test')
                        if event['type']=='error':break
            payload=self.client.get('/api/workflows/context/'+self.patient.patient_id).json()
            self.assertEqual(payload['workflow']['state'],'FAILED')
            self.assertEqual(payload['workflow']['resume_state'],'DOCUMENTATION_PROCESSING')
            self.assertIsNone(payload['note'])
            self.assertEqual(self.client.post('/api/workflows/'+workflow_id+'/retry-documentation').status_code,200)
