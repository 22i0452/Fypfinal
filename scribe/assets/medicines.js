/* Exact source-name checks; these are not probabilities or prescribing advice. */
window.medicineEditorFields=function(turn){
  const check=turn.medicine_checks;if(!check?.mentions?.length)return '';
  const unknown=check.mentions.filter(row=>row.status!=='catalog_name');
  return `<fieldset class="turn-edit-full medicine-confirm"><legend>Medicine wording</legend><p>Compare the original turn and English above. Keep the exact medicine, dose and any instruction to stop or avoid it.</p>${unknown.map(row=>`<label>Confirmed English spelling for <b dir="auto">${escHtml(row.source)}</b><input data-medicine-spelling="${escAttr(row.source)}" maxlength="100" value="${escAttr(turn.medicine_spellings?.[row.source] || turn.medicine_review?.spellings?.[row.source] || row.suggested_english || row.name)}"></label>${medicineCandidateMarkup(turn,row)}`).join('')}<label class="medicine-attest"><input type="checkbox" data-medicines-reviewed ${turn.medicines_reviewed?'checked':''}>I checked these medicine names and the English wording against the source.</label></fieldset>`;
};
function medicineSuggestedName(turn,row){
  const mention=turn.medicine_suggestions?.mentions?.find(item=>item.source===row.source && item.start===row.start);
  const choice=mention?.candidates?.find(item=>item.catalog_id===mention.selected_catalog_id);
  return choice?'Possible '+choice.name+' · confirm spelling':'Confirm spelling';
}
function medicineCandidateMarkup(turn,row){
  const result=turn.medicine_suggestions,mention=result?.mentions?.find(item=>item.source===row.source && item.start===row.start);
  if(!mention || mention.exact)return '';
  const preferred=mention.candidates.find(item=>item.catalog_id===mention.selected_catalog_id);
  const choices=[...(preferred?[preferred]:[]),...mention.candidates.filter(item=>item!==preferred)].slice(0,3);
  if(!choices.length)return `<div class="medicine-candidates"><small>${mention.status==='llm_unavailable'?'Automatic name check unavailable.':'No catalogue match found.'} Check the source and enter the intended spelling above.</small></div>`;
  return `<div class="medicine-candidates"><small>${mention.status==='llm_unavailable'?'Automatic name check unavailable. Local catalogue candidates:':preferred?'Automatic LLM suggestion. Confirm against the source:':'Uncertain name. Catalogue candidates for review:'}</small><div>${choices.map(item=>`<button type="button" class="note-action" data-medicine-candidate="${escAttr(item.name)}" data-recognized-name="${escAttr(row.source)}" ${visitLocked()?'disabled':''}>${preferred===item?studioIcon('sparkles'):studioIcon('pill')}Use ${escHtml(item.name)}</button>`).join('')}</div><small>${choices.some(item=>item.source_filename)?'Pakistan medicines CSV and curated name references. A catalogue match does not verify hearing.':'Curated name references. A similar spelling does not verify hearing.'}</small><span class="medicine-candidate-result" role="status"></span></div>`;
}
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-medicine-candidate]');if(!button || visitLocked())return;
  const editor=button.closest('.conversation-turn-editor');if(!editor)return;
  const input=Array.from(editor.querySelectorAll('[data-medicine-spelling]')).find(input=>input.dataset.medicineSpelling===button.dataset.recognizedName);
  if(!input)return;input.value=button.dataset.medicineCandidate;
  const english=editor.querySelector('[data-turn-english]'),source=button.dataset.recognizedName;
  const escaped=source.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  // Change only an existing literal mention in English. Never synthesize the
  // remainder of a failed translation, a dose or a prescription.
  if(!/^\[Translation /.test(english.value))english.value=english.value.replace(new RegExp('(?<![\\p{L}\\p{N}_])'+escaped+'(?![\\p{L}\\p{N}_])','giu'),()=>button.dataset.medicineCandidate);
  editor.querySelector('[data-medicines-reviewed]').checked=false;
  button.closest('.medicine-candidates').querySelector('.medicine-candidate-result').textContent='Spelling added. Check the full English turn, then confirm below.';
  english.focus();
});
function medicineIssueLabel(issue){
  if(issue.startsWith('name_missing_or_changed:'))return 'English name missing or changed: '+issue.split(':').slice(1).join(':');
  if(issue.startsWith('soap_medicine_missing:'))return 'Name missing from SOAP: '+issue.split(':').slice(1).join(':');
  if(issue.includes('dose'))return 'Check the stated dose and its medicine.';
  if(issue.includes('negation'))return 'Check the instruction to stop, avoid or not take this medicine.';
  if(issue.includes('introduced'))return 'A medicine was added without a matching source name.';
  if(issue==='name_confirmation_required')return 'Confirm the unfamiliar medicine spelling.';
  return 'Review the medicine translation against the original turn.';
}
const medicineBaseTranscript=renderTranscript;
renderTranscript=function(...args){
  medicineBaseTranscript(...args);
  document.querySelectorAll('#transcriptBody [data-utterance-id]').forEach(node=>{
    const turn=fullTranscript.find(turn=>turn.utterance_id===node.dataset.utteranceId),check=turn?.medicine_checks;
    if(!check?.mentions?.length)return;
    const local=Boolean(conversationEdits[turn.utterance_id]);
    const receipt=document.createElement('div');receipt.className='medicine-receipt'+(check.issues.length?' needs-review':'');
    receipt.innerHTML=`<div>${studioIcon('pill')}<strong>${local?'Medicine checks pending save':check.issues.length?'Medicine wording needs review':'Medicine names preserved'}</strong></div><div class="medicine-names">${check.mentions.map(row=>`<span><b dir="auto">${escHtml(row.source)}</b><span aria-hidden="true"> → </span>${escHtml(row.confirmed_english || (row.status==='catalog_name'?row.name:medicineSuggestedName(turn,row)))}</span>`).join('')}</div>${!local && check.issues.length?`<ul>${check.issues.map(issue=>`<li>${escHtml(medicineIssueLabel(issue))}</li>`).join('')}</ul>`:`<small>${local?'Save the corrected turn to refresh these checks.':check.reviewed_by?'Doctor reviewed this wording.':'Vocabulary match; hearing and clinical correctness still need doctor review.'}</small>`}`;
    const actions=node.querySelector('.conversation-turn-actions');if(actions)actions.before(receipt);else node.append(receipt);
  });studioIcons();
};
const medicineBaseFlow=renderClinicFlow;
renderClinicFlow=function(...args){
  medicineBaseFlow(...args);
  if(conversationReview && visitStage==='transcript'){
    const report=conversationReview.medicine_report,bar=document.getElementById('conversationReviewBar');
    if(report?.checks?.length || report?.context_unavailable_turns?.length){const detail=document.createElement('p');detail.className='medicine-review-summary';detail.textContent=conversationDirty?'Medicine checks refresh when these corrections are saved.':report.context_unavailable_turns?.length?'Full-conversation medicine context check unavailable. Original wording is preserved; review the transcript.':report.requires_review?'Review flagged medicine turns before SOAP. Original wording is preserved.':'Medicine names checked against the original turns. Doctor review remains required.';bar.append(detail);}
    if(conversationReview.raw_asr_text){const original=document.createElement('details');original.className='medicine-raw-source';original.innerHTML=`<summary>Original speech-recognition text</summary><p dir="auto">${escHtml(conversationReview.raw_asr_text)}</p><small>Preserved before cleanup. This is recognized text, not verified audio.</small>`;bar.append(original);}
    if(conversationReview.symptom_patterns)bar.insertAdjacentHTML('beforeend',symptomPatternMarkup(conversationReview.symptom_patterns,conversationDirty));
    // Keep the primary action as Generate SOAP. Medicine attestation is handled
    // inside advanceConversationReview so the doctor is not stuck on this page.
  }
  if(visitStage==='review' && generatedSoap?.medicine_report?.soap_issues?.length && generatedNoteState==='REVIEW_REQUIRED' && !soapDraftTouched){const button=document.getElementById('visitNextBtn');button.disabled=true;button.title='Correct the medicine wording in SOAP, then save and review the corrected version.';}
  studioIcons();
};
const medicineBaseSoap=renderSoapNote;
renderSoapNote=function(...args){
  medicineBaseSoap(...args);const issues=generatedSoap?.medicine_report?.soap_issues || [];
  if(generatedSoap?.symptom_patterns)document.querySelector('#soapContent .soap-header')?.insertAdjacentHTML('afterend',symptomPatternMarkup(generatedSoap.symptom_patterns,false));
  if(!issues.length)return;
  const warning=document.createElement('aside');warning.className='medicine-receipt needs-review';warning.setAttribute('role','status');warning.innerHTML=`<div>${studioIcon('pill')}<strong>Medicine source check</strong></div><ul>${issues.map(issue=>`<li>${escHtml(medicineIssueLabel(issue))}</li>`).join('')}</ul><small>${soapDraftTouched?'Save corrections to refresh these checks.':'Correct the SOAP wording before approval. View the conversation to compare the source.'}</small>`;document.querySelector('#soapContent .soap-header')?.after(warning);studioIcons();
};
function symptomPatternMarkup(report,dirty){
  if(!report?.observations?.length)return '';
  if(dirty)return '<p class="medicine-review-summary">Symptom reference results refresh after saving the conversation.</p>';
  const states={reported:'Reported',denied:'Denied',historical:'History',resolved:'Resolved',other_person:'Other person',needs_review:'Needs review',translation_only:'Translation only'};
  return `<details class="symptom-pattern-reference"><summary>${studioIcon('scan-line')}Symptom reference · ${report.observations.length} observations</summary><p>Source wording matched to the uploaded symptom dataset. Pattern labels are unverified references, not diagnoses or probabilities.</p><div class="symptom-observations">${report.observations.map(item=>`<button type="button" class="symptom-source ${item.status==='reported'?'reported':''}" data-symptom-source="${escAttr(item.utterance_id)}"><span>${escHtml(item.label)}</span><small>${escHtml(states[item.status] || 'Needs review')} · ${escHtml(item.utterance_id)}</small><q dir="auto">${escHtml(item.quote)}</q></button>`).join('')}</div>${report.conflicting_symptoms.length?'<p>Some source wording conflicts or needs clarification. These observations are excluded from pattern matching.</p>':''}${report.matches.length?`<div class="symptom-pattern-matches">${report.matches.map(item=>`<article><strong>${escHtml(item.disease_label)}</strong><small>Dataset pattern only · ${item.matched_symptoms.length} matched symptom groups</small><p>Not reported: ${escHtml(item.not_reported.map(value=>value.replaceAll('_',' ')).join(', ') || 'None in this pattern')}. ${item.not_in_pattern.length?'Outside this pattern: '+escHtml(item.not_in_pattern.map(value=>value.replaceAll('_',' ')).join(', '))+'.':''}</p><div>${item.source_turns.map(id=>`<button type="button" class="note-action" data-symptom-source="${escAttr(id)}">${studioIcon('quote')}Source ${escHtml(id)}</button>`).join('')}</div><small>Sheet ${escHtml(report.source.sheet)} · source rows ${escHtml(item.source_rows.slice(0,4).join(', '))}${item.source_rows.length>4?' and '+(item.source_rows.length-4)+' duplicates':''}</small></article>`).join('')}</div>`:'<p>No dataset pattern is shown. At least three distinct current symptom groups and a close reference overlap are required.</p>'}<small>Source: ${escHtml(report.source.filename)}. This lookup does not write a diagnosis into SOAP.</small></details>`;
}
document.addEventListener('click',event=>{const button=event.target.closest('[data-symptom-source]');if(button)locateEvidenceSource(button.dataset.symptomSource);});
