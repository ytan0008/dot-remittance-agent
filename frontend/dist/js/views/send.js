import {state, t, api, toast, isOwner, canPrepare, invalidate, newId, $, rerender} from '../core.js';
import {esc, amt, tag, panel, field, options, segmented, icons, empty} from '../ui.js';
import {money, num, day, pct, region, decimalsOf, phrase} from '../i18n.js';
import {renderDetail} from './payments.js';

let timer = 0, seq = 0;

function routeOf(id) {
  if (id === 'onchain') return {id: 'onchain', source: 'ETH', target: 'ETH', send: null, receive: null, capabilities: {sandbox_payment: true}};
  return (state.data.routes || []).find(r => r.id === id);
}

function routeChips() {
  const routes = (state.data.routes || []).filter(r => r.enabled);
  const sorted = [...routes].sort((a, b) => b.capabilities.sandbox_payment - a.capabilities.sandbox_payment);
  const wallet = state.data.wallet;
  return `<div class="route-chips hscroll">${sorted.map(r => `<button class="route-chip ${state.send.route === r.id ? 'on' : ''} ${r.capabilities.sandbox_payment ? '' : 'analysis'}" data-action="pick-route" data-value="${esc(r.id)}">
      <span class="route-line"><i></i><s></s><i></i></span><b>${esc(r.send)} → ${esc(r.receive)}</b><small>${esc(r.source)}/${esc(r.target)} · ${r.capabilities.sandbox_payment ? t('send.payable') : t('send.analysis_only')}</small></button>`).join('')}
    ${wallet?.available ? `<button class="route-chip chain ${state.send.route === 'onchain' ? 'on' : ''}" data-action="pick-route" data-value="onchain"><span class="route-line"><i></i><s></s><i></i></span><b>${t('send.onchain')}</b><small>ETH · ${esc(wallet.environment)}</small></button>` : ''}
    <button class="route-chip ghost" data-action="go" data-view="routes">${icons.plus}<b>${t('send.more_routes')}</b><small>APEC</small></button></div>`;
}

function form(route) {
  const s = state.send;
  const chain = route.id === 'onchain';
  const recipients = (state.data.recipients || []).filter(r => r.enabled && (chain ? r.rail === 'evm' : r.rail === 'sandbox' && r.currency === route.target));
  const goals = (state.data.goals || []).filter(g => g.status === 'active' && g.source === route.source && g.target === route.target);
  const mode = chain ? 'send' : s.mode;
  const currency = mode === 'send' ? route.source : route.target;
  return `<form id="send-form" class="send-form" autocomplete="off">
    ${chain ? '' : segmented('mode', [['send', t('send.mode_send')], ['receive', t('send.mode_receive')]], mode, 'send-mode')}
    <div class="amount-field"><label for="send-amount">${t(mode === 'send' ? 'send.amount' : 'send.receive_amount')}</label>
      <div class="amount-input"><input id="send-amount" name="amount" inputmode="decimal" placeholder="${chain ? '0.001' : decimalsOf(currency) ? '100.00' : '1000000'}" value="${esc(mode === 'send' ? s.amount : s.receive)}" maxlength="24" required><span>${esc(currency)}</span></div>
      <small>${t('send.decimals', {n: decimalsOf(currency)})}</small></div>
    ${field('send-recipient', t('send.recipient'), `<select id="send-recipient" name="recipient" required><option value="">${t('send.choose_recipient')}</option>${options(recipients.map(r => [r.id, `${r.name} · ${r.id}`]), s.recipient)}</select>`,
      recipients.length ? '' : `${t(chain ? 'send.no_evm_recipient' : 'send.no_recipient', {c: route.target})} <button type="button" class="link" data-action="new-recipient" data-currency="${esc(chain ? '' : route.target)}" data-country="${esc(route.receive || '')}">${t('action.add_recipient')}</button>`)}
    ${field('send-purpose', t('send.purpose'), `<input id="send-purpose" name="purpose" maxlength="200" required placeholder="${t('send.purpose_ph')}" value="${esc(s.purpose)}">`)}
    <div class="grid-2">
      ${field('send-arrival', t('send.arrival'), `<input id="send-arrival" name="arrival" type="date" value="${esc(s.arrival)}">`)}
      ${field('send-goal', t('send.goal'), `<select id="send-goal" name="goal"><option value="">${t('common.none')}</option>${options(goals.map(g => [g.id, g.title]), s.goal)}</select>`)}
    </div>
    <div class="form-error"></div>
    <button class="button primary wide magnetic" ${canPrepare() && route.capabilities.sandbox_payment ? '' : 'disabled'}>${t('send.prepare')} ${icons.arrow}</button>
    <p class="fine">${t(chain ? 'send.onchain_note' : 'send.prepare_note')}</p>
  </form>`;
}

function comparison(result, route) {
  if (route.id === 'onchain') {
    const w = state.data.wallet;
    const mandates = w?.mandates || [];
    return `<div class="chain-explain"><span class="eyebrow">${t('kind.onchain')}</span><p>${t('send.onchain_explain')}</p>
      ${w?.connected ? `<div class="kv"><span>${t('wallets.balance')}</span>${amt(w.balance, 'ETH')}</div>` : ''}
      <div class="kv"><span>${t('wallets.mandates')}</span><b>${mandates.length}</b></div>
      ${mandates.map(m => `<div class="kv"><span>${esc(m.recipient.name)}</span><small>${t('autonomy.per')} ${esc(money(m.per_payment, 'ETH'))} · ${t('autonomy.budget')} ${esc(money(m.total_budget, 'ETH'))}</small></div>`).join('')}
      <button class="link" data-action="go" data-view="autonomy">${t('autonomy.title')} ${icons.arrow}</button></div>`;
  }
  if (!result) return `<div class="compare-empty"><span class="empty-orb"><i></i></span><p>${t('send.enter_amount')}</p></div>`;
  if (result.error) return `<div class="rate-error">${esc(result.error)}</div>`;
  const r = result, unit = r.mode === 'send' ? r.target : r.source;
  const ref = r.reference;
  const top = r.options.find(o => o.rank === 1);
  return `<div class="compare-head">
      ${ref ? `<div><span class="eyebrow">${tag('reference')}</span><b>${num(ref.rate, 6)}</b> <small>${esc(r.target)}/${esc(r.source)}</small><small class="muted block">${esc(ref.provider)} · ${day(ref.observed)} · ${esc(phrase(ref.frequency || ''))}${ref.derived ? ' · ' + t('rates.derived') : ''}</small></div>` : `<div class="note warn">${t('send.no_reference')}</div>`}
      ${segmented('rank', [['receive', t(r.mode === 'send' ? 'send.rank_receive' : 'send.rank_cost')], ['speed', t('send.rank_speed')]], state.send.rank, 'send-rank')}
    </div>
    <p class="fine basis">${t('send.basis')}: ${esc(t('basis.' + r.rank + '.' + r.mode))}</p>
    <ol class="options">${r.options.map(o => `<li class="option k-${esc(o.kind)} ${o.rank === 1 ? 'best' : ''} reveal in">
      <div class="option-rank">${o.rank ? String(o.rank).padStart(2, '0') : '—'}</div>
      <div class="option-main"><div class="option-title">${tag(o.kind)}<b>${esc(t('option.' + o.id))}</b></div>
        <div class="option-facts"><span>${t('detail.fee')} ${o.fee ? esc(money(o.fee, r.source)) + ' ' + esc(r.source) : '0'}</span><span>${t('detail.rate')} ${num(o.applied_rate, 6)}</span><span>${t('detail.spread')} ${num(o.spread_pct, 2)}%</span>${o.eta ? `<span>${t('detail.eta')} ${esc(t('eta.' + o.id))}</span>` : ''}${o.cost_vs_reference_pct ? `<span>${t('send.vs_ref')} −${num(o.cost_vs_reference_pct, 2)}%</span>` : ''}</div>
        ${o.unknown_charges ? `<small class="muted">${t('send.unknown')}: ${esc(phrase(o.unknown_charges))}</small>` : ''}
      </div>
      <div class="option-amt">${amt(r.mode === 'send' ? o.receive : o.send, unit, 'lg')}<small>${t(r.mode === 'send' ? 'send.they_get' : 'send.you_pay')}</small>
        ${o.kind === 'sandbox_quote' && o.executable ? `<button class="button sm primary" data-action="submit-send">${t('send.prepare_short')}</button>` : ''}
        ${o.rank === 1 && isOwner() ? `<button class="link sm" data-action="accept-rec" data-id="${esc(o.id)}">${t('send.accept')}</button>` : ''}</div>
    </li>`).join('')}</ol>
    ${r.notes?.length ? `<div class="notes">${r.notes.map(n => `<p class="fine">· ${esc(phrase(n))}</p>`).join('')}</div>` : ''}
    <p class="fine">${t('send.disclaimer')}</p>`;
}

export const view = {
  id: 'send',
  needs: ['routes', 'recipients', 'goals', 'wallet', 'balances'],
  render() {
    let route = routeOf(state.send.route);
    if (!route) { route = (state.data.routes || []).find(r => r.capabilities.sandbox_payment) || (state.data.routes || [])[0]; if (route) state.send.route = route.id; }
    if (!route) return empty(t('common.loading'));
    const balance = (state.data.balances || []).find(b => b.currency === route.source);
    return `${routeChips()}
      <div class="send-layout">
        ${panel(`${route.id === 'onchain' ? t('send.onchain') : `${esc(region(route.send))} <span class="muted">→</span> ${esc(region(route.receive))}`}`, form(route),
          {sub: balance ? `${t('wallets.available')} ${esc(money(balance.available, balance.currency))} ${esc(balance.currency)}` : '', cls: 'send-panel'})}
        ${panel(route.id === 'onchain' ? t('send.agent_wallet') : t('send.compare'), `<div id="compare">${comparison(state.send.result, route)}</div>`, {cls: 'compare-panel', sub: route.id === 'onchain' ? '' : t('send.live')})}
      </div>`;
  },
  mount(root) {
    const formEl = root.querySelector('#send-form');
    formEl?.addEventListener('input', e => {
      const s = state.send, name = e.target.name;
      if (name === 'amount') { if (s.mode === 'send' || s.route === 'onchain') s.amount = e.target.value; else s.receive = e.target.value; schedule(); }
      if (name === 'recipient') s.recipient = e.target.value;
      if (name === 'purpose') s.purpose = e.target.value;
      if (name === 'arrival') s.arrival = e.target.value;
      if (name === 'goal') s.goal = e.target.value;
    });
    if (!state.send.result && (state.send.amount || state.send.receive)) schedule(0);
  },
  actions: {
    'pick-route'(el) { state.send.route = el.dataset.value; state.send.result = null; state.send.recipient = ''; rerenderSend(); schedule(0); },
    'send-mode'(el) { state.send.mode = el.dataset.value; state.send.result = null; rerenderSend(); schedule(0); },
    'send-rank'(el) { state.send.rank = el.dataset.value; schedule(0); },
    'submit-send'() { $('#send-form')?.requestSubmit(); },
    async 'accept-rec'(el) {
      const r = state.send.result, o = r.options.find(x => x.id === el.dataset.id);
      await api('/decisions', 'POST', {subject: `${r.source}-${r.target}:${o.id}`, detail: {option: o.id, kind: o.kind, mode: r.mode, rank_basis: r.rank,
        send: String(o.send), receive: String(o.receive), fee: String(o.fee), applied_rate: o.applied_rate}});
      invalidate(['decisions']);
      toast(t('send.accepted'), 'good');
    },
  },
  submit: {
    async 'send-form'(f) {
      const s = state.send, route = routeOf(s.route);
      const amount = s.mode === 'send' || route.id === 'onchain' ? s.amount : null;
      const result = await api('/transfers', 'POST', {amount: amount || null, receive_amount: amount ? null : s.receive || null,
        source: route.source, target: route.target, recipient_id: s.recipient, purpose: s.purpose,
        arrival_by: s.arrival || null, goal_id: s.goal || null, idempotency_key: s.key});
      s.key = newId();
      invalidate();
      renderDetail(result);
      toast(t('send.drafted'), 'good');
    },
  },
};

const rerenderSend = () => rerender();

function schedule(delay = 380) {
  clearTimeout(timer);
  timer = setTimeout(compare, delay);
}

async function compare() {
  const s = state.send, route = routeOf(s.route);
  const box = document.getElementById('compare');
  if (!route || route.id === 'onchain') return;
  const amount = s.mode === 'send' ? s.amount : s.receive;
  if (!amount || !/^\d+(\.\d+)?$/.test(amount) || Number(amount) <= 0) { s.result = null; if (box) box.innerHTML = comparison(null, route); return; }
  const mine = ++seq;
  box?.classList.add('loading');
  try {
    const result = await api('/compare', 'POST', {source: route.source, target: route.target, rank: s.rank,
      amount: s.mode === 'send' ? amount : null, receive_amount: s.mode === 'receive' ? amount : null});
    if (mine !== seq) return;
    s.result = result;
  } catch (e) {
    if (mine !== seq) return;
    s.result = {error: e.message};
  }
  const target = document.getElementById('compare');
  if (target) { target.classList.remove('loading'); target.innerHTML = comparison(s.result, route); }
}
