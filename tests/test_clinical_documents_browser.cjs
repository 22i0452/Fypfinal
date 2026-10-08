/* Real Chromium; offline routes with fictional versions from the service fixture. */
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES?process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright':'playwright');
const root=path.resolve(__dirname,'..'),qa='/tmp/medflow-clinical-documents-qa';let browser;
(async()=>{
 const original=JSON.parse(await fs.readFile(qa+'/draft.json','utf8')),prepared=JSON.parse(await fs.readFile(qa+'/prepared.json','utf8')),
  saved=JSON.parse(await fs.readFile(qa+'/saved.json','utf8')),approved=JSON.parse(await fs.readFile(qa+'/approved.json','utf8'));let active=original;
 browser=await chromium.launch({executablePath:process.env.QA_CHROMIUM_PATH||undefined,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process'],headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url()),p=url.pathname;if(url.hostname!=='medflow.test')return route.abort();
  if(p==='/api/auth/me')return route.fulfill({json:{full_name:'Dr. Synthetic Test',email:'doctor@example.test',role:'DOCTOR'}});
  if(p==='/api/patients')return route.fulfill({json:[]});if(p==='/api/notes'&&request.method()==='GET')return route.fulfill({json:[]});
  if(p==='/api/appointments/doctor-queue')return route.fulfill({json:{appointments:[],timezone:'Asia/Karachi'}});
  if(p==='/api/templates')return route.fulfill({json:[]});
  if(p==='/api/workflows/capabilities')return route.fulfill({json:{coding_enabled:false,previsit_enabled:false,development_quick_start_enabled:false}});
  if(p.endsWith('/prescription/prepare'))return route.fulfill({json:{version:1,prescription:prepared}});
  if(p.endsWith('/prescription')&&request.method()==='PATCH'){writes.push(request.postDataJSON());active=saved;return route.fulfill({json:saved});}
  if(p.endsWith('/relevance')){writes.push(request.postDataJSON());return route.fulfill({json:{...active,version:active.version+1}});}
  if(p.startsWith('/api/'))return route.fulfill({status:404,json:{detail:'Offline browser fixture'}});
  if(p==='/branding/logo'||p==='/branding/icon')return route.fulfill({status:204});
  const filename=p==='/workspace'?path.join(root,'scribe/index.html'):p.startsWith('/assets/')?path.join(root,'scribe',p):null;
  if(!filename)return route.fulfill({status:204});
  try{const body=await fs.readFile(filename);return route.fulfill({body,contentType:({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.ttf':'font/ttf'})[path.extname(filename)]||'application/octet-stream'});}catch{return route.fulfill({status:404});}
 });
 await page.goto('http://medflow.test/workspace');await page.waitForFunction(()=>document.body.classList.contains('auth-locked')===false);
 await page.evaluate(payload=>{
  selectedPatient={_id:payload.patient_id,name:payload.patient_name,age:'40 years'};
  activeWorkflow={workflow_id:'WF-QA',patient_id:payload.patient_id,note_id:payload.note_id,state:'NOTE_REVIEW_REQUIRED'};
  activeEncounter={encounter_id:payload.encounter_id};applyClinicalNote(payload);showVisitWorkspace();
 },original);
 await page.locator('[data-open-prescription]:visible').click();await page.waitForFunction(()=>clinicalDocument?.value);
 assert.ok((await page.locator('#documentPanel').innerText()).includes('500 mg'));assert.ok((await page.locator('#documentPanel').innerText()).includes('STOP Motilium'));
 assert.equal(await page.locator('[data-prescription-export]').isEnabled(),false);
 await page.screenshot({path:qa+'/prescription-dark-desktop.png'});
 await page.locator('[data-document-tab="medicines"]').click();await page.locator('[data-rx-field="dose"]').fill('500 mg');
 await page.locator('[data-document-tab="instructions"]').click();await page.locator('[data-rx-document="advice"]').fill('Doctor entered hydration advice.');
 await page.locator('#rxConfirmed').check();await page.locator('[data-prescription-save]').click();
 await page.waitForFunction(()=>currentNoteVersion===2);assert.equal(writes.length,1);assert.equal(writes[0].medicines[1].action,'stop');
 assert.equal(writes[0].advice,'Doctor entered hydration advice.');assert.equal(await page.locator('[data-prescription-export]').isEnabled(),false);
 await page.locator('[data-document-discard]').click();await page.evaluate(payload=>applyClinicalNote(payload),approved);
 await page.locator('[data-open-prescription]:visible').click();await page.waitForFunction(()=>clinicalDocument?.value);assert.equal(await page.locator('[data-prescription-export]').isEnabled(),true);
 await page.locator('[data-document-discard]').click();await page.evaluate(payload=>applyClinicalNote(payload),original);
 await page.locator('[data-open-relevance]:visible').click();assert.equal(await page.locator('#documentTabs [role=tab]').count(),3);
 await page.locator('[data-document-tab="excluded"]').click();assert.ok((await page.locator('#documentPanel').innerText()).includes('Parking logistics'));
 await page.locator('[data-document-tab="review"]').click();assert.ok((await page.locator('#documentPanel').innerText()).includes('Yes.'));
 await page.locator('#relevanceStatus').selectOption('included');await page.locator('#relevanceReason').fill('Answer to the clinical question.');await page.locator('[data-relevance-apply]').click();
 await page.locator('[data-relevance-save]').click();await page.waitForFunction(()=>!document.getElementById('clinicalDocumentDialog').open);
 assert.equal(writes[1].corrections[0].utterance_id,'U4');assert.equal(writes[1].corrections[0].relevance_status,'included');
 await page.evaluate(payload=>applyClinicalNote(payload),original);await page.locator('[data-open-relevance]:visible').click();await page.screenshot({path:qa+'/relevance-dark-desktop.png'});
 await page.evaluate(()=>{MedFlowDisplay.set({theme:'light'});});await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:qa+'/relevance-light-mobile.png'});
 assert.equal(await page.evaluate(()=>document.getElementById('clinicalDocumentDialog').scrollWidth<=document.getElementById('clinicalDocumentDialog').clientWidth+1),true);
 await page.locator('[data-document-discard]').click();await page.locator('[data-open-prescription]:visible').click();await page.waitForFunction(()=>clinicalDocument?.value);
 await page.locator('[data-document-tab="medicines"]').click();await page.screenshot({path:qa+'/prescription-light-mobile.png'});
 assert.equal(await page.evaluate(()=>document.getElementById('clinicalDocumentDialog').scrollWidth<=document.getElementById('clinicalDocumentDialog').clientWidth+1),true);
 await page.locator('[data-document-discard]').click();await page.setViewportSize({width:1280,height:1000});await page.evaluate(()=>{MedFlowDisplay.set({zoom:160,theme:'light'});});
 await page.locator('[data-open-prescription]:visible').click();await page.waitForFunction(()=>clinicalDocument?.value);await page.screenshot({path:qa+'/prescription-light-zoom.png'});
 assert.equal(await page.evaluate(()=>document.getElementById('clinicalDocumentDialog').scrollWidth<=document.getElementById('clinicalDocumentDialog').clientWidth+1),true);
 await page.locator('[data-document-discard]').click();await page.evaluate(payload=>{payload.soap.relevance_report.items[0].original='<script>window.qaInjected=true</script>';applyClinicalNote(payload);},original);
 await page.locator('[data-open-relevance]:visible').click();assert.equal(await page.evaluate(()=>!!window.qaInjected),false);
 assert.deepEqual(errors,[]);console.log('PASS: prescription source fields, stop wording, doctor edits, version save, approval-gated export, relevance tabs and override, dark/light/mobile/160% zoom, escaped evidence; page errors 0. Offline browser fixtures.');
 await browser.close();
})().catch(async error=>{console.error(error);if(browser)await browser.close();process.exit(1);});
