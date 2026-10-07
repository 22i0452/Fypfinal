let intakeStage=0;
let intakeAlternatives=[];
function renderIntakeAlternatives(booking){
  intakeAlternatives=booking.alternatives || [];
  const result=document.getElementById('bookingResult');result.hidden=false;
  result.innerHTML='<h4>Intake saved. Choose another time.</h4><p>The requested slot is unavailable. No appointment has been created.</p>'+intakeAlternatives.map((slot,i)=>`<button class="note-action" onclick="selectIntakeAlternative(${i})">${escapeHtml(formatSlot(slot.start_at))}</button>`).join('');
}
function selectIntakeAlternative(index){
  const slot=intakeAlternatives[index];if(!slot)return;
  const select=document.getElementById('fieldSlot');
  if(!Array.from(select.options).some(x=>x.value===slot.start_at))select.add(new Option(formatSlot(slot.start_at),slot.start_at));
  select.value=slot.start_at;document.getElementById('bookingResult').hidden=true;setIntakeStage(1);updateProgress();
}
function setIntakeStage(step){
  intakeStage=step;
  updateProgress();
  const form=document.getElementById('intakeForm');form.dataset.step=String(step);
  document.getElementById('intakeBack').hidden=step!==1;
  document.getElementById('intakeNext').hidden=step!==0;
  document.getElementById('submitBtn').hidden=step!==1;
  document.getElementById('intakeStepPatient').classList.toggle('active',step===0);
  document.getElementById('intakeStepBooking').classList.toggle('active',step===1);
  document.getElementById('intakeStepHandoff').classList.toggle('active',step===2);
  document.querySelector('.form-panel h3').textContent=step===0?'Begin with the patient.':step===1?'A time that works.':'A connected handoff.';
}
function continueIntake(){
  for(const id of FIELDS.slice(0,6)){const field=document.getElementById(id);if(!field.checkValidity()){field.reportValidity();return;}}
  setIntakeStage(1);
}
const studioIntakeSubmit=submitIntake;
submitIntake=async function(event){
  if(intakeStage===0){event.preventDefault();continueIntake();return;}
  for(const id of FIELDS){const field=document.getElementById(id);if(!field.checkValidity()){event.preventDefault();if(FIELDS.indexOf(id)<6)setIntakeStage(0);field.reportValidity();return;}}
  await studioIntakeSubmit(event);
  if(state.appointmentId){setIntakeStage(2);const result=document.getElementById('bookingResult');result.innerHTML=`<div class="handoff-mark"><i data-lucide="check-check"></i></div><span class="section-kicker">SENT TO THE DOCTOR</span><h3>${escapeHtml(document.getElementById('fieldName').value)}</h3><p>Intake and the appointment request are stored together. Identity verification and confirmation continue in the doctor workspace.</p><div class="handoff-details"><span>${escapeHtml(document.getElementById('fieldDoctor').selectedOptions[0]?.textContent || '')}</span><span>${escapeHtml(document.getElementById('fieldSlot').selectedOptions[0]?.textContent || '')}</span></div><a class="toolbar-btn primary" href="/workspace?patient_ref=${encodeURIComponent(state.patientId)}"><i data-lucide="arrow-up-right"></i>Open doctor handoff</a><button class="note-action" onclick="resetSession()"><i data-lucide="plus"></i>Next patient</button>`;if(window.lucide)lucide.createIcons();}
};
const studioReceptionReset=resetSession;
resetSession=function(){if(state.busy || state.demoBusy || state.demoSaving){showToast('Wait for the active action to finish.','error');return;}studioReceptionReset();setIntakeStage(0);};
const studioScenarioSelect=selectDemoScenario;
selectDemoScenario=function(id){studioScenarioSelect(id);if(id!=='in-new-booking')document.getElementById('demoRunnerDescription').textContent+=' Conversation simulation: this scenario does not change appointment records.';};
const studioDemoEnd=endDemo;
endDemo=async function(){const simulated=state.selectedDemoId!=='in-new-booking';await studioDemoEnd();if(simulated){const box=document.getElementById('demoResult');box.hidden=false;box.innerHTML='<h4>Conversation completed</h4><p>This simulation did not change any booking or clinical records.</p>';}};
const studioDemoResult=renderDemoResult;
renderDemoResult=function(result){studioDemoResult(result);if(result?.saved){const link=document.createElement('a');link.className='toolbar-btn primary';link.href='/workspace?patient_ref='+encodeURIComponent(result.patient_id);link.textContent='Open doctor handoff';document.getElementById('demoResult').append(link);}};
document.addEventListener('DOMContentLoaded',()=>setIntakeStage(0));
