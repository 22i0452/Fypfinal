/* Actual report runner; scripted audio/providers remain explicitly synthetic. */
const assert=require('node:assert/strict');
const fs=require('node:fs/promises'),path=require('node:path');
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES?process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright':'playwright');
let browser,server;
const deadline=setTimeout(()=>{console.error('Demo report browser deadline');process.exit(1);},120000);
(async()=>{
 server=require('node:child_process').spawn('python',['tests/evidence_fixture.py'],{cwd:path.resolve(__dirname,'..'),env:{...process.env,QA_ENABLE_CODING:'1'},stdio:['ignore','ignore','pipe']});server.stderr.on('data',d=>process.stderr.write(d));process.on('exit',()=>server.kill());
 for(let i=0;i<100;i++){try{if((await fetch('http://127.0.0.1:8765/api/desk/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 const shots=process.env.QA_SHOTS_DIR||'/tmp/medflow-report-qa';await fs.mkdir(shots,{recursive:true});
 browser=await chromium.launch({executablePath:process.env.QA_CHROMIUM_PATH||undefined,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process','--disable-software-rasterizer'],headless:true});
 const ctx=await browser.newContext({viewport:{width:1440,height:1000}}),p=await ctx.newPage(),errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.goto('http://127.0.0.1:8765/');await p.getByRole('link',{name:'Demo testing report'}).click();await p.waitForURL('**/consultation/login?next=/testing');
 await p.locator('#loginEmail').fill('audit@example.test');await p.locator('#loginPassword').fill('AuditPass123!');await p.locator('#loginSubmit').click();await p.waitForURL('**/testing');await p.waitForFunction(()=>typeof reportConfig!=='undefined'&&!!reportConfig);
 assert.equal(await p.locator('.scenario-row').count(),16);assert.equal(await p.locator('#testPassed').innerText(),'—');assert.equal(await p.locator('#testMode option[value="live_text"]').evaluate(node=>node.disabled),true);
 await p.locator('.scenario-row[data-scenario="short-confirmation"]').click();assert.ok((await p.locator('#testDetail').innerText()).includes('Not run yet'));
 const original=await ctx.request.get('http://127.0.0.1:8765/api/patients');const originalPatients=await original.json();
 await p.locator('#runTests').click();await p.waitForFunction(()=>reportRun?.status==='RUNNING');const first=await p.evaluate(()=>reportRun.run_id);
 assert.equal(await p.locator('#runTests').isDisabled(),true);await p.reload();await p.waitForFunction(()=>reportRun?.run_id && reportConfig);
 await p.waitForFunction(()=>reportRun?.status!=='RUNNING'&&reportRun?.totals?.passed===16,null,{timeout:45000});assert.equal(await p.evaluate(()=>reportRun.run_id),first);
 assert.equal(await p.locator('#testPassed').innerText(),'16');assert.equal(await p.locator('#testFailed').innerText(),'0');assert.equal(await p.locator('#testSkipped').innerText(),'0');
 assert.ok((await p.locator('#testRunScope').innerText()).includes('not provider speed'));
 await p.locator('.scenario-row[data-scenario="coding-after-edit"]').click();assert.ok((await p.locator('#testDetail').innerText()).includes('Old code approval blocked'));assert.ok((await p.locator('#testDetail').innerText()).includes('409'));
 for(const width of [1440,1280,390]){await p.setViewportSize({width,height:1000});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);await p.screenshot({path:shots+'/report-'+width+'.png',fullPage:true});}
 await p.locator('#testFilter').selectOption('attention');assert.equal(await p.locator('.scenario-row').count(),0);await p.locator('#testFilter').selectOption('all');
 const download=await Promise.all([p.waitForEvent('download'),p.locator('#exportTests').click()]);const filepath=await download[0].path(),exported=JSON.parse(await fs.readFile(filepath,'utf8'));assert.equal(exported.run_id,first);assert.equal(exported.totals.passed,16);
 const current=await ctx.request.get('http://127.0.0.1:8765/api/patients');
 // The existing legacy import refreshes updated_at on list reads; compare all
 // other fields. Python isolation checks compare an actual saved sentinel too.
 const stable=rows=>rows.map(({updated_at,...patient})=>patient);assert.deepEqual(stable(await current.json()),stable(originalPatients));
 // Check the failure inspector with a visibly synthetic transport fixture.
 const failure=structuredClone(exported);failure.status='FAILED';failure.totals.passed=15;failure.totals.failed=1;failure.cases[0].status='FAILED';failure.cases[0].checks=[{label:'QA failure presentation','expected':'23','actual':'22','status':'FAILED'}];
 await p.route('**/api/demo-testing/runs/'+first,route=>route.fulfill({json:failure}));await p.evaluate(id=>selectReport(id),first);await p.locator('.scenario-row[data-scenario="short-confirmation"]').click();assert.ok((await p.locator('#testDetail').innerText()).includes('QA failure presentation'));assert.equal(await p.locator('.assertion.failed').count(),1);await p.screenshot({path:shots+'/report-failure-390.png',fullPage:true});await p.unroute('**/api/demo-testing/runs/'+first);
 await p.setViewportSize({width:1440,height:1000});await p.locator('#runTests').click();await p.waitForFunction(()=>reportRun?.status==='RUNNING');const stopped=await p.evaluate(()=>reportRun.run_id);await p.locator('#stopTests').click();await p.waitForFunction(()=>reportRun?.status==='CANCELLED');assert.ok(await p.evaluate(()=>reportRun.totals.skipped>0));
 await p.reload();await p.waitForFunction(()=>reportRun?.status==='CANCELLED');assert.equal(await p.evaluate(()=>reportRun.run_id),stopped);await p.locator('#testHistory').selectOption(first);await p.waitForFunction(()=>reportRun?.status==='PASSED');assert.equal(await p.locator('#testPassed').innerText(),'16');
 await p.locator('.home-account').click();await p.waitForURL('**/workspace');await p.waitForFunction(()=>typeof allPatients!=='undefined'&&allPatients.length===2);await p.getByRole('button',{name:'Demo testing',exact:true}).click();await p.waitForURL('**/testing');await p.waitForFunction(()=>typeof reportConfig!=='undefined'&&reportConfig&&reportRun?.status==='CANCELLED');
 await p.route('**/api/demo-testing/configuration',route=>route.fulfill({status:503,json:{detail:'Synthetic configuration outage'}}));await p.reload();await p.locator('#retryTests').waitFor({state:'visible'});assert.equal(await p.locator('#runTests').isDisabled(),true);await p.unroute('**/api/demo-testing/configuration');await p.locator('#retryTests').click();await p.waitForFunction(()=>reportConfig&&reportRun?.status==='CANCELLED'&&!reportBusy);assert.equal(await p.locator('#retryTests').isVisible(),false);
 assert.deepEqual(errors,[]);console.log('REPORT: login return, real 16-case isolated runner, reload recovery, unchanged clinic, measured sources, failure inspection fixture, JSON download, cancel/skipped/history, home/workspace navigation; three viewport widths; page errors 0');
 await browser.close();server.kill();clearTimeout(deadline);
})().catch(async e=>{console.error(e);clearTimeout(deadline);if(browser)await browser.close();if(server)server.kill();process.exitCode=1;});
