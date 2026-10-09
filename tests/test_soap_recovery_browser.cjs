/* Real workspace/scripts, no external services or patient records. */
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
const root=path.resolve(__dirname,'..');let browser;
const draft={note_id:'NOTE-SYNTHETIC',patient_id:'PT-SYNTHETIC',encounter_id:'ENC-SYNTHETIC',patient_name:'Synthetic Patient',version:1,state:'AI_DRAFT',
 soap:{subjective:'Sore throat and fever for two days.',objective:'Not documented.',assessment:'Not documented.',plan:'Take Motilium, one tablespoon.',
 structured_soap:{warnings:['A transcript-based draft was created instead of an accepted model draft. Clinician review is required.']}},
 transcript:[{utterance_id:'U1',speaker:'Doctor',original_text:'موٹیلیم لیں۔',clinical_english:'Take Motilium, one tablespoon.'}]};
(async()=>{
 browser=await chromium.launch({executablePath:process.env.QA_CHROMIUM_PATH||'/tmp/chromium',headless:true,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[];
 page.on('pageerror',e=>errors.push(e.message));await page.routeWebSocket('**/ws',()=>{});
 let fail=true,release,started;const gate=new Promise(r=>release=r),requestStart=new Promise(r=>started=r);
 await page.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname;if(u.hostname!=='medflow.test')return route.abort();
  if(p==='/api/auth/me')return route.fulfill({json:{full_name:'Dr. Synthetic',email:'doctor@example.test',role:'DOCTOR'}});
  if(['/api/patients','/api/notes','/api/templates'].includes(p))return route.fulfill({json:[]});
  if(p==='/api/appointments/doctor-queue')return route.fulfill({json:{appointments:[],timezone:'Asia/Karachi'}});
  if(p==='/api/workflows/capabilities')return route.fulfill({json:{}});
  if(p.endsWith('/regenerate-soap')){
   writes.push(req.postDataJSON());if(fail){started();await gate;return route.fulfill({status:503,json:{detail:'The summary could not be validated. Saved draft preserved.'}});}
   return route.fulfill({json:{...draft,version:2,soap:{...draft.soap,structured_soap:{warnings:[]},subjective:'Patient reports a two-day history of sore throat and fever.'}}});
  }
  if(p.startsWith('/api/'))return route.fulfill({status:404,json:{detail:'Offline fixture'}});
  const file=p==='/workspace'?path.join(root,'scribe/index.html'):p.startsWith('/assets/')?path.join(root,'scribe',p):null;
  if(!file)return route.fulfill({status:204});
  try{return route.fulfill({body:await fs.readFile(file),contentType:({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2'})[path.extname(file)]||'application/octet-stream'});}catch{return route.fulfill({status:404});}
 });
 await page.goto('http://medflow.test/workspace');await page.waitForFunction(()=>document.body.classList.contains('auth-ready'));
 await page.evaluate(payload=>{
  selectedPatient={_id:payload.patient_id,name:payload.patient_name};activeWorkflow={workflow_id:'WF-SYNTHETIC',state:'NOTE_REVIEW_REQUIRED'};
  activeEncounter={encounter_id:payload.encounter_id};applyClinicalNote(payload);showVisitWorkspace();
 },draft);
 assert.equal(await page.locator('.soap-recovery').count(),1);assert.equal(await page.locator('[data-rebuild-soap]').isEnabled(),true);
 await page.evaluate(()=>{soapDraftTouched=true;renderSoapNote(generatedSoap,fullTranscript);});
 assert.equal(await page.locator('[data-rebuild-soap]').isEnabled(),false);assert.equal(writes.length,0);
 await page.evaluate(()=>{soapDraftTouched=false;renderSoapNote(generatedSoap,fullTranscript);});
 await page.locator('[data-rebuild-soap]').click();await requestStart;
 assert.equal(await page.locator('[data-rebuild-soap]').isEnabled(),false);assert.ok((await page.locator('[data-rebuild-soap]').innerText()).includes('Rebuilding'));
 assert.ok((await page.locator('#soapContent').innerText()).includes('Take Motilium, one tablespoon.'));
 release();await page.waitForFunction(()=>!clinicalDocumentBusy);
 assert.equal(await page.evaluate(()=>currentNoteVersion),1);assert.equal(await page.locator('[data-rebuild-soap]').isEnabled(),true);
 await page.locator('.soap-recovery').scrollIntoViewIfNeeded();await page.screenshot({path:'/tmp/medflow-soap-recovery.png'});
 fail=false;await page.locator('[data-rebuild-soap]').click();await page.waitForFunction(()=>currentNoteVersion===2);
 assert.equal(await page.evaluate(()=>generatedNoteState),'AI_DRAFT');assert.equal(await page.locator('.soap-recovery').count(),0);
 assert.deepEqual(writes,[{expected_version:1},{expected_version:1}]);
 await page.evaluate(payload=>{applyClinicalNote({...payload,state:'APPROVED_BY_DOCTOR'});},draft);
 assert.equal(await page.locator('[data-rebuild-soap]').count(),0);
 await page.evaluate(payload=>applyClinicalNote(payload),draft);await page.evaluate(()=>MedFlowDisplay.set({theme:'light'}));await page.setViewportSize({width:390,height:844});
 assert.equal(await page.locator('.soap-recovery').count(),1);
 assert.equal(await page.evaluate(()=>{const c=document.querySelector('.soap-recovery');return c.scrollWidth<=c.clientWidth+1;}),true);
 assert.deepEqual(errors,[]);console.log('PASS: saved fallback labelled, unsaved/approved gates, busy state and preserved content, failed retry preserves draft, successful version remains unapproved, light mobile layout; 0 page errors. Offline synthetic fixtures.');
 await browser.close();
})().catch(async e=>{console.error(e);if(browser)await browser.close();process.exit(1);});
