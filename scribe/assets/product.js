/* Version-bound coding and navigation for one connected visit. */
let codingError='',codingEvidence=null,codingEvidenceClaim='',codingRequestEpoch=0,codingOperation='loading';
resolveCodingNote=function(){
  const id=codingNoteId || soapLastSavedNoteId || selectedNoteId;if(!id)return null;
  const saved=savedNotes.find(item=>item.note_id===id);if(saved)return saved;
  if(generatedSoap && soapLastSavedNoteId===id)return {note_id:id,patient_id:selectedPatient?._id,patient_name:selectedPatient?.name,state:generatedNoteState,version:currentNoteVersion,soap:generatedSoap};
  return null;
};
function goMedflowHome(){if(canLeaveVisit())location.assign('/');}
function goDemoTests(){if(canLeaveVisit())location.assign('/testing');}
function codingDisabledReason(){
  if(!workspaceCodingEnabled)return 'Clinical coding has not been enabled for this clinic.';
  if(!soapLastSavedNoteId)return 'Generate and save a SOAP draft first.';
  if(soapDraftTouched || Object.values(soapSectionEditing).some(Boolean))return 'Save or cancel your SOAP edits before coding.';
  if(visitLocked())return 'Finish the current action before opening coding.';
  return '';
}
function renderSoapCodingEntry(){
  const root=document.querySelector('#soapContent .soap-header');if(!root)return;
  let entry=root.querySelector('.soap-coding-entry');
  if(!entry){entry=document.createElement('div');entry.className='soap-coding-entry';root.append(entry);}
  const reason=codingDisabledReason();
  entry.innerHTML=`<button class="note-action coding-entry-button" type="button" onclick="openCodingFromNote(false)" ${reason?'disabled':''} aria-describedby="soapCodingReason">${studioIcon('scan-line')}<span>ICD-10 / CPT</span>${studioIcon('arrow-up-right')}</button><p id="soapCodingReason">${escHtml(reason || 'Suggestions with a traceable source. Doctor review required.')}</p>`;
}
const productBaseSoap=renderSoapNote;
renderSoapNote=function(...args){productBaseSoap(...args);renderSoapCodingEntry();};
const productBaseFlow=renderClinicFlow;
renderClinicFlow=function(){productBaseFlow();renderSoapCodingEntry();renderVisitContinuity();};
function renderVisitContinuity(){
  const root=document.getElementById('visitContinuity');if(!root)return;root.hidden=!activeWorkflow;
  if(!activeWorkflow)return;
  const state=activeWorkflow.state;
  const effectiveState=['FAILED','HUMAN_ASSISTANCE_REQUIRED'].includes(state)?activeWorkflow.resume_state:state;
  const verified=['PATIENT_VERIFIED','INTAKE_IN_PROGRESS','INTAKE_COMPLETED','BOOKING_REQUIRED','BOOKING_CONFIRMED','PATIENT_CHECKED_IN','CONSULTATION_READY','CONSULTATION_ACTIVE','DOCUMENTATION_PROCESSING','TRANSCRIPT_REVIEW','NOTE_REVIEW_REQUIRED','NOTE_APPROVED','ENCOUNTER_COMPLETED'].includes(effectiveState);
  const milestones=[['calendar-check','Appointment',activeAppointment?.status==='CONFIRMED' || activeAppointment?.status==='COMPLETED'],['shield-check','Verified',verified],['stethoscope','Check-in',!!activeEncounter],['file-check-2','Approved record',generatedNoteState==='APPROVED_BY_DOCTOR']];
  root.innerHTML=milestones.map(([icon,label,complete])=>`<span class="${complete?'complete':''}">${studioIcon(complete?'check':icon)}${label}</span>`).join('')+`<details><summary>Visit receipt</summary><dl><dt>Workflow</dt><dd>${escHtml(activeWorkflow.workflow_id)}</dd><dt>Appointment</dt><dd>${escHtml(activeAppointment?.appointment_id || 'Pending')}</dd><dt>Encounter</dt><dd>${escHtml(activeEncounter?.encounter_id || 'Pending')}</dd><dt>Note</dt><dd>${escHtml(soapLastSavedNoteId || 'Pending')}</dd></dl></details>`;
}
showCodingWorkspace=async function(options={}){
  if(!canLeaveVisit())return;
  codingNoteId=options.noteId || soapLastSavedNoteId || selectedNoteId || '';
  codingSuggestions=[];codingError='';codingEvidence=null;
  setView('coding');document.getElementById('eyebrowText').textContent='CLINICAL CODING';
  renderCodingWorkspace();if(codingNoteId)await loadCodingSuggestions(codingNoteId);
  // Generation always needs an explicit action, including from archived records.
};
loadCodingSuggestions=async function(noteId){
  if(!noteId || codingBusy)return;
  const epoch=++codingRequestEpoch;codingBusy=true;codingOperation='loading';codingError='';renderCodingWorkspace();
  try{
    const response=await fetch('/api/notes/'+encodeURIComponent(noteId)+'/code-suggestions');
    const payload=await response.json();
    if(!response.ok)throw new Error(apiMessage(payload,'Unable to load this coding source.'));
    if(epoch!==codingRequestEpoch)return;
    savedNotes=[payload.source_note,...savedNotes.filter(item=>item.note_id!==noteId)];codingSuggestions=payload.suggestions || [];
  }catch(error){codingError=error.message;codingSuggestions=[];}
  finally{if(epoch===codingRequestEpoch){codingBusy=false;renderCodingWorkspace();}}
};
renderCodingWorkspace=function(){
  const note=resolveCodingNote(),current=codingSuggestions.filter(item=>!item.stale);
  const title=document.getElementById('codingNoteTitle');if(!title)return;
  title.textContent=note?.patient_name || 'No note selected';
  document.getElementById('codingNoteSubtitle').textContent=note?'Saved SOAP · version '+(note.version || currentNoteVersion || '—')+' · '+String(note.state || '').replaceAll('_',' '):'Generate and save a SOAP draft before requesting codes.';
  const reason=!note?'A saved SOAP draft is required.':!workspaceCodingEnabled?'Clinical coding has not been enabled for this clinic.':'';
  document.getElementById('codingStatusPill').textContent=codingBusy?'Working…':codingError?'Needs attention':reason?'Unavailable':current.length?current.length+' current suggestions':'Ready for review';
  const generate=document.getElementById('codingGenerateBtn');generate.disabled=codingBusy || !!reason;generate.innerHTML=studioIcon('scan-line')+(current.length?'Load current suggestions':'Generate ICD-10 / CPT');
  document.getElementById('codingRegenerateBtn').disabled=codingBusy || !!reason || !current.length;
  document.getElementById('codingStateMessage').innerHTML=reason?`<p>${escHtml(reason)}</p>${!workspaceCodingEnabled?'<details><summary>Clinic setup</summary><p>Enable <code>ICD_CODING_ENABLED=true</code> on the server, then restart. Coding uses the existing configured AI gateway.</p></details>':''}`:codingError?`<p role="alert">${escHtml(codingError)}</p><button class="note-action" type="button" onclick="loadCodingSuggestions(codingNoteId)">Reload saved results</button>`:'<p>Reference links are checked separately from code validity and clinical correctness.</p>';
  const soap=note?.soap || {};
  document.getElementById('codingNoteSummary').innerHTML=note?`<div class="coding-version-receipt">${MedFlowEvidence.badge('received','Saved source · v'+(note.version || currentNoteVersion || '—'))}<span>Doctor review required</span></div>${['subjective','assessment','plan'].map(section=>`<details class="coding-soap-section"><summary>${escHtml(section.charAt(0).toUpperCase()+section.slice(1))}</summary><p>${escHtml(soap[section] || 'Not documented.')}</p></details>`).join('')}`:'<p class="evidence-empty">Choose a saved note to begin.</p>';
  renderCodingResults();studioIcons();
};
renderCodingResults=function(){
  const root=document.getElementById('codingResults');if(!root)return;
  if(codingBusy){const action={loading:'Loading the saved SOAP and suggestions…',generating:'Requesting code suggestions…',evidence:'Resolving the saved evidence chain…',review:'Saving your code review…'}[codingOperation];root.innerHTML='<div class="coding-pending" role="status">'+studioIcon('loader-circle')+action+'<p>Saved results remain attached to their note version.</p></div>';return;}
  const current=codingSuggestions.filter(item=>!item.stale),old=codingSuggestions.filter(item=>item.stale);
  root.innerHTML=current.length?`<div class="coding-columns">${[['ICD-10','Diagnosis / symptoms'],['CPT','Documented services']].map(([system,label])=>`<section class="coding-column"><span class="section-kicker">${system}</span><h4>${label}</h4><div class="coding-list">${current.filter(item=>item.system===system).map(renderCodingCard).join('') || '<p class="coding-empty">No supported suggestions in this category.</p>'}</div></section>`).join('')}</div>`:`<div class="coding-pending">${studioIcon('scan-line')}<h4>${codingError?'Generation needs attention':'The next layer of the record.'}</h4><p>${old.length?'SOAP changed. Generate suggestions for the current version.':workspaceCodingEnabled?'Generate suggestions, then follow each code to its supporting statement and conversation.':'Suggestions become available when clinical coding is enabled.'}</p></div>`;
  if(old.length)root.innerHTML+=`<details class="coding-history"><summary>${old.length} earlier-version suggestion(s) · read only</summary>${old.map(renderCodingCard).join('')}</details>`;
  studioIcons();
};
renderCodingCard=function(item){
  const status=(item.stale?'Earlier version · ':'')+String(item.status || 'SUGGESTED').replaceAll('_',' '),pending=item.status==='SUGGESTED' && !item.stale;
  return `<article class="coding-card ${item.stale?'coding-stale':''}"><button class="code-evidence-open" data-code-evidence="${escAttr(item.code_suggestion_id)}" type="button"><span class="coding-card-top"><strong>${escHtml(item.code)}</strong>${MedFlowEvidence.badge(item.stale?'missing':item.status==='APPROVED'?'checked':'review',status)}</span><span class="code-description">${escHtml(item.description)}</span><span class="code-evidence-hint">${studioIcon('git-branch')}${(item.evidence_ids || []).length} SOAP statement(s) · inspect sources ${studioIcon('arrow-up-right')}</span></button>${pending?`<div class="detail-actions"><button class="note-action" data-code-review="${escAttr(item.code_suggestion_id)}" data-approve="true" type="button">${studioIcon('check')}Approve suggestion</button><button class="note-action" data-code-review="${escAttr(item.code_suggestion_id)}" data-approve="false" type="button">Reject</button></div>`:''}</article>`;
};
generateCodingSuggestions=async function(force=false){
  const note=resolveCodingNote();if(codingBusy || !note?.note_id || !workspaceCodingEnabled)return;
  codingBusy=true;codingOperation='generating';codingError='';renderCodingWorkspace();
  try{
    const response=await fetch('/api/notes/'+encodeURIComponent(note.note_id)+'/code-suggestions'+(force?'?force=true':''),{method:'POST'}),payload=await response.json();
    if(!response.ok)throw new Error(apiMessage(payload,'Code generation failed. Retry from the saved note.'));
    if(payload.source_note)savedNotes=[payload.source_note,...savedNotes.filter(item=>item.note_id!==note.note_id)];
    codingSuggestions=[...(payload.suggestions || []),...codingSuggestions.filter(item=>item.stale)];
    showToast('Suggestions saved. Inspect their evidence before review.');
  }catch(error){codingError=error.message;showToast(error.message,'error');}
  finally{codingBusy=false;renderCodingWorkspace();}
};
reviewCodingSuggestion=async function(id,approve){
  if(codingBusy)return;codingBusy=true;codingOperation='review';codingError='';renderCodingWorkspace();
  try{
    const response=await fetch('/api/code-suggestions/'+encodeURIComponent(id)+'/'+(approve?'approve':'reject'),{method:'POST'}),payload=await response.json();
    if(!response.ok)throw new Error(apiMessage(payload,'This suggestion could not be reviewed.'));
    codingSuggestions=codingSuggestions.map(item=>item.code_suggestion_id===id?{...payload,stale:false}:item);
  }catch(error){codingError=error.message;}
  finally{codingBusy=false;renderCodingWorkspace();}
};
async function openCodeEvidence(id){
  if(codingBusy)return;codingBusy=true;codingOperation='evidence';codingError='';renderCodingWorkspace();
  try{
    const response=await fetch('/api/code-suggestions/'+encodeURIComponent(id)+'/evidence'),payload=await response.json();
    if(!response.ok)throw new Error(apiMessage(payload,'This evidence is unavailable.'));
    codingEvidence=payload;codingEvidenceClaim=payload.claims[0]?.claim_id || '';renderCodeEvidence();
  }catch(error){codingError=error.message;}
  finally{codingBusy=false;renderCodingWorkspace();}
}
function renderCodeEvidence(){
  if(!codingEvidence)return;
  let dialog=document.getElementById('codingEvidenceDialog');
  if(!dialog){dialog=document.createElement('dialog');dialog.id='codingEvidenceDialog';dialog.className='evidence-dialog coding-evidence-dialog';dialog.setAttribute('aria-label','Code, SOAP statement and conversation evidence');dialog.addEventListener('click',event=>{if(event.target===dialog || event.target.closest('[data-code-close]'))dialog.close();});dialog.addEventListener('close',()=>document.querySelector(`[data-code-evidence="${CSS.escape(codingEvidence?.suggestion.code_suggestion_id || '')}"]`)?.focus());document.body.append(dialog);}
  const data=codingEvidence,item=data.suggestion,claim=data.claims.find(row=>row.claim_id===codingEvidenceClaim);
  dialog.innerHTML=`<header class="evidence-dialog-head"><div><span class="section-kicker">${escHtml(item.system)} · SOURCE CHAIN</span><h3>${escHtml(item.code)}</h3><p>${escHtml(item.description)}</p></div><button class="note-action" type="button" data-code-close aria-label="Close coding evidence">Close ×</button></header><div class="coding-chain-labels"><span>01 · Code suggestion</span>${studioIcon('chevron-right')}<span>02 · SOAP statement</span>${studioIcon('chevron-right')}<span>03 · Conversation</span></div><p class="evidence-scope">${data.stale?'Earlier SOAP version · read only. Generate current suggestions before review.':'Saved SOAP version '+data.version+'. Links show recorded attribution.'} Code validity and clinical correctness remain unassessed.</p><div class="coding-evidence-grid"><section><h4>Supporting SOAP</h4>${data.claims.map(row=>`<button class="coding-claim ${row.claim_id===codingEvidenceClaim?'active':''}" type="button" data-code-claim="${escAttr(row.claim_id)}"><small>${escHtml(row.section.toUpperCase())}</small><span>${escHtml(row.text)}</span></button>`).join('') || '<p class="evidence-empty">The referenced statement is unavailable.</p>'}${data.missing_claim_ids.length?'<p class="conversation-error">Some statement references could not be resolved.</p>':''}</section><section><h4>Original conversation</h4>${claim?(claim.sources.map(source=>`<article class="coding-conversation-turn"><span class="section-kicker">${escHtml(source.speaker || 'Unknown')} · ${escHtml(source.utterance_id)}</span><blockquote dir="auto">${escHtml(source.original_text || 'Original source unavailable')}</blockquote>${source.clinical_english?`<p>${escHtml(source.clinical_english)}</p>`:''}${source.available?`<button class="note-action" data-code-source="${escAttr(source.utterance_id)}" type="button">${studioIcon('quote')}Open original turn</button>`:''}</article>`).join('') || '<p class="evidence-empty">This SOAP statement has no conversation source attached. No source has been inferred.</p>'):'<p class="evidence-empty">Select a statement to inspect its source.</p>'}</section></div><div class="coding-check-strip">${MedFlowEvidence.badge(data.missing_claim_ids.length?'failed':'checked',data.missing_claim_ids.length?'Reference check failed':'SOAP references linked')}${MedFlowEvidence.badge('missing','Clinical correctness unassessed')}${MedFlowEvidence.badge('missing','Catalog validity unassessed')}</div><button class="note-action" type="button" data-code-open-visit ${data.stale || !claim?'disabled':''}>${studioIcon('arrow-up-right')}Open statement in SOAP</button><details class="evidence-technical"><summary>Technical receipt · version, sources and method</summary><dl>${Object.entries({suggestion_id:item.code_suggestion_id,note_id:data.note_id,note_version_id:data.note_version_id,transcript_id:data.transcript_id,claim_ids:item.evidence_ids,method:item.generation_method,generation_ms:item.generation_duration_ms,provider_score:item.confidence,score_interpretation:data.confidence_status,reviewed_by:item.reviewed_by_actor_id || 'Pending',reviewed_at:item.reviewed_at || 'Pending',decision:item.status}).map(([key,value])=>`<div><dt>${escHtml(key.replaceAll('_',' '))}</dt><dd>${escHtml(Array.isArray(value)?value.join(', '):String(value ?? 'Unavailable'))}</dd></div>`).join('')}</dl></details>`;
  if(!dialog.open)dialog.showModal();studioIcons();
}
function openCodeOriginal(id){
  const data=codingEvidence,claim=data?.claims.find(row=>row.claim_id===codingEvidenceClaim),source=claim?.sources.find(row=>row.utterance_id===id);if(!source?.available)return;
  document.getElementById('codingEvidenceDialog').close();
  const key='code-turn:'+data.suggestion.code_suggestion_id+':'+id;
  MedFlowEvidence.register(key,{title:id+' · original conversation',status:'received',label:'Saved source',raw:source.original_text,interpretation:source.clinical_english,scope:'Conversation source of the selected SOAP statement in version '+data.version+'. Linking does not establish whether the code is correct.',checks:[{code:'SOURCE_MEMBERSHIP',status:'passed',label:'Source exists',detail:'The turn belongs to the saved transcript for this patient and encounter.'},{code:'CLINICAL_CORRECTNESS',status:'unassessed',label:'Clinical correctness',detail:'Not measured by source linkage.'}],technical:{suggestion_id:data.suggestion.code_suggestion_id,note_version_id:data.note_version_id,transcript_id:data.transcript_id,utterance_id:id}});MedFlowEvidence.open(key);
}
async function returnCodingToVisit(withClaim=false){
  if(codingBusy || !canLeaveVisit())return;
  const note=resolveCodingNote();if(!note)return showVisitWorkspace();
  const patient=allPatients.find(item=>item._id===note.patient_id);
  if(!patient)return showToast('The patient for this note is not available to this account.','error');
  if(withClaim && (codingEvidence?.stale || codingEvidence?.note_id!==note.note_id))return;
  document.getElementById('codingEvidenceDialog')?.close();
  if(!await openPatientVisit(patient,{noteId:note.note_id}))return;
  if(withClaim && currentNoteVersion!==codingEvidence.version){showToast('SOAP changed. Reopen coding to load the current version.','error');return;}
  chooseVisitStage('review');
  if(withClaim){const claim=codingEvidence.claims.find(row=>row.claim_id===codingEvidenceClaim),section=document.querySelectorAll('#soapContent .soap-section')[['subjective','objective','assessment','plan'].indexOf(claim.section)],statement=[...(section?.querySelectorAll('.evidence-span') || [])].find(node=>node.textContent===claim.text);statement?.classList.add('coding-linked-claim');(statement || section)?.scrollIntoView({behavior:'smooth',block:'center'});}
}
document.addEventListener('click',event=>{
  const code=event.target.closest('[data-code-evidence]'),claim=event.target.closest('[data-code-claim]'),source=event.target.closest('[data-code-source]'),review=event.target.closest('[data-code-review]');
  if(code)openCodeEvidence(code.dataset.codeEvidence);
  if(claim){codingEvidenceClaim=claim.dataset.codeClaim;renderCodeEvidence();}
  if(source)openCodeOriginal(source.dataset.codeSource);
  if(review)reviewCodingSuggestion(review.dataset.codeReview,review.dataset.approve==='true');
  if(event.target.closest('[data-code-open-visit]'))returnCodingToVisit(true);
});
document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('a.agent-switch').forEach(link=>link.addEventListener('click',event=>{if(!canLeaveVisit())event.preventDefault();}));
  renderSoapCodingEntry();renderVisitContinuity();
});
