/* Saved measurements only. Replay has presentation pacing and never invokes a model. */
let reportConfig=null,reportRun=null,reportCaseId='',reportBusy=false,reportPoll=null,reportEpoch=0,reportConnectionLost=false;
let reportHistory=[],caseView='checks',audioClips=[],audioSelection=new Set(),replayId='',replayIndex=0,replayTimer=null,replayPlaying=false,comparisonPair=null;
const $=id=>document.getElementById(id);
const testIcon=name=>`<i data-lucide="${name}" aria-hidden="true"></i>`;
const testEscape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const testValue=value=>testEscape(typeof value==='string'?value:JSON.stringify(value,null,2));
const testTime=value=>value==null?'—':value<1000?Math.round(value)+' ms':(value/1000).toFixed(2)+' s';
const testLabel=status=>({PENDING:'Not run',RUNNING:'Running',PASSED:'Passed',FAILED:'Failed',ERROR:'Error',SKIPPED:'Not evaluated',CANCELLED:'Stopped',INTERRUPTED:'Interrupted'}[status]||status);
const metricNames={medicine_preservation:'Medicine wording checks',instruction_preservation:'Instruction wording checks',unsafe_blocked:'Unsafe checks detected',valid_allowed:'Valid actions allowed',source_integrity:'Source / state checks',speaker_role:'Authored role checks'};
function testBadge(status){return `<span class="test-status ${String(status).toLowerCase()}">${testEscape(testLabel(status))}</span>`;}
function testIcons(){window.lucide?.createIcons({attrs:{'stroke-width':1.35}});}
function testMessage(message='',error=false){$('testMessage').textContent=message;$('testMessage').classList.toggle('error',error);}
function rateText(rate){return rate?.denominator?`${rate.percent}% <small>(${rate.numerator} / ${rate.denominator})</small>`:'<small>Not tested</small>';}
function ratePlain(rate){return rate?.denominator?`${rate.numerator} / ${rate.denominator} · ${rate.percent}%`:'Not tested';}
function switchTab(name){
  if(name!=='replay')pauseReplay();
  document.querySelectorAll('#evaluationTabs [role=tab]').forEach(button=>{const active=button.dataset.tab===name;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;$('panel-'+button.dataset.tab).hidden=!active;});
  if(name==='replay')renderReplay();
}
function switchSubtab(group,name){
  document.querySelectorAll(`.subtabs[data-group="${group}"] [role=tab]`).forEach(button=>{const active=button.dataset.subtab===name;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;$(group+'-'+button.dataset.subtab).hidden=!active;});
}
function keyboardTabs(event){
  const target=event.target.closest('[role=tab]');if(!target||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  const tabs=[...target.parentElement.querySelectorAll('[role=tab]')];let index=tabs.indexOf(target);
  index=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  event.preventDefault();tabs[index].click();tabs[index].focus();
}
async function testApi(path,options={}){
  const response=await fetch('/api/demo-testing/'+path,{credentials:'same-origin',...options});const payload=await response.json().catch(()=>({}));
  if(response.status===401){location.assign('/consultation/login?next=/testing');throw new Error('Sign in to continue.');}
  if(!response.ok)throw new Error(typeof payload.detail==='string'?payload.detail:payload.detail?.message||'Unable to complete the test request.');
  return payload;
}
function reportRows(){return reportRun?.cases||reportConfig?.modes[$('testMode').value]?.map(item=>({...item,status:'PENDING',checks:[],steps:[],duration_ms:null}))||[];}
function renderReport(){
  const running=reportRun?.status==='RUNNING',mode=$('testMode').value,live=mode!=='synthetic';
  $('runTests').disabled=reportBusy||running||!reportConfig?.enabled||(live&&(!reportConfig.live_text_enabled||!$('confirmLive').checked))||(mode==='audio'&&!audioSelection.size);
  $('runTests').querySelector('span').textContent=running?'Running…':mode==='audio'?'Test recordings':'Run '+((reportConfig?.modes[mode]?.length||0)*Number($('testRepetitions').value))+' checks';
  $('stopTests').hidden=!running;$('stopTests').disabled=reportBusy;$('testMode').disabled=reportBusy||running;$('testHistory').disabled=reportBusy;$('testRepetitions').disabled=reportBusy||running;
  $('liveTestConsent').hidden=!live;$('testModeNote').textContent=live?'Real requests; fixed references. See request limits below.':'Isolated workflow checks. No dataset or API credits required.';
  $('exportTests').disabled=!reportRun;$('exportTestsPdf').disabled=!reportRun;
  const totals=reportRun?.totals,status=$('testRunStatus');status.className='test-status '+String(reportRun?.status||'pending').toLowerCase();status.textContent=testLabel(reportRun?.status||'PENDING');
  const finished=totals?totals.passed+totals.failed+totals.error+totals.skipped:0,total=totals?.total||reportRows().length;
  $('testProgress').setAttribute('aria-valuenow',String(finished));$('testProgress').setAttribute('aria-valuemax',String(total));$('testProgress').querySelector('span').style.width=(total?finished/total*100:0)+'%';
  $('testProgressLabel').textContent=reportRun?`${finished} / ${total} resolved${totals.skipped?' · '+totals.skipped+' untested':''}`:'Ready to run';
  $('testPackVersion').textContent=reportRun?.pack_version||reportConfig?.pack_version||'Loading…';
  const categories=[...new Set(reportRows().map(r=>r.category))],previous=$('categoryFilter').value;
  $('categoryFilter').innerHTML='<option value="all">All categories</option>'+categories.map(name=>`<option value="${testEscape(name)}">${testEscape(name)}</option>`).join('');$('categoryFilter').value=categories.includes(previous)?previous:'all';
  renderOverview();renderCoverage();renderScenarioList();renderScenarioDetail();refreshReplayOptions();testIcons();
}
function renderOverview(){
  const scores=reportRun?.scores,totals=reportRun?.totals;
  if(!scores){$('overviewResults').innerHTML=`<div class="test-empty">${testIcon('flask-conical')}<h2>Ready when you are.</h2><p>Run the fixed workflow pack, then inspect actual outcomes. Live text and recordings are optional. No score is shown before execution.</p></div>`;return;}
  const success=scores.success,timing=scores.timings;
  const categories=scores.categories.map(row=>`<div class="category-line"><span>${testEscape(row.name)}</span><div class="metric-bar"><span style="width:${row.percent??0}%"></span></div><b>${row.denominator?`${row.numerator} / ${row.denominator}`:'Not tested'}</b></div>`).join('');
  const metricRows=Object.entries(scores.metrics).filter(([,r])=>r.denominator).map(([name,rate])=>`<div class="metric-line"><span>${testEscape(metricNames[name]||name)}</span><strong>${rateText(rate)}</strong></div>`).join('');
  const audio=scores.audio.clips?`<section class="metric-section"><h3>Recorded audio · ${scores.audio.clips} ASR-scored clips</h3>${[['Raw ASR word errors',scores.audio.word_error_rate],['Raw ASR character errors',scores.audio.character_error_rate],['Medicine name precision',scores.audio.medicine_precision],['Medicine name recall',scores.audio.medicine_recall],['Text role agreement',scores.audio.roles]].map(([name,r])=>`<div class="metric-line"><span>${name}</span><strong>${rateText(r)}</strong></div>`).join('')}<p class="mini-legend">WER / CER: lower is better. Name and role agreement: higher is better. Small, uploader-attested sample; no acoustic or clinical claim.</p></section>`:'';
  $('overviewResults').innerHTML=`<div class="score-hero"><article class="score-card"><div class="score-ring" style="--progress:${success.percent??0}%"><strong>${success.percent==null?'—':success.percent+'%'}</strong></div><div><small>Scenario success</small><p>${success.numerator} passed / ${success.denominator} attempted</p><p>${totals.failed} failed · ${totals.error} errors</p></div></article><article class="score-card">${testIcon('list-checks')}<div><small>Completed assertions</small><strong>${scores.checks.numerator}<span style="font-size:14px;color:var(--qa-muted)"> / ${scores.checks.denominator}</span></strong><p>${scores.checks.percent==null?'Not measured':scores.checks.percent+'% passed'}</p></div></article><article class="score-card">${testIcon('timer')}<div><small>Median case wall time</small><strong style="font-size:25px">${testTime(timing.median_ms)}</strong><p>p95 ${testTime(timing.p95_ms)} · n = ${timing.n}</p></div></article></div><div class="result-grid"><section><h3>By category · passing scenarios / attempted</h3>${categories}<p class="mini-legend">${scores.completion.numerator} / ${scores.completion.denominator} attempted · ${totals.skipped+totals.pending+totals.running} not evaluated. Errors stay in the success denominator.</p></section><section><h3>Checks by purpose</h3>${metricRows||'<p class="detail-scope">This saved pack has no purpose-tagged checks. Scenario receipts remain available.</p>'}<p class="mini-legend">Separate sample checks; these percentages are not model confidence or clinical accuracy.</p>${audio}</section></div><div class="score-footnote"><span>${testEscape(reportRun.timing_scope)}</span><span>Total run ${testTime(reportRun.duration_ms)} · ${reportRun.repetitions||1} repetition(s)</span></div>`;
}
function renderCoverage(){
  const rows=reportRun?.scores?.categories;
  $('coverageResults').innerHTML=`<div class="panel-heading"><h2>Measured, and still open.</h2><span class="detail-scope">${reportRun?'This saved run':'No run selected'}</span></div>${rows?`<table class="coverage-table"><thead><tr><th>Category</th><th>Planned</th><th>Passed</th><th>Failed</th><th>Errors</th><th>Untested</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${testEscape(r.name)}</td><td>${r.planned}</td><td>${r.numerator}</td><td>${r.failed}</td><td>${r.errors}</td><td>${r.unassessed}</td></tr>`).join('')}</tbody></table>`:'<p class="detail-scope">Run a pack to see measured coverage.</p>'}<div class="metric-section" style="margin-top:24px"><h3>Outside this run’s claims</h3>${(reportRun?.unassessed||reportConfig?.unassessed||[]).map(name=>`<div class="unassessed-item">${testIcon('circle-minus')}${testEscape(name)}</div>`).join('')}<p class="mini-legend">Synthetic fixture checks exercise software paths. Live text has no audio. Recorded audio uses uploaded files; microphone capture and acoustic DER remain unassessed.</p></div>`;
}
function renderScenarioList(){
  const filter=$('testFilter').value,category=$('categoryFilter').value;
  const rows=reportRows().filter(item=>(category==='all'||category===item.category)&&(filter==='all'||filter==='attention'&&['FAILED','ERROR'].includes(item.status)||filter==='passed'&&item.status==='PASSED'||filter==='unevaluated'&&['PENDING','RUNNING','SKIPPED'].includes(item.status)));
  const icons={Medicines:'pill',Reception:'headset',Appointments:'calendar-check',Consultation:'audio-lines',SOAP:'file-text',Coding:'scan-line',Access:'shield-check','Live text':'radio',Guardrails:'shield',Privacy:'eye-off',Persistence:'database',Recovery:'rotate-ccw','Recorded audio':'mic'};
  $('caseCount').textContent=rows.length+' cases';
  $('scenarioList').innerHTML=rows.length?rows.map(item=>`<button class="scenario-row ${item.status.toLowerCase()} ${item.id===reportCaseId?'selected':''}" type="button" data-scenario="${testEscape(item.id)}" aria-pressed="${item.id===reportCaseId}">${testIcon(icons[item.category]||'flask-conical')}<span class="scenario-copy"><strong>${testEscape(item.title)}${reportRun?.repetitions>1?' · '+item.repetition:''}</strong><small>${testEscape(item.category)}${item.duration_ms!=null?' · '+testTime(item.duration_ms):''}</small></span>${testBadge(item.status)}</button>`).join(''):'<p class="test-filter-empty">No cases match this filter.</p>';
}
function renderScenarioDetail(){
  const item=reportRows().find(row=>row.id===reportCaseId),root=$('testDetail');
  if(!item){root._signature=null;root.innerHTML=`<div class="test-empty">${testIcon('scan-line')}<h2>Inspect one case.</h2><p>Choose a case. Checks, evidence and run details have their own tabs.</p></div>`;return;}
  const signature=JSON.stringify({case:item,view:caseView,run:reportRun?.run_id,diagnostics:reportRun?.runner_diagnostics});
  if(root._signature===signature)return;root._signature=signature;
  const scroll=root.scrollTop;
  const checks=(item.checks||[]).map(check=>{
    const values=`<div class="assertion-values"><div><small>EXPECTED</small><pre>${testValue(check.expected)}</pre></div><div><small>ACTUAL</small><pre>${testValue(check.actual)}</pre></div></div>`;
    const complex=typeof check.expected==='object'&&check.expected!==null||typeof check.actual==='object'&&check.actual!==null;
    return `<div class="assertion ${check.status.toLowerCase()}"><div class="assertion-head"><strong>${testEscape(check.label)}</strong>${testBadge(check.status)}</div>${complex?`<details class="assertion-records" ${check.status==='FAILED'?'open':''}><summary>Compare saved values</summary>${values}</details>`:values}</div>`;
  }).join('');
  const error=item.error?`<p class="test-message error">${testEscape(item.error.message)}${item.error.code?' · '+testEscape(item.error.code):''}</p>`:'';
  const content=caseView==='checks'?`${error}${checks||'<p class="detail-scope">No completed assertions yet. This case has not produced a measured result.</p>'}`:caseView==='evidence'?`${item.steps?.length?item.steps.map(step=>`<details class="test-step"><summary>${testEscape(step.label)}<span>${testTime(step.duration_ms)}</span></summary><pre>${step.data!=null?testValue(step.data):'Measured application action. No separate provider latency claim.'}</pre></details>`).join(''):'<p class="detail-scope">No execution receipts have been saved yet.</p>'}${item.audio_metrics?`<details class="test-step"><summary>Raw audio measurements</summary><pre>${testValue(item.audio_metrics)}</pre></details>`:''}<p class="detail-scope">Saved execution artifacts establish what happened, not clinical correctness.</p>`:`<p class="detail-scope">${testEscape(item.scope)}</p><p class="detail-scope">Case wall time ${testTime(item.duration_ms)} · includes setup and checks.</p><pre>${testValue(reportRun?{run_id:reportRun.run_id,protocol:reportRun.evaluation_protocol,pack:reportRun.pack_version,reference_sha256:reportRun.reference_sha256,environment:reportRun.environment,provider_calls:item.provider_calls,runner_diagnostics:reportRun.runner_diagnostics}:'Run this case to save a receipt.')}</pre>`;
  root.innerHTML=`<button class="test-button back-cases" id="backCases">${testIcon('arrow-left')}All cases</button><div class="detail-heading"><div><small>${testEscape(item.category)}</small><h2>${testEscape(item.title)}</h2></div>${testBadge(item.status)}</div><div class="detail-reference"><div><small>PREPARED INPUT</small><p dir="auto">${testEscape(item.input)}</p></div><div><small>EXPECTED OUTCOME</small><p>${testEscape(item.expected)}</p></div></div><div class="subtabs detail-tabs" role="tablist" aria-label="Case sections">${['checks','evidence','run'].map(name=>`<button id="case-${name}-tab" role="tab" aria-selected="${caseView===name}" aria-controls="caseSection" tabindex="${caseView===name?0:-1}" data-case-view="${name}">${name[0].toUpperCase()+name.slice(1)}</button>`).join('')}</div><div id="caseSection" role="tabpanel" aria-labelledby="case-${caseView}-tab">${content}</div>`;
  root.scrollTop=scroll;
}
async function refreshHistory(){
  const {runs}=await testApi('runs');reportHistory=runs;
  const options=runs.map(item=>`<option value="${testEscape(item.run_id)}">${testEscape(new Date(item.started_at).toLocaleString())} · ${testEscape(item.mode)} · ${testEscape(testLabel(item.status))}</option>`).join('');
  $('testHistory').innerHTML='<option value="">New run</option>'+options;$('testHistory').value=reportRun?.run_id||'';
  for(const id of ['compareBaseline','compareCurrent']){const prior=$(id).value;$(id).innerHTML='<option value="">Choose a saved run</option>'+options;$(id).value=runs.some(r=>r.run_id===prior)?prior:'';}
  if(reportRun)$('compareCurrent').value=reportRun.run_id;
  return runs;
}
async function compareReports(){
  const baseline=$('compareBaseline').value,current=$('compareCurrent').value;comparisonPair=null;$('exportComparison').disabled=true;
  if(!baseline||!current){$('comparisonResult').innerHTML='<p class="detail-scope">Choose two saved runs.</p>';return;}
  $('compareRuns').disabled=true;
  try{
    const result=await testApi('compare?baseline='+encodeURIComponent(baseline)+'&current='+encodeURIComponent(current));
    const summary=result.compatible?`<div class="compare-result-head"><strong class="compare-delta ${result.success_delta_pp<0?'negative':''}">${result.success_delta_pp>0?'+':''}${result.success_delta_pp} pp</strong><div><p style="margin:0;font-size:13px">Observed scenario success change</p><p class="detail-scope" style="margin:5px 0 0">${ratePlain(result.baseline.success)} → ${ratePlain(result.current.success)}</p></div></div>`:`<div class="compare-reasons"><strong>No improvement percentage available.</strong><br>${result.reasons.map(testEscape).join('<br>')}</div>`;
    $('comparisonResult').className='';$('comparisonResult').innerHTML=summary+`<table class="coverage-table"><thead><tr><th>Category</th><th>Baseline</th><th>Current</th><th>Change</th></tr></thead><tbody>${result.categories.map(row=>`<tr><td>${testEscape(row.name)}</td><td>${ratePlain(row.baseline)}</td><td>${ratePlain(row.current)}</td><td>${row.delta_pp==null?'—':(row.delta_pp>0?'+':'')+row.delta_pp+' pp'}</td></tr>`).join('')}</tbody></table><div class="metric-line"><span>Median case wall time</span><strong>${testTime(result.baseline.timings.median_ms)} → ${testTime(result.current.timings.median_ms)}</strong></div><p class="mini-legend">${testEscape(result.scope)}</p>`;
    comparisonPair={baseline,current};$('exportComparison').disabled=false;
  }catch(error){$('comparisonResult').innerHTML=`<p class="test-message error">${testEscape(error.message)}</p>`;}finally{$('compareRuns').disabled=false;}
}
function scheduleReportPoll(){clearTimeout(reportPoll);if(reportRun?.status==='RUNNING')reportPoll=setTimeout(pollReport,1000);}
async function pollReport(){
  const id=reportRun?.run_id,epoch=reportEpoch;if(!id)return;
  try{
    const result=await testApi('runs/'+encodeURIComponent(id));if(epoch!==reportEpoch)return;reportRun=result;renderReport();
    if(reportConnectionLost){reportConnectionLost=false;testMessage('Connection restored. Saved results loaded.');}
    if(result.status!=='RUNNING'){testMessage(result.message||'Run finished. Inspect actual checks and evidence.',result.status==='ERROR'||result.status==='FAILED');await refreshHistory();}
    renderReport();
  }catch(error){if(epoch===reportEpoch){reportConnectionLost=true;testMessage('Connection interrupted; reconnecting to the saved report. '+error.message,true);}}
  if(epoch===reportEpoch)scheduleReportPoll();
}
async function selectReport(id){
  const epoch=++reportEpoch;clearTimeout(reportPoll);pauseReplay();reportBusy=true;renderReport();
  try{
    reportRun=id?await testApi('runs/'+encodeURIComponent(id)):null;if(epoch!==reportEpoch)return;
    if(reportRun){$('testMode').value=reportRun.mode;$('testRepetitions').value=reportRun.repetitions||1;}
    reportCaseId=reportRows()[0]?.id||'';replayId='';replayIndex=0;testMessage(reportRun?.message||'');
  }catch(error){testMessage(error.message,true);}finally{if(epoch===reportEpoch){reportBusy=false;renderReport();scheduleReportPoll();}}
}
async function startReport(){
  if(reportBusy||reportRun?.status==='RUNNING')return;pauseReplay();reportBusy=true;renderReport();testMessage('Starting an isolated run…');
  try{
    const mode=$('testMode').value;
    reportRun=await testApi('runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode,confirm_live:$('confirmLive').checked,repetitions:Number($('testRepetitions').value),audio_ids:mode==='audio'?[...audioSelection]:[]})});
    reportEpoch++;reportCaseId=reportRun.cases[0].id;replayId='';replayIndex=0;$('testFilter').value='all';await refreshHistory();testMessage('Running checks in a temporary clinic. Saved patients and visits are untouched.');
  }catch(error){testMessage(error.message,true);}finally{reportBusy=false;renderReport();scheduleReportPoll();}
}
async function stopReport(){
  if(reportBusy||!reportRun)return;reportBusy=true;renderReport();
  try{reportRun=await testApi('runs/'+encodeURIComponent(reportRun.run_id)+'/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});clearTimeout(reportPoll);testMessage(reportRun.message||'Run stopped.');await refreshHistory();}
  catch(error){testMessage(error.message,true);}finally{reportBusy=false;renderReport();scheduleReportPoll();}
}
function refreshReplayOptions(){
  const rows=reportRows().filter(r=>['PASSED','FAILED','ERROR','SKIPPED'].includes(r.status)&&r.steps?.length);
  $('replayCase').innerHTML='<option value="">Choose a completed case</option>'+rows.map(r=>`<option value="${testEscape(r.id)}">${testEscape(r.title)} · ${testLabel(r.status)}</option>`).join('');
  if(!rows.some(r=>r.id===replayId)){replayId=rows[0]?.id||'';replayIndex=0;pauseReplay();}
  $('replayCase').value=replayId;$('replayPlay').disabled=!replayId;
  if(!$('panel-replay').hidden&&!replayPlaying)renderReplay();
}
function replayRows(){return reportRows().find(r=>r.id===replayId);}
function replayStepIcon(step){const stage=step.stage||step.label.toLowerCase();return /transcrib|asr|audio|capture/.test(stage)?'audio-lines':/translat|interpret|role|speaker/.test(stage)?'languages':/medicine|validat|reject|policy|check|gate/.test(stage)?'shield-check':/soap|draft/.test(stage)?'file-text':/store|saved|persist|receipt|restart|book/.test(stage)?'database':'workflow';}
function artifactView(step){
  if(step.data==null)return `<p class="detail-scope">Saved measured action: ${testTime(step.duration_ms)}. This receipt has no intermediate output.</p>`;
  if(typeof step.data!=='object')return `<div class="artifact-block"><p dir="auto">${testValue(step.data)}</p></div>`;
  const entries=Object.entries(step.data),simple=entries.filter(([,v])=>typeof v==='string'||typeof v==='number'||typeof v==='boolean');
  const structured=entries.filter(([key,value])=>value&&typeof value==='object'&&['proposed','result','soap','turns','fields','medicine_checks'].includes(key));
  return simple.map(([key,value])=>`<div class="artifact-block"><small>${testEscape(key.replaceAll('_',' ').toUpperCase())}</small><p dir="auto">${testEscape(value)}</p></div>`).join('')+structured.map(([key,value])=>`<div class="artifact-block"><small>${testEscape(key.replaceAll('_',' ').toUpperCase())}</small><pre>${testValue(value)}</pre></div>`).join('')+`<details class="test-step" ${simple.length||structured.length?'':'open'}><summary>Complete saved artifact</summary><pre>${testValue(step.data)}</pre></details>`;
}
function renderReplay(){
  const row=replayRows();$('replayPlay').querySelector('span').textContent=replayPlaying?'Pause replay':'Play saved steps';
  if(!row){$('replayStage').innerHTML=`<div class="test-empty">${testIcon('history')}<h2>Replay what actually happened.</h2><p>Finish a run, then walk through its saved actions and outputs. Presentation pacing does not alter the recorded timing.</p></div>`;return;}
  const steps=row.steps;replayIndex=Math.max(0,Math.min(replayIndex,steps.length-1));const current=steps[replayIndex];
  $('replayStage').innerHTML=`<div class="replay-title"><div><small>SAVED RUN · ${testEscape(row.category)}</small><h2>${testEscape(row.title)}</h2></div>${testBadge(row.status)}</div><div class="replay-rail" aria-label="Saved step sequence">${steps.map((step,index)=>`${index?`<span class="replay-connector ${index<=replayIndex?'done':''} ${replayPlaying&&index===replayIndex?'moving':''}"></span>`:''}<button class="replay-node ${index<replayIndex?'done':''} ${index===replayIndex?'active':''} ${replayPlaying?'playing':''}" data-replay-step="${index}" aria-pressed="${index===replayIndex}">${testIcon(replayStepIcon(step))}<span>${index+1} · ${testEscape(step.stage||(step.data!=null?'Inspect':'Action'))}</span></button>`).join('')}</div><article class="replay-artifact"><div class="artifact-heading">${testIcon(replayStepIcon(current))}<div><h3>${testEscape(current.label)}</h3><small>Step ${replayIndex+1} / ${steps.length} · ${current.duration_ms==null?'Saved output artifact':'Actual action wall time '+testTime(current.duration_ms)} · replay pace ${Number($('replayPace').value)/1000}s</small></div></div>${artifactView(current)}</article><div class="replay-end">${testIcon(replayIndex===steps.length-1?'check-check':'history')}<span>${replayIndex===steps.length-1?'Final saved outcome: '+testLabel(row.status)+'. '+row.checks.filter(c=>c.status==='PASSED').length+' / '+row.checks.length+' assertions passed.':'Displaying a saved receipt. No computation is being simulated as live.'}</span></div>`;
  testIcons();$('replayStage').querySelector('.replay-node.active')?.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
}
function pauseReplay(){clearTimeout(replayTimer);replayTimer=null;replayPlaying=false;if($('replayPlay'))$('replayPlay').querySelector('span').textContent='Play saved steps';}
function advanceReplay(){
  const row=replayRows();if(!replayPlaying||!row)return;
  replayTimer=setTimeout(()=>{if(replayIndex<row.steps.length-1){replayIndex++;renderReplay();advanceReplay();}else{pauseReplay();renderReplay();}},Number($('replayPace').value));
}
function toggleReplay(){if(replayPlaying){pauseReplay();renderReplay();return;}const row=replayRows();if(!row)return;if(replayIndex===row.steps.length-1)replayIndex=0;replayPlaying=true;renderReplay();advanceReplay();}
async function refreshAudio(){const {clips}=await testApi('audio');audioClips=clips;audioSelection=new Set([...audioSelection].filter(id=>clips.some(c=>c.clip_id===id)));renderAudioLibrary();}
function renderAudioLibrary(){
  $('audioSelectedCount').textContent=audioSelection.size+' / 6 selected';
  $('audioLibrary').innerHTML=audioClips.length?audioClips.map(c=>`<div class="audio-row"><input type="checkbox" id="pick-${testEscape(c.clip_id)}" data-audio-select="${testEscape(c.clip_id)}" ${audioSelection.has(c.clip_id)?'checked':''} aria-label="Select ${testEscape(c.script.title)}"><div><label for="pick-${testEscape(c.clip_id)}">${testEscape(c.script.title)}</label><small>${testEscape(c.script.split.replace('_',' '))} · ${testTime(c.duration_ms)} · ${c.sample_rate} Hz · uploader checked</small><audio controls preload="none" src="/api/demo-testing/audio/${encodeURIComponent(c.clip_id)}" aria-label="Reference recording"></audio><details class="test-step"><summary>Reference and fingerprint</summary><p dir="auto" class="detail-scope">${testEscape(c.script.reference)}</p><pre>${testValue({audio_sha256:c.audio_sha256,reference_sha256:c.reference_sha256,attestation:c.reference_attestation})}</pre></details></div><button class="test-button icon-button" data-audio-delete="${testEscape(c.clip_id)}" aria-label="Delete ${testEscape(c.script.title)}">${testIcon('trash-2')}</button></div>`).join(''):`<div class="test-empty">${testIcon('mic')}<h2>No recordings tested yet.</h2><p>Use the Scripts tab, record fictional speech, then add the WAV with its checked reference. No dataset purchase is needed.</p></div>`;
  testIcons();
}
function renderScript(id,target,compact=false){
  const row=reportConfig?.scripts.find(s=>s.id===id);if(!row){$(target).textContent='Choose a script.';return;}
  $(target).innerHTML=compact?testEscape(row.reference):`<span class="test-status">${testEscape(row.split.replace('_',' '))}</span><p class="detail-scope">${testEscape(row.instructions)}</p>${row.turns.map(t=>`<div class="script-turn"><small>${testEscape(t.speaker)}</small><p dir="auto">${testEscape(t.text)}</p></div>`).join('')}<p class="mini-legend">Read exactly as written. The gold script scores the output; it is never passed as an ASR hint. Role labels are evaluated from text meaning. Keep held-out clips separate from tuning.</p>`;
}
async function uploadAudio(event){
  event.preventDefault();$('uploadAudio').disabled=true;$('uploadMessage').textContent='Checking and saving recording…';
  try{
    const file=$('audioFile').files[0];if(!file||file.size>3000000)throw new Error('Choose a PCM WAV under 3 MB.');
    const form=new FormData($('audioUpload'));form.set('attested','true');await testApi('audio',{method:'POST',body:form});
    $('audioUpload').reset();$('uploadScript').value=reportConfig.scripts[0].id;renderScript($('uploadScript').value,'uploadReference',true);await refreshAudio();switchSubtab('audio','library');$('uploadMessage').textContent='Recording saved.';
  }catch(error){$('uploadMessage').textContent=error.message;}finally{$('uploadAudio').disabled=false;}
}
async function loadReportConfiguration(){
  $('retryTests').hidden=true;
  try{
    reportConfig=await testApi('configuration');
    for(const mode of ['live_text','audio']){const option=document.querySelector(`#testMode option[value="${mode}"]`);option.disabled=!reportConfig.live_text_enabled;option.textContent=(mode==='audio'?'Recorded audio':'Live text')+(reportConfig.live_text_enabled?' · uses credits':' · setup required');}
    $('testUnassessed').innerHTML=reportConfig.unassessed.map(name=>`<div class="unassessed-item">${testIcon('circle-minus')}${testEscape(name)}</div>`).join('')+(!reportConfig.live_text_enabled?`<p class="detail-scope">${testEscape(reportConfig.live_text_reason)}</p>`:'');
    const scriptOptions=reportConfig.scripts.map(s=>`<option value="${testEscape(s.id)}">${testEscape(s.title)} · ${s.split==='held_out'?'held-out':'development'}</option>`).join('');
    $('uploadScript').innerHTML=scriptOptions;$('scriptPicker').innerHTML=scriptOptions;renderScript($('uploadScript').value,'uploadReference',true);renderScript($('scriptPicker').value,'scriptDetail');
    await refreshAudio();const runs=await refreshHistory();if(runs.length)await selectReport(runs[0].run_id);else renderReport();
  }catch(error){testMessage(error.message,true);renderReport();$('testPackVersion').textContent='Unavailable';$('retryTests').hidden=false;}
}
document.addEventListener('DOMContentLoaded',async()=>{
  $('evaluationTabs').addEventListener('click',event=>{const button=event.target.closest('[data-tab]');if(button)switchTab(button.dataset.tab);});
  document.addEventListener('keydown',keyboardTabs);
  document.querySelectorAll('.subtabs[data-group]').forEach(root=>root.addEventListener('click',event=>{const button=event.target.closest('[data-subtab]');if(button)switchSubtab(root.dataset.group,button.dataset.subtab);}));
  $('toggleRunSettings').addEventListener('click',()=>{const open=$('runSettings').hidden;$('runSettings').hidden=!open;$('toggleRunSettings').setAttribute('aria-expanded',String(open));});
  $('runTests').addEventListener('click',startReport);$('stopTests').addEventListener('click',stopReport);$('retryTests').addEventListener('click',loadReportConfiguration);
  for(const id of ['testFilter','categoryFilter'])$(id).addEventListener('change',()=>{renderScenarioList();testIcons();});
  for(const id of ['confirmLive','testRepetitions'])$(id).addEventListener('change',renderReport);
  $('testMode').addEventListener('change',()=>{pauseReplay();reportRun=null;reportCaseId='';reportEpoch++;clearTimeout(reportPoll);$('testHistory').value='';testMessage('');if($('testMode').value!=='synthetic'){$('runSettings').hidden=false;$('toggleRunSettings').setAttribute('aria-expanded','true');}if($('testMode').value==='audio')switchTab('audio');renderReport();});
  $('testHistory').addEventListener('change',event=>selectReport(event.target.value));
  $('scenarioList').addEventListener('click',event=>{const button=event.target.closest('[data-scenario]');if(button){reportCaseId=button.dataset.scenario;caseView='checks';$('testDetail').scrollTop=0;$('caseWorkbench').classList.add('inspecting');renderScenarioList();renderScenarioDetail();testIcons();}});
  $('testDetail').addEventListener('click',event=>{if(event.target.closest('#backCases'))$('caseWorkbench').classList.remove('inspecting');const button=event.target.closest('[data-case-view]');if(button){caseView=button.dataset.caseView;renderScenarioDetail();testIcons();$('case-'+caseView+'-tab').focus();}});
  $('compareRuns').addEventListener('click',compareReports);
  for(const id of ['compareBaseline','compareCurrent'])$(id).addEventListener('change',()=>{comparisonPair=null;$('exportComparison').disabled=true;});
  $('exportComparison').addEventListener('click',()=>{if(comparisonPair)location.assign('/api/demo-testing/compare.pdf?baseline='+encodeURIComponent(comparisonPair.baseline)+'&current='+encodeURIComponent(comparisonPair.current));});
  $('exportTests').addEventListener('click',()=>{if(reportRun)location.assign('/api/demo-testing/runs/'+encodeURIComponent(reportRun.run_id)+'/export');});
  $('exportTestsPdf').addEventListener('click',()=>{if(reportRun)location.assign('/api/demo-testing/runs/'+encodeURIComponent(reportRun.run_id)+'/export.pdf');});
  $('replayPlay').addEventListener('click',toggleReplay);$('replayReset').addEventListener('click',()=>{pauseReplay();replayIndex=0;renderReplay();});$('replayCase').addEventListener('change',()=>{pauseReplay();replayId=$('replayCase').value;replayIndex=0;renderReplay();});$('replayPace').addEventListener('change',()=>{if(replayPlaying){clearTimeout(replayTimer);advanceReplay();}renderReplay();});
  $('replayStage').addEventListener('click',event=>{const button=event.target.closest('[data-replay-step]');if(button){pauseReplay();replayIndex=Number(button.dataset.replayStep);renderReplay();}});
  $('audioUpload').addEventListener('submit',uploadAudio);$('uploadScript').addEventListener('change',()=>renderScript($('uploadScript').value,'uploadReference',true));$('scriptPicker').addEventListener('change',()=>renderScript($('scriptPicker').value,'scriptDetail'));
  $('audioLibrary').addEventListener('change',event=>{
    const checkbox=event.target.closest('[data-audio-select]');if(!checkbox)return;const id=checkbox.dataset.audioSelect,clip=audioClips.find(c=>c.clip_id===id);
    if(checkbox.checked){const first=audioClips.find(c=>audioSelection.has(c.clip_id));if(audioSelection.size>=6||first&&first.script.split!==clip.script.split){checkbox.checked=false;testMessage('Choose up to six recordings from the same development or held-out split.',true);return;}audioSelection.add(id);}else audioSelection.delete(id);
    $('audioSelectedCount').textContent=audioSelection.size+' / 6 selected';renderReport();
  });
  $('audioLibrary').addEventListener('click',async event=>{const button=event.target.closest('[data-audio-delete]');if(!button)return;button.disabled=true;try{await testApi('audio/'+encodeURIComponent(button.dataset.audioDelete),{method:'DELETE',headers:{'Content-Type':'application/json'},body:'{}'});await refreshAudio();renderReport();}catch(error){testMessage(error.message,true);button.disabled=false;}});
  testIcons();await loadReportConfiguration();
});
addEventListener('pagehide',()=>{clearTimeout(reportPoll);pauseReplay();});
