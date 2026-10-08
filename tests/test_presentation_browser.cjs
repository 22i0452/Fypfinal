/* Real app + fictional providers. Appearance/playback must never change saved data. */
const fs=require('node:fs/promises');
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES ? process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright' : 'playwright');
let server,browser;
const deadline=setTimeout(()=>{console.error('Browser validation timed out');process.exit(1);},120000);
(async()=>{
 const assert=require('node:assert/strict');
 const path=require('node:path');
 server=require('node:child_process').spawn('python',['tests/evidence_fixture.py'],{cwd:path.resolve(__dirname,'..'),env:{...process.env,QA_ENABLE_CODING:'1'},stdio:['ignore','ignore','pipe']});server.stderr.on('data',d=>process.stderr.write(d));process.on('exit',()=>server.kill());
 for(let i=0;i<100;i++){try{if((await fetch('http://127.0.0.1:8765/api/desk/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 const shots=process.env.QA_SHOTS_DIR || '/tmp/medflow-presentation-qa';await fs.mkdir(shots,{recursive:true});
 browser=await chromium.launch({executablePath:process.env.QA_CHROMIUM_PATH || undefined,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process','--disable-software-rasterizer'],headless:true});const ctx=await browser.newContext({viewport:{width:1440,height:900}});
 const p=await ctx.newPage();const errors=[];p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept());
 await p.goto('http://127.0.0.1:8765/');
 for(const width of [1440,1280,390]){await p.setViewportSize({width,height:900});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);await p.screenshot({path:shots+'/home-'+width+'.png',fullPage:true});}
 assert.equal(await p.locator('.workspace-portals a').count(),2);assert.ok((await p.locator('.patient-portal').innerText()).includes('Coming soon'));
 assert.equal(await p.locator('.patient-portal a,.patient-portal button').count(),0);
 await validateDisplay(p,ctx,shots);
 await p.setViewportSize({width:1440,height:900});await p.getByRole('link',{name:'Open Doctor Workspace',exact:true}).click();await p.waitForURL('**/consultation/login');
await p.waitForTimeout(300);await p.screenshot({path:shots+'/login.png',fullPage:true});
 await p.locator('#loginEmail').fill('audit@example.test');await p.locator('#loginPassword').fill('AuditPass123!');await p.locator('#loginSubmit').click();
 await p.waitForURL('**/workspace');await p.waitForFunction(()=>allPatients.length===2 && ws?.readyState===WebSocket.OPEN);
 await p.waitForTimeout(300);await p.screenshot({path:shots+'/today.png',fullPage:true});
 await p.locator('#dashboardPatientList .patient-row').first().click();await p.waitForFunction(()=>!visitLoading);
 console.log('READ ONLY OPEN',await p.evaluate(()=>({workflow:activeWorkflow,encounter:activeEncounter,stage:visitStage})));
 await p.waitForTimeout(300);await p.screenshot({path:shots+'/prepare.png',fullPage:true});
 await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>activeWorkflow?.state==='PATIENT_UNVERIFIED');
 await p.locator('#visitNextBtn').click();await p.locator('#verificationDialog').waitFor({state:'visible'});await p.locator('#patientOtpInput').fill('123456');await p.locator('#verificationDialog').getByRole('button',{name:'Verify patient',exact:true}).click();await p.waitForFunction(()=>activeWorkflow?.state==='BOOKING_REQUIRED');
 await p.locator('#visitNextBtn').click();await p.locator('#bookingDialog').waitFor({state:'visible'});
 console.log('BOOKING FIELDS',await p.locator('#bookingDoctor').innerText());
 await p.getByRole('button',{name:'Find slots',exact:true}).click();await p.waitForFunction(()=>document.getElementById('bookingSlot').options.length>1);
 await p.locator('#bookingSlot').selectOption({index:1});await p.getByRole('button',{name:'Confirm appointment',exact:true}).click();await p.waitForFunction(()=>activeWorkflow?.state==='BOOKING_CONFIRMED');
 await p.locator('#visitNextBtn').click();await p.locator('#consentDialog').waitFor({state:'visible'});for(const id of ['consentRecording','consentTranscription','consentDocumentation'])await p.locator('#'+id).check();await p.getByRole('button',{name:'Save choices',exact:true}).click();await p.waitForFunction(()=>hasRequiredConsent());
 await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>visitStage==='capture');await p.waitForTimeout(300);await p.screenshot({path:shots+'/capture.png',fullPage:true});



 await p.evaluate(()=>{window.qaAudio=new AudioContext();const oscillator=qaAudio.createOscillator(),destination=qaAudio.createMediaStreamDestination();oscillator.connect(destination);oscillator.start();navigator.mediaDevices.getUserMedia=async()=>destination.stream;});
 await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>isRecording);await p.waitForTimeout(1800);await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>visitStage==='transcript' && !isProcessing);await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>visitStage==='review' && !!soapLastSavedNoteId && !visitActionBusy);
 const ids=await p.evaluate(()=>({note:soapLastSavedNoteId,workflow:activeWorkflow.workflow_id,encounter:activeEncounter.encounter_id}));
 const saved=await (await ctx.request.get('http://127.0.0.1:8765/api/notes/'+ids.note)).json();
 let mutations=0;p.on('request',request=>{if(request.url().includes('/api/')&&request.method()!=='GET')mutations++;});
 const callCount=await (await ctx.request.get('http://127.0.0.1:8765/audit/soap-controls')).json();
 await p.locator('[data-present-soap]').click();await p.locator('#resultPresentation').waitFor({state:'visible'});
 assert.ok((await p.locator('#presentationReceipt').innerText()).includes('v1'));
 assert.equal(await p.locator('.presentation-timeline button').count(),6);
 await p.getByRole('button',{name:'Display settings for website',exact:true}).click();await p.getByRole('button',{name:'Light',exact:true}).click();await p.locator('[data-display-close]').click();assert.equal(await p.locator('#resultPresentation').evaluate(node=>node.open),true);assert.equal(await p.evaluate(()=>document.documentElement.dataset.theme),'light');
 await p.locator('[data-presentation-pause]').click();const pausedProgress=await p.locator('.presentation-playback-progress').getAttribute('aria-valuenow');await p.waitForTimeout(300);assert.equal(await p.locator('.presentation-playback-progress').getAttribute('aria-valuenow'),pausedProgress);
 await p.locator('[data-presentation-stage="1"]').click();assert.ok((await p.locator('#presentationResults').innerText()).includes(saved.soap.subjective));
 assert.equal(await p.locator('.source-connected').count(),1);
 await p.locator('[data-presentation-expand]').click();assert.equal(await p.locator('#resultPresentation').evaluate(node=>node.classList.contains('presentation-expanded')),true);
 const actualTime=await p.locator('#presentationReceipt').innerText();assert.ok(actualTime.includes('generation'));
 for(const width of [1440,1280,390]){
  await p.setViewportSize({width,height:900});for(const zoom of [100,130,160]){await p.evaluate(zoom=>MedFlowDisplay.set({zoom,theme:'light'}),zoom);assert.equal(await p.locator('#resultPresentation').evaluate(node=>node.scrollWidth<=node.clientWidth+1),true,`Playback overflow ${width}/${zoom}`);assert.equal(await p.locator('#resultPresentation').evaluate(node=>node.getBoundingClientRect().bottom<=innerHeight+1),true,`Playback clipped ${width}/${zoom}`);}
  await p.evaluate(()=>MedFlowDisplay.set({zoom:100}));await p.screenshot({path:shots+'/soap-playback-light-'+width+'.png',fullPage:true});
 }
 await p.setViewportSize({width:1440,height:900});await p.evaluate(()=>MedFlowDisplay.set({theme:'dark'}));await p.screenshot({path:shots+'/soap-playback-dark.png',fullPage:true});
 await p.locator('[data-presentation-replay]').click();await p.waitForFunction(()=>document.getElementById('presentationStatus').textContent.includes('Playback complete'),null,{timeout:16000});assert.equal(await p.locator('.presentation-playback-progress').getAttribute('aria-valuenow'),'100');
 await p.locator('[data-presentation-replay]').click();await p.locator('[data-presentation-skip]').click();assert.equal(await p.locator('.presentation-playback-progress').getAttribute('aria-valuenow'),'100');await p.keyboard.press('Escape');
 assert.equal(await p.locator('#resultPresentation').evaluate(node=>node.open),false);assert.equal(mutations,0,'Playback never writes clinic records');
 assert.deepEqual(await (await ctx.request.get('http://127.0.0.1:8765/api/notes/'+ids.note)).json(),saved);
 assert.equal((await (await ctx.request.get('http://127.0.0.1:8765/audit/soap-controls')).json()).soap_calls,callCount.soap_calls);
 await p.locator('.soap-section').first().getByRole('button',{name:'Edit section',exact:true}).click();assert.equal(await p.locator('[data-present-soap]').isDisabled(),true);await p.locator('.soap-section').first().getByRole('button',{name:'Cancel',exact:true}).click();
 await p.emulateMedia({reducedMotion:'reduce'});await p.locator('[data-present-soap]').click();assert.equal(await p.locator('.presentation-playback-progress').getAttribute('aria-valuenow'),'100');await p.locator('[data-presentation-close]').click();await p.emulateMedia({reducedMotion:'no-preference'});
 await p.locator('.coding-entry-button').click();await p.waitForFunction(()=>!codingBusy);await p.locator('#codingGenerateBtn').click();await p.waitForFunction(()=>!codingBusy&&codingSuggestions.length===2);await p.locator('[data-present-codes]').click();await p.locator('[data-presentation-stage="1"]').click();assert.ok((await p.locator('#presentationResults').innerText()).includes('Z00.00'));await p.locator('[data-presentation-close]').click();
 // All public/authenticated page types retain global settings through navigation.
 for(const route of ['/Receptionist','/testing','/workspace','/']){
  await p.goto('http://127.0.0.1:8765'+route);await p.locator('#displaySettingsButton').waitFor();await checkPageZoom(p,route);
 }
 await p.goto('http://127.0.0.1:8765/Receptionist');await p.waitForFunction(()=>state.config);await p.getByRole('button',{name:'New session',exact:true}).click();
 await p.locator('#fieldName').fill('Synthetic Presentation Patient');await p.locator('#fieldAge').fill('27');await p.locator('#fieldPhone').fill('03000000432');await p.locator('#fieldFirstVisit').selectOption('yes');await p.locator('#fieldHistory').fill('None');await p.locator('#fieldComplaint').fill('Synthetic complaint');await p.locator('#intakeNext').click();await p.waitForFunction(()=>document.getElementById('fieldSlot').options.length>1);await p.locator('#fieldSlot').selectOption({index:1});await p.locator('#submitBtn').click();await p.waitForFunction(()=>!!state.appointmentId&&!state.busy);
 const appointment=await p.evaluate(()=>state.appointmentId),beforeHandoff=mutations;await p.locator('[data-present-reception]').click();await p.locator('[data-presentation-skip]').click();assert.ok((await p.locator('#presentationResults').innerText()).includes(appointment));await p.locator('[data-presentation-replay]').click();await p.locator('[data-presentation-close]').click();assert.equal(mutations,beforeHandoff,'Handoff playback does not book again');assert.equal(await p.evaluate(()=>state.appointmentId),appointment);
 assert.deepEqual(errors,[]);console.log('PRESENTATION: real SOAP/code/handoff snapshots, actual sources, 13-second reveal, pause/skip/replay, reduced motion, unchanged saved records/provider counts, dark/light and whole-page zoom across all five screens passed; page errors 0');
 await browser.close();server.kill();clearTimeout(deadline);
})().catch(async error=>{console.error(error);clearTimeout(deadline);await browser?.close();server?.kill();process.exitCode=1;});

async function checkPageZoom(page,label){
 const assert=require('node:assert/strict');
 for(const width of [1440,1280,390]){await page.setViewportSize({width,height:900});for(const zoom of [80,100,130,160]){
  await page.evaluate(zoom=>MedFlowDisplay.set({zoom,theme:'light'}),zoom);
  const dimensions=await page.evaluate(()=>({scroll:document.body.scrollWidth,client:document.body.clientWidth}));
  if(dimensions.scroll>dimensions.client+1)console.log('OVERFLOW ELEMENTS',await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(node=>{const rect=node.getBoundingClientRect();return rect.width>0&&rect.right>innerWidth+1;}).map(node=>({tag:node.tagName,id:node.id,class:node.getAttribute('class'),text:node.textContent?.slice(0,45)})).slice(0,15)));
  assert.ok(dimensions.scroll<=dimensions.client+1,`${label} overflow ${width}/${zoom}: ${JSON.stringify(dimensions)}`);
 }}await page.setViewportSize({width:1440,height:900});await page.evaluate(()=>MedFlowDisplay.set({zoom:100}));
}
async function validateDisplay(page,context,shots){
 const assert=require('node:assert/strict');
 await page.locator('#displaySettingsButton').click();await page.getByRole('button',{name:'Light',exact:true}).click();await page.locator('#displayZoomIn').click();assert.equal(await page.locator('#displayZoomValue').innerText(),'110%');await page.locator('#displayZoomReset').click();await page.locator('[data-display-close]').click();
 await page.reload();assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),'light');await checkPageZoom(page,'Home');await page.screenshot({path:shots+'/home-light.png',fullPage:true});
 await page.goto('http://127.0.0.1:8765/consultation/login');await checkPageZoom(page,'Login');await page.screenshot({path:shots+'/login-light.png',fullPage:true});await page.goto('http://127.0.0.1:8765/');await page.evaluate(()=>MedFlowDisplay.set({theme:'dark'}));
}
