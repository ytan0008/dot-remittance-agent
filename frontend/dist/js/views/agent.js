import {state, t, toast, isOwner, canPrepare, invalidate, api, bus} from '../core.js';
import {stream} from '../api.js';
import {esc, chip, amt, tag, icons, panel, field, options} from '../ui.js';
import {lang, money, num, day, pct, has, region} from '../i18n.js';
import {sparkline} from '../charts.js';
import {envLabel} from './payments.js';
import {jellyBoard, buzz} from '../jelly.js';

const CUR_TO_ECON = {AUD: 'AU', CNY: 'CN', VND: 'VN', USD: 'US', PHP: 'PH', MXN: 'MX', JPY: 'JP', KRW: 'KR', HKD: 'HK', TWD: 'TW',
  SGD: 'SG', NZD: 'NZ', CAD: 'CA', MYR: 'MY', THB: 'TH', IDR: 'ID', CLP: 'CL', PEN: 'PE', RUB: 'RU', BND: 'BN', PGK: 'PG'};
const FORM_CURRENCIES = ['AUD', 'CNY', 'USD', 'VND', 'PHP', 'MXN', 'JPY', 'KRW', 'HKD', 'TWD', 'SGD', 'NZD', 'CAD', 'MYR', 'THB', 'IDR'];
const CURRENCIES = ['AUD', 'CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'SGD', 'CAD', 'NZD', 'KRW', 'VND', 'INR', 'CHF'];
const FORMATS = ['swift', 'sepa', 'au_bsb', 'uk_fps', 'us_ach', 'cn_cnaps', 'in_neft'];
const BOARD_MAX = 6;
const slug = name => (name || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
const toolName = tool => has('tool.' + tool) ? t('tool.' + tool) : tool;
let keySeq = 0, board = null, formats = null;
const fmts = () => formats || state.data.tformats;  // page refreshes may drop state.data; the open form must not lose it

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

/* ---------- result cards: every useful tool result becomes a jelly card that says something and leads somewhere ---------- */

const go = (view, label = t('nav.' + view)) => `<button class="link sm" data-action="go" data-view="${view}">${esc(label)} ${icons.arrow}</button>`;
const line = (k, v) => `<div class="kv"><span>${esc(k)}</span>${v}</div>`;

/** {title, body, foot, cls} for one finished step, or null when it has nothing worth showing on its own. */
function cardFor(step) {
  const r = step.result;
  if (step.status === 'fail') {
    return {title: t('agent.blocked'), cls: 'fail', body: `<p>${esc(step.code && has('err.' + step.code) ? t('err.' + step.code, step.params) : step.error || '')}</p>`, foot: ''};
  }
  if (step.status !== 'ok' || !r) return null;
  switch (step.tool) {
    case 'get_balances': {
      const list = (Array.isArray(r) ? r : []).filter(b => b.total !== null).slice(0, 3);
      return {title: t('kind.ledger'), body: list.map(b => line(b.currency, amt(b.available, b.currency))).join('') || `<p>—</p>`, foot: go('sandbox')};
    }
    case 'latest_rate':
      return {title: `${r.source} → ${r.target}`, body: `<b class="ac-big">${num(r.rate, 6)}</b><small>${esc(r.provider)} · ${day(r.observed)}${r.change_pct ? ' · ' + pct(r.change_pct, 3) : ''}</small>`, foot: go('markets')};
    case 'rate_history':
      return {title: t('kind.historical'), body: `${sparkline(r.series)}<small>${t('rates.percentile')} ${num(r.percentile, 1)} · ${t('rates.position.' + r.position)}</small>`, foot: go('markets')};
    case 'forecast_rate':
      return {title: t('kind.forecast'), body: r.available ? `<b class="ac-big">${num(r.point, 6)}</b><small>80%: ${num(r.interval_80[0], 5)} – ${num(r.interval_80[1], 5)}</small>` : `<small>${esc(r.reason)}</small>`, foot: go('markets')};
    case 'compare_options': {
      const best = (r.options || [])[0];
      const value = o => amt(r.mode === 'send' ? o.receive : o.send, r.mode === 'send' ? r.target : r.source);
      return {title: t('agent.comparison'), body: best ? `<b class="ac-big">${value(best)}</b><small>${t('agent.c.best', {o: t('option.' + best.id)})} · ${t('agent.c.options', {n: r.options.length})}</small>` : '',
        foot: go('send', t('agent.open_compare'))};
    }
    case 'scenario':
      return {title: t('kind.scenario'), body: line(t('scenario.now'), amt(r.receive_now, r.target)) + line(t('scenario.then', {p: pct(r.rate_change_pct)}), amt(r.receive_scenario, r.target)), foot: go('send')};
    case 'exchange_advice': {
      const v = r.verdict || r.last?.verdict;
      return {title: `${r.source} → ${r.target}`, body: `${v ? `<span class="tag k-ai_${esc(v)}">${esc(t('kind.ai_' + v))}</span>` : ''}<p>${esc((r.explanation || r.reason || r.last?.explanation || t('agent.c.watching')).slice(0, 150))}</p>`, foot: go('overview')};
    }
    case 'plan_exchange':
      return {title: `${r.source} → ${r.target}`, body: `<b class="ac-big">${esc(money(r.amount, r.amount_currency))} <small>${esc(r.amount_currency)}</small></b><small>${esc(r.purpose || t('ov.kind.custom'))}${r.due ? ' · ' + day(r.due) : ''}</small>`, foot: go('overview', t('ov.p.title'))};
    case 'simulate_exchange': {
      const rows = (r.rows || []).filter(x => x.before || x.after).slice(0, 3);
      const short = (r.rows || []).filter(x => x.gap_after && x.known).length;
      return {title: t('ov.s.title'), cls: short ? 'fail' : '', body: rows.map(x => line(x.currency, `<b>${esc(money(x.before, x.currency))} → ${esc(money(x.after, x.currency))}</b>`)).join('')
        + `<small>${short ? t('agent.c.gaps', {n: short}) : t('agent.c.no_gaps')}</small>`, foot: go('overview')};
    }
    case 'money_overview': {
      const p = r.position || {};
      const need = (r.needs || [])[0];
      return {title: t('ov.cash_now'), body: `<b class="ac-big">${p.has_cash ? esc(money(p.total, p.display)) + ` <small>${esc(p.display)}</small>` : '—'}</b>${need ? `<small>${t('agent.c.need', {n: (r.needs || []).length})}</small>` : ''}`, foot: go('overview')};
    }
    case 'prepare_payment': case 'modify_payment': case 'get_payment': case 'reconcile_payment': {
      const b = r.details;
      if (!b) return null;
      const lacking = (r.checks || []).find(c => c.id === 'available_funds' && c.status === 'fail');
      const fund = lacking && isOwner() && b.rail !== 'evm' ? `<button class="button sm ghost" data-action="fund" data-currency="${esc(b.source)}">${icons.plus}${t('agent.add_funds', {c: b.source})}</button>` : '';
      return {title: esc(envLabel(b)), cls: 'draft', badge: chip(r.status),
        body: `<div class="ac-flow">${amt(b.value, b.source)}<span>${icons.arrow}</span>${amt(b.receive, b.target)}</div><small>${esc(b.recipient.name)} · ${t('detail.fee')} ${esc(money(b.fee, b.source))} ${esc(b.source)}</small>`,
        foot: `<button class="button primary sm" data-action="detail" data-id="${esc(r.id)}">${r.status === 'draft' && isOwner() ? t('agent.review_authorize') : t('agent.view')} ${icons.arrow}</button>${fund}`};
    }
    case 'list_payments':
      return {title: t('nav.payments'), body: `<b class="ac-big">${(r.items || r || []).length ?? 0}</b><small>${t('agent.c.payments')}</small>`, foot: go('payments')};
    case 'list_recipients':
      return {title: t('nav.wallets'), body: (Array.isArray(r) ? r : []).slice(0, 3).map(x => `<p>· ${esc(x.name)} <small>${esc(x.currency)}</small></p>`).join('') || '<p>—</p>', foot: go('wallets', t('send.tab_recipients'))};
    case 'remember_note':
      return {title: t('memory.saved'), body: `<p>“${esc(r.text)}”</p>`, foot: go('memory')};
    case 'forget_note':
      return {title: t('memory.forgotten'), body: '', foot: go('memory')};
    case 'recall_memory':
      return {title: t('memory.recall_card'), body: (r.notes || []).slice(0, 3).map(n => `<p>· ${esc(n.text)}</p>`).join('') || `<p>${t('memory.empty')}</p>`, foot: go('memory')};
    case 'propose_change': case 'do_action': {
      const pending = r.status === 'pending';
      const act = pending && isOwner()
        ? `<button class="button sm primary" data-action="chat-decide" data-id="${esc(r.id)}" data-accept="1">${icons.check}${t(r.kind === 'action' ? 'act.confirm' : 'agent.confirm')}</button><button class="button sm ghost" data-action="chat-decide" data-id="${esc(r.id)}" data-accept="0">${t('agent.reject')}</button>`
        : pending ? `<small>${t('act.owner')}</small>` : '';
      if (r.kind === 'action') {  // "Get this done for me": what will run, with which details — it runs only on Confirm
        const a = r.payload?.action, params = r.payload?.params || {};
        const val = v => typeof v === 'boolean' || v === 'true' || v === 'false' ? t(String(v) === 'true' ? 'act.yes' : 'act.no') : typeof v === 'object' && v ? Object.values(v).join(' ') : String(v);
        const rows = Object.entries(params).slice(0, 6).map(([k, v]) => line(has('act.p.' + k) ? t('act.p.' + k) : k, `<b>${esc(val(v))}</b>`)).join('');
        return {title: has('act.' + a) ? t('act.' + a) : a, cls: pending ? 'ask' : '', badge: chip(r.status, 'proposal.status'),
          body: `${r.note ? `<p>${esc(r.note)}</p>` : ''}${rows}`, foot: act};
      }
      const rows = Object.entries(r.payload || {}).slice(0, 3).map(([k, v]) => line(has('field.' + k) ? t('field.' + k) : k, `<b>${esc(v)}</b>`)).join('');
      return {title: `${t('agent.proposal')} · ${t('proposal.kind.' + r.kind)}`, badge: chip(r.status, 'proposal.status'), body: rows, foot: act};
    }
    case 'read_records': {
      const list = Array.isArray(r) ? r : null;
      const label = x => x.title || x.description || x.name || x.purpose || (x.source && x.target ? `${x.source} → ${x.target}` : '') || x.kind || '';
      return {title: t('act.records'), body: list ? (list.slice(0, 5).map(x => `<p>· ${esc(label(x))}</p>`).join('') || '<p>—</p>') + (list.length > 5 ? `<small>+${list.length - 5}</small>` : '') : '<p>✓</p>', foot: ''};
    }
    case 'sandbox_timeline':
      return {title: t('ov.s.title'), body: `<small>${day(r.today)} → ${day(r.end)}</small>${(r.negative || []).length ? `<p>${t('sb.low_neg', {a: '', d: ''})} ${esc(r.negative.join(', '))}</p>` : ''}`, foot: go('sandbox')};
    case 'bank_scenarios': {
      const best = (r.scenarios || [])[0];
      return {title: t('scen.title'), body: best ? `<b class="ac-big">${esc(money(best.total_receive, r.target))} <small>${esc(r.target)}</small></b><small>${t('scen.best')}</small>` : '<p>—</p>', foot: go('send')};
    }
    case 'request_details': {
      const fm = forms.get(step.formKey);
      const done = fm?.done;
      return {title: t('af.card'), cls: done ? 'done' : 'ask', badge: done ? `<span class="tag">${icons.check}${t('af.done')}</span>` : '',
        body: `<p>${esc(t('af.' + (r.form === 'watch' ? 'plan' : r.form) + '.title'))}</p>${!done && fm?.values && Object.values(fm.values).some(Boolean) ? `<small>${t('af.draft_kept')}</small>` : ''}`,
        foot: fm && !done ? `<button class="button sm primary" data-action="resume-form" data-key="${fm.key}">${t(state.chat.form?.key === fm.key ? 'agent.form_open' : 'af.resume')} ${icons.arrow}</button>` : ''};
    }
    case 'reminders':
      return {title: t('shell.reminders'), body: (Array.isArray(r) ? r : []).slice(0, 2).map(x => `<p>· ${esc(t('reminder.' + x.kind, x.data))}</p>`).join('') || `<p>${t('reminder.none')}</p>`, foot: go('overview')};
    case 'goals_overview': case 'goal_plan':
      return {title: t('nav.plans'), body: (Array.isArray(r) ? r : [r]).slice(0, 2).map(g => g.title ? line(g.title, amt(g.remaining, g.target)) : '').join('') || `<p>${t('plans.empty')}</p>`, foot: go('plans')};
    case 'habits_overview':
      return {title: t('habits.indicator'), body: `<b class="ac-big">${r.indicator?.on_time_pct ?? '—'}%</b><small>${t('habits.streak')} ${r.indicator?.streak ?? 0}</small>`, foot: go('habits')};
    case 'progress_overview': case 'start_challenge':
      return {title: t('nav.progress'), body: r.level ? `<b class="ac-big">Lv ${esc(r.level.level ?? r.level)}</b>` : `<p>${esc(r.kind ? t('agent.c.challenge') : '')}</p>`, foot: go('progress')};
    case 'log_expense': case 'spending_summary': case 'spending_insights': {
      const tip = (r.tips || [])[0];
      const head = r.total !== undefined ? `<b class="ac-big">${esc(money(r.total, r.currency))} <small>${esc(r.currency)}</small></b>` : r.description ? `<p>${esc(r.description)} · ${esc(money(Math.abs(r.amount), r.currency))} ${esc(r.currency)}</p>` : '';
      return {title: t('nav.spending'), body: head + (tip ? `<small>${esc(tip.text || t('insight.' + tip.id, tip.params || {}) || '')}</small>` : ''), foot: go('spending')};
    }
    case 'afford_check':
      return {title: t('afford.title'), cls: 'v-' + r.verdict, body: `<b class="ac-big">${esc(t('afford.v.' + r.verdict))}</b><small>${esc(r.label || '')} · ${esc(money(r.amount, r.currency))} ${esc(r.currency)}${r.wait_until ? ' · ' + esc(t('afford.wait', {d: day(r.wait_until)})) : ''}</small>`, foot: go('study')};
    case 'cashflow_plan':
      return {title: t('agent.c.cashflow'), body: r.lowest ? line(t('agent.c.lowest'), `<b>${esc(money(r.lowest.amount, r.currency))}</b>`) + `<small>${day(r.lowest.date)}${r.below_buffer ? ' · ' + t('agent.c.below_buffer') : ''}</small>` : '', foot: go('study')};
    case 'list_scholarships': case 'track_scholarship': {
      const list = Array.isArray(r) ? r : [r];
      return {title: t('agent.c.scholarships'), body: list.slice(0, 3).map(s => `<p>· ${esc(s.name)}${s.days_left != null ? ` <small>${t('agent.c.days', {n: s.days_left})}</small>` : ''}</p>`).join('') || '<p>—</p>', foot: go('study')};
    }
    case 'list_transfer_templates': case 'draft_transfer_template': case 'check_bank_details': {
      const list = Array.isArray(r) ? r : r.id ? [r] : [];
      const issues = (r.issues || []).filter(i => i.level === 'error').length;
      return {title: t('nav.templates'), body: list.length ? list.slice(0, 3).map(x => `<p>· ${esc(x.name)} <small>${esc(t('tf.fmt.' + x.format))}</small></p>`).join('')
        : `<p>${esc(t('tf.fmt.' + (r.format || 'swift')))} · ${issues ? t('tf.invalid') : t('tf.valid')}</p>`, foot: go('templates')};
    }
    case 'list_routes':
      return {title: t('nav.routes'), body: `<b class="ac-big">${(Array.isArray(r) ? r : []).length}</b>`, foot: go('routes', t('send.more_routes'))};
    default:
      return null;
  }
}

/** All cards for the conversation, newest first; each card keeps a stable id (message key + step index). */
function cards() {
  const out = [];
  for (const m of state.chat.messages) {
    if (m.role !== 'assistant') continue;
    m.key ??= ++keySeq;
    m.steps.forEach((s, i) => {
      if (s.tool === 'record_plan') return;
      let c = null;
      try { c = cardFor(s); } catch { c = null; }
      if (c) out.push({id: `${m.key}-${i}`, tool: s.tool, same: `${s.tool}:${s.result?.id || ''}`, ...c});
    });
  }
  const seen = new Set();  // asking the same thing twice refreshes its card instead of stacking a copy
  return out.reverse().filter(c => !seen.has(c.same) && seen.add(c.same)).slice(0, BOARD_MAX);
}

const cardInner = c => `<header><span class="ac-tool">${esc(toolName(c.tool))}</span>${c.badge || ''}</header><b class="ac-title">${c.title}</b><div class="ac-body">${c.body}</div>${c.foot ? `<footer>${c.foot}</footer>` : ''}`;
const cardEl = c => `<article class="jelly-tile acard ${c.cls || ''}" data-jelly data-card="${c.id}" data-title="${esc(String(c.title).replace(/<[^>]+>/g, ''))}">${cardInner(c)}</article>`;

function boardPanel() {
  const list = cards();
  return panel(t('agent.board'), `<div class="jelly-stage" id="agent-stage">
      <div class="jelly-head"><small>${t('agent.board_hint')}</small>${list.length > 1 ? `<button class="link sm" data-action="agent-scatter">${t('ov.scatter')}</button>` : ''}</div>
      <div class="jelly-board agent-board ${list.length ? '' : 'is-empty'}" id="agent-board">${list.map(cardEl).join('')}<p class="board-empty">${t('agent.board_empty')}</p></div>
    </div>`, {cls: 'board-panel', sub: t('agent.board_sub')});
}

/** Joining two cards is a question: what do these two mean together? */
function combinePill(a, b) {
  const x = a.dataset.title, y = b.dataset.title;
  return `<b>${esc(x)} + ${esc(y)}</b><button class="button sm" data-action="prompt" data-prompt="${esc(t('agent.combine_prompt', {a: x, b: y}))}">${t('agent.combine')} ${icons.arrow}</button>`;
}

function syncBoard() {
  const el = document.getElementById('agent-board');
  if (!el) return;
  const list = cards(), ids = new Set(list.map(c => c.id));
  el.classList.toggle('is-empty', !list.length);
  for (const tile of [...el.querySelectorAll('[data-card]')]) if (!ids.has(tile.dataset.card)) board ? board.remove(tile) : tile.remove();
  for (const c of [...list].reverse()) {
    const html = cardInner(c);
    const tile = el.querySelector(`[data-card="${c.id}"]`);
    if (tile) {
      if (tile.dataset.sig !== html) { tile.innerHTML = html; tile.dataset.sig = html; tile.className = `jelly-tile acard ${c.cls || ''}`; }
      continue;
    }
    const tmp = document.createElement('div');
    tmp.innerHTML = cardEl(c);
    const fresh = tmp.firstElementChild;
    fresh.dataset.sig = html;
    el.appendChild(fresh);
    board?.add(fresh);
  }
}

function capabilities() {
  const can = [1, 2, 3, 4, 5].map(n => `<li>${icons.check}<span>${t('agent.can_' + n)}</span></li>`).join('');
  return panel(t('agent.can'), `<ul class="can-list">${can}</ul>`, {cls: 'can-panel'});
}

/* ---------- chat ---------- */

function trace(m, steps) {
  const plan = m.plan;
  if (!plan && !steps.length) return m.done ? '' : `<div class="thinking"><span class="think-orb"><i></i></span><span class="think-text">${t('agent.thinking')}</span></div>`;
  const entities = plan ? Object.entries(plan.entities || {}).filter(([, v]) => v && typeof v !== 'object') : [];
  const intent = plan ? (has('intent.' + plan.intent) ? t('intent.' + plan.intent) : plan.intent) : '';
  return `<div class="did">${plan ? `<span class="did-intent">${esc(intent)}${entities.length ? ' · ' + entities.map(([, v]) => esc(v)).join(' · ') : ''}</span>` : ''}
    ${steps.map((s, i) => `<button class="did-chip st-${esc(s.status)}" data-action="card-focus" data-card="${m.key}-${m.steps.indexOf(s)}">${esc(toolName(s.tool))}</button>`).join('')}
    ${plan?.missing?.length ? `<span class="missing">${t('agent.missing')}: ${plan.missing.map(esc).join(', ')}</span>` : ''}</div>`;
}

export function message(m) {
  m.key ??= ++keySeq;
  if (m.role === 'user') return `<div class="msg user" data-key="${m.key}"><div class="bubble">${esc(m.text)}</div></div>`;
  if (m.role === 'note') return `<div class="msg note"><p>${esc(m.text)}</p></div>`;
  const steps = m.steps.filter(s => s.tool !== 'record_plan');
  return `<div class="msg bot ${m.done ? 'done' : 'live'}" data-key="${m.key}">
    <div class="who"><span class="agent-orb sm"><i></i></span>DOT <span class="mode-badge m-${esc(m.mode || 'model')}">${t('agent.mode.' + (m.mode || 'model'))}</span></div>
    ${m.note ? `<p class="mode-note">${esc(t('agent.offline_note'))}</p>` : ''}
    ${trace(m, steps)}
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

/* ---------- forms the assistant pops up when it needs something only the person can give ---------- */

const val = (form, name) => (new FormData(form).get(name) ?? '').toString().trim();
const sel = (name, list, selected, extra = '') => `<select id="af-${name}" name="${name}" ${extra}>${options(list.map(c => Array.isArray(c) ? c : [c, c]), selected)}</select>`;
const inp = (name, value = '', extra = '') => `<input id="af-${name}" name="${name}" value="${esc(value ?? '')}" ${extra}>`;
const f = (name, label, input, hint = '') => field('af-' + name, label, input, hint);
const pickCurrency = (c, list = CURRENCIES, fallback = 'AUD') => list.includes(String(c || '').toUpperCase()) ? String(c).toUpperCase() : fallback;

function templateFields(fmt, values) {
  const fm = fmts()?.formats?.[fmt];
  if (!fm) return '';
  return fm.fields.map(x => {
    const v = values[x.id] ?? '';
    let input;
    if (x.kind === 'charges') input = sel(x.id, (fmts().charges || []).map(c => [c, t('tf.charge.' + c)]), v || 'SHA');
    else if (x.kind === 'purpose') input = sel(x.id, [['', '—'], ...(fmts().purposes || []).map(c => [c, `${c} · ${t('tf.purpose.' + c)}`])], v);
    else if (x.kind === 'account_type') input = sel(x.id, [['checking', t('tf.checking')], ['savings', t('tf.savings')]], v || 'checking');
    else input = inp(x.id, v, `maxlength="${x.max + 8}" autocomplete="off" spellcheck="false" class="${/bic|iban|account|bsb|sort|aba|ifsc|cnaps|digits/.test(x.kind) ? 'mono' : ''}"`);
    return `<div class="field af-tf ${v ? 'filled' : ''}" data-field="${x.id}"><label for="af-${x.id}">${t('tf.f.' + x.id)}${x.required ? '' : ` <small class="muted">${t('tf.optional')}</small>`}</label>${input}<small class="tf-msg">${v ? t('af.from_chat') : esc(t('tf.h.' + x.id))}</small></div>`;
  }).join('');
}

/** What the form shows: the assistant's prefill, overlaid with whatever the person already typed (kept across repaints). */
function current(fm) {
  const p = {...(fm.prefill || {})}, typed = fm.values || {};
  if (fm.kind !== 'template') return {...p, ...typed};
  const fields = {...(p.fields || {})};
  for (const [k, v] of Object.entries(typed)) if (!k.startsWith('__')) fields[k] = v;
  return {...p, fields, format: typed.__format || p.format, name: typed.__name ?? p.name, currency: typed.__currency || p.currency};
}

function snapshot(form) {
  const fm = state.chat.form;
  if (!fm || !form) return;
  fm.values = Object.fromEntries([...new FormData(form)].filter(([k]) => k !== '__checked'));
}

function formBody(fm) {
  const p = current(fm);
  switch (fm.kind) {
    case 'recipient': {
      const currency = pickCurrency(p.currency, FORM_CURRENCIES, 'CNY');
      const country = p.country || CUR_TO_ECON[currency] || '';
      return f('name', t('wallets.r_name'), inp('name', p.name, 'required maxlength="100"'))
        + f('recipient_id', t('wallets.r_id'), inp('recipient_id', p.recipient_id || slug(p.name), 'required pattern="[A-Za-z0-9_\\-]{1,64}" maxlength="64"'), t('wallets.r_id_hint'))
        + `<div class="grid-2">${f('currency', t('wallets.r_currency'), sel('currency', FORM_CURRENCIES, currency))}
           ${f('country', t('wallets.r_country'), sel('country', [['', '—'], ...[...new Set(Object.values(CUR_TO_ECON))].map(c => [c, region(c)])], country))}</div>`
        + f('account', t('wallets.r_account'), inp('account', '', `maxlength="34" placeholder="${t('wallets.r_account_ph')}"`), t('wallets.r_account_hint'));
    }
    case 'template': {
      const fmt = FORMATS.includes(p.format) ? p.format : 'swift';
      const known = fmts()?.formats?.[fmt]?.fields?.map(x => x.id) || [];
      const values = {...Object.fromEntries(Object.entries(p).filter(([k]) => known.includes(k))), ...(p.fields || {})};
      const name = p.name || [values.beneficiary_name || values.account_name, t('tf.fmt.' + fmt)].filter(Boolean).join(' · ');
      const fixed = fmts()?.formats?.[fmt]?.currency;
      return `<div class="af-formats" role="radiogroup">${FORMATS.map(x => `<button type="button" class="af-fmt ${x === fmt ? 'on' : ''}" data-action="af-format" data-format="${x}" aria-pressed="${x === fmt}">${t('tf.fmt.' + x)}</button>`).join('')}</div>
        <input type="hidden" name="__format" value="${fmt}">
        <div class="grid-2">${f('__name', t('tf.name'), inp('__name', name, 'required maxlength="80"'))}
          ${f('__currency', t('plans.currency'), fixed ? inp('__currency', fixed, 'readonly') : sel('__currency', CURRENCIES, pickCurrency(p.currency)))}</div>
        <div class="af-fields">${templateFields(fmt, values)}</div>
        <label class="check-label"><input type="checkbox" name="__checked"> ${t('af.template.check')}</label>`;
    }
    case 'cash':
      return `<div class="grid-2">${f('currency', t('plans.currency'), sel('currency', CURRENCIES, pickCurrency(p.currency)))}
        ${f('amount', t('spend.amount'), inp('amount', p.amount, 'required inputmode="decimal" maxlength="24"'))}</div>`;
    case 'term':
      return f('name', t('af.term.name'), inp('name', p.name, 'required maxlength="80"'))
        + `<div class="grid-2">${f('start', t('af.term.start'), inp('start', p.start, 'type="date" required'))}${f('end', t('af.term.end'), inp('end', p.end, 'type="date" required'))}</div>`
        + `<div class="grid-2">${f('currency', t('plans.currency'), sel('currency', CURRENCIES, pickCurrency(p.currency)))}${f('tuition', t('af.term.tuition'), inp('tuition', p.tuition, 'inputmode="decimal"'))}</div>`
        + `<div class="grid-2">${f('tuition_due', t('af.term.tuition_due'), inp('tuition_due', p.tuition_due, 'type="date"'))}${f('living', t('af.term.living'), inp('living', p.living, 'inputmode="decimal"'))}</div>`
        + f('income', t('af.term.income'), inp('income', p.income, 'inputmode="decimal"'));
    case 'scholarship':
      return f('name', t('af.scholarship.name'), inp('name', p.name, 'required maxlength="120"'))
        + f('provider', t('af.scholarship.provider'), inp('provider', p.provider, 'maxlength="120"'))
        + `<div class="grid-2">${f('amount', t('spend.amount'), inp('amount', p.amount, 'inputmode="decimal"'))}${f('currency', t('plans.currency'), sel('currency', CURRENCIES, pickCurrency(p.currency)))}</div>`
        + f('deadline', t('af.scholarship.deadline'), inp('deadline', p.deadline, 'type="date"'));
    case 'plan':
      return `<div class="grid-2">${f('source', t('af.watch.source'), sel('source', CURRENCIES, pickCurrency(p.source, CURRENCIES, 'CNY')))}${f('target', t('af.watch.target'), sel('target', CURRENCIES, pickCurrency(p.target)))}</div>`
        + `<div class="grid-2">${f('side', t('af.plan.side'), sel('side', [['receive', t('ov.e.side_receive')], ['spend', t('ov.e.side_spend')]], p.side === 'spend' ? 'spend' : 'receive'))}${f('amount', t('spend.amount'), inp('amount', p.amount, 'required inputmode="decimal"'))}</div>`
        + `<div class="grid-2">${f('due', t('af.watch.deadline'), inp('due', p.due || p.deadline, 'type="date"'))}${f('purpose', t('ov.e.purpose'), inp('purpose', p.purpose || p.note, 'maxlength="120"'))}</div>`
        + f('min_rate', t('af.watch.min_rate'), inp('min_rate', p.min_rate, 'inputmode="decimal"'), t('af.watch.min_rate_hint'));
    case 'expense':
      return f('text', t('spend.quick'), inp('text', p.text, `required maxlength="200" placeholder="${t('spend.quick_ph')}"`), t('af.expense.hint'));
    case 'afford':
      return `<div class="grid-2">${f('amount', t('spend.amount'), inp('amount', p.amount, 'required inputmode="decimal"'))}${f('currency', t('plans.currency'), sel('currency', CURRENCIES, pickCurrency(p.currency)))}</div>`
        + f('label', t('afford.label'), inp('label', p.label, `maxlength="80" placeholder="${t('afford.label_ph')}"`))
        + f('date', t('afford.date'), inp('date', p.date, 'type="date"'));
    default:
      return '';
  }
}

export function sideForm() {
  const fm = state.chat.form;
  if (!fm) return '';
  const owner = isOwner();
  return `<div class="side-form af-${esc(fm.kind)}" data-key="${fm.key}">
    <div class="side-form-head"><span class="side-form-orb"><i></i></span><div><b>${t('af.' + fm.kind + '.title')}</b><small>${t('af.' + fm.kind + '.intro')}</small></div>
      <button type="button" class="x" data-action="close-side-form" aria-label="${t('common.close')}">×</button></div>
    <form id="side-form" class="form-block" data-key="${fm.key}" data-kind="${esc(fm.kind)}">
      <fieldset ${owner ? '' : 'disabled'}>${formBody(fm)}</fieldset>
      ${owner ? '' : `<p class="note warn">${t('af.owner_only')}</p>`}
      <div class="form-error"></div>
      <div class="row-actions"><button class="button primary" ${owner ? '' : 'disabled'}>${icons.check}${t('af.' + fm.kind + '.submit')}</button><button type="button" class="button ghost" data-action="close-side-form">${t('agent.form_cancel')}</button></div>
    </form></div>`;
}

let formSeq = 0;
const forms = new Map();  // key -> form, kept after closing so it can be resumed from the board

function openForm(kind, prefill = {}, extra = {}, step = null) {
  if (kind === 'watch') kind = 'plan';  // the exchange watch's needs are exchange plans now
  const fm = {key: ++formSeq, kind, prefill: prefill || {}, ...extra};
  forms.set(fm.key, fm);
  if (step) step.formKey = fm.key;
  const show = () => { state.chat.form = fm; paintSideForm(); syncBoard(); };
  if (kind === 'template' && !formats) {
    (async () => { try { formats = fmts() || await api('/transfer-formats'); } catch { /* the form still opens, with the format chooser */ } show(); })();
  } else show();
  return fm.key;
}

function resumeForm(key) {
  const fm = forms.get(Number(key));
  if (!fm || fm.done) return;
  if (state.chat.form?.key === fm.key) { wobbleForm(); return; }
  fm.shown = false;  // play the entrance again
  state.chat.form = fm;
  paintSideForm();
  syncBoard();
  document.getElementById('side-form-host')?.scrollIntoView({behavior: 'smooth', block: 'start'});
}

/** Pops the form in (jelly + blur + buzz) or out, without touching anything the user is typing. */
export function paintSideForm() {
  const host = document.getElementById('side-form-host');
  if (!host) return;
  const fm = state.chat.form;
  const shown = host.firstElementChild;
  if (fm && shown?.dataset.key === String(fm.key) && !shown.classList.contains('leaving')) return;
  if (!fm) {
    if (shown) { shown.classList.add('leaving'); setTimeout(() => { if (!state.chat.form) host.innerHTML = ''; }, 460); }
    return;
  }
  host.innerHTML = sideForm();
  const again = fm.shown;  // a page refresh repaints the same form: no second entrance
  fm.shown = true;
  host.firstElementChild.classList.toggle('settled', !!again);
  if (!again) buzz([14, 40, 22]);
  if (!again) host.querySelectorAll('.side-form-head, .side-form .field, .side-form .af-formats, .side-form .check-label, .side-form .row-actions, .side-form .note')
    .forEach((el, i) => { el.style.animationDelay = (220 + Math.min(i, 10) * 55) + 'ms'; });
  const form = host.querySelector('#side-form');
  if (fm.kind === 'recipient') {
    const name = form.querySelector('#af-name'), id = form.querySelector('#af-recipient_id');
    let touched = false;
    id.addEventListener('input', () => { touched = true; });
    name.addEventListener('input', () => { if (!touched) id.value = slug(name.value) || id.value; });
    form.querySelector('#af-currency').addEventListener('change', e => { const c = CUR_TO_ECON[e.target.value]; if (c) form.querySelector('#af-country').value = c; });
  }
  form.addEventListener('input', e => {
    const box = e.target.closest('.af-tf');
    box?.classList.toggle('filled', !!e.target.value);
    box?.classList.remove('lv-error');  // fixing a field clears its mark
    snapshot(form);
  });
  form.addEventListener('change', () => snapshot(form));
  if (again) return;
  if (matchMedia('(max-width: 1280px)').matches) host.scrollIntoView({behavior: 'smooth', block: 'start'});
  const first = [...form.querySelectorAll('input:not([type=hidden]):not([readonly]), select')].find(x => !x.value) || form.querySelector('input:not([type=hidden])');
  setTimeout(() => first?.focus({preventScroll: true}), 420);
}

function wobbleForm() {
  const host = document.getElementById('side-form-host');
  host?.classList.remove('nudge'); void host?.offsetWidth; host?.classList.add('nudge');
  buzz([10, 30, 10]);
}

function closeForm(done = false) {
  const fm = state.chat.form;
  if (fm) {
    snapshot(document.getElementById('side-form'));
    if (done) fm.done = true;
  }
  state.chat.form = null;
  paintSideForm();
  syncBoard();
}

const SUBMIT = {
  async recipient(form, fm) {
    if ((state.data.recipients || []).some(r => r.id === val(form, 'recipient_id'))) throw new Error(t('wallets.r_exists'));
    const body = {recipient_id: val(form, 'recipient_id'), name: val(form, 'name'), currency: val(form, 'currency'), country: val(form, 'country'),
      account: val(form, 'account').replace(/\s+/g, ''), kind: 'individual', address: '', enabled: true};
    const proposal = fm.proposalId, p = fm.prefill || {};
    const same = proposal && ['name', 'currency'].every(k => (p[k] || '') === body[k]) && (p.recipient_id || body.recipient_id) === body.recipient_id;
    if (same) await api(`/proposals/${encodeURIComponent(proposal)}/decide`, 'POST', {accept: true});
    else {
      if (proposal) await api(`/proposals/${encodeURIComponent(proposal)}/decide`, 'POST', {accept: false, note: 'replaced by owner-entered details'});
      await api('/recipients', 'POST', body);
    }
    for (const m of state.chat.messages) for (const st of m.steps || []) if (proposal && st.result?.id === proposal) st.result = {...st.result, status: same ? 'confirmed' : 'rejected'};
    invalidate(['recipients', 'proposals']);
    return t('agent.form_done_msg', {name: body.name, id: body.recipient_id, currency: body.currency});
  },
  async template(form) {
    const fmt = val(form, '__format');
    const spec = fmts()?.formats?.[fmt];
    if (!spec) throw new Error(t('tf.invalid'));
    const fields = Object.fromEntries(spec.fields.map(x => [x.id, val(form, x.id)]).filter(([, v]) => v));
    const currency = spec.currency || val(form, '__currency');
    const check = await api('/transfer-templates/validate', 'POST', {format: fmt, fields, currency});
    const errors = (check.issues || []).filter(i => i.level === 'error');
    let first = null;
    form.querySelectorAll('.af-tf').forEach(el => {
      const mine = errors.filter(i => i.field === el.dataset.field);
      el.classList.toggle('lv-error', mine.length > 0);
      if (mine.length) {
        el.querySelector('.tf-msg').textContent = mine.map(i => t('tf.e.' + i.code)).join(' · ');
        el.classList.remove('shake'); void el.offsetWidth; el.classList.add('shake');
        first ??= el;
      }
    });
    if (errors.length) {
      buzz([10, 30, 10]);
      if (first) { first.scrollIntoView({behavior: 'smooth', block: 'center'}); first.querySelector('input, select, textarea')?.focus({preventScroll: true}); }
      throw new Error(t('af.template.fix', {n: errors.length}));
    }
    const name = val(form, '__name');
    const saved = await api('/transfer-templates', 'POST', {name, format: fmt, fields, currency, purpose: '', notes: ''});
    if (form.querySelector('[name=__checked]')?.checked) await api(`/transfer-templates/${encodeURIComponent(saved.id)}/confirm`, 'POST', {});
    invalidate(['ttemplates']);
    return t('af.template.done', {name});
  },
  async cash(form) {
    const currency = val(form, 'currency'), amount = val(form, 'amount');
    await api('/cash', 'PUT', {currency, amount, label: ''});
    return t('af.cash.done', {amount, currency});
  },
  async term(form) {
    const body = Object.fromEntries(['name', 'currency', 'start', 'end', 'tuition', 'tuition_due', 'living', 'income'].map(k => [k, val(form, k)]));
    if (!body.tuition_due) body.tuition_due = null;
    await api('/terms', 'POST', body);
    return t('af.term.done', {name: body.name});
  },
  async scholarship(form) {
    const body = {name: val(form, 'name'), provider: val(form, 'provider'), amount: val(form, 'amount'), currency: val(form, 'currency'), deadline: val(form, 'deadline') || null};
    await api('/scholarships', 'POST', body);
    return t('af.scholarship.done', {name: body.name});
  },
  async plan(form) {
    const body = {source: val(form, 'source'), target: val(form, 'target'), amount: val(form, 'amount'), side: val(form, 'side') || 'receive',
      due: val(form, 'due') || null, purpose: val(form, 'purpose'), kind: 'custom', min_rate: val(form, 'min_rate') || null};
    await api('/exchange-plans', 'POST', body);
    invalidate(['money']);
    return t('af.plan.done', {pair: `${body.source}→${body.target}`, amount: body.amount});
  },
  async expense(form) {
    const parsed = await api('/expenses/parse', 'POST', {text: val(form, 'text')});
    await api('/expenses', 'POST', {date: parsed.date, amount: parsed.amount, currency: parsed.currency, description: parsed.description, category: parsed.category, source: 'manual'});
    return t('af.expense.done', {text: val(form, 'text')});
  },
  async afford(form) {
    return t('af.afford.done', {amount: val(form, 'amount'), currency: val(form, 'currency'), label: val(form, 'label') || '—'});
  },
};

export const view = {
  id: 'agent',
  submit: {
    async 'side-form'(form) {
      const fm = state.chat.form;
      if (!fm || !SUBMIT[fm.kind]) return;
      const next = await SUBMIT[fm.kind](form, fm);
      invalidate(['reminders', 'transfers']);
      toast(t('wallets.saved'), 'good');
      buzz([20, 30, 40]);
      closeForm(true);
      send(next);
    },
  },
  needs: ['recipients'],
  mount(root) {
    root.querySelectorAll('#chat-log').forEach(log => { log.scrollTop = log.scrollHeight; });
    const host = root.querySelector('#side-form-host');
    if (host && state.chat.form) { host.innerHTML = ''; paintSideForm(); }
    const stage = root.querySelector('#agent-stage');
    board?.stop();
    board = stage ? jellyBoard(stage, {link: combinePill, fixed: true}) : null;
  },
  actions: {
    /* One-click owner decisions inside the chat; the assistant then continues on its own. */
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
      wobbleForm();
      document.getElementById('side-form-host')?.scrollIntoView({behavior: 'smooth', block: 'start'});
    },
    'close-side-form'() { closeForm(); },
    'resume-form'(el) {
      if (state.view !== 'agent') { location.hash = 'agent'; setTimeout(() => resumeForm(el.dataset.key), 500); return; }
      resumeForm(el.dataset.key);
    },
    'af-format'(el) {
      const form = document.getElementById('side-form'), fm = state.chat.form;
      if (!form || !fm) return;
      const old = fmts()?.formats?.[val(form, '__format')];
      const values = Object.fromEntries((old?.fields || []).map(x => [x.id, val(form, x.id)]).filter(([, v]) => v));
      // Carry what was typed across formats where it means the same thing.
      const acct = values.account || values.iban || values.account_number;
      const who = values.beneficiary_name || values.account_name;
      const fmt = el.dataset.format;
      const spec = fmts()?.formats?.[fmt];
      if (!spec) return;
      const ids = spec.fields.map(x => x.id);
      const moved = Object.fromEntries(Object.entries(values).filter(([k]) => ids.includes(k)));
      for (const k of ['account', 'iban', 'account_number']) if (ids.includes(k) && !moved[k] && acct) moved[k] = acct;
      for (const k of ['beneficiary_name', 'account_name']) if (ids.includes(k) && !moved[k] && who) moved[k] = who;
      form.querySelector('[name=__format]').value = fmt;
      form.querySelectorAll('.af-fmt').forEach(b => { b.classList.toggle('on', b.dataset.format === fmt); b.setAttribute('aria-pressed', String(b.dataset.format === fmt)); });
      const box = form.querySelector('.af-fields');
      box.innerHTML = templateFields(fmt, moved);
      box.classList.remove('swap'); void box.offsetWidth; box.classList.add('swap');
      const cur = form.querySelector('[name=__currency]');
      if (spec.currency && cur) cur.closest('.field').outerHTML = f('__currency', t('plans.currency'), inp('__currency', spec.currency, 'readonly'));
      else if (!spec.currency && cur?.readOnly) cur.closest('.field').outerHTML = f('__currency', t('plans.currency'), sel('__currency', CURRENCIES, 'AUD'));
      snapshot(form);
      buzz(8);
    },
    'card-focus'(el) {
      const tile = document.querySelector(`#agent-board [data-card="${el.dataset.card}"]`);
      if (!tile) return;
      board?.focus(tile);
      if (matchMedia('(max-width: 1280px)').matches) tile.scrollIntoView({behavior: 'smooth', block: 'center'});
    },
    'agent-scatter'() { board?.scatter(); },
  },
  render() {
    return `<div class="agent-layout">
      ${panel(`<span class="agent-orb"><i></i></span>${t('agent.title')}`, `<div class="chat-log" id="chat-log">${chatLog()}</div>${composer()}<p class="fine">${t('agent.disclaimer')}</p>`, {cls: 'chat-panel', sub: state.model ? `${t('agent.mode.model')}${state.modelName ? ' · ' + esc(state.modelName) : ''}` : t('agent.mode.rules')})}
      <div class="agent-side">
        <div id="side-form-host" class="side-form-host">${sideForm()}</div>
        ${boardPanel()}
        ${capabilities()}
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
        if (['prepare_payment', 'modify_payment', 'reconcile_payment', 'propose_change', 'do_action', 'log_expense', 'track_scholarship', 'plan_exchange', 'draft_transfer_template'].includes(e.tool)) invalidate();
        if (e.ok && e.tool === 'request_details') openForm(e.result.form, e.result.prefill, {reason: e.result.reason}, s);
        if (e.ok && e.tool === 'propose_change' && e.result.kind === 'recipient' && e.result.status === 'pending' && isOwner())
          openForm('recipient', e.result.payload, {proposalId: e.result.id}, s);
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

/** Repaints the conversation and the card board in place, so streaming never flickers. */
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
  syncBoard();
}
