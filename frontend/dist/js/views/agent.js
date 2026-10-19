import {state, t, toast, isOwner, canPrepare, invalidate, api, bus} from '../core.js';
import {stream} from '../api.js';
import {esc, chip, amt, tag, mono, short, icons, panel} from '../ui.js';
import {lang, money, num, day, pct, has, when, region} from '../i18n.js';
import {sparkline} from '../charts.js';
import {envLabel} from './payments.js';

const TIERS = {view: 1, prepare: 2, submit: 3};
const NEED_TIER = {view: 1, prepare: 2, submit: 3};
const CUR_TO_ECON = {AUD: 'AU', CNY: 'CN', VND: 'VN', USD: 'US', PHP: 'PH', MXN: 'MX', JPY: 'JP', KRW: 'KR', HKD: 'HK', TWD: 'TW',
  SGD: 'SG', NZD: 'NZ', CAD: 'CA', MYR: 'MY', THB: 'TH', IDR: 'ID', CLP: 'CL', PEN: 'PE', RUB: 'RU', BND: 'BN', PGK: 'PG'};
const FORM_CURRENCIES = ['AUD', 'CNY', 'USD', 'VND', 'PHP', 'MXN', 'JPY', 'KRW', 'HKD', 'TWD', 'SGD', 'NZD', 'CAD', 'MYR', 'THB', 'IDR'];
const slug = name => (name || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
let keySeq = 0;
const TOOL_TIER = {remember_note: 'prepare', forget_note: 'prepare', prepare_payment: 'prepare', modify_payment: 'prepare', reconcile_payment: 'prepare', propose_change: 'prepare', execute_payment: 'submit'};

/** Minimal, safe Markdown for model answers: escape everything first, then bold, inline code and bullet lists. */
function md(text) {
  const inline = x => esc(x).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code class="mono">$1</code>');
  const out = []; let list = null;
  for (const raw of String(text).split(/\r?\n/)) {
    const item = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(raw);
    if (item) { (list ??= []).push(`<li>${inline(item[1])}</li>`); continue; }
    if (list) { out.push(`<ul>${list.join('')}</ul>`); list = null; }
    out.push(raw.trim() ? `<p>${inline(raw)}</p>` : '');
  }
  if (list) out.push(`<ul>${list.join('')}</ul>`);
  return out.join('');
}

export const suggestions = () => [t('agent.s1'), t('agent.s2'), t('agent.s3'), t('agent.s4')];

function card(step) {
  const r = step.result;
  if (step.status === 'fail') {
    const need = NEED_TIER[step.params?.need];
    const fix = step.code === 'tier_denied' && need && isOwner()
      ? `<button class="button sm primary" data-action="chat-tier" data-tier="${need}">${t('agent.raise_tier', {n: need})} ${icons.arrow}</button>` : '';
    return `<div class="rcard fail"><b>${t('agent.blocked')}</b><p>${esc(step.code && has('err.' + step.code) ? t('err.' + step.code, step.params) : step.error)}</p>${fix}</div>`;
  }
  if (step.status !== 'ok' || !r) return '';
  switch (step.tool) {
    case 'get_balances':
      return `<div class="rcard"><span class="eyebrow">${t('kind.ledger')}</span>${r.filter(b => b.total !== null).map(b => `<div class="kv"><span>${esc(b.currency)}</span>${amt(b.available, b.currency)}<small class="muted">${t('wallets.reserved')} ${esc(money(b.reserved, b.currency))}</small></div>`).join('')}</div>`;
    case 'latest_rate':
      return `<div class="rcard"><span class="eyebrow">${tag('reference')}</span><div class="big-num">${num(r.rate, 6)} <small>${esc(r.target)}/${esc(r.source)}</small></div><small class="muted">${esc(r.provider)} · ${day(r.observed)}${r.change_pct ? ' · ' + pct(r.change_pct, 3) : ''}${r.derived ? ' · ' + t('rates.derived') : ''}</small></div>`;
    case 'rate_history':
      return `<div class="rcard"><span class="eyebrow">${tag('historical')}</span>${sparkline(r.series)}<small class="muted">${t('rates.percentile')} ${num(r.percentile, 1)} · ${t('rates.position.' + r.position)} · ${r.observations} ${t('rates.obs')}</small></div>`;
    case 'forecast_rate':
      return `<div class="rcard"><span class="eyebrow">${tag('forecast')}</span>${r.available ? `<div class="big-num">${num(r.point, 6)}</div><small class="muted">80%: ${num(r.interval_80[0], 6)} – ${num(r.interval_80[1], 6)} · ${r.beats_baseline ? t('forecast.beats') : t('forecast.not_beats')}</small>` : `<small>${esc(r.reason)}</small>`}</div>`;
    case 'compare_options':
      return `<div class="rcard"><span class="eyebrow">${t('agent.comparison')}</span>${r.options.slice(0, 4).map(o => `<div class="kv">${tag(o.kind)}<span>${esc(t('option.' + o.id))}</span>${amt(r.mode === 'send' ? o.receive : o.send, r.mode === 'send' ? r.target : r.source)}</div>`).join('')}<button class="link" data-action="go" data-view="send">${t('agent.open_compare')} ${icons.arrow}</button></div>`;
    case 'scenario':
      return `<div class="rcard"><span class="eyebrow">${tag('scenario')}</span><div class="kv"><span>${t('scenario.now')}</span>${amt(r.receive_now, r.target)}</div><div class="kv"><span>${t('scenario.then', {p: pct(r.rate_change_pct)})}</span>${amt(r.receive_scenario, r.target)}</div><div class="kv"><span>${t('scenario.extra')}</span>${amt(r.extra_needed, r.source)}</div></div>`;
    case 'prepare_payment': case 'modify_payment': case 'get_payment': case 'execute_payment': case 'reconcile_payment': {
      const b = r.details;
      const cta = r.status === 'draft' ? (isOwner() ? t('agent.review_authorize') : t('agent.view')) : t('agent.view');
      const lacking = (r.checks || []).find(c => c.id === 'available_funds' && c.status === 'fail');
      const fund = lacking && isOwner() && b.rail !== 'evm' ? `<button class="button sm ghost" data-action="fund" data-currency="${esc(b.source)}">${icons.plus}${t('agent.add_funds', {c: b.source})}</button>` : '';
      return `<div class="rcard draft"><div class="kv"><span class="env env-${esc(b.rail)}"><i></i>${esc(envLabel(b))}</span>${chip(r.status)}</div><div class="flow-amt"><span class="flow-side"><small>${t('detail.you_send')}</small>${amt(b.value, b.source, 'lg')}</span><span class="flow-arrow">${icons.arrow}</span><span class="flow-side"><small>${t('detail.they_receive')} · ${esc(b.recipient.name)}</small>${amt(b.receive, b.target, 'lg')}</span></div><small class="muted">${esc(b.recipient.name)} · ${esc(b.purpose)} · ${t('detail.fee')} ${esc(money(b.fee, b.source))} ${esc(b.source)}</small><div class="row-actions"><button class="button primary sm" data-action="detail" data-id="${esc(r.id)}">${cta} ${icons.arrow}</button>${fund}</div></div>`;
    }
    case 'remember_note':
      return `<div class="rcard"><span class="eyebrow">${t('memory.saved')}</span><p>“${esc(r.text)}”</p><small class="muted">${esc(t('memory.kind.' + r.kind))}</small><button class="link" data-action="go" data-view="memory">${t('nav.memory')} ${icons.arrow}</button></div>`;
    case 'forget_note':
      return `<div class="rcard"><span class="eyebrow">${t('memory.forgotten')}</span><button class="link" data-action="go" data-view="memory">${t('nav.memory')} ${icons.arrow}</button></div>`;
    case 'recall_memory':
      return `<div class="rcard"><span class="eyebrow">${t('memory.recall_card')}</span>${r.notes.length || r.episodes.length ? r.notes.map(n => `<p>· ${esc(n.text)}</p>`).join('') + r.episodes.slice(0, 3).map(e => `<small class="muted">${when(e.time)} — “${esc(e.request.slice(0, 80))}”</small>`).join('') : `<p>${t('memory.empty')}</p>`}</div>`;
    case 'request_recipient_details':
      return `<div class="rcard form-card"><span class="eyebrow">${t('agent.form_title')}</span><p>${t('agent.form_card')}</p>${state.chat.form ? `<button class="button sm" data-action="open-side-form">${t('agent.form_open')} ${icons.arrow}</button>` : `<small class="muted">${t('agent.form_done')}</small>`}</div>`;
    case 'propose_change': {
      const rows = Object.entries(r.payload || {}).map(([k, v]) => `<div><dt>${esc(has('field.' + k) ? t('field.' + k) : k)}</dt><dd>${esc(v)}</dd></div>`).join('');
      const act = r.status === 'pending' && isOwner()
        ? `<div class="row-actions"><button class="button sm primary" data-action="chat-decide" data-id="${esc(r.id)}" data-accept="1">${icons.check}${t('agent.confirm')}</button><button class="button sm ghost" data-action="chat-decide" data-id="${esc(r.id)}" data-accept="0">${t('agent.reject')}</button></div>`
        : r.status === 'pending' ? `<button class="link" data-action="go" data-view="autonomy">${t('agent.review_proposal')} ${icons.arrow}</button>` : '';
      return `<div class="rcard proposal-card p-${esc(r.status)}"><div class="kv"><span class="eyebrow">${t('agent.proposal')} · ${esc(t('proposal.kind.' + r.kind))}</span>${chip(r.status, 'proposal.status')}</div><dl class="facts compact">${rows}</dl>${act}</div>`;
    }
    case 'wallet_info':
      return r.available ? `<div class="rcard"><span class="eyebrow">${t('kind.onchain')}</span><div class="kv"><span class="mono">${esc(r.address.slice(0, 8))}…${esc(r.address.slice(-6))}</span>${r.connected ? amt(r.balance, 'ETH') : t('wallets.rpc_down')}</div><small class="muted">${t('wallets.mandates_active', {n: r.mandates.length})}</small></div>` : `<div class="rcard"><small>${t('wallets.unavailable')}</small></div>`;
    case 'reminders':
      return `<div class="rcard"><span class="eyebrow">${t('shell.reminders')}</span>${r.length ? r.slice(0, 3).map(x => `<p>· ${esc(t('reminder.' + x.kind, x.data))}</p>`).join('') : `<p>${t('reminder.none')}</p>`}</div>`;
    case 'goals_overview':
      return `<div class="rcard"><span class="eyebrow">${t('nav.plans')}</span>${r.length ? r.slice(0, 3).map(g => `<div class="kv"><span>${esc(g.title)}</span>${amt(g.remaining, g.target)}</div>`).join('') : `<p>${t('plans.empty')}</p>`}</div>`;
    case 'habits_overview':
      return `<div class="rcard"><span class="eyebrow">${t('habits.indicator')}</span><p>${r.indicator.on_time_pct ?? '—'}% · ${t('habits.streak')} ${r.indicator.streak}</p><small class="muted">${t('habits.not_score')}</small></div>`;
    default:
      return '';
  }
}

function stepRow(s) {
  const tier = TOOL_TIER[s.tool] || 'view';
  return `<li class="step st-${esc(s.status)}"><span class="step-dot"></span><span class="step-name">${esc(has('tool.' + s.tool) ? t('tool.' + s.tool) : s.tool)}</span><span class="tier-badge t${TIERS[tier]}">T${TIERS[tier]}</span></li>`;
}

export function message(m) {
  m.key ??= ++keySeq;
  if (m.role === 'user') return `<div class="msg user" data-key="${m.key}"><div class="bubble">${esc(m.text)}</div></div>`;
  if (m.role === 'note') return `<div class="msg note"><p>${esc(m.text)}</p></div>`;
  const steps = m.steps.filter(s => s.tool !== 'record_plan');
  const plan = m.plan;
  const entities = plan ? Object.entries(plan.entities || {}).filter(([, v]) => v && typeof v !== 'object') : [];
  return `<div class="msg bot ${m.done ? 'done' : 'live'}" data-key="${m.key}">
    <div class="who"><span class="agent-orb sm"><i></i></span>DOT <span class="mode-badge m-${esc(m.mode || 'model')}">${t('agent.mode.' + (m.mode || 'model'))}</span></div>
    ${m.note ? `<p class="mode-note">${esc(t('agent.offline_note'))}</p>` : ''}
    <div class="stages">
      <section class="stage ${plan ? 'on' : 'wait'}"><span class="stage-n">01</span><div><b>${t('agent.understand')}</b>${plan ? `<p>${esc(t('intent.' + plan.intent) !== 'intent.' + plan.intent ? t('intent.' + plan.intent) : plan.intent)}</p><div class="entity-row">${entities.map(([k, v]) => `<span class="entity"><small>${esc(t('entity.' + k))}</small>${esc(v)}</span>`).join('')}</div>${plan.missing?.length ? `<p class="missing">${t('agent.missing')}: ${plan.missing.map(esc).join(', ')}</p>` : ''}` : `<div class="thinking"><span class="think-orb"><i></i></span><span class="think-text">${t('agent.thinking')}</span></div>`}</div></section>
      <section class="stage ${steps.length ? 'on' : plan ? 'on' : 'wait'}"><span class="stage-n">02</span><div><b>${t('agent.plan')}</b>${steps.length ? `<ol class="steps">${steps.map(stepRow).join('')}</ol>` : plan ? `<p class="muted">${t(plan.missing?.length ? 'agent.plan_wait' : 'agent.plan_none')}</p>` : ''}</div></section>
      <section class="stage ${steps.some(s => s.status !== 'planned') ? 'on' : 'wait'}"><span class="stage-n">03</span><div><b>${t('agent.act')}</b><div class="rcards">${steps.map(card).join('')}</div></div></section>
    </div>
    ${m.text ? `<div class="answer md">${md(m.text)}</div>` : m.done ? '' : `<div class="typing"><i></i><i></i><i></i><span>${t('agent.writing')}</span></div>`}
  </div>`;
}

export function chatLog(limit) {
  const list = limit ? state.chat.messages.slice(-limit) : state.chat.messages;
  const welcome = `<div class="msg bot welcome done" data-key="welcome-${state.model ? 1 : 0}"><div class="who"><span class="agent-orb sm"><i></i></span>DOT</div><div class="answer">${t('agent.welcome')}</div>${!state.model ? `<p class="mode-note">${t('agent.offline_hint')}</p>` : ''}<div class="suggestions">${suggestions().map(s => `<button class="pill" data-action="prompt" data-prompt="${esc(s)}">${esc(s)}</button>`).join('')}</div></div>`;
  return welcome + list.map(message).join('');
}

export function composer(id = 'chat-form') {
  const busy = state.chat.streaming;
  return `<form id="${id}" class="composer" data-chat><textarea name="message" rows="1" maxlength="4000" aria-label="${t('agent.input')}" placeholder="${t('agent.placeholder')}" ${busy ? 'disabled' : ''}></textarea><button class="send-button" aria-label="${t('agent.send')}" ${busy ? 'disabled' : ''}>${busy ? '<span class="spinner"></span>' : '↑'}</button></form>`;
}

export function pipeline() {
  const last = [...state.chat.messages].reverse().find(m => m.role === 'assistant');
  const steps = last ? last.steps.filter(s => s.tool !== 'record_plan') : [];
  const stage = !last ? 0 : last.done ? 3 : steps.some(s => s.status !== 'planned') ? 3 : last.plan ? 2 : 1;
  const nodes = steps.slice(0, 8).map((s, i, a) => {
    const angle = -Math.PI / 2 + (i + .5) / Math.max(a.length, 1) * Math.PI * 2;
    return `<g class="pnode st-${esc(s.status)}"><circle cx="${(160 + Math.cos(angle) * 128).toFixed(1)}" cy="${(160 + Math.sin(angle) * 128).toFixed(1)}" r="6"/></g>`;
  }).join('');
  return `<svg class="pipeline-orbit" viewBox="0 0 320 320" role="img" aria-label="${t('agent.pipeline')}">
    <circle class="ring r3 ${stage >= 3 ? 'on' : ''}" cx="160" cy="160" r="128"/><circle class="ring r2 ${stage >= 2 ? 'on' : ''}" cx="160" cy="160" r="88"/><circle class="ring r1 ${stage >= 1 ? 'on' : ''}" cx="160" cy="160" r="50"/>
    <g class="spin ${state.chat.streaming ? 'go' : ''}"><circle cx="160" cy="32" r="3"/><circle cx="160" cy="288" r="2"/></g>
    <circle class="core" cx="160" cy="160" r="24"/><text x="160" y="164" text-anchor="middle" class="core-text">dot.</text>
    <text x="160" y="104" text-anchor="middle" class="ring-label">${t('agent.understand').toUpperCase()}</text>
    <text x="160" y="66" text-anchor="middle" class="ring-label">${t('agent.plan').toUpperCase()}</text>
    <text x="160" y="26" text-anchor="middle" class="ring-label">${t('agent.act').toUpperCase()}</text>${nodes}</svg>`;
}

export const view = {
  id: 'agent',
  submit: {
    async 'side-recipient-form'(form) {
      const v = Object.fromEntries(new FormData(form));
      const f = state.chat.form || {};
      if ((state.data.recipients || []).some(r => r.id === v.recipient_id)) throw new Error(t('wallets.r_exists'));
      const body = {recipient_id: v.recipient_id.trim(), name: v.name.trim(), currency: v.currency, country: v.country || '',
        account: (v.account || '').replace(/\s+/g, ''), kind: 'individual', address: '', enabled: true};
      const proposal = f.proposalId;
      const same = proposal && f.prefill && ['name', 'currency'].every(k => (f.prefill[k] || '') === body[k]) && (f.prefill.recipient_id || body.recipient_id) === body.recipient_id;
      if (same) await api(`/proposals/${encodeURIComponent(proposal)}/decide`, 'POST', {accept: true});
      else {
        if (proposal) await api(`/proposals/${encodeURIComponent(proposal)}/decide`, 'POST', {accept: false, note: 'replaced by owner-entered details'});
        await api('/recipients', 'POST', body);
      }
      let raised = false;
      if (v.raise) { await api('/settings/tier', 'PUT', {tier: 2}); raised = true; }
      for (const m of state.chat.messages) for (const st of m.steps || []) if (proposal && st.result?.id === proposal) st.result = {...st.result, status: same ? 'confirmed' : 'rejected'};
      state.chat.form = null;
      paintSideForm();
      invalidate(['recipients', 'settings', 'proposals']);
      toast(t('wallets.saved'), 'good');
      send(t('agent.form_done_msg', {name: body.name, id: body.recipient_id, currency: body.currency}) + (raised ? ' ' + t('agent.after_tier', {n: 2}) : ''));
    },
  },
  needs: ['settings', 'mandates', 'recipients'],
  mount(root) {
    root.querySelectorAll('#chat-log').forEach(log => { log.scrollTop = log.scrollHeight; });
    const host = root.querySelector('#side-form-host');
    if (host && state.chat.form) { host.innerHTML = ''; paintSideForm(); }
  },
  actions: {
    /* One-click owner decisions inside the chat; the agent then continues on its own. */
    async 'chat-decide'(el) {
      const accept = el.dataset.accept === '1';
      const result = await api(`/proposals/${encodeURIComponent(el.dataset.id)}/decide`, 'POST', {accept});
      for (const m of state.chat.messages) for (const st of m.steps || []) if (st.result?.id === result.id) st.result = result;
      invalidate(); paint();
      toast(t(accept ? 'autonomy.confirmed' : 'autonomy.rejected'), accept ? 'good' : '');
      if (accept) send(t('agent.after_confirm'));
    },
    'open-side-form'() {
      if (state.view !== 'agent') { location.hash = 'agent'; return; }
      const host = document.getElementById('side-form-host');
      host?.classList.remove('nudge'); void host?.offsetWidth; host?.classList.add('nudge');
      host?.scrollIntoView({behavior: 'smooth', block: 'start'});
    },
    'close-side-form'() { state.chat.form = null; paintSideForm(); paint(); },
    async 'chat-tier'(el) {
      const n = Number(el.dataset.tier);
      await api('/settings/tier', 'PUT', {tier: n});
      invalidate(['settings']); toast(t('autonomy.tier_set', {n}), 'good');
      send(t('agent.after_tier', {n}));
    },
  },
  render() {
    const tier = state.data.settings?.agent_tier ?? 3;
    return `<div class="agent-layout">
      ${panel(`<span class="agent-orb"><i></i></span>${t('agent.title')}`, `<div class="chat-log" id="chat-log">${chatLog()}</div>${composer()}<p class="fine">${t('agent.disclaimer')}</p>`, {cls: 'chat-panel', sub: state.model ? `${t('agent.mode.model')}${state.modelName ? ' · ' + esc(state.modelName) : ''}` : t('agent.mode.rules')})}
      <div class="agent-side">
        <div id="side-form-host" class="side-form-host">${sideForm()}</div>
        ${panel(t('agent.pipeline'), `<div class="pipeline-wrap" id="pipeline">${pipeline()}</div><ol class="legend"><li><b>01</b>${t('agent.understand_d')}</li><li><b>02</b>${t('agent.plan_d')}</li><li><b>03</b>${t('agent.act_d')}</li></ol>`, {cls: 'tilt'})}
        ${panel(t('agent.boundary'), `<div class="tier-meter">${[1, 2, 3].map(n => `<span class="${n <= tier ? 'on' : ''}"><b>T${n}</b>${t('tier.' + n)}</span>`).join('')}</div><p class="fine">${t('agent.boundary_d')}</p><button class="link" data-action="go" data-view="autonomy">${t('agent.manage_boundary')} ${icons.arrow}</button>`)}
      </div></div>`;
  },
};

/* ---------- sending a message: streams the understand -> plan -> act events ---------- */
export async function send(text) {
  text = text.trim();
  if (!text || state.chat.streaming) return;
  if (!canPrepare()) { toast(t('err.chat_role'), 'bad'); return; }
  state.chat.messages.push({role: 'user', text});
  const m = {role: 'assistant', text: '', steps: [], plan: null, done: false, mode: state.model ? 'model' : 'rules'};
  state.chat.messages.push(m);
  state.chat.streaming = true;
  paint();
  try {
    for await (const e of stream('/chat/stream', {message: text, session: state.chat.session, language: lang})) {
      if (e.type === 'start') { m.mode = e.mode; m.note = e.note; }
      if (e.type === 'understand') m.plan = e;
      if (e.type === 'plan') m.steps = (e.steps || []).map(s => ({tool: s.tool, status: 'planned'}));
      if (e.type === 'tool') {
        const s = m.steps.find(x => x.tool === e.tool && x.status === 'planned');
        if (s) s.status = 'running'; else m.steps.push({tool: e.tool, status: 'running'});
      }
      if (e.type === 'tool_result') {
        const s = m.steps.find(x => x.tool === e.tool && x.status === 'running') || {};
        Object.assign(s, {status: e.ok ? 'ok' : 'fail', result: e.result, error: e.error, code: e.code, params: e.params});
        if (['prepare_payment', 'modify_payment', 'execute_payment', 'reconcile_payment', 'propose_change'].includes(e.tool)) invalidate();
        if (e.ok && e.tool === 'request_recipient_details') openForm(e.result.prefill, {reason: ''});
        if (e.ok && e.tool === 'propose_change' && e.result.kind === 'recipient' && e.result.status === 'pending' && isOwner())
          openForm(e.result.payload, {proposalId: e.result.id});
      }
      if (e.type === 'message') m.text = e.text || (e.code ? t('err.' + e.code) : '');
      if (e.type === 'done') m.done = true;
      paint();
    }
  } catch (e) {
    m.text = e.message;
  } finally {
    m.done = true;
    m.steps.forEach(s => { if (s.status === 'running' || s.status === 'planned') s.status = s.status === 'running' ? 'fail' : 'skipped'; });
    state.chat.streaming = false;
    paint();
    bus.flush?.();  // page refreshes held back while streaming
    document.querySelector('[data-chat] textarea')?.focus();
  }
}

/** Patch old DOM to match new DOM, keeping unchanged nodes so nothing replays its entrance animation. */
function morph(old, next) {
  if (old.nodeType !== next.nodeType || old.nodeName !== next.nodeName ||
      (old.nodeType === 1 && old.dataset.key !== next.dataset.key)) { old.replaceWith(next); return; }
  if (old.nodeType === 3) { if (old.textContent !== next.textContent) old.textContent = next.textContent; return; }
  if (old.nodeType !== 1 || old.isEqualNode(next)) return;
  for (const at of [...old.attributes]) if (!next.hasAttribute(at.name)) old.removeAttribute(at.name);
  for (const at of [...next.attributes]) if (old.getAttribute(at.name) !== at.value) old.setAttribute(at.name, at.value);
  const fresh = [...next.childNodes], kids = [...old.childNodes];
  fresh.forEach((n, i) => { if (kids[i]) morph(kids[i], n); else old.appendChild(n); });
  for (let i = fresh.length; i < kids.length; i++) kids[i].remove();
}

/** Repaints only the conversation and pipeline, in place, so streaming never flickers. */
export function paint() {
  for (const log of document.querySelectorAll('#chat-log, #mini-chat-log')) {
    const limit = log.id === 'mini-chat-log' ? 2 : 0;
    const stick = log.scrollHeight - log.scrollTop - log.clientHeight < 120;
    const next = log.cloneNode(false);
    next.innerHTML = chatLog(limit);
    morph(log, next);
    if (stick) log.scrollTo({top: log.scrollHeight, behavior: 'smooth'});
  }
  for (const form of document.querySelectorAll('[data-chat]')) {
    const ta = form.querySelector('textarea'), btn = form.querySelector('button');
    ta.disabled = btn.disabled = state.chat.streaming;
    const icon = state.chat.streaming ? 'busy' : 'idle';
    if (btn.dataset.icon !== icon) { btn.dataset.icon = icon; btn.innerHTML = state.chat.streaming ? '<span class="spinner"></span>' : '↑'; }
    form.classList.toggle('busy', state.chat.streaming);
  }
  const p = document.getElementById('pipeline');
  if (p) { const next = p.cloneNode(false); next.innerHTML = pipeline(); morph(p, next); }
}


/* ---------- recipient form that slides out beside the chat ---------- */
export function sideForm() {
  const f = state.chat.form;
  if (!f) return '';
  const p = f.prefill || {};
  const currency = FORM_CURRENCIES.includes(p.currency) ? p.currency : 'CNY';
  const country = p.country || CUR_TO_ECON[currency] || '';
  const tier = state.data.settings?.agent_tier ?? 3;
  const owner = isOwner();
  const econ = Object.keys(CUR_TO_ECON).map(c => CUR_TO_ECON[c]);
  return `<div class="side-form" data-key="${f.key}">
    <div class="side-form-head"><span class="side-form-orb"><i></i></span><div><b>${t('agent.form_title')}</b><small>${t('agent.form_intro')}</small></div>
      <button type="button" class="x" data-action="close-side-form" aria-label="${t('common.close')}">×</button></div>
    ${f.reason ? `<p class="fine">${esc(f.reason)}</p>` : ''}
    <form id="side-recipient-form" class="form-block" data-key="${f.key}">
      <div class="field"><label for="sf-name">${t('wallets.r_name')}</label><input id="sf-name" name="name" required maxlength="100" value="${esc(p.name || '')}" ${owner ? '' : 'disabled'}></div>
      <div class="field"><label for="sf-id">${t('wallets.r_id')}</label><input id="sf-id" name="recipient_id" required pattern="[A-Za-z0-9_\\-]{1,64}" maxlength="64" value="${esc(p.recipient_id || slug(p.name) || '')}" ${owner ? '' : 'disabled'}><small>${t('wallets.r_id_hint')}</small></div>
      <div class="grid-2"><div class="field"><label for="sf-currency">${t('wallets.r_currency')}</label><select id="sf-currency" name="currency" ${owner ? '' : 'disabled'}>${FORM_CURRENCIES.map(c => `<option ${c === currency ? 'selected' : ''}>${c}</option>`).join('')}</select></div>
      <div class="field"><label for="sf-country">${t('wallets.r_country')}</label><select id="sf-country" name="country" ${owner ? '' : 'disabled'}><option value="">—</option>${[...new Set(econ)].map(c => `<option value="${c}" ${c === country ? 'selected' : ''}>${esc(region(c))}</option>`).join('')}</select></div></div>
      <div class="field"><label for="sf-account">${t('wallets.r_account')}</label><input id="sf-account" name="account" maxlength="34" placeholder="${t('wallets.r_account_ph')}" ${owner ? '' : 'disabled'}><small>${t('wallets.r_account_hint')}</small></div>
      ${owner && tier < 2 ? `<label class="check-label"><input type="checkbox" name="raise" checked> ${t('agent.form_allow_t2')}</label>` : ''}
      ${owner ? '' : `<p class="note warn">${t('agent.form_owner_only')}</p>`}
      <div class="form-error"></div>
      <div class="row-actions"><button class="button primary" ${owner ? '' : 'disabled'}>${icons.check}${t('agent.form_submit')}</button><button type="button" class="button ghost" data-action="close-side-form">${t('agent.form_cancel')}</button></div>
    </form></div>`;
}

let formSeq = 0;
function openForm(prefill, extra = {}) {
  state.chat.form = {key: ++formSeq, prefill, ...extra};
  paintSideForm();
}

/** Slides the form in or out without touching anything the user is typing. */
export function paintSideForm() {
  const host = document.getElementById('side-form-host');
  if (!host) return;
  const f = state.chat.form;
  const shown = host.firstElementChild;
  if (f && shown?.dataset.key === String(f.key)) return;
  if (!f) {
    if (shown) { shown.classList.add('leaving'); setTimeout(() => { if (!state.chat.form) host.innerHTML = ''; }, 460); }
    return;
  }
  host.innerHTML = sideForm();
  // Jelly entrance: the panel springs in, then each row follows a beat later.
  host.querySelectorAll('.side-form-head, .side-form .field, .side-form .check-label, .side-form .row-actions, .side-form .fine, .side-form .note')
    .forEach((el, i) => { el.style.animationDelay = (260 + i * 60) + 'ms'; });
  const form = host.querySelector('#side-recipient-form');
  const name = form.querySelector('#sf-name'), id = form.querySelector('#sf-id');
  let touched = false;
  id.addEventListener('input', () => { touched = true; });
  name.addEventListener('input', () => { if (!touched) id.value = slug(name.value) || id.value; });
  form.querySelector('#sf-currency').addEventListener('change', e => {
    const c = CUR_TO_ECON[e.target.value]; if (c) form.querySelector('#sf-country').value = c;
  });
  if (matchMedia('(max-width: 1280px)').matches) host.scrollIntoView({behavior: 'smooth', block: 'start'});
  setTimeout(() => (name.value ? id : name).focus({preventScroll: true}), 420);
}
