/* One inline selection surface; voice and taps share the server booking flow. */
let receptionChoiceOverride='',receptionChoiceSignature='';
let receptionChoiceData=null,receptionChoiceKey='',receptionChoiceEpoch=0,receptionChoiceDay='',receptionChoiceMonth='',receptionChoiceDismissed='';
const departmentPresentation={
 'General Medicine':['stethoscope','General consultations and everyday health concerns.'],
 'Cardiology':['heart-pulse','Appointments for heart-related consultations.'],
 'Pediatrics':['baby','Appointments for children and young patients.']
};
function choiceCard(item,selected,onclick){return `<button type="button" class="choice-card ${selected?'selected':''}" onclick="${onclick}" ${state.demoBusy||state.demoSaving?'disabled':''}>${item.avatar?`<span class="choice-medallion">${escapeHtml(item.avatar)}</span>`:`<i data-lucide="${item.icon}"></i>`}<strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.subtitle)}</small>${item.note?`<em>${escapeHtml(item.note)}</em>`:''}</button>`;}
renderReceptionDoctorChoices=function(){
 const signature=JSON.stringify(state.demoHistory);if(signature!==receptionChoiceSignature){receptionChoiceSignature=signature;receptionChoiceOverride='';}
 const root=document.getElementById('receptionDoctorChoices'),field=agentArtifact?.current_field;
 if(!root)return;
 const visible=state.demoRunning&&state.selectedDemoId==='in-new-booking'&&['department','doctor','time'].includes(field)&&!['summary','done'].includes(agentArtifact?.step);
 root.hidden=!visible;if(!visible){receptionChoiceKey='';receptionChoiceData=null;receptionChoiceEpoch++;return;}
 root.className='choice-panel reception-choice-surface';
 const key=state.demoSessionId+':'+JSON.stringify(state.demoHistory)+':'+receptionChoiceDay;
 if(key!==receptionChoiceKey){receptionChoiceKey=key;loadReceptionChoices(key);}
 if(receptionChoiceData?.field===field)renderReceptionChoiceSurface(root,receptionChoiceOverride||field);
};
async function loadReceptionChoices(key){
 const epoch=++receptionChoiceEpoch,field=agentArtifact?.current_field;
 if(field!=='time'){receptionChoiceDay='';receptionChoiceMonth='';}
 const root=document.getElementById('receptionDoctorChoices');
 root.innerHTML='<p class="calendar-empty" role="status">Preparing clinic choices…</p>';
 try{
  const data=await api('/api/desk/demo-calls/choices',{method:'POST',body:JSON.stringify({history:state.demoHistory,...(receptionChoiceDay?{start_date:receptionChoiceDay}:{})})});
  if(epoch!==receptionChoiceEpoch||key!==receptionChoiceKey||!state.demoRunning)return;
  receptionChoiceData=data;
  if(field==='time'&&!receptionChoiceDay){receptionChoiceDay=data.slots[0]?MedFlowCalendar.key(data.slots[0].start_at,data.timezone):MedFlowCalendar.key(new Date(),data.timezone);receptionChoiceMonth=receptionChoiceDay;}
  renderReceptionChoiceSurface(root,receptionChoiceOverride||field);
 }catch(e){if(epoch===receptionChoiceEpoch)root.innerHTML=`<p class="attendance-hint">${escapeHtml(e.message)}</p><button class="note-action" type="button" onclick="receptionChoiceKey='';renderReceptionDoctorChoices()">Retry choices</button>`;}
}
function renderReceptionChoiceSurface(root,field){
 const d=receptionChoiceData,values=agentArtifact.values||{},current=['department','doctor','time'].indexOf(field);
 const title={department:'Choose your department',doctor:'Meet your doctor',time:'Find a time that works'}[field];
 root.innerHTML=`<div class="choice-stepbar">${[['department','building-2','Department'],['doctor','stethoscope','Doctor'],['time','calendar-days','Time']].map(([k,i,l],n)=>`<button type="button" onclick="editReceptionChoice('${k}')" ${n>['department','doctor','time'].indexOf(agentArtifact.current_field)?'disabled':''} class="${n===current?'active':''}"><i data-lucide="${n<current?'check':i}"></i>${l}</button>`).join('')}</div><div class="choice-heading"><i data-lucide="${field==='time'?'calendar-days':field==='doctor'?'stethoscope':'building-2'}"></i><div><h4>${title}</h4><p>Speak your choice or select it here. ${field==='time'?'Times shown in '+escapeHtml(d.timezone)+'.':'Samra continues the same conversation.'}</p></div></div><div id="receptionChoiceContent"></div><div class="booking-summary"><i data-lucide="${agentArtifact.step==='confirm'?'circle-help':'audio-lines'}"></i><span>${agentArtifact.step==='confirm'?'Awaiting your confirmation. Say yes, or choose a different option.':'Your microphone and accepted details stay connected.'}</span></div>`;
 const content=root.querySelector('#receptionChoiceContent');
 if(field==='department'){
  content.innerHTML='<div class="choice-cards">'+d.departments.map((item,index)=>{const [icon,subtitle]=departmentPresentation[item.name]||['building-2','Clinic department.'];return choiceCard({icon,title:item.name,subtitle},values.department?.en===item.name,`chooseReceptionOption('department',${index})`);}).join('')+'</div><button class="note-action" type="button" onclick="document.getElementById(\'demoInput\').value=\'I am not sure which department\';sendDemoMessage()">Not sure? Ask Samra</button>';
 }else if(field==='doctor'){
  content.innerHTML='<div class="choice-cards">'+d.doctors.map((item,index)=>choiceCard({avatar:item.display_name.replace(/^Dr\.?\s*/i,'').split(/\s+/).slice(0,2).map(s=>s[0]).join(''),title:item.display_name,subtitle:item.next_slot?'Next opening · '+formatSlot(item.next_slot):'No opening listed in the next 14 days',note:item.recommended?'Earliest listed opening':''},values.doctor?.practitioner_id===item.practitioner_id,`chooseReceptionOption('doctor',${index})`)).join('')+'</div><button class="note-action" type="button" onclick="document.getElementById(\'demoInput\').value=\'any doctor\';sendDemoMessage()">Any available doctor</button>';
  if(!d.doctors.length)content.innerHTML='<p class="calendar-empty">No doctors are currently listed for this department. Ask Samra to change department.</p>';
 }else{
  content.innerHTML='<div class="booking-calendar-layout"><div id="receptionCalendar"></div><div><h5 id="receptionSelectedDay"></h5><div id="receptionSlots"></div></div></div>';
  const zone=d.timezone,today=MedFlowCalendar.key(new Date(),zone),max=new Date(MedFlowCalendar.date(today).getTime()+90*86400000).toISOString().slice(0,10);
  MedFlowCalendar.render(document.getElementById('receptionCalendar'),{month:receptionChoiceMonth||receptionChoiceDay,selected:receptionChoiceDay,today,min:today,max,onDate:day=>{receptionChoiceDay=day;receptionChoiceKey='';renderReceptionDoctorChoices();},onMonth:month=>{receptionChoiceMonth=month;renderReceptionChoiceSurface(root,receptionChoiceOverride||field);}});
  document.getElementById('receptionSelectedDay').textContent=MedFlowCalendar.date(receptionChoiceDay).toLocaleDateString('en-US',{dateStyle:'full',timeZone:'UTC'});
  MedFlowCalendar.slots(document.getElementById('receptionSlots'),{rows:d.slots.filter(s=>MedFlowCalendar.key(s.start_at,zone)===receptionChoiceDay),zone,selected:agentArtifact.pending?.iso||values.time?.iso,onSelect:slot=>chooseReceptionSlot(slot)});
 }
 lucide?.createIcons();
}
function editReceptionChoice(field){if(state.demoBusy||!receptionChoiceData)return;receptionChoiceOverride=field;renderReceptionChoiceSurface(document.getElementById('receptionDoctorChoices'),field);}
function chooseReceptionOption(field,index){
 const d=receptionChoiceData,item=field==='department'?d?.departments[index]:d?.doctors[index];if(!item||state.demoBusy||state.demoSaving)return;
 submitReceptionChoice({field,value:field==='department'?item.department_id:item.practitioner_id,label:field==='department'?item.name:item.display_name,revision:d.revision});
}
function chooseReceptionSlot(slot){if(!receptionChoiceData||state.demoBusy||state.demoSaving)return;submitReceptionChoice({field:'time',value:slot.start_at,label:formatSlot(slot.start_at),revision:receptionChoiceData.revision});}
function submitReceptionChoice(choice){
 stopDemoAudio();stopDemoMicCapture({finalize:false});window.liveConversation?.hold();
 sendDemoMessage(null,choice);
}
// Manual intake uses cards and the same shared calendar; native values remain
// the form's canonical fields, rather than a second unsaved booking draft.
let manualSlotDay='',manualSlotMonth='',manualChoiceEpoch=0,manualSlotRows=[];
function manualChoiceRoot(){return document.getElementById('manualBookingChoices');}
function renderManualBookingChoices(){
 const root=manualChoiceRoot();if(!root||!state.config)return;
 const department=document.getElementById('fieldDepartment'),doctor=document.getElementById('fieldDoctor'),visit=document.getElementById('fieldVisitType');
 root.innerHTML=`<div class="choice-heading"><i data-lucide="building-2"></i><div><h4>Department</h4><p>A clear starting point for this visit.</p></div></div><div class="choice-cards">${state.config.departments.map((d,i)=>{const [icon,subtitle]=departmentPresentation[d.name]||['building-2','Clinic department.'];return choiceCard({icon,title:d.name,subtitle},d.department_id===department.value,`selectManualDepartment(${i})`);}).join('')}</div><div class="choice-panel"><div class="choice-heading"><i data-lucide="stethoscope"></i><div><h4>Your doctor</h4><p>Choose an active doctor in this department.</p></div></div><div class="choice-cards">${practitionersForDepartment(department.value).map((d,i)=>choiceCard({avatar:d.display_name.replace(/^Dr\.?\s*/i,'').split(/\s+/).slice(0,2).map(s=>s[0]).join(''),title:d.display_name,subtitle:state.config.departments.find(x=>x.department_id===d.department_id)?.name||''},d.practitioner_id===doctor.value,`selectManualDoctor(${i})`)).join('')}</div></div><div class="choice-panel"><div class="choice-heading"><i data-lucide="calendar-days"></i><div><h4>Appointment time</h4><p>${escapeHtml(state.config.clinic.timezone)} · availability is checked again when saving.</p></div></div><div class="attendance-options">${state.config.visit_types.map((v,i)=>`<button type="button" class="slot-choice ${v.visit_type_id===visit.value?'selected':''}" onclick="selectManualVisit(${i})">${escapeHtml(v.name)}</button>`).join('')}</div><div class="booking-calendar-layout"><div id="manualCalendar"></div><div><h5 id="manualSelectedDay"></h5><div id="manualSlots"></div></div></div><div id="manualSlotSummary" class="booking-summary"></div></div>`;
 renderManualCalendar();window.lucide?.createIcons();
}
function selectManualDepartment(index){document.getElementById('fieldDepartment').value=state.config.departments[index].department_id;manualSlotRows=[];onDepartmentChange();renderManualBookingChoices();}
function selectManualDoctor(index){document.getElementById('fieldDoctor').value=practitionersForDepartment(document.getElementById('fieldDepartment').value)[index].practitioner_id;onDoctorChange();renderManualBookingChoices();}
function selectManualVisit(index){document.getElementById('fieldVisitType').value=state.config.visit_types[index].visit_type_id;loadSlots();renderManualBookingChoices();}
function renderManualCalendar(){
 if(!document.getElementById('manualCalendar'))return;
 const zone=state.config.clinic.timezone,today=MedFlowCalendar.key(new Date(),zone);manualSlotDay ||= today;manualSlotMonth ||= manualSlotDay;
 MedFlowCalendar.render(document.getElementById('manualCalendar'),{month:manualSlotMonth,selected:manualSlotDay,today,min:today,onDate:day=>{manualSlotDay=day;loadSlots();renderManualCalendar();},onMonth:month=>{manualSlotMonth=month;renderManualCalendar();}});
 document.getElementById('manualSelectedDay').textContent=MedFlowCalendar.date(manualSlotDay).toLocaleDateString('en-US',{dateStyle:'full',timeZone:'UTC'});
 MedFlowCalendar.slots(document.getElementById('manualSlots'),{rows:manualSlotRows.filter(s=>MedFlowCalendar.key(s.start_at,zone)===manualSlotDay),zone,selected:document.getElementById('fieldSlot').value,onSelect:slot=>{document.getElementById('fieldSlot').value=slot.start_at;updateProgress();renderManualCalendar();}});
 document.getElementById('manualSlotSummary').innerHTML=document.getElementById('fieldSlot').value?'<i data-lucide="check"></i>'+escapeHtml(formatSlot(document.getElementById('fieldSlot').value)):'<i data-lucide="clock-3"></i>Choose a time to complete the appointment.';
 window.lucide?.createIcons();
}
const choiceBaseConfiguration=loadConfiguration;
loadConfiguration=async function(){await choiceBaseConfiguration();renderManualBookingChoices();};
loadSlots=async function(){
 const epoch=++manualChoiceEpoch,doctor=document.getElementById('fieldDoctor').value,visit=document.getElementById('fieldVisitType').value,select=document.getElementById('fieldSlot');
 manualSlotRows=[];select.innerHTML='<option value="">Choose a time</option>';
 if(!doctor||!visit){renderManualCalendar();return;}
 const zone=state.config?.clinic.timezone||'Asia/Karachi';manualSlotDay ||= MedFlowCalendar.key(new Date(),zone);
 const target=document.getElementById('manualSlots');if(target)MedFlowCalendar.slots(target,{loading:true,rows:[]});
 try{const result=await api(`/api/desk/availability?practitioner_id=${encodeURIComponent(doctor)}&visit_type_id=${encodeURIComponent(visit)}&start_date=${manualSlotDay}&days=1&limit=30`);
  if(epoch!==manualChoiceEpoch||document.getElementById('fieldDoctor').value!==doctor||document.getElementById('fieldVisitType').value!==visit)return;
  manualSlotRows=result.slots||[];fillSelect(select,manualSlotRows,s=>s.start_at,s=>formatSlot(s.start_at),'Choose a time');renderManualCalendar();updateProgress();
 }catch(e){if(epoch===manualChoiceEpoch){showToast(e.message,'error');if(target)target.innerHTML='<p class="attendance-hint">Unable to load openings. Use Refresh slots to retry.</p>';}}
};
const choiceBaseDepartment=onDepartmentChange;
onDepartmentChange=function(){manualChoiceEpoch++;manualSlotRows=[];choiceBaseDepartment();renderManualBookingChoices();};
document.addEventListener('DOMContentLoaded',()=>{
 const root=document.createElement('div');root.id='manualBookingChoices';root.className='manual-choice-surface';root.dataset.intakeStage='1';document.querySelector('#intakeForm .form-grid').append(root);
 for(const id of ['fieldDepartment','fieldDoctor','fieldVisitType','fieldSlot'])document.getElementById(id).closest('label').classList.add('choice-native');
 renderManualBookingChoices();
});
