/* Local Lucide assets: no CDN, no runtime network dependency. */
(()=>{
  let scheduled=false;
  const compact={'View source':'quote','Edit section':'pencil','Copy':'copy','Copy note':'copy','Download':'download','Print':'printer','Clear':'eraser','Refresh slots':'refresh-cw'};
  const labelled={'Generate':'sparkles','Regenerate':'refresh-cw','Submit for review':'file-check','Resume review':'file-pen-line','Open visit':'arrow-up-right','Record choices':'shield-check','Update choices':'shield-check','Mic':'mic','Send':'arrow-up-right','End demo':'phone-off','New session':'plus'};
  function enhance(){
    scheduled=false;
    document.querySelectorAll('button.note-action,button.toolbar-btn').forEach(button=>{
      button.dataset.iconReady='true';
      if(button.querySelector('svg,[data-lucide]'))return;
      const label=button.textContent.trim(),name=compact[label] || labelled[label];if(!name)return;
      const i=document.createElement('i');i.dataset.lucide=name;i.setAttribute('aria-hidden','true');
      if(compact[label]){button.textContent='';button.append(i);button.classList.add('icon-action');button.setAttribute('aria-label',label);button.title=label;}
      else button.prepend(i);
    });
    document.querySelectorAll('button.nav-item,a.nav-item').forEach(button=>{if(!button.getAttribute('aria-label'))button.setAttribute('aria-label',button.textContent.trim());if(!button.title)button.title=button.textContent.trim();});
    if(window.lucide && document.querySelector('i[data-lucide]'))lucide.createIcons({attrs:{'stroke-width':1.5}});
  }
  function queue(){if(scheduled)return;scheduled=true;requestAnimationFrame(enhance);}
  document.addEventListener('DOMContentLoaded',()=>{enhance();new MutationObserver(queue).observe(document.body,{childList:true,subtree:true});});
})();
