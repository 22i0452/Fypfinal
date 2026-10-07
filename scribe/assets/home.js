document.addEventListener('DOMContentLoaded',async()=>{
  window.lucide?.createIcons({attrs:{'stroke-width':1.35}});
  try{
    const response=await fetch('/api/auth/me',{credentials:'same-origin'});
    if(response.ok){document.querySelector('#homeAccount span').textContent='Continue to workspace';document.getElementById('homeAccount').setAttribute('aria-label','Continue to your signed-in doctor workspace');}
  }catch{/* The public entry points remain usable when the session check is unavailable. */}
});
