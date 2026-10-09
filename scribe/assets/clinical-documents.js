/* Compact source selection and versioned doctor prescription worksheet. */
let clinicalDocument=null,clinicalDocumentDirty=false,clinicalDocumentBusy=false;
const docEscape=value=>escHtml(String(value??''));
function clinicalDocumentDialog(){
  let dialog=document.getElementById('clinicalDocumentDialog');if(dialog)return dialog;
  dialog=document.createElement('dialog');dialog.id='clinicalDocumentDialog';dialog.className='clinical-document-dialog';dialog.setAttribute('aria-labelledby','clinicalDocumentTitle');
  dialog.innerHTML='<div class="document-shell"><header id="documentHeader"></header><nav id="documentTabs" role="tablist"></nav><div id="documentPanel" class="document-panel" role="tabpanel"></div><p id="documentMessage" role="status"></p><footer id="documentFooter"></footer></div>';
  dialog.addEventListener('cancel',event=>{if(clinicalDocumentBusy||clinicalDocumentDirty){event.preventDefault();documentMessage('Save your changes or use Discard & close.');}});
  dialog.addEventListener('close',()=>{clinicalDocument=null;clinicalDocumentDirty=false;clinicalDocumentBusy=false;});
  dialog.querySelector('#documentTabs').addEventListener('keydown',event=>{
    const tabs=[...dialog.querySelectorAll('[data-document-tab]')],i=tabs.indexOf(event.target);if(i<0)return;
    const next=event.key==='ArrowRight'?(i+1)%tabs.length:event.key==='ArrowLeft'?(i+tabs.length-1)%tabs.length:event.key==='Home'?0:event.key==='End'?tabs.length-1:null;
    if(next===null)return;event.preventDefault();tabs[next].click();dialog.querySelectorAll('[data-document-tab]')[next]?.focus();
  });
  document.body.append(dialog);return dialog;
}
function documentMessage(text){const node=document.getElementById('documentMessage');if(node)node.textContent=text;}
function closeClinicalDocument(discard=false){if(clinicalDocumentBusy)return;if(clinicalDocumentDirty&&!discard){documentMessage('Save your changes or use Discard & close.');return;}clinicalDocumentDialog().close();}
function clinicalDocumentHeader(title,subtitle){return `<div><span class="section-kicker">CLINICAL DOCUMENTATION</span><h2 id="clinicalDocumentTitle">${docEscape(title)}</h2><p>${docEscape(subtitle)}</p></div><button type="button" class="icon-btn" data-document-close aria-label="Close">${studioIcon('x')}</button>`;}
function documentTabs(tabs){return tabs.map(([key,label,count])=>`<button type="button" role="tab" aria-selected="${clinicalDocument.tab===key}" tabindex="${clinicalDocument.tab===key?'0':'-1'}" data-document-tab="${key}">${docEscape(label)}${count===undefined?'':`<small>${count}</small>`}</button>`).join('');}
function documentVersionCurrent(){return clinicalDocument?.noteId===soapLastSavedNoteId&&clinicalDocument?.version===currentNoteVersion;}
function applyClinicalNote(payload){
  soapLastSavedNoteId=payload.note_id;currentNoteVersion=payload.version;generatedNoteState=payload.state;
  generatedSoap=normalizeSoapDraft(payload.soap);fullTranscript=payload.transcript||fullTranscript;
  diarizedTranscript=fullTranscript.map(t=>({...t,text:t.original_text}));soapDraftTouched=false;soapSectionEditing={};
  soapSectionSnapshots={};upsertSavedNote(payload);visitStage=payload.state==='APPROVED_BY_DOCTOR'?'finish':'review';
  renderSoapNote(generatedSoap,fullTranscript);renderClinicFlow();rememberVisit();
}
async function clinicalApi(url,options){const response=await fetch(url,options),payload=await response.json();if(!response.ok)throw new Error(apiMessage(payload,'The document could not be saved.'));return payload;}
function sourceExtractDraft(soap){
  return soap?.generation_mode==='TRANSCRIPT_FALLBACK'||(soap?.structured_soap?.warnings||[]).some(w=>/transcript-based draft|model draft was unavailable|transcript-grounded fallback|fallback_draft_requires_clinician_review/i.test(String(w)));
}
async function rebuildSavedSoap(){
  if(visitLocked()||!soapLastSavedNoteId||generatedNoteState==='APPROVED_BY_DOCTOR')return;
  if(soapDraftTouched||Object.values(soapSectionEditing).some(Boolean)||conversationDirty||conversationEditor){showToast('Save your wording changes before rebuilding SOAP.','error');return;}
  const noteId=soapLastSavedNoteId,version=currentNoteVersion,epoch=contextRevision;
  clinicalDocumentBusy=true;visitActionBusy=true;renderSoapNote(generatedSoap,fullTranscript);renderClinicFlow();
  try{
    const payload=await clinicalApi('/api/notes/'+encodeURIComponent(noteId)+'/regenerate-soap',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:version})});
    if(epoch!==contextRevision||noteId!==soapLastSavedNoteId)return;
    delete afterVisitSummaries[noteId];applyClinicalNote(payload);showToast('SOAP rebuilt from your reviewed conversation. Review this new draft.');
  }catch(error){if(epoch===contextRevision)showToast(error.message,'error');}
  finally{clinicalDocumentBusy=false;visitActionBusy=false;if(epoch===contextRevision){renderSoapNote(generatedSoap,fullTranscript);renderClinicFlow();}}
}
async function openPrescription(){
  if(visitLocked()||soapDraftTouched||Object.values(soapSectionEditing).some(Boolean)){showToast('Save the SOAP wording before opening its prescription.','error');return;}
  if(!soapLastSavedNoteId)return;
  const dialog=clinicalDocumentDialog(),noteId=soapLastSavedNoteId,version=currentNoteVersion,epoch=contextRevision;
  clinicalDocument={kind:'prescription',tab:'preview',noteId,version,patient:selectedPatient?.name||'Patient',soap:{...generatedSoap},selected:0};
  clinicalDocumentDirty=false;clinicalDocumentBusy=true;dialog.showModal();
  document.getElementById('documentHeader').innerHTML=clinicalDocumentHeader('Prescription','Preparing the layout from the saved Plan.');
  document.getElementById('documentTabs').innerHTML='';document.getElementById('documentPanel').innerHTML='<div class="document-loading">'+studioIcon('file-text')+'<p>Preparing medication instructions…</p></div>';document.getElementById('documentFooter').innerHTML='';documentMessage('');
  try{
    const payload=generatedSoap.prescription?{prescription:generatedSoap.prescription}:await clinicalApi('/api/notes/'+encodeURIComponent(noteId)+'/prescription/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:version})});
    if(epoch!==contextRevision||noteId!==soapLastSavedNoteId)return;
    clinicalDocument.value=structuredClone(payload.prescription);clinicalDocumentBusy=false;renderPrescriptionDocument();
  }catch(error){clinicalDocumentBusy=false;documentMessage(error.message);document.getElementById('documentPanel').innerHTML='<div class="document-empty">The saved SOAP is preserved. Close this view and retry preparation.</div>';}
  finally{clinicalDocumentBusy=false;renderClinicFlow();}
}
function prescriptionPreview(value,soap,patient){
  const positive=value.medicines.filter(r=>!['stop','avoid'].includes(r.action)),cautions=value.medicines.filter(r=>['stop','avoid'].includes(r.action));
  return `<article class="prescription-sheet"><header><span class="section-kicker">MEDFLOW / PRESCRIPTION</span><h2>${docEscape(patient)}</h2><small>Note v${clinicalDocument.version} · ${generatedNoteState==='APPROVED_BY_DOCTOR'&&value.confirmed?'Doctor approved':'Draft for doctor review'}</small></header><div class="rx-clinical-grid">${[['Symptoms & history',soap.subjective],['Findings',soap.objective],['Assessment',soap.assessment]].map(([label,text])=>`<section><h3>${label}</h3><p>${docEscape(text||'Not documented.')}</p></section>`).join('')}</div><section class="rx-medications"><h3>${studioIcon('pill')}Medication instructions</h3>${positive.length?positive.map(r=>`<article class="rx-order"><div><strong>${docEscape(r.name)}</strong><span class="document-status status-${r.action==='review'?'review':'included'}">${r.action==='review'?'Choose direction':docEscape(r.action)}</span></div><dl>${['dose','route','frequency','duration'].map(f=>`<div><dt>${f}</dt><dd>${docEscape(r[f]||'Not documented')}</dd></div>`).join('')}</dl><p>${docEscape(r.instructions)}</p></article>`).join(''):'<p>No take/continue instructions recorded.</p>'}</section>${cautions.length?`<section class="rx-cautions"><h3>${studioIcon('shield-alert')}Stop / Avoid</h3>${cautions.map(r=>`<p><strong>${r.action.toUpperCase()} ${docEscape(r.name)}</strong><br>${docEscape(r.instructions)}</p>`).join('')}</section>`:''}<div class="rx-clinical-grid">${[['tests','Tests & investigations'],['advice','Advice'],['follow_up','Follow-up']].map(([key,label])=>`<section><h3>${label}</h3><p>${docEscape(value[key]||'Not documented')}</p></section>`).join('')}</div><footer><small>Doctor-entered instructions are saved separately from the original conversation. Missing fields are never guessed.</small></footer></article>`;
}
function renderPrescriptionDocument(){
  const d=clinicalDocument,v=d.value,dialog=clinicalDocumentDialog();if(!v)return;
  document.getElementById('documentHeader').innerHTML=clinicalDocumentHeader('Prescription',d.patient+' · Saved SOAP v'+d.version);
  document.getElementById('documentTabs').innerHTML=documentTabs([['preview','Prescription'],['medicines','Medicines',v.medicines.length],['instructions','Tests & follow-up']]);
  let html='';
  if(d.tab==='preview')html=prescriptionPreview(v,d.soap,d.patient);
  if(d.tab==='medicines'){
    if(d.selected>=v.medicines.length)d.selected=Math.max(0,v.medicines.length-1);
    const r=v.medicines[d.selected];
    html=`<div class="document-selection-bar">${v.medicines.map((r,i)=>`<button type="button" class="note-action ${i===d.selected?'primary':''}" data-prescription-row="${i}">${studioIcon(r.action==='stop'||r.action==='avoid'?'shield-alert':'pill')}${docEscape(r.name)}</button>`).join('')}<button type="button" class="note-action" data-prescription-add>${studioIcon('plus')}Add doctor instruction</button></div>`;
    html+=r?`<div class="rx-editor"><div class="rx-editor-heading"><h3>${studioIcon('pill')}${docEscape(r.name)}</h3><button type="button" class="note-action" data-prescription-remove>${studioIcon('trash-2')}Remove row</button></div><div class="document-form-grid"><label>Medicine name<input data-rx-field="name" maxlength="120" value="${escAttr(r.name)}"></label><label>Direction<select data-rx-field="action">${[['review','Choose direction'],['take','Take'],['continue','Continue'],['stop','Stop'],['avoid','Avoid']].map(([key,label])=>`<option value="${key}" ${r.action===key?'selected':''}>${label}</option>`).join('')}</select></label>${['dose','route','frequency','duration'].map(f=>`<label>${f}<input data-rx-field="${f}" maxlength="100" value="${escAttr(r[f])}" placeholder="Not documented"></label>`).join('')}<label class="document-wide">Instructions<textarea data-rx-field="instructions" maxlength="2000" rows="3">${docEscape(r.instructions)}</textarea></label></div><details class="document-source"><summary>${studioIcon('quote')}Saved Plan source</summary><p>${docEscape(r.source_quote||'Added directly by the doctor. No conversation source is claimed.')}</p><small>${docEscape((r.source_ids||[]).join(', '))}</small></details><p class="document-help">Fill missing fields only with your intended instructions. Your entries will be recorded as doctor-authored.</p></div>`:'<div class="document-empty">'+studioIcon('pill')+'<h3>No medication rows.</h3><p>Add an instruction if you intend to prescribe, continue, stop or avoid a medicine.</p></div>';
  }
  if(d.tab==='instructions')html=`<div class="rx-editor document-form-grid">${[['tests','Tests & investigations'],['advice','Advice'],['follow_up','Follow-up']].map(([key,label])=>`<label class="document-wide">${label}<textarea data-rx-document="${key}" rows="3" maxlength="${key==='follow_up'?2000:4000}" placeholder="Not documented">${docEscape(v[key])}</textarea></label>`).join('')}</div>`;
  document.getElementById('documentPanel').innerHTML=html;
  const approved=documentVersionCurrent()&&generatedNoteState==='APPROVED_BY_DOCTOR'&&v.confirmed&&!clinicalDocumentDirty;
  document.getElementById('documentFooter').innerHTML=`<label class="document-confirm"><input type="checkbox" id="rxConfirmed" ${v.confirmed?'checked':''}>I confirm these are my intended prescription instructions.</label><div class="document-footer-actions"><button type="button" class="note-action" data-document-discard>${clinicalDocumentDirty?'Discard & close':'Close'}</button><button type="button" class="note-action" data-prescription-export ${approved?'':'disabled'}>${studioIcon('file-down')}Prescription PDF</button><button type="button" class="toolbar-btn primary" data-prescription-save ${clinicalDocumentBusy?'disabled':''}>${studioIcon('save')}Save reviewed instructions</button></div>`;
  if(!documentVersionCurrent())documentMessage('The saved note changed. Close and reopen this prescription.');
  else if(approved)documentMessage('Approved prescription ready to export.');
  else if(!clinicalDocumentDirty)documentMessage(v.origin==='source_extraction'?'Fields copied from the saved Plan. Review before saving.':v.confirmed?'Prescription saved. Submit the note for review and approve it to export.':'Review the source instructions and complete any missing fields.');
  studioIcons();
}
async function savePrescriptionDocument(){
  if(clinicalDocumentBusy||!documentVersionCurrent())return;
  const d=clinicalDocument,v=d.value;v.confirmed=!!document.getElementById('rxConfirmed')?.checked;
  if(!v.confirmed){documentMessage('Confirm your intended prescription instructions before saving.');return;}
  clinicalDocumentBusy=true;documentMessage('Saving a new draft version…');
  try{
    const medicines=v.medicines.map(r=>({name:r.name,action:r.action,dose:r.dose,route:r.route,frequency:r.frequency,duration:r.duration,instructions:r.instructions,
      source_quote:r.source_quote||'',source_ids:r.source_ids||[]}));
    const payload=await clinicalApi('/api/notes/'+encodeURIComponent(d.noteId)+'/prescription',{method:'PATCH',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({expected_version:d.version,medicines,tests:v.tests,advice:v.advice,follow_up:v.follow_up,confirmed:true})});
    clinicalDocumentDirty=false;applyClinicalNote(payload);d.version=payload.version;d.value=structuredClone(payload.soap.prescription);d.soap={...payload.soap};
    showToast('Prescription saved. Review and approve this note version.');
  }catch(error){documentMessage(error.message);return;}
  finally{clinicalDocumentBusy=false;renderClinicFlow();}
  renderPrescriptionDocument();
}
function openRelevanceReview(){
  if(visitLocked()||conversationDirty||conversationEditor||soapDraftTouched||Object.values(soapSectionEditing).some(Boolean)){showToast('Save the current wording changes before reviewing selection.','error');return;}
  const report=soapLastSavedNoteId?generatedSoap?.relevance_report:conversationReview?.relevance_report;
  if(!report?.items?.length){showToast('A saved conversation is needed first.','error');return;}
  clinicalDocument={kind:'relevance',tab:'included',report,selected:null,changes:{},noteId:soapLastSavedNoteId,version:currentNoteVersion,
    workflowId:activeWorkflow?.workflow_id,transcriptId:conversationReview?.transcript_id,revision:conversationReview?.revision,pending:{}};
  if(!report.counts.included)clinicalDocument.tab=report.counts.review?'review':'excluded';
  clinicalDocumentDirty=false;clinicalDocumentBusy=false;clinicalDocumentDialog().showModal();documentMessage('');renderRelevanceDocument();
}
function relevanceItem(item){const change=clinicalDocument.changes[item.utterance_id];return change?{...item,status:change.relevance_status,reason:change.relevance_reason,origin:'doctor_pending'}:item;}
function renderRelevanceDocument(){
  const d=clinicalDocument,items=d.report.items.map(relevanceItem),rows=items.filter(r=>r.status===d.tab);
  if(!rows.some(r=>r.utterance_id===d.selected))d.selected=rows[0]?.utterance_id||null;
  const r=rows.find(r=>r.utterance_id===d.selected),canEdit=generatedNoteState!=='APPROVED_BY_DOCTOR'&&(!activeWorkflow||!['ENCOUNTER_COMPLETED','CANCELLED'].includes(activeWorkflow.state));
  document.getElementById('documentHeader').innerHTML=clinicalDocumentHeader('What belongs in the note?','Full conversation preserved · selection is separate from clinical correctness');
  document.getElementById('documentTabs').innerHTML=documentTabs([['included','Included'],['excluded','Excluded'],['review','Needs review']].map(([key,label])=>[key,label,items.filter(r=>r.status===key).length]));
  document.getElementById('documentPanel').innerHTML=`<div class="relevance-workspace"><aside class="relevance-list">${rows.map(r=>`<button type="button" class="relevance-row ${r.utterance_id===d.selected?'selected':''}" data-relevance-row="${escAttr(r.utterance_id)}"><span>${studioIcon(r.status==='excluded'?'message-circle-off':r.status==='review'?'scan-eye':'file-check')}<strong>${docEscape(r.speaker)}</strong><small>${docEscape(r.utterance_id)}</small></span><p dir="auto">${docEscape(r.english||r.original)}</p><small>${docEscape(r.topic)} · ${r.origin==='doctor'||r.origin==='doctor_pending'?'Doctor selection':r.origin==='model'?'AI selection':'Source rule / review'}</small></button>`).join('')||`<div class="document-empty">${studioIcon('check')}<p>No ${d.tab==='review'?'turns awaiting review':d.tab+' turns'}.</p></div>`}</aside><article class="relevance-detail">${r?`<div class="relevance-detail-heading"><h3>${docEscape(r.speaker)} <small>${docEscape(r.utterance_id)}</small></h3><span class="document-status status-${r.status}">${r.status==='review'?'Needs review':r.status}</span></div><section><span class="section-kicker">ORIGINAL WORDING</span><blockquote dir="auto">${docEscape(r.original)}</blockquote><p>${docEscape(r.english)}</p></section><section class="relevance-reason"><h4>${studioIcon('git-branch')}Selection reason</h4><p>${docEscape(r.reason)}</p><small>${r.status==='excluded'?'Omitted from the next SOAP generation; original retained.':'Available to SOAP generation; actual attribution is shown below.'}</small></section><section><h4>${studioIcon('file-text')}Saved SOAP links</h4>${r.soap_links?.length?r.soap_links.map(l=>`<p><strong>${docEscape(l.section)}</strong><br>${docEscape(l.text)}</p>`).join(''):'<p class="document-help">No claim-level link recorded for this turn. Being included does not mean every word appears in SOAP.</p>'}</section>${canEdit?`<div class="relevance-override"><h4>${studioIcon('user-check')}Doctor selection</h4><label>Use in documentation<select id="relevanceStatus">${[['included','Include'],['excluded','Exclude'],['review','Needs review']].map(([s,l])=>`<option value="${s}" ${s===(d.pending[r.utterance_id]?.status||r.status)?'selected':''}>${l}</option>`).join('')}</select></label><label>Reason<textarea id="relevanceReason" maxlength="240" rows="2">${docEscape(d.pending[r.utterance_id]?.reason??r.reason)}</textarea></label><button type="button" class="note-action" data-relevance-apply>Apply selection</button></div>`:'<p class="document-help">This approved visit is read-only.</p>'}`:''}</article></div>`;
  document.getElementById('documentFooter').innerHTML=`<small class="document-help">${Object.keys(d.changes).length} unsaved selection changes · medicine turns remain included or under review.</small><div class="document-footer-actions"><button type="button" class="note-action" data-document-discard>${clinicalDocumentDirty?'Discard & close':'Close'}</button><button type="button" class="toolbar-btn primary" data-relevance-save ${!clinicalDocumentDirty||clinicalDocumentBusy?'disabled':''}>${studioIcon('save')}${d.noteId?'Save & regenerate SOAP':'Save selections'}</button></div>`;studioIcons();
}
async function saveRelevanceDocument(){
  const d=clinicalDocument;
  for(const [id,pending] of Object.entries(d.pending)){if(!pending.reason.trim()){documentMessage('Enter a reason for each selection.');return;}d.changes[id]={utterance_id:id,relevance_status:pending.status,relevance_reason:pending.reason.trim()};}
if(clinicalDocumentBusy||!clinicalDocumentDirty)return;
  if(d.noteId&&!documentVersionCurrent()){documentMessage('The note changed. Close and reopen its selection review.');return;}
  clinicalDocumentBusy=true;documentMessage(d.noteId?'Saving selections and regenerating a new draft…':'Saving source selections…');
  try{
    const corrections=Object.values(d.changes),payload=await clinicalApi(d.noteId?'/api/notes/'+encodeURIComponent(d.noteId)+'/relevance':'/api/workflows/'+encodeURIComponent(d.workflowId)+'/conversation',
      {method:d.noteId?'POST':'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(d.noteId?{expected_version:d.version,corrections}:{expected_revision:d.revision,transcript_id:d.transcriptId,corrections})});
    clinicalDocumentDirty=false;if(d.noteId)applyClinicalNote(payload);else applyVisitContext(payload);
    clinicalDocumentBusy=false;clinicalDocumentDialog().close();showToast(d.noteId?'Selection saved. Review the regenerated SOAP draft.':'Documentation selection saved.');
  }catch(error){documentMessage(error.message);}finally{clinicalDocumentBusy=false;renderClinicFlow();}
}
document.addEventListener('click',event=>{
  const b=event.target.closest('button');if(!b)return;
  if(b.hasAttribute('data-open-prescription'))return void openPrescription();
  if(b.hasAttribute('data-rebuild-soap'))return void rebuildSavedSoap();
  if(b.hasAttribute('data-open-relevance'))return void openRelevanceReview();
  if(!b.closest('#clinicalDocumentDialog')||!clinicalDocument||clinicalDocumentBusy)return;
  if(b.hasAttribute('data-document-close'))return closeClinicalDocument();
  if(b.hasAttribute('data-document-discard'))return closeClinicalDocument(true);
  if(b.dataset.documentTab){clinicalDocument.tab=b.dataset.documentTab;return clinicalDocument.kind==='prescription'?renderPrescriptionDocument():renderRelevanceDocument();}
  if(b.dataset.prescriptionRow){clinicalDocument.selected=Number(b.dataset.prescriptionRow);return renderPrescriptionDocument();}
  if(b.hasAttribute('data-prescription-add')){clinicalDocument.value.medicines.push({name:'New medicine',action:'review',dose:'',route:'',frequency:'',duration:'',instructions:'',source_quote:'',source_ids:[]});clinicalDocument.selected=clinicalDocument.value.medicines.length-1;clinicalDocumentDirty=true;return renderPrescriptionDocument();}
  if(b.hasAttribute('data-prescription-remove')){clinicalDocument.value.medicines.splice(clinicalDocument.selected,1);clinicalDocumentDirty=true;return renderPrescriptionDocument();}
  if(b.hasAttribute('data-prescription-save'))return void savePrescriptionDocument();
  if(b.hasAttribute('data-prescription-export')&&!b.disabled)return void location.assign('/api/notes/'+encodeURIComponent(clinicalDocument.noteId)+'/prescription.pdf');
  if(b.dataset.relevanceRow){clinicalDocument.selected=b.dataset.relevanceRow;return renderRelevanceDocument();}
  if(b.hasAttribute('data-relevance-apply')){
    const r=clinicalDocument.report.items.find(r=>r.utterance_id===clinicalDocument.selected),status=document.getElementById('relevanceStatus').value,reason=document.getElementById('relevanceReason').value.trim();
    if(!reason){documentMessage('Enter a short reason for this selection.');return;}
    clinicalDocument.changes[r.utterance_id]={utterance_id:r.utterance_id,relevance_status:status,relevance_reason:reason};delete clinicalDocument.pending[r.utterance_id];clinicalDocumentDirty=true;
    clinicalDocument.tab=status;documentMessage('Selection ready to save.');return renderRelevanceDocument();
  }
  if(b.hasAttribute('data-relevance-save'))return void saveRelevanceDocument();
});
document.addEventListener('input',event=>{
  if(!clinicalDocument||!event.target.closest('#clinicalDocumentDialog'))return;
  const input=event.target;
  if(clinicalDocument.kind==='relevance'){
    if(!['relevanceStatus','relevanceReason'].includes(input.id))return;
    clinicalDocument.pending[clinicalDocument.selected]={status:document.getElementById('relevanceStatus').value,reason:document.getElementById('relevanceReason').value};
    clinicalDocumentDirty=true;document.querySelector('[data-relevance-save]')?.removeAttribute('disabled');documentMessage('Unsaved selection changes.');return;
  }
  if(input.dataset.rxField){const r=clinicalDocument.value.medicines[clinicalDocument.selected];r[input.dataset.rxField]=input.value;
    if(input.dataset.rxField==='name'&&r.source_quote){r.source_quote='';r.source_ids=[];}}
  else if(input.dataset.rxDocument)clinicalDocument.value[input.dataset.rxDocument]=input.value;
  else if(input.id==='rxConfirmed')clinicalDocument.value.confirmed=input.checked;
  else return;
  clinicalDocumentDirty=true;document.querySelector('[data-prescription-export]')?.setAttribute('disabled','');documentMessage('Unsaved doctor instructions.');
});
const documentBaseSoap=renderSoapNote;
renderSoapNote=function(...args){documentBaseSoap(...args);const header=document.querySelector('#soapContent .soap-header');if(!header||!soapLastSavedNoteId)return;
  const actions=document.createElement('div');actions.className='clinical-document-actions';actions.innerHTML=`<button type="button" class="note-action" data-open-prescription>${studioIcon('clipboard-plus')}Prescription</button><button type="button" class="note-action" data-open-relevance>${studioIcon('list-filter')}Conversation selection</button>`;header.after(actions);
  if(sourceExtractDraft(generatedSoap)){
    const card=document.createElement('section');card.className='soap-recovery';card.setAttribute('aria-label','SOAP generation status');
    const dirty=soapDraftTouched||Object.values(soapSectionEditing).some(Boolean)||conversationDirty||conversationEditor;
    const approved=generatedNoteState==='APPROVED_BY_DOCTOR';
    card.innerHTML=`${studioIcon('file-warning')}<div><strong>AI summary unavailable · source extract shown</strong><p>The saved conversation is preserved. Rebuild the summary using your reviewed transcript and medicine confirmations.</p>${dirty?'<small>Save your wording changes first.</small>':''}</div>${approved?'':`<button type="button" class="note-action" data-rebuild-soap ${visitLocked()||dirty?'disabled':''}>${studioIcon('refresh-cw')}${clinicalDocumentBusy?'Rebuilding SOAP…':'Rebuild SOAP'}</button>`}`;
    actions.after(card);
  }
  studioIcons();};
const documentBaseFinish=renderFinishWorkspace;
renderFinishWorkspace=function(){documentBaseFinish();const actions=document.querySelector('#finishContent .detail-actions');if(!actions||!soapLastSavedNoteId)return;
  actions.insertAdjacentHTML('beforeend',`<button type="button" class="note-action" data-open-prescription>${studioIcon('clipboard-plus')}Prescription</button><button type="button" class="note-action" data-open-relevance>${studioIcon('list-filter')}Conversation selection</button>`);studioIcons();};
function sizeClinicalDocument(){const scale=(window.MedFlowDisplay?.preferences?.zoom||100)/100;document.documentElement.style.setProperty('--document-vw',(innerWidth/scale)+'px');}
window.addEventListener('medflow:display',sizeClinicalDocument);window.addEventListener('resize',sizeClinicalDocument);sizeClinicalDocument();
const documentBaseTranscript=renderTranscript;
renderTranscript=function(){documentBaseTranscript();if(!conversationReview||soapLastSavedNoteId)return;
  const container=document.getElementById('transcriptBody');if(!container||!conversationReview.relevance_report?.items?.length)return;
  const button=document.createElement('button');button.type='button';button.className='note-action relevance-entry';button.dataset.openRelevance='';button.innerHTML=studioIcon('list-filter')+'Documentation selection';container.prepend(button);studioIcons();};
const documentBaseLeave=canLeaveVisit;
canLeaveVisit=function(){if(clinicalDocumentBusy||clinicalDocumentDirty){showToast('Save or discard the open document changes before leaving.','error');return false;}return documentBaseLeave();};
const documentBaseLocked=visitLocked;
visitLocked=function(){return clinicalDocumentBusy||documentBaseLocked();};
window.addEventListener('beforeunload',event=>{if(clinicalDocumentDirty||clinicalDocumentBusy){event.preventDefault();event.returnValue='';}});
