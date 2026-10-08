/* Returned booking data only. Presentation cannot drive the booking state machine. */
(function () {
  'use strict';
  function available() {return !state.demoBusy && !state.demoSaving && !state.demoRecording && !state.busy && !state.demoRunning && !window.liveConversation?.controller.active;}
  const row = (label,text,tone='received',badge='') => ({label,text:String(text ?? ''),tone,badge});
  function fieldsRows(values) {return Object.entries(values || {}).map(([key,value]) => row(key.replaceAll('_',' '), typeof value === 'object' ? value.en || value.ur || '' : value));}
  window.presentReceptionResult = function (manual = false) {
    if (!available()) return;
    const result = manual ? {saved:!!state.patientId,patient_id:state.patientId,workflow_id:state.workflowId,booking:state.bookingReceipt} : agentSaved;
    if (!result?.saved) return;
    const appointment = result.booking?.appointment;
    const values = manual ? {name:document.getElementById('fieldName').value,age:document.getElementById('fieldAge').value,phone:document.getElementById('fieldPhone').value,history:document.getElementById('fieldHistory').value,complaint:document.getElementById('fieldComplaint').value} : agentArtifact?.values || {};
    const conversation = manual ? [] : [...document.querySelectorAll('#demoTranscript .chat-bubble')].map((node,index) => ({id:String(index+1),label:node.querySelector('.meta')?.textContent || 'Conversation',text:[...node.querySelectorAll('p,.bilingual-urdu,.bilingual-en')].map(p => p.textContent).join('\n')}));
    const fields = fieldsRows(values);
    const stages = [
      {label:'Intake',title:'Collected patient details',icon:'user-round',detail:manual ? 'Submitted manual intake.' : 'Accepted fields returned by the receptionist.',rows:fields.length ? fields : (result.details || []).map(item => row(item.label,item.en || item.ur))},
      {label:'Saved',title:'Patient intake persisted',icon:'database',detail:'This receipt was returned before playback started.',rows:[row('Patient',result.patient_id,'checked','Saved'),row('Workflow',result.workflow_id || 'Not supplied')]},
      {label:'Appointment',title:appointment ? 'Appointment receipt' : 'Appointment needs attention',icon:'calendar-check',detail:'Playback shows the stored booking outcome.',rows:appointment ? [row('Doctor',appointment.practitioner_name || appointment.practitioner_id),row('Time',formatSlot(appointment.start_at)),row('Status',String(appointment.status || 'Stored').replaceAll('_',' '),'review')] : [row('Booking status',result.booking?.message || result.booking?.status || 'No appointment saved. Choose an available slot.','review','Not booked')]},
      {label:'Handoff',title:appointment ? 'Doctor handoff available' : 'Saved intake retained',icon:'arrow-up-right',detail:'Identity verification and appointment confirmation remain separate recorded steps.',rows:appointment ? [row('Appointment',appointment.appointment_id,'checked','Stored'),row('Destination',appointment.practitioner_name || appointment.practitioner_id),row('Next step',appointment.status === 'REQUESTED' ? 'The assigned doctor can open the saved request, verify identity and confirm the appointment.':'Open the assigned doctor workspace to continue the visit.','review')] : [row('Next step','Continue booking from this saved intake. No doctor appointment has been created.','review')]}
    ];
    MedFlowPresentation.open({title:'Reception → doctor handoff',receipt:`Saved intake · ${result.patient_id}`,sourceTitle:manual ? 'Submitted details' : 'Caller & Samra',sources:conversation.length ? conversation : fields.map((item,index) => ({id:String(index),label:item.label,text:item.text})),stages,duration:12000});
  };
  function addButton(root, manual = false) {
    if (!root || root.hidden) return;
    let button = root.querySelector('[data-present-reception]');
    if (!button) {button = document.createElement('button'); button.type = 'button'; button.className = 'present-result-button'; button.dataset.presentReception = ''; button.innerHTML = '<i data-lucide="presentation" aria-hidden="true"></i>Present handoff'; button.onclick = () => window.presentReceptionResult(manual); root.append(button);}
    button.disabled = !available(); button.title = button.disabled ? 'Finish the current call or action first.' : 'Reveal the saved intake and booking receipt. No new API calls.';
    window.lucide?.createIcons();
  }
  const baseResult = renderDemoResult;
  renderDemoResult = function (result) {baseResult(result); if (result?.saved) addButton(document.getElementById('demoResult'));};
  const baseProcess = renderReceptionProcess;
  renderReceptionProcess = function (...args) {baseProcess(...args); if (agentSaved?.saved) addButton(document.getElementById('demoResult'));};
  const baseEnd = endDemo;
  endDemo = async function (...args) {await baseEnd(...args); if (agentSaved?.saved) addButton(document.getElementById('demoResult'));};
  const baseSubmit = submitIntake;
  submitIntake = async function (...args) {await baseSubmit(...args); if (state.patientId && !document.getElementById('bookingResult').hidden) addButton(document.getElementById('bookingResult'),true);};
  const baseReset = resetSession;
  resetSession = function (...args) {if (!state.busy && !state.demoBusy && !state.demoSaving) MedFlowPresentation.close(); return baseReset(...args);};
})();
