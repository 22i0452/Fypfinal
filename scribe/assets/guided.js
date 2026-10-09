/* One task per screen. The saved transcript revision gates actual SOAP generation. */
let conversationReview=null,conversationDirty=false,conversationEdits={},conversationEditor=null,conversationSourceOpen=false;
try{
  const storedAutomaticSoap=localStorage.getItem('medflow-automatic-soap');
  // Default ON so a finished recording continues to SOAP after roles/translation.
  // Users can still turn it off from the visit preparation toggle.
  window.medflowAutomaticSoap=storedAutomaticSoap===null?true:storedAutomaticSoap==='true';
}catch{window.medflowAutomaticSoap=true;}
window.hasConversationReview=()=>!!conversationReview && !soapLastSavedNoteId;
window.conversationActionLabel=()=>conversationReview?.status==='TRANSLATION_FAILED'?'Retry translation':conversationReview?.status==='SOAP_FAILED'?'Retry SOAP generation':conversationDirty?'Save & generate SOAP':'Generate SOAP';
function escapeRegExp(value){return String(value||'').replace(/[.*+?^${}()|[\]\\]/g,'\\$&');}
function buildAutoMedicineCorrections(review){
  // Best-effort confirmations so a doctor is not trapped on transcript review when
  // medicine checks only need an explicit attestation / cleaned English line.
  const corrections=[];
  for(const check of review?.medicine_report?.checks||[]){
    if(!check.issues?.length)continue;
    const turn=review.utterances.find(item=>item.utterance_id===check.utterance_id);if(!turn)continue;
    let english=String(turn.clinical_english||'').replace(/^\[Translation (?:requires review|needed)\]\s*/i,'').trim();
    const spellings={};const names=[];
    for(const mention of check.mentions||[]){
      const spelling=String(mention.status==='catalog_name'?mention.name:mention.suggested_english||mention.name||mention.source||'').trim();
      if(!spelling)continue;names.push(spelling);
      if(mention.status!=='catalog_name')spellings[mention.source]=spelling;
    }
    const looksEnglish=/[A-Za-z]{3,}/.test(english)&&!/[\u0600-\u06FF]/.test(english);
    if(!looksEnglish)english=names.length?('Discussed: '+names.join(', ')+'.'):(english||'Medicine wording reviewed.');
    for(const spelling of Object.values(spellings)){
      if(spelling&&!new RegExp(escapeRegExp(spelling),'i').test(english))english+=' '+spelling+'.';
    }
    corrections.push({utterance_id:turn.utterance_id,clinical_english:english,medicines_reviewed:true,medicine_spellings:spellings});
  }
  return corrections;
}
async function postConversationAction(action,body){
  const response=await fetch('/api/workflows/'+encodeURIComponent(activeWorkflow.workflow_id)+'/'+action,{method:action==='conversation'?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const payload=await response.json().catch(()=>({}));
  if(!response.ok)throw new Error(apiMessage(payload,'The saved stage could not be completed.'));
  return payload;
}
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
    conversationReview=msg.conversation_review;fullTranscript=conversationReview.utterances || [];diarizedTranscript=fullTranscript.map(item=>({...item,text:item.original_text}));
    const englishReady=fullTranscript.some(item=>{
      const english=String(item.clinical_english||'').trim();
      return english && !english.startsWith('[Translation requires review]') && !english.startsWith('[Translation needed]');
    });
    const rolesReady=fullTranscript.some(item=>!['unknown',''].includes(String(item.speaker||'').toLowerCase()));
    transcriptMode=englishReady && rolesReady?'english':'urdu';
    if(activeWorkflow)activeWorkflow.state='TRANSCRIPT_REVIEW';visitStage='transcript';captureContext=null;
    renderTranscript();renderClinicFlow();rememberVisit();
    updateRecordingBanner(
      rolesReady?'Conversation saved':'Roles need a quick check',
      conversationReview.medicine_report?.requires_review
        ?'Review flagged medicine wording, then generate SOAP.'
        : englishReady
          ?'Review the wording and roles, then generate SOAP.'
          :'Speaker roles were recovered from the recording. Confirm them, then generate SOAP.'
    );
    refreshActiveContext().catch(()=>{});return;
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
  if(visitLocked() || !conversationReview || !activeWorkflow)return;
  // Never trap the doctor inside an open turn editor — continue means leave review.
  if(conversationEditor){conversationEditor=null;renderTranscript();}
  const epoch=contextRevision;
  visitActionBusy=true;renderClinicFlow();
  try{
    if(conversationReview.status==='TRANSLATION_FAILED'){
      isProcessing=true;visitStage='processing';processSelected='translation';processInspectOpen=false;scheduleContextRefresh();renderClinicFlow();
      const payload=await postConversationAction('retry-translation',{expected_revision:conversationReview.revision,transcript_id:conversationReview.transcript_id});
      if(epoch!==contextRevision)return;
      conversationEdits={};conversationDirty=false;applyVisitContext(payload);
      showToast('Translation restored. Generating SOAP…');
    }
    if(conversationDirty){
      isProcessing=true;visitStage='processing';processSelected='translation';processInspectOpen=false;scheduleContextRefresh();renderClinicFlow();
      const payload=await postConversationAction('conversation',{expected_revision:conversationReview.revision,transcript_id:conversationReview.transcript_id,corrections:Object.values(conversationEdits)});
      if(epoch!==contextRevision)return;
      conversationEdits={};conversationDirty=false;applyVisitContext(payload);
    }
    if(conversationReview.medicine_report?.requires_review){
      const medicineCorrections=buildAutoMedicineCorrections(conversationReview);
      if(medicineCorrections.length){
        isProcessing=true;visitStage='processing';processSelected='translation';processInspectOpen=false;scheduleContextRefresh();renderClinicFlow();
        const payload=await postConversationAction('conversation',{expected_revision:conversationReview.revision,transcript_id:conversationReview.transcript_id,corrections:medicineCorrections});
        if(epoch!==contextRevision)return;
        conversationEdits={};conversationDirty=false;applyVisitContext(payload);
      }
    }
    if(conversationReview.medicine_report?.requires_review){
      const flagged=conversationReview.medicine_report.checks.find(turn=>turn.issues.length);
      const button=Array.from(document.querySelectorAll('[data-edit-conversation]')).find(node=>node.dataset.editConversation===flagged?.utterance_id);
      button?.click();button?.scrollIntoView({block:'center',behavior:'smooth'});
      showToast('Confirm the highlighted medicine spelling, then press Generate SOAP again.','error');
      return;
    }
    isProcessing=true;visitStage='processing';processSelected='draft';processInspectOpen=false;scheduleContextRefresh();renderClinicFlow();
    const payload=await postConversationAction('generate-soap',{expected_revision:conversationReview.revision,transcript_id:conversationReview.transcript_id});
    if(epoch!==contextRevision)return;
    conversationEdits={};conversationDirty=false;conversationEditor=null;applyVisitContext(payload);
    showToast('SOAP draft saved. Review it before approval.');
  }catch(error){
    showToast(error.message||'Could not continue to SOAP.','error');
    try{await refreshActiveContext();}catch{scheduleContextRefresh();}
  }finally{
    visitActionBusy=false;isProcessing=false;
    if(epoch===contextRevision){renderClinicFlow();rememberVisit();}
  }
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
    document.getElementById('workflowStatePill').textContent=conversationDirty?'Unsaved conversation changes':conversationReview?.status==='TRANSLATION_FAILED'?'Translation needs retry':conversationReview?.status==='SOAP_FAILED'?'SOAP needs retry':'Ready for SOAP';
    document.getElementById('visitNextBtn').disabled=false;
    document.getElementById('visitSaveStatus').textContent=conversationDirty?'Unsaved conversation corrections':'Transcript saved to this visit';
    document.getElementById('visitSaveDetail').textContent=conversationDirty
      ?('Revision '+(conversationReview?.revision || '')+' · Save & generate SOAP in one step')
      :(conversationReview?.medicine_report?.requires_review
        ?('Revision '+(conversationReview?.revision || '')+' · Generate SOAP will confirm medicine wording')
        :('Revision '+(conversationReview?.revision || '')+' · Press Generate SOAP to continue'));
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
