/* Real run receipts; no canned success, fabricated score or animation delays. */
let reportConfig=null,reportRun=null,reportCaseId='',reportBusy=false,reportPoll=null,reportEpoch=0,reportConnectionLost=false;
const testIcon=name=>`<i data-lucide="${name}" aria-hidden="true"></i>`;
const testEscape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const testValue=value=>testEscape(typeof value==='string'?value:JSON.stringify(value,null,2));
const testTime=value=>value==null?'—':value<1000?Math.round(value)+' ms':(value/1000).toFixed(2)+' s';
const testLabel=status=>({PENDING:'Not run',RUNNING:'Running',PASSED:'Passed',FAILED:'Failed',ERROR:'Error',SKIPPED:'Not evaluated',CANCELLED:'Stopped',INTERRUPTED:'Interrupted'}[status]||status);
function testBadge(status){return `<span class="test-status ${String(status).toLowerCase()}">${testEscape(testLabel(status))}</span>`;}
function testIcons(){window.lucide?.createIcons({attrs:{'stroke-width':1.35}});}
function testMessage(message='',error=false){const root=document.getElementById('testMessage');root.textContent=message;root.classList.toggle('error',error);}
async function testApi(path,options={}){
  const response=await fetch('/api/demo-testing/'+path,{credentials:'same-origin',...options});
  const payload=await response.json().catch(()=>({}));
  if(response.status===401){location.assign('/consultation/login?next=/testing');throw new Error('Sign in to continue.');}
  if(!response.ok)throw new Error(typeof payload.detail==='string'?payload.detail:payload.detail?.message||'Unable to complete the test request.');
  return payload;
}
function reportRows(){return reportRun?.cases||reportConfig?.modes[document.getElementById('testMode').value]?.map(item=>({...item,status:'PENDING',checks:[],steps:[],duration_ms:null}))||[];}
function renderReport(){
  const running=reportRun?.status==='RUNNING',mode=document.getElementById('testMode').value;
  document.getElementById('runTests').disabled=reportBusy||running||!reportConfig?.enabled||(mode==='live_text'&&(!reportConfig.live_text_enabled||!document.getElementById('confirmLive').checked));
  document.getElementById('runTests').querySelector('span').textContent=running?'Checks running…':'Run '+(reportConfig?.modes[mode]?.length||'')+' checks';
  document.getElementById('stopTests').hidden=!running;document.getElementById('stopTests').disabled=reportBusy;
  document.getElementById('testMode').disabled=reportBusy||running;document.getElementById('testHistory').disabled=reportBusy;
  document.getElementById('liveTestConsent').hidden=mode!=='live_text';
  document.getElementById('testModeNote').textContent=mode==='live_text'?'Real provider requests. Fictional text only.':'No dataset or API credits required.';
  document.getElementById('exportTests').disabled=!reportRun;
  const totals=reportRun?.totals;
  document.getElementById('testPassed').textContent=totals?.passed??'—';
  document.getElementById('testFailed').textContent=totals?totals.failed+totals.error:'—';
  document.getElementById('testSkipped').textContent=totals?totals.skipped+totals.pending+totals.running:'—';
  document.getElementById('testElapsed').textContent=testTime(reportRun?.duration_ms??(running?Math.max(0,Date.now()-Date.parse(reportRun.started_at)):null));
  const status=document.getElementById('testRunStatus');status.className='test-status '+String(reportRun?.status||'pending').toLowerCase();status.textContent=testLabel(reportRun?.status||'PENDING');
  document.getElementById('testRunScope').textContent=reportRun?.timing_scope||(mode==='live_text'?'Provider timings are measured only when executed.':'Synthetic timings are not real provider speed.');
  const finished=totals?totals.passed+totals.failed+totals.error+totals.skipped:0,total=totals?.total||reportRows().length;
  const progress=document.getElementById('testProgress');progress.setAttribute('aria-valuenow',String(finished));progress.setAttribute('aria-valuemax',String(total));progress.querySelector('span').style.width=(total?finished/total*100:0)+'%';
  document.getElementById('testProgressLabel').textContent=reportRun?`${finished} / ${total} resolved${totals?.skipped?' · '+totals.skipped+' not evaluated':''}`:'Ready to run';
  document.getElementById('testPackVersion').textContent=reportRun?.pack_version||reportConfig?.pack_version||'Loading…';
  renderScenarioList();renderScenarioDetail();testIcons();
}
function renderScenarioList(){
  const filter=document.getElementById('testFilter').value;
  const rows=reportRows().filter(item=>filter==='all'||filter==='attention'&&['FAILED','ERROR'].includes(item.status)||filter==='passed'&&item.status==='PASSED'||filter==='unevaluated'&&['PENDING','RUNNING','SKIPPED'].includes(item.status));
  const icons={Reception:'headset',Appointments:'calendar-check',Consultation:'audio-lines',SOAP:'file-text',Coding:'scan-line',Access:'shield-check','Live text':'radio'};
  document.getElementById('scenarioList').innerHTML=rows.length?rows.map(item=>`<button class="scenario-row ${item.status.toLowerCase()} ${item.id===reportCaseId?'selected':''}" type="button" data-scenario="${testEscape(item.id)}" aria-pressed="${item.id===reportCaseId}">${testIcon(icons[item.category]||'flask-conical')}<span class="scenario-copy"><strong>${testEscape(item.title)}</strong><small>${testEscape(item.category)}${item.duration_ms!=null?' · '+testTime(item.duration_ms):''}</small></span>${testBadge(item.status)}</button>`).join(''):'<p class="test-filter-empty">No scenarios match this filter.</p>';
}
function renderScenarioDetail(){
  const item=reportRows().find(row=>row.id===reportCaseId),root=document.getElementById('testDetail');
  if(!item){root.innerHTML=`<div class="test-empty">${testIcon('scan-line')}<h2>Inspect the evidence.</h2><p>Choose a scenario to see its input, expected outcome and actual checks.</p></div>`;return;}
  const checkRows=(item.checks||[]).map(check=>{
    const values=`<div class="assertion-values"><div><small>EXPECTED</small><pre>${testValue(check.expected)}</pre></div><div><small>ACTUAL</small><pre>${testValue(check.actual)}</pre></div></div>`;
    const complex=check.expected!==null&&typeof check.expected==='object'||check.actual!==null&&typeof check.actual==='object';
    return `<div class="assertion ${check.status.toLowerCase()}"><div class="assertion-head"><strong>${testEscape(check.label)}</strong>${testBadge(check.status)}</div>${complex?`<details class="assertion-records" ${check.status==='FAILED'?'open':''}><summary>${check.status==='PASSED'?'Saved records match':'Saved records differ'} · Compare receipts</summary>${values}</details>`:values}</div>`;
  }).join('');
  const error=item.error?`<p class="test-message error" role="alert">${testEscape(item.error.message)}${item.error.code?' · '+testEscape(item.error.code):''}</p>`:'';
  const opened=root.dataset.scenario===item.id?Array.from(root.querySelectorAll('details')).map((entry,index)=>entry.open?index:-1):[];
  root.dataset.scenario=item.id;
  root.innerHTML=`<div class="detail-heading"><div><small>${testEscape(item.category)}</small><h2>${testEscape(item.title)}</h2></div>${testBadge(item.status)}</div><section><h3>Prepared input</h3><p>${testEscape(item.input)}</p></section><section><h3>Expected outcome</h3><p>${testEscape(item.expected)}</p></section><section><h3>Measured checks</h3>${error}${checkRows||`<p class="detail-scope">${item.status==='RUNNING'?'This scenario is executing. Completed assertions appear when it finishes.':item.status==='PENDING'?'Not run yet. No result has been measured.':'No completed assertions were returned.'}</p>`}</section><section><h3>Execution scope</h3><p class="detail-scope">${testEscape(item.scope)}</p>${item.duration_ms!=null?`<p class="detail-scope">Scenario wall time: ${testTime(item.duration_ms)} · includes setup and checks.</p>`:''}</section>${item.steps?.length?`<section><h3>Execution receipts</h3>${item.steps.map(step=>`<details class="test-step"><summary>${testEscape(step.label)}${step.duration_ms!=null?`<span>${testTime(step.duration_ms)}</span>`:''}</summary><pre>${step.data?testValue(step.data):'Measured application action duration. No provider latency claim.'}</pre></details>`).join('')}</section>`:''}${reportRun?`<details class="test-technical"><summary>Run details</summary><pre>${testValue({run_id:reportRun.run_id,pack_version:reportRun.pack_version,mode:reportRun.mode,started_at:reportRun.started_at,finished_at:reportRun.finished_at,environment:reportRun.environment})}</pre></details>`:''}`;
  root.querySelectorAll('details').forEach((entry,index)=>{if(opened.includes(index))entry.open=true;});
}
async function refreshHistory(){
  const {runs}=await testApi('runs'),root=document.getElementById('testHistory');
  root.innerHTML='<option value="">New run</option>'+runs.map(item=>`<option value="${testEscape(item.run_id)}">${testEscape(new Date(item.started_at).toLocaleString())} · ${item.mode==='synthetic'?'Synthetic':'Live text'} · ${testEscape(testLabel(item.status))}</option>`).join('');
  root.value=reportRun?.run_id||'';return runs;
}
function scheduleReportPoll(){clearTimeout(reportPoll);if(reportRun?.status==='RUNNING')reportPoll=setTimeout(pollReport,750);}
async function pollReport(){
  const id=reportRun?.run_id,epoch=reportEpoch;if(!id)return;
  try{
    const result=await testApi('runs/'+encodeURIComponent(id));if(epoch!==reportEpoch)return;
    reportRun=result;if(reportConnectionLost){reportConnectionLost=false;testMessage('Connection restored. Saved results loaded.');}
    if(result.status!=='RUNNING'){testMessage(result.message||'Run finished. Inspect each scenario for its measured checks.',result.status==='ERROR'||result.status==='FAILED');await refreshHistory();}
    renderReport();
  }catch(error){if(epoch===reportEpoch){reportConnectionLost=true;testMessage('Connection interrupted. The server may still be running; reconnecting to the saved report. '+error.message,true);}}
  if(epoch===reportEpoch)scheduleReportPoll();
}
async function selectReport(id){
  const epoch=++reportEpoch;clearTimeout(reportPoll);reportBusy=true;renderReport();
  try{
    reportRun=id?await testApi('runs/'+encodeURIComponent(id)):null;
    if(epoch!==reportEpoch)return;
    if(reportRun)document.getElementById('testMode').value=reportRun.mode;
    reportCaseId=reportRows()[0]?.id||'';testMessage(reportRun?.message||'');
  }catch(error){testMessage(error.message,true);}
  finally{if(epoch===reportEpoch){reportBusy=false;renderReport();scheduleReportPoll();}}
}
async function startReport(){
  if(reportBusy||reportRun?.status==='RUNNING')return;
  reportBusy=true;renderReport();testMessage('Starting an isolated scenario run…');
  try{
    reportRun=await testApi('runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:document.getElementById('testMode').value,confirm_live:document.getElementById('confirmLive').checked})});
    reportEpoch++;reportCaseId=reportRun.cases[0].id;document.getElementById('testFilter').value='all';await refreshHistory();testMessage('Running real application checks in a temporary clinic.');
  }catch(error){testMessage(error.message,true);}
  finally{reportBusy=false;renderReport();scheduleReportPoll();}
}
async function stopReport(){
  if(reportBusy||!reportRun)return;reportBusy=true;renderReport();
  try{reportRun=await testApi('runs/'+encodeURIComponent(reportRun.run_id)+'/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});clearTimeout(reportPoll);testMessage(reportRun.message||'Run stopped.');await refreshHistory();}
  catch(error){testMessage(error.message,true);}finally{reportBusy=false;renderReport();scheduleReportPoll();}
}
async function loadReportConfiguration(){
  document.getElementById('retryTests').hidden=true;
  try{
    reportConfig=await testApi('configuration');document.querySelector('#testMode option[value="live_text"]').disabled=!reportConfig.live_text_enabled;
    document.querySelector('#testMode option[value="live_text"]').textContent=reportConfig.live_text_enabled?'Live text · uses credits':'Live text · setup required';
    document.getElementById('testUnassessed').innerHTML=reportConfig.unassessed.map(item=>`<span class="unassessed-item">${testIcon('circle-minus')}${testEscape(item)} · Not tested</span>`).join('');
    const runs=await refreshHistory();if(runs.length)await selectReport(runs[0].run_id);else renderReport();
    const methodology=document.getElementById('testUnassessed');if(!reportConfig.live_text_enabled)methodology.insertAdjacentHTML('beforeend','<p>Optional live text setup: '+testEscape(reportConfig.live_text_reason)+'</p>');
    if(!runs.length && !reportConfig.live_text_enabled)testMessage('Synthetic workflow checks are ready. Optional live text setup is explained under the methodology.');
  }catch(error){testMessage(error.message,true);renderReport();document.getElementById('testPackVersion').textContent='Unavailable';document.getElementById('retryTests').hidden=false;}
}
document.addEventListener('DOMContentLoaded',async()=>{
  document.getElementById('runTests').addEventListener('click',startReport);
  document.getElementById('stopTests').addEventListener('click',stopReport);
  document.getElementById('testFilter').addEventListener('change',()=>{renderScenarioList();testIcons();});
  document.getElementById('confirmLive').addEventListener('change',renderReport);
  document.getElementById('testMode').addEventListener('change',()=>{reportRun=null;reportCaseId='';reportEpoch++;clearTimeout(reportPoll);document.getElementById('testHistory').value='';testMessage('');renderReport();});
  document.getElementById('testHistory').addEventListener('change',event=>selectReport(event.target.value));
  document.getElementById('scenarioList').addEventListener('click',event=>{const button=event.target.closest('[data-scenario]');if(button){reportCaseId=button.dataset.scenario;renderScenarioList();renderScenarioDetail();testIcons();if(innerWidth<=650)document.getElementById('testDetail').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth',block:'start'});}});
  document.getElementById('exportTests').addEventListener('click',()=>{if(reportRun)location.assign('/api/demo-testing/runs/'+encodeURIComponent(reportRun.run_id)+'/export');});
  testIcons();
  document.getElementById('retryTests').addEventListener('click',loadReportConfiguration);
  await loadReportConfiguration();
});
addEventListener('pagehide',()=>clearTimeout(reportPoll));
