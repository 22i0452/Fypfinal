/* Offline UI transport fixtures. Backend/worker measurements are tested in Python.
   QA_REPORT_JSON may supply an actual isolated run for browser inspection.
   No provider calls, listening server or working clinic access. */
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES?process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright':'playwright');
const root=path.resolve(__dirname,'..');let browser;
(async()=>{
 if(!process.env.QA_CONFIG_JSON||!process.env.QA_REPORT_JSON){const prepared=require('node:child_process').spawnSync(process.env.QA_PYTHON||'python',['-m','tests.evaluation_fixture'],{cwd:root,env:process.env,encoding:'utf8',timeout:60000});if(prepared.status!==0)throw new Error('Isolated fixture preparation failed: '+prepared.stderr);console.log('Actual fixture run: '+prepared.stdout.trim());}
 const config=JSON.parse(await fs.readFile(process.env.QA_CONFIG_JSON||'/tmp/medflow-evaluation-qa/configuration.json','utf8'));
 const report=JSON.parse(await fs.readFile(process.env.QA_REPORT_JSON||'/tmp/medflow-evaluation-qa/observed-report.json','utf8'));
 const shots=process.env.QA_SHOTS_DIR||'/tmp/medflow-evaluation-qa/screens';await fs.mkdir(shots,{recursive:true});
 browser=await chromium.launch({executablePath:process.env.QA_CHROMIUM_PATH||undefined,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process'],headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:960}}),page=await context.newPage(),errors=[],requests=[];
 let active=false,comparison=false;page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url());requests.push(url.pathname);
  if(url.hostname!=='medflow.test')return route.abort();
  const p=url.pathname;
  if(p==='/api/demo-testing/configuration')return route.fulfill({json:config});
  if(p==='/api/demo-testing/audio')return route.fulfill({json:{clips:[]}});
  if(p==='/api/demo-testing/runs'&&req.method()==='POST'){
    active=true;return route.fulfill({status:202,json:{...report,status:'RUNNING',duration_ms:null,cases:report.cases.map(r=>({...r,status:'PENDING',checks:[],steps:[]})),
        totals:{passed:0,failed:0,error:0,skipped:0,running:0,pending:report.cases.length,total:report.cases.length},scores:{...report.scores,success:{numerator:0,denominator:0,percent:null}}}});
  }
  if(p==='/api/demo-testing/runs')return route.fulfill({json:{runs:active?[{...report,cases:undefined}]:[]}});
  if(p==='/api/demo-testing/compare')return route.fulfill({json:{compatible:false,reasons:['Select two different runs'],baseline:report.scores,current:report.scores,
       success_delta_pp:null,categories:[],scope:'Explicit browser comparison transport fixture.'}});
  if(p.startsWith('/api/demo-testing/runs/'))return route.fulfill({json:report});
  if(p.startsWith('/api/'))return route.fulfill({status:404,json:{detail:'Offline UI fixture; operation unavailable.'}});
  const filename=p==='/testing'?path.join(root,'scribe/testing.html'):p.startsWith('/assets/')?path.join(root,'scribe',p):null;
  if(!filename)return route.fulfill({status:204});
  try{const body=await fs.readFile(filename);const ext=path.extname(filename);return route.fulfill({body,contentType:({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.woff':'font/woff','.ttf':'font/ttf','.svg':'image/svg+xml'})[ext]||'application/octet-stream'});}catch{return route.fulfill({status:404});}
 });
 await page.goto('http://medflow.test/testing');await page.waitForFunction(()=>!!reportConfig);
 assert.ok((await page.locator('#overviewResults').innerText()).includes('No score'));
 assert.equal(await page.locator('.studio-panel:visible').count(),1);
 await page.locator('#tab-overview').focus();await page.keyboard.press('ArrowRight');assert.equal(await page.locator('#tab-cases').getAttribute('aria-selected'),'true');await page.keyboard.press('Home');
 await page.locator('#runTests').click();await page.waitForFunction(()=>reportRun?.status==='PASSED');
 await page.waitForFunction(({passed,total})=>document.getElementById('overviewResults').textContent.includes(`${passed} passed / ${total} attempted`),{passed:report.totals.passed,total:report.cases.length});
 await page.locator('#tab-cases').click();assert.equal(await page.locator('.scenario-row').count(),report.cases.length);
 await page.locator('[data-scenario="guard-source-id"]').click();assert.ok((await page.locator('#testDetail').innerText()).includes('Forged output rejected'));
 await page.locator('[data-case-view="evidence"]').click();assert.ok((await page.locator('#caseSection').innerText()).includes('Controlled model output'));
 await page.locator('[data-case-view="run"]').click();assert.ok((await page.locator('#caseSection').innerText()).includes('reference_sha256'));
 await page.locator('#tab-replay').click();await page.locator('#replayCase').selectOption('guard-source-id');await page.locator('#replayPace').selectOption('800');
 const before=requests.filter(p=>p.startsWith('/api/')).length;await page.locator('#replayPlay').click();await page.waitForTimeout(1800);
 assert.equal(requests.filter(p=>p.startsWith('/api/')).length,before);assert.ok((await page.locator('#replayStage').innerText()).includes('U999'));assert.ok((await page.locator('#replayStage').innerText()).includes('Final saved outcome'));
 await page.screenshot({path:shots+'/replay-dark-desktop.png'});
 await page.locator('#tab-overview').click();await page.screenshot({path:shots+'/overview-dark-desktop.png'});
 await page.locator('#overview-compare-tab').click();await page.locator('#compareBaseline').selectOption(report.run_id);await page.locator('#compareCurrent').selectOption(report.run_id);await page.locator('#compareRuns').click();await page.waitForFunction(()=>document.getElementById('comparisonResult').textContent.includes('No improvement percentage'));
 assert.ok(!(await page.locator('#comparisonResult').innerText()).includes('+100'));
 await page.locator('#tab-audio').click();assert.ok((await page.locator('#audioLibrary').innerText()).includes('No recordings tested yet'));
 await page.locator('#audio-scripts-tab').click();await page.locator('#scriptPicker').selectOption('audio-three-speakers');assert.equal(await page.locator('.script-turn').count(),4);
 await page.locator('#tab-method').click();await page.locator('#method-guardrails-tab').click();assert.equal(await page.locator('.method-grid article').count(),6);
 await page.locator('#tab-overview').click();await page.locator('#overview-results-tab').click();
 for(const settings of [{width:1440,theme:'light',zoom:100},{width:1280,theme:'dark',zoom:160},{width:390,theme:'light',zoom:100}]){
  await page.setViewportSize({width:settings.width,height:960});
  await page.evaluate(({theme,zoom})=>{const r=document.documentElement;r.dataset.theme=theme;r.style.zoom=zoom/100;r.style.setProperty('--display-vh',`${innerHeight/(zoom/100)}px`);const w=innerWidth/(zoom/100);r.dataset.displayLayout=w<=700?'mobile':w<=1000?'compact':'wide';},settings);
  assert.equal(await page.locator('.studio-panel:visible').count(),1);
  const size=await page.evaluate(()=>({width:document.documentElement.scrollWidth,view:innerWidth}));assert.ok(size.width<=size.view+2,JSON.stringify(size));
  await page.screenshot({path:shots+`/overview-${settings.theme}-${settings.width}-${settings.zoom}.png`});
 }
 await page.locator('#tab-cases').click();if(await page.locator('#backCases').isVisible())await page.locator('#backCases').click();await page.locator('[data-scenario="short-confirmation"]').click();assert.equal(await page.locator('#testDetail').isVisible(),true);assert.equal(await page.locator('.test-scenarios').isVisible(),false);
 await page.locator('#backCases').click();assert.equal(await page.locator('.test-scenarios').isVisible(),true);assert.equal(await page.locator('#testDetail').isVisible(),false);
 await page.screenshot({path:shots+'/cases-light-mobile.png'});
 // Inspector escaping fixture, never published as a measured result.
 await page.evaluate(()=>{reportRun.cases[0].checks=[{label:'<script>bad()</script>',expected:'<img src=x onerror=bad()>',actual:'safe',status:'FAILED'}];reportCaseId=reportRun.cases[0].id;caseView='checks';renderScenarioDetail();document.getElementById('caseWorkbench').classList.add('inspecting');});
 assert.equal(await page.locator('#testDetail script').count(),0);assert.equal(await page.locator('#testDetail img').count(),0);assert.ok((await page.locator('#testDetail').innerText()).includes('<script>bad()'));
 assert.deepEqual(errors,[]);console.log('PASS: five tabs, keyboard navigation, measured counts, case subtabs, saved replay without requests, comparison eligibility, empty audio, fixed scripts, guardrails, dark/light, mobile list/detail, 160% zoom, escaped evidence; page errors 0. Offline UI transport fixtures.');
 await browser.close();
})().catch(async error=>{console.error(error);if(browser)await browser.close();process.exitCode=1;});
