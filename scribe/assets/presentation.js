/* A read-only animation of returned artifacts. This module never sends requests. */
window.MedFlowPresentation = (() => {
  'use strict';
  let dialog, opener, snapshot, frame, lastTime, elapsed = 0, paused = false, selected = -1, renderedRows = -1;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const icon = name => `<i data-lucide="${escape(name || 'file-text')}" aria-hidden="true"></i>`;
  const icons = () => window.lucide?.createIcons();
  function ensure() {
    if (dialog) return;
    dialog = document.createElement('dialog'); dialog.id = 'resultPresentation'; dialog.className = 'result-presentation';
    dialog.setAttribute('aria-labelledby', 'presentationTitle');
    dialog.innerHTML = `<header class="presentation-header"><div><span class="presentation-eyebrow">RESULT PLAYBACK</span><h2 id="presentationTitle"></h2><p id="presentationReceipt"></p></div><div class="presentation-header-actions"><button type="button" class="presentation-button" data-presentation-expand aria-label="Expand result playback" aria-pressed="false">${icon('expand')}</button><button type="button" class="presentation-button" data-presentation-close aria-label="Close result playback">${icon('x')}</button></div></header><div class="presentation-body"><nav class="presentation-timeline" aria-label="Playback stages"></nav><div class="presentation-stage"><aside class="presentation-source"><span class="presentation-eyebrow">RETURNED SOURCE</span><h3 id="presentationSourceTitle"></h3><div id="presentationSources"></div></aside><div class="presentation-motion" aria-hidden="true"><svg class="presentation-threads" viewBox="0 0 200 400" preserveAspectRatio="none"><path d="M0 50C110 50 0 200 100 200S90 50 200 50"/><path d="M0 150C80 150 30 200 100 200S120 150 200 150"/><path d="M0 250C80 250 30 200 100 200S120 250 200 250"/><path d="M0 350C110 350 0 200 100 200S90 350 200 350"/></svg><div class="presentation-orbit"><span></span><div id="presentationGlyph"></div></div><small id="presentationMotionLabel"></small></div><section class="presentation-output" aria-labelledby="presentationStageTitle"><div class="presentation-output-head"><span class="presentation-eyebrow" id="presentationStep"></span><span class="presentation-measured" id="presentationMeasured"></span></div><h3 id="presentationStageTitle"></h3><p id="presentationStageDetail"></p><div id="presentationResults"></div></section></div><div class="presentation-destinations" aria-label="Result destinations"></div></div><footer class="presentation-footer"><div class="presentation-playback-progress" role="progressbar" aria-label="Presentation playback progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span></span></div><div class="presentation-playback-controls"><span id="presentationStatus" role="status" aria-live="polite"></span><div><button type="button" class="presentation-button" data-presentation-pause></button><button type="button" class="presentation-button" data-presentation-skip>${icon('skip-forward')}Skip</button><button type="button" class="presentation-button" data-presentation-replay>${icon('rotate-ccw')}Replay</button></div></div><p>Animated reveal of returned results. Records are already saved where stated; playback adds no API calls. Source links and clinical correctness are separate.</p></footer>`;
    document.body.append(dialog);
    const display = document.createElement('button'); display.type = 'button'; display.className = 'presentation-button'; display.setAttribute('aria-label', 'Display settings for website'); display.innerHTML = MedFlowDisplay.icon('display'); display.onclick = () => MedFlowDisplay.open(display); dialog.querySelector('.presentation-header-actions').prepend(display);
    dialog.addEventListener('click', event => {
      if (event.target.closest('[data-presentation-close]')) close();
      if (event.target.closest('[data-presentation-expand]')) {
        const expanded = dialog.classList.toggle('presentation-expanded');
        const button = dialog.querySelector('[data-presentation-expand]');
        button.setAttribute('aria-pressed', String(expanded)); button.setAttribute('aria-label', expanded ? 'Restore result playback size' : 'Expand result playback');
      }
      if (event.target.closest('[data-presentation-pause]')) {paused = !paused; lastTime = performance.now(); controls(); schedule();}
      if (event.target.closest('[data-presentation-skip]')) {elapsed = duration(); paused = true; render();}
      if (event.target.closest('[data-presentation-replay]')) replay();
      const stage = event.target.closest('[data-presentation-stage]');
      if (stage) {elapsed = Number(stage.dataset.presentationStage) * duration() / snapshot.stages.length; paused = true; render(true);}
    });
    dialog.addEventListener('close', () => {cancelAnimationFrame(frame); frame = null; snapshot = null; dialog.querySelector('#presentationSources').replaceChildren(); dialog.querySelector('#presentationResults').replaceChildren(); dialog.querySelector('.presentation-destinations').replaceChildren(); opener?.focus({preventScroll:true});});
  }
  function duration() {return snapshot?.duration || 12000;}
  function open(payload) {
    if (!payload?.stages?.length) return false;
    ensure(); if (dialog.open) return false; opener = document.activeElement;
    // Freeze the displayed run/version; later application updates cannot alter it.
    snapshot = JSON.parse(JSON.stringify(payload));
    snapshot.duration = Math.max(10000, Math.min(15000, Number(snapshot.duration) || 12000));
    elapsed = reduced.matches ? duration() : 0; paused = reduced.matches; selected = -1; renderedRows = -1;
    dialog.classList.remove('presentation-expanded'); dialog.querySelector('[data-presentation-expand]').setAttribute('aria-pressed', 'false'); dialog.querySelector('[data-presentation-expand]').setAttribute('aria-label', 'Expand result playback');
    dialog.querySelector('#presentationTitle').textContent = snapshot.title || 'The result, in motion.';
    dialog.querySelector('#presentationReceipt').textContent = snapshot.receipt || '';
    dialog.querySelector('#presentationSourceTitle').textContent = snapshot.sourceTitle || 'Conversation';
    dialog.querySelector('#presentationSources').innerHTML = (snapshot.sources || []).map(row => `<article class="presentation-source-row" data-presentation-source="${escape(row.id)}"><small>${escape(row.label || row.id)}</small><p dir="auto">${escape(row.text)}</p></article>`).join('') || '<p class="presentation-empty">No source content attached to this result.</p>';
    dialog.querySelector('.presentation-timeline').innerHTML = snapshot.stages.map((stage, i) => `<button type="button" data-presentation-stage="${i}" aria-label="Show ${escape(stage.title)}"><span>${icon(stage.icon)}</span><strong>${escape(stage.label || stage.title)}</strong></button>`).join('');
    dialog.showModal(); render(); lastTime = performance.now(); schedule(); return true;
  }
  function controls() {
    if (!snapshot) return;
    const done = elapsed >= duration();
    const button = dialog.querySelector('[data-presentation-pause]');
    button.innerHTML = icon(paused ? 'play' : 'pause') + (paused ? 'Continue' : 'Pause'); button.disabled = done;
    dialog.querySelector('[data-presentation-skip]').disabled = done;
    dialog.querySelector('#presentationStatus').textContent = done ? 'Playback complete · results available for review' : paused ? 'Playback paused' : `Revealing returned results · ${(duration()/1000).toFixed(0)}s sequence`;
    dialog.classList.toggle('playback-paused', paused || done); icons();
  }
  function rowHtml(row, animate) {
    const tone = ['checked','review','failed'].includes(row.tone) ? row.tone : 'received';
    return `<article class="presentation-result-row ${animate ? 'result-arrives' : ''}" data-tone="${tone}"><div>${row.label ? `<small>${escape(row.label)}</small>` : ''}${row.badge ? `<span class="presentation-result-badge">${escape(row.badge)}</span>` : ''}</div><p dir="auto">${escape(row.text)}</p>${row.sourceIds?.length ? `<span class="presentation-source-ids">${icon('git-branch')}${row.sourceIds.map(escape).join(' · ')}</span>` : ''}</article>`;
  }
  function render(inspect = false) {
    if (!snapshot) return;
    const count = snapshot.stages.length, segment = duration() / count, done = elapsed >= duration();
    const index = Math.min(count - 1, Math.floor(elapsed / segment)), stage = snapshot.stages[index];
    const fraction = done || inspect ? 1 : (elapsed % segment) / segment;
    const rows = stage.rows || [], visible = done || inspect ? rows.length : Math.min(rows.length, Math.max(1, Math.ceil(fraction * rows.length)));
    const stageChanged = selected !== index;
    if (stageChanged) {
      selected = index; renderedRows = -1;
      dialog.querySelector('#presentationStep').textContent = `${String(index+1).padStart(2,'0')} / ${String(count).padStart(2,'0')}`;
      dialog.querySelector('#presentationStageTitle').textContent = stage.title;
      dialog.querySelector('#presentationStageDetail').textContent = stage.detail || '';
      dialog.querySelector('#presentationGlyph').innerHTML = icon(stage.icon);
      dialog.querySelector('#presentationMotionLabel').textContent = stage.label || stage.title;
      dialog.querySelector('#presentationMeasured').textContent = Number.isFinite(stage.measuredMs) ? `${(stage.measuredMs / 1000).toFixed(2)}s actual operation` : '';
      dialog.querySelectorAll('[data-presentation-stage]').forEach((button, i) => {button.classList.toggle('active', i === index); button.classList.toggle('revealed', i < index || done); button.setAttribute('aria-current', i === index ? 'step' : 'false');});
    }
    if (visible !== renderedRows || stageChanged || inspect) {
      const results = dialog.querySelector('#presentationResults');
      if (stageChanged || inspect || visible < renderedRows) results.replaceChildren();
      const start = stageChanged || inspect || visible < renderedRows ? 0 : renderedRows;
      for (let i = start; i < visible; i++) results.insertAdjacentHTML('beforeend', rowHtml(rows[i], !reduced.matches && !inspect));
      if (!rows.length) results.innerHTML = '<p class="presentation-empty">No output recorded for this stage.</p>';
      renderedRows = visible;
      const references = new Set([...(stage.sourceIds || []), ...rows.slice(0,visible).flatMap(row => row.sourceIds || [])]);
      dialog.querySelectorAll('[data-presentation-source]').forEach(node => node.classList.toggle('source-connected', references.has(node.dataset.presentationSource)));
      dialog.querySelector('.presentation-destinations').innerHTML = snapshot.stages.map((item, i) => `<div class="${i <= index ? 'destination-revealed' : ''} ${i === index ? 'destination-active' : ''}">${icon(item.icon)}<span>${escape(item.label || item.title)}</span>${i <= index ? '<small>Returned</small>' : '<small>Upcoming reveal</small>'}</div>`).join('');
      icons();
    }
    const progress = Math.round(elapsed / duration() * 100);
    const bar = dialog.querySelector('.presentation-playback-progress'); bar.setAttribute('aria-valuenow', progress); bar.firstElementChild.style.width = progress + '%';
    if (stageChanged || done || inspect) controls();
  }
  function tick(now) {
    frame = null; if (!dialog?.open || !snapshot || paused || elapsed >= duration()) return;
    elapsed = Math.min(duration(), elapsed + Math.max(0, now - lastTime)); lastTime = now; render(); schedule();
  }
  function schedule() {if (!frame && snapshot && dialog.open && !paused && elapsed < duration()) frame = requestAnimationFrame(tick);}
  function replay() {if (!snapshot) return; elapsed = reduced.matches ? duration() : 0; paused = reduced.matches; selected = -1; renderedRows = -1; lastTime = performance.now(); render(); schedule();}
  function close() {dialog?.close();}
  document.addEventListener('visibilitychange', () => {if (document.hidden && dialog?.open && snapshot && elapsed < duration()) {paused = true; cancelAnimationFrame(frame); frame = null; controls();}});
  reduced.addEventListener('change', () => {if (reduced.matches && dialog?.open && snapshot) {elapsed = duration(); paused = true; render();}});
  return {open, close, escape};
})();
