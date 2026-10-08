/* Saved-source medicine receipts. Status labels are not clinical probabilities. */
function medicineEvidenceMarkup(report){
  const rows=report?.items||[];if(!rows.length)return '';
  const dirty=soapDraftTouched||Object.values(soapSectionEditing).some(Boolean);
  return `<details class="medicine-evidence-card"><summary>${studioIcon('pill')}<span>Medicine evidence <small>${rows.length} source mentions</small></span>${studioIcon('chevron-down')}</summary><p>${dirty?'Saved version shown. Save your SOAP changes to refresh these links.':escHtml(report.scope)}</p>${rows.map(row=>`<article class="medicine-evidence-item"><div class="medicine-evidence-title"><strong>${escHtml(row.final_name)}</strong><small>${escHtml(row.speaker)} · ${escHtml(row.utterance_id)} · Note v${escHtml(row.note_version)}</small></div><div class="medicine-evidence-path">${[['quote','Source'],['sparkles','Proposal'],['book-open-check','Catalogue'],['user-check','Doctor'],['file-check','SOAP']].map(([icon,label])=>`<span>${studioIcon(icon)}${label}</span>`).join('')}</div><div class="medicine-evidence-grid"><section><small>ORIGINAL WORDING</small><blockquote dir="auto">${escHtml(row.original)}</blockquote><button class="note-action" data-medicine-evidence-source="${escAttr(row.utterance_id)}">${studioIcon('messages-square')}Open conversation</button></section><section><small>PROPOSED / CONFIRMED</small><p>${escHtml(row.proposed_name)}${row.confirmed_name?' → '+escHtml(row.confirmed_name):''}</p><small>${row.catalogue?'Catalogue: '+escHtml(row.catalogue.name)+' · '+escHtml(row.catalogue.source_filename||'Curated reference'):'No exact catalogue match'}</small><p class="medicine-review-state ${row.doctor_reviewed?'reviewed':''}">${studioIcon(row.doctor_reviewed?'check-check':'circle-dashed')}${row.doctor_reviewed?'Doctor wording review recorded':'Doctor wording review not recorded'}</p></section><section class="medicine-evidence-instruction"><small>TRANSLATION - DOSE & STOP/AVOID WORDING</small><p>${escHtml(row.source_instruction)}</p><div class="medicine-soap-links">${row.soap_links.map(link=>`<button class="note-action" data-medicine-soap-section="${escAttr(link.section)}" ${dirty?'disabled':''}>${studioIcon('file-text')}${escHtml(link.section)}${studioIcon('arrow-up-right')}</button>`).join('')||'<small>Name not found in the saved SOAP.</small>'}</div></section></div></article>`).join('')}</details>`;
}
const medicineEvidenceBaseSoap=renderSoapNote;
renderSoapNote=function(...args){
  medicineEvidenceBaseSoap(...args);const header=document.querySelector('#soapContent .soap-header');
  header?.insertAdjacentHTML('afterend',medicineEvidenceMarkup(generatedSoap?.medicine_evidence));
  if(header&&soapLastSavedNoteId){const toolbar=document.createElement('div');toolbar.className='medicine-pdf-actions';
    const dirty=soapDraftTouched||Object.values(soapSectionEditing).some(Boolean);
    toolbar.innerHTML=`<button class="note-action" data-visit-pdf="summary" ${dirty?'disabled':''}>${studioIcon('file-down')}${generatedNoteState==='APPROVED_BY_DOCTOR'?'Visit PDF':'Draft PDF'}</button><button class="note-action" data-visit-pdf="technical" ${dirty?'disabled':''}>${studioIcon('git-branch')}Evidence PDF</button>`;header.append(toolbar);}
  studioIcons();
};
document.addEventListener('click',event=>{
  const source=event.target.closest('[data-medicine-evidence-source]');if(source)locateEvidenceSource(source.dataset.medicineEvidenceSource);
  const section=event.target.closest('[data-medicine-soap-section]');if(section&&!section.disabled){
    const target=document.querySelector(`[data-soap-section="${section.dataset.medicineSoapSection}"]`);
    target?.scrollIntoView({behavior:'smooth',block:'center'});target?.animate([{outline:'2px solid var(--gold)'},{outline:'2px solid transparent'}],{duration:1500});
  }
  const pdf=event.target.closest('[data-visit-pdf]');if(pdf&&!pdf.disabled&&soapLastSavedNoteId){
    location.assign('/api/notes/'+encodeURIComponent(soapLastSavedNoteId)+'/export.pdf'+(pdf.dataset.visitPdf==='technical'?'?technical=true':''));
  }
});
// The existing approved-note download now produces the patient-facing PDF.
downloadSoap=function(){
  if(generatedNoteState!=='APPROVED_BY_DOCTOR'||soapDraftTouched||Object.values(soapSectionEditing).some(Boolean)){showToast('Save and approve the current note before exporting.','error');return;}
  if(soapLastSavedNoteId)location.assign('/api/notes/'+encodeURIComponent(soapLastSavedNoteId)+'/export.pdf');
};
