/* One task per screen. The saved transcript revision gates actual SOAP generation. */
let conversationReview=null,conversationDirty=false,conversationEdits={},conversationEditor=null,conversationSourceOpen=false;
try{window.medflowAutomaticSoap=localStorage.getItem('medflow-automatic-soap')==='true';}catch{window.medflowAutomaticSoap=false;}
window.hasConversationReview=()=>!!conversationReview && !soapLastSavedNoteId;
window.conversationActionLabel=()=>conversationEditor?'Finish turn edit':conversationDirty?'Save conversation changes':conversationReview?.status==='TRANSLATION_FAILED'?'Retry translation':conversationReview?.status==='SOAP_FAILED'?'Retry SOAP generation':'Generate SOAP';
function setAutomaticSoapMode(value){
  if(visitLocked() || conversationReview || soapLastSavedNoteId)return;
  window.medflowAutomaticSoap=Boolean(value);try{localStorage.setItem('medflow-automatic-soap',String(Boolean(value)));}catch{}
  renderClinicFlow();
}
const guidedBaseLeave=canLeaveVisit;
canLeaveVisit=function(){if(conversationDirty || conversationEditor){showToast('Save or discard your conversation changes before leaving.','error');return false;}return guidedBaseLeave();};
const guidedBaseOpen=openPatientVisit;
openPatientVisit=async function(...args){if(!canLeaveVisit())return false;conversationReview=null;conversationDirty=false;conversationEdits={};conversationEditor=null;conversationSourceOpen=false;document.getElementById('visitView').classList.remove('show-process-inspector');return guidedBaseOpen(...args);};
const guidedBaseContext=applyVisitContext;
applyVisitContext=function(payload,options){
  guidedBaseContext(payload,options);
  conversationReview=payload.conversation_review || null;
  if(conversationReview && !payload.note && !soapLastSavedNoteId && !['CANCELLED','ENCOUNTER_COMPLETED'].includes(activeWorkflow?.state)){
    if(!conversationDirty && !conversationEditor){
      fullTranscript=conversationReview.utterances || [];
      diarizedTranscript=fullTranscript.map(item=>({...item,text:item.original_text}));
      transcriptMode=fullTranscript.some(item=>item.clinical_english)?'english':'urdu';
    }
    isProcessing=['TRANSLATING','GENERATING','EDITING'].includes(conversationReview.status);
    visitStage=isProcessing?'processing':'transcript';
    renderTranscript();scheduleContextRefresh();rememberVisit();
  }
  if(isProcessing && !processInspectOpen){const running=processTrace?.events?.filter(event=>event.status==='running').at(-1);if(running)processSelected=running.stage;}
};
const guidedBaseMessage=handleServerMessage;
handleServerMessage=function(event){
  let msg;try{msg=JSON.parse(event.data);}catch{return;}
  if(msg.type==='conversation_ready'){
    if(!captureContext || msg.patient_id!==captureContext.patientId || msg.workflow_id!==captureContext.workflowId || msg.encounter_id!==captureContext.encounterId || msg.capture_id!==captureContext.captureId)return;
    clearTimeout(recordingStartTimer);stopDurationTimer();isRecording=false;pendingRecordingStart=false;isProcessing=false;setRecordingUI(false);
    conversationReview=msg.conversation_review;fullTranscript=conversationReview.utterances || [];diarizedTranscript=fullTranscript.map(item=>({...item,text:item.original_text}));transcriptMode='english';
    if(activeWorkflow)activeWorkflow.state='TRANSCRIPT_REVIEW';visitStage='transcript';captureContext=null;
    renderTranscript();renderClinicFlow();rememberVisit();updateRecordingBanner('Conversation saved','Review the wording and roles, then generate SOAP.');refreshActiveContext().catch(()=>{});return;
  }
  guidedBaseMessage(event);
};
const guidedBaseTranscript=renderTranscript;
renderTranscript=function(){
  guidedBaseTranscript();if(visitStage!=='transcript' || !conversationReview || soapLastSavedNoteId)return;
  document.querySelectorAll('#transcriptBody [data-utterance-id]').forEach(node=>{
    const id=node.dataset.utteranceId,turn=fullTranscript.find(item=>item.utterance_id===id);if(!turn)return;
    const change=conversationEdits[id];
    if(change){node.classList.add('turn-edited');const label=document.createElement('small');label.className='turn-edit-label';label.textContent='Local correction · save before SOAP';node.append(label);}
    const actions=document.createElement('div');actions.className='conversation-turn-actions';
    const button=document.createElement('button');button.type='button';button.className='note-action';button.textContent=turn.medicine_checks?.issues?.length?'Review medicine':'Edit turn';button.dataset.editConversation=id;button.disabled=visitLocked() || conversationReview.status==='TRANSLATION_FAILED';actions.append(button);node.append(actions);
    if(conversationEditor?.id!==id)return;
    node.classList.add('turn-editing');
    const value={...turn,...change};const editor=document.createElement('div');editor.className='conversation-turn-editor';
    editor.innerHTML=`<label>Speaker<select data-turn-role>${['DOCTOR','PATIENT','NURSE','ATTENDANT','UNKNOWN'].map(role=>`<option value="${role}" ${String(value.speaker).toUpperCase()===role?'selected':''}>${role.charAt(0)+role.slice(1).toLowerCase()}</option>`).join('')}</select></label><label>Relation (for an attendant)<input data-turn-relation maxlength="40" value="${escAttr(value.speaker_relation || '')}"/></label><label class="turn-edit-full">Original wording<textarea data-turn-original dir="auto" maxlength="4000">${escHtml(value.original_text || value.text || '')}</textarea></label><label class="turn-edit-full">English wording<textarea data-turn-english maxlength="4000">${escHtml(value.clinical_english || '')}</textarea></label><div class="conversation-turn-actions turn-edit-full"><button class="note-action primary" type="button" data-turn-done="${escAttr(id)}">Done</button><button class="note-action" type="button" data-turn-cancel>Cancel</button></div>`;editor.querySelector('.conversation-turn-actions').insertAdjacentHTML('beforebegin',window.medicineEditorFields?.(value) || '');node.append(editor);
  });
};
document.addEventListener('click',event=>{
  const edit=event.target.closest('[data-edit-conversation]'),done=event.target.closest('[data-turn-done]');
  if(edit){if(conversationEditor){showToast('Finish or cancel the current turn edit first.','error');return;}conversationEditor={id:edit.dataset.editConversation};renderTranscript();renderClinicFlow();}
  if(event.target.closest('[data-turn-cancel]')){conversationEditor=null;renderTranscript();renderClinicFlow();}
  if(done){
    const editor=done.closest('.conversation-turn-editor'),id=done.dataset.turnDone,source=conversationReview.utterances.find(item=>item.utterance_id===id);
    const original=editor.querySelector('[data-turn-original]').value.trim(),english=editor.querySelector('[data-turn-english]').value.trim();
    if(!original){showToast('Keep the turn wording, or correct it; an empty turn cannot be saved.','error');return;}
    const speaker=editor.querySelector('[data-turn-role]').value,relation=editor.querySelector('[data-turn-relation]').value.trim();
    const change={utterance_id:id};
    if(original!==source.original_text)change.original_text=original;
    if(english && english!==source.clinical_english)change.clinical_english=english;
    if(speaker!==String(source.speaker).toUpperCase() || relation!==(source.speaker_relation || '')){change.speaker=speaker;change.speaker_relation=speaker==='ATTENDANT'?relation:null;}
    if(editor.querySelector('[data-medicines-reviewed]')?.checked){change.medicines_reviewed=true;change.medicine_spellings={};editor.querySelectorAll('[data-medicine-spelling]').forEach(input=>{if(input.value.trim())change.medicine_spellings[input.dataset.medicineSpelling]=input.value.trim();});}
    if(Object.keys(change).length>1)conversationEdits[id]=change;else delete conversationEdits[id];
    conversationDirty=Object.keys(conversationEdits).length>0;conversationEditor=null;
    fullTranscript=conversationReview.utterances.map(turn=>{const c=conversationEdits[turn.utterance_id] || {};const result={...turn,...c};result.speaker=String(result.speaker).charAt(0).toUpperCase()+String(result.speaker).slice(1).toLowerCase();result.text=transcriptMode==='english'?(result.clinical_english || result.original_text):result.original_text;return result;});
    diarizedTranscript=fullTranscript.map(turn=>({...turn,text:turn.original_text}));renderTranscript();renderClinicFlow();
  }
});
function discardConversationChanges(){if(visitLocked())return;conversationEdits={};conversationEditor=null;conversationDirty=false;fullTranscript=conversationReview.utterances;diarizedTranscript=fullTranscript.map(turn=>({...turn,text:turn.original_text}));renderTranscript();renderClinicFlow();}
window.advanceConversationReview=async function(){
  if(visitLocked() || conversationEditor || !conversationReview)return;
  if(!conversationDirty && conversationReview.medicine_report?.requires_review && conversationReview.status!=='TRANSLATION_FAILED'){document.querySelector('#transcriptBody [data-edit-conversation]')?.focus();const flagged=conversationReview.medicine_report.checks.find(turn=>turn.issues.length);const button=Array.from(document.querySelectorAll('[data-edit-conversation]')).find(node=>node.dataset.editConversation===flagged?.utterance_id);button?.click();button?.scrollIntoView({block:'center',behavior:'smooth'});showToast('Review the flagged medicine wording before generating SOAP.','error');return;}
  const action=conversationDirty?'conversation':conversationReview.status==='TRANSLATION_FAILED'?'retry-translation':'generate-soap';
  const workflowId=activeWorkflow.workflow_id,epoch=contextRevision;
  const body={expected_revision:conversationReview.revision,transcript_id:conversationReview.transcript_id};if(conversationDirty)body.corrections=Object.values(conversationEdits);
  visitActionBusy=true;if(action!=='conversation'){isProcessing=true;visitStage='processing';processSelected=action==='retry-translation'?'translation':'draft';processInspectOpen=false;scheduleContextRefresh();}renderClinicFlow();
  try{
    const response=await fetch('/api/workflows/'+encodeURIComponent(workflowId)+'/'+action,{method:action==='conversation'?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const payload=await response.json();if(!response.ok)throw new Error(apiMessage(payload,'The saved stage could not be completed.'));
    if(epoch!==contextRevision)return;
    conversationEdits={};conversationDirty=false;conversationEditor=null;applyVisitContext(payload);
    showToast(action==='conversation'?'Conversation corrections saved. Review before generating SOAP.':action==='retry-translation'?'Translation restored. Review the conversation.':'SOAP draft saved. Review it before approval.');
  }catch(error){showToast(error.message,'error');try{await refreshActiveContext();}catch{scheduleContextRefresh();}}
  finally{visitActionBusy=false;if(epoch===contextRevision){renderClinicFlow();rememberVisit();}}
};
const guidedBaseProcess=renderProcess;
renderProcess=function(){guidedBaseProcess();document.getElementById('processObservatory')?.classList.toggle('inspection-closed',!processInspectOpen && !processReplay);};
function toggleGuidedProcess(){processInspectOpen=!processInspectOpen;document.getElementById('visitView').classList.toggle('show-process-inspector',processInspectOpen);renderClinicFlow();}
toggleProcessInspection=function(){toggleGuidedProcess();};
processPick=function(stage){processSelected=stage;processInspectOpen=true;document.getElementById('visitView').classList.add('show-process-inspector');renderClinicFlow();};
function toggleConversationSource(force){conversationSourceOpen=typeof force==='boolean'?force:!conversationSourceOpen;renderClinicFlow();if(conversationSourceOpen)renderTranscript();}
const guidedLocateSource=locateEvidenceSource;
locateEvidenceSource=function(id){if(!fullTranscript.some(turn=>turn.utterance_id===id))return;if(soapLastSavedNoteId)toggleConversationSource(true);guidedLocateSource(id);};
const guidedSectionSource=showSoapEvidence;
showSoapEvidence=function(section){if(soapLastSavedNoteId)toggleConversationSource(true);guidedSectionSource(section);};
document.addEventListener('click',event=>{const source=event.target.closest('#soapContent [data-source-id]');if(source && soapLastSavedNoteId)locateEvidenceSource(source.dataset.sourceId);});
const guidedBaseFlow=renderClinicFlow;
renderClinicFlow=function(){
  guidedBaseFlow();
  const view=document.getElementById('visitView');view.classList.toggle('source-drawer-open',conversationSourceOpen);
  const inspector=document.getElementById('guidedProcessToggle');inspector.hidden=!processTrace;inspector.setAttribute('aria-expanded',String(processInspectOpen));inspector.querySelector('span').textContent=processInspectOpen?'Close process':'Inspect process';
  const source=document.getElementById('conversationSourceToggle');source.hidden=visitStage!=='review' || !soapLastSavedNoteId;source.setAttribute('aria-expanded',String(conversationSourceOpen));source.querySelector('span').textContent=conversationSourceOpen?'Close conversation':'View conversation';
  const toggle=document.getElementById('automaticSoapToggle');toggle.checked=Boolean(window.medflowAutomaticSoap);toggle.disabled=visitLocked() || !!conversationReview || !!soapLastSavedNoteId;
  document.getElementById('automaticSoapHint').textContent=window.medflowAutomaticSoap?'On · SOAP follows translation automatically.':'Off · review the conversation before generating a note.';
  const bar=document.getElementById('conversationReviewBar');bar.hidden=visitStage!=='transcript';
  if(conversationReview){bar.innerHTML=`<div><span class="section-kicker">SAVED CONVERSATION · REVISION ${conversationReview.revision}</span><h3>Review the source first.</h3><p>Check wording and speaker roles. Original and English views stay paired by turn ID.</p></div><div>${MedFlowEvidence.badge(conversationDirty?'review':'received',conversationDirty?'Unsaved corrections':'Conversation stored')}${conversationDirty?'<button class="note-action" onclick="discardConversationChanges()" type="button">Discard changes</button>':''}</div>${conversationReview.last_error?`<p class="conversation-error" role="alert">${escHtml(conversationReview.last_error)}</p>`:''}`;}
  if(visitStage==='transcript'){
    document.getElementById('workflowStatePill').textContent=conversationDirty?'Unsaved conversation changes':conversationReview?.status==='TRANSLATION_FAILED'?'Translation needs retry':conversationReview?.status==='SOAP_FAILED'?'SOAP needs retry':'Conversation review';
    document.getElementById('visitNextBtn').disabled ||= !!conversationEditor;
    document.getElementById('visitSaveStatus').textContent=conversationDirty?'Unsaved conversation corrections':'Transcript saved to this visit';
    document.getElementById('visitSaveDetail').textContent='Revision '+(conversationReview?.revision || '')+' · SOAP starts when you continue';
  }
  if(visitStage==='processing'){
    document.getElementById('visitStageTitle').textContent=conversationReview?.status==='GENERATING' || processSelected==='draft'?'A note from your reviewed conversation.':'Preparing the conversation.';
    document.getElementById('visitNextBtn').textContent=conversationReview?.status==='GENERATING' || processSelected==='draft'?'Generating SOAP':'Processing conversation';
  }
  if(visitStage==='transcript' || visitStage==='review')document.querySelectorAll('.visit-step[data-stage="prepare"],.visit-step[data-stage="capture"]').forEach(button=>button.disabled=true);else document.querySelectorAll('.visit-step[data-stage="prepare"],.visit-step[data-stage="capture"]').forEach(button=>button.disabled=false);
  document.getElementById('roleCorrectionBtn').hidden ||= !soapLastSavedNoteId;
  studioIcons();
};
window.addEventListener('beforeunload',event=>{if(conversationDirty || conversationEditor){event.preventDefault();event.returnValue='';}});
document.addEventListener('DOMContentLoaded',()=>renderClinicFlow());
