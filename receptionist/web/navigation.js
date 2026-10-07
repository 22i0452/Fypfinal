let receptionIntakeDirty=false;
function canLeaveReception(){
  if(state.busy || state.demoBusy || state.demoSaving || state.demoRecording || state.demoRunning){
    showToast('Finish the current call or save before leaving reception.','error');return false;
  }
  if(receptionIntakeDirty && intakeStage!==2){showToast('Save the intake or start a new session before leaving reception.','error');return false;}
  return true;
}
function goReceptionHome(){
  if(!canLeaveReception())return;
  window.liveConversation?.controller.stop();stopDemoAudio();location.assign('/');
}
const navigationBaseReset=resetSession;
resetSession=function(...args){
  const blocked=state.busy || state.demoBusy || state.demoSaving;
  const result=navigationBaseReset(...args);if(!blocked)receptionIntakeDirty=false;return result;
};
document.addEventListener('DOMContentLoaded',()=>{
  const form=document.getElementById('intakeForm');
  form?.addEventListener('input',()=>receptionIntakeDirty=true);form?.addEventListener('change',()=>receptionIntakeDirty=true);
  document.querySelectorAll('a[href="/workspace"]').forEach(link=>link.addEventListener('click',event=>{if(!canLeaveReception())event.preventDefault();}));
});
