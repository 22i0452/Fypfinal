/* Reproducible browser QA: requires Playwright + Chromium and Python app dependencies.
 * Uses synthetic microphone signal and provider outputs, not a real ASR accuracy test.
 */
const {chromium}=require(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES ? process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES+'/playwright' : 'playwright');
const assert=require('node:assert/strict'),path=require('node:path');
const base='http://127.0.0.1:8766';
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const deadline=setTimeout(()=>process.exit(1),180000);
let server,browser;
(async()=>{
 server=require('node:child_process').spawn('python',['tests/hands_free_fixture.py'],{cwd:path.resolve(__dirname,'..'),stdio:['ignore','ignore','pipe']});
 server.stderr.on('data',d=>process.stderr.write(d));process.on('exit',()=>server?.kill());
 let ready=false;for(let i=0;i<150;i++){try{if((await fetch(base+'/api/desk/health')).ok){ready=true;break}}catch{}await wait(100)}assert.ok(ready,'test server started');
 browser=await chromium.launch({executablePath:process.env.QA_CHROMIUM_PATH || undefined,args:['--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-zygote','--single-process','--disable-software-rasterizer'],headless:true});
 const p=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];let stt=0,turns=0,tts=0;
 p.on('pageerror',e=>errors.push(e.message));p.on('request',r=>{if(r.url().endsWith('/demo-calls/stt'))stt++;if(r.url().endsWith('/demo-calls/turn'))turns++;if(r.url().endsWith('/demo-calls/tts'))tts++;});
 await p.addInitScript(()=>{
   navigator.mediaDevices.getUserMedia=async()=>{
     const ctx=new AudioContext();await ctx.resume();const osc=ctx.createOscillator(),gain=ctx.createGain(),dest=ctx.createMediaStreamDestination();
     osc.frequency.value=380;gain.gain.value=0;osc.connect(gain);gain.connect(dest);osc.start();
     window.qaSignal={ctx,osc,gain,stream:dest.stream};return dest.stream;
   };
 });
 await p.goto(base+'/Receptionist');await p.waitForFunction(()=>state.config && state.selectedDemoId==='in-new-booking');
 assert.equal(await p.locator('#handsFreeToggle').isChecked(),false);await p.locator('#handsFreeToggle').check();
 await p.locator('#demoVoiceBtn').click();await p.waitForFunction(()=>!state.demoBusy && liveConversation.controller.phase==='listening');
 assert.equal(await p.locator('#demoMicBtn').isVisible(),false);
 assert.ok(await p.evaluate(()=>liveConversation.controller.processor instanceof AudioWorkletNode),'uses real audio worklet');
 await wait(1500);assert.equal(stt,0,'silence sends no API requests');
 async function config(data){const r=await p.request.post(base+'/audit/voice-answer',{data});assert.ok(r.ok());}
 async function pulse(ms=180){await p.evaluate(()=>qaSignal.gain.gain.value=.09);await wait(ms);await p.evaluate(()=>qaSignal.gain.gain.value=0);}
 async function voice(text,ms=180){
   await config({text});const previous=turns;
   await p.waitForFunction(()=>!state.demoBusy && liveConversation.controller.phase==='listening');await wait(300);await pulse(ms);
   await p.waitForFunction(()=>!state.demoBusy && liveConversation.controller.phase==='listening');
   await p.waitForFunction(n=>agentRequests.filter(x=>x.label.includes('Extracting')).length>=n,previous+1).catch(()=>{});
   assert.equal(turns,previous+1,'one completed turn per answer');
 }
 // Real complete booking, using synthetic STT text through the existing server route.
 const answers=['Ahmed Khan','جی','22','جی','03000000567','جی','جی','none','بخار','general medicine','1'];
 for(const [index,answer] of answers.entries()){
   await voice(answer,answer==='جی'?100:180);
   if(index===0){
     await p.getByRole('button',{name:'Inspect Name evidence',exact:true}).click();
     assert.equal(await p.evaluate(()=>liveConversation.controller.paused),true);
     assert.equal(await p.evaluate(()=>qaSignal.stream.getTracks()[0].enabled),false);
     assert.ok((await p.locator('#evidenceDialog').innerText()).includes('Ahmed Khan'));
     await p.locator('#evidenceDialog [data-evidence-close]').click();
     await p.locator('#liveVoicePause').click();
   }
   if(index===1){
     await p.getByRole('button',{name:'Inspect Name evidence',exact:true}).click();
     assert.ok((await p.locator('#evidenceDialog').innerText()).includes('Patient confirmed'));
     await p.locator('#evidenceDialog .evidence-technical summary').click();
     assert.ok((await p.locator('#evidenceDialog').innerText()).includes('R0001'));
     assert.ok((await p.locator('#evidenceDialog').innerText()).includes('R0002'));
     for(const width of [1440,1280,390]){
       await p.setViewportSize({width,height:900});
       assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);
       assert.equal(await p.locator('#evidenceDialog').evaluate(x=>x.scrollWidth<=x.clientWidth),true);
     }
     await p.setViewportSize({width:1440,height:900});
     await p.locator('#evidenceDialog [data-evidence-close]').click();
     await p.locator('#liveVoicePause').click();
   }
 }
 console.log('Reception evidence: raw answer, separate confirmation IDs, muted inspection and responsive modal passed.');
 assert.equal(await p.evaluate(()=>agentArtifact.current_field),'time');
 const practitioner=await p.evaluate(()=>agentArtifact.values.doctor.practitioner_id);
 const availability=await p.request.get(base+'/api/desk/availability',{params:{practitioner_id:practitioner,visit_type_id:'VISIT-NEW'}});
 const slot=(await availability.json()).slots[0].start_at;
 await voice(slot);
 await voice('جی');assert.equal(await p.evaluate(()=>agentArtifact.step),'summary');
 await config({text:'جی'});await wait(300);await pulse(100);
 await p.waitForFunction(()=>!state.demoRunning && state.demoSaved?.booking?.appointment?.appointment_id);
 const receipt=await p.evaluate(()=>state.demoSaved);assert.equal(receipt.confirmed,true);assert.equal(receipt.booking.appointment.practitioner_id,practitioner);
 assert.equal(await p.evaluate(()=>liveConversation.controller.active),false);assert.equal(await p.evaluate(()=>qaSignal.stream.getTracks()[0].readyState),'ended');
 console.log('Full hands-free booking: short Urdu answers, real available slot, final confirmation, exact doctor and saved handoff passed.');
 // Presentation uses the returned voice-call receipt and cannot send another turn.
 const playbackCounts={stt,turns,tts};await p.locator('[data-present-reception]').click();await p.locator('[data-presentation-skip]').click();assert.ok((await p.locator('#presentationResults').innerText()).includes(receipt.booking.appointment.appointment_id));await p.locator('[data-presentation-close]').click();assert.deepEqual({stt,turns,tts},playbackCounts);assert.equal(await p.evaluate(()=>state.demoSaved.booking.appointment.appointment_id),receipt.booking.appointment.appointment_id);
 // Start a second call and test pause, switching, interruption and failures.
 await p.locator('#demoVoiceBtn').click();await p.waitForFunction(()=>!state.demoBusy && liveConversation.controller.phase==='listening');
 await p.locator('#liveVoicePause').click();assert.equal(await p.evaluate(()=>qaSignal.stream.getTracks()[0].enabled),false);
 const beforePause=stt;await pulse(250);await wait(1500);assert.equal(stt,beforePause);
 await p.locator('#liveVoicePause').click();await p.waitForFunction(()=>liveConversation.controller.phase==='listening');
 await p.locator('#handsFreeToggle').uncheck();assert.equal(await p.locator('#demoMicBtn').isVisible(),true);
 assert.equal(await p.evaluate(()=>qaSignal.stream.getTracks()[0].readyState),'ended');
 await config({text:'Ahmed Khan'});await p.locator('#demoMicBtn').click();await p.waitForFunction(()=>state.demoRecording);
 await pulse(180);await p.locator('#demoMicBtn').click();await p.waitForFunction(()=>!state.demoBusy && agentArtifact.step==='confirm');
 const historyBefore=await p.evaluate(()=>JSON.stringify(state.demoHistory));await p.locator('#handsFreeToggle').check();await p.waitForFunction(()=>liveConversation.controller.phase==='listening');
 assert.equal(await p.evaluate(()=>JSON.stringify(state.demoHistory)),historyBefore,'switch preserves accepted history');
 // Leaving the call panel and connection loss mute capture until explicit resume.
 await p.locator('#navIntake').click();assert.equal(await p.evaluate(()=>liveConversation.controller.paused),true);
 await p.locator('#navDemo').click();await p.locator('#liveVoicePause').click();await p.waitForFunction(()=>liveConversation.controller.phase==='listening');
 await p.evaluate(()=>window.dispatchEvent(new Event('offline')));assert.equal(await p.evaluate(()=>liveConversation.controller.paused),true);
 assert.equal(await p.evaluate(()=>qaSignal.stream.getTracks()[0].enabled),false);await p.locator('#liveVoicePause').click();

 // Explicit interruption settles the playback promise and retains the next answer.
 await config({tts_seconds:5,text:'جی'});await p.locator('#liveVoiceRepeat').click();await p.waitForFunction(()=>!!state.demoAudio);
 await p.locator('#liveVoiceInterrupt').click();await p.waitForFunction(()=>!state.demoBusy && liveConversation.controller.phase==='listening');
 await config({tts_seconds:.25});await voice('جی',100);assert.equal(await p.evaluate(()=>agentArtifact.current_field),'age');
 // Echo gate: a synthetic strong input while Samra speaks must not submit.
 await config({tts_seconds:2});const beforeEcho=stt;await p.locator('#liveVoiceRepeat').click();await p.waitForFunction(()=>!!state.demoAudio);
 await pulse(500);await p.waitForFunction(()=>!state.demoBusy);assert.equal(stt,beforeEcho);
 await config({tts_seconds:.25});
 // Opt-in automatic interruption with synthetic signal (physical echo remains unmeasured).
 await p.locator('#autoInterruptOption').evaluate(el=>el.open=true);await p.locator('#autoInterruptToggle').check();
 await config({tts_seconds:5,text:'22'});await p.locator('#liveVoiceRepeat').click();await p.waitForFunction(()=>liveConversation.controller.phase==='speaking');
 await pulse(400);await p.waitForFunction(()=>!state.demoBusy && liveConversation.controller.phase==='capturing');await config({tts_seconds:.25});
 await p.waitForFunction(()=>!state.demoBusy && agentArtifact.pending?.key==='age');await p.locator('#autoInterruptToggle').uncheck();
 // Uncertain transcript preserves accepted history and pauses.
 const valuesBefore=await p.evaluate(()=>JSON.stringify(agentArtifact.values));await config({text:'مریض اردو رسم خط میں لکھیں جیسے 3 بجے۔'});
 await wait(300);await pulse();await p.waitForFunction(()=>!state.demoBusy && liveConversation.controller.paused);
 assert.equal(await p.evaluate(()=>JSON.stringify(agentArtifact.values)),valuesBefore);assert.ok((await p.locator('#demoInput').inputValue()).includes('مریض'));
 await p.locator('#demoInput').fill('جی');await p.locator('#demoSendBtn').click();await p.waitForFunction(()=>!state.demoBusy);
 await p.locator('#liveVoicePause').click();await p.waitForFunction(()=>liveConversation.controller.phase==='listening');
 // Provider failure pauses with accepted fields retained.
 await config({fail:true});await wait(300);await pulse();await p.waitForFunction(()=>!state.demoBusy && liveConversation.controller.paused);await config({fail:false});
 await p.locator('#liveVoicePause').click();await p.waitForFunction(()=>liveConversation.controller.phase==='listening');
 // Send-now dispatches before silence endpointing.
 await config({text:'03000000999'});const beforeSend=stt;await wait(300);await pulse(200);await p.waitForFunction(()=>liveConversation.controller.phase==='capturing');
 await p.locator('#liveVoiceSend').click();await p.waitForFunction(()=>!state.demoBusy && agentArtifact.pending?.key==='phone');assert.equal(stt,beforeSend+1);
 // Late transcription cannot write into a new session.
 await config({text:'جی',stt_delay:2});await wait(300);await pulse();await p.waitForFunction(()=>state.demoBusy && agentPhase==='speech');
 await p.locator('#demoStopBtn').click();await p.waitForFunction(()=>!state.demoSaving && !state.demoRunning);
 await config({stt_delay:0});await p.locator('#demoVoiceBtn').click();await p.waitForFunction(()=>!state.demoBusy && liveConversation.controller.phase==='listening');
 await wait(2300);assert.equal(await p.evaluate(()=>agentArtifact.current_field),'name');assert.deepEqual(await p.evaluate(()=>agentArtifact.values),{});
 // Saved preference survives reload; a reload never activates a microphone automatically.
 await p.evaluate(()=>stopDemo());await p.reload();await p.waitForFunction(()=>state.config && state.selectedDemoId==='in-new-booking');
 assert.equal(await p.locator('#handsFreeToggle').isChecked(),true);assert.equal(await p.evaluate(()=>liveConversation.controller.active),false);
 // Permission failure leaves typing and switching available.
 await p.evaluate(()=>stopDemo());await p.evaluate(()=>{navigator.mediaDevices.getUserMedia=async()=>{throw new Error('Synthetic permission denied')}});
 await p.locator('#demoVoiceBtn').click();await p.waitForFunction(()=>!state.demoBusy);assert.equal(await p.evaluate(()=>liveConversation.controller.active),false);
 assert.equal(await p.locator('#demoInput').isEnabled(),true);await p.locator('#handsFreeToggle').uncheck();assert.equal(await p.locator('#demoMicBtn').isVisible(),true);
 await p.evaluate(()=>stopDemo());await p.reload();await p.waitForFunction(()=>state.config && state.selectedDemoId==='in-new-booking');
 assert.equal(await p.locator('#handsFreeToggle').isChecked(),false);
 for(const width of [1440,1280,390]){await p.setViewportSize({width,height:1000});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await p.screenshot({path:require('node:os').tmpdir()+'/medflow-hands-free-'+width+'.png',fullPage:true});}
 assert.deepEqual(errors,[]);console.log('Manual mode, switching/history, muted pause, interruption, playback echo gating, experimental interruption, review, failure, Send now, stale response, permission recovery and responsive layouts passed.');
 await p.evaluate(()=>stopDemo());await browser.close();server.kill();clearTimeout(deadline);
})().catch(async error=>{console.error(error);await browser?.close();server?.kill();clearTimeout(deadline);process.exitCode=1});
