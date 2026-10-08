/* Exact source-name checks; these are not probabilities or prescribing advice. */
window.medicineEditorFields=function(turn){
  const check=turn.medicine_checks;if(!check?.mentions?.length)return '';
  const unknown=check.mentions.filter(row=>row.status!=='catalog_name');
  return `<fieldset class="turn-edit-full medicine-confirm"><legend>Medicine wording</legend><p>Compare the original turn and English above. Keep the exact medicine, dose and any instruction to stop or avoid it.</p>${unknown.map(row=>`<label>Confirmed English spelling for <b dir="auto">${escHtml(row.source)}</b><input data-medicine-spelling="${escAttr(row.source)}" maxlength="100" value="${escAttr(turn.medicine_spellings?.[row.source] || turn.medicine_review?.spellings?.[row.source] || row.name)}"></label>`).join('')}<label class="medicine-attest"><input type="checkbox" data-medicines-reviewed ${turn.medicines_reviewed?'checked':''}>I checked these medicine names and the English wording against the source.</label></fieldset>`;
};
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
    receipt.innerHTML=`<div>${studioIcon('pill')}<strong>${local?'Medicine checks pending save':check.issues.length?'Medicine wording needs review':'Medicine names preserved'}</strong></div><div class="medicine-names">${check.mentions.map(row=>`<span><b dir="auto">${escHtml(row.source)}</b><span aria-hidden="true"> → </span>${escHtml(row.confirmed_english || (row.status==='catalog_name'?row.name:'Confirm spelling'))}</span>`).join('')}</div>${!local && check.issues.length?`<ul>${check.issues.map(issue=>`<li>${escHtml(medicineIssueLabel(issue))}</li>`).join('')}</ul>`:`<small>${local?'Save the corrected turn to refresh these checks.':check.reviewed_by?'Doctor reviewed this wording.':'Vocabulary match; hearing and clinical correctness still need doctor review.'}</small>`}`;
    const actions=node.querySelector('.conversation-turn-actions');if(actions)actions.before(receipt);else node.append(receipt);
  });studioIcons();
};
const medicineBaseFlow=renderClinicFlow;
renderClinicFlow=function(...args){
  medicineBaseFlow(...args);
  if(conversationReview && visitStage==='transcript'){
    const report=conversationReview.medicine_report,bar=document.getElementById('conversationReviewBar');
    if(report?.checks?.length){const detail=document.createElement('p');detail.className='medicine-review-summary';detail.textContent=conversationDirty?'Medicine checks refresh when these corrections are saved.':report.requires_review?'Review flagged medicine turns before SOAP. Original wording is preserved.':'Medicine names checked against the original turns. Doctor review remains required.';bar.append(detail);}
    if(conversationReview.raw_asr_text){const original=document.createElement('details');original.className='medicine-raw-source';original.innerHTML=`<summary>Original speech-recognition text</summary><p dir="auto">${escHtml(conversationReview.raw_asr_text)}</p><small>Preserved before cleanup. This is recognized text, not verified audio.</small>`;bar.append(original);}
    if(report?.requires_review && !conversationDirty && !conversationEditor && conversationReview.status!=='TRANSLATION_FAILED')document.getElementById('visitNextBtn').innerHTML=escHtml('Review medicine wording')+studioIcon('pill');
  }
  if(visitStage==='review' && generatedSoap?.medicine_report?.soap_issues?.length && generatedNoteState==='REVIEW_REQUIRED' && !soapDraftTouched){const button=document.getElementById('visitNextBtn');button.disabled=true;button.title='Correct the medicine wording in SOAP, then save and review the corrected version.';}
  studioIcons();
};
const medicineBaseSoap=renderSoapNote;
renderSoapNote=function(...args){
  medicineBaseSoap(...args);const issues=generatedSoap?.medicine_report?.soap_issues || [];
  if(!issues.length)return;
  const warning=document.createElement('aside');warning.className='medicine-receipt needs-review';warning.setAttribute('role','status');warning.innerHTML=`<div>${studioIcon('pill')}<strong>Medicine source check</strong></div><ul>${issues.map(issue=>`<li>${escHtml(medicineIssueLabel(issue))}</li>`).join('')}</ul><small>${soapDraftTouched?'Save corrections to refresh these checks.':'Correct the SOAP wording before approval. View the conversation to compare the source.'}</small>`;document.querySelector('#soapContent .soap-header')?.after(warning);studioIcons();
};
