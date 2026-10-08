/* Shared calendar: date keys use the clinic timezone, never browser timezone. */
window.MedFlowCalendar=(()=>{
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function key(value,zone='Asia/Karachi'){const parts=new Intl.DateTimeFormat('en-US',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(value));const get=t=>parts.find(p=>p.type===t).value;return `${get('year')}-${get('month')}-${get('day')}`;}
 function time(value,zone='Asia/Karachi'){return new Intl.DateTimeFormat('en-US',{timeZone:zone,hour:'numeric',minute:'2-digit'}).format(new Date(value));}
 function date(value){return new Date(value+'T12:00:00Z');}
 function shift(value,months){const d=date(value);return new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+months,1)).toISOString().slice(0,10);}
 function render(root,{month,selected,today=key(new Date()),min='',max='',counts={},onDate,onMonth}){
  const start=date(month.slice(0,7)+'-01'),offset=(start.getUTCDay()+6)%7;
  const end=new Date(Date.UTC(start.getUTCFullYear(),start.getUTCMonth()+1,0)).getUTCDate();
  root.innerHTML=`<div class="calendar-toolbar"><button type="button" data-month="-1" aria-label="Previous month"><i data-lucide="chevron-left"></i></button><strong>${start.toLocaleDateString('en-US',{month:'long',year:'numeric',timeZone:'UTC'})}</strong><button type="button" data-month="1" aria-label="Next month"><i data-lucide="chevron-right"></i></button></div><div class="calendar-weekdays">${['M','T','W','T','F','S','S'].map(d=>`<span>${d}</span>`).join('')}</div><div class="calendar-days">${'<span class="calendar-gap"></span>'.repeat(offset)}${Array.from({length:end},(_,i)=>{const k=month.slice(0,7)+'-'+String(i+1).padStart(2,'0'),count=counts[k],disabled=(min&&k<min)||(max&&k>max);return `<button type="button" data-date="${k}" class="${k===selected?'selected ':''}${k===today?'today ':''}${count?'has-visits':''}" aria-label="${esc(date(k).toLocaleDateString('en-US',{dateStyle:'full',timeZone:'UTC'}))}${count?', '+count+' appointments':''}" aria-pressed="${k===selected}" ${disabled?'disabled':''}><span>${i+1}</span>${count?`<small>${count}</small>`:'<small class="calendar-dot"></small>'}</button>`;}).join('')}</div>`;
  root.querySelectorAll('[data-date]').forEach(b=>b.onclick=()=>onDate(b.dataset.date));
  root.querySelectorAll('[data-month]').forEach(b=>b.onclick=()=>onMonth(shift(month,Number(b.dataset.month))));
  window.lucide?.createIcons();
 }
 function slots(root,{rows,selected='',zone='Asia/Karachi',onSelect,loading=false}){
  root.innerHTML=loading?'<p class="calendar-empty" role="status">Checking available times…</p>':!rows.length?'<div class="calendar-empty"><i data-lucide="calendar-x-2"></i><strong>No openings on this day.</strong><span>Choose another date.</span></div>':`<div class="slot-grid">${rows.map((s,i)=>`<button type="button" data-slot="${i}" class="slot-choice ${s.start_at===selected?'selected':''}" aria-pressed="${s.start_at===selected}"><i data-lucide="clock-3"></i><strong>${esc(time(s.start_at,zone))}</strong></button>`).join('')}</div>`;
  root.querySelectorAll('[data-slot]').forEach(b=>b.onclick=()=>onSelect(rows[Number(b.dataset.slot)]));window.lucide?.createIcons();
 }
 return {esc,key,time,date,shift,render,slots};
})();
