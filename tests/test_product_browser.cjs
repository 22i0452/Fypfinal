/* Full real workflow with synthetic providers; not clinical or ASR accuracy evaluation. */
const fs=require('node:fs/promises');
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES ? process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright' : 'playwright');
let server,browser;
const deadline=setTimeout(()=>{console.error('Browser validation timed out');process.exit(1);},120000);
(async()=>{
 const assert=require('node:assert/strict');
 const path=require('node:path');
 server=require('node:child_process').spawn('python',['tests/evidence_fixture.py'],{cwd:path.resolve(__dirname,'..'),env:{...process.env,QA_ENABLE_CODING:'1'},stdio:['ignore','ignore','pipe']});server.stderr.on('data',d=>process.stderr.write(d));process.on('exit',()=>server.kill());
 for(let i=0;i<100;i++){try{if((await fetch('http://127.0.0.1:8765/api/desk/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 const shots=process.env.QA_SHOTS_DIR || '/tmp/medflow-evidence-qa';await fs.mkdir(shots,{recursive:true});
 browser=await chromium.launch({executablePath:process.env.QA_CHROMIUM_PATH || undefined,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process','--disable-software-rasterizer'],headless:true});const ctx=await browser.newContext({viewport:{width:1440,height:900}});
 const p=await ctx.newPage();const errors=[];p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept());
 await p.goto('http://127.0.0.1:8765/');
 for(const width of [1440,1280,390]){await p.setViewportSize({width,height:900});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);await p.screenshot({path:shots+'/home-'+width+'.png',fullPage:true});}
 assert.equal(await p.locator('.workspace-portals a').count(),2);assert.ok((await p.locator('.patient-portal').innerText()).includes('Coming soon'));
 assert.equal(await p.locator('.patient-portal a,.patient-portal button').count(),0);
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
 assert.equal(await p.locator('.coding-entry-button').isEnabled(),true);
 assert.equal(await p.locator('#visitContinuity').isVisible(),true);
 await p.locator('.soap-section').first().getByRole('button',{name:'Edit section',exact:true}).click();assert.equal(await p.locator('.coding-entry-button').isDisabled(),true);assert.ok((await p.locator('#soapCodingReason').innerText()).includes('Save or cancel'));await p.locator('.soap-section').first().getByRole('button',{name:'Cancel',exact:true}).click();
 await p.evaluate(()=>fetch('/audit/coding-controls',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:false})}));await p.evaluate(()=>refreshActiveContext());assert.equal(await p.locator('.coding-entry-button').isDisabled(),true);assert.ok((await p.locator('#soapCodingReason').innerText()).includes('not been enabled'));
 await p.evaluate(()=>showCodingWorkspace({noteId:soapLastSavedNoteId}));await p.waitForFunction(()=>!codingBusy);assert.equal(await p.locator('#codingGenerateBtn').isDisabled(),true);assert.ok((await p.locator('#codingStateMessage').innerText()).includes('not been enabled'));
 await p.evaluate(()=>fetch('/audit/coding-controls',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:true})}));await p.getByRole('button',{name:'Back to visit',exact:true}).click();await p.waitForFunction(()=>!visitLoading && visitStage==='review');
 await p.locator('.coding-entry-button').click();await p.waitForFunction(()=>!codingBusy && document.getElementById('codingView').classList.contains('active'));
 await p.evaluate(()=>fetch('/audit/coding-controls',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fail_next:true})}));await p.locator('#codingGenerateBtn').click();await p.waitForFunction(()=>!codingBusy && !!codingError);assert.ok((await p.locator('#codingStateMessage').innerText()).includes('preserved'));
 await p.locator('#codingGenerateBtn').click();await p.waitForFunction(()=>!codingBusy && codingSuggestions.length===2);
 assert.equal(await p.locator('.coding-card').count(),2);assert.equal((await p.locator('#codingResults').innerText()).includes('% confidence'),false);
 await p.locator('[data-code-evidence]').first().click();await p.locator('#codingEvidenceDialog').waitFor({state:'visible'});
 assert.ok((await p.locator('#codingEvidenceDialog').innerText()).includes('clinical correctness remain unassessed'));
 assert.ok((await p.locator('.coding-conversation-turn').innerText()).includes('synthetic response'));
 for(const width of [1440,1280,390]){await p.setViewportSize({width,height:900});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);assert.equal(await p.locator('#codingEvidenceDialog').evaluate(x=>x.scrollWidth<=x.clientWidth),true);await p.screenshot({path:shots+'/coding-source-'+width+'.png',fullPage:true});}
 await p.locator('[data-code-source]').first().click();await p.locator('#evidenceDialog').waitFor({state:'visible'});assert.ok((await p.locator('#evidenceDialog').innerText()).toLowerCase().includes('synthetic response'));await p.locator('#evidenceDialog [data-evidence-close]').click();
 await p.locator('[data-code-evidence]').first().click();await p.locator('[data-code-open-visit]').click();await p.waitForFunction(()=>visitStage==='review' && !visitLoading && document.getElementById('visitView').classList.contains('active'));assert.equal(await p.evaluate(()=>activeWorkflow.workflow_id),ids.workflow);
 await p.setViewportSize({width:1440,height:900});
 // Amend SOAP through the normal editor: old suggestions become immutable history.
 await p.locator('.soap-section').first().getByRole('button',{name:'Edit section',exact:true}).click();await p.locator('#soapEditor_subjective').fill('Synthetic clinician amendment for a new version.');await p.locator('.soap-section').first().getByRole('button',{name:'Done',exact:true}).click();await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>!soapSaveBusy && !soapDraftTouched && currentNoteVersion===2);
 await p.locator('.coding-entry-button').click();await p.waitForFunction(()=>!codingBusy && codingSuggestions.length===2);assert.equal(await p.evaluate(()=>codingSuggestions.every(item=>item.stale)),true);
 await p.locator('.coding-history summary').click();await p.locator('[data-code-evidence]').first().click();await p.waitForFunction(()=>!codingBusy && codingEvidence?.stale && document.getElementById('codingEvidenceDialog').open);assert.ok((await p.locator('#codingEvidenceDialog').innerText()).includes('Earlier SOAP version'));assert.equal(await p.locator('[data-code-open-visit]').isDisabled(),true);await p.locator('[data-code-close]').click();
 await p.locator('#codingGenerateBtn').click();await p.waitForFunction(()=>!codingBusy && codingSuggestions.filter(item=>!item.stale).length===2);
 await p.locator('[data-code-review][data-approve="true"]').first().click();await p.waitForFunction(()=>!codingBusy && codingSuggestions.some(item=>item.status==='APPROVED' && !item.stale));
 for(const width of [1440,1280,390]){await p.setViewportSize({width,height:900});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);await p.screenshot({path:shots+'/coding-'+width+'.png',fullPage:true});}
 await p.getByRole('button',{name:'Back to visit',exact:true}).click();await p.waitForFunction(()=>!visitLoading && visitStage==='review');
 await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>generatedNoteState==='REVIEW_REQUIRED' && !visitActionBusy);await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>generatedNoteState==='APPROVED_BY_DOCTOR' && visitStage==='finish' && !visitActionBusy);
 await p.locator('#visitSummaryLanguage').selectOption('ENGLISH');await p.getByRole('button',{name:'Generate summary',exact:true}).click();await p.waitForFunction(()=>!summaryBusy && !!afterVisitSummaries[soapLastSavedNoteId]);await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>activeWorkflow?.state==='ENCOUNTER_COMPLETED');
 assert.equal(await p.evaluate(()=>activeEncounter.encounter_id),ids.encounter);
 await p.getByRole('button',{name:'Medflow home',exact:true}).click();await p.waitForURL('http://127.0.0.1:8765/');await p.waitForFunction(()=>document.querySelector('#homeAccount span').textContent==='Continue to workspace');
 await p.getByRole('link',{name:'Open AI Receptionist',exact:true}).click();await p.waitForURL('**/Receptionist');await p.waitForFunction(()=>typeof state!=='undefined' && state.config!==null);
 await p.getByRole('button',{name:'New session',exact:true}).click();await p.locator('#fieldName').fill('Synthetic unfinished intake');await p.getByRole('button',{name:'Medflow home',exact:true}).click();assert.ok(p.url().endsWith('/Receptionist'));assert.equal(await p.evaluate(()=>receptionIntakeDirty),true);
 await p.evaluate(()=>{state.busy=true;resetSession();state.busy=false;});assert.equal(await p.evaluate(()=>receptionIntakeDirty),true);
 await p.getByRole('button',{name:'New session',exact:true}).click();assert.equal(await p.evaluate(()=>receptionIntakeDirty),false);await p.getByRole('button',{name:'Medflow home',exact:true}).click();await p.waitForURL('http://127.0.0.1:8765/');
 assert.deepEqual(errors,[]);console.log('PRODUCT: home/auth portals, live coding disabled/dirty/error/retry states, ICD/CPT sources, original turns, immutable version history, review, connected visit completion and home navigation passed at three widths; page errors 0');
 await browser.close();server.kill();clearTimeout(deadline);
})().catch(async e=>{console.error(e);clearTimeout(deadline);await browser?.close();server?.kill();process.exitCode=1});
