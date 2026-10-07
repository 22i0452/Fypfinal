/* Guided encounter UI. Server records remain authoritative; storage holds identifiers only. */
let isProcessing = false;
let captureContext = null;
let recordingStartTimer = null;
let visitStage = 'prepare';
let visitLoading = false;
let visitActionBusy = false;
let workspaceCodingEnabled = false;
let contextRevision = 0;
let processStep = 0;
let summaryBusy = false;
let visitSummaryLanguage = "BILINGUAL";
let currentNoteVersion = 0;
let previsitEnabled = true;
let contextRefreshTimer=null;
function scheduleContextRefresh(){
  clearTimeout(contextRefreshTimer);
  if(isProcessing || activeWorkflow?.state==='DOCUMENTATION_PROCESSING')contextRefreshTimer=setTimeout(async()=>{
    try{await refreshActiveContext();}catch{scheduleContextRefresh();}
  },2000);
}

async function fetchWorkspaceCapabilities(){
  const response=await fetch('/api/workflows/capabilities');
  if(response.ok){const payload=await response.json();workspaceCodingEnabled=Boolean(payload.coding_enabled);previsitEnabled=Boolean(payload.previsit_enabled);}
}

function studioIcon(name) { return `<i data-lucide="${name}" aria-hidden="true"></i>`; }
function studioIcons() { if (window.lucide) lucide.createIcons({attrs:{'stroke-width':1.5}}); }
function visitLocked() { return isRecording || pendingRecordingStart || isProcessing || soapSaveBusy || visitActionBusy || assistantBusy || codingBusy || previsitBusy || summaryBusy; }
function canLeaveVisit() {
  if (visitLocked()) { showToast('Finish the active action before changing the patient or workspace.', 'error'); return false; }
  if (soapDraftTouched || Object.values(soapSectionEditing).some(Boolean)) { showToast('Save your note changes before leaving this visit.', 'error'); return false; }
  return true;
}
function rememberVisit() {
  if (!selectedPatient) return;
  sessionStorage.setItem('medflow-visit',JSON.stringify({user:currentUser.email,patientId:selectedPatient._id,noteId:soapLastSavedNoteId || '',stage:visitStage}));
}
async function restoreLastVisit() {
  const params=new URLSearchParams(location.search);
  let saved=null;
  try { saved=JSON.parse(sessionStorage.getItem('medflow-visit') || 'null'); } catch { sessionStorage.removeItem('medflow-visit'); }
  const reference=params.get('patient_ref') || (saved?.user===currentUser.email ? saved.patientId : '');
  const patient=allPatients.find(p=>p._id===reference || p.legacy_ref===reference || p.file_name===reference);
  if (patient) { await openPatientVisit(patient,{noteId:params.get('patient_ref')?'':saved?.noteId || '',restore:true}); }
  if (params.get('patient_ref') && !patient) {
    const notice=document.getElementById('handoffAccessNotice');
    if(notice){notice.hidden=false;notice.textContent='This handoff is unavailable to the signed-in account. Check the assigned doctor on the reception receipt and sign in with that account, or refresh if it was just submitted. Your record may still be saved.';}
    showToast('Handoff unavailable for this account. Check the assigned doctor on the receipt.','error');
  }
  renderRecentDrafts();
}
async function readVisitContext(patientId,noteId='') {
  const query=noteId?'?note_id='+encodeURIComponent(noteId):'';
  const response=await fetch('/api/workflows/context/'+encodeURIComponent(patientId)+query);
  const payload=await response.json().catch(()=>({}));
  if (!response.ok) throw new Error(apiMessage(payload,'Unable to load this visit.'));
  return payload;
}
function applyVisitContext(payload,{loadNote=true}={}) {
  activeWorkflow=payload.workflow || null;
  activeAppointment=payload.appointment || null;
  activeEncounter=payload.encounter || null;
  consentDecisions=Object.fromEntries((payload.consents || []).map(x=>[x.consent_type,x]));
  developmentQuickStartEnabled=Boolean(payload.development_quick_start_enabled && String(selectedPatient?._id).startsWith('PT-DEMO-SYNTHETIC-'));
  workspaceCodingEnabled=Boolean(payload.coding_enabled);
  if (payload.note && loadNote) {
    generatedSoap=normalizeSoapDraft({...payload.note.soap,patient_name:payload.note.patient_name,visit_date:payload.note.created_at});
    soapLastSavedNoteId=payload.note.note_id;
    currentNoteVersion=payload.note.version;
    generatedNoteState=payload.note.state;
    fullTranscript=payload.note.transcript || [];
    diarizedTranscript=fullTranscript.map(x=>({...x,text:x.original_text || x.text}));
    transcriptMode=fullTranscript.length?'english':'urdu';
    soapDraftTouched=false;soapSectionEditing={};soapSectionSnapshots={};
    savedNotes=[payload.note,...savedNotes.filter(x=>x.note_id!==payload.note.note_id)];
    visitStage=payload.note.state==='APPROVED_BY_DOCTOR'?'finish':'review';
    renderSoapNote(generatedSoap,fullTranscript);renderTranscript();
  }
  isProcessing=activeWorkflow?.state==='DOCUMENTATION_PROCESSING';
  if (isProcessing) visitStage='processing';
  else if (activeWorkflow?.state==='FAILED' && !soapLastSavedNoteId) visitStage='prepare';
  scheduleContextRefresh();
  rememberVisit();
}
async function openPatientVisit(patient,{noteId='',restore=false}={}) {
  if (!canLeaveVisit()) return false;
  const revision=++contextRevision;
  selectedPatient=patient;activeWorkflow=null;activeEncounter=null;activeAppointment=null;consentDecisions=null;
  generatedNoteState='';currentNoteVersion=0;visitSummaryLanguage="BILINGUAL";previsitSummary=null;previsitBusy=false;highlightedEvidenceIds=[];
  resetSoapDraftState();resetTranscriptState();captureContext=null;assistantMessages=[];assistantBusy=false;
  visitStage='prepare';visitLoading=true;
  renderSelectedPatient();renderTranscript();renderSoapEmptyState();renderPatientList();showVisitWorkspace();renderClinicFlow();
  try {
    let payload;
    try { payload=await readVisitContext(patient._id,noteId); }
    catch(error) { if (restore && noteId) payload=await readVisitContext(patient._id); else throw error; }
    if (revision!==contextRevision || selectedPatient?._id!==patient._id) return false;
    applyVisitContext(payload);
    if (activeEncounter) await Promise.all([refreshPrevisitSummary(),loadStoredVisitSummary()]);
    return true;
  } catch(error) { if (revision===contextRevision) showToast(error.message,'error');return false; }
  finally { if (revision===contextRevision) {visitLoading=false;renderSelectedPatient();renderClinicFlow();updateNoteStats();renderRecentDrafts();} }
}
async function preparePatientWorkflow(patient) {
  const revision=contextRevision;
  try {const payload=await readVisitContext(patient._id);if(revision!==contextRevision)return false;applyVisitContext(payload);renderClinicFlow();return true;}
  catch(error){showToast(error.message,'error');return false;}
}
async function refreshActiveContext() {
  if (!selectedPatient) return;
  const revision=contextRevision;
  const payload=await readVisitContext(selectedPatient._id,soapLastSavedNoteId);
  if (revision!==contextRevision) return;
  applyVisitContext(payload,{loadNote:!soapDraftTouched && !soapSaveBusy});
  renderClinicFlow();
}
async function beginNewVisit() {
  if (!selectedPatient || !canLeaveVisit()) return;
  if (activeWorkflow && !['ENCOUNTER_COMPLETED','CANCELLED'].includes(activeWorkflow.state)) {
    showToast('Complete the current visit before starting another. Your saved draft stays with this encounter.','error');return;
  }
  visitActionBusy=true;renderClinicFlow();
  try {
    const response=await fetch('/api/workflows',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({patient_id:selectedPatient._id})});
    const payload=await response.json();if(!response.ok)throw new Error(apiMessage(payload,'Unable to start a visit.'));
    resetSoapDraftState();resetTranscriptState();generatedNoteState='';activeWorkflow=payload.workflow;activeEncounter=null;activeAppointment=null;consentDecisions=null;visitStage='prepare';
    rememberVisit();renderSoapEmptyState();renderTranscript();renderSelectedPatient();
  }catch(error){showToast(error.message,'error');}finally{visitActionBusy=false;renderClinicFlow();}
}
async function resumeSavedNote(noteId) {
  if (!canLeaveVisit()) return;
  const note=savedNotes.find(x=>x.note_id===noteId);
  if(!note)return;
  let patient=allPatients.find(x=>x._id===note.patient_id);
  if(!patient){await fetchPatients();patient=allPatients.find(x=>x._id===note.patient_id);}
  if(patient)await openPatientVisit(patient,{noteId});else showToast('Patient record is unavailable.','error');
}
function chooseVisitStage(stage) {
  if (stage!=='review' && (soapDraftTouched || Object.values(soapSectionEditing).some(Boolean))) {showToast('Save or cancel your note changes before moving to another stage.','error');return;}
  if (visitLocked() && stage!==visitStage) {showToast('The active action is still running.','error');return;}
  if(stage==='capture' && (!isConsultationRecordable() || !hasRequiredConsent() || soapLastSavedNoteId)){showToast('Complete preparation before recording, or review the saved note.','error');return;}
  if(stage==='transcript' && !window.hasConversationReview?.()){showToast('The saved conversation will be available after processing.','error');return;}
  if(stage==='review' && !generatedSoap){showToast('The SOAP draft will be available after the recording is processed.','error');return;}
  if(stage==='finish' && (generatedNoteState!=='APPROVED_BY_DOCTOR' || soapDraftTouched)){showToast('Save and approve the note before finishing this visit.','error');return;}
  visitStage=stage;rememberVisit();renderClinicFlow();
}
async function ensureConsultationReadyForRecording() {
  if(isConsultationRecordable() && activeEncounter && !soapLastSavedNoteId)return true;
  visitStage='prepare';renderClinicFlow();showToast('Prepare this visit first. Opening a record does not start a new encounter.','error');return false;
}
const studioBaseRecording=startRecording;
startRecording=async function(){
  if(visitLocked() || soapLastSavedNoteId)return;
  pendingRecordingStart=true;renderClinicFlow();
  try{await studioBaseRecording();}
  catch(error){releaseMicrophone();showMicrophoneAccessError(error);}
  finally{if(!captureContext)pendingRecordingStart=false;renderClinicFlow();}
};
const studioBaseStop=stopRecording;
stopRecording=function(){if(!isRecording)return;isProcessing=true;visitStage='processing';processStep=0;studioBaseStop();renderClinicFlow();};
const studioBaseMessage=handleServerMessage;
handleServerMessage=function(event){
  let msg;try{msg=JSON.parse(event.data);}catch{return;}
  if(msg.type==='pong')return;
  if(!captureContext || msg.patient_id!==captureContext.patientId || msg.workflow_id!==captureContext.workflowId || msg.encounter_id!==captureContext.encounterId || msg.capture_id!==captureContext.captureId)return;
  if(['recording_started','soap_note','error'].includes(msg.type)){clearTimeout(recordingStartTimer);recordingStartTimer=null;}
  if(msg.type==='recording_started'){visitStage='capture';isProcessing=false;}
  if(msg.type==='processing'){isProcessing=true;scheduleContextRefresh();visitStage='processing';processStep=/speaker/i.test(msg.message)?1:/translat/i.test(msg.message)?2:/SOAP|draft/i.test(msg.message)?3:0;}
  if(msg.type==='soap_note'){isProcessing=false;visitStage='review';currentNoteVersion=1;}
  if(msg.type==='error'){isProcessing=false;visitStage='capture';}
  studioBaseMessage(event);
  if(msg.type==='soap_note'){
    const note={note_id:msg.note_id,patient_id:captureContext.patientId,encounter_id:captureContext.encounterId,patient_name:selectedPatient.name,soap:generatedSoap,transcript:fullTranscript,state:generatedNoteState,created_at:generatedSoap.visit_date,excerpt:generatedSoap.assessment};
    savedNotes=[note,...savedNotes.filter(x=>x.note_id!==note.note_id)];activeWorkflow.note_id=note.note_id;
    rememberVisit();renderRecentDrafts();fetchNotes();
  }
  if(msg.type==='error'){captureContext=null;refreshActiveContext().catch(()=>{});updateRecordingBanner('Action interrupted',msg.message || 'Please review the visit status before continuing.');}
  renderClinicFlow();
};
const studioBaseConnect=connectWebSocket;
connectWebSocket=function(){
  studioBaseConnect();if(!ws || ws._studioBound)return;ws._studioBound=true;
  const onOpen=ws.onopen,onClose=ws.onclose;
  ws.onopen=e=>{if(onOpen)onOpen(e);document.getElementById('connectionDot')?.classList.add('connected');const label=document.getElementById('connectionLabel');if(label)label.textContent='Server connected';if(selectedPatient && !visitActionBusy && !isRecording && !pendingRecordingStart && !soapDraftTouched)refreshActiveContext().catch(()=>{});renderClinicFlow();};
  ws.onclose=e=>{
    document.getElementById('connectionDot')?.classList.remove('connected');const label=document.getElementById('connectionLabel');if(label)label.textContent='Reconnecting';
    if(isRecording || pendingRecordingStart || isProcessing){releaseMicrophone();stopDurationTimer();isRecording=false;pendingRecordingStart=false;isProcessing=false;captureContext=null;clearTimeout(recordingStartTimer);setRecordingUI(false);updateRecordingBanner('Connection interrupted','Recording has stopped. Reconnect and reload the visit to check for a saved draft.');showToast('Connection lost. Microphone capture has stopped.','error');}
    renderClinicFlow();if(onClose)onClose(e);
  };
};
function renderClinicFlow(){
  const view=document.getElementById('visitView');if(!view)return;
  view.classList.toggle('no-patient',!selectedPatient);view.dataset.stage=visitStage;
  const state=activeWorkflow?.state || '';
  const labels={PATIENT_UNVERIFIED:'Verification needed',BOOKING_REQUIRED:'Ready to book',BOOKING_CONFIRMED:'Appointment confirmed',CONSULTATION_READY:'Ready for consultation',CONSULTATION_ACTIVE:'Consultation active',DOCUMENTATION_PROCESSING:'Preparing documentation',NOTE_REVIEW_REQUIRED:'Doctor review',NOTE_APPROVED:'Approved',ENCOUNTER_COMPLETED:'Completed',FAILED:'Attention needed',CANCELLED:'Cancelled'};
  document.getElementById('workflowStatePill').textContent=visitLoading?'Loading visit':labels[state] || (state?state.replaceAll('_',' ').toLowerCase():'No active visit');
  const headings={prepare:['BEFORE THE CONSULTATION','A considered beginning.'],capture:['DURING THE CONSULTATION',isRecording?'The conversation, uninterrupted.':'Space for the conversation.'],processing:['PREPARING YOUR DOCUMENTATION','From conversation to clarity.'],transcript:['CONVERSATION REVIEW','First, the conversation.'],review:['DOCTOR REVIEW','Your judgement. A clearer record.'],finish:['AFTER THE CONSULTATION',state==='ENCOUNTER_COMPLETED'?'A visit, thoughtfully completed.':'The final details.']};
  const [kicker,title]=headings[visitStage];document.getElementById('visitStageKicker').textContent=kicker;document.getElementById('visitStageTitle').textContent=title;
  const stages=['prepare','capture','transcript','review','finish'];view.querySelectorAll('.visit-step').forEach(b=>{b.classList.toggle('active',b.dataset.stage===(visitStage==='processing'?'capture':visitStage));b.classList.toggle('done',stages.indexOf(b.dataset.stage)<stages.indexOf(visitStage==='processing'?'capture':visitStage));if(b.classList.contains('active'))b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');});
  const ready=isConsultationRecordable(),granted=hasRequiredConsent();
  const prepareRows=[['user-check','Identity verified',!['','PATIENT_UNVERIFIED'].includes(state),'Verification required before booking'],['calendar-check','Appointment confirmed',Boolean(activeAppointment),'Choose an appointment'],['clipboard-check','Patient checked in',Boolean(activeEncounter),'Confirm arrival'],['shield-check','Patient choices recorded',granted,'Recording and AI permissions']];
  document.getElementById('preparationSteps').innerHTML=prepareRows.map(([icon,label,done,sub])=>`<div class="preparation-item ${done?'done':''}">${studioIcon(done?'check':icon)}<span><strong>${label}</strong><small>${done?'Complete':sub}</small></span></div>`).join('');
  document.getElementById('consentStatus').textContent=granted?'Required permissions recorded. Audio retention '+(consentDecisions?.AUDIO_RETENTION?.decision?'on.':'off.'):activeEncounter?'Record the patient’s choices before capture.':'Check in the patient to record choices.';
  if(state==='FAILED')document.getElementById('consentStatus').textContent='Documentation was interrupted. Your visit and choices are preserved. Try recording again to create a new draft.';
  const consentButton=document.getElementById('openConsentBtn');consentButton.disabled=!activeEncounter || !ready || visitLocked();consentButton.textContent=granted?'Update choices':'Record choices';
  document.getElementById('manualPathNotice').hidden=!activeEncounter || granted;
  document.getElementById('quickStartBtn').hidden=!developmentQuickStartEnabled;document.getElementById('quickStartBtn').disabled=visitLocked() || Boolean(soapLastSavedNoteId);
  for(const id of ['recordToggleBtn','recBtn'])document.getElementById(id).disabled=pendingRecordingStart || isProcessing || visitActionBusy || !selectedPatient || !ready || !granted || Boolean(soapLastSavedNoteId);
  document.getElementById('clinicalTemplateSelect').disabled=visitLocked();
  document.getElementById('regeneratePrevisitBtn').disabled=!activeEncounter || previsitBusy || !previsitEnabled;
  document.getElementById('correctIntakeBtn').disabled=!selectedPatient || Boolean(activeEncounter) || visitLocked();
  const action=document.getElementById('visitNextBtn');let actionLabel='Start visit';let disabled=visitLoading || visitActionBusy || pendingRecordingStart || soapSaveBusy;
  if(visitStage==='prepare')actionLabel=!activeWorkflow || ['ENCOUNTER_COMPLETED','CANCELLED'].includes(state)?'Start new visit':state==='PATIENT_UNVERIFIED'?'Verify patient':['PATIENT_VERIFIED','INTAKE_IN_PROGRESS','INTAKE_COMPLETED'].includes(state)?'Confirm intake':state==='BOOKING_REQUIRED'?'Book appointment':state==='BOOKING_CONFIRMED'?'Check in patient':state==='FAILED' && activeWorkflow.resume_state==='DOCUMENTATION_PROCESSING' && !soapLastSavedNoteId?'Try recording again':ready?(granted?'Continue to consultation':'Record patient choices'):'Return to visits';
  if(visitStage==='capture'){actionLabel=isRecording?'Finish recording':'Start recording';disabled ||= !ready || !granted;}
  if(visitStage==='processing'){actionLabel='Processing conversation';disabled=true;}
  if(visitStage==='transcript'){actionLabel=window.conversationActionLabel?.() || 'Generate SOAP';disabled ||= visitLocked();}
  if(visitStage==='review'){actionLabel=soapDraftTouched?'Save changes':generatedNoteState==='REVIEW_REQUIRED'?'Approve note':generatedNoteState==='APPROVED_BY_DOCTOR'?'Continue to summary':'Review draft';disabled ||= Object.values(soapSectionEditing).some(Boolean);}
  if(visitStage==='finish'){actionLabel=state==='ENCOUNTER_COMPLETED'?'Back to today':'Complete visit';disabled ||= generatedNoteState!=='APPROVED_BY_DOCTOR' || soapDraftTouched;renderFinishWorkspace();}
  action.innerHTML=escHtml(actionLabel)+studioIcon(isRecording?'square':visitStage==='processing'?'loader-circle':'arrow-right');action.disabled=disabled;
  document.getElementById('newVisitBtn').hidden=state!=='ENCOUNTER_COMPLETED';
  document.getElementById('visitSaveStatus').textContent=soapDraftTouched?'Unsaved note changes':soapLastSavedNoteId?(generatedNoteState==='APPROVED_BY_DOCTOR'?'Doctor-approved note':'Draft saved to this visit'):activeWorkflow?'Visit in progress':'Patient record opened';
  document.getElementById('visitSaveDetail').textContent=activeEncounter?'Encounter '+activeEncounter.encounter_id.replace('ENC-','').slice(0,8)+(currentNoteVersion?' · Version '+currentNoteVersion:''):'Opening this record does not change its appointments.';
  document.getElementById('statRecordings').textContent=isRecording?'1':'0';
  const focus=document.getElementById('captureFocusTitle');if(focus)focus.textContent=isRecording?'Listening. Stay in the moment.':'Space for the conversation.';
  if(isProcessing && visitStage==='processing')showProcessingInSoap(['Transcribing audio','Identifying speakers','Translating to English','Preparing the SOAP draft'][processStep]);
  studioIcons();
}
async function advanceVisit(){
  if(visitActionBusy || visitLoading)return;
  if(visitStage==='capture'){await toggleRecording();return;}
  if(visitStage==='transcript'){await window.advanceConversationReview?.();return;}
  if(visitStage==='review'){
    if(soapDraftTouched){await saveSoapDraft();renderClinicFlow();return;}
    if(generatedNoteState==='APPROVED_BY_DOCTOR'){chooseVisitStage('finish');return;}
    visitActionBusy=true;renderClinicFlow();
    try{if(generatedNoteState==='REVIEW_REQUIRED')await approveCurrentSoap();else await submitSoapForReview();}
    finally{visitActionBusy=false;renderClinicFlow();}return;
  }
  if(visitStage==='finish'){if(activeWorkflow?.state==='ENCOUNTER_COMPLETED'){showDashboard();return;}await completeCurrentVisit();return;}
  const state=activeWorkflow?.state || '';
  if(!state || ['ENCOUNTER_COMPLETED','CANCELLED'].includes(state)){await beginNewVisit();return;}
  if(state==='FAILED' && activeWorkflow.resume_state==='DOCUMENTATION_PROCESSING' && !soapLastSavedNoteId){await retryVisitDocumentation();return;}
  if(state==='PATIENT_UNVERIFIED'){await requestPatientOtp();return;}
  if(['PATIENT_VERIFIED','INTAKE_IN_PROGRESS','INTAKE_COMPLETED'].includes(state)){
    visitActionBusy=true;try{const r=await fetch('/api/workflows/'+encodeURIComponent(activeWorkflow.workflow_id)+'/complete-intake',{method:'POST'});const p=await r.json();if(!r.ok)throw new Error(apiMessage(p,'Unable to confirm intake.'));activeWorkflow=p.workflow;}catch(e){showToast(e.message,'error');}finally{visitActionBusy=false;renderClinicFlow();}return;
  }
  if(state==='BOOKING_REQUIRED'){await openBookingDialog();return;}
  if(state==='BOOKING_CONFIRMED'){await checkInPatient();return;}
  if(isConsultationRecordable()){if(!hasRequiredConsent())openConsentDialog();else chooseVisitStage('capture');return;}
  showDashboard();
}
function showProcessingInSoap(message){
  const stages=['Transcription','Speaker labels','English translation','SOAP draft'];
  document.getElementById('soapContent').innerHTML=`<div class="processing-shell"><div><div class="spinner"></div><h4>Preparing your record</h4><p class="muted">${escHtml(message || 'Processing the consultation…')}</p><div class="processing-stages">${stages.map((label,i)=>`<span class="${i===processStep?'active':i<processStep?'done':''}">${studioIcon(i<processStep?'check':i===processStep?'audio-lines':'circle')}${label}</span>`).join('')}</div></div></div>`;
}
function renderRecentDrafts(){
  const el=document.getElementById('recentDrafts');if(!el)return;
  const drafts=savedNotes.filter(x=>x.state!=='APPROVED_BY_DOCTOR').slice(0,5);
  el.innerHTML=drafts.length?drafts.map(note=>`<button class="draft-link" onclick="resumeSavedNote('${escAttr(note.note_id)}')">${studioIcon('file-pen-line')}<span><b>${escHtml(note.patient_name || 'Patient')}</b><small>${escHtml((note.state || 'Draft').replaceAll('_',' ').toLowerCase())}</small></span>${studioIcon('arrow-up-right')}</button>`).join(''):'<p class="muted">No drafts waiting. Your next consultation will appear here.</p>';
  studioIcons();
}
async function loadStoredVisitSummary(){
  if(!activeEncounter || !soapLastSavedNoteId)return;
  const noteId=soapLastSavedNoteId,revision=contextRevision;
  const r=await fetch('/api/encounters/'+encodeURIComponent(activeEncounter.encounter_id)+'/after-visit-summary');
  if(r.ok){const p=await r.json();if(revision===contextRevision){afterVisitSummaries[noteId]=p;visitSummaryLanguage=p.language || "BILINGUAL";renderFinishWorkspace();}}
}
function renderFinishWorkspace(){
  const el=document.getElementById('finishContent');if(!el || !soapLastSavedNoteId)return;
  const summary=afterVisitSummaries[soapLastSavedNoteId];const completed=activeWorkflow?.state==='ENCOUNTER_COMPLETED';
  el.innerHTML=`<div class="finish-grid"><article class="panel-card glass finish-summary"><div class="panel-header"><div><span class="section-kicker">FOR YOUR PATIENT</span><h3>After-visit summary</h3></div>${studioIcon('file-heart')}</div><p>${summary?'Instructions from the current doctor-approved note.':'Prepare a patient-friendly summary from the approved clinical record.'}</p><div class="after-visit-toolbar"><label>Language<select id="visitSummaryLanguage" onchange="visitSummaryLanguage=this.value"><option value="BILINGUAL">Urdu + English</option><option value="ENGLISH">English</option><option value="URDU">Urdu</option></select></label><button class="note-action ${summary?'':'primary'}" onclick="generateVisitSummary()" ${summaryBusy?'disabled':''}>${studioIcon('sparkles')}${summaryBusy?'Preparing…':summary?'Regenerate':'Generate summary'}</button>${summary?`<button class="icon-btn" onclick="printAfterVisitSummary()" aria-label="Print patient summary" title="Print summary">${studioIcon('printer')}</button>`:''}</div>${summary?`<div class="after-visit-summary print-target">${(summary.sections || []).map(section=>`<section><h6>${escHtml(section.title)}</h6><ul>${(section.items || []).map(item=>`<li dir="auto">${escHtml(item.text)}</li>`).join('')}</ul></section>`).join('')}</div>`:''}</article><article class="panel-card glass"><span class="section-kicker">THE VISIT RECORD</span>${[['clipboard-check','Intake & booking','Stored'],['messages-square','Consultation transcript','Stored'],['file-check','Clinical note','Approved'],['check-check','Encounter',completed?'Completed':'Ready to close']].map(([icon,label,status])=>`<div class="finish-check">${studioIcon(icon)}<span>${label}</span><small>${status}</small></div>`).join('')}<div class="detail-actions" style="margin-top:20px"><button class="icon-btn" onclick="copySoap()" aria-label="Copy approved note" title="Copy note">${studioIcon('copy')}</button><button class="icon-btn" onclick="downloadSoap()" aria-label="Download approved note" title="Download note">${studioIcon('download')}</button><button class="note-action" onclick="showNoteVersions('${escAttr(soapLastSavedNoteId)}')">${studioIcon('history')}Version history</button></div><details class="finish-options"><summary>Optional clinical coding</summary><p class="muted" style="margin:12px 0">${workspaceCodingEnabled?'Suggestions require doctor review.':'Clinical coding is disabled in this server configuration.'}</p><button class="note-action" onclick="openCodingFromNote(false)" ${workspaceCodingEnabled?'':'disabled'}>${studioIcon('scan-line')}Open coding</button></details></article></div>`;
  document.getElementById("visitSummaryLanguage").value=visitSummaryLanguage;
}
async function generateVisitSummary(){
  if(summaryBusy || generatedNoteState!=='APPROVED_BY_DOCTOR')return;
  const language=document.getElementById('visitSummaryLanguage').value,noteId=soapLastSavedNoteId,revision=contextRevision;
  summaryBusy=true;renderFinishWorkspace();studioIcons();
  try{const r=await fetch('/api/notes/'+encodeURIComponent(noteId)+'/after-visit-summary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({language})});const p=await r.json();if(!r.ok)throw new Error(apiMessage(p,'Unable to prepare the patient summary.'));afterVisitSummaries[noteId]=p;}
  catch(error){showToast(error.message,'error');}finally{summaryBusy=false;if(revision===contextRevision){renderFinishWorkspace();studioIcons();}}
}
async function completeCurrentVisit(){
  if(!activeWorkflow || visitLocked())return;visitActionBusy=true;renderClinicFlow();
  try{const r=await fetch('/api/workflows/'+encodeURIComponent(activeWorkflow.workflow_id)+'/complete',{method:'POST'});const p=await r.json();if(!r.ok)throw new Error(apiMessage(p,'Unable to complete this visit.'));applyVisitContext(p);showToast('Visit completed. The approved record is preserved.');fetchDoctorQueue();}
  catch(error){showToast(error.message,'error');}finally{visitActionBusy=false;renderClinicFlow();}
}
async function showNoteVersions(noteId){
  try{const r=await fetch('/api/notes/'+encodeURIComponent(noteId)+'/versions');const p=await r.json();if(!r.ok)throw new Error(apiMessage(p,'Unable to load versions.'));document.getElementById('studioDialogHeading').textContent='Note history';document.getElementById('studioDialogContent').innerHTML=p.slice().reverse().map(v=>`<div class="preparation-item"><span><strong>Version ${v.version_number} · ${escHtml(v.status.replaceAll('_',' '))}</strong><small>${escHtml(v.change_reason)} · ${escHtml(formatDateTime(v.created_at))}</small></span></div>`).join('');document.getElementById('studioDialog').showModal();studioIcons();}catch(e){showToast(e.message,'error');}
}
function showWorkspaceDetails(){document.getElementById('studioDialogHeading').textContent='Workspace';document.getElementById('studioDialogContent').innerHTML=`<p class="muted">${escHtml(currentUser.name)} · ${escHtml(currentUser.email)}</p><div class="preparation-item"><span><strong>Server connection</strong><small>${ws?.readyState===WebSocket.OPEN?'Connected':'Reconnecting'}</small></span></div><div class="preparation-item"><span><strong>Clinical coding</strong><small>${workspaceCodingEnabled?'Enabled':'Disabled'}</small></span></div><div class="dialog-actions"><button class="note-action" onclick="signOut()">Sign out</button></div>`;document.getElementById('studioDialog').showModal();}
async function signOut(){if(!canLeaveVisit())return;await fetch('/api/auth/logout',{method:'POST'});sessionStorage.removeItem('medflow-visit');location.replace('/consultation/login');}
showAddPatient=function(){if(canLeaveVisit())location.href='/Receptionist';};
window.addEventListener('beforeunload',event=>{if(visitLocked() || soapDraftTouched){event.preventDefault();event.returnValue='';}});
document.addEventListener('DOMContentLoaded',()=>{const dialog=document.createElement('dialog');dialog.id='studioDialog';dialog.className='workflow-dialog';dialog.innerHTML=`<div class="workflow-dialog-body"><div class="dialog-heading"><h3 id="studioDialogHeading"></h3><button class="icon-btn" onclick="closeWorkflowDialog('studioDialog')" aria-label="Close">${studioIcon('x')}</button></div><div id="studioDialogContent"></div></div>`;document.body.append(dialog);});

// Protect the selected identity through modal mutations, including Escape during a request.
for (const name of ['requestPatientOtp','verifyPatientOtp','bookSelectedAppointment','checkInPatient','saveConsentChoices','saveIntakeCorrection']) {
  const base=window[name];
  window[name]=async function(...args){
    if(visitActionBusy){args[0]?.preventDefault?.();return;}
    visitActionBusy=true;renderClinicFlow();
    try{return await base(...args);}finally{visitActionBusy=false;renderSelectedPatient();renderClinicFlow();rememberVisit();}
  };
}
const studioCancelEdit=cancelSoapSectionEdit;
cancelSoapSectionEdit=function(key){
  studioCancelEdit(key);
  const saved=savedNotes.find(x=>x.note_id===soapLastSavedNoteId);
  if(saved)soapDraftTouched=['subjective','objective','assessment','plan'].some(k=>(generatedSoap?.[k] || '')!==(saved.soap?.[k] || ''));
  renderSoapNote(generatedSoap,fullTranscript);
};
rejectCurrentSoap=function(){
  document.getElementById('studioDialogHeading').textContent='Return draft for correction';
  document.getElementById('studioDialogContent').innerHTML='<label class="dialog-field"><span>Reason</span><textarea id="rejectionReason" rows="3" maxlength="240" placeholder="Describe the correction needed"></textarea></label><p id="rejectionError" class="dialog-error" role="alert"></p><div class="dialog-actions"><button class="toolbar-btn" onclick="closeWorkflowDialog(\'studioDialog\')">Cancel</button><button class="toolbar-btn primary" id="confirmRejectBtn" onclick="confirmDraftRejection()">Return draft</button></div>';
  document.getElementById('studioDialog').showModal();
};
async function confirmDraftRejection(){
  const reason=document.getElementById('rejectionReason').value.trim();if(!reason){document.getElementById('rejectionError').textContent='Enter the correction needed.';return;}
  document.getElementById('confirmRejectBtn').disabled=true;visitActionBusy=true;
  try{const ok=await updateNoteState('/api/notes/'+encodeURIComponent(soapLastSavedNoteId)+'/reject',{reason},'Draft returned for correction.');if(ok)closeWorkflowDialog('studioDialog');}
  finally{visitActionBusy=false;document.getElementById('confirmRejectBtn').disabled=false;renderClinicFlow();}
}

async function retryVisitDocumentation(){
  if(visitLocked() || !activeWorkflow)return;visitActionBusy=true;renderClinicFlow();
  try{const r=await fetch('/api/workflows/'+encodeURIComponent(activeWorkflow.workflow_id)+'/retry-documentation',{method:'POST'});const p=await r.json();if(!r.ok)throw new Error(apiMessage(p,'Unable to resume recording.'));applyVisitContext(p);visitStage='capture';captureContext=null;resetTranscriptState();renderTranscript();rememberVisit();showToast('The same encounter is ready for a new recording.');}
  catch(e){showToast(e.message,'error');}finally{visitActionBusy=false;renderClinicFlow();}
}
