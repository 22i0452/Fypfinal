/* Presentation adapters read the currently persisted version; they never generate it. */
(function () {
  'use strict';
  const sections = ['subjective','objective','assessment','plan'];
  const title = key => key.charAt(0).toUpperCase() + key.slice(1);
  const sources = turns => (turns || []).map((turn, i) => ({id: turn.utterance_id || String(i+1), label: `${turn.speaker || 'Unknown'} · ${turn.utterance_id || i+1}`, text: turn.original_text || turn.text || turn.clinical_english || ''}));
  function button(label, action) {const node = document.createElement('button'); node.type = 'button'; node.className = 'present-result-button'; node.innerHTML = studioIcon('presentation') + label; node.addEventListener('click', action); return node;}
  function readySoap() {return !!generatedSoap && !!soapLastSavedNoteId && !soapDraftTouched && !Object.values(soapSectionEditing).some(Boolean) && !visitLocked();}
  function soapSnapshot() {
    if (!readySoap()) return null;
    const report = currentEvidenceReport(), claims = report?.claims || [];
    const latestDraft = processTrace?.events?.filter(e => e.stage === 'draft' && e.status === 'complete').at(-1);
    const initialVersion = currentNoteVersion === 1;
    const stages = [{label:'Source', title:'Reviewed conversation', icon:'messages-square', detail:'Source turns attached to this saved SOAP version.', rows: fullTranscript.map(turn => ({label: `${turn.speaker} · ${turn.utterance_id}`, text: turn.clinical_english || turn.original_text || turn.text, sourceIds:[turn.utterance_id]}))}];
    for (const key of sections) {
      const rows = claims.filter(row => row.section === key);
      stages.push({label:key === 'subjective' ? 'S' : key === 'objective' ? 'O' : key === 'assessment' ? 'A' : 'P', title:title(key), icon: key === 'plan' ? 'clipboard-list' : 'file-text', detail:'Returned SOAP content. Linked turns are model attributions for doctor review.',
        rows: rows.length ? rows.map(row => ({label:title(key), text:row.text, badge:row.label, tone:row.status === 'checked' ? 'checked' : row.status === 'failed' ? 'failed' : 'review', sourceIds:row.source_ids})) : [{label:title(key), text:generatedSoap[key] || 'Not documented.', badge:'No claim-level source recorded', tone:'review'}]});
    }
    const checkRows = claims.flatMap(row => (row.checks || []).map(check => ({label:check.label, text:check.detail, badge:check.status, tone:check.status === 'passed' ? 'checked' : check.status === 'failed' ? 'failed' : 'review', sourceIds:row.source_ids})));
    stages.push({label:'Checks', title:'Saved evidence & review state', icon:'shield-check', detail:'Recorded structural checks. Clinical correctness and calibrated confidence are not measured.', rows:[
      {label:'Saved note', text:`${soapLastSavedNoteId} · version ${currentNoteVersion} · ${generatedNoteState.replaceAll('_',' ')}`, badge:generatedNoteState === 'APPROVED_BY_DOCTOR' ? 'Doctor approved' : 'Doctor review required', tone:generatedNoteState === 'APPROVED_BY_DOCTOR' ? 'checked' : 'review'},
      ...checkRows,
      ...(report?.warnings || []).map(text => ({label:'Warning', text, tone:'review'})),
      ...(report?.missing_information || []).map(text => ({label:'Missing information', text, tone:'review'}))]});
    return {title:'Conversation → SOAP', receipt:`Saved note · v${currentNoteVersion}${initialVersion && Number.isFinite(latestDraft?.duration_ms) ? ` · generation ${(latestDraft.duration_ms/1000).toFixed(2)}s measured` : ''}`, duration:13000, sourceTitle:'Conversation turns', sources:sources(fullTranscript), stages};
  }
  window.presentSoapResult = () => {const result = soapSnapshot(); if (result) MedFlowPresentation.open(result);};
  function renderSoapPresentation() {
    const header = document.querySelector('#soapContent .soap-header'); if (!header) return;
    let entry = header.querySelector('[data-present-soap]');
    if (!entry) {entry = button('Present SOAP', window.presentSoapResult); entry.dataset.presentSoap = ''; (header.querySelector('.soap-actions') || header).append(entry);}
    entry.disabled = !readySoap(); entry.title = entry.disabled ? 'Finish the current action and save or cancel SOAP edits first.' : 'Animate this saved SOAP version. No new API calls.';
    studioIcons();
  }
  const baseSoap = renderSoapNote;
  renderSoapNote = function (...args) {baseSoap(...args); renderSoapPresentation();};
  const baseFlow = renderClinicFlow;
  renderClinicFlow = function (...args) {baseFlow(...args); renderSoapPresentation();};
  window.presentProcessResult = () => {
    if (visitLocked() || !processTrace?.events?.length) return;
    const stages = [];
    for (const [key,label,icon] of PROCESS_STAGES) {
      const event = processTrace.events.filter(e => e.stage === key && ['complete','failed'].includes(e.status)).at(-1); if (!event) continue;
      const a = event.artifact || {}; let rows;
      if (event.status === 'failed') rows = [{label:'Recorded failure', text:a.message || a.code || 'Stage failed.', tone:'failed'}];
      else if (key === 'audio') rows = [{label:'Captured audio', text:`${a.seconds}s · ${a.sample_rate} Hz · retention ${a.retained ? 'allowed' : 'off'}`}];
      else if (key === 'speech') rows = [{label:a.language || 'Transcript', text:a.text || 'No transcript recorded.'}];
      else if (key === 'roles' || key === 'translation') rows = (a.utterances || []).map(turn => ({label:`${turn.speaker} · ${turn.utterance_id}`, text:key === 'translation' ? turn.clinical_english || 'Translation unavailable' : turn.original_text || turn.text, sourceIds:[turn.utterance_id]}));
      else if (key === 'draft') rows = sections.map(section => ({label:title(section), text:a.soap?.[section] || 'Not documented.'}));
      else rows = [{label:'Source linkage', text:`${a.linked_claims || 0} of ${a.claim_count || 0} statements have attached sources.`, tone:'review'}, {label:'Reference check', text:a.known_references ? 'Attached IDs exist in the transcript.' : 'Reference check unavailable.', tone:a.known_references ? 'checked' : 'review'}, ...(a.warnings || []).map(text => ({label:'Warning', text, tone:'review'}))];
      stages.push({label,title:label,icon,measuredMs:event.duration_ms,detail:key === 'roles' ? 'Saved role attribution. Distinct acoustic voices and alignment are unmeasured.' : key === 'draft' ? 'Initial returned SOAP artifact. Current saved edits are available through Present SOAP.' : 'Artifact from this saved capture run.', rows});
    }
    if (stages.length) MedFlowPresentation.open({title:'The captured process', receipt:`Saved run ${processTrace.run_id} · original operation timings`, sourceTitle:'Saved capture turns', sources:sources(processTrace.events.filter(e => e.stage === 'translation' && e.status === 'complete').at(-1)?.artifact?.utterances || []), stages});
  };
  // Replace only the old presentation replay entry; live observability is unchanged.
  startProcessReplay = window.presentProcessResult;
  window.presentCodingResult = () => {
    if (codingBusy) return;
    const note = resolveCodingNote(), current = codingSuggestions.filter(item => !item.stale); if (!note || !current.length) return;
    const claimRows = sections.flatMap(section => (note.soap?.structured_soap?.[section] || []).map(claim => ({id:claim.claim_id,label:title(section),text:claim.text})));
    const sourceRows = claimRows.length ? claimRows : sections.map(section => ({id:section,label:title(section),text:note.soap?.[section] || 'Not documented.'}));
    const stages = [{label:'SOAP',title:'Saved SOAP source',icon:'file-text',detail:`Version ${note.version}.`,rows:sourceRows.map(row => ({label:row.label,text:row.text}))}];
    for (const system of ['ICD-10','CPT']) stages.push({label:system,title:`${system} suggestions`,icon:'scan-line',detail:'Returned suggestions. Catalogue validity and clinical correctness are unassessed.',rows:current.filter(item => item.system === system).map(item => ({label:item.code,text:item.description,badge:String(item.status).replaceAll('_',' '),tone:'review',sourceIds:item.evidence_ids || []}))});
    stages.push({label:'Review',title:'Version & review receipt',icon:'git-branch',detail:'Only suggestions attached to the selected current version are included.',rows:current.map(item => ({label:item.code,text:`${(item.evidence_ids || []).length} attached SOAP statement(s) · ${String(item.status).replaceAll('_',' ')}`,badge:'Clinical correctness unassessed',tone:'review',sourceIds:item.evidence_ids || []}))});
    MedFlowPresentation.open({title:'SOAP → ICD-10 / CPT',receipt:`Saved note · v${note.version}`,sourceTitle:'SOAP statements',sources:sourceRows,stages});
  };
  const baseCoding = renderCodingResults;
  renderCodingResults = function (...args) {
    baseCoding(...args); const root = document.getElementById('codingResults'); if (!root) return;
    if (!codingBusy && codingSuggestions.some(item => !item.stale)) {const entry = button('Present codes', window.presentCodingResult); entry.dataset.presentCodes = ''; root.prepend(entry); studioIcons();}
  };
  const baseOpen = openPatientVisit;
  openPatientVisit = async function (...args) {if (!canLeaveVisit()) return false; MedFlowPresentation.close(); return baseOpen(...args);};
})();
