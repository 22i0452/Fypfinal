/* Reception evidence follows observed server transitions, not estimated probabilities. */
let receptionEvidenceChanges={},receptionEvidenceSignature={};
const RECEPTION_EVIDENCE_FIELDS=[['name','user-round','Name'],['age','calendar','Age'],['phone','phone','Phone'],['first_visit','clipboard','First visit'],['history','heart-pulse','History'],['complaint','stethoscope','Complaint'],['department','building-2','Department'],['doctor','user-check','Doctor'],['time','clock','Requested time']];
function receptionEvidenceData(key){
  const proof=agentArtifact?.field_evidence?.[key] || agentSaved?.field_evidence?.[key];
  const value=agentArtifact?.values?.[key] || (agentArtifact?.pending?.key===key?agentArtifact.pending:null);
  const label=RECEPTION_EVIDENCE_FIELDS.find(x=>x[0]===key)?.[2] || key;
  if(!proof)return {title:label,status:'missing',label:'Source unavailable',interpretation:value?.en || 'Not collected',checks:[],scope:'No recorded provenance is available for this field.',technical:{field:key,confidence:'Not measured'}};
  return {title:label,status:proof.status,label:proof.label,raw:proof.raw,interpretation:proof.interpretation?.en,confirmation:proof.confirmation,revisions:proof.revisions,
    checks:[...(proof.checks || []),{code:'patient_confirmation',label:'Patient confirmation',status:proof.confirmation?'passed':'review',detail:proof.confirmation?'A readback or final summary was accepted by the caller.':'This field has not been explicitly confirmed by the caller.'}],
    scope:'Booking rules and caller confirmation. Identity, phone ownership and clinical truth are separate checks.',
    technical:{field:key,source_turn_id:proof.source_turn_id,confirmation_turn:proof.confirmation?.source_turn_id || 'Pending',method:proof.method?.method || proof.method?.provider || 'BookingFlow',model:proof.method?.model || 'No model reported',practitioner_id:proof.interpretation?.practitioner_id || 'Not applicable',confidence:'Not measured'}};
}
window.receptionEvidenceFields=function(){
  MedFlowEvidence.setScope('reception:'+state.demoSessionId);
  const pending=agentArtifact?.pending,values=agentArtifact?.values || {},proofs=agentArtifact?.field_evidence || {};
  return RECEPTION_EVIDENCE_FIELDS.map(([key,icon,label])=>{
    const proof=proofs[key],value=values[key] || (pending?.key===key?pending:null) || proof?.interpretation,status=proof?.status || 'missing';
    const buttonKey=MedFlowEvidence.register('field:'+key,()=>receptionEvidenceData(key));
    const change=receptionEvidenceChanges[key],animated=change && performance.now()-change.at<1000;
    return `<button class="agent-field evidence-field ev-${status} ${key===agentArtifact?.current_field?'pending':''} ${animated?(change.confirmed?'is-confirmed':'is-updated'):''}" data-evidence-key="${buttonKey}" type="button" aria-label="Inspect ${label} evidence" ${state.demoBusy || window.liveConversation?.capturing()?'disabled':''}><small><i data-lucide="${icon}"></i>${label}</small><strong>${escapeHtml(value?.en || '—')}</strong>${MedFlowEvidence.badge(status,proof?.label || (value?'Source unavailable':'Not collected'))}</button>`;
  }).join('');
};
window.receptionEvidenceReceipt=function(){
  const answer=agentArtifact?.last_answer;
  const proofs=Object.values(agentArtifact?.field_evidence || {});
  const confirmed=proofs.filter(x=>x.confirmation).length;
  let html=`${MedFlowEvidence.legend()}<div class="evidence-path"><span>${MedFlowEvidence.badge('received','Receive')}</span><i data-lucide="chevron-right"></i><span>${MedFlowEvidence.badge('review','Interpret')}</span><i data-lucide="chevron-right"></i><span>${MedFlowEvidence.badge('checked','Check & confirm')}</span></div>`;
  if(answer){const key=MedFlowEvidence.register('last-answer',()=>({title:'Latest caller answer',raw:answer.raw,status:answer.status,label:answer.status==='review'?'Review answer':'Turn processed',checks:answer.checks,scope:'Receipt for the current answer; accepted fields have separate receipts.',technical:{source_turn_id:answer.source_turn_id,state:agentArtifact.step,current_field:agentArtifact.current_field,method:answer.method,confidence:'Not measured'}}));
    html+=`<div class="evidence-live-receipt"><div><h4>Answer → checked details</h4><button class="note-action" data-evidence-key="${key}" type="button">Inspect</button></div><p dir="auto">${escapeHtml(answer.raw)}</p><div class="evidence-turn-receipt">${MedFlowEvidence.badge(answer.status,answer.status==='review'?'Review required':'Turn processed')}<code>${escapeHtml(answer.source_turn_id)}</code></div><p>${proofs.length} fields with recorded sources · ${confirmed} caller-confirmed</p></div>`;
  }
  return html;
};
const evidenceBaseArtifact=receptionArtifact;
receptionArtifact=function(artifact){
  const next=artifact?.field_evidence || {};
  for(const [key,proof] of Object.entries(next)){const sig=JSON.stringify([proof.interpretation,proof.status,proof.confirmation]);if(receptionEvidenceSignature[key]!==sig){receptionEvidenceChanges[key]={at:performance.now(),confirmed:!!proof.confirmation};receptionEvidenceSignature[key]=sig;}}
  evidenceBaseArtifact(artifact);
  const answer=artifact?.last_answer;if(!answer)return;
  const bubble=[...document.querySelectorAll('#demoTranscript .chat-bubble.patient')].at(-1);
  if(bubble){bubble.dataset.sourceTurn=answer.source_turn_id;let receipt=bubble.querySelector('.evidence-turn-receipt');if(!receipt){receipt=document.createElement('div');receipt.className='evidence-turn-receipt';bubble.append(receipt);}const raw=bubble.querySelector('.caller-words');
    if(raw && raw.textContent===answer.raw){const spans=Object.entries(next).filter(([,proof])=>proof.source_turn_id===answer.source_turn_id).flatMap(([key,proof])=>{const words=proof.interpretation?.ur;return words && answer.raw.includes(words)?[{text:words,status:proof.status,key:MedFlowEvidence.register('field:'+key,()=>receptionEvidenceData(key))}]:[];});raw.innerHTML=MedFlowEvidence.marks(answer.raw,spans);}
    receipt.innerHTML=`${MedFlowEvidence.badge(answer.status,answer.status==='review'?'Review answer':'Processed answer')}<code>${escapeHtml(answer.source_turn_id)}</code>`;}
};
window.receptionArtifact=receptionArtifact;
const evidenceBaseStop=stopDemo;
stopDemo=function(){MedFlowEvidence.close();receptionEvidenceChanges={};receptionEvidenceSignature={};evidenceBaseStop();};
window.onEvidenceOpen=()=>{if(window.liveConversation?.controller.active)window.liveConversation.controller.pause('Listening paused while you inspect evidence. Press Resume when ready.');};
const evidenceBaseResult=renderDemoResult;
renderDemoResult=function(result){
  evidenceBaseResult(result);const root=document.getElementById('demoResult');root.querySelector('.booking-evidence-receipt')?.remove();
  const appointment=result?.booking?.appointment;
  if(!result?.saved)return;
  const checks=[{code:'intake_storage',label:'Patient intake persisted',status:'passed',detail:'The server returned the stored patient ID and workflow ID.'},
    {code:'appointment_storage',label:'Appointment request persisted',status:appointment?.appointment_id?'passed':'review',detail:appointment?.appointment_id?'A real appointment ID was returned.':'No stored appointment exists for this intake yet.'},
    {code:'appointment_status',label:'Clinic appointment state',status:appointment?.status==='CONFIRMED'?'passed':'review',detail:appointment?.status==='CONFIRMED'?'Appointment is confirmed.':appointment?.status==='REQUESTED'?'Request stored; identity verification and clinic confirmation remain pending.':'Continue booking with an available slot.'}];
  const key=MedFlowEvidence.register('booking-receipt',{title:'Saved handoff receipt',status:appointment?'checked':'review',label:appointment?'Request stored':'Intake stored',interpretation:appointment?.practitioner_name || 'Appointment pending',checks,scope:'Stored IDs demonstrate persistence. REQUESTED and CONFIRMED remain different appointment states.',technical:{patient_id:result.patient_id,workflow_id:result.workflow_id,appointment_id:appointment?.appointment_id || 'None',practitioner_id:appointment?.practitioner_id || 'None',appointment_status:appointment?.status || result.booking?.status,confidence:'Not applicable'}});
  const receipt=document.createElement('div');receipt.className='evidence-live-receipt booking-evidence-receipt';receipt.innerHTML=`<div><h4>Stored handoff</h4><button class="note-action" data-evidence-key="${key}" type="button">Inspect receipt</button></div><p>${MedFlowEvidence.badge('checked','Intake stored')} · ${MedFlowEvidence.badge(appointment?'checked':'review',appointment?'Appointment request stored':'Appointment pending')}</p>`;root.append(receipt);
};
document.addEventListener('DOMContentLoaded',()=>renderReceptionProcess());

let manualEvidenceSaved=null;
function renderManualEvidence(){
  for(const id of FIELDS){
    const field=document.getElementById(id);if(!field)continue;
    let receipt=field.parentElement.querySelector('.manual-field-evidence');
    if(!receipt){receipt=document.createElement('span');receipt.className='manual-field-evidence';field.after(receipt);}
    const value=field.value.trim(),saved=manualEvidenceSaved?.values[id]===value;
    const status=saved?'checked':value?'received':'missing';
    receipt.innerHTML=MedFlowEvidence.badge(status,saved?'Server stored':value?'Entered · server check pending':'Not entered');
  }
}
const evidenceBaseApi=api;
api=async function(path,options){
  const result=await evidenceBaseApi(path,options);
  if(path==='/api/desk/intakes' && options?.method==='POST' && result.patient_id){
    manualEvidenceSaved={patient_id:result.patient_id,workflow_id:result.workflow_id,values:Object.fromEntries(FIELDS.slice(0,6).map(id=>[id,document.getElementById(id).value.trim()]))};renderManualEvidence();
  }
  return result;
};
const evidenceBaseIntakeSubmit=submitIntake;
submitIntake=async function(event){
  await evidenceBaseIntakeSubmit(event);
  if(!state.bookingReceipt?.appointment?.appointment_id || intakeStage!==2)return;
  const appointment=state.bookingReceipt.appointment;
  const key=MedFlowEvidence.register('manual-booking',{title:'Manual intake handoff',status:'checked',label:'Request stored',interpretation:appointment.practitioner_name,
    scope:'Observed server save results. Intake storage and identity verification are separate.',checks:[{code:'intake_storage',label:'Intake stored',status:'passed',detail:'The server returned this patient and workflow.'},{code:'appointment_storage',label:'Appointment stored',status:'passed',detail:'The server returned the actual appointment ID.'},{code:'clinic_confirmation',label:'Clinic confirmation',status:appointment.status==='CONFIRMED'?'passed':'review',detail:'Appointment status: '+appointment.status}],
    technical:{patient_id:state.patientId,workflow_id:state.workflowId,appointment_id:appointment.appointment_id,practitioner_id:appointment.practitioner_id,status:appointment.status}});
  const root=document.getElementById('bookingResult');root.querySelector('.manual-evidence-receipt')?.remove();const button=document.createElement('button');button.type='button';button.className='note-action manual-evidence-receipt';button.dataset.evidenceKey=key;button.textContent='Inspect stored handoff';root.append(button);
};
const evidenceBaseReset=resetSession;
resetSession=function(){if(state.busy || state.demoBusy || state.demoSaving)return evidenceBaseReset();manualEvidenceSaved=null;MedFlowEvidence.close();evidenceBaseReset();renderManualEvidence();};
document.addEventListener('DOMContentLoaded',()=>{renderManualEvidence();document.getElementById('intakeForm').addEventListener('input',renderManualEvidence);document.getElementById('intakeForm').addEventListener('change',renderManualEvidence);});
