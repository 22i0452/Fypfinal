const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs/promises');
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright');
let server,browser;const deadline=setTimeout(()=>{console.error('Booking experience browser deadline');process.exit(1);},180000);
(async()=>{
 server=require('node:child_process').spawn('python',['tests/evidence_fixture.py'],{cwd:path.resolve(__dirname,'..'),env:process.env,stdio:['ignore','ignore','pipe']});server.stderr.on('data',d=>process.stderr.write(d));process.on('exit',()=>server.kill());
 for(let i=0;i<150;i++){try{if((await fetch('http://127.0.0.1:8765/api/desk/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 browser=await chromium.launch({executablePath:process.env.QA_CHROMIUM_PATH,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process'],headless:true});
 const ctx=await browser.newContext({viewport:{width:1440,height:1000}}),p=await ctx.newPage(),errors=[];p.on('pageerror',e=>errors.push(e.message));
 const shots=process.env.QA_SHOTS_DIR||'/tmp/booking-experience-shots';await fs.mkdir(shots,{recursive:true});
 await p.goto('http://127.0.0.1:8765/consultation/login');await p.locator('#loginEmail').fill('audit@example.test');await p.locator('#loginPassword').fill('AuditPass123!');await p.locator('#loginForm').getByRole('button',{name:'Sign in',exact:true}).click();await p.waitForURL('**/workspace');await p.waitForFunction(()=>currentUser&&allPatients.length===2);
 await p.goto('http://127.0.0.1:8765/Receptionist');await p.waitForFunction(()=>state.config?.preferred_practitioner_id);await p.locator('#navIntake').click();
 for(const [id,value] of [['fieldName','Calendar Browser Patient'],['fieldAge','23'],['fieldPhone','03000000001'],['fieldHistory','None'],['fieldComplaint','Fictional calendar concern']])await p.locator('#'+id).fill(value);
 await p.locator('#intakeNext').click();await p.locator('#manualBookingChoices').waitFor({state:'visible'});
 await p.waitForFunction(()=>document.querySelectorAll('#manualBookingChoices .choice-card').length>=2);
 const slot=await p.evaluate(async()=>{const r=await fetch('/api/desk/availability?'+new URLSearchParams({practitioner_id:document.getElementById('fieldDoctor').value,visit_type_id:'VISIT-NEW',days:14,limit:30}));return (await r.json()).slots[0];});
 const day=await p.evaluate(s=>MedFlowCalendar.key(s.start_at,state.config.clinic.timezone),slot);
 await p.locator('#manualCalendar [data-date="'+day+'"]').click();await p.waitForFunction(()=>manualSlotRows.length>0);await p.locator('#manualSlots .slot-choice').first().click();
 const selected=await p.locator('#fieldSlot').inputValue();assert.ok(selected);
 for(const width of [1440,1280,390]){await p.setViewportSize({width,height:1000});for(const zoom of [80,100,130,160]){await p.evaluate(z=>MedFlowDisplay.set({zoom:z}),zoom);const d=await p.evaluate(()=>({scroll:document.body.scrollWidth,client:document.body.clientWidth}));if(d.scroll>d.client+1)console.log('OVERFLOW',await p.evaluate(()=>[...document.querySelectorAll('body *')].filter(n=>n.getBoundingClientRect().right>innerWidth+1).map(n=>({id:n.id,c:n.className,text:n.textContent.slice(0,60)})).slice(0,20)));assert.ok(d.scroll<=d.client+1,JSON.stringify({width,zoom,...d}));}await p.evaluate(()=>MedFlowDisplay.set({zoom:100}));assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);await p.waitForTimeout(350);await p.screenshot({path:shots+'/reception-calendar-'+width+'.png',fullPage:true});}
 await p.setViewportSize({width:1440,height:1000});await p.locator('#submitBtn').click();await p.waitForFunction(()=>!!state.appointmentId&&!state.busy);
 const receipt=await p.evaluate(()=>({patient:state.patientId,appointment:state.appointmentId}));
 await p.goto('http://127.0.0.1:8765/workspace');await p.waitForFunction(()=>doctorAppointments.length===1);await p.locator('#requestsTab').click();await p.locator('#pendingRequestList .appointment-row').click();await p.waitForFunction(()=>activeWorkflow?.state==='PATIENT_UNVERIFIED'&&!visitLoading);
 await p.locator('#patientDetailsChecked').check();await p.locator('#reviewPatientDetailsBtn').click();await p.waitForFunction(()=>activeWorkflow?.state==='BOOKING_CONFIRMED'&&!visitActionBusy);
 assert.equal(await p.evaluate(()=>activeDetailsVerification.method),'MANUAL_STAFF_REVIEW');assert.ok((await p.locator('#preparationSteps').innerText()).includes('reviewed by staff'));
 await p.getByRole('button',{name:'Today',exact:true}).first().click();await p.waitForFunction(()=>document.getElementById('dashboardView').classList.contains('active'));
 await p.locator('#doctorCalendar [data-date="'+day+'"]').click();await p.locator('#scheduleTab').click();assert.equal(await p.locator('#doctorAppointmentList .schedule-item').count(),1);
 await p.locator('#doctorAppointmentList').getByRole('button',{name:'Attendance',exact:true}).click();await p.waitForFunction(()=>attendanceTarget?.version>=2);
 const before=await p.evaluate(async id=>(await (await fetch('/api/appointments/'+id)).json()),receipt.appointment);
 await p.getByRole('button',{name:'Preview patient response',exact:true}).click();await p.locator('#attendancePanel .choice-card').first().click();assert.ok((await p.locator('#attendanceResponseDetail').innerText()).includes('No records changed'));
 const after=await p.evaluate(async id=>(await (await fetch('/api/appointments/'+id)).json()),receipt.appointment);assert.deepEqual(after,before);
 await p.getByRole('button',{name:'Exit preview',exact:true}).click();await p.getByRole('button',{name:'Request confirmation',exact:true}).click();await p.waitForFunction(()=>attendanceRecord?.status==='AWAITING_RESPONSE'&&!attendanceBusy);
 assert.ok((await p.locator('#attendancePanel').innerText()).includes('No patient notification has been delivered'));
 await p.locator('#attendancePanel .choice-card').first().click();await p.locator('#responseReceived').check();await p.getByRole('button',{name:'Save attendance confirmation',exact:true}).click();await p.waitForFunction(()=>attendanceRecord?.status==='CONFIRMED'&&!attendanceBusy);
 await p.reload();await p.waitForFunction(()=>doctorAppointments[0]?.attendance?.status==='CONFIRMED');await p.evaluate(()=>showDashboard());await p.waitForFunction(()=>document.getElementById('dashboardView').classList.contains('active'));await p.evaluate(()=>window.scrollTo(0,0));
 await p.locator('#doctorAppointmentList').getByRole('button',{name:'Attendance',exact:true}).click();await p.waitForFunction(()=>attendanceTarget?.version>=2);
 await p.getByRole('button',{name:'Request confirmation',exact:true}).click();await p.waitForFunction(()=>attendanceRecord?.status==='AWAITING_RESPONSE'&&!attendanceBusy);
 await p.locator('#attendancePanel .choice-card').filter({hasText:'Change time'}).click();await p.waitForFunction(()=>attendanceSlots.length>0);
 await p.locator('#attendanceSlots .slot-choice').first().click();const replacement=await p.evaluate(()=>attendanceSlot);assert.notEqual(replacement,before.start_at);
 await p.locator('#responseReceived').check();await p.getByRole('button',{name:'Confirm replacement time',exact:true}).click();await p.waitForFunction(()=>attendanceRecord?.status==='RESCHEDULED'&&!attendanceBusy);
 assert.equal(await p.evaluate(()=>attendanceTarget.start_at),replacement);await p.getByRole('button',{name:'Close attendance',exact:true}).click();
 for(const width of [1440,1280,390]){await p.setViewportSize({width,height:1000});await p.evaluate(()=>{MedFlowDisplay.set({theme:'light'});});for(const zoom of [80,100,130,160]){await p.evaluate(z=>MedFlowDisplay.set({zoom:z}),zoom);const d=await p.evaluate(()=>({scroll:document.body.scrollWidth,client:document.body.clientWidth}));if(d.scroll>d.client+1)console.log('OVERFLOW',await p.evaluate(()=>[...document.querySelectorAll('body *')].filter(n=>n.getBoundingClientRect().right>innerWidth+1).map(n=>({id:n.id,c:n.className,text:n.textContent.slice(0,60)})).slice(0,20)));assert.ok(d.scroll<=d.client+1,JSON.stringify({width,zoom,...d}));}await p.evaluate(()=>MedFlowDisplay.set({zoom:100}));assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);await p.waitForTimeout(350);await p.screenshot({path:shots+'/doctor-calendar-'+width+'.png',fullPage:true});}
 // Real conversational choices, with controlled extraction for free-text intake.
 await p.setViewportSize({width:1440,height:1000});await p.goto('http://127.0.0.1:8765/Receptionist');await p.waitForFunction(()=>state.config);await p.locator('#navDemo').click();await p.locator('#demoModeChat').click();await p.locator('#demoRunBtn').click();await p.waitForFunction(()=>state.demoRunning&&!state.demoBusy);
 for(const text of ['Browser Voice Patient','جی','23','جی','03000000002','جی','yes','no','Cough']){await p.locator('#demoInput').fill(text);await p.locator('#demoSendBtn').click();await p.waitForFunction(()=>!state.demoBusy);}
 await p.waitForFunction(()=>agentArtifact.current_field==='department'&&receptionChoiceData?.field==='department');
 await p.locator('#receptionChoiceContent .choice-card').filter({hasText:'General Medicine'}).click();await p.waitForFunction(()=>!state.demoBusy&&agentArtifact.current_field==='doctor'&&receptionChoiceData?.field==='doctor');
 await p.locator('#receptionChoiceContent .choice-card').filter({hasText:'Synthetic Audit Doctor'}).click();await p.waitForFunction(()=>!state.demoBusy&&agentArtifact.current_field==='time'&&receptionChoiceData?.field==='time');
 await p.locator('#receptionSlots .slot-choice').first().click();await p.waitForFunction(()=>!state.demoBusy&&agentArtifact.step==='confirm');
 assert.ok(await p.evaluate(()=>agentArtifact.pending.iso.includes('+05:00')));
 await p.locator('#demoInput').fill('جی');await p.locator('#demoSendBtn').click();await p.waitForFunction(()=>!state.demoBusy&&agentArtifact.step==='summary');
 await p.locator('#demoInput').fill('جی');await p.locator('#demoSendBtn').click();await p.waitForFunction(()=>state.demoSaved?.saved&&!state.demoSaving);
 assert.equal(await p.evaluate(()=>state.demoSaved.booking.appointment.practitioner_id),before.practitioner_id);
 assert.deepEqual(errors,[]);console.log('BOOKING: inline department/doctor/slot calendar; actual voice/tap booking; staff identity review; calendar/request separation; read-only preview; durable attendance confirmation and calendar replacement; three viewports at 80–160% zoom; page errors 0');
 await browser.close();server.kill();clearTimeout(deadline);
})().catch(async e=>{console.error(e);clearTimeout(deadline);if(browser)await browser.close();server?.kill();process.exitCode=1;});
