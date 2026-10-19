import {state, t, api, isOwner, go} from '../core.js';
import {esc, chip, amt, empty, panel, icons, short} from '../ui.js';
import {money, approx, num, day, when, pct, decimalsOf, currencyName} from '../i18n.js';
import {sparkline} from '../charts.js';
import {zoomPan, reduced} from '../motion.js';
import {table} from './payments.js';
import {alertText} from './send.js';
import {chatLog, composer} from './agent.js';

const NODES = [
  {id: 'intent', x: 150, y: 250, view: 'agent'},
  {id: 'understand', x: 255, y: 112, view: 'agent'},
  {id: 'plan', x: 545, y: 112, view: 'send'},
  {id: 'guardrails', x: 650, y: 250, view: 'autonomy'},
  {id: 'execute', x: 545, y: 388, view: 'payments'},
  {id: 'outcome', x: 255, y: 388, view: 'payments'},
];
const PHASE = {draft: 3, approved: 4, pending: 5, unknown: 5, completed: 6, failed: 6, cancelled: 3, superseded: 3};

function latest() {
  const list = state.data.transfers || [];
  return list.find(p => ['pending', 'unknown', 'approved', 'draft'].includes(p.status)) || list[0];
}

function orbit() {
  const p = latest();
  const phase = state.chat.streaming ? 2 : p ? PHASE[p.status] || 0 : 0;
  const path = NODES.map((n, i) => `${i ? 'L' : 'M'}${n.x} ${n.y}`).join('') + 'Z';
  const done = NODES.slice(0, Math.max(1, phase)).map((n, i) => `${i ? 'L' : 'M'}${n.x} ${n.y}`).join('');
  const glyph = {
    intent: '<path d="M-7 0h14M2-5l5 5-5 5"/>', understand: '<circle r="6"/><circle r="1.6" class="fill"/>',
    plan: '<path d="M-7-5h14M-7 0h9M-7 5h12"/>', guardrails: '<path d="M0-8l7 3v5q-1 5-7 8-6-3-7-8v-5z"/><path d="M-3 0l2.4 2.4L4-2"/>',
    execute: '<path d="M-4-7l10 7-10 7z"/>', outcome: '<circle r="7"/><path d="M-3.5 0l2.5 2.5 4.5-5"/>',
  };
  return `<div class="orbit-stage no-swipe">
    <svg class="orbit" id="orbit" viewBox="0 0 800 500" role="img" aria-label="${t('overview.orbit_label')}">
      <g id="orbit-world">
        <g class="layer-back" id="layer-back">
          ${Array.from({length: 9}, (_, i) => `<circle class="halo" cx="400" cy="250" r="${70 + i * 34}"/>`).join('')}
          <ellipse class="ring-dash" cx="400" cy="250" rx="300" ry="190"/>
          ${Array.from({length: 48}, (_, i) => { const a = i / 48 * Math.PI * 2; return `<circle class="speck" cx="${(400 + Math.cos(a) * 340).toFixed(1)}" cy="${(250 + Math.sin(a) * 222).toFixed(1)}" r="${i % 6 ? .9 : 1.8}"/>`; }).join('')}
        </g>
        <g class="layer-mid">
          <path class="track" d="${path}"/>
          ${phase ? `<path class="track-done" d="${done}"/>` : ''}
          ${NODES.map(n => `<line class="spoke" x1="400" y1="250" x2="${n.x}" y2="${n.y}"/>`).join('')}
          <g class="spinner-ring ${reduced() ? '' : 'go'}"><circle cx="400" cy="250" r="86" class="ring-thin"/><circle cx="400" cy="164" r="3.4" class="fill"/><circle cx="400" cy="336" r="2.2" class="fill"/></g>
          ${p && !reduced() ? `<circle class="particle" r="3.5"><animateMotion dur="5s" repeatCount="indefinite" path="${path}"/></circle>` : ''}
        </g>
        <g class="layer-front">
          <circle class="core-halo" cx="400" cy="250" r="54"/>
          <circle class="core" cx="400" cy="250" r="40"/>
          <text class="core-text" x="400" y="256" text-anchor="middle">dot.</text>
          ${NODES.map((n, i) => `<g class="node ${i < phase ? 'done' : ''} ${i === phase - 1 ? 'current' : ''}" data-node="${n.id}" data-focus="${n.x},${n.y}" tabindex="0" role="button" aria-label="${t('flow.' + n.id)}">
            <circle class="node-hit" cx="${n.x}" cy="${n.y}" r="40"/>
            <circle class="node-ring" cx="${n.x}" cy="${n.y}" r="31"/>
            <circle class="node-bg" cx="${n.x}" cy="${n.y}" r="25"/>
            <g class="glyph" transform="translate(${n.x} ${n.y})">${glyph[n.id]}</g>
            <text class="node-title" x="${n.x}" y="${n.y + 50}" text-anchor="middle">${t('flow.' + n.id)}</text>
            <text class="node-sub" x="${n.x}" y="${n.y + 64}" text-anchor="middle">${String(i + 1).padStart(2, '0')} / ${n.id.toUpperCase()}</text>
          </g>`).join('')}
        </g>
      </g>
    </svg>
    <div class="zoom-controls"><button data-zoom="in" aria-label="${t('common.zoom_in')}">${icons.zoomIn}</button><button data-zoom="out" aria-label="${t('common.zoom_out')}">${icons.zoomOut}</button><button data-zoom="reset" aria-label="${t('common.reset')}">${icons.reset}</button></div>
    <div class="orbit-caption" id="orbit-caption"><span class="eyebrow">${p ? 'TRACKING · ' + short(p.id) : t('overview.ready')}</span><b>${p ? esc(p.details.recipient.name) + ' · ' + esc(money(p.details.value, p.details.source)) + ' ' + esc(p.details.source) : t('overview.start')}</b><small>${p ? chip(p.status) : t('overview.hint_zoom')}</small>${p ? `<button class="link" data-action="detail" data-id="${esc(p.id)}">${t('agent.view')} ${icons.arrow}</button>` : ''}</div>
  </div>`;
}

function metrics() {
  const balances = (state.data.balances || []).filter(b => b.rail === 'sandbox');
  const tier = state.data.settings?.agent_tier ?? 3;
  const cards = balances.map(b => {
    const digits = Math.min(2, decimalsOf(b.currency));
    return `<article class="metric tilt reveal"><div class="metric-head"><span>${esc(b.currency)}</span><small>${esc(currencyName(b.currency))}</small></div>
      <div class="metric-value"><span data-count="${approx(b.available, b.currency)}" data-digits="${digits}">${esc(money(b.available, b.currency))}</span></div>
      <div class="metric-bar"><i class="bar-fill" data-ratio="${Number(b.total) > 0 ? (Number(b.reserved) / Number(b.total)).toFixed(4) : 0}"></i></div>
      <div class="metric-foot"><span>${t('wallets.reserved')} ${esc(money(b.reserved, b.currency))}</span><span class="tag k-simulation">${t('kind.simulation')}</span></div><i class="metric-orbit"></i></article>`;
  });
  const alerts = (state.data.alerts || []).filter(a => a.active);
  const next = alerts.find(a => a.condition === 'date') || alerts[0];
  cards.push(`<article class="metric dark tilt reveal" data-action="go" data-view="send"><div class="metric-head"><span>${t('overview.reminders')}</span><small>${t('overview.reminders_d')}</small></div>
    <div class="metric-value"><span data-count="${alerts.length}" data-digits="0">${alerts.length}</span><small>${t('overview.reminders_unit')}</small></div>
    <div class="metric-foot"><span>${next ? esc(alertText(next)) : t('overview.reminders_none')}</span></div><i class="metric-orbit"></i></article>`);
  const mo = state.data.motivationSummary;
  if (mo?.settings?.enabled) cards.push(`<article class="metric tilt reveal" data-action="go" data-view="progress"><div class="metric-head"><span>${t('overview.momentum')}</span><small>${esc(t('level.' + mo.level))}</small></div>
    <div class="metric-value"><span>L${mo.level}</span><small>/ ${mo.max_level}</small></div>
    <div class="tier-dots">${Array.from({length: mo.max_level}, (_, i) => `<i class="${i < mo.level ? 'on' : ''}"></i>`).join('')}</div>
    <div class="metric-foot"><span>${t('overview.streak', {n: mo.streak.current})}</span><span>${t('overview.challenges', {n: mo.active.length})}</span></div><i class="metric-orbit"></i></article>`);
  cards.push(`<article class="metric tilt reveal" data-action="go" data-view="autonomy"><div class="metric-head"><span>${t('overview.boundary')}</span><small>IN CONTROL</small></div>
    <div class="metric-value"><span>T${tier}</span><small>${esc(t('tier.' + tier))}</small></div>
    <div class="tier-dots">${[1, 2, 3].map(n => `<i class="${n <= tier ? 'on' : ''}"></i>`).join('')}</div>
    <div class="metric-foot"><span>${t('overview.boundary_d')}</span></div><i class="metric-orbit"></i></article>`);
  return `<div class="metrics hscroll">${cards.join('')}</div>`;
}

function reminders() {
  const list = (state.data.reminders || []).slice(0, 4);
  if (!list.length) return '';
  return `<div class="reminder-strip reveal">${list.map(r => `<div class="reminder sev-${esc(r.severity)}"><span class="pulse"></span><p>${esc(t('reminder.' + r.kind, r.data))}</p>${r.kind.startsWith('quote') || r.kind === 'unresolved' || r.kind === 'insufficient_funds' ? `<button class="link" data-action="detail" data-id="${esc(r.ref)}">${t('agent.view')}</button>` : ''}<button class="x" data-action="dismiss" data-id="${r.id}" aria-label="${t('common.dismiss')}">×</button></div>`).join('')}</div>`;
}

function rateCard() {
  const r = state.data.overviewRate;
  const {source, target} = state.markets;
  const body = r ? `<div class="rate-main"><strong data-count="${Number(r.latest)}" data-digits="4">${num(r.latest, 4)}</strong><span>${esc(target)} / 1 ${esc(source)}</span></div>${sparkline(r.series, 340, 84)}
      <div class="rate-meta"><span>${day(r.first)}</span><span>${t('rates.percentile')} ${num(r.percentile, 0)} · ${t('rates.position.' + r.position)}</span><span>${day(r.last)}</span></div>`
    : `<div class="rate-error">${esc(state.errors.overviewRate || t('common.loading'))}</div>`;
  return panel(`${esc(source)} <span class="muted">→</span> ${esc(target)}`, body + `<p class="fine">${r ? esc(r.provider) + ' · ' : ''}${t('rates.not_quote')}</p>`, {actions: `<button class="link" data-action="go" data-view="markets">${t('overview.markets')} ${icons.arrow}</button>`, cls: 'rate-card tilt'});
}

export const view = {
  id: 'overview',
  needs: ['balances', 'transfers', 'alerts', 'settings', 'reminders', 'motivationSummary'],
  async load() {
    const {source, target} = state.markets;
    try { state.data.overviewRate = await api(`/rates?source=${source}&target=${target}&days=30`); delete state.errors.overviewRate; }
    catch (e) { state.errors.overviewRate = e.message; }
  },
  render() {
    return `${reminders()}${metrics()}
      <div class="grid-overview">
        ${panel(`<i class="dot"></i>${t('overview.journey')}`, orbit(), {sub: 'INTENT → OUTCOME', cls: 'orbit-panel'})}
        ${panel(`<span class="agent-orb"><i></i></span>${t('overview.ask')}`, `<div class="chat-log mini" id="mini-chat-log">${chatLog(2)}</div>${composer('mini-chat-form')}`, {cls: 'chat-panel mini', actions: `<button class="link" data-action="go" data-view="agent">${t('overview.open_agent')} ${icons.arrow}</button>`})}
      </div>
      <div class="grid-lower">
        ${panel(t('overview.recent'), table((state.data.transfers || []).filter(p => p.status !== 'superseded'), {limit: 5, compact: true}), {actions: `<button class="link" data-action="go" data-view="payments">${t('common.view_all')} ${icons.arrow}</button>`})}
        ${rateCard()}
      </div>`;
  },
  mount(root) {
    root.querySelectorAll('#mini-chat-log').forEach(log => { log.scrollTop = log.scrollHeight; });
    root.querySelectorAll('.bar-fill[data-ratio]').forEach(el => el.style.setProperty('--ratio', el.dataset.ratio));
    const svg = root.querySelector('#orbit');
    if (!svg) return;
    const back = root.querySelector('#layer-back');
    const zp = zoomPan(svg, root.querySelector('#orbit-world'), {min: .55, max: 3.4, onChange: v => {
      // Depth of field: the far layer blurs as you pull close, the scene softens as you push far.
      back.style.filter = v.k > 1 ? `blur(${((v.k - 1) * 1.6).toFixed(2)}px)` : 'none';
      svg.style.setProperty('--depth', v.k.toFixed(3));
      svg.classList.toggle('far', v.k < .85);
    }});
    root.querySelectorAll('[data-zoom]').forEach(b => b.addEventListener('click', () => {
      ({in: () => zp.zoom(1.35), out: () => zp.zoom(1 / 1.35), reset: () => zp.reset()})[b.dataset.zoom]();
    }));
    const caption = root.querySelector('#orbit-caption');
    const focusNode = node => {
      const n = NODES.find(x => x.id === node.dataset.node);
      root.querySelectorAll('.node').forEach(x => x.classList.toggle('focused', x === node));
      zp.focus(n.x, n.y, 2.1);
      caption.innerHTML = `<span class="eyebrow">${String(NODES.indexOf(n) + 1).padStart(2, '0')} / ${n.id.toUpperCase()}</span><b>${t('flow.' + n.id)}</b><small>${t('flow.' + n.id + '_d')}</small><span class="caption-actions"><button class="link" data-action="go" data-view="${n.view}">${t('common.open')} ${icons.arrow}</button><button class="link" data-zoom-reset>${t('common.reset')}</button></span>`;
      caption.querySelector('[data-zoom-reset]').addEventListener('click', () => { zp.reset(); root.querySelectorAll('.node').forEach(x => x.classList.remove('focused')); });
      caption.classList.remove('pop'); void caption.offsetWidth; caption.classList.add('pop');
    };
    root.querySelectorAll('.node').forEach(node => {
      node.addEventListener('click', () => focusNode(node));
      node.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); focusNode(node); } });
    });
  },
};
