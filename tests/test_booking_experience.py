"""Exact catalog selection and atomic staff attendance records."""
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import create_app
from tests.test_central_app_auth import _settings
from app.services.booking_flow import BookingFlow

class BookingExperienceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  with patch('app.services.inbound_call_service.FastUrduTTS.warmup'):
   self.app=create_app(_settings(Path(self.tmp.name)))
   self.client=TestClient(self.app);self.client.__enter__()
  self.addCleanup(self.client.__exit__,None,None,None)
  self.c=self.app.state.container
  self.user=self.c.auth_repository.create_doctor('Dr. Calendar QA','calendar@example.test','SyntheticQA123!')
  self.client.post('/api/auth/login',json={'email':'calendar@example.test','password':'SyntheticQA123!'})
  self.practitioner=self.c.clinic_repository.get_practitioner(self.user.practitioner_id)
 def intake_booking(self,suffix='one'):
  token='calendar-fictional-intake-token-123456-'+suffix
  r=self.client.post('/api/desk/intakes',json={'name':'Fictional Calendar Patient','age_text':'23','phone_number':'03000000001','first_visit':'Yes','past_medical_history':'None','current_complaint':'Fictional concern','intake_token':token,'revision':1,'confirmed_revision':1})
  self.assertEqual(r.status_code,200,r.text);saved=r.json()
  slots=self.client.get('/api/desk/availability',params={'practitioner_id':self.user.practitioner_id,'visit_type_id':'VISIT-NEW','days':14,'limit':30}).json()['slots']
  r=self.client.post('/api/desk/bookings',json={'patient_id':saved['patient_id'],'workflow_id':saved['workflow_id'],'department_id':self.practitioner['department_id'],'practitioner_id':self.user.practitioner_id,'visit_type_id':'VISIT-NEW','start_at':slots[0]['start_at'],'idempotency_key':token+'-booking','intake_token':token,'revision':1})
  self.assertEqual(r.status_code,200,r.text)
  return saved,r.json()['appointment'],slots
 def prepare(self,a):
  r=self.client.post('/api/appointments/'+a['appointment_id']+'/attendance',json={'expected_version':a['version']});self.assertEqual(r.status_code,200,r.text);return r.json()
 def response(self,a,q,kind,**extra):
  return self.client.post('/api/appointments/'+a['appointment_id']+'/attendance/respond',json={'request_id':q['request_id'],'response':kind,**extra})
 def test_staff_details_review_has_no_otp_or_attendance_side_effect(self):
  saved,a,_=self.intake_booking();workflow=self.c.workflow_repository.get(saved['workflow_id'])
  payload={'patient_id':saved['patient_id'],'workflow_id':workflow.workflow_id,'expected_version':workflow.version,'details_checked':False}
  self.assertEqual(self.client.post('/api/verification/review-details',json=payload).status_code,400)
  payload['details_checked']=True
  r=self.client.post('/api/verification/review-details',json=payload);self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()['method'],'MANUAL_STAFF_REVIEW');self.assertEqual(r.json()['phone_last_four'],'')
  self.assertIsNone(self.c.attendance_service.latest(a['appointment_id']))
  context=self.client.get('/api/workflows/context/'+saved['patient_id']).json()
  self.assertEqual(context['details_verification']['method'],'MANUAL_STAFF_REVIEW')
  self.assertEqual(self.client.post('/api/workflows/'+workflow.workflow_id+'/complete-intake').status_code,200)
 def test_attendance_confirmation_is_durable_idempotent_and_separate(self):
  saved,a,_=self.intake_booking();q=self.prepare(a)
  self.assertEqual(q['delivery'],'PREPARED');self.assertEqual(self.prepare(a)['request_id'],q['request_id'])
  r=self.response(a,q,'ATTEND');self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()['response_source'],'STAFF_RECORDED')
  self.assertEqual(self.response(a,q,'ATTEND').json(),r.json())
  self.assertEqual(self.c.workflow_repository.get(saved['workflow_id']).state.value,'PATIENT_UNVERIFIED')
  self.assertEqual(self.c.appointment_repository.get(a['appointment_id']).status.value,'REQUESTED')
  self.assertEqual(self.client.get('/api/appointments/doctor-queue').json()['appointments'][0]['attendance']['status'],'CONFIRMED')
  workflow=self.c.workflow_repository.get(saved['workflow_id'])
  self.client.post('/api/verification/review-details',json={'patient_id':saved['patient_id'],'workflow_id':workflow.workflow_id,'expected_version':workflow.version,'details_checked':True})
  self.client.post('/api/workflows/'+workflow.workflow_id+'/complete-intake')
  self.assertFalse(self.c.attendance_service.latest(a['appointment_id'])['stale'])
 def test_occupied_replacement_keeps_original_slot_and_pending_response(self):
  _,a,slots=self.intake_booking();q=self.prepare(a)
  _,other,_=self.intake_booking('other')
  self.assertNotEqual(a['start_at'],other['start_at'])
  r=self.response(a,q,'CHANGE_TIME',new_start_at=other['start_at'])
  self.assertEqual(r.status_code,409,r.text)
  self.assertEqual(self.c.appointment_repository.get(a['appointment_id']).start_at.isoformat(),a['start_at'])
  self.assertEqual(self.c.attendance_service.latest(a['appointment_id'])['status'],'AWAITING_RESPONSE')
 def test_replacement_and_receipt_commit_together_and_release_old_slot(self):
  _,a,slots=self.intake_booking();q=self.prepare(a)
  alternative=slots[1]['start_at']
  with patch.object(self.c.audit_service,'record',side_effect=RuntimeError('synthetic audit write failure')):
   with self.assertRaises(RuntimeError):self.response(a,q,'CHANGE_TIME',new_start_at=alternative)
  self.assertEqual(self.c.appointment_repository.get(a['appointment_id']).start_at.isoformat(),a['start_at'])
  self.assertEqual(self.c.attendance_service.latest(a['appointment_id'])['status'],'AWAITING_RESPONSE')
  r=self.response(a,q,'CHANGE_TIME',new_start_at=alternative);self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(self.c.appointment_repository.get(a['appointment_id']).start_at.isoformat(),alternative)
  self.assertEqual(self.response(a,q,'CHANGE_TIME',new_start_at=alternative).json(),r.json())
 def test_cancel_updates_workflow_and_rejects_other_doctor(self):
  saved,a,_=self.intake_booking();q=self.prepare(a)
  other=self.c.auth_repository.create_doctor('Other QA','other-calendar@example.test','SyntheticQA123!')
  self.client.post('/api/auth/login',json={'email':'other-calendar@example.test','password':'SyntheticQA123!'})
  self.assertEqual(self.response(a,q,'ATTEND').status_code,404)
  self.client.post('/api/auth/login',json={'email':'calendar@example.test','password':'SyntheticQA123!'})
  r=self.response(a,q,'CANCEL');self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(self.c.workflow_repository.get(saved['workflow_id']).state.value,'CANCELLED')
  self.assertEqual(self.c.appointment_repository.get(a['appointment_id']).status.value,'CANCELLED')
 def test_stale_request_cannot_confirm_a_changed_appointment(self):
  _,a,slots=self.intake_booking();q=self.prepare(a)
  from app.dependencies import actor_for_user
  self.c.appointment_service.reschedule(a['appointment_id'],new_start_at=datetime.fromisoformat(slots[1]['start_at']),idempotency_key='outside-change-12345',actor=actor_for_user(self.c,self.user,a['patient_id']))
  self.assertEqual(self.response(a,q,'ATTEND').status_code,409)
  self.assertTrue(self.c.attendance_service.latest(a['appointment_id'])['stale'])
 def test_card_selection_uses_exact_ids_no_model_and_rejects_stale_choices(self):
  values={k:{'ur':v,'en':v} for k,v in {'name':'Fictional QA','age':'23','phone':'03000000001','first_visit':'Yes','history':'None','complaint':'Fictional concern'}.items()}
  history=[BookingFlow({'current':'department','values':values}).state_message()]
  self.c.demo_call_service._extract=lambda *a: (_ for _ in ()).throw(AssertionError('Unexpected model call'))
  def select(history,field,value):
   flow=BookingFlow.from_history(history)
   return self.client.post('/api/desk/demo-calls/select',json={'history':history,'field':field,'value':value,'revision':flow.evidence_turn})
  r=select(history,'department',self.practitioner['department_id']);self.assertEqual(r.status_code,200,r.text)
  history=r.json()['history'];self.assertEqual(r.json()['process']['current_field'],'doctor')
  r=select(history,'doctor',self.user.practitioner_id);self.assertEqual(r.status_code,200,r.text);history=r.json()['history']
  self.assertEqual(r.json()['process']['values']['doctor']['practitioner_id'],self.user.practitioner_id)
  choices=self.client.post('/api/desk/demo-calls/choices',json={'history':history}).json()
  self.assertTrue(choices['slots']);slot=choices['slots'][0]['start_at']
  r=select(history,'time',slot);self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()['process']['pending']['iso'],slot)
  r=self.client.post('/api/desk/demo-calls/select',json={'history':r.json()['history'],'field':'time','value':slot,'revision':0});self.assertEqual(r.status_code,409)
  r=select(history,'department',self.practitioner['department_id']);self.assertEqual(r.status_code,200,r.text)
  self.assertNotIn('doctor',r.json()['process']['values']);self.assertNotIn('time',r.json()['process']['values'])
