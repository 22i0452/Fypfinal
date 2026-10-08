/* Website-wide preferences contain appearance only, never clinical content. */
window.MedFlowDisplay = (() => {
  'use strict';
  const key = 'medflow.display.v1';
  let preferences = {theme: 'dark', zoom: 100};
  let panel, trigger, returnFocus;
  const icon = name => {
    const paths = {
      display: '<rect x="3" y="4" width="18" height="13" rx="3"/><path d="M8 21h8m-4-4v4M8 8h8m-8 4h5"/>',
      sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"/>',
      moon: '<path d="M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11Z"/>',
      expand: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
      close: '<path d="m6 6 12 12M18 6 6 18"/>'
    };
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.display}</svg>`;
  };
  function normalize(value) {
    return {theme: value?.theme === 'light' ? 'light' : 'dark', zoom: Number.isFinite(Number(value?.zoom)) ? Math.max(80, Math.min(160, Math.round(Number(value.zoom) / 10) * 10)) : 100};
  }
  function load() {try {return normalize(JSON.parse(localStorage.getItem(key)));} catch {return normalize(null);}}
  function apply(save = false) {
    const root = document.documentElement;
    root.dataset.theme = preferences.theme;
    root.style.zoom = String(preferences.zoom / 100);
    const effectiveWidth = window.innerWidth / (preferences.zoom / 100);
    root.style.setProperty('--display-vh', `${window.innerHeight / (preferences.zoom / 100)}px`);
    root.dataset.displayLayout = effectiveWidth <= 700 ? 'mobile' : effectiveWidth <= 1000 ? 'compact' : 'wide';
    root.dataset.displayNarrow = String(effectiveWidth <= 360);
    if (save) {try {localStorage.setItem(key, JSON.stringify(preferences));} catch {}}
    if (panel) {
      panel.querySelectorAll('[data-theme-choice]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.themeChoice === preferences.theme)));
      panel.querySelector('#displayZoom').value = preferences.zoom;
      panel.querySelector('#displayZoomValue').value = preferences.zoom + '%';
      panel.querySelector('#displayZoomOut').disabled = preferences.zoom <= 80;
      panel.querySelector('#displayZoomIn').disabled = preferences.zoom >= 160;
    }
    window.dispatchEvent(new CustomEvent('medflow:display', {detail: {...preferences}}));
  }
  function set(value) {preferences = normalize({...preferences, ...value}); apply(true);}
  function close() {panel?.close(); trigger?.setAttribute('aria-expanded', 'false');}
  function open(opener = document.activeElement) {if (!panel || panel.open) return; returnFocus = opener; apply(); panel.showModal(); trigger.setAttribute('aria-expanded', 'true');}
  async function fullscreen() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen();
      else throw new Error('Use your browser’s full-screen controls on this device.');
      if (panel) panel.querySelector('#displayNotice').textContent = '';
    } catch (error) {if (panel) panel.querySelector('#displayNotice').textContent = error.message || 'Full screen is unavailable in this browser.';}
  }
  function init() {
    trigger = document.createElement('button');
    trigger.type = 'button'; trigger.className = 'display-trigger';
    trigger.id = 'displaySettingsButton'; trigger.setAttribute('aria-label', 'Display settings');
    trigger.setAttribute('aria-haspopup', 'dialog'); trigger.setAttribute('aria-controls', 'displaySettings'); trigger.setAttribute('aria-expanded', 'false');
    trigger.title = 'Theme, page zoom and full screen'; trigger.innerHTML = icon('display');
    let host = document.querySelector('.topbar-actions');
    if (!host && document.querySelector('.home-header')) {
      host = document.createElement('div'); host.className = 'home-header-actions';
      const account = document.querySelector('.home-header .home-account');
      document.querySelector('.home-header').append(host); if (account) host.append(account);
    }
    if (!host) {host = document.createElement('div'); host.className = 'display-floating'; document.body.append(host);}
    host.prepend(trigger);
    panel = document.createElement('dialog'); panel.id = 'displaySettings'; panel.className = 'display-panel'; panel.setAttribute('aria-labelledby', 'displayTitle');
    panel.innerHTML = `<header><div><small>YOUR VIEW</small><h2 id="displayTitle">Display</h2></div><button type="button" class="display-icon" data-display-close aria-label="Close display settings">${icon('close')}</button></header><p>Applies across Medflow.</p><div class="display-theme" role="group" aria-label="Website theme"><button type="button" data-theme-choice="dark">${icon('moon')}Dark</button><button type="button" data-theme-choice="light">${icon('sun')}Light</button></div><div class="display-zoom-heading"><label for="displayZoom">Page zoom</label><output id="displayZoomValue" for="displayZoom"></output></div><input id="displayZoom" type="range" min="80" max="160" step="10" aria-label="Page zoom"><div class="display-zoom-actions"><button type="button" id="displayZoomOut" aria-label="Zoom out">−</button><button type="button" id="displayZoomReset">Reset · 100%</button><button type="button" id="displayZoomIn" aria-label="Zoom in">+</button></div><button type="button" id="displayFullscreen" class="display-fullscreen">${icon('expand')}<span>Full screen</span></button><p id="displayNotice" role="status"></p>`;
    document.body.append(panel);
    trigger.addEventListener('click', () => {if (panel.open) return close(); open(trigger);});
    panel.addEventListener('close', () => {trigger.setAttribute('aria-expanded', 'false'); (returnFocus || trigger).focus({preventScroll: true});});
    panel.addEventListener('click', event => {
      if (event.target === panel) {const r = panel.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) close();}
      if (event.target.closest('[data-display-close]')) close();
      const theme = event.target.closest('[data-theme-choice]'); if (theme) set({theme: theme.dataset.themeChoice});
    });
    panel.querySelector('#displayZoom').addEventListener('input', event => set({zoom: Number(event.target.value)}));
    panel.querySelector('#displayZoomOut').onclick = () => set({zoom: preferences.zoom - 10});
    panel.querySelector('#displayZoomIn').onclick = () => set({zoom: preferences.zoom + 10});
    panel.querySelector('#displayZoomReset').onclick = () => set({zoom: 100});
    panel.querySelector('#displayFullscreen').onclick = fullscreen;
    if (!document.documentElement.requestFullscreen) panel.querySelector('#displayFullscreen').hidden = true;
    document.addEventListener('fullscreenchange', () => {panel.querySelector('#displayFullscreen span').textContent = document.fullscreenElement ? 'Exit full screen' : 'Full screen';});
    apply();
    if (typeof window.fetch === 'function') window.fetch('/api/demo-access').then(response => response.ok ? response.json() : null).then(config => {
      if (!config?.demo) return;
      const badge = document.createElement('small'); badge.className = 'demo-deployment-badge';
      badge.textContent = 'FYP demo · fictional patients'; document.body.append(badge);
    }).catch(() => {});
  }
  preferences = load(); apply();
  window.addEventListener('resize', () => apply());
  window.addEventListener('storage', event => {if (event.key === key) {preferences = load(); apply();}});
  document.addEventListener('DOMContentLoaded', init);
  return {set, open, fullscreen, icon, get preferences() {return {...preferences};}};
})();
