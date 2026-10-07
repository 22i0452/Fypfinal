/* Voice agent observability. Fields come from BookingFlow; indicators follow requests/playback. */
let agentPhase='ready',agentMessage='Begin a voice conversation',agentArtifact=null,agentRequests=[],agentSaved=null;
const AGENT_STEPS=[['listening','mic','Listen'],['speech','scan-text','Transcribe'],['extract','list-filter','Collect'],['tts','audio-lines','Respond'],['save','calendar-check','Handoff']];
function receptionPhase(phase,message){agentPhase=phase;agentMessage=message || '';renderReceptionProcess();}
function receptionArtifact(artifact){if(artifact?.extractor){const meta=artifact.extractor;const latest=agentRequests.at(-1);if(latest)latest.backend=meta.method || `${meta.provider} / ${meta.model}${meta.fallback?" · fallback":""}`;}agentArtifact=artifact || (state.selectedDemoId!=='in-new-booking'?{simulation:true}:null);renderReceptionProcess();}
window.receptionSttResult=(payload,ms)=>{agentRequests.push({label:payload.garbled?"Unclear speech — repeat requested":"Speech transcription",ms,status:"complete",backend:payload.provider || ""});renderReceptionProcess();};
window.receptionIsError=()=>agentPhase==="error";
window.receptionPhase=receptionPhase;window.receptionArtifact=receptionArtifact;
const processReceptionApi=api;
api=async function(path,options){
  const map={'/api/desk/demo-calls/start':['extract','Opening the conversation'],'/api/desk/demo-calls/turn':['extract','Extracting your answer and choosing the next question'],'/api/desk/demo-calls/tts':['tts','Preparing Urdu speech'],'/api/desk/demo-calls/finish':['save','Saving confirmed intake and checking the requested slot']};
  const step=map[path];if(!step)return processReceptionApi(path,options);
  receptionPhase(...step);const started=performance.now(),epoch=state.demoSessionId;
  try{const result=await processReceptionApi(path,options);if(epoch!==state.demoSessionId)return result;agentRequests.push({label:step[1],ms:performance.now()-started,status:'complete',backend:result.backend || ''});if(path.endsWith('/finish'))agentSaved=result;renderReceptionProcess();return result;}
  catch(error){if(epoch!==state.demoSessionId || options?.signal?.aborted)throw error;agentRequests.push({label:step[1],ms:performance.now()-started,status:'failed'});receptionPhase('error',error.message || 'Action interrupted');throw error;}
};
const receptionBaseStatus=setStatus;
setStatus=function(text){receptionBaseStatus(text);if(/your turn|tap Mic|Ready|Complete/i.test(text)){if(window.liveConversation?.controller.active){const live=window.liveConversation.controller;receptionPhase(live.phase==='capturing'?'listening':live.phase,live.paused?'Listening paused':live.phase==='listening'?'Listening · speak when ready':text);}else receptionPhase('ready',state.demoRunning?(state.demoMode==='voice'?'Tap the microphone to reply':'Type your next reply'):'Start a conversation');}};
const receptionBaseScenario=selectDemoScenario;
selectDemoScenario=function(id){if(state.demoBusy || state.demoSaving || state.demoRecording || window.liveConversation?.capturing()){showToast('Finish the active voice turn before changing scenarios.','error');return;}agentArtifact=null;agentSaved=null;agentRequests=[];receptionBaseScenario(id);receptionPhase('ready','Start the voice agent or use text input');};
const receptionBaseDirection=setDemoDirection;
setDemoDirection=function(direction){if(state.demoBusy || state.demoSaving || state.demoRecording || window.liveConversation?.capturing()){showToast('Finish the active voice turn first.','error');return;}agentArtifact=null;agentSaved=null;agentRequests=[];receptionBaseDirection(direction);renderReceptionProcess();};
const receptionBaseMode=setDemoMode;
setDemoMode=function(mode){if(state.demoBusy || state.demoRecording){showToast('Finish the active voice turn before changing input mode.','error');return;}receptionBaseMode(mode);renderReceptionProcess();};
const receptionBaseView=showView;
showView=function(view){if((state.demoBusy || state.demoRecording || state.demoSaving) && view!==state.view){showToast('Finish the active voice turn before leaving.','error');return;}receptionBaseView(view);if(view==='demo')renderReceptionProcess();};
const receptionBaseSpeech=playDemoSpeech;
playDemoSpeech=async function(...args){try{return await receptionBaseSpeech(...args);}catch(error){receptionPhase('error','Speech playback failed. Retry with the next voice turn or switch to text.');throw error;}};
const receptionBaseResult=renderDemoResult;
renderDemoResult=function(result){agentSaved=result;receptionBaseResult(result);receptionPhase('ready',result?.booking?.appointment?.appointment_id?'Appointment request stored · ready for doctor handoff':result?.saved?'Intake stored · appointment needs attention':'No appointment saved');};
function renderReceptionProcess(){
  const root=document.getElementById('receptionProcess');if(!root)return;
  const values=agentArtifact?.values || {}, pending=agentArtifact?.pending;
  const fields=[['name','user-round','Name'],['age','calendar','Age'],['phone','phone','Phone'],['first_visit','clipboard','First visit'],['history','heart-pulse','History'],['complaint','stethoscope','Complaint'],['department','building-2','Department'],['doctor','user-check','Doctor'],['time','clock','Requested time']];
  const simulated=state.selectedDemoId && state.selectedDemoId!=='in-new-booking';
  const phaseIcon=AGENT_STEPS.find(x=>x[0]===agentPhase)?.[1] || (agentPhase==='speaking'?'volume-2':agentPhase==='error'?'circle-alert':'headset');
  const existingCanvas=root.querySelector('canvas');
  root.innerHTML=`<header class="agent-process-head"><div class="agent-identity"><span class="agent-avatar"><i data-lucide="${phaseIcon}"></i></span><div><h4>Samra</h4><small>RECEPTIONIST AGENT · ${simulated?'CONVERSATION SIMULATION':'BOOKING WORKFLOW'}</small></div></div><span class="agent-phase" role="status">${escapeHtml(agentMessage)}</span></header><div class="agent-signal"><canvas data-meter="reception" aria-label="Actual caller microphone waveform"></canvas><small data-meter-level="reception">${state.demoRecording || window.liveConversation?.controller.active && !window.liveConversation.controller.paused?'Microphone active':'Microphone inactive'}</small></div><div class="agent-flow">${AGENT_STEPS.map(([key,icon,label])=>`<div class="${key===agentPhase || key==='tts' && agentPhase==='speaking'?'active':key==='save' && agentSaved?.booking?.appointment?.appointment_id?'done':''}"><i data-lucide="${icon}"></i><span>${label}</span></div>`).join('')}</div><div class="agent-state-grid"><section><h5><i data-lucide="list-checks"></i>Collected details</h5>${fields.map(([key,icon,label])=>`<div class="agent-field ${key===agentArtifact?.current_field?'pending':''}"><small><i data-lucide="${icon}"></i>${label}</small><strong>${escapeHtml(values[key]?.en || (key===agentArtifact?.current_field && pending?.en?pending.en+' · awaiting confirmation':'—'))}</strong></div>`).join('')}</section><section><h5><i data-lucide="route"></i>Current action</h5><div class="agent-step-callout"><i data-lucide="${phaseIcon}"></i><strong>${escapeHtml(agentPhase==='listening'?'Listening to the caller':agentPhase==='speech'?'Transcribing recorded audio':agentPhase==='extract'?'Extracting and validating fields':agentPhase==='tts'?'Preparing speech':agentPhase==='speaking'?'Samra is speaking':agentPhase==='save'?'Saving and checking availability':agentPhase==='error'?'Action needs attention':agentSaved?.booking?.appointment?.appointment_id?'Doctor handoff available':agentArtifact?.confirmed?'Summary confirmed':'Awaiting caller input')}</strong><p>${escapeHtml(agentSaved?.booking?.appointment?.appointment_id?'Stored appointment '+agentSaved.booking.appointment.appointment_id:agentSaved?.saved?'Patient intake stored. Booking status: '+(agentSaved.booking?.status || 'not booked'):agentArtifact?.confirmed?'Caller details confirmed. Saving must succeed before a handoff exists.':agentArtifact?.current_field?'Next field: '+agentArtifact.current_field.replaceAll('_',' ')+'. The server owns this conversation state.':window.liveConversation?.supported()?'Start the agent. Hands-free sends each answer after a natural pause.':'Start the agent to collect patient details. Tap Mic, then Stop to send speech.')}</p></div><details class="agent-tool-log"><summary>Request timings · ${agentRequests.length} completed attempts</summary><ul>${agentRequests.slice(-12).map(item=>`<li><span>${escapeHtml(item.label)}${item.backend?'<br>'+escapeHtml(item.backend):''}</span><span>${(item.ms/1000).toFixed(2)}s · ${item.status}</span></li>`).join('')}</ul></details>${simulated?'<p class="agent-simulation">Conversation simulation: this scenario does not modify booking or clinical records.</p>':'<p class="agent-simulation">Listed openings are checked again when saving. The clinic confirms the final appointment.</p>'}</section></div>`;
  renderReceptionDoctorChoices();
  if(existingCanvas && (state.demoRecording || window.liveConversation?.controller.active)){const newCanvas=root.querySelector('canvas');newCanvas.replaceWith(existingCanvas);}
  if(window.lucide)lucide.createIcons({attrs:{'stroke-width':1.5}});
}
window.renderPhoneProcess=function(call){
  let panel=document.getElementById('phoneProcess');if(!panel){panel=document.createElement('div');panel.id='phoneProcess';panel.className='phone-process reception-process';document.getElementById('liveTranscript').before(panel);}
  const result=call.booking_result, fields=call.booking_process?.values || {};
  panel.innerHTML=`<div class="agent-process-head"><div class="agent-identity"><span class="agent-avatar"><i data-lucide="${call.speaking?'volume-2':call.processing?'scan-text':'phone-call'}"></i></span><div><h4>Phone session</h4><small>${call.speaking?'SPEECH PLAYBACK':call.processing?'PROCESSING TURN':call.status==='active'?'LISTENING':escapeHtml(call.status).toUpperCase()}</small></div></div><span class="agent-phase">${Object.keys(fields).length} fields collected</span></div><p class="agent-simulation">${result?.booking?.appointment?.appointment_id?'Appointment request stored: '+escapeHtml(result.booking.appointment.appointment_id):result?.saved?'Intake stored; booking needs attention.':'No stored appointment yet.'}</p>${result?.patient_id?`<a class="note-action" href="/workspace?patient_ref=${encodeURIComponent(result.patient_id)}">Open doctor handoff <i data-lucide="arrow-up-right"></i></a>`:''}`;if(window.lucide)lucide.createIcons();
};
document.addEventListener('DOMContentLoaded',()=>{const grid=document.createElement('div');grid.className='agent-live-grid';const process=document.getElementById('receptionProcess');process.before(grid);grid.append(document.getElementById('demoTranscript'),process);showView('demo');selectDemoScenario('in-new-booking');setDemoMode('voice');renderReceptionProcess();MedFlowMeter.reset('reception');});
window.addEventListener('beforeunload',()=>{stopDemoAudio();stopDemoMicCapture({finalize:false});});

const receptionBaseEnd=endDemo;
endDemo=async function(){await receptionBaseEnd();};

function renderReceptionDoctorChoices(){
  const root=document.getElementById('receptionDoctorChoices');if(!root)return;
  const choices=agentArtifact?.doctor_choices || [];
  root.hidden=!state.demoRunning || agentArtifact?.current_field!=='doctor' || !choices.length;
  if(root.hidden){root.innerHTML='';return;}
  const locked=state.demoBusy || state.demoSaving || state.demoRecording || window.liveConversation?.capturing();
  root.innerHTML=`<div class="doctor-choice-heading"><i data-lucide="stethoscope"></i><div><h4>Choose your doctor</h4><p>Say a name or number, or choose below. Suggestions use listed appointment availability.</p></div></div><div class="doctor-choice-grid">${choices.map((doctor,index)=>`<button type="button" class="doctor-choice ${doctor.recommended?'suggested':''}" ${locked?'disabled':''} onclick="chooseReceptionDoctor(${index})"><span class="doctor-option-number">${index+1}</span><span class="doctor-choice-copy"><strong>${escapeHtml(doctor.display_name)}</strong><small>${doctor.next_slot?'Next opening · '+escapeHtml(formatSlot(doctor.next_slot)):'No opening listed in the next 14 days'}</small>${doctor.recommended?'<em><i data-lucide="clock-3"></i>Earliest listed opening</em>':''}${doctor.preferred?'<small>Your workspace doctor</small>':''}</span><i data-lucide="arrow-up-right"></i></button>`).join('')}</div>`;
  if(window.lucide)lucide.createIcons();
}
function chooseReceptionDoctor(index){
  if(state.demoBusy || state.demoSaving || state.demoRecording || window.liveConversation?.capturing() || !state.demoRunning || agentArtifact?.current_field!=='doctor')return;
  const doctor=agentArtifact.doctor_choices?.[index];if(!doctor)return;
  document.getElementById('demoInput').value=String(index+1);
  sendDemoMessage();
}
window.renderReceptionDoctorChoices=renderReceptionDoctorChoices;
