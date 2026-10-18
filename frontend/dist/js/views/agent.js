import {state, t, toast, isOwner, canPrepare, invalidate, $, go} from '../core.js';
import {stream} from '../api.js';
import {esc, chip, amt, tag, mono, short, icons, panel} from '../ui.js';
import {lang, money, num, day, pct, has} from '../i18n.js';
import {sparkline} from '../charts.js';
import {envLabel} from './payments.js';

const TIERS = {view: 1, prepare: 2, submit: 3};
const TOOL_TIER = {prepare_payment: 'prepare', modify_payment: 'prepare', reconcile_payment: 'prepare', propose_change: 'prepare', execute_payment: 'submit'};

export const suggestions = () => [t('agent.s1'), t('agent.s2'), t('agent.s3'), t('agent.s4')];

function card(step) {
  const r = step.result;
  if (step.status === 'fail') return `<div class="rcard fail"><b>${t('agent.blocked')}</b><p>${esc(step.code && has('err.' + step.code) ? t('err.' + step.code) : step.error)}</p></div>`;
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
      return `<div class="rcard draft"><div class="kv"><span class="env env-${esc(b.rail)}"><i></i>${esc(envLabel(b))}</span>${chip(r.status)}</div><div class="flow-amt">${amt(b.value, b.source, 'lg')}<span>${icons.arrow}</span>${amt(b.receive, b.target, 'lg')}</div><small class="muted">${esc(b.recipient.name)} · ${esc(b.purpose)} · ${t('detail.fee')} ${esc(money(b.fee, b.source))} ${esc(b.source)}</small><button class="button primary sm" data-action="detail" data-id="${esc(r.id)}">${cta} ${icons.arrow}</button></div>`;
    }
    case 'propose_change':
      return `<div class="rcard"><span class="eyebrow">${t('agent.proposal')}</span><p>${esc(t('proposal.kind.' + r.kind))} · ${chip(r.status, 'proposal.status')}</p><button class="link" data-action="go" data-view="autonomy">${t('agent.review_proposal')} ${icons.arrow}</button></div>`;
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
  if (m.role === 'user') return `<div class="msg user"><div class="bubble">${esc(m.text)}</div></div>`;
  if (m.role === 'note') return `<div class="msg note"><p>${esc(m.text)}</p></div>`;
  const steps = m.steps.filter(s => s.tool !== 'record_plan');
  const plan = m.plan;
  const entities = plan ? Object.entries(plan.entities || {}).filter(([, v]) => v && typeof v !== 'object') : [];
  return `<div class="msg bot ${m.done ? 'done' : 'live'}">
    <div class="who"><span class="agent-orb sm"><i></i></span>DOT <span class="mode-badge m-${esc(m.mode || 'model')}">${t('agent.mode.' + (m.mode || 'model'))}</span></div>
    ${m.note ? `<p class="mode-note">${esc(t('agent.offline_note'))}</p>` : ''}
    <div class="stages">
      <section class="stage ${plan ? 'on' : 'wait'}"><span class="stage-n">01</span><div><b>${t('agent.understand')}</b>${plan ? `<p>${esc(t('intent.' + plan.intent) !== 'intent.' + plan.intent ? t('intent.' + plan.intent) : plan.intent)}</p><div class="entity-row">${entities.map(([k, v]) => `<span class="entity"><small>${esc(t('entity.' + k))}</small>${esc(v)}</span>`).join('')}</div>${plan.missing?.length ? `<p class="missing">${t('agent.missing')}: ${plan.missing.map(esc).join(', ')}</p>` : ''}` : `<p class="muted">${t('agent.thinking')}</p>`}</div></section>
      <section class="stage ${steps.length ? 'on' : plan ? 'on' : 'wait'}"><span class="stage-n">02</span><div><b>${t('agent.plan')}</b>${steps.length ? `<ol class="steps">${steps.map(stepRow).join('')}</ol>` : plan ? `<p class="muted">${t(plan.missing?.length ? 'agent.plan_wait' : 'agent.plan_none')}</p>` : ''}</div></section>
      <section class="stage ${steps.some(s => s.status !== 'planned') ? 'on' : 'wait'}"><span class="stage-n">03</span><div><b>${t('agent.act')}</b><div class="rcards">${steps.map(card).join('')}</div></div></section>
    </div>
    ${m.text ? `<div class="answer">${esc(m.text)}</div>` : m.done ? '' : '<div class="typing"><i></i><i></i><i></i></div>'}
  </div>`;
}

export function chatLog(limit) {
  const list = limit ? state.chat.messages.slice(-limit) : state.chat.messages;
  const welcome = `<div class="msg bot welcome done"><div class="who"><span class="agent-orb sm"><i></i></span>DOT</div><div class="answer">${t('agent.welcome')}</div>${!state.model ? `<p class="mode-note">${t('agent.offline_hint')}</p>` : ''}<div class="suggestions">${suggestions().map(s => `<button class="pill" data-action="prompt" data-prompt="${esc(s)}">${esc(s)}</button>`).join('')}</div></div>`;
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
  needs: ['settings', 'mandates', 'recipients'],
  render() {
    const tier = state.data.settings?.agent_tier ?? 3;
    return `<div class="agent-layout">
      ${panel(`<span class="agent-orb"><i></i></span>${t('agent.title')}`, `<div class="chat-log" id="chat-log">${chatLog()}</div>${composer()}<p class="fine">${t('agent.disclaimer')}</p>`, {cls: 'chat-panel', sub: state.model ? `${t('agent.mode.model')}${state.modelName ? ' · ' + esc(state.modelName) : ''}` : t('agent.mode.rules')})}
      <div class="agent-side">
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
        Object.assign(s, {status: e.ok ? 'ok' : 'fail', result: e.result, error: e.error, code: e.code});
        if (['prepare_payment', 'modify_payment', 'execute_payment', 'reconcile_payment', 'propose_change'].includes(e.tool)) invalidate();
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
    document.querySelector('[data-chat] textarea')?.focus();
  }
}

/** Repaints only the conversation and pipeline so typing elsewhere is never interrupted. */
export function paint() {
  for (const log of document.querySelectorAll('#chat-log, #mini-chat-log')) {
    const limit = log.id === 'mini-chat-log' ? 2 : 0;
    const stick = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
    log.innerHTML = chatLog(limit);
    if (stick || state.chat.streaming) log.scrollTop = log.scrollHeight;
  }
  for (const form of document.querySelectorAll('[data-chat]')) {
    const ta = form.querySelector('textarea'), btn = form.querySelector('button');
    ta.disabled = btn.disabled = state.chat.streaming;
    btn.innerHTML = state.chat.streaming ? '<span class="spinner"></span>' : '↑';
  }
  const p = document.getElementById('pipeline');
  if (p) p.innerHTML = pipeline();
}
