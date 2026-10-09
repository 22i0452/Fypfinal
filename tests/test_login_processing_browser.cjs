/* Real pages and scripts; offline synthetic API responses only. */
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const root=path.resolve(__dirname,'..');let browser;
(async()=>{
 browser=await chromium.launch({executablePath:process.env.QA_CHROMIUM_PATH||'/tmp/chromium',headless:true,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 await page.routeWebSocket('**/ws',()=>{});
 page.on('pageerror',e=>errors.push(e.message));
 let releaseAuth,authStarted;const authGate=new Promise(resolve=>releaseAuth=resolve),authRequest=new Promise(resolve=>authStarted=resolve);
 await page.route('**/*',async route=>{
  const u=new URL(route.request().url()),p=u.pathname;if(u.hostname!=='medflow.test')return route.abort();
  if(p==='/api/auth/login')return route.fulfill({json:{ok:true}});
  if(p==='/api/auth/me'){authStarted();await authGate;return route.fulfill({json:{full_name:'Dr. Synthetic',email:'doctor@example.test',role:'DOCTOR'}});}
  if(p==='/api/demo-access')return route.fulfill({json:{demo:false}});
  if(['/api/patients','/api/notes','/api/templates'].includes(p))return route.fulfill({json:[]});
  if(p==='/api/appointments/doctor-queue')return route.fulfill({json:{appointments:[],timezone:'Asia/Karachi'}});
  if(p==='/api/workflows/capabilities')return route.fulfill({json:{}});
  if(p.startsWith('/api/'))return route.fulfill({status:404,json:{detail:'Offline fixture'}});
  const file=p==='/workspace'?path.join(root,'scribe/index.html'):p==='/consultation/login'?path.join(root,'consultation/login.html'):p.startsWith('/assets/')?path.join(root,'scribe',p):null;
  if(!file)return route.fulfill({status:204});
  try{return route.fulfill({body:await fs.readFile(file),contentType:({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2'})[path.extname(file)]||'application/octet-stream'});}catch{return route.fulfill({status:404});}
 });
 await page.goto('http://medflow.test/consultation/login');
 await page.locator('#loginEmail').fill('doctor@example.test');await page.locator('#loginPassword').fill('SyntheticPass123!');
 await page.locator('#loginSubmit').click();await authRequest;
 await page.waitForSelector('#workspaceBoot');
 assert.equal(await page.locator('.auth-shell').count(),0);
 assert.equal(await page.locator('#loginPanel').count(),0);
 assert.equal(await page.locator('.app-shell').isVisible(),false);
 assert.equal(await page.locator('#workspaceBoot').isVisible(),true);
 await page.screenshot({path:'/tmp/medflow-login-boot.png'});
 releaseAuth();await page.waitForFunction(()=>document.body.classList.contains('auth-ready'));
 assert.equal(await page.locator('#workspaceBoot').isVisible(),false);
 assert.equal(await page.locator('.app-shell').isVisible(),true);
 assert.ok((await page.locator('#greetingText').innerText()).includes('Dr. Synthetic'));
 await page.waitForFunction(()=>ws!==null);
 await page.evaluate(()=>{
   selectedPatient={_id:'PT-SYNTHETIC',name:'Synthetic Patient'};isProcessing=true;visitStage='processing';activeWorkflow={workflow_id:'WF-SYNTHETIC',state:'DOCUMENTATION_PROCESSING'};
   processTrace={run_id:'RUN-SYNTHETIC',events:[{sequence:1,stage:'translation',status:'running',at:new Date().toISOString(),duration_ms:2000,
     artifact:{provider_calls:[{task:'medicine_context',provider:'mock',model:'mock-chat',status:'complete',duration_ms:2300}],activity:{task:'medicine_matching',provider:'mock',model:'mock-chat',status:'running'}}}]};
   processSelected='translation';renderSelectedPatient();showVisitWorkspace();renderClinicFlow();
 });
 assert.ok((await page.locator('.process-live-status .provider-steps').innerText()).includes('Identifying medicine mentions in context'));
 assert.ok((await page.locator('.process-live-status .provider-steps').innerText()).includes('2.3s · done'));
 assert.ok((await page.locator('.process-live-status .provider-step.running').innerText()).includes('Comparing uncertain medicine names'));
 assert.ok((await page.locator('[data-process-clock]').innerText()).toLowerCase().includes('elapsed'));
 assert.equal(await page.locator('.process-live-status').isVisible(),true);
 await page.locator('.process-live-status').scrollIntoViewIfNeeded();
 await page.screenshot({path:'/tmp/medflow-processing-substeps.png'});
 await page.evaluate(()=>{fullTranscript=[{utterance_id:'U1',speaker:'Doctor',original_text:'پیناڈول لیں۔',clinical_english:'Take Panadol.'}];renderProcess();});
 assert.equal(await page.locator('.process-translation-preview').isVisible(),true);
 await page.locator('.process-translation-preview summary').click();
 assert.ok((await page.locator('.process-translation-preview').innerText()).includes('Take Panadol.'));
 await page.evaluate(()=>{processReplay=true;replayEvents=processTrace.events;renderProcess();});
 assert.equal(await page.locator('[data-process-clock]').count(),0);
 assert.deepEqual(errors,[]);
 await page.route('**/api/auth/me',route=>route.fulfill({status:503,json:{detail:'Synthetic unavailable'}}));
 await page.goto('http://medflow.test/workspace');await page.locator('#workspaceBootRetry').waitFor({state:'visible'});
 assert.equal(await page.locator('.app-shell').isVisible(),false);
 assert.equal(await page.locator('.auth-shell').count(),0);
 await page.route('**/api/auth/me',route=>route.fulfill({status:401,json:{detail:'Synthetic expired'}}));
 await page.locator('#workspaceBootRetry').click();await page.waitForURL('**/consultation/login');
 assert.equal(await page.locator('#loginPanel').isVisible(),true);
 assert.deepEqual(errors,[]);
 console.log('PASS: actual sign-in navigation, held session check shows current boot only, no legacy login DOM, authenticated workspace, real substep receipts/clock, replay clock freeze, recoverable session failure, expired session redirects; page errors 0. Offline fixtures.');
 await browser.close();
})().catch(async error=>{console.error(error);if(browser)await browser.close();process.exit(1);});
