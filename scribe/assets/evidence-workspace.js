/* Clinical evidence view. Structural checks and authenticated approval remain separate. */
let evidenceNoteFilter='all',evidenceNoteIdentity='';
const EV_SECTIONS=['subjective','objective','assessment','plan'];
function currentEvidenceReport(){return generatedSoap?.evidence_report || null;}
function evidenceClaimData(row,report){
  return {title:row.section.toUpperCase()+' · statement',status:row.status,label:row.label,interpretation:row.text,sources:row.sources,checks:row.checks,
    scope:'Current persisted note version. Source links are model attributions; doctor approval is a separate recorded action.',
    technical:{claim_id:row.claim_id,note_id:report.note_id,version:report.version,note_state:report.state,source_ids:row.source_ids,
      reference_check:'ID membership in the saved transcript',text_check:'Exact substring after whitespace normalization',confidence:report.confidence_status,
      approved_by:report.approval?.doctor_id || 'Pending',approved_at:report.approval?.approved_at || 'Pending'}};
}
function registerEvidenceClaim(row,report,prefix='claim'){
  return MedFlowEvidence.register(prefix+':'+report.note_id+':'+report.version+':'+row.claim_id,()=>{const data=evidenceClaimData(row,report);if(prefix==='capture')data.scope='Initial capture artifact, version '+report.version+'. Later edits and approval are shown on the current note.';return data;});
}
function sectionEvidenceCurrent(key){
  const claims=generatedSoap?.structured_soap?.[key] || [];
  return !soapSectionEditing[key] && String(generatedSoap?.[key] || '').replace(/\s+/g,' ').trim()===claims.map(x=>x.text).join(' ').replace(/\s+/g,' ').trim();
}
const evidenceBaseSection=renderSoapSection;
renderSoapSection=function(key,heading,value){
  let html=evidenceBaseSection(key,heading,value);
  if(soapSectionEditing[key])return html;
  const report=currentEvidenceReport(),rows=report?.claims?.filter(row=>row.section===key) || [];
  if(!report)return html;
  if(!sectionEvidenceCurrent(key))return html.replace('</div>',MedFlowEvidence.badge('review','Edited · save to refresh source checks')+'</div>');
  const text=String(value || 'Not documented.');
  const spans=rows.map(row=>({text:row.text,status:row.status,key:registerEvidenceClaim(row,report)}));
  return html.replace(`<p>${escHtml(text)}</p>`,`<p class="evidence-soap-text">${MedFlowEvidence.marks(text,spans)}</p>`);
};
function renderEvidenceOverview(){
  const root=document.getElementById('soapContent');if(!root || !generatedSoap)return;
  root.querySelectorAll('.evidence-note-overview,.claim-source-inspector').forEach(x=>x.remove());
  const report=currentEvidenceReport();if(!report)return;
  const identity=report.note_id+':'+report.version;
  if(evidenceNoteIdentity!==identity){evidenceNoteIdentity=identity;evidenceNoteFilter='all';MedFlowEvidence.close();}
  const currentRows=report.claims.filter(row=>sectionEvidenceCurrent(row.section));
  const dirty=soapDraftTouched || Object.values(soapSectionEditing).some(Boolean);
  const rows=currentRows.filter(row=>evidenceNoteFilter==='all' || evidenceNoteFilter==='linked' && row.has_source || evidenceNoteFilter==='review' && row.status==='review' || evidenceNoteFilter==='missing' && row.status==='missing' || evidenceNoteFilter==='failed' && row.status==='failed');
  const counts={all:currentRows.length,linked:currentRows.filter(x=>x.has_source).length,review:currentRows.filter(x=>x.status==='review').length,missing:currentRows.filter(x=>x.status==='missing').length,failed:currentRows.filter(x=>x.status==='failed').length};
  const section=document.createElement('section');section.className='evidence-note-overview';
  section.innerHTML=`<header><div><span class="section-kicker">EVIDENCE & CHECKS</span><h4>Every statement, inspectable.</h4></div>${MedFlowEvidence.badge(!dirty && report.state==='APPROVED_BY_DOCTOR'?'checked':'review',!dirty && report.state==='APPROVED_BY_DOCTOR'?'Doctor approved':'Doctor review')}</header><div class="evidence-counters">${[['all','Statements','received'],['linked','Source linked','checked'],['review','Review','review'],['missing','Missing detail','missing'],['failed','Failed','failed']].map(([key,label,status])=>`<button class="evidence-counter ev-${status} ${key===evidenceNoteFilter?'active':''}" type="button" onclick="filterNoteEvidence('${key}')" aria-pressed="${key===evidenceNoteFilter}" ${!counts[key] && key!=='all'?'disabled':''}><span class="evidence-dot"></span><b>${counts[key]}</b>${label}</button>`).join('')}</div><p>${dirty?'Local edits have no fresh source checks. Save to inspect the new persisted version.':`Version ${escHtml(report.version)} · ${counts.linked} of ${counts.all} statements have attached sources. Source links do not establish clinical correctness.`}</p>${MedFlowEvidence.legend()}<details class="claim-source-inspector"><summary>${studioIcon('git-branch')}Statement sources & review</summary><div class="evidence-claim-review">${rows.map(row=>`<article><button class="evidence-claim-row ev-${row.status}" data-evidence-key="${registerEvidenceClaim(row,report)}" type="button"><span class="evidence-dot" aria-hidden="true"></span><div><p>${escHtml(row.text)}</p><small>${escHtml(row.section.toUpperCase())} · ${escHtml(row.label)} · ${row.source_ids.length} attached source(s)</small></div></button><div class="evidence-source-actions">${row.source_ids.map(id=>`<button class="note-action" data-source-id="${escAttr(id)}" type="button">${studioIcon('quote')}${escHtml(id)}</button>`).join('')}</div></article>`).join('') || '<p class="evidence-empty">No current statements in this filter.</p>'}</div></details>${report.warnings.length || report.missing_information.length?`<details class="evidence-technical"><summary>Recorded warnings and missing-information checks · ${report.warnings.length+report.missing_information.length}</summary>${[...report.warnings,...report.missing_information].map(text=>`<p>${escHtml(text)}</p>`).join('')}</details>`:''}`;
  section.querySelector('.claim-source-inspector').open=evidenceNoteFilter!=='all';
  section.addEventListener('click',event=>{const button=event.target.closest('[data-source-id]');if(button)locateEvidenceSource(button.dataset.sourceId);});
  root.querySelector('.soap-header')?.after(section);studioIcons();
}
window.filterNoteEvidence=key=>{evidenceNoteFilter=key;renderEvidenceOverview();};
function locateEvidenceSource(id){
  if(!fullTranscript.some(x=>x.utterance_id===id))return;
  MedFlowEvidence.close();highlightedEvidenceIds=[id];if(fullTranscript.length)transcriptMode='english';renderTranscript();
  [...document.querySelectorAll('[data-utterance-id]')].find(x=>x.dataset.utteranceId===id)?.scrollIntoView({behavior:'smooth',block:'center'});
}
const evidenceBaseSoap=renderSoapNote;
renderSoapNote=function(...args){MedFlowEvidence.setScope(`visit:${selectedPatient?._id}:${activeEncounter?.encounter_id}`);evidenceBaseSoap(...args);renderEvidenceOverview();};
const evidenceBaseTranscript=renderTranscript;
renderTranscript=function(){
  evidenceBaseTranscript();
  const entries=transcriptMode==='english' && fullTranscript.length?fullTranscript:diarizedTranscript;
  document.querySelectorAll('#transcriptBody [data-utterance-id]').forEach(node=>{
    const turn=entries.find(x=>x.utterance_id===node.dataset.utteranceId);if(!turn)return;
    const translated=!!turn.clinical_english;
    const key=MedFlowEvidence.register('turn:'+turn.utterance_id,{title:'Conversation turn '+turn.utterance_id,status:'review',label:turn.needs_review?'Review role / wording':'Proposed role',raw:turn.original_text || turn.text,interpretation:turn.clinical_english || '',
      scope:'Role attribution and translation are model outputs. Distinct acoustic voices and semantic translation accuracy have not been measured.',
      checks:[{code:'source_id',label:'Transcript turn ID',status:'passed',detail:'This ID is present in the displayed transcript.'},{code:'translation_pair',label:'Translation pair',status:translated?'passed':'unassessed',detail:translated?'Original wording and English are paired by the same utterance ID. Meaning still needs review.':'No translated text is available.'},{code:'role_review',label:'Speaker role',status:'review',detail:turn.needs_review?'This role or wording is flagged for review.':'Text-based role attribution. Review the role against the conversation.'}],
      technical:{utterance_id:turn.utterance_id,proposed_role:turn.speaker,relation:turn.speaker_relation || 'None',audio_alignment:'Unavailable',distinct_voices:'Unmeasured',confidence:'Not measured'}});
    const receipt=document.createElement('div');receipt.className='evidence-turn-receipt';receipt.innerHTML=`${MedFlowEvidence.badge('review',turn.needs_review?'Role / wording review':'Proposed role')}<button class="note-action" data-evidence-key="${key}" type="button">Inspect turn</button>`;node.append(receipt);
  });
};
const evidenceBaseArtifact=processArtifact;
processArtifact=function(stage,event){
  const html=evidenceBaseArtifact(stage,event);
  if(event?.status!=='complete')return html;
  if(stage==='validation' && event.artifact.evidence_report){
    const report=event.artifact.evidence_report;
    return `<div class="evidence-live-receipt"><div><h4>Capture draft checks</h4>${MedFlowEvidence.badge('review','Initial draft · review')}</div><p>${report.counts.linked} / ${report.counts.statements} source-linked statements · ${report.counts.exact_matches} exact text matches. These are structural checks.</p><code>${escHtml(event.run_id)} · sequence ${event.sequence}</code></div>${html}<div class="evidence-claim-review">${report.claims.map(row=>`<button class="evidence-claim-row ev-${row.status}" data-evidence-key="${registerEvidenceClaim(row,report,'capture')}" type="button"><span class="evidence-dot"></span><div><p>${escHtml(row.text)}</p><small>${escHtml(row.label)} · initial capture version ${report.version}</small></div></button>`).join('')}</div>`;
  }
  const a=event.artifact || {};
  const checkItems=stage==='audio'?[{code:'pcm_received',label:'Audio samples received',status:'passed',detail:`${a.samples} PCM samples at ${a.sample_rate} Hz.`}]:stage==='speech'?[{code:'transcript_returned',label:'Transcript returned',status:'passed',detail:'The transcription stage completed. Acoustic accuracy and word-level confidence are unmeasured.'}]:stage==='roles'?[{code:'role_attribution',label:'Text-based speaker roles',status:'review',detail:'Proposed roles are available for correction. Acoustic speaker counting is not measured.'}]:stage==='translation'?[{code:'paired_source_ids',label:'Original/English pairing',status:'passed',detail:'Translations retain their original utterance IDs. This is not a semantic accuracy measurement.'}]:[{code:'draft_created',label:'Draft created',status:'passed',detail:'SOAP generation completed. Doctor review remains required.'}];
  return html+MedFlowEvidence.checks(checkItems);
};
const evidenceBasePatientOpen=openPatientVisit;
openPatientVisit=async function(...args){if(!canLeaveVisit())return false;MedFlowEvidence.close();evidenceNoteIdentity='';return evidenceBasePatientOpen(...args);};
document.addEventListener('click',event=>{const source=event.target.closest('[data-evidence-source]');if(source)locateEvidenceSource(source.dataset.evidenceSource);});
document.addEventListener('DOMContentLoaded',()=>renderEvidenceOverview());
