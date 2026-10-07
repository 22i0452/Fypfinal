/* Shared structural evidence UI. Colour never represents an invented probability. */
(function(root){
  'use strict';
  const entries=new Map();let scope='',opener=null;
  const esc=value=>String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const states={received:['Received','circle-dot'],checked:['Checked','check'],review:['Review','scan-eye'],failed:['Failed','circle-alert'],missing:['Not assessed','minus']};
  const badge=(status,label)=>`<span class="evidence-badge ev-${states[status]?status:'missing'}"><span class="evidence-dot" aria-hidden="true"></span>${esc(label || states[status]?.[0] || 'Not assessed')}</span>`;
  const legend=()=>`<details class="evidence-legend"><summary><span class="evidence-dot"></span>Evidence & checks · colour key</summary><div>${Object.entries(states).map(([key,[label]])=>badge(key,label)).join('')}</div><p>Colours describe recorded checks and review states. Model confidence and clinical accuracy are not measured here.</p></details>`;
  const checks=items=>`<div class="evidence-check-list">${(items || []).map(item=>`<article class="evidence-check ev-${item.status==='passed'?'checked':item.status==='failed'?'failed':item.status==='review'?'review':'missing'}"><span class="evidence-dot" aria-hidden="true"></span><div><strong>${esc(item.label)}</strong><p>${esc(item.detail)}</p><code>${esc(item.code)} · ${esc(item.status)}</code></div></article>`).join('') || '<p class="evidence-empty">No recorded checks available.</p>'}</div>`;
  function register(key,data){entries.set(key,data);if(entries.size>256)entries.delete(entries.keys().next().value);return esc(key);}
  function close(){const dialog=document.getElementById('evidenceDialog');if(dialog?.open)dialog.close();}
  function setScope(next){if(scope!==next){scope=next;entries.clear();close();}}
  function ensureDialog(){
    let dialog=document.getElementById('evidenceDialog');if(dialog)return dialog;
    dialog=document.createElement('dialog');dialog.id='evidenceDialog';dialog.className='evidence-dialog';dialog.setAttribute('aria-label','Evidence and check details');
    dialog.addEventListener('click',e=>{if(e.target===dialog)close();if(e.target.closest('[data-evidence-close]'))close();});
    dialog.addEventListener('close',()=>opener?.focus({preventScroll:true}));document.body.append(dialog);return dialog;
  }
  function open(key){
    let data=entries.get(key);if(typeof data==='function')data=data();if(!data)return;
    opener=document.activeElement;const dialog=ensureDialog();
    dialog.innerHTML=`<header class="evidence-dialog-head"><div><span class="section-kicker">EVIDENCE INSPECTOR</span><h3>${esc(data.title || 'Inspect this result')}</h3>${badge(data.status,data.label)}</div><button type="button" class="note-action" data-evidence-close aria-label="Close evidence inspector">Close ×</button></header><p class="evidence-scope">${esc(data.scope || 'Recorded observations; review remains required.')}</p><div class="evidence-inspect-grid"><section><h4>Original → interpretation</h4>${data.raw!==undefined?`<blockquote dir="auto">${esc(data.raw || 'Original wording unavailable')}</blockquote>`:''}${data.interpretation?`<div class="evidence-interpretation" dir="auto">${esc(data.interpretation)}</div>`:''}${(data.sources || []).map(source=>`<article class="evidence-source"><div><button class="note-action" data-evidence-source="${esc(source.utterance_id)}" type="button">${esc(source.utterance_id)} · locate turn</button><small>${esc(source.speaker || '')}</small></div><blockquote dir="auto">${esc(source.original || 'Original unavailable')}</blockquote>${source.translation?`<p>${esc(source.translation)}</p>`:''}</article>`).join('')}${!data.raw && !(data.sources || []).length?'<p class="evidence-empty">No original source is available for this item.</p>':''}${data.confirmation?`<div class="evidence-confirmation">${badge('checked','Patient confirmed')}<p dir="auto">${esc(data.confirmation.raw)}</p><code>${esc(data.confirmation.source_turn_id)} · ${esc(data.confirmation.type)}</code></div>`:''}</section><section><h4>Check receipt</h4>${checks(data.checks)}</section></div>${data.revisions?.length?`<details class="evidence-revisions"><summary>${data.revisions.length} earlier interpretation(s)</summary>${data.revisions.map(item=>`<p dir="auto">${esc(item.raw)} → ${esc(item.interpretation?.en || '')}<br><code>${esc(item.source_turn_id)}</code></p>`).join('')}</details>`:''}<details class="evidence-technical"><summary>Technical record · IDs, method and scope</summary><dl>${Object.entries(data.technical || {}).map(([key,value])=>`<div><dt>${esc(key.replaceAll('_',' '))}</dt><dd>${esc(typeof value==='object'?JSON.stringify(value):value ?? 'Not available')}</dd></div>`).join('')}</dl><p>Reference integrity and exact text comparison are structural checks. Semantic correctness and calibrated model confidence are not established by these checks.</p></details>`;
    if(!dialog.open)dialog.showModal();
  }
  function marks(text,spans){
    const items=(spans || []).filter(x=>x.text && text.includes(x.text)).sort((a,b)=>text.indexOf(a.text)-text.indexOf(b.text));let cursor=0,html='';
    for(const item of items){const index=text.indexOf(item.text,cursor);if(index<cursor)continue;html+=esc(text.slice(cursor,index))+`<button type="button" class="evidence-span ev-${states[item.status]?item.status:'review'}" data-evidence-key="${esc(item.key)}" title="Inspect original and checks">${esc(item.text)}</button>`;cursor=index+item.text.length;}
    return html+esc(text.slice(cursor));
  }
  if(root.document)document.addEventListener('click',e=>{const target=e.target.closest('[data-evidence-key]');if(target){root.onEvidenceOpen?.();open(target.dataset.evidenceKey);}});
  root.MedFlowEvidence={esc,badge,legend,checks,register,setScope,open,close,marks};
  if(typeof module!=='undefined')module.exports=root.MedFlowEvidence;
})(typeof window!=='undefined'?window:globalThis);
