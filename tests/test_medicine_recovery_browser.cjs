/* Actual workspace interaction; all routes are fictional offline fixtures. */
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path');
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES?process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright':'playwright');
const root=path.resolve(__dirname,'..');let browser;
(async()=>{
 const broken={utterance_id:'U1',speaker:'Doctor',original_text:'پیناڈول لیں۔',clinical_english:'Take MF_MED_...',text:'Take MF_MED_...',medicine_checks:{mentions:[],issues:['unresolved_medicine_token']}};
 const good={...broken,clinical_english:'Take Panadol.',text:'Take Panadol.',medicine_checks:{mentions:[{source:'پیناڈول',name:'Panadol',status:'catalog_name'}],issues:[]}};
 const context=turn=>({workflow:{workflow_id:'WF-SYNTHETIC',state:'TRANSCRIPT_REVIEW',version:2},encounter:{encounter_id:'ENC-SYNTHETIC'},consents:[],note:null,
  conversation_review:{status:'TRANSCRIPT_REVIEW',revision:turn===broken?1:2,transcript_id:turn===broken?'TRN-OLD':'TRN-RECOVERED',utterances:[turn],raw_asr_text:'پیناڈول لیں۔',
   medicine_report:{requires_review:turn===broken,checks:[{utterance_id:'U1',...turn.medicine_checks}],context_unavailable_turns:[]}}});
 let current=context(broken),sent=[];const errors=[];
 browser=await chromium.launch({executablePath:process.env.QA_CHROMIUM_PATH||'/tmp/chromium',headless:true,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const request=route.request(),u=new URL(request.url()),p=u.pathname;if(u.hostname!=='medflow.test')return route.abort();
  if(p==='/api/auth/me')return route.fulfill({json:{full_name:'Dr. Synthetic Test',email:'doctor@example.test',role:'DOCTOR'}});
  if(['/api/patients','/api/notes','/api/templates'].includes(p))return route.fulfill({json:[]});
  if(p==='/api/appointments/doctor-queue')return route.fulfill({json:{appointments:[],timezone:'Asia/Karachi'}});
  if(p==='/api/workflows/capabilities')return route.fulfill({json:{}});
  if(p.endsWith('/repair-medicines')){sent.push(request.postDataJSON());current=context(good);return route.fulfill({json:current});}
  if(p.startsWith('/api/workflows/context/'))return route.fulfill({json:current});
  if(p.startsWith('/api/'))return route.fulfill({status:404,json:{detail:'Offline fixture'}});
  const file=p==='/workspace'?path.join(root,'scribe/index.html'):p.startsWith('/assets/')?path.join(root,'scribe',p):null;
  if(!file)return route.fulfill({status:204});
  try{return route.fulfill({body:await fs.readFile(file),contentType:({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2'})[path.extname(file)]||'application/octet-stream'});}catch{return route.fulfill({status:404});}
 });
 await page.goto('http://medflow.test/workspace');await page.waitForFunction(()=>!document.body.classList.contains('auth-locked'));
 await page.evaluate(payload=>{selectedPatient={_id:'PT-SYNTHETIC',name:'Synthetic Patient'};applyVisitContext(payload);showVisitWorkspace();renderClinicFlow();},current);
 assert.ok((await page.locator('#transcriptBody').innerText()).includes('unresolved medicine identifier'));
 assert.equal(await page.locator('[data-repair-medicines]').isEnabled(),true);
 await page.evaluate(()=>{conversationDirty=true;renderClinicFlow();});assert.equal(await page.locator('[data-repair-medicines]').isEnabled(),false);
 await page.evaluate(()=>{conversationDirty=false;renderClinicFlow();});await page.locator('[data-repair-medicines]').click();
 await page.waitForFunction(()=>conversationReview?.revision===2&&!visitActionBusy);
 assert.deepEqual(sent,[{expected_revision:1,transcript_id:'TRN-OLD'}]);assert.equal(await page.locator('[data-repair-medicines]').count(),0);
 assert.ok((await page.locator('#transcriptBody').innerText()).includes('Take Panadol.'));assert.equal(await page.evaluate(()=>Boolean(soapLastSavedNoteId)),false);
 assert.deepEqual(errors,[]);await page.screenshot({path:'/tmp/medflow-medicine-recovered.png'});
 console.log('PASS: unresolved-marker warning with zero recognized medicines, repair action, unsaved-edit protection, exact revision request, recovered name, no automatic SOAP, page errors 0. Offline fixtures.');await browser.close();
})().catch(async error=>{console.error(error);if(browser)await browser.close();process.exit(1);});
