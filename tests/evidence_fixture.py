"""Synthetic providers and temporary database for evidence browser QA only."""
import sys,json,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.inbound_call_service import FastUrduTTS
FastUrduTTS.warmup=lambda self,phrases: None
from app.main import create_app
from tests.test_central_app_auth import _settings
from security_guardrails import SecureLLMGateway,set_gateway
root=Path(tempfile.mkdtemp(prefix='medflow-audit-'))
from dataclasses import replace
settings=replace(_settings(root),app_env="test",development_quick_start_enabled=True,receptionist_service_token="synthetic-audit-desk-token",primary_doctor_email="audit@example.test",primary_doctor_display_name="Synthetic Audit Doctor")
settings.patient_records_dir.mkdir(parents=True)
for index,complaint in [(1,'Knee pain after a fall'),(2,'Persistent cough')]:
 (settings.patient_records_dir/f'patient_audit_{index}.json').write_text(json.dumps({'name':f'Synthetic Patient {index}','age':'30','phone_number':f'0300000000{index}','first_visit':'Yes','past_medical_history':'None','current_complaint':complaint}))
qa_gateway=SecureLLMGateway(provider='mock')
qa_gateway._adapter('mock').set_response('soap_generation',{
 'subjective':'The patient provided a synthetic response during the consultation.',
 'objective':'Not documented.','assessment':'Not documented.','plan':'Not documented.',
 'visit_date':'2026-10-07','generated_by':'AI Medical Scribe','evidence':[{'utterance_id':'U1','quote':'synthetic response'}],
 'claim_sources':{'subjective':[{'text':'The patient provided a synthetic response during the consultation.','evidence_ids':['U1']}],'objective':[],'assessment':[],'plan':[]}})
set_gateway(qa_gateway)

app=create_app(settings)
c=app.state.container
c.initialize()
u=c.auth_repository.create_doctor('Synthetic Audit Doctor','audit@example.test','AuditPass123!')
for p in c.patient_repository.list(): c.auth_repository.assign_patient(u.practitioner_id,p.patient_id)
from fastapi import Request
@app.post('/audit/fail-next-documentation')
async def fail_next_documentation():
 original=c.documentation_service.transcribe
 def failure(*args,**kwargs):
  c.documentation_service.transcribe=original
  raise RuntimeError('Synthetic browser failure')
 c.documentation_service.transcribe=failure
 return {'ready':True}
original_transcribe=c.documentation_service.transcribe
def delayed_transcribe(*args,**kwargs):
 import time
 time.sleep(3)
 return original_transcribe(*args,**kwargs)
c.documentation_service.transcribe=delayed_transcribe

# Synthetic controls for checkpoint/retry browser tests; no production routes.
qa_controls={'soap_calls':0,'soap_delay':0,'fail_soap':False}
original_generate=c.documentation_service.generate_draft
def controlled_generate(*args,**kwargs):
 import time
 qa_controls['soap_calls']+=1
 time.sleep(qa_controls['soap_delay'])
 if qa_controls['fail_soap']:
  qa_controls['fail_soap']=False
  raise RuntimeError('Synthetic SOAP failure')
 return original_generate(*args,**kwargs)
c.documentation_service.generate_draft=controlled_generate
@app.post('/audit/soap-controls')
async def soap_controls(request:Request):
 values=await request.json()
 for key in ('soap_delay','fail_soap'):
  if key in values:qa_controls[key]=values[key]
 return qa_controls
@app.get('/audit/soap-controls')
async def read_soap_controls():
 return qa_controls
if __name__=='__main__':
 import uvicorn
 uvicorn.run(app,host='127.0.0.1',port=8765,log_level='warning')

# Browser QA endpoints/providers below are synthetic and never part of the application.
