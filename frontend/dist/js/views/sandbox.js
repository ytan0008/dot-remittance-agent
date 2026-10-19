import {state, t, api, rerender} from '../core.js';
import {esc, panel, icons, options, empty} from '../ui.js';
import {money, day} from '../i18n.js';
import {ledgerPanel, mountLedger} from './wallets.js';

/* The sandbox, dated: what you hold today, then — day by day — what your exchange plans, goals, bills, subscriptions,
   term costs and a scenario chosen on the Send page would do to each currency. Each source can be switched off
   ("don't deduct"), pretend money can be added; nothing is saved, paid or exchanged. */

const CURRENCIES = ['AUD', 'CNY', 'USD', 'EUR', 'GBP', 'JPY', 'KRW', 'HKD', 'SGD', 'CAD', 'NZD', 'VND', 'INR', 'CHF'];
const GROUPS = ['scenario', 'plans', 'goals', 'bills', 'subscriptions', 'recurring', 'term', 'pretend'];
const ui = {days: 90, off: new Set(), extra: []};
const signed = (minor, cur) => `${minor > 0 ? '+' : '−'}${money(Math.abs(minor), cur)}`;

async function fetchTimeline() {
  const sc = state.sandboxScenario;
  return api('/sandbox/timeline', 'POST', {off: [...ui.off], days: ui.days, extra: ui.extra,
    scenario: sc ? {source: sc.source, target: sc.target, label: sc.label, legs: sc.legs} : null});
}

/** Balance of one currency over the period, as a step line; the zero line shows when it would go negative. */
function chart(cur, start, events, from, to) {
  const pts = [[from, start]];
  let bal = start;
  for (const e of events) { pts.push([e.date, bal]); bal = e.balance; pts.push([e.date, bal]); }
  pts.push([to, bal]);
  const t0 = Date.parse(from), span = Math.max(1, Date.parse(to) - t0);
  const vals = pts.map(p => p[1]), lo = Math.min(0, ...vals), hi = Math.max(1, ...vals);
  const x = d => ((Date.parse(d) - t0) / span * 100).toFixed(2), y = v => (36 - (v - lo) / (hi - lo || 1) * 32).toFixed(2);
  const line = pts.map(p => `${x(p[0])},${y(p[1])}`).join(' ');
  return `<svg class="sb-chart" viewBox="0 0 100 40" preserveAspectRatio="none" role="img" aria-label="${esc(cur)}">
    ${lo < 0 ? `<line class="zero" x1="0" x2="100" y1="${y(0)}" y2="${y(0)}" vector-effect="non-scaling-stroke"/>` : ''}
    <polyline class="area" points="0,40 ${line} 100,40"/><polyline class="line" points="${line}" vector-effect="non-scaling-stroke"/></svg>`;
}

function assets(tl) {
  const list = Object.entries(tl.start);
  return panel(`${t('sb.have')} <small class="muted">· ${day(tl.today)}</small>`, list.length ? `<ul class="sb-assets">${list.map(([cur, a]) =>
    `<li><b class="code">${esc(cur)}</b><span>${esc(money(a, cur))}</span></li>`).join('')}</ul>
    <p class="fine">${t('sb.have_total', {a: money(tl.total_start, tl.display), c: tl.display})}</p>` : `<p class="fine">${t('ov.empty')}</p>`,
    {cls: 'sb-have', actions: `<button class="link sm" data-action="go" data-view="overview">${t('ov.edit')} ${icons.arrow}</button>`});
}

function scenarioCard() {
  const sc = state.sandboxScenario;
  return panel(t('sb.scenario'), sc ? `<div class="sb-scen"><b>${esc(sc.source)} → ${esc(sc.target)} · ${esc(sc.label)}</b>
      <small>${sc.timing === 'split' ? t('scen.split', {d: day(sc.legs[sc.legs.length - 1].date)}) : t('scen.once')}</small>
      <ul>${sc.legs.map(l => `<li>${day(l.date)} · −${esc(money(l.spend, sc.source))} ${esc(sc.source)} → +${esc(money(l.receive, sc.target))} ${esc(sc.target)}</li>`).join('')}</ul>
      <button class="link sm" data-action="sb-scen-clear">${t('sb.scen_clear')}</button></div>`
    : `<p class="fine">${t('sb.scen_none')}</p><button class="button sm" data-action="go" data-view="send">${t('sb.scen_pick')} ${icons.arrow}</button>`, {cls: 'sb-scen-panel'});
}

function sources(tl) {
  const by = GROUPS.map(g => [g, tl.sources.filter(s => s.group === g)]).filter(([, l]) => l.length);
  return panel(t('sb.deduct'), by.length ? by.map(([g, list]) => `<div class="sb-group"><span class="eyebrow">${t('sb.g.' + g)}</span>
      <ul class="sb-plans">${list.map(s => `<li><label class="check-label"><input type="checkbox" data-src="${esc(s.key)}" ${s.on ? 'checked' : ''}>
        <b>${esc(s.label || t('sb.g.' + g))}</b> <span>${Object.entries(s.amounts).map(([c, a]) => `${signed(a, c)} ${esc(c)}`).join(' · ')}</span>
        <small>${day(s.first)}${s.count > 1 ? ' · ' + t('sb.times', {n: s.count}) : ''}</small></label></li>`).join('')}</ul></div>`).join('')
    : `<p class="fine">${t('sb.no_sources')}</p>`,
    {cls: 'sb-sources', sub: t('sb.deduct_sub')});
}

function pretend(tl) {
  return `<form id="sim-extra-form" class="sim-extra" autocomplete="off">
      <select name="currency" aria-label="${t('plans.currency')}">${options(CURRENCIES.map(c => [c, c]), tl.display)}</select>
      <input name="amount" inputmode="decimal" placeholder="${t('ov.s.pretend_ph')}" aria-label="${t('ov.s.pretend')}">
      <button class="button sm">${icons.plus}${t('sb.add')}</button></form>
    ${ui.extra.length ? `<div class="sim-chips">${ui.extra.map((x, i) => `<button class="pill on" data-action="sim-drop" data-i="${i}">${Number(x.amount) > 0 ? '+' : ''}${esc(x.amount)} ${esc(x.currency)} ×</button>`).join('')}</div>` : ''}`;
}

function timeline(tl) {
  const curs = [...new Set([...Object.keys(tl.start), ...tl.events.map(e => e.currency)])];
  const charts = curs.map(cur => {
    const ev = tl.events.filter(e => e.currency === cur);
    const low = tl.lowest[cur];
    return `<div class="sb-cur ${tl.negative.includes(cur) ? 'neg' : ''}"><header><b class="code">${esc(cur)}</b>
        <span>${esc(money(tl.start[cur] || 0, cur))} → <b>${esc(money(tl.end_balances[cur] ?? tl.start[cur] ?? 0, cur))}</b></span>
        ${low ? `<small>${t(low.amount < 0 ? 'sb.low_neg' : 'sb.low', {a: money(low.amount, cur), d: day(low.date)})}</small>` : ''}</header>
      ${chart(cur, tl.start[cur] || 0, ev, tl.today, tl.end)}</div>`;
  }).join('');
  const rows = tl.events.length ? `<div class="table-wrap"><table class="table sb-events"><thead><tr><th>${t('spend.date')}</th><th>${t('sb.what')}</th><th>${t('sb.change')}</th><th>${t('sb.after')}</th></tr></thead><tbody>
    ${tl.events.map(e => `<tr class="${e.balance < 0 ? 'neg' : ''}"><td>${day(e.date)}</td><td><span class="tag">${t('sb.g.' + e.group)}</span> ${esc(e.label)}</td>
      <td class="num ${e.amount > 0 ? 'up' : ''}">${signed(e.amount, e.currency)} ${esc(e.currency)}</td><td class="num">${esc(money(e.balance, e.currency))} ${esc(e.currency)}</td></tr>`).join('')}</tbody></table></div>`
    : `<p class="fine">${t('sb.no_events')}</p>`;
  return panel(`${t('sb.over_time')} <small class="muted">· ${day(tl.today)} → ${day(tl.end)}</small>`, `<div class="sb-charts">${charts}</div>
    <div class="ov-sim-total"><div><small>${t('ov.s.before')}</small><b>${esc(money(tl.total_start, tl.display))}</b></div><i>→</i>
      <div><small>${t('sb.at_end', {d: day(tl.end)})}</small><b>${esc(money(tl.total_end, tl.display))}</b> <small>${esc(tl.display)} · ${t('sb.approx')}</small></div></div>
    ${rows}<p class="fine">${t('ov.s.note')}</p>`, {cls: 'sb-time', id: 'sb-time',
      actions: `<div class="segmented">${[30, 90, 180].map(d => `<button type="button" class="${ui.days === d ? 'on' : ''}" data-action="sb-days" data-v="${d}">${t('sb.days', {n: d})}</button>`).join('')}</div>`});
}

/** The overview's short version: before → after, and how many currencies are still short. */
export function sandboxCard(m) {
  const sim = m.simulation, d = sim.display;
  const rows = sim.rows.filter(r => r.before !== r.after).slice(0, 4);
  const short = m.gaps.filter(g => g.known && g.gap_after > 0).length;
  return panel(t('ov.s.title'), `<div class="ov-sim-total"><div><small>${t('ov.s.before')}</small><b>${esc(money(sim.total_before, d))}</b></div><i>→</i>
      <div><small>${t('ov.s.after')}</small><b>${esc(money(sim.total_after, d))}</b> <small>${esc(d)} · ${t('sb.approx')}</small></div></div>
    ${rows.length ? `<ul class="sb-mini">${rows.map(r => `<li><b>${esc(r.currency)}</b><span>${esc(money(r.before, r.currency))} → <b>${esc(money(r.after, r.currency))}</b></span></li>`).join('')}</ul>` : `<p class="fine">${t('ov.s.no_plans')}</p>`}
    <p class="fine">${short ? t('sb.short', {n: short}) : t('agent.c.no_gaps')}</p>
    <button class="button sm" data-action="go" data-view="sandbox">${t('sb.open')} ${icons.arrow}</button>`, {cls: 'ov-sim-panel', sub: t('ov.s.sub')});
}

function ledger(L) {
  if (!L?.moves?.length) return '';
  return panel(t('ov.s.ledger'), `<p class="fine">${t('ov.s.ledger_d')}</p><ul class="ov-moves">${L.moves.map(x => `<li class="fx-${esc(x.effect)}">
      <span>${day(new Date(x.created * 1000).toISOString().slice(0, 10))}</span>
      <span class="who">→ ${esc(x.recipient || x.target)}${x.purpose ? ' · ' + esc(x.purpose) : ''}</span>
      <b>−${esc(money(Math.abs(x.amount), x.currency))} ${esc(x.currency)}</b>
      <span class="chip s-${esc(x.status)}"><i></i>${esc(t('ov.s.fx.' + x.effect))}</span></li>`).join('')}</ul>`, {cls: 'sb-ledger'});
}

export const view = {
  id: 'sandbox',
  needs: ['balances', 'equivalents'],
  async load() {
    try {
      const [tl, L] = await Promise.all([fetchTimeline(), api('/sandbox/ledger')]);
      state.data.timeline = tl; state.data.sbLedger = L;
      delete state.errors.sandbox;
    } catch (e) { state.errors.sandbox = e.message; }
  },
  render() {
    const tl = state.data.timeline;
    if (!tl) return panel(t('ov.s.title'), empty(state.errors.sandbox || t('common.loading')));
    return `<div class="sb-top">${assets(tl)}${scenarioCard()}</div>
      <div class="sb-layout">
        <div class="sb-side">${sources(tl)}${panel(t('ov.s.pretend'), pretend(tl), {cls: 'sb-pretend'})}</div>
        ${timeline(tl)}
      </div>
      ${ledger(state.data.sbLedger)}${ledgerPanel()}`;
  },
  mount(root) {
    mountLedger(root);
    root.querySelector('.sb-sources')?.addEventListener('change', async e => {
      const key = e.target.dataset.src;
      if (!key) return;
      if (e.target.checked) ui.off.delete(key); else ui.off.add(key);
      await refresh();
    });
  },
  actions: {
    async 'sb-days'(el) { ui.days = Number(el.dataset.v); await refresh(); },
    async 'sim-drop'(el) { ui.extra.splice(Number(el.dataset.i), 1); await refresh(); },
    async 'sb-scen-clear'() { state.sandboxScenario = null; await refresh(); },
  },
  submit: {
    async 'sim-extra-form'(f) {
      const v = Object.fromEntries(new FormData(f));
      const amount = String(v.amount || '').replace(/,/g, '').trim();
      if (!amount || !Number(amount)) return;
      ui.extra.push({currency: v.currency, amount});
      await refresh();
    },
  },
};

async function refresh() {
  state.data.timeline = await fetchTimeline();
  rerender();
}
