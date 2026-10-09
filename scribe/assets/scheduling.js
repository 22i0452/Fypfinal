/* Calendar, staff identity review and prepared attendance requests. */
let doctorScheduleTab='schedule',doctorScheduleDay='',doctorScheduleMonth='',doctorScheduleZone='Asia/Karachi';
let attendanceTarget=null,attendanceRecord=null,attendanceBusy=false,attendanceEpoch=0,attendancePreview=false,attendanceMode='',attendanceDay='',attendanceMonth='',attendanceSlots=[],attendanceSlot='';
let activeDetailsVerification=null;
renderDoctorAppointmentList=function(){
 const cal=document.getElementById('doctorCalendar');if(!cal)return;
 const today=MedFlowCalendar.key(new Date(),doctorScheduleZone);
 doctorScheduleDay ||= today;doctorScheduleMonth ||= doctorScheduleDay;
 const pending=doctorAppointments.filter(x=>x.status==='REQUESTED'),scheduled=doctorAppointments.filter(x=>x.status!=='REQUESTED');
 document.getElementById('appointmentCountBadge').textContent=scheduled.length?'· '+scheduled.length:'';
 document.getElementById('pendingRequestCount').textContent=pending.length;
 document.getElementById('scheduleTimezone').textContent=doctorScheduleZone.replaceAll('_',' ')+' · your assigned appointments';
 const counts={};doctorAppointments.forEach(a=>{const d=MedFlowCalendar.key(a.start_at,doctorScheduleZone);counts[d]=(counts[d]||0)+1;});
 MedFlowCalendar.render(cal,{month:doctorScheduleMonth,selected:doctorScheduleDay,today,counts,onDate:day=>{doctorScheduleDay=day;renderDoctorAppointmentList();},onMonth:month=>{doctorScheduleMonth=month;renderDoctorAppointmentList();}});
 document.getElementById('scheduleDateTitle').textContent=doctorScheduleTab==='requests'?'Reception requests':MedFlowCalendar.date(doctorScheduleDay).toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric',timeZone:'UTC'});
 document.getElementById('scheduleTab').classList.toggle('active',doctorScheduleTab==='schedule');document.getElementById('requestsTab').classList.toggle('active',doctorScheduleTab==='requests');
 const list=document.getElementById('doctorAppointmentList'),requests=document.getElementById('pendingRequestList');list.hidden=doctorScheduleTab!=='schedule';requests.hidden=doctorScheduleTab!=='requests';
 const visible=scheduled.filter(a=>MedFlowCalendar.key(a.start_at,doctorScheduleZone)===doctorScheduleDay);
 list.innerHTML=visible.length?visible.map(scheduleRow).join(''):`<div class="calendar-empty"><i data-lucide="calendar-days"></i><strong>A little space in your day.</strong><span>No confirmed appointments on this date.</span>${scheduled.length?'<button class="note-action" onclick="scheduleNextAppointment()" type="button">Next appointment</button>':''}</div>`;
 requests.innerHTML=pending.length?pending.map(scheduleRow).join(''):'<div class="calendar-empty"><i data-lucide="inbox"></i><strong>You’re up to date.</strong><span>New reception requests will appear here.</span></div>';
 studioIcons();
};
function scheduleRow(a){
 const index=doctorAppointments.indexOf(a),request=a.attendance;
 const state=request?.stale?'Needs new confirmation':request?({AWAITING_RESPONSE:'Awaiting response',CONFIRMED:'Attendance confirmed',RESCHEDULED:'Time changed',CANCELLED:'Cancelled'}[request.status]||request.status):'Attendance not requested';
 return `<div class="schedule-item"><time datetime="${escAttr(a.start_at)}">${escHtml(MedFlowCalendar.time(a.start_at,doctorScheduleZone))}</time><div><strong>${escHtml(a.patient_name)}</strong><small>${escHtml(a.department)} · ${escHtml(a.visit_type)}</small>${doctorScheduleTab==='requests'?`<small>${escHtml(formatDateTime(a.start_at))}</small>`:''}<small class="attendance-status ${!request||request.status==='AWAITING_RESPONSE'?'pending':''}">${studioIcon(request?.status==='CONFIRMED'&&!request.stale?'check-check':'circle')}${escHtml(state)}</small></div><div class="schedule-actions"><button class="note-action appointment-row" type="button" onclick="openScheduledPatient('${escAttr(a.patient_id)}')">${a.status==='REQUESTED'?'Review intake':'Open visit'}${studioIcon('arrow-up-right')}</button>${['REQUESTED','CONFIRMED'].includes(a.status)?`<button class="note-action" type="button" onclick="openAttendance(${index})">${studioIcon('bell')}Attendance</button>`:''}</div></div>`;
}
function setScheduleTab(tab){doctorScheduleTab=tab;renderDoctorAppointmentList();}
function scheduleToday(){doctorScheduleDay=MedFlowCalendar.key(new Date(),doctorScheduleZone);doctorScheduleMonth=doctorScheduleDay;renderDoctorAppointmentList();}
function scheduleNextAppointment(){const next=doctorAppointments.find(a=>a.status!=='REQUESTED'&&MedFlowCalendar.key(a.start_at,doctorScheduleZone)>=doctorScheduleDay)||doctorAppointments.find(a=>a.status!=='REQUESTED');if(next){doctorScheduleDay=MedFlowCalendar.key(next.start_at,doctorScheduleZone);doctorScheduleMonth=doctorScheduleDay;renderDoctorAppointmentList();}}
async function attendanceApi(path,body){const r=await fetch(path,{credentials:'same-origin',...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})}),p=await r.json().catch(()=>({}));if(!r.ok)throw new Error(apiMessage(p,'Unable to update attendance.'));return p;}
async function openAttendance(index){
 if(!canLeaveVisit()||attendanceBusy)return;
 const a=doctorAppointments[index];if(!a)return;
 const epoch=++attendanceEpoch;attendanceTarget={...a};attendanceRecord=a.attendance;attendancePreview=false;attendanceMode='';attendanceSlot='';attendanceDay=MedFlowCalendar.key(a.start_at,doctorScheduleZone);attendanceMonth=attendanceDay;
 renderAttendance();document.getElementById('attendancePanel').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth',block:'nearest'});
 try{const p=await attendanceApi('/api/appointments/'+encodeURIComponent(a.appointment_id));if(epoch!==attendanceEpoch)return;attendanceTarget={...a,...p};attendanceRecord=(await attendanceApi('/api/appointments/'+encodeURIComponent(a.appointment_id)+'/attendance')).request;if(epoch===attendanceEpoch)renderAttendance();}catch(e){showToast(e.message,'error');}
}
function closeAttendance(){if(attendanceBusy)return;attendanceEpoch++;attendanceTarget=null;document.getElementById('attendancePanel').hidden=true;}
function renderAttendance(){
 const root=document.getElementById('attendancePanel');root.hidden=!attendanceTarget;if(!attendanceTarget)return;
 const a=attendanceTarget,record=attendanceRecord,current=record&&!record.stale&&record.status==='AWAITING_RESPONSE';
 root.className='attendance-surface';
 root.innerHTML=`<div class="attendance-head"><div><span class="section-kicker">${attendancePreview?'PATIENT RESPONSE PREVIEW · DEMO':'APPOINTMENT ATTENDANCE'}</span><h4>${escHtml(a.patient_name)}</h4></div><button type="button" class="icon-btn" aria-label="Close attendance" onclick="closeAttendance()" ${attendanceBusy?'disabled':''}>${studioIcon('x')}</button></div><div class="attendance-receipt"><span>${studioIcon('calendar-days')}${escHtml(formatDateTime(a.start_at))}</span><span>${escHtml(a.department)}</span><span>${a.status==='REQUESTED'?'Clinic approval pending':'Clinic '+escHtml(a.status.toLowerCase().replaceAll('_',' '))}</span></div><p class="attendance-hint">${attendancePreview?'Preview only. These choices do not update the appointment or send a message.':record?.stale?'This appointment changed. Prepare a new confirmation request.':record?record.status==='AWAITING_RESPONSE'?'Prepared · awaiting response. No patient notification has been delivered.':'Saved response: '+escHtml(record.status.toLowerCase())+' · recorded by staff.':'Prepare a confirmation request, then record the patient’s response when received.'}</p><div class="attendance-options">${!current&&!attendancePreview?`<button class="toolbar-btn primary" onclick="prepareAttendance()" ${attendanceBusy?'disabled':''}>${studioIcon('bell')}Request confirmation</button>`:''}${current&&!attendanceMode&&!attendancePreview?'<button class="toolbar-btn primary" onclick="attendanceMode=\'response\';renderAttendance()">Record patient response</button>':''}<button class="note-action" onclick="attendancePreview=!attendancePreview;attendanceMode='';renderAttendance()" ${attendanceBusy?'disabled':''}>${studioIcon('eye')}${attendancePreview?'Exit preview':'Preview patient response'}</button></div>${attendanceMode||attendancePreview?`<div class="choice-cards">${[['ATTEND','check-check','I’ll attend','Confirm the selected appointment.'],['CHANGE_TIME','calendar-clock','Change time','Choose an available replacement.'],['CANCEL','calendar-x-2','Cancel appointment','Release this appointment.']].map(([value,icon,title,subtitle])=>`<button type="button" class="choice-card" onclick="chooseAttendanceResponse('${value}')" ${attendanceBusy?'disabled':''}>${studioIcon(icon)}<strong>${title}</strong><small>${subtitle}</small></button>`).join('')}</div>`:''}<div id="attendanceResponseDetail"></div>`;
 if(attendanceMode==='CHANGE_TIME'&&!attendancePreview)renderAttendanceCalendar();
 if(['ATTEND','CANCEL'].includes(attendanceMode)&&!attendancePreview){document.getElementById('attendanceResponseDetail').innerHTML=`<p class="attendance-hint">${attendanceMode==='CANCEL'?'This cancels the appointment and releases the reserved time.':'Attendance confirmation remains separate from the identity review and clinic approval.'}</p><label class="review-choice"><input type="checkbox" id="responseReceived">The patient communicated this response to clinic staff.</label><button type="button" class="toolbar-btn primary" onclick="saveAttendanceResponse('${attendanceMode}')" ${attendanceBusy?'disabled':''}>${attendanceMode==='CANCEL'?'Confirm cancellation':'Save attendance confirmation'}</button>`;}
 studioIcons();
}
async function prepareAttendance(){
 if(attendanceBusy||!attendanceTarget)return;attendanceBusy=true;renderAttendance();
 try{attendanceRecord=await attendanceApi('/api/appointments/'+encodeURIComponent(attendanceTarget.appointment_id)+'/attendance',{expected_version:attendanceTarget.version});await fetchDoctorQueue({quiet:true});attendanceMode='response';}
 catch(e){showToast(e.message,'error');}finally{attendanceBusy=false;renderAttendance();}
}
function chooseAttendanceResponse(value){
 if(attendancePreview){document.getElementById('attendanceResponseDetail').innerHTML=`<div class="booking-summary">${studioIcon('eye')}Demo preview: ${escHtml({ATTEND:'attendance confirmed',CHANGE_TIME:'available replacement times would appear here',CANCEL:'appointment cancellation requested'}[value])}. No records changed.</div>`;studioIcons();return;}
 attendanceMode=value;renderAttendance();if(value==='CHANGE_TIME')loadAttendanceSlots();
}
function renderAttendanceCalendar(){
 const root=document.getElementById('attendanceResponseDetail');root.innerHTML='<div class="booking-calendar-layout"><div id="attendanceCalendar"></div><div><h5 id="attendanceDayLabel"></h5><div id="attendanceSlots"></div></div></div><label class="review-choice"><input type="checkbox" id="responseReceived">The patient agreed to this replacement time.</label><button class="toolbar-btn primary" type="button" id="saveAttendanceTime" onclick="saveAttendanceResponse(\'CHANGE_TIME\')" disabled>Confirm replacement time</button>';
 MedFlowCalendar.render(document.getElementById('attendanceCalendar'),{month:attendanceMonth,selected:attendanceDay,min:MedFlowCalendar.key(new Date(),doctorScheduleZone),onDate:day=>{attendanceDay=day;attendanceSlot='';renderAttendanceCalendar();loadAttendanceSlots();},onMonth:month=>{attendanceMonth=month;renderAttendanceCalendar();}});
 document.getElementById('attendanceDayLabel').textContent=MedFlowCalendar.date(attendanceDay).toLocaleDateString('en-US',{dateStyle:'full',timeZone:'UTC'});
 renderAttendanceSlots();
}
function renderAttendanceSlots(loading=false){const root=document.getElementById('attendanceSlots');if(!root)return;MedFlowCalendar.slots(root,{rows:attendanceSlots.filter(s=>MedFlowCalendar.key(s.start_at,doctorScheduleZone)===attendanceDay),zone:doctorScheduleZone,selected:attendanceSlot,loading,onSelect:s=>{attendanceSlot=s.start_at;renderAttendanceSlots();document.getElementById('saveAttendanceTime').disabled=false;}});const b=document.getElementById('saveAttendanceTime');if(b)b.disabled=!attendanceSlot||attendanceBusy;}
async function loadAttendanceSlots(){
 const epoch=++attendanceEpoch,a=attendanceTarget,day=attendanceDay;attendanceSlots=[];renderAttendanceSlots(true);
 try{const params=new URLSearchParams({patient_id:a.patient_id,practitioner_id:a.practitioner_id,visit_type_id:a.visit_type_id,start_date:day,days:'1'});const p=await attendanceApi('/api/appointments/availability?'+params);if(epoch!==attendanceEpoch||!attendanceTarget)return;attendanceSlots=p.slots||[];renderAttendanceSlots();}
 catch(e){if(epoch===attendanceEpoch){showToast(e.message,'error');renderAttendanceSlots();}}
}
async function saveAttendanceResponse(response){
 if(attendanceBusy||attendancePreview||!attendanceRecord)return;
 if(!document.getElementById('responseReceived')?.checked){showToast('Confirm that the patient communicated this response.','error');return;}
 if(response==='CHANGE_TIME'&&!attendanceSlot)return;
 attendanceBusy=true;
 const panel=document.getElementById('attendancePanel');panel.querySelectorAll('button,input').forEach(x=>x.disabled=true);
 try{attendanceRecord=await attendanceApi('/api/appointments/'+encodeURIComponent(attendanceTarget.appointment_id)+'/attendance/respond',{request_id:attendanceRecord.request_id,response,...(response==='CHANGE_TIME'?{new_start_at:attendanceSlot}:{})});attendanceTarget={...attendanceTarget,...await attendanceApi('/api/appointments/'+encodeURIComponent(attendanceTarget.appointment_id))};attendanceMode='';await refreshDashboardQueues();if(selectedPatient?._id===attendanceTarget.patient_id)await refreshActiveContext();showToast('Patient response saved.');}
 catch(e){showToast(e.message,'error');}finally{attendanceBusy=false;renderAttendance();}
}
// Manual staff review is the default. OTP remains an explicit optional path.
const scheduleOtp=requestPatientOtp;
requestPatientOtp=async function(){renderPatientDetailsReview();document.getElementById('patientDetailsReview')?.scrollIntoView({behavior:'smooth',block:'center'});};
function renderPatientDetailsReview(){
 const root=document.getElementById('patientDetailsReview');if(!root)return;
 root.hidden=!selectedPatient||!activeWorkflow||activeWorkflow.state!=='PATIENT_UNVERIFIED';if(root.hidden){root.dataset.workflow='';return;}
 const key=activeWorkflow.workflow_id+':'+activeWorkflow.version;
 if(root.dataset.workflow!==key){root.dataset.workflow=key;root.innerHTML=`<div class="choice-heading">${studioIcon('user-check')}<div><h4>Review patient details</h4><p>Check this name and intake against the person attending.</p></div></div><label class="review-choice"><input type="checkbox" id="patientDetailsChecked">I checked the patient’s name and intake details.</label><div class="attendance-options"><button class="toolbar-btn primary" id="reviewPatientDetailsBtn" type="button" onclick="savePatientDetailsReview()">${studioIcon('check')}Confirm details reviewed</button></div><p class="attendance-hint">Recorded as staff review. This does not verify phone ownership or attendance.</p>`;}
 root.querySelectorAll('button,input').forEach(x=>x.disabled=visitLocked());studioIcons();
}
async function savePatientDetailsReview(){
 if(visitLocked()||!selectedPatient||!activeWorkflow)return;
 if(!document.getElementById('patientDetailsChecked')?.checked){showToast('Check the patient name and intake first.','error');return;}
 const patientId=selectedPatient._id,workflowId=activeWorkflow.workflow_id,version=activeWorkflow.version;
 visitActionBusy=true;renderClinicFlow();
 try{await attendanceApi('/api/verification/review-details',{patient_id:patientId,workflow_id:workflowId,expected_version:version,details_checked:true});const p=await attendanceApi('/api/workflows/'+encodeURIComponent(workflowId)+'/complete-intake',{});activeWorkflow=p.workflow;await refreshActiveContext();await fetchDoctorQueue({quiet:true});showToast('Patient details reviewed by staff.');}
 catch(e){showToast(e.message,'error');}finally{visitActionBusy=false;renderClinicFlow();}
}
const schedulingBaseContext=applyVisitContext;
applyVisitContext=function(payload,options){activeDetailsVerification=payload.details_verification;schedulingBaseContext(payload,options);};
const schedulingBaseRender=renderClinicFlow;
renderClinicFlow=function(){schedulingBaseRender();renderPatientDetailsReview();const first=document.querySelector('#preparationSteps .preparation-item strong');if(first&&activeDetailsVerification?.method==='MANUAL_STAFF_REVIEW')first.textContent='Patient details reviewed by staff';};
document.addEventListener('DOMContentLoaded',()=>renderDoctorAppointmentList());
// Calendar presentation for a doctor's direct booking path too.
let doctorBookingRows=[],doctorBookingMonth='';
function renderDoctorBookingCalendar(){
 const root=document.getElementById('doctorBookingCalendar');if(!root)return;
 const day=document.getElementById('bookingStartDate').value||MedFlowCalendar.key(new Date(),doctorScheduleZone);doctorBookingMonth ||= day;
 MedFlowCalendar.render(root,{month:doctorBookingMonth,selected:day,min:MedFlowCalendar.key(new Date(),doctorScheduleZone),onDate:d=>{document.getElementById('bookingStartDate').value=d;loadAvailableSlots();renderDoctorBookingCalendar();},onMonth:m=>{doctorBookingMonth=m;renderDoctorBookingCalendar();}});
 MedFlowCalendar.slots(document.getElementById('doctorBookingSlots'),{rows:doctorBookingRows.filter(s=>MedFlowCalendar.key(s.start_at,doctorScheduleZone)===day),zone:doctorScheduleZone,selected:document.getElementById('bookingSlot').value,onSelect:s=>{document.getElementById('bookingSlot').value=s.start_at;renderDoctorBookingCalendar();}});
}
const calendarBaseOpenBooking=openBookingDialog;
openBookingDialog=async function(){await calendarBaseOpenBooking();doctorBookingRows=[];doctorBookingMonth=document.getElementById('bookingStartDate').value;renderDoctorBookingCalendar();if(document.getElementById('bookingDialog').open)await loadAvailableSlots();};
const calendarBaseAvailable=loadAvailableSlots;
let doctorBookingEpoch=0;
loadAvailableSlots=async function(){
 const epoch=++doctorBookingEpoch,key=['bookingDoctor','bookingVisitType','bookingStartDate'].map(id=>document.getElementById(id).value).join(':');
 await calendarBaseAvailable();if(epoch!==doctorBookingEpoch||key!==['bookingDoctor','bookingVisitType','bookingStartDate'].map(id=>document.getElementById(id).value).join(':'))return;
 doctorBookingRows=Array.from(document.getElementById('bookingSlot').options).filter(o=>o.value).map(o=>({start_at:o.value}));renderDoctorBookingCalendar();
};
const calendarBaseSync=syncBookingProfile;
syncBookingProfile=function(){doctorBookingEpoch++;calendarBaseSync();doctorBookingRows=[];renderDoctorBookingCalendar();};
document.addEventListener('DOMContentLoaded',()=>{
 const native=document.getElementById('bookingSlot');native.closest('label').classList.add('choice-native');
 const surface=document.createElement('div');surface.className='booking-calendar-layout';surface.innerHTML='<div id="doctorBookingCalendar"></div><div><h5>Available times</h5><div id="doctorBookingSlots"></div></div>';
 native.closest('label').before(surface);
});
