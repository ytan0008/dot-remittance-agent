import {api} from './api.js';
import {t} from './i18n.js';
import {reduced} from './motion.js';

export const $ = (s, root = document) => root.querySelector(s);
export const $$ = (s, root = document) => [...root.querySelectorAll(s)];
export const newId = () => crypto.randomUUID?.() ?? Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');

export const state = {
  view: 'overview', role: null, model: false, modelName: null, health: null, connected: false,
  data: {}, errors: {}, stale: new Set(), version: 0,
  chat: {messages: [], streaming: false, session: 'web-' + newId().slice(0, 8)},
  send: {route: 'AU-CN', mode: 'send', amount: '', receive: '', rank: 'receive', recipient: '', purpose: '', arrival: '', goal: '', key: newId(), tab: 'compare'},
  markets: {source: 'AUD', target: 'CNY', days: '90', direction: 'send', scenario: '-3', scenarioAmount: '1000'},
  filters: {status: 'all', rail: 'all'},
  audit: {q: '', outcome: '', actor: ''},
  display: 'AUD',
};

const RESOURCES = {
  balances: '/balances', transfers: '/transfers', recipients: '/recipients', routes: '/routes', economies: '/economies',
  settings: '/settings', memory: '/memory', proposals: '/proposals',
  decisions: '/decisions', goals: '/goals', budget: '/budget', obligations: '/obligations', habits: '/habits',
  reminders: '/reminders', alerts: '/rate-alerts', motivationSummary: '/motivation', recurring: '/recurring', agentMemory: '/agent/memory',
  equivalents: () => '/balances/equivalents?display=' + encodeURIComponent(state.display),
  audit: () => '/audit?' + new URLSearchParams(Object.entries({q: state.audit.q, outcome: state.audit.outcome, actor_filter: state.audit.actor}).filter(([, v]) => v)),
};
const OWNER_ONLY = new Set(['audit']);
const inflight = new Map();

export async function need(keys, force = false) {
  if (!state.role) return;
  const wanted = keys.filter(k => (force || state.stale.has(k) || !(k in state.data)) && !(OWNER_ONLY.has(k) && state.role !== 'owner'));
  await Promise.all(wanted.map(async key => {
    if (inflight.has(key)) return inflight.get(key);
    const path = typeof RESOURCES[key] === 'function' ? RESOURCES[key]() : RESOURCES[key];
    const job = api(path).then(v => { state.data[key] = v; delete state.errors[key]; state.stale.delete(key); })
      .catch(e => { state.errors[key] = e.message; state.stale.delete(key); if (!(key in state.data)) state.data[key] = null; })
      .finally(() => inflight.delete(key));
    inflight.set(key, job);
    return job;
  }));
}

export const invalidate = (keys = Object.keys(state.data)) => keys.forEach(k => state.stale.add(k));

export const isOwner = () => state.role === 'owner';
export const canPrepare = () => ['owner', 'agent'].includes(state.role);
export const ownerAttr = () => isOwner() ? '' : 'disabled';

/* ---------- render bus (set by app.js) ---------- */
export const bus = {render: () => {}, go: () => {}};
export const rerender = () => bus.render();
export const go = view => bus.go(view);
export const refreshView = () => bus.refresh();

/* ---------- toast ---------- */
let toastTimer;
export function toast(text, tone = '') {
  const el = $('#toast');
  el.textContent = text; el.className = tone; el.hidden = false;
  el.classList.remove('show'); void el.offsetWidth; el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.classList.remove('show'); setTimeout(() => { el.hidden = true; }, 300); }, 4200);
}

/* ---------- modal zooms out of the element that opened it ---------- */
let lastPointer = {x: innerWidth / 2, y: innerHeight / 2};
addEventListener('pointerdown', e => { lastPointer = {x: e.clientX, y: e.clientY}; }, {capture: true});
export function modal(title, html, eyebrow = 'WORKSPACE', {wide = false, mount} = {}) {
  const d = $('#modal');
  $('#modal-eyebrow').textContent = eyebrow;
  $('#modal-body').innerHTML = `<h2 class="modal-title">${title}</h2>${html}`;
  d.classList.toggle('wide', wide);
  if (!d.open) {
    d.style.setProperty('--ox', lastPointer.x + 'px');
    d.style.setProperty('--oy', lastPointer.y + 'px');
    d.showModal();
    d.classList.remove('closing');
  }
  mount?.($('#modal-body'));
  bus.enhance?.($('#modal-body'));
}

export function closeModal() {
  const d = $('#modal');
  if (!d.open) return;
  if (reduced()) { d.close(); return; }
  d.classList.add('closing');
  setTimeout(() => { d.close(); d.classList.remove('closing'); }, 220);
}

export function formError(scope, error) {
  const box = scope?.querySelector?.('.form-error');
  if (box) { box.textContent = error.message; box.classList.remove('shake'); void box.offsetWidth; box.classList.add('shake'); }
  else toast(error.message, 'bad');
}

export const value = (form, name) => (new FormData(form).get(name) ?? '').toString().trim();
export { api, t };
