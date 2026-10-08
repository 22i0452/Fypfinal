/* Full real workflow with synthetic providers; not clinical or ASR accuracy evaluation. */
const fs=require('node:fs/promises');
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES ? process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright' : 'playwright');
let server,browser;
const deadline=setTimeout(()=>{console.error('Browser validation timed out');process.exit(1);},120000);
(async()=>{
 const assert=require('node:assert/strict');
 const path=require('node:path');
 server=require('node:child_process').spawn('python',['tests/evidence_fixture.py'],{cwd:path.resolve(__dirname,'..'),stdio:['ignore','ignore','pipe']});server.stderr.on('data',d=>process.stderr.write(d));process.on('exit',()=>server.kill());
 for(let i=0;i<100;i++){try{if((await fetch('http://127.0.0.1:8765/api/desk/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 const shots=process.env.QA_SHOTS_DIR || '/tmp/medflow-evidence-qa';await fs.mkdir(shots,{recursive:true});
 browser=await chromium.launch({executablePath:process.env.QA_CHROMIUM_PATH || undefined,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process','--disable-software-rasterizer'],headless:true});const ctx=await browser.newContext({viewport:{width:1440,height:900}});
 const p=await ctx.newPage();const errors=[];p.on('pageerror',e=>errors.push(e.message));p.on('dialog',d=>d.accept());
 await p.goto('http://127.0.0.1:8765/consultation/login');await p.waitForTimeout(300);await p.screenshot({path:shots+'/login.png',fullPage:true});
 await p.locator('#loginEmail').fill('audit@example.test');await p.locator('#loginPassword').fill('AuditPass123!');await p.locator('#loginSubmit').click();
 await p.waitForURL('**/workspace');await p.waitForFunction(()=>allPatients.length===2 && ws?.readyState===WebSocket.OPEN);
 await p.waitForTimeout(300);await p.screenshot({path:shots+'/today.png',fullPage:true});
 await p.locator('#dashboardPatientList .patient-row').first().click();await p.waitForFunction(()=>!visitLoading);
 console.log('READ ONLY OPEN',await p.evaluate(()=>({workflow:activeWorkflow,encounter:activeEncounter,stage:visitStage})));
 await p.waitForTimeout(300);await p.screenshot({path:shots+'/prepare.png',fullPage:true});
 await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>activeWorkflow?.state==='PATIENT_UNVERIFIED');
 await p.locator('#visitNextBtn').click();await p.getByRole('button',{name:'Use phone OTP instead',exact:true}).click();await p.locator('#verificationDialog').waitFor({state:'visible'});await p.locator('#patientOtpInput').fill('123456');await p.locator('#verificationDialog').getByRole('button',{name:'Verify patient',exact:true}).click();await p.waitForFunction(()=>activeWorkflow?.state==='BOOKING_REQUIRED');
 await p.locator('#visitNextBtn').click();await p.locator('#bookingDialog').waitFor({state:'visible'});
 console.log('BOOKING FIELDS',await p.locator('#bookingDoctor').innerText());
 await p.getByRole('button',{name:'Find slots',exact:true}).click();await p.waitForFunction(()=>document.getElementById('bookingSlot').options.length>1);
 await p.locator('#bookingSlot').selectOption({index:1});await p.getByRole('button',{name:'Confirm appointment',exact:true}).click();await p.waitForFunction(()=>activeWorkflow?.state==='BOOKING_CONFIRMED');
 await p.locator('#visitNextBtn').click();await p.locator('#consentDialog').waitFor({state:'visible'});for(const id of ['consentRecording','consentTranscription','consentDocumentation'])await p.locator('#'+id).check();await p.getByRole('button',{name:'Save choices',exact:true}).click();await p.waitForFunction(()=>hasRequiredConsent());
 await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>visitStage==='capture');await p.waitForTimeout(300);await p.screenshot({path:shots+'/capture.png',fullPage:true});

 await p.evaluate(()=>{navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Synthetic permission denial','NotAllowedError');};});
 await p.locator('#visitNextBtn').click();
 assert.equal(await p.evaluate(()=>!pendingRecordingStart && !isRecording && !document.getElementById('visitNextBtn').disabled),true);
 console.log('MIC PERMISSION RECOVERY',true);
 // Real websocket pipeline with synthetic audio and the local mock AI provider.
 await p.evaluate(()=>{captureContext={patientId:selectedPatient._id,workflowId:activeWorkflow.workflow_id,encounterId:activeEncounter.encounter_id,captureId:crypto.randomUUID()};pendingRecordingStart=true;ws.send(JSON.stringify({type:'start',auto_soap:true,patient_id:captureContext.patientId,workflow_id:captureContext.workflowId,encounter_id:captureContext.encounterId,capture_id:captureContext.captureId,sample_rate:16000,template_id:'TPL-GP-01'}));});
 await p.waitForFunction(()=>isRecording);
 await p.evaluate(()=>{const a=new Int16Array(32000);for(let i=0;i<a.length;i++)a[i]=Math.round(5000*Math.sin(i/20));ws.send(a.buffer);stopRecording();});await p.waitForFunction(()=>isProcessing);await p.reload();await p.waitForFunction(()=>!visitLoading && isProcessing);console.log('RELOAD DURING PROCESSING',true);await p.waitForFunction(()=>!!soapLastSavedNoteId,{timeout:20000});
 await p.waitForTimeout(300);await p.screenshot({path:shots+'/review.png',fullPage:true});


 await p.waitForFunction(()=>currentEvidenceReport()?.counts.linked===1);
 const initialReport=await p.evaluate(()=>currentEvidenceReport());
 assert.ok(initialReport.counts.missing>0);assert.equal(initialReport.confidence,null);
 assert.equal(await p.locator('.evidence-note-overview').count(),1);
 await p.locator('.evidence-soap-text .evidence-span').first().click();
 await p.locator('#evidenceDialog').waitFor({state:'visible'});
 assert.ok((await p.locator('#evidenceDialog').innerText()).includes('Semantic support has not been measured'));
 await p.locator('#evidenceDialog .evidence-technical summary').click();
 assert.ok((await p.locator('#evidenceDialog').innerText()).includes(initialReport.note_id));
 for(const width of [1440,1280,390]){
   await p.setViewportSize({width,height:900});
   assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);
   assert.equal(await p.locator('#evidenceDialog').evaluate(x=>x.scrollWidth<=x.clientWidth),true);
   await p.screenshot({path:shots+'/inspector-'+width+'.png',fullPage:true});
 }
 await p.setViewportSize({width:1440,height:900});
 await p.locator('#evidenceDialog [data-evidence-source]').first().click();
 assert.equal(await p.locator('#evidenceDialog').evaluate(x=>x.open),false);
 assert.equal(await p.evaluate(()=>highlightedEvidenceIds[0]),'U1');
 await p.evaluate(()=>filterNoteEvidence('missing'));
 assert.equal(await p.locator('.evidence-note-overview .evidence-claim-row').count(),initialReport.counts.missing);
 await p.evaluate(()=>filterNoteEvidence('all'));
 await p.locator('#transcriptBody [data-evidence-key]').first().click();
 assert.ok((await p.locator('#evidenceDialog').innerText()).includes('Proposed role'));
 await p.locator('#evidenceDialog [data-evidence-close]').click();
 await p.evaluate(()=>{toggleGuidedProcess();processPick('validation');});
 await p.locator('.process-artifact [data-evidence-key]').first().click();
 assert.ok((await p.locator('#evidenceDialog').innerText()).includes('Initial capture artifact'));
 await p.locator('#evidenceDialog [data-evidence-close]').click();
 console.log('SOURCE INSPECTOR, FILTERS, ORIGINAL PAIRS AND THREE MODAL VIEWPORTS passed');
 await p.locator('.soap-section').first().getByRole('button',{name:'Edit section',exact:true}).click();
 await p.locator('#soapEditor_subjective').fill('Temporary synthetic edit');
 await p.locator('.soap-section').first().getByRole('button',{name:'Cancel',exact:true}).click();
 assert.equal(await p.evaluate(()=>soapDraftTouched),false);
 await p.locator('.soap-section').first().getByRole('button',{name:'Edit section',exact:true}).click();
 await p.locator('#soapEditor_subjective').fill('Synthetic clinician amendment for browser verification.');
 const before=await p.evaluate(()=>selectedPatient._id);
 await p.evaluate(()=>openPatientVisit(allPatients[1]));assert.equal(await p.evaluate(()=>selectedPatient._id),before);
 await p.locator('.soap-section').first().getByRole('button',{name:'Done',exact:true}).click();
 assert.equal(await p.locator('.soap-section').first().locator('.evidence-soap-text .evidence-span').count(),0);
 assert.ok((await p.locator('#soapContent').innerText()).includes('Local edits have no fresh source checks'));
 await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>!soapSaveBusy && !soapDraftTouched && currentNoteVersion===2);
 assert.equal(await p.evaluate(()=>currentEvidenceReport().counts.linked),0);
 assert.equal(await p.evaluate(()=>currentEvidenceReport().version),2);
 console.log('EDIT SAVED & PATIENT GUARD',true);
 await p.waitForTimeout(300);await p.screenshot({path:shots+'/review.png',fullPage:true});
 const ids=await p.evaluate(()=>({note:soapLastSavedNoteId,workflow:activeWorkflow.workflow_id,encounter:activeEncounter.encounter_id,patient:selectedPatient._id}));
 console.log('DRAFT',await p.evaluate(()=>({stage:visitStage,state:generatedNoteState,processing:isProcessing,next:document.getElementById('visitNextBtn').innerText})));
 await p.reload();await p.waitForFunction(()=>!!soapLastSavedNoteId && !visitLoading);console.log('RESTORED',await p.evaluate(()=>({note:soapLastSavedNoteId,workflow:activeWorkflow.workflow_id,stage:visitStage})));
 console.log('BEFORE REVIEW',await p.evaluate(()=>({processing:isProcessing,busy:visitActionBusy,note:generatedNoteState,disabled:document.getElementById('visitNextBtn').disabled})));await p.locator('#visitNextBtn').click();console.log('REVIEW CLICKED');await p.waitForFunction(()=>generatedNoteState==='REVIEW_REQUIRED' && !visitActionBusy);console.log('REVIEW READY');await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>generatedNoteState==='APPROVED_BY_DOCTOR' && visitStage==='finish' && !visitActionBusy);console.log('APPROVED',await p.evaluate(()=>({stage:visitStage,workflow:activeWorkflow.state})));
 assert.equal(await p.evaluate(()=>currentEvidenceReport().state),'APPROVED_BY_DOCTOR');assert.equal(await p.evaluate(()=>currentEvidenceReport().counts.missing),initialReport.counts.missing);assert.ok(await p.evaluate(()=>!!currentEvidenceReport().approval.doctor_id));
 await p.locator('#visitSummaryLanguage').selectOption('ENGLISH');await p.getByRole('button',{name:'Generate summary',exact:true}).click();await p.waitForFunction(()=>!summaryBusy && !!afterVisitSummaries[soapLastSavedNoteId]);
 await p.waitForTimeout(300);await p.screenshot({path:shots+'/finish.png',fullPage:true});await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>activeWorkflow?.state==='ENCOUNTER_COMPLETED');
 assert.equal(await p.evaluate(()=>activeWorkflow.state==='ENCOUNTER_COMPLETED' && activeEncounter.status==='COMPLETED' && activeAppointment.status==='COMPLETED'),true);
 console.log('COMPLETED',await p.evaluate(()=>({workflow:activeWorkflow.state,encounter:activeEncounter.status,appointment:activeAppointment.status})));
 await p.getByRole('button',{name:'Records',exact:true}).click();await p.locator('#notesList .note-row').first().click();await p.waitForTimeout(300);await p.screenshot({path:shots+'/records.png',fullPage:true});
 await p.getByRole('button',{name:'Open visit',exact:true}).click();await p.waitForFunction(()=>visitStage==='finish' && !visitLoading);assert.equal(await p.evaluate(old=>activeWorkflow.workflow_id===old,ids.workflow),true);console.log('ARCHIVE SAME',await p.evaluate(old=>({same:activeWorkflow.workflow_id===old,stage:visitStage}),ids.workflow));
 const patient2=await p.evaluate(()=>allPatients[1]);await p.evaluate(patient=>openPatientVisit(patient),patient2);await p.waitForFunction(()=>!visitLoading);
 await p.evaluate(()=>{captureContext={patientId:selectedPatient._id,workflowId:'OTHER-WORKFLOW',encounterId:'OTHER-ENCOUNTER',captureId:'old'};});
 await p.evaluate(old=>handleServerMessage({data:JSON.stringify({type:'soap_note',patient_id:old.patient,workflow_id:old.workflow,encounter_id:old.encounter,capture_id:'old',soap:{subjective:'WRONG PATIENT NOTE'}})}),ids);console.log('STALE IGNORED',await p.evaluate(()=>generatedSoap===null));
 for(const width of [1440,1280,390]){await p.setViewportSize({width,height:900});console.log('WIDTH',width,await p.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth})));}
 await p.setViewportSize({width:1440,height:900});await p.goto('http://127.0.0.1:8765/Receptionist');await p.waitForFunction(()=>state.config!==null);await p.waitForTimeout(300);await p.screenshot({path:shots+'/reception.png',fullPage:true});

 await p.evaluate(()=>showView('intake'));await p.locator('#fieldName').fill('Synthetic Handoff Patient');await p.locator('#fieldAge').fill('32');await p.locator('#fieldPhone').fill('03000000111');await p.locator('#fieldHistory').fill('None');await p.locator('#fieldComplaint').fill('Synthetic knee pain');
 await p.evaluate(()=>showView('intake'));await p.locator('#intakeNext').click();assert.equal(await p.evaluate(()=>intakeStage),1);
 await p.locator('#fieldDepartment').selectOption({index:1});await p.locator('#fieldDoctor').selectOption({index:1});await p.locator('#fieldVisitType').selectOption({index:1});await p.waitForFunction(()=>document.getElementById('fieldSlot').options.length>1);await p.locator('#fieldSlot').selectOption({index:1});
 await p.locator('#submitBtn').click();await p.waitForFunction(()=>intakeStage===2 && !!state.appointmentId,{timeout:20000});
 const handoff=await p.evaluate(()=>({patient:state.patientId,workflow:state.workflowId,appointment:state.appointmentId}));console.log('REAL HANDOFF',handoff);
 assert.ok(await p.evaluate(()=>manualEvidenceSaved?.patient_id===state.patientId));
 await p.getByRole('button',{name:'Inspect stored handoff',exact:true}).click();
 await p.locator('#evidenceDialog .evidence-technical summary').click();
 assert.ok((await p.locator('#evidenceDialog').innerText()).includes(handoff.appointment));
 assert.ok((await p.locator('#evidenceDialog').innerText()).includes('REQUESTED'));
 await p.locator('#evidenceDialog [data-evidence-close]').click();
 await p.waitForTimeout(300);await p.screenshot({path:shots+'/handoff.png',fullPage:true});
 await p.getByRole('link',{name:'Open doctor handoff',exact:true}).click();await p.waitForFunction(()=>!visitLoading && selectedPatient?.name==='Synthetic Handoff Patient');
 assert.equal(await p.evaluate(()=>activeWorkflow.state), 'PATIENT_UNVERIFIED');assert.equal(await p.evaluate(()=>activeAppointment.status),'REQUESTED');assert.equal(await p.evaluate(()=>activeEncounter),null);
 await p.locator('#visitNextBtn').click();await p.getByRole('button',{name:'Use phone OTP instead',exact:true}).click();await p.locator('#verificationDialog').waitFor({state:'visible'});await p.locator('#patientOtpInput').fill('123456');await p.locator('#verificationDialog').getByRole('button',{name:'Verify patient',exact:true}).click();await p.waitForFunction(()=>activeWorkflow?.state==='BOOKING_CONFIRMED' && !visitActionBusy);
 assert.equal(await p.evaluate(()=>activeWorkflow.workflow_id),handoff.workflow);assert.equal(await p.evaluate(()=>activeAppointment.appointment_id),handoff.appointment);console.log('HANDOFF CONFIRMS SAME BOOKING',true);
 await p.locator('#visitNextBtn').click();await p.locator('#consentDialog').waitFor({state:'visible'});for(const id of ['consentRecording','consentTranscription','consentDocumentation'])await p.locator('#'+id).check();await p.getByRole('button',{name:'Save choices',exact:true}).click();await p.waitForFunction(()=>hasRequiredConsent() && !visitActionBusy);
 await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>visitStage==='capture');
 await p.evaluate(()=>{captureContext={patientId:selectedPatient._id,workflowId:activeWorkflow.workflow_id,encounterId:activeEncounter.encounter_id,captureId:crypto.randomUUID()};pendingRecordingStart=true;ws.send(JSON.stringify({type:'start',auto_soap:true,patient_id:captureContext.patientId,workflow_id:captureContext.workflowId,encounter_id:captureContext.encounterId,capture_id:captureContext.captureId,sample_rate:16000,template_id:'TPL-GP-01'}));});await p.waitForFunction(()=>isRecording);
 await p.evaluate(()=>{window.trackWasStopped=false;mediaStream={getTracks:()=>[{stop:()=>window.trackWasStopped=true}]};ws.close();});await p.waitForFunction(()=>!isRecording && !pendingRecordingStart && ws.readyState===WebSocket.OPEN,{timeout:20000});assert.equal(await p.evaluate(()=>window.trackWasStopped),true);console.log('DISCONNECT STOPS CAPTURE & RECONNECTS',true);
 for(const width of [1440,1280,390]){await p.setViewportSize({width,height:900});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);}
 await p.setViewportSize({width:1440,height:900});

 await p.evaluate(()=>fetch('/audit/fail-next-documentation',{method:'POST'}));
 await p.evaluate(()=>{captureContext={patientId:selectedPatient._id,workflowId:activeWorkflow.workflow_id,encounterId:activeEncounter.encounter_id,captureId:crypto.randomUUID()};pendingRecordingStart=true;ws.send(JSON.stringify({type:'start',auto_soap:true,patient_id:captureContext.patientId,workflow_id:captureContext.workflowId,encounter_id:captureContext.encounterId,capture_id:captureContext.captureId,sample_rate:16000}));});await p.waitForFunction(()=>isRecording);
 const oldEncounter=await p.evaluate(()=>activeEncounter.encounter_id);
 await p.evaluate(()=>{ws.send(new Int16Array(16000).buffer);stopRecording();});await p.waitForFunction(()=>activeWorkflow?.state==='FAILED' && !isProcessing);
 await p.locator('#visitNextBtn').click();await p.waitForFunction(()=>activeWorkflow.state==='CONSULTATION_ACTIVE' && visitStage==='capture' && !visitActionBusy);assert.equal(await p.evaluate(()=>activeEncounter.encounter_id),oldEncounter);console.log('FAILURE RECOVERY SAME ENCOUNTER',true);
 console.log('HANDOFF READY',await p.evaluate(()=>({stage:visitStage,patient:selectedPatient.name})));assert.deepEqual(errors,[]);
 console.log('ERRORS',errors);await browser.close();server.kill();clearTimeout(deadline);
})().catch(async e=>{console.error(e);clearTimeout(deadline);await browser?.close();server?.kill();process.exitCode=1});
