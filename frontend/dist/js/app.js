import {state, need, invalidate, bus, toast, modal, closeModal, formError, $, $$, api, isOwner, value} from './core.js';
import {t, initLang, setLang, LANGS, lang, relative, region, when} from './i18n.js';
import {esc, icons, options, field, empty, panel} from './ui.js';
import {field as dotField, transition, reveal, interactive, countUp, swipe, progress, reduced} from './motion.js';
import {view as overview} from './views/overview.js';
import {view as agent, send as sendChat, paint as paintChat} from './views/agent.js';
import {view as sendView, enableNotifications} from './views/send.js';
import {view as payments, openDetail} from './views/payments.js';
import {view as markets} from './views/markets.js';
import {view as plans} from './views/plans.js';
import {view as habits} from './views/habits.js';
import {view as wallets, recipientForm} from './views/wallets.js';
import {view as autonomy} from './views/autonomy.js';
import {view as routes} from './views/routes.js';
import {view as audit} from './views/audit.js';
import {view as memory} from './views/memory.js';
import {view as spending} from './views/spending.js';
import {view as study} from './views/study.js';

const VIEWS = [overview, agent, sendView, spending, payments, markets, plans, study, habits, wallets, autonomy, memory, routes, audit];
const BY_ID = Object.fromEntries(VIEWS.map(v => [v.id, v]));
const GROUPS = [['nav.g_work', ['overview', 'agent', 'send', 'spending', 'payments']], ['nav.g_insight', ['markets', 'plans', 'study', 'habits']], ['nav.g_control', ['wallets', 'autonomy', 'memory', 'routes', 'audit']]];
const DOCK = ['overview', 'agent', 'send', 'payments'];
const ORDER = GROUPS.flatMap(g => g[1]);
let pendingPaint = false, refreshTimer = 0, events = null;

/* ---------- shell ---------- */
function shellText() {
  $$('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  $$('[data-i18n-label]').forEach(el => el.setAttribute('aria-label', t(el.dataset.i18nLabel)));
  $('#nav').innerHTML = GROUPS.map(([g, ids]) => `<div class="nav-group"><span class="nav-caption">${t(g)}</span>${ids.map(id => `<a href="#${id}" data-view="${id}" class="${state.view === id ? 'active' : ''}">${icons[id]}<span>${t('nav.' + id)}</span><b>${String(ORDER.indexOf(id) + 1).padStart(2, '0')}</b></a>`).join('')}</div>`).join('');
  $('#dock').innerHTML = DOCK.map(id => `<a href="#${id}" data-view="${id}" class="${state.view === id ? 'active' : ''}">${icons[id]}<span>${t('nav.' + id)}</span></a>`).join('') +
    `<button data-action="open-sheet" class="${DOCK.includes(state.view) ? '' : 'active'}">${icons.more}<span>${t('nav.more')}</span></button>`;
  $('#lang-select').innerHTML = LANGS.map(([c, n]) => `<option value="${c}" ${c === lang ? 'selected' : ''}>${n}</option>`).join('');
  $('#crumb').textContent = t('nav.' + state.view);
  document.title = `${t('nav.' + state.view)} · DOT`;
  status();
}

function status() {
  const h = state.health;
  const badge = $('#env-badge');
  badge.className = 'env-badge ' + (state.connected ? 'ok' : 'off');
  badge.querySelector('span').textContent = state.connected ? t('env.sandbox') : t('shell.offline');
  $('#side-status').textContent = state.connected ? t('shell.connected') : t('shell.disconnected');
  $('#avatar').textContent = state.role ? state.role[0].toUpperCase() : '·';
  const count = (state.data.reminders || []).length;
  $('#bell-count').hidden = !count; $('#bell-count').textContent = count;
  notifyNew(state.data.reminders);
  $('#sync').textContent = state.connected ? t('shell.synced', {at: new Date().toLocaleTimeString(lang, {hour12: false})}) : '';
}

function heading(id) {
  return `<div class="page-head reveal"><div><span class="eyebrow">${String(ORDER.indexOf(id) + 1).padStart(2, '0')} / ${esc(t('nav.' + id)).toUpperCase()}</span><h1>${t('page.' + id)}<i>.</i></h1><p>${t('page.' + id + '_d')}</p></div>
    ${id === 'overview' ? `<div class="head-actions"><button class="button ghost" data-action="go" data-view="agent">${icons.agent}${t('overview.ask')}</button><button class="button primary magnetic" data-action="go" data-view="send">${icons.plus}${t('action.new_transfer')}</button></div>` : ''}</div>`;
}

export function enhance(root, quiet = false) {
  if (quiet) root.querySelectorAll('.reveal').forEach(el => el.classList.add('in'));
  reveal(root); interactive(root);
  if (!quiet) countUp(root, (n, d) => new Intl.NumberFormat(lang, {minimumFractionDigits: d, maximumFractionDigits: d}).format(n));
}
bus.enhance = enhance;

/** quiet: a data refresh of the page already on screen; entrance animations must not replay. */
function paint(quiet = false) {
  const v = BY_ID[state.view], root = $('#view'), html = document.documentElement;
  pendingPaint = false;
  if (quiet) html.dataset.quiet = '1';
  if (!state.role) root.innerHTML = heading(state.view) + loginPanel();
  else root.innerHTML = heading(state.view) + v.render();
  enhance(root, quiet);
  if (state.role) v.mount?.(root);
  status();
  if (quiet) requestAnimationFrame(() => requestAnimationFrame(() => { delete html.dataset.quiet; }));
}

const editing = () => document.activeElement?.closest?.('#view') && document.activeElement.matches('input:not([type=checkbox]):not([type=range]),textarea,select');

function render() {
  // Never rebuild the page under a streaming answer or while the user types; catch up afterwards.
  if (editing() || (state.chat.streaming && ['agent', 'overview'].includes(state.view))) { pendingPaint = true; return; }
  const y = scrollY;
  paint(true);
  scrollTo(0, y);
}
bus.render = render;
bus.flush = () => { if (pendingPaint) render(); };
// After an explicit user action the page must update even if a field keeps focus; restore that focus afterwards.
bus.repaint = () => { const id = document.activeElement?.id, y = scrollY; paint(true); scrollTo(0, y); if (id) document.getElementById(id)?.focus({preventScroll: true}); };

async function show(id, mode = 'forward') {
  const v = BY_ID[id] ? id : 'overview';
  const changed = v !== state.view;
  state.view = v;
  shellText();
  closeSheets();
  let done = false;
  const work = Promise.all([need(BY_ID[v].needs), BY_ID[v].load?.()]).catch(() => {}).then(() => { done = true; });
  if (!changed) { await work; paint(true); return; }
  // Cached data renders at once; otherwise wait briefly so the transition shows a complete page.
  await Promise.race([work, new Promise(r => setTimeout(r, 450))]);
  const complete = done;
  await transition(async () => { paint(); scrollTo(0, 0); }, mode);
  if (complete) return;
  await work;
  if (state.view === v && !editing()) { const y = scrollY; paint(true); scrollTo(0, y); }
}
bus.go = id => { location.hash = id; };
bus.refresh = async () => { const v = BY_ID[state.view]; await Promise.all([need(v.needs), v.load?.()]); render(); };

async function refresh(force = false) {
  if (!state.role) return;
  invalidate();
  const v = BY_ID[state.view];
  try {
    await Promise.all([need([...v.needs, 'reminders'], force), v.load?.()]);
    state.connected = true;
  } catch { state.connected = false; }
  if (!$('#modal').open || force) render(); else pendingPaint = true;
  status();
}

/* ---------- live updates ---------- */
function connectEvents() {
  events?.close();
  if (!('EventSource' in window) || !state.role) return;
  events = new EventSource('/api/events');
  events.onmessage = e => {
    const data = JSON.parse(e.data);
    if (data.version === state.version) return;
    const first = !state.version;
    state.version = data.version;
    if (first) return;
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(async () => {
      await refresh();
      // Live-update an open payment only while its outcome is pending; never re-render a draft under review.
      const waiting = $('#modal').open && $('#modal-body .detail-top') && $('#modal-body [data-action="reconcile"]');
      if (waiting) openDetail(waiting.dataset.id);
    }, 350);
  };
  events.onerror = () => { state.connected = false; status(); };
  events.onopen = () => { state.connected = true; status(); };
}

/* ---------- session ---------- */
function loginPanel() {
  return panel(t('login.title'), `<form id="login-form" class="form-block"><p class="intro">${t('login.intro')}</p>
    ${field('access-token', t('login.token'), `<input id="access-token" type="password" name="token" required minlength="24" autocomplete="off" placeholder="Owner / Agent / Viewer">`)}
    <div class="form-error"></div><button class="button primary">${t('login.connect')}</button></form>`, {cls: 'login-panel'});
}

async function session() {
  try {
    const s = await api('/session');
    Object.assign(state, {role: s.role, model: s.model_configured, modelName: s.model});
  } catch {
    if (state.health?.demo_login) {
      await api('/session/demo', 'POST', {});
      const s = await api('/session');
      Object.assign(state, {role: s.role, model: s.model_configured, modelName: s.model});
    }
  }
}

async function settingsModal() {
  if (state.role) await need(['memory', 'economies']);
  const m = state.data.memory || {};
  const theme = document.documentElement.dataset.theme;
  const zones = ['UTC', 'Australia/Sydney', 'Asia/Shanghai', 'Asia/Taipei', 'Asia/Hong_Kong', 'Asia/Ho_Chi_Minh', 'Asia/Tokyo', 'Asia/Seoul', 'Asia/Singapore', 'Asia/Manila', 'America/Los_Angeles', 'America/New_York', 'Pacific/Auckland'];
  const econ = (state.data.economies || []).map(e => [e.code, region(e.code)]);
  modal(t('settings.title'), `
    <section class="settings-sec"><span class="eyebrow">${t('settings.display')}</span>
      <div class="grid-2">${field('set-lang', t('settings.language'), `<select id="set-lang">${options(LANGS, lang)}</select>`)}
      ${field('set-theme', t('settings.theme'), `<select id="set-theme">${options([['light', t('settings.light')], ['dark', t('settings.dark')]], theme)}</select>`)}</div></section>
    <form id="settings-form" class="settings-sec"><span class="eyebrow">${t('settings.preferences')}</span><p class="fine">${t('settings.pref_note')}</p>
      <div class="grid-2">${field('set-home', t('settings.home_region'), `<select id="set-home" name="home_region"><option value="">—</option>${options(econ, m.home_region)}</select>`)}
      ${field('set-recv', t('settings.receive_region'), `<select id="set-recv" name="receive_region"><option value="">—</option>${options(econ, m.receive_region)}</select>`)}
      ${field('set-cur', t('settings.display_currency'), `<select id="set-cur" name="display_currency">${options(['AUD', 'USD', 'CNY', 'EUR', 'JPY', 'VND'].map(c => [c, c]), m.display_currency || state.display)}</select>`)}
      ${field('set-tz', t('settings.time_zone'), `<select id="set-tz" name="time_zone">${options(zones.map(z => [z, z]), m.time_zone || 'UTC')}</select>`)}</div>
      ${field('set-goal', t('settings.payment_goal'), `<input id="set-goal" name="payment_goal" maxlength="200" value="${esc(m.payment_goal || '')}">`)}
      <div class="form-error"></div><button class="button" ${isOwner() ? '' : 'disabled'}>${t('common.save')}</button></form>
    <section class="settings-sec"><span class="eyebrow">${t('settings.session')}</span>
      <dl class="facts"><div><dt>${t('settings.role')}</dt><dd>${esc(state.role ? t('role.' + state.role) : '—')}</dd></div><div><dt>${t('settings.model')}</dt><dd>${state.model ? esc(state.modelName || t('agent.mode.model')) : t('settings.model_off')}</dd></div>
      <div><dt>${t('settings.rails')}</dt><dd>${t('env.sandbox')}</dd></div></dl>
      <label class="check-label"><input type="checkbox" id="set-notify" ${localStorage.getItem('dot.notify') === '1' ? 'checked' : ''}> ${t('rem.notify')}</label>
      <form id="login-form" class="inline-form">${field('access-token-2', t('login.switch'), `<input id="access-token-2" type="password" name="token" minlength="24" autocomplete="off" required>`)}<div class="form-error"></div>
      <div class="row-actions"><button class="button">${t('login.connect')}</button>${state.role ? `<button type="button" class="button ghost" data-action="logout">${t('login.logout')}</button>` : ''}</div></form></section>`, 'SETTINGS', {mount: root => {
    root.querySelector('#set-lang').addEventListener('change', e => changeLang(e.target.value));
    root.querySelector('#set-theme').addEventListener('change', e => setTheme(e.target.value));
    root.querySelector('#set-notify').addEventListener('change', async e => { if (e.target.checked) e.target.checked = await enableNotifications(); else localStorage.setItem('dot.notify', '0'); });
  }});
}

/* Browser notifications for reminders that appeared since the last look (opt-in, per browser). */
function notifyNew(list) {
  if (!Array.isArray(list)) return;
  let seen = null;
  try { seen = JSON.parse(localStorage.getItem('dot.seenReminders') || 'null'); } catch { /* storage blocked */ }
  const ids = list.map(r => r.id);
  try { localStorage.setItem('dot.seenReminders', JSON.stringify(ids.slice(0, 200))); } catch { /* storage blocked */ }
  if (!seen) return;  // first visit: remember what exists, announce nothing
  let on = false;
  try { on = localStorage.getItem('dot.notify') === '1' && 'Notification' in window && Notification.permission === 'granted'; } catch { /* ignore */ }
  if (!on) return;
  for (const r of list.filter(x => !seen.includes(x.id)).slice(0, 3)) {
    try { const n = new Notification('DOT · ' + t('shell.reminders'), {body: t('reminder.' + r.kind, r.data), tag: 'dot-' + r.id}); n.onclick = () => { window.focus(); location.hash = REMINDER_VIEW[r.kind] || 'overview'; }; } catch { /* unsupported */ }
  }
}
const REMINDER_VIEW = {rate_target: 'send', rate_favorable: 'send', exchange_due: 'send', expense_expected: 'spending', scholarship_due: 'study', tuition_due: 'study', goal_deadline: 'plans', obligation_due_soon: 'habits', obligation_overdue: 'habits'};

function drawer() {
  const list = state.data.reminders || [];
  $('#drawer-panel').innerHTML = `<header><span class="eyebrow">${t('shell.reminders')}</span><button class="icon-button" data-action="close-drawer" aria-label="${t('common.close')}">×</button></header>
    ${list.length ? `<ul class="reminders">${list.map(r => `<li class="sev-${esc(r.severity)}"><span class="pulse"></span><div><p>${esc(t('reminder.' + r.kind, r.data))}</p><small>${when(r.created)}</small></div>
      <div class="row-actions">${['quote_expired', 'quote_expiring', 'unresolved', 'insufficient_funds'].includes(r.kind) ? `<button class="link sm" data-action="detail" data-id="${esc(r.ref)}">${t('agent.view')}</button>` : r.kind.startsWith('goal') ? `<button class="link sm" data-action="go" data-view="plans">${t('common.open')}</button>` : r.kind.startsWith('obligation') ? `<button class="link sm" data-action="go" data-view="habits">${t('common.open')}</button>` : REMINDER_VIEW[r.kind] ? `<button class="link sm" data-action="go" data-view="${REMINDER_VIEW[r.kind]}">${t('common.open')}</button>` : ''}
      <button class="x" data-action="dismiss" data-id="${r.id}" aria-label="${t('common.dismiss')}">×</button></div></li>`).join('')}</ul>` : empty(t('reminder.none'))}
    <p class="fine">${t('reminder.note')}</p>`;
}

function openDrawer() { drawer(); $('#drawer').hidden = false; requestAnimationFrame(() => $('#drawer').classList.add('open')); }
function closeSheets() {
  for (const id of ['#drawer', '#sheet']) {
    const el = $(id);
    if (el.hidden) continue;
    el.classList.remove('open');
    setTimeout(() => { el.hidden = true; }, reduced() ? 0 : 280);
  }
}
function openSheet() {
  $('#sheet-panel').innerHTML = `<span class="sheet-grip"></span>${GROUPS.map(([g, ids]) => `<span class="nav-caption">${t(g)}</span><div class="sheet-grid">${ids.map(id => `<a href="#${id}" class="${state.view === id ? 'active' : ''}">${icons[id]}<span>${t('nav.' + id)}</span></a>`).join('')}</div>`).join('')}`;
  $('#sheet').hidden = false; requestAnimationFrame(() => $('#sheet').classList.add('open'));
}

async function changeLang(code) {
  await setLang(code);
  if (isOwner()) api('/memory', 'PUT', {key: 'language', value: code}).catch(() => {});
  shellText();
  await transition(async () => { paint(); }, 'forward');
  if ($('#modal').open && $('#settings-form')) settingsModal();
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('dot.theme', theme); } catch {}
  document.querySelector('meta[name=theme-color]').content = theme === 'dark' ? '#0b0b0b' : '#f5f5f2';
}

/* ---------- delegation ---------- */
const GLOBAL = {
  go(el) { location.hash = el.dataset.view; },
  detail(el) { return openDetail(el.dataset.id); },
  prompt(el) { if (state.view !== 'agent' && state.view !== 'overview') location.hash = 'agent'; return sendChat(el.dataset.prompt); },
  async dismiss(el) { await api(`/reminders/${el.dataset.id}/dismiss`, 'POST', {}); invalidate(['reminders']); await need(['reminders']); drawer(); render(); status(); },
  'new-recipient'(el) { return wallets.actions['new-recipient'](el); },
  copy(el) { return wallets.actions.copy(el); },
  'open-sheet': openSheet,
  'close-drawer': closeSheets,
  async logout() {
    await api('/session', 'DELETE');
    Object.assign(state, {role: null, data: {}, connected: false});
    events?.close(); closeModal(); shellText(); paint(); toast(t('login.logged_out'));
  },
};

document.addEventListener('click', async e => {
  const el = e.target.closest('[data-action]');
  if (!el || el.disabled) return;
  const action = el.dataset.action;
  const handler = BY_ID[state.view]?.actions?.[action] || GLOBAL[action] || VIEWS.map(v => v.actions?.[action]).find(Boolean);
  if (!handler) return;
  e.preventDefault();
  const async = handler.constructor.name === 'AsyncFunction';
  if (async) el.disabled = true;
  try { await handler(el, e); }
  catch (error) { formError(el.closest('form') || ($('#modal').open ? $('#modal-body') : null), error); }
  finally { if (async) el.disabled = false; }
});

document.addEventListener('submit', async e => {
  const f = e.target;
  e.preventDefault();
  if (f.dataset.chat !== undefined) { const ta = f.querySelector('textarea'); const text = ta.value; ta.value = ''; return sendChat(text); }
  const key = f.dataset.form || f.id;
  const handler = key === 'login-form' ? login : key === 'settings-form' ? savePrefs : VIEWS.map(v => v.submit?.[key]).find(Boolean);
  if (!handler) return;
  const button = f.querySelector('button:not([type=button])');
  if (button) button.disabled = true;
  try { await handler(f); }
  catch (error) { formError(f, error); }
  finally { if (button?.isConnected) button.disabled = false; }
});

async function login(f) {
  const s = await api('/session', 'POST', {token: value(f, 'token')});
  const current = await api('/session');
  Object.assign(state, {role: s.role, model: current.model_configured, modelName: current.model, data: {}});
  closeModal(); connectEvents(); await show(state.view); toast(t('login.connected'), 'good');
}

async function savePrefs(f) {
  for (const [key, v] of new FormData(f)) {
    if ((state.data.memory || {})[key] !== v && !(v === '' && !(key in (state.data.memory || {})))) await api('/memory', 'PUT', {key, value: String(v)});
  }
  state.display = value(f, 'display_currency') || state.display;
  invalidate(['memory', 'equivalents']); await need(['memory']);
  toast(t('settings.saved'), 'good');
}

document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.target.matches?.('tr[data-action]')) { e.preventDefault(); e.target.click(); }
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.target.matches?.('[data-chat] textarea')) { e.preventDefault(); e.target.form.requestSubmit(); }
  if (e.key === 'Escape') closeSheets();
});
document.addEventListener('input', e => {
  if (e.target.matches?.('[data-chat] textarea')) { e.target.style.height = 'auto'; e.target.style.height = Math.min(160, e.target.scrollHeight) + 'px'; }
});
document.addEventListener('focusout', () => setTimeout(() => { if (pendingPaint && !editing()) render(); }, 250));

/* ---------- boot ---------- */
async function boot() {
  let theme = 'light';
  try { theme = localStorage.getItem('dot.theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); } catch {}
  setTheme(theme);
  let hadLang = null;
  try { hadLang = localStorage.getItem('dot.lang'); } catch {}
  await initLang();
  dotField($('#field'));
  progress($('#progress'));
  const intro = $('#intro');
  if (reduced() || sessionStorage.getItem('dot.intro')) intro.remove();
  else { sessionStorage.setItem('dot.intro', '1'); intro.classList.add('play'); setTimeout(() => intro.remove(), 1500); }
  state.view = BY_ID[location.hash.slice(1)] ? location.hash.slice(1) : 'overview';
  shellText();
  $('#view').innerHTML = heading(state.view) + `<div class="skeleton reveal in"><i></i><i></i><i></i></div>`;
  try {
    state.health = await api('/health');
    state.connected = true;
    await session();
  } catch {
    state.connected = false;
    $('#banner').textContent = t('err.backend'); $('#banner').hidden = false;
  }
  status();
  if (state.role) {
    connectEvents();
    need(['reminders', 'memory', 'economies']).then(() => {
      const m = state.data.memory || {};
      if (m.display_currency) state.display = m.display_currency;
      if (!hadLang && m.language && m.language !== lang) changeLang(m.language);
      status();
    });
  }
  await show(state.view);
  swipe($('#main'), dir => {
    const i = ORDER.indexOf(state.view), next = ORDER[(i + (dir === 'left' ? 1 : -1) + ORDER.length) % ORDER.length];
    swipeMode = dir; location.hash = next;
  });
  setInterval(() => {
    $$('[data-countdown]').forEach(el => {
      const s = Number(el.dataset.countdown);
      el.textContent = s * 1000 > Date.now() ? relative(s) : t('detail.expired');
    });
  }, 1000);
  setInterval(() => { if (!document.hidden && (!events || events.readyState !== 1)) refresh(); }, 20000);
}

let swipeMode = null;
addEventListener('hashchange', () => {
  const next = location.hash.slice(1);
  const mode = swipeMode || (ORDER.indexOf(next) >= ORDER.indexOf(state.view) ? 'forward' : 'back');
  swipeMode = null;
  show(next, mode);
});
$('#modal-close').addEventListener('click', closeModal);
$('#modal').addEventListener('click', e => { if (e.target === $('#modal')) closeModal(); });
$('#modal').addEventListener('close', () => { if (pendingPaint) render(); });
$('#account').addEventListener('click', () => settingsModal());
$('#bell').addEventListener('click', openDrawer);
$('#drawer').addEventListener('click', e => { if (e.target === $('#drawer')) closeSheets(); });
$('#sheet').addEventListener('click', e => { if (e.target === $('#sheet') || e.target.closest('a')) closeSheets(); });
$('#refresh').addEventListener('click', async () => { $('#refresh').classList.add('spin'); await refresh(true); setTimeout(() => $('#refresh').classList.remove('spin'), 600); toast(t('shell.refreshed')); });
$('#theme-toggle').addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  if (document.startViewTransition && !reduced()) document.startViewTransition(() => setTheme(next)); else setTheme(next);
});
$('#lang-select').addEventListener('change', e => changeLang(e.target.value));
boot();
