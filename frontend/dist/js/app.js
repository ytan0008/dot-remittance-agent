import {state, need, invalidate, bus, toast, modal, closeModal, formError, $, $$, api, isOwner, value} from './core.js';
import {t, initLang, setLang, LANGS, lang, relative, region, when} from './i18n.js';
import {esc, icons, options, field, empty, panel} from './ui.js';
import {authScreen} from './auth.js';
import {field as dotField, transition, reveal, interactive, countUp, swipe, progress, reduced} from './motion.js';
import {deformTitles} from './deform.js';
import {liquid, gesturePages, dragDismiss, expandFrom} from './tactile.js';
import {deck, refit} from './cards.js';
import {mountAssistant, syncAssistant} from './assistant.js';
bus.expandFrom = expandFrom;
import {view as overview} from './views/overview.js';
import {view as agent, send as sendChat, paint as paintChat} from './views/agent.js';
import {view as sendView, enableNotifications} from './views/send.js';
import {view as payments, openDetail} from './views/payments.js';
import {view as markets} from './views/markets.js';
import {view as habits} from './views/habits.js';
import {view as wallets, recipientForm} from './views/wallets.js';
import {view as audit} from './views/audit.js';
import {view as memory} from './views/memory.js';
import {view as spending, openFixed} from './views/spending.js';
import {view as study, emailPanel} from './views/study.js';
import {view as templates} from './views/templates.js';
import {view as progressView, medal} from './views/progress.js';
import {view as sandbox} from './views/sandbox.js';
import {view as banksView} from './views/banks.js';

const VIEWS = [overview, sandbox, agent, sendView, templates, spending, payments, markets, study, progressView, habits, wallets, memory, audit, banksView];
const BY_ID = Object.fromEntries(VIEWS.map(v => [v.id, v]));
const GROUPS = [['nav.g_ai', ['agent']], ['nav.g_money', ['overview', 'sandbox']], ['nav.g_send', ['markets', 'send', 'payments']],
  ['nav.g_plan', ['spending', 'study', 'progress']], ['nav.g_system', ['memory', 'audit']]];
const DOCK = ['overview', 'agent', 'send', 'spending'];
// Pages that were merged into others: their old links still land in the right place.
const MOVED = {templates: ['send', 'templates'], wallets: ['send', 'recipients'], routes: ['send', 'compare'], habits: ['spending'], plans: ['overview']};
const ORDER = GROUPS.flatMap(g => g[1]);
let pendingPaint = false, refreshTimer = 0, events = null, primed = false;

/* ---------- shell ---------- */

function shellText() {
  $$('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  $$('[data-i18n-label]').forEach(el => el.setAttribute('aria-label', t(el.dataset.i18nLabel)));
  // Build the navigation once per language; switching pages only moves the active class, so the CSS transitions and the
  // spring blob animate from where they are instead of every item jumping to its new size at once.
  const nav = $('#nav'), dock = $('#dock');
  if (nav.dataset.lang !== lang) {
    nav.innerHTML = GROUPS.map(([g, ids]) => `<div class="nav-group"><span class="nav-caption">${t(g)}</span>${ids.map(id => `<a href="#${id}" data-view="${id}">${icons[id]}<span class="nav-label">${t('nav.' + id)}</span><b>${String(ORDER.indexOf(id) + 1).padStart(2, '0')}</b></a>`).join('')}</div>`).join('');
    dock.innerHTML = DOCK.map(id => `<a href="#${id}" data-view="${id}">${icons[id]}<span>${t('nav.' + id)}</span></a>`).join('') +
      `<button data-action="open-sheet" data-view="more">${icons.more}<span>${t('nav.more')}</span></button>`;
    nav.dataset.lang = lang;
  }
  nav.querySelectorAll('a[data-view]').forEach(a => a.classList.toggle('active', a.dataset.view === state.view));
  dock.querySelectorAll('[data-view]').forEach(a => a.classList.toggle('active', a.dataset.view === state.view || (a.dataset.view === 'more' && !DOCK.includes(state.view))));
  $$('.nav-blob').forEach(el => el.remove());
  liquid($('#nav'), {axis: 'y', key: 'nav', extend: 22}); liquid($('#dock'), {axis: 'x', key: 'dock'});  // one indicator glides; the items never move
  syncAssistant();
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
  $('#avatar').textContent = state.user ? (state.user.name || state.user.email)[0].toUpperCase() : state.role ? state.role[0].toUpperCase() : '·';
  const count = (state.data.reminders || []).length;
  $('#bell-count').hidden = !count; $('#bell-count').textContent = count;
  notifyNew(state.data.reminders);
  $('#sync').textContent = state.connected ? t('shell.synced', {at: new Date().toLocaleTimeString(lang, {hour12: false})}) : '';
}

function heading(id) {
  const page = id === 'send' && state.send.tab === 'templates' ? 'templates' : id;
  return `<div class="page-head reveal"><div><span class="eyebrow">${String(ORDER.indexOf(id) + 1).padStart(2, '0')} / ${esc(t('nav.' + id)).toUpperCase()}</span><h1>${t('page.' + page)}<i>.</i></h1><p>${t('page.' + page + '_d')}</p></div>
    ${id === 'overview' ? `<div class="head-actions"><button class="button ghost" data-action="go" data-view="agent">${icons.agent}${t('overview.ask')}</button><button class="button primary" data-action="go" data-view="send">${icons.plus}${t('action.new_transfer')}</button></div>` : ''}</div>`;
}

export function enhance(root, quiet = false) {
  if (quiet) root.querySelectorAll('.reveal').forEach(el => el.classList.add('in'));
  reveal(root); interactive(root); deformTitles(root);
  if (root.id === 'view' && state.role) deck(root, state.view, t);  // cards you arrange; the first is the focus
  // Liquid Tab: every page-tab bar and segmented choice; keyed by page and position, because a click re-renders them.
  root.querySelectorAll('.page-tabs, .segmented').forEach((el, i) => liquid(el, {axis: 'x', key: `${state.view}:${i}:${el.className}`}));

  if (!quiet) countUp(root, (n, d) => new Intl.NumberFormat(lang, {minimumFractionDigits: d, maximumFractionDigits: d}).format(n));
}
bus.enhance = enhance;

/** quiet: a data refresh of the page already on screen; entrance animations must not replay. */
function paint(quiet = false) {
  const v = BY_ID[state.view], root = $('#view'), html = document.documentElement;
  pendingPaint = false;
  if (quiet) html.dataset.quiet = '1';
  root.style.opacity = '';  // a swipe may have carried the old page away
  if (!state.role) root.innerHTML = heading(state.view) + `<div class="skeleton reveal in"><i></i><i></i><i></i></div>`;  // the sign-in stage covers it
  else root.innerHTML = heading(state.view) + v.render();
  enhance(root, quiet);
  if (state.role) v.mount?.(root);
  refit(root);  // charts drawn by mount change card heights: settle the layout before the frame is painted
  status();
  if (quiet) requestAnimationFrame(() => requestAnimationFrame(() => { delete html.dataset.quiet; }));
}

const editing = () => document.activeElement?.closest?.('#view') && document.activeElement.matches('input:not([type=checkbox]):not([type=range]),textarea,select');

const arranging = () => !!document.querySelector('#view.arranging, #view .card-block.resizing');
addEventListener('dot:arranged', () => bus.flush());

/** Rebuild the page in place without it moving: the old height holds while the new page is built (so the browser
 *  never pulls the scroll position back), and the position is restored at once — the page scrolls smoothly for the
 *  user, but a refresh must not animate a jump up and back down. */
function steady(rebuild) {
  const root = $('#view'), y = scrollY;
  root.style.minHeight = root.offsetHeight + 'px';
  rebuild();
  scrollTo({top: y, behavior: 'instant'});
  requestAnimationFrame(() => requestAnimationFrame(() => {
    root.style.minHeight = '';
    if (Math.abs(scrollY - y) > 1) scrollTo({top: y, behavior: 'instant'});
  }));
}

function render() {
  // Never rebuild the page under a streaming answer or while the user types; catch up afterwards.
  // Nor under a card being dragged or resized: a live-rate refresh would rebuild the deck and drop it mid-flight.
  if (editing() || arranging() || (state.chat.streaming && ['agent', 'overview'].includes(state.view))) { pendingPaint = true; return; }
  steady(() => paint(true));
}
bus.render = render;
bus.flush = () => { if (pendingPaint) render(); };
// After an explicit user action the page must update even if a field keeps focus; restore that focus afterwards.
bus.repaint = () => { const id = document.activeElement?.id; steady(() => paint(true)); if (id) document.getElementById(id)?.focus({preventScroll: true}); };

async function show(id, mode = 'forward') {
  if (id === 'send' && state.view !== 'send') state.send.tab = 'compare';  // a plain visit opens the main tab
  if (MOVED[id]) {
    const openRoutes = id === 'routes';
    if (id === 'habits') openFixed();  // bills and the payment-habits indicator live in Spending → Fixed costs
    const [to, tab] = MOVED[id];
    id = to;
    if (tab) state.send.tab = tab;
    history.replaceState(null, '', '#' + id);
    if (openRoutes) state.send.openRoutes = true;  // the route manager is a dialog on the Send page
  }
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
  const before = JSON.stringify(state.data);
  invalidate();
  const v = BY_ID[state.view];
  try {
    await Promise.all([need([...v.needs, 'reminders'], force), v.load?.()]);
    state.connected = true;
  } catch { state.connected = false; }
  const same = !force && JSON.stringify(state.data) === before;  // nothing this page shows has changed: leave it be
  if (same) { status(); return; }
  if (!$('#modal').open || force) render(); else pendingPaint = true;
  status();
  celebrate();
}

/* ---------- celebration moments: shown once, gently, never compared with anyone ---------- */
let celebrating = false;
async function celebrate() {
  if (!state.role || celebrating || state.role === 'agent') return;
  let list = [];
  try { list = await api('/celebrations'); } catch { return; }
  if (!list.length) return;
  celebrating = true;
  const seen = [];
  for (const c of list) {
    await new Promise(resolve => showCelebration(c, resolve));
    seen.push(c.id);
  }
  try { await api('/celebrations/seen', 'POST', {ids: seen}); } catch { /* shown again next time */ }
  celebrating = false;
}

function celebrationText(c) {
  const d = c.data || {};
  if (c.kind === 'badge') return t('badge.' + c.ref);
  if (c.kind === 'level') return t('cel.level', {n: c.ref, name: t('level.' + c.ref)});
  if (c.kind === 'challenge') return t('ch.' + d.kind);
  if (c.kind === 'streak') return t('cel.streak', {n: c.ref});
  if (c.kind === 'goal') return t('cel.goal', {title: d.title || ''});
  if (c.kind === 'awarded') return t('cel.awarded', {name: d.name || ''});
  return '';
}

function showCelebration(c, done) {
  const box = document.createElement('div');
  box.className = 'celebrate';
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-modal', 'true');
  box.setAttribute('aria-label', t('cel.kind.' + c.kind));
  const dots = Array.from({length: 18}, (_, i) => `<i data-i="${i}"></i>`).join('');
  box.innerHTML = `<div class="cel-card"><div class="cel-burst" aria-hidden="true">${dots}</div>${medal(true, 88)}
    <span class="eyebrow">${esc(t('cel.kind.' + c.kind))}</span><h2>${esc(celebrationText(c))}</h2><p>${esc(t('cel.sub'))}</p>
    <div class="row-actions"><button class="button primary" data-cel="ok">${t('cel.ok')}</button><button class="link" data-cel="view">${t('cel.view')}</button></div></div>`;
  box.querySelectorAll('.cel-burst i').forEach(el => {
    const i = Number(el.dataset.i), a = i / 18 * Math.PI * 2, r = 90 + (i % 3) * 26;
    el.style.setProperty('--x', `${Math.cos(a) * r}px`); el.style.setProperty('--y', `${Math.sin(a) * r}px`);
    el.style.setProperty('--d', `${(i % 6) * 40}ms`); el.style.setProperty('--s', String(0.5 + (i % 4) * 0.25));
  });
  const close = go => {
    box.classList.add('out');
    setTimeout(() => { box.remove(); if (go) location.hash = 'progress'; done(); }, 320);
  };
  box.addEventListener('click', e => {
    const b = e.target.closest('[data-cel]');
    if (b) close(b.dataset.cel === 'view');
    else if (e.target === box) close(false);
  });
  box.addEventListener('keydown', e => { if (e.key === 'Escape') close(false); });
  document.body.appendChild(box);
  box.querySelector('[data-cel="ok"]').focus();
}

/* ---------- live updates ---------- */
function connectEvents() {
  events?.close();
  primed = false;
  if (!('EventSource' in window) || !state.role) return;
  events = new EventSource('/api/events');
  events.onmessage = e => {
    const data = JSON.parse(e.data);
    if (data.version === state.version) return;
    const first = !primed;
    primed = true;
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
async function session() {
  try {
    const s = await api('/session');
    Object.assign(state, {role: s.role, model: s.model_configured, modelName: s.model, user: s.user || null});
  } catch { Object.assign(state, {role: null, user: null}); }
}

/** Signed out (by you, or because the session ended): clear what was on screen and show the sign-in stage again. */
let signingIn = false;
async function backToSignIn() {
  if (signingIn) return;
  signingIn = true;
  try {
    Object.assign(state, {role: null, user: null, data: {}});
    if (state.chat) state.chat.messages = [];
    events?.close(); events = null; closeModal(); closeSheets(); shellText(); paint();
    await signIn();
    if (state.role) { connectEvents(); shellText(); if (!builtUnderAuth) await show(state.view); builtUnderAuth = false; }
  } finally { signingIn = false; }
}
addEventListener('dot:signed-out', () => { if (state.role && !document.getElementById('auth')) backToSignIn(); });

/** No session: the sign-in stage (sign up, sign in, demo or an access token). The first page is built underneath before
    the dot flies into its place, so the hand-over shows a finished page, not a skeleton. */
let builtUnderAuth = false;
async function signIn() {
  try { state.health = await api('/health'); } catch { /* keep the last known */ }
  await authScreen(state.health || {}, async () => {
    state.data = {};
    await session();
    if (!state.role) return;
    shellText();
    await Promise.race([show(state.view), new Promise(r => setTimeout(r, 2500))]);  // never hold the curtain for long
    builtUnderAuth = true;
  });
}

/** What goes to the AI model, and your data: take it with you or wipe it. */
function privacySection() {
  const u = state.user;
  return `<section class="settings-sec privacy-sec"><span class="eyebrow">${t('privacy.title')}</span>
    <ul class="privacy-list"><li>${t('privacy.sent')}</li><li>${t('privacy.masked')}</li><li>${t('privacy.images')}</li><li>${t('privacy.never')}</li></ul>
    <div class="row-actions"><a class="button sm" href="/api/account/export" download="dot-export.json">${icons.arrow}${t('privacy.export')}</a>
      <button type="button" class="button sm ghost" data-action="privacy-clear" data-what="conversations">${t('privacy.clear_chats')}</button>
      <button type="button" class="button sm ghost" data-action="privacy-clear" data-what="notes">${t('privacy.clear_notes')}</button></div>
    ${u && !u.original ? `<details class="danger-zone"><summary>${t('privacy.close')}</summary>
      <form id="close-form" class="inline-form" autocomplete="off"><p class="fine">${t('privacy.close_d')}</p>
        <div class="grid-2">${field('cl-email', t('auth.q.email'), `<input id="cl-email" name="email" type="email" required>`)}${field('cl-pw', t('privacy.password'), `<input id="cl-pw" name="password" type="password" required>`)}</div>
        <div class="form-error"></div><button class="button sm">${t('privacy.close_btn')}</button></form></details>`
      : u ? `<p class="fine">${t('privacy.original')}</p>` : ''}
    ${u && !u.original ? `<details class="danger-zone"><summary>${t('privacy.claim_title')}</summary>
      <form id="claim-form" class="inline-form" autocomplete="off"><p class="fine">${t('privacy.claim_d')}</p>
        ${field('cl-token', 'OWNER_TOKEN', `<input id="cl-token" name="owner_token" type="password" required minlength="24">`)}
        <div class="form-error"></div><button class="button sm">${t('privacy.claim_btn')}</button></form></details>` : ''}
  </section>`;
}

async function settingsModal(focus) {
  if (state.role) await need(['memory', 'economies']);
  if (isOwner()) { try { state.data.email = await api('/email'); } catch { /* shown as unavailable */ } }
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
    ${isOwner() ? `<section class="settings-sec email-sec">${emailPanel()}</section>` : ''}
    ${isOwner() ? privacySection() : ''}
    <section class="settings-sec"><span class="eyebrow">${t('settings.session')}</span>
      <dl class="facts"><div><dt>${t('settings.role')}</dt><dd>${esc(state.role ? t('role.' + state.role) : '—')}</dd></div><div><dt>${t('settings.model')}</dt><dd>${state.model ? esc(state.modelName || t('agent.mode.model')) : t('settings.model_off')}</dd></div>
      <div><dt>${t('settings.rails')}</dt><dd>${t('env.sandbox')}</dd></div></dl>
      <label class="check-label"><input type="checkbox" id="set-notify" ${localStorage.getItem('dot.notify') === '1' ? 'checked' : ''}> ${t('rem.notify')}</label>
      <form id="login-form" class="inline-form">${field('access-token-2', t('login.switch'), `<input id="access-token-2" type="password" name="token" minlength="24" autocomplete="off" required>`)}<div class="form-error"></div>
      <div class="row-actions"><button class="button">${t('login.connect')}</button>${state.role ? `<button type="button" class="button ghost" data-action="logout">${t('login.logout')}</button>` : ''}</div></form></section>`, 'SETTINGS', {mount: root => {
    if (focus) setTimeout(() => root.querySelector('.' + focus)?.scrollIntoView({block: 'start', behavior: 'smooth'}), 260);  // e.g. "email settings" from the gaps card
    root.querySelector('#set-lang').addEventListener('change', e => changeLang(e.target.value));
    root.querySelector('#em-digest')?.addEventListener('change', e => { const wd = root.querySelector('#em-weekday'); if (wd) wd.disabled = e.target.value !== 'weekly'; });
    root.querySelector('#set-theme').addEventListener('change', e => setTheme(e.target.value));
    root.querySelector('#set-notify').addEventListener('change', async e => { if (e.target.checked) e.target.checked = await enableNotifications(); else localStorage.setItem('dot.notify', '0'); });
  }});
}

export const reminderText = r => t('reminder.' + r.kind, r.data) + (r.data?.why ? ' — ' + r.data.why : '');

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
    try { const n = new Notification('DOT · ' + t('shell.reminders'), {body: reminderText(r), tag: 'dot-' + r.id}); n.onclick = () => { window.focus(); location.hash = REMINDER_VIEW[r.kind] || 'overview'; }; } catch { /* unsupported */ }
  }
}
const REMINDER_VIEW = {fx_rule_ready: 'markets', fx_rule_done: 'markets', fx_rule_blocked: 'markets', fx_rule_due: 'markets',
  budget_near: 'spending', budget_over: 'spending', budget_others_near: 'spending', budget_others_over: 'spending', log_nudge: 'spending', ai_good_time: 'send', ai_deadline: 'send', rate_target: 'send', rate_favorable: 'send', exchange_due: 'send', expense_expected: 'spending', scholarship_due: 'study', tuition_due: 'study', challenge_ending: 'progress', goal_deadline: 'plans', obligation_due_soon: 'habits', obligation_overdue: 'habits'};

function drawer() {
  const list = state.data.reminders || [];
  $('#drawer-panel').innerHTML = `<header><span class="eyebrow">${t('shell.reminders')}</span><button class="icon-button" data-action="close-drawer" aria-label="${t('common.close')}">×</button></header>
    ${list.length ? `<ul class="reminders">${list.map(r => `<li class="sev-${esc(r.severity)}"><span class="pulse"></span><div><p>${esc(reminderText(r))}</p><small>${when(r.created)}</small></div>
      <div class="row-actions">${['quote_expired', 'quote_expiring', 'unresolved', 'insufficient_funds'].includes(r.kind) ? `<button class="link sm" data-action="detail" data-id="${esc(r.ref)}">${t('agent.view')}</button>` : r.kind.startsWith('goal') ? `<button class="link sm" data-action="go" data-view="plans">${t('common.open')}</button>` : r.kind.startsWith('obligation') ? `<button class="link sm" data-action="go" data-view="habits">${t('common.open')}</button>` : REMINDER_VIEW[r.kind] ? `<button class="link sm" data-action="go" data-view="${REMINDER_VIEW[r.kind]}">${t('common.open')}</button>` : ''}
      <button class="x" data-action="dismiss" data-id="${r.id}" aria-label="${t('common.dismiss')}">×</button></div></li>`).join('')}</ul>` : empty(t('reminder.none'))}
    <p class="fine">${t('reminder.note')}</p>`;
}

function openDrawer() { drawer(); $('#drawer').hidden = false; requestAnimationFrame(() => $('#drawer').classList.add('open')); dragDismiss($('#drawer-panel'), closeSheets, 'x'); }
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
  dragDismiss($('#sheet-panel'), closeSheets, 'y');
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
  'open-settings'(el) { return settingsModal(el.dataset.focus); },
  async 'privacy-clear'(el) {
    if (!confirm(t('privacy.clear_q'))) return;
    await api('/agent/memory/clear', 'POST', {what: el.dataset.what});
    state.chat.messages = el.dataset.what === 'conversations' ? [] : state.chat.messages;
    invalidate(); toast(t('privacy.cleared'), 'good');
  },
  copy(el) { return wallets.actions.copy(el); },
  'open-sheet': openSheet,
  'close-drawer': closeSheets,
  async logout() {
    try { await api('/session', 'DELETE'); } catch { /* already gone */ }
    await backToSignIn();
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
  const handler = key === 'claim-form' ? claimData : key === 'close-form' ? closeAccount : key === 'login-form' ? login : key === 'settings-form' ? savePrefs : VIEWS.map(v => v.submit?.[key]).find(Boolean);
  if (!handler) return;
  const button = f.querySelector('button:not([type=button])');
  if (button) button.disabled = true;
  try { await handler(f); }
  catch (error) { formError(f, error); }
  finally { if (button?.isConnected) button.disabled = false; }
});

async function claimData(f) {
  await api('/auth/claim', 'POST', {owner_token: value(f, 'owner_token')});
  closeModal(); toast(t('privacy.claimed'), 'good');
  state.data = {}; await session(); await show(state.view);
}

async function closeAccount(f) {
  if (!confirm(t('privacy.close_q'))) return;
  const r = await api('/account/delete', 'POST', {email: value(f, 'email'), password: value(f, 'password')});
  toast(r.deleted === false ? t('privacy.delete_pending') : t('privacy.closed'));
  await backToSignIn();
}

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
    if (!state.role) await signIn();
  } catch {
    state.connected = false;
    $('#banner').textContent = t('err.backend'); $('#banner').hidden = false;
  }
  status();
  if (state.role) {
    connectEvents();
    setTimeout(celebrate, 1500);
    need(['reminders', 'memory', 'economies']).then(() => {
      const m = state.data.memory || {};
      if (m.display_currency) state.display = m.display_currency;
      if (!hadLang && m.language && m.language !== lang) changeLang(m.language);
      status();
    });
  }
  if (!builtUnderAuth) await show(state.view);
  builtUnderAuth = false;
  mountAssistant();  // DOT on every page
  // Gesture-driven Transition: the page follows the finger; release decides from distance and speed.
  gesturePages($('#main'), $('#view'), {
    canGo: dir => { const i = ORDER.indexOf(state.view); return dir === 'left' ? i < ORDER.length - 1 : i > 0; },
    go: dir => { const i = ORDER.indexOf(state.view); swipeMode = dir; location.hash = ORDER[i + (dir === 'left' ? 1 : -1)]; },
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
// Clicking "Send" while already on another tab of the Send page goes back to its main tab (the hash does not change).
document.addEventListener('click', e => {
  const a = e.target.closest('#nav a[data-view="send"], #dock a[data-view="send"]');
  if (a && state.view === 'send' && state.send.tab !== 'compare') { state.send.tab = 'compare'; show('send'); }
});
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
