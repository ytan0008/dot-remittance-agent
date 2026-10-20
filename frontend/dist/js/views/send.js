import {state, t, api, toast, isOwner, canPrepare, invalidate, newId, $, rerender} from '../core.js';
import {esc, amt, tag, panel, field, options, segmented, icons, empty} from '../ui.js';
import {money, num, day, pct, region, decimalsOf, phrase, when, lang, currencyName} from '../i18n.js';
import {renderDetail} from './payments.js';
import {view as templatesView} from './templates.js';
import {recipientsPanels, recipientForm, ownAccountForm} from './wallets.js';
import {modal, need, bus} from '../core.js';
import {loadBanks, banksFor, pricingLine, ensureBank, bankName, autoLine, knowledgeList} from './banks.js';

const onTemplates = () => state.send.tab === 'templates';
const onRecipients = () => state.send.tab === 'recipients';
/** A confirmed bank transfer template linked to this recipient, if any. */
const templateFor = id => id ? (state.data.ttemplates || []).find(x => x.recipient_id === id && x.confirmed) : null;
const tplHint = id => { const x = templateFor(id); return x ? `${icons.check}${t('send.tpl_hint', {name: x.name})} <button type="button" class="link sm" data-action="send-tab" data-v="templates">${t('send.tpl_open')} ${icons.arrow}</button>` : ''; };

function tabs() {
  const tab = onTemplates() ? 'templates' : onRecipients() ? 'recipients' : 'compare';
  const icon = {compare: icons.send, recipients: icons.wallets, templates: icons.templates};
  return `<div class="page-tabs" role="tablist">${[['compare', t('send.tab_compare')], ['recipients', t('send.tab_recipients')], ['templates', t('send.tab_templates')]].map(([v, l]) =>
    `<button type="button" role="tab" aria-selected="${v === tab}" class="${v === tab ? 'on' : ''}" data-action="send-tab" data-v="${v}">${icon[v]}${esc(l)}</button>`).join('')}</div>`;
}

let timer = 0, seq = 0;
const insight = {};  // pair -> {latest, history, forecast} used by the reminder step

const PAIR_CURRENCIES = ['AUD', 'CNY', 'USD', 'EUR', 'GBP', 'JPY', 'KRW', 'HKD', 'SGD', 'NZD', 'CAD', 'VND', 'PHP', 'MXN', 'TWD', 'MYR', 'THB', 'IDR', 'INR'];
const HOME = {AUD: 'AU', CNY: 'CN', USD: 'US', JPY: 'JP', KRW: 'KR', HKD: 'HK', SGD: 'SG', NZD: 'NZ', CAD: 'CA', VND: 'VN', PHP: 'PH', MXN: 'MX', TWD: 'TW', MYR: 'MY', THB: 'TH', IDR: 'ID', GBP: 'GB', INR: 'IN'};
/** The route for a currency pair: a configured one when it exists (it may be payable in the sandbox), else a plan-only pair. */
const routeOf = id => (state.data.routes || []).find(r => r.id === id) || (String(id || '').startsWith('pair:') ? virtualRoute(...id.slice(5).split('-')) : undefined);
const virtualRoute = (source, target) => ({id: `pair:${source}-${target}`, source, target, send: HOME[source] || source, receive: HOME[target] || target,
  enabled: true, capabilities: {sandbox_payment: false}});
const routeFor = (source, target) => (state.data.routes || []).filter(r => r.enabled && r.source === source && r.target === target)
  .sort((a, b) => b.capabilities.sandbox_payment - a.capabilities.sandbox_payment)[0] || virtualRoute(source, target);

// The other side's currency is greyed out: you cannot send AUD to receive AUD.
const pairOptions = (selected, other) => PAIR_CURRENCIES.map(c => `<option value="${esc(c)}" ${c === selected ? 'selected' : ''} ${c === other ? 'disabled' : ''}>${esc(c)}</option>`).join('');

function pairCard(route) {
  const s = state.send, banks = banksFor(route.source, route.target) || [];
  const senders = banks.filter(b => b.currencies.includes(route.source)), receivers = banks.filter(b => b.currencies.includes(route.target));
  const pick = (id, list) => list.find(b => b.id === id);
  return `<div class="pair-card reveal">
    <div class="pair-sides">
      <label class="pair-select"><span>${t('send.you_pay')}</span><select id="pair-source" data-pair="source">${pairOptions(route.source, route.target)}</select><small>${esc(currencyName(route.source))}</small></label>
      <button class="swap" type="button" data-action="pair-swap" aria-label="${t('markets.swap')}">${icons.swap}</button>
      <label class="pair-select"><span>${toMe() ? t('send.i_receive') : t('send.they_receive')}</span><select id="pair-target" data-pair="target">${pairOptions(route.target, route.source)}</select><small>${esc(currencyName(route.target))}</small></label>
      <span class="pair-cap">${route.capabilities.sandbox_payment ? `<span class="tag k-sandbox_quote">${t('send.payable')}</span>` : ''}
        <button type="button" class="link sm" data-action="routes-open">${t('send.more_routes')}</button></span>
    </div>
    ${autoLine(route.source, route.target)}
    <div class="pair-banks">
      <div class="field"><label for="bank-send">${t('send.bank_send')} <small class="muted">${t('tf.optional')}</small></label>
        <select id="bank-send" data-bank-pick="send_bank"><option value="">${t('send.bank_any')}</option>${options(senders.map(b => [b.id, bankName(b)]), s.send_bank)}</select>
        <small class="bank-line">${s.send_bank ? pricingLine(pick(s.send_bank, senders)) + bankButtons(pick(s.send_bank, senders), route) : t('send.bank_hint')}</small>
        ${s.send_bank ? knowledgeList(pick(s.send_bank, senders)) : ''}</div>
      <div class="field"><label for="bank-recv">${t('send.bank_receive')} <small class="muted">${t('tf.optional')}</small></label>
        <select id="bank-recv" data-bank-pick="receive_bank"><option value="">${t('send.bank_any')}</option>${options(receivers.map(b => [b.id, bankName(b)]), s.receive_bank)}</select>
        <small class="bank-line">${s.receive_bank ? pricingLine(pick(s.receive_bank, receivers)) + bankButtons(pick(s.receive_bank, receivers), route) : t('send.bank_hint')}</small>
        ${s.receive_bank ? knowledgeList(pick(s.receive_bank, receivers)) : ''}</div>
    </div></div>`;
}

const bankButtons = (b, route) => !b || !isOwner() ? '' : ` <button type="button" class="link sm" data-action="bank-refresh" data-bank="${esc(b.id)}" data-s="${esc(route.source)}" data-t="${esc(route.target)}">${icons.agent}${t('bank.read')}</button>
  ${!b.pricing || b.pricing.status !== 'ok' ? `<button type="button" class="link sm" data-action="bank-edit" data-bank="${esc(b.id)}" data-s="${esc(route.source)}" data-t="${esc(route.target)}">${t('bank.edit')}</button>` : ''}`;

/* ---------- step 3: exchange scenarios through real banks ---------- */
function scenariosHtml(route) {
  const r = state.send.scen;
  if (!r) return `<p class="fine">${t('scen.hint')}</p>`;
  if (r.error) return `<p class="note warn">${esc(r.error)}</p>`;
  if (!r.scenarios.length) return `<p class="fine">${t('scen.none')}</p>`;
  const name = id => bankName((banksFor(route.source, route.target) || []).find(b => b.id === id)) || t('send.bank_any');
  const unit = r.mode === 'send' ? r.target : r.source;
  const fees = x => x.fees.length ? x.fees.map(f => `${t('scen.fee_' + f.kind)} ${esc(money(f.amount, f.currency))} ${esc(f.currency)}`).join(' · ')
    + (x.fees_total.converted ? ` · ${t('scen.fees_total', {a: money(x.fees_total.amount, x.fees_total.currency), c: x.fees_total.currency, r: num(x.fees_total.rate, 4)})}` : '')
    : `${t('scen.fees')} 0`;
  const card = x => `<li class="scen-card ${x.rank === 1 ? 'best' : ''} ${x.tier !== 'sourced' || !x.feasible ? 'dim' : ''}">
      <div class="scen-head"><span class="scen-rank">${x.rank ? String(x.rank).padStart(2, '0') : '—'}</span>
        <div><b>${esc(x.convert_at === 'receive_bank' ? t('scen.at_receive', {b: name(x.receive_bank)}) : x.convert_at === 'send_bank' ? t('scen.at_send', {b: name(x.send_bank)}) : t('scen.at_reference'))}</b>
          <small>${esc(name(x.send_bank))} → ${esc(name(x.receive_bank))} · ${x.timing === 'split' ? t('scen.split', {d: day(x.legs[1].date)}) : t('scen.once')}</small></div>
        ${x.rank === 1 ? `<span class="tag">${t('scen.best')}</span>` : ''}</div>
      <ul class="scen-legs">${x.legs.map(l => `<li><span>${day(l.date)}</span><span>−${esc(money(l.spend, r.source))} ${esc(r.source)}</span><span>${icons.arrow}</span><b>${esc(money(l.receive, r.target))} ${esc(r.target)}</b><small>${t('detail.rate')} ${num(l.rate, 4)}</small></li>`).join('')}</ul>
      <div class="scen-foot"><div>${amt(r.mode === 'send' ? x.total_receive : x.total_spend, unit, 'lg')}<small>${t(r.mode === 'send' ? 'send.they_get' : 'send.you_pay')}</small></div>
        <small>${fees(x)}${x.rate_source === 'reference' ? ' · ' + t('scen.ref_rate') : x.rate_source === 'estimate' ? ' · ' + t('scen.est_rate') : ''}</small>
        ${x.spread_cost > 0 ? `<small class="scen-spread">${t('scen.spread', {a: money(x.spread_cost, r.source), c: esc(r.source), p: num(x.spread_pct, 2)})}</small>` : ''}
        <small>${t('scen.arrive', {d: day(x.arrives_by), a: x.days[0], b: x.days[1]})}${x.latest_start ? ' · ' + t('scen.latest', {d: day(x.latest_start)}) : ''}</small>
        ${x.late ? `<small class="scen-unknown">${t('scen.late.' + x.late, {d: day(x.arrives_by), due: day(r.due), f: day(x.legs[x.legs.length - 1].date)})}</small>` : ''}
        ${x.unknown.length ? `<small class="scen-unknown">${t('scen.unknown')}: ${x.unknown.map(u => t('scen.u.' + u)).join(', ')}</small>` : ''}
        ${x.caveats.includes('intermediary') ? `<small class="muted">${t('scen.caveat_inter')}</small>` : ''}
        <span class="row-actions"><button class="button sm" data-action="scen-plan" data-id="${esc(x.id)}" ${isOwner() ? '' : 'disabled'}>${icons.plus}${t('scen.to_plan')}</button>
          <button class="button sm ghost" data-action="scen-sandbox" data-id="${esc(x.id)}">${t('scen.to_sandbox')} ${icons.arrow}</button></span></div></li>`;
  // Only complete, sourced figures that arrive in time are compared; the rest are shown for what they are.
  const groups = [['ranked', x => x.feasible && x.tier === 'sourced'], ['partial', x => x.feasible && x.tier === 'partial'],
    ['forecast', x => x.feasible && x.tier === 'forecast'], ['estimate', x => x.feasible && x.tier === 'estimate'],
    ['reference', x => x.feasible && x.tier === 'reference'], ['late', x => !x.feasible]];
  const blocks = groups.map(([g, f]) => [g, r.scenarios.filter(f)]).filter(([, list]) => list.length)
    .map(([g, list]) => `<p class="scen-sec">${t('scen.sec_' + g)}</p><ol class="scenarios">${list.map(card).join('')}</ol>`).join('');
  return `${r.scenarios.some(x => x.rank === 1) ? '' : `<p class="note">${t('scen.no_best')}</p>`}${blocks}
    ${r.forecast ? `<p class="fine">${t('scen.split_note', {d: day(r.forecast_day)})}</p>` : `<p class="fine">${t('scen.no_forecast')}</p>`}
    <p class="fine">${t('scen.note')}</p>`;
}

let scenTimer = 0, scenSeq = 0;
function scheduleScenarios(delay = 600) { clearTimeout(scenTimer); scenTimer = setTimeout(runScenarios, delay); }
async function runScenarios() {
  const s = state.send, route = routeOf(s.route);
  const amount = s.mode === 'send' ? s.amount : s.receive;
  if (!route || !amount || !(Number(amount) > 0)) { s.scen = null; paintScenarios(route); return; }
  const mine = ++scenSeq;
  try {
    const r = await api('/exchange-scenarios', 'POST', {source: route.source, target: route.target, amount, mode: s.mode,
      send_bank: s.send_bank || null, receive_bank: s.receive_bank || null, due: s.arrival || null});
    if (mine === scenSeq) s.scen = r;
  } catch (e) { if (mine === scenSeq) s.scen = {error: e.message}; }
  if (mine === scenSeq) paintScenarios(route);
}
function paintScenarios(route) {
  const box = document.getElementById('scenarios');
  if (box && route) { box.innerHTML = scenariosHtml(route); box.classList.remove('pop'); void box.offsetWidth; box.classList.add('pop'); }
}

/* ---------- me: my own accounts are "me", on both sides of a payment ---------- */
const mine = currency => (state.data.recipients || []).filter(r => r.kind === 'self' && r.enabled && r.currency === currency);
const last4 = a => a ? ' ····' + String(a).slice(-4) : '';
export const ownLabel = r => `${t('recipient.me')} · ${r.bank || r.currency}${last4(r.account)}`;
const chosen = () => (state.data.recipients || []).find(r => r.id === state.send.recipient);
const toMe = () => chosen()?.kind === 'self';
/** "I receive" when the money goes to my own account, "Anna receives" for someone else, "They receive" before choosing. */
const receiveWord = () => toMe() ? t('send.mode_receive_me') : chosen() ? t('send.mode_receive_x', {n: chosen().name}) : t('send.mode_receive');

/* No one to pay in this currency yet: fill the recipient in right here instead of leaving the page. */
function inlineRecipient(route) {
  const owner = isOwner() ? '' : 'disabled';
  return `<fieldset class="inline-recipient"><legend>${t('send.recipient')}</legend>
    <p class="fine">${t('send.r_inline', {c: route.target})}</p>
    <div class="grid-2">${field('ir-name', t('wallets.r_name'), `<input id="ir-name" maxlength="100" autocomplete="off" ${owner}>`)}
      ${field('ir-account', t('wallets.r_account'), `<input id="ir-account" maxlength="34" autocomplete="off" placeholder="${t('wallets.r_account_ph')}" ${owner}>`)}</div>
    <p class="form-error" id="ir-error"></p>
    <button type="button" class="button sm" data-action="inline-recipient" data-currency="${esc(route.target)}" data-country="${esc(route.receive || '')}" ${owner}>${icons.plus}${t('wallets.save_recipient')}</button>
    <button type="button" class="link sm" data-action="own-account" data-currency="${esc(route.target)}" data-country="${esc(route.receive || '')}" ${owner}>${t('send.its_me')}</button>
  </fieldset>`;
}

function form(route) {
  const s = state.send;
  const recipients = (state.data.recipients || []).filter(r => r.enabled && r.rail === 'sandbox' && r.currency === route.target);
  const myTo = recipients.filter(r => r.kind === 'self'), others = recipients.filter(r => r.kind !== 'self'), myFrom = mine(route.source);
  // A payment can count toward one of your exchange plans for this pair (it shows as that plan's progress).
  const goals = (state.data.sendPlans || []).filter(g => g.source === route.source && g.target === route.target)
    .map(g => ({id: g.id, title: `${g.purpose || g.source + '→' + g.target} · ${money(g.total ?? g.amount, g.amount_currency)} ${g.amount_currency}`}));
  const currency = s.mode === 'send' ? route.source : route.target;
  return `<form id="send-form" class="send-form" autocomplete="off">
    <p class="direction-line">${t(toMe() ? 'send.direction_me' : 'send.direction', {s: route.source, t: route.target})}</p>
    ${segmented('mode', [['send', t('send.mode_send')], ['receive', receiveWord()]], s.mode, 'send-mode')}
    <div class="amount-field"><label for="send-amount">${t(s.mode === 'send' ? 'send.amount' : 'send.receive_amount')}</label>
      <div class="amount-input"><input id="send-amount" name="amount" inputmode="decimal" placeholder="${decimalsOf(currency) ? '100.00' : '1000000'}" value="${esc(s.mode === 'send' ? s.amount : s.receive)}" maxlength="24" required><span>${esc(currency)}</span></div>
      <small>${t('send.decimals', {n: decimalsOf(currency)})}</small></div>
    <div class="grid-2 from-to">
      ${field('send-from', t('send.from'), `<select id="send-from" name="from_account"><option value="">${t('send.from_any')}</option>${options(myFrom.map(r => [r.id, ownLabel(r)]), s.from || '')}<option value="__me">${t('send.add_mine', {c: route.source})}</option></select>`)}
      ${recipients.length
        ? field('send-recipient', t('send.recipient'), `<select id="send-recipient" name="recipient" required><option value="">${t('send.choose_recipient')}</option>
          ${myTo.length ? `<optgroup label="${esc(t('send.to_me'))}">${options(myTo.map(r => [r.id, ownLabel(r)]), s.recipient)}</optgroup>` : ''}
          ${others.length ? `<optgroup label="${esc(t('send.to_others'))}">${options(others.map(r => [r.id, `${r.name} · ${r.id}`]), s.recipient)}</optgroup>` : ''}
          <option value="__me">${t('send.add_mine', {c: route.target})}</option><option value="__new">${t('send.r_new')}</option></select>`)
        : ''}</div>
    ${recipients.length ? '' : inlineRecipient(route)}
    ${toMe() ? `<p class="note">${t('send.self_note', {c: route.target})}</p>` : ''}
    <p class="fine tpl-hint" id="tpl-hint">${tplHint(s.recipient)}</p>
    ${field('send-purpose', t('send.purpose'), `<input id="send-purpose" name="purpose" maxlength="200" required placeholder="${t('send.purpose_ph')}" value="${esc(s.purpose)}">`)}
    <div class="grid-2">
      ${field('send-arrival', t('send.arrival'), `<input id="send-arrival" name="arrival" type="date" value="${esc(s.arrival)}">`)}
      ${field('send-goal', t('send.goal'), `<select id="send-goal" name="goal"><option value="">${t('common.none')}</option>${options(goals.map(g => [g.id, g.title]), s.goal)}</select>`)}
    </div>
    <div class="form-error"></div>
    <button class="button primary wide" ${canPrepare() && route.capabilities.sandbox_payment ? '' : 'disabled'}>${t('send.prepare')} ${icons.arrow}</button>
    <p class="fine">${t('send.prepare_note')}</p>
  </form>`;
}

function comparison(result) {
  if (!result) return `<div class="compare-empty"><span class="empty-orb"><i></i></span><p>${t('send.enter_amount')}</p></div>`;
  if (result.error) return `<div class="rate-error">${esc(result.error)}</div>`;
  const r = result, unit = r.mode === 'send' ? r.target : r.source;
  // The sandbox quote is not shown here (drafts come from the form); the remaining options are ranked among themselves.
  const shown = r.options.filter(o => o.kind !== 'sandbox_quote');
  const order = shown.filter(o => o.rank).sort((a, b) => a.rank - b.rank);
  const rankOf = o => o.rank ? order.indexOf(o) + 1 : 0;
  const ref = r.reference;
  return `<div class="compare-head">
      ${ref ? `<div><span class="eyebrow">${tag('reference')}</span><b>${num(ref.rate, 6)}</b> <small>${esc(r.target)}/${esc(r.source)}</small><small class="muted block">${esc(ref.provider)} · ${day(ref.observed)} · ${esc(phrase(ref.frequency || ''))}${ref.derived ? ' · ' + t('rates.derived') : ''}</small></div>` : `<div class="note warn">${t('send.no_reference')}</div>`}
      ${segmented('rank', [['receive', t(r.mode === 'send' ? 'send.rank_receive' : 'send.rank_cost')], ['speed', t('send.rank_speed')]], state.send.rank, 'send-rank')}
    </div>
    <p class="fine basis">${t('send.basis')}: ${esc(t('basis.' + r.rank + '.' + r.mode))}</p>
    <ol class="options">${shown.map(o => `<li class="option k-${esc(o.kind)} ${rankOf(o) === 1 ? 'best' : ''} reveal in">
      <div class="option-rank">${rankOf(o) ? String(rankOf(o)).padStart(2, '0') : '—'}</div>
      <div class="option-main"><div class="option-title">${tag(o.kind)}<b>${esc(t('option.' + o.id))}</b></div>
        <div class="option-facts"><span>${t('detail.fee')} ${o.fee ? esc(money(o.fee, r.source)) + ' ' + esc(r.source) : '0'}</span><span>${t('detail.rate')} ${num(o.applied_rate, 6)}</span><span>${t('detail.spread')} ${num(o.spread_pct, 2)}%</span>${o.eta ? `<span>${t('detail.eta')} ${esc(t('eta.' + o.id))}</span>` : ''}${o.cost_vs_reference_pct ? `<span>${t('send.vs_ref')} −${num(o.cost_vs_reference_pct, 2)}%</span>` : ''}</div>
        ${o.unknown_charges ? `<small class="muted">${t('send.unknown')}: ${esc(phrase(o.unknown_charges))}</small>` : ''}
      </div>
      <div class="option-amt">${amt(r.mode === 'send' ? o.receive : o.send, unit, 'lg')}<small>${t(r.mode === 'send' ? 'send.they_get' : 'send.you_pay')}</small>
        ${o.kind === 'sandbox_quote' && o.executable ? `<button class="button sm primary" data-action="submit-send">${t('send.prepare_short')}</button>` : ''}
        ${rankOf(o) === 1 && isOwner() ? `<button class="link sm" data-action="accept-rec" data-id="${esc(o.id)}">${t('send.accept')}</button>` : ''}</div>
    </li>`).join('')}</ol>
    ${r.notes?.length ? `<div class="notes">${r.notes.map(n => `<p class="fine">· ${esc(phrase(n))}</p>`).join('')}</div>` : ''}
    <p class="fine">${t('send.disclaimer')}</p>`;
}

/* ---------- step 3: plan the timing and get an exchange reminder ---------- */
function reminderStep(route) {
  const key = route.source + '-' + route.target, info = insight[key];
  const s = state.send;
  const alerts = (state.data.alerts || []).filter(a => a.source === route.source && a.target === route.target);
  const latest = info?.latest ? Number(info.latest.rate) : null;
  const fc = info?.forecast?.available ? info.forecast : null;
  const suggested = latest ? Math.max(latest * 1.01, fc ? Number(fc.interval_80[1]) : 0) : '';
  const r = s.rem || (s.rem = {target: true, favorable: false, dated: null, threshold: '', top: '20', due: '', notify: null});
  const defaultDate = s.arrival ? new Date(Date.parse(s.arrival) - 3 * 864e5).toISOString().slice(0, 10) : new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);
  const plan = info ? `<div class="plan-read">
      <div><span class="eyebrow">${t('rem.today')}</span><b>${latest ? num(latest, 5) : '—'}</b><small>${esc(route.target)} / 1 ${esc(route.source)}</small></div>
      <div><span class="eyebrow">${t('rem.position')}</span><b>${info.history ? t('rates.position.' + info.history.position) : '—'}</b><small>${info.history ? t('rem.percentile', {p: num(info.history.percentile, 0)}) : ''}</small></div>
      <div><span class="eyebrow">${t('rem.forecast')}</span><b>${fc ? `${num(fc.interval_80[0], 4)} – ${num(fc.interval_80[1], 4)}` : '—'}</b><small>${fc ? (fc.beats_baseline ? t('rem.fc_ok') : t('rem.fc_weak')) : t('rem.fc_none')}</small></div>
    </div><p class="fine">${t('rem.plan_note', {s: route.source, t: route.target})}</p>` : `<p class="fine">${t('common.loading')}</p>`;
  const list = alerts.length ? `<ul class="list alert-list">${alerts.map(a => `<li class="row"><span class="state-dot ${a.active ? '' : 'off'}"></span><div><b>${esc(alertText(a))}</b><small>${a.triggered_at ? t('markets.triggered', {at: when(a.triggered_at)}) : a.active ? t('markets.armed') : '—'}${a.note ? ' · ' + esc(a.note) : ''}</small></div>
      <button class="pill sm ${a.active ? 'on' : ''}" data-action="toggle-alert" data-id="${esc(a.id)}" data-active="${a.active ? 0 : 1}" ${isOwner() ? '' : 'disabled'}>${a.active ? t('markets.armed') : t('markets.rearm')}</button></li>`).join('')}</ul>` : '';
  const custom = `<details class="custom-rules" ${alerts.length ? 'open' : ''}><summary>${icons.plus}${t('watch.custom')}</summary><p class="fine">${t('watch.custom_d')}</p>
    <form id="reminder-form" class="reminder-options">
      <label class="rem-opt"><input type="checkbox" name="target" ${r.target ? 'checked' : ''}><span><b>${t('rem.target')}</b><span class="rem-line">${t('rem.target_line', {s: route.source, t: route.target})} <input name="threshold" inputmode="decimal" value="${esc(r.threshold || (suggested ? Number(suggested).toFixed(4) : ''))}" class="mini-input"> ${esc(route.target)}</span></span></label>
      <label class="rem-opt"><input type="checkbox" name="favorable" ${r.favorable ? 'checked' : ''}><span><b>${t('rem.favorable')}</b><span class="rem-line">${t('rem.favorable_line')} <select name="top" class="mini-input">${options([['20', '20%'], ['10', '10%'], ['30', '30%']], r.top)}</select></span></span></label>
      <label class="rem-opt"><input type="checkbox" name="dated" ${(r.dated ?? !!s.arrival) ? 'checked' : ''}><span><b>${t('rem.date')}</b><span class="rem-line">${t('rem.date_line')} <input type="date" name="due" value="${esc(r.due || defaultDate)}" class="mini-input"></span></span></label>
      <label class="check-label notify-opt"><input type="checkbox" name="notify" ${(r.notify ?? notifyOn()) ? 'checked' : ''}> ${t('rem.notify')}</label>
      <div class="form-error"></div>
      <button class="button primary" ${isOwner() ? '' : 'disabled'}>${icons.check}${t('rem.create')}</button>
    </form>${list}</details>`;
  return panel(`<span class="step-n">4</span>${t('rem.title')}`, `${aiCard(route, info, plan)}${needsForm(route, info)}${custom}`,
    {cls: 'reminder-step', id: 'reminder-step'});
}

const signed = x => (Number(x) > 0 ? '+' : '') + num(x, 2) + '%';

function aiCard(route, info, plan) {
  const a = info?.advice, pair = `${route.source}→${route.target}`;
  if (!a) return `<div class="ai-watch loading"><div class="ai-head"><span class="ai-orb"><i></i><b></b></span><div><span class="eyebrow">${t('watch.title')}</span>
    <h3>${info?.adviceError ? esc(info.adviceError) : t('watch.loading')}</h3></div></div>${plan}</div>`;
  const reason = r => t('watch.r.' + r.code, {p: num(r.p ?? 0, 0), pct: signed(r.pct ?? 0), days: r.days, rate: r.rate});
  return `<div class="ai-watch v-${esc(a.verdict)}">
    <div class="ai-head"><span class="ai-orb"><i></i><b></b></span>
      <div><span class="eyebrow">${t('watch.title')} · ${t('watch.by_' + a.judged_by)} · ${t('watch.conf.' + a.confidence)}</span><h3>${esc(t('watch.v.' + a.verdict, {pair}))}</h3></div>
      <button class="pill ${a.watching ? 'on' : ''}" data-action="watch-toggle" ${isOwner() ? '' : 'disabled'}>${a.watching ? t('watch.on') : t('watch.off')}</button></div>
    ${a.explanation ? `<p class="ai-why">${esc(a.explanation)}</p>` : ''}
    <ul class="ai-reasons">${a.reasons.map(r => `<li class="r-${esc(r.code)}">${esc(reason(r))}</li>`).join('')}</ul>
    ${plan}
    <p class="fine">${t('watch.note')}</p></div>`;
}

function needsForm(route, info) {
  const n = info?.advice?.needs || {}, s = state.send;
  const amount = s.mode === 'receive' ? s.receive : '';  // each save adds a plan; existing plans are listed on the overview
  const planned = n.plans ? `<p class="fine">${t('watch.planned', {n: n.plans, a: n.amount ? money(n.amount, route.target) + ' ' + route.target : '—'})} <button type="button" class="link sm" data-action="go" data-view="overview">${t('nav.overview')} ${icons.arrow}</button></p>` : '';
  return `<form id="needs-form" class="needs-form"><div><span class="eyebrow">${t('watch.needs')}</span><p class="fine">${t('watch.needs_d')}</p>${planned}</div>
    <div class="needs-grid">
      ${field('nd-amount', t('watch.amount', {c: route.target}), `<input id="nd-amount" name="amount" inputmode="decimal" value="${esc(amount)}" placeholder="0">`)}
      ${field('nd-deadline', t('watch.deadline'), `<input id="nd-deadline" name="deadline" type="date" value="${esc(s.arrival || '')}">`)}
      ${field('nd-rate', t('watch.min_rate'), `<input id="nd-rate" name="min_rate" inputmode="decimal" value="${esc(n.min_rate || '')}" placeholder="${esc(info?.history?.median ? num(info.history.median, 4) : '')}">`)}
      ${field('nd-note', t('watch.note_field'), `<input id="nd-note" name="note" maxlength="120" value="${esc(s.purpose || '')}">`)}
    </div><div class="form-error"></div><button class="button sm" ${isOwner() ? '' : 'disabled'}>${icons.check}${t('watch.save')}</button></form>`;
}

function notifyOn() { try { return localStorage.getItem('dot.notify') === '1'; } catch { return false; } }

function rememberReminder(e) {
  const r = state.send.rem, el = e.target;
  if (!r || !el.name) return;
  r[el.name] = el.type === 'checkbox' ? el.checked : el.value;
}

// One listener for the page's lifetime: the reminder step is re-rendered often (insight load, live refresh).
document.addEventListener('input', e => e.target.closest?.('#reminder-form') && rememberReminder(e));

export function alertText(a) {
  if (a.condition === 'date') return t('rem.when_date', {d: day(a.due_date)});
  if (a.condition === 'percentile') return t('rem.when_top', {p: 100 - Number(a.threshold), s: a.source, t: a.target});
  return t(a.condition === 'above' ? 'rem.when_above' : 'rem.when_below', {s: a.source, t: a.target, r: num(a.threshold, 4)});
}

/** Replace step 3 in place; the new panel is already on screen, so it must not wait for the reveal animation. */
function swapStep(route) {
  const box = document.getElementById('reminder-step');
  if (!box || state.view !== 'send' || state.send.route !== route.id) return;
  box.outerHTML = reminderStep(route);
  document.getElementById('reminder-step')?.classList.add('in');
}

const adviceFor = route => api(`/exchange-advice?source=${route.source}&target=${route.target}&lang=${encodeURIComponent(lang)}`);

async function refreshAdvice(route) {
  const info = insight[route.source + '-' + route.target] || {};
  try { info.advice = await adviceFor(route); delete info.adviceError; } catch (e) { info.adviceError = e.message; }
  insight[route.source + '-' + route.target] = info;
  swapStep(route);
}

async function loadInsight(route) {
  const key = route.source + '-' + route.target;
  if (insight[key]) return;
  const [latest, history, forecast, advice] = await Promise.allSettled([
    api(`/rates/latest?source=${route.source}&target=${route.target}`), api(`/rates?source=${route.source}&target=${route.target}&days=90`),
    api(`/rates/forecast?source=${route.source}&target=${route.target}`), adviceFor(route)]);
  insight[key] = {latest: latest.value, history: history.value, forecast: forecast.value, advice: advice.value, adviceError: advice.reason?.message};
  swapStep(route);
}

export const view = {
  id: 'send',
  needs: ['routes', 'recipients', 'balances', 'alerts'],
  async load() {
    if (onTemplates()) { await templatesView.load(); return; }
    if (onRecipients()) { await need(['settings']); return; }
    try { state.data.ttemplates = await api('/transfer-templates'); } catch { /* the recipient hint is optional */ }
    try { state.data.sendPlans = await api('/exchange-plans'); } catch { state.data.sendPlans = []; }
    const route = routeOf(state.send.route) || routeFor('AUD', 'CNY');
    await loadBanks(route.source, route.target);
  },
  render() {
    if (onTemplates()) return tabs() + (state.data.tformats ? templatesView.render() : empty(t('common.loading')));
    if (onRecipients()) return tabs() + recipientsPanels();
    let route = routeOf(state.send.route);
    if (!route) { route = (state.data.routes || []).find(r => r.enabled && r.capabilities.sandbox_payment) || routeFor('AUD', 'CNY'); state.send.route = route.id; }
    const balance = (state.data.balances || []).find(b => b.currency === route.source);
    return `${tabs()}${pairCard(route)}
      <div class="send-layout">
        ${panel(`<span class="step-n">1</span>${esc(currencyName(route.source))} <span class="muted">→</span> ${esc(currencyName(route.target))}`, form(route),
          {sub: balance ? `${t(balance.basis === 'cash' ? 'send.avail_cash' : 'send.avail_test')} ${esc(money(balance.available, balance.currency))} ${esc(balance.currency)}` : '', cls: 'send-panel'})}
        ${panel(`<span class="step-n">2</span>${t('send.compare')}`, `<div id="compare">${comparison(state.send.result)}</div>`, {cls: 'compare-panel', sub: t('send.live')})}
      </div>
      ${panel(`<span class="step-n">3</span>${t('scen.title')}`, `<div id="scenarios">${scenariosHtml(route)}</div>`, {cls: 'scen-panel', sub: t('scen.sub'),
        actions: `<button class="button sm" data-action="scen-run">${icons.reset}${t('scen.run')}</button>`})}
      ${reminderStep(route)}`;
  },
  mount(root) {
    if (state.send.openRoutes) { state.send.openRoutes = false; routesDialog(); }
    if (onTemplates()) { templatesView.mount(root); return; }
    if (onRecipients()) return;
    const route = routeOf(state.send.route);
    root.querySelector('#send-form')?.addEventListener('input', e => {
      const s = state.send, name = e.target.name;
      if (name === 'amount') { if (s.mode === 'send') s.amount = e.target.value; else s.receive = e.target.value; schedule(); scheduleScenarios(); }
      if (name === 'recipient' && e.target.value === '__new') {  // "+ New recipient…": add one without leaving, it is picked when saved
        e.target.value = s.recipient || ''; recipientForm({currency: route.target, country: route.receive || ''}); return;
      }
      if ((name === 'recipient' || name === 'from_account') && e.target.value === '__me') {  // add one of my own accounts here
        e.target.value = (name === 'recipient' ? s.recipient : s.from) || '';
        ownAccountForm({currency: name === 'recipient' ? route.target : route.source, country: name === 'recipient' ? route.receive || '' : route.send || '', pick: name});
        return;
      }
      if (name === 'recipient') {
        const wasMe = toMe();
        s.recipient = e.target.value; const hint = root.querySelector('#tpl-hint'); if (hint) hint.innerHTML = tplHint(s.recipient);
        const r = chosen(), bank = r?.kind === 'self' && r.bank_id && banksFor(route.source, route.target)?.some(b => b.id === r.bank_id) ? r.bank_id : null;
        if (bank && bank !== s.receive_bank) { s.receive_bank = bank; s.scen = null; scheduleScenarios(0); }
        if (bank || wasMe !== toMe()) (bus.repaint || rerender)();  // the labels say "I receive" now
      }
      if (name === 'from_account') {
        s.from = e.target.value;
        const r = (state.data.recipients || []).find(x => x.id === s.from);
        if (r?.bank_id && banksFor(route.source, route.target)?.some(b => b.id === r.bank_id)) { s.send_bank = r.bank_id; s.scen = null; scheduleScenarios(0); (bus.repaint || rerender)(); }
      }
      if (name === 'purpose') s.purpose = e.target.value;
      if (name === 'arrival') s.arrival = e.target.value;
      if (name === 'goal') s.goal = e.target.value;
    });
    if (route) loadInsight(route);
    if (!state.send.result && (state.send.amount || state.send.receive)) schedule(0);
    if (!state.send.scen && (state.send.amount || state.send.receive)) scheduleScenarios(0);
    root.querySelectorAll('select[data-pair]').forEach(sel => sel.addEventListener('change', () => {
      const cur = routeOf(state.send.route), source = sel.dataset.pair === 'source' ? sel.value : cur.source, target = sel.dataset.pair === 'target' ? sel.value : cur.target;
      if (source === target) { pickPair(cur.target, cur.source); return; }  // picking the other side's currency swaps the two
      pickPair(source, target);
    }));
    root.querySelectorAll('select[data-bank-pick]').forEach(sel => sel.addEventListener('change', async () => {
      state.send[sel.dataset.bankPick] = sel.value; state.send.scen = null;
      const r = routeOf(state.send.route);
      if (sel.value && !banksFor(r.source, r.target)?.find(b => b.id === sel.value)?.pricing) {
        sel.closest('.field')?.querySelector('.bank-line')?.replaceChildren(document.createTextNode(t('bank.reading')));
        await ensureBank(sel.value, r.source, r.target);  // pages first, then the AI's knowledge; a hand entry only if both fail
      }
      (bus.repaint || rerender)(); scheduleScenarios(0);  // the select keeps focus: a plain render would wait for it to blur
    }));
  },
  actions: {
    async 'send-tab'(el) {
      state.send.tab = ['templates', 'recipients'].includes(el.dataset.v) ? el.dataset.v : 'compare';
      await view.load();
      rerender();
      scrollTo({top: 0, behavior: 'smooth'});
    },
    async 'routes-open'() { await need(['economies']); routesDialog(); },
    async 'rt-toggle'(el) {
      await api('/routes/' + encodeURIComponent(el.dataset.id), 'PATCH', {[el.dataset.field]: el.dataset.value === '1'});
      invalidate(['routes']); await need(['routes']); routesDialog(); rerender();
    },
    'pick-route'(el) { state.send.route = el.dataset.value; state.send.result = null; state.send.recipient = ''; rerender(); schedule(0); },
    async 'inline-recipient'(el) {
      const box = el.closest('.inline-recipient'), name = box.querySelector('#ir-name').value.trim(), account = box.querySelector('#ir-account').value.replace(/\s+/g, '');
      const err = box.querySelector('#ir-error');
      if (!name) { err.textContent = t('send.r_name_needed'); box.querySelector('#ir-name').focus(); return; }
      const slug = name.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
      const taken = new Set((state.data.recipients || []).map(r => r.id));
      let id = slug || 'r-' + Date.now().toString(36);
      for (let n = 2; taken.has(id); n++) id = `${slug || 'r'}-${n}`;
      try {
        await api('/recipients', 'POST', {recipient_id: id, name, address: '', currency: el.dataset.currency, country: el.dataset.country, account, kind: 'individual', enabled: true});
      } catch (e) { err.textContent = e.message; return; }
      invalidate(['recipients']); await need(['recipients'], true);
      state.send.recipient = id; toast(t('wallets.saved'), 'good'); rerender();
    },
    'pair-swap'() { const r = routeOf(state.send.route); pickPair(r.target, r.source); },
    'scen-run'() { runScenarios(); },
    async 'scen-plan'(el) {
      const r = state.send.scen, x = r.scenarios.find(y => y.id === el.dataset.id);
      for (const l of x.legs) {
        await api('/exchange-plans', 'POST', {source: r.source, target: r.target, amount: money(l.receive, r.target).replace(/,/g, ''), side: 'receive', due: l.date,
          purpose: state.send.purpose || t('scen.plan_purpose'), kind: 'custom'});
      }
      invalidate(['money']); toast(t('scen.planned', {n: x.legs.length}), 'good');
    },
    'scen-sandbox'(el) {
      const r = state.send.scen, x = r.scenarios.find(y => y.id === el.dataset.id);
      const name = id => bankName((banksFor(r.source, r.target) || []).find(b => b.id === id));
      state.sandboxScenario = {source: r.source, target: r.target, label: [name(x.send_bank), name(x.receive_bank)].filter(Boolean).join(' → ') || t('scen.at_reference'),
        timing: x.timing, legs: x.legs.map(l => ({date: l.date, spend: l.spend, receive: l.receive}))};
      location.hash = 'sandbox';
    },
    'own-account'(el) { ownAccountForm({currency: el.dataset.currency, country: el.dataset.country, pick: 'recipient'}); },
    'send-mode'(el) { state.send.mode = el.dataset.value; state.send.result = null; rerender(); schedule(0); },
    'send-rank'(el) { state.send.rank = el.dataset.value; schedule(0); },
    async 'watch-toggle'() {
      const route = routeOf(state.send.route), a = insight[route.source + '-' + route.target]?.advice;
      const n = a?.needs || {};
      await api('/watches', 'PUT', {source: route.source, target: route.target, amount: n.amount ? money(n.amount, route.target).replace(/,/g, '') : null,
        deadline: n.deadline || null, min_rate: n.min_rate || null, note: n.note || '', active: !a?.watching});
      toast(t(a?.watching ? 'watch.toggled_off' : 'watch.toggled_on', {pair: `${route.source}→${route.target}`}), 'good');
      await refreshAdvice(route);
    },
    async 'toggle-alert'(el) { await api('/rate-alerts/' + encodeURIComponent(el.dataset.id), 'PATCH', {active: el.dataset.active === '1'}); invalidate(['alerts']); rerender(); },
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
    async 'rt-form'(f) {
      await api('/routes', 'POST', {send: f.querySelector('[name=send]').value, receive: f.querySelector('[name=receive]').value});
      invalidate(['routes']); await need(['routes']); toast(t('routes.added'), 'good'); routesDialog(); rerender();
    },
    async 'send-form'() {
      const s = state.send, route = routeOf(s.route);
      const amount = s.mode === 'send' ? s.amount : null;
      const result = await api('/transfers', 'POST', {amount: amount || null, receive_amount: amount ? null : s.receive || null,
        source: route.source, target: route.target, recipient_id: s.recipient, purpose: s.purpose,
        arrival_by: s.arrival || null, goal_id: s.goal || null, idempotency_key: s.key});
      s.key = newId();
      invalidate();
      renderDetail(result);
      const tpl = templateFor(s.recipient);
      toast(tpl ? `${t('send.drafted')} ${t('send.tpl_after', {name: tpl.name})}` : t('send.drafted'), 'good');
    },
    async 'needs-form'(f) {
      const route = routeOf(state.send.route), v = Object.fromEntries(new FormData(f));
      const amount = String(v.amount || '').replace(/,/g, '').trim(), floor = String(v.min_rate || '').replace(',', '.') || null;
      if (amount) {  // a need with an amount is an exchange plan: it shows on the overview, in the sandbox and in gaps
        await api('/exchange-plans', 'POST', {source: route.source, target: route.target, amount, side: 'receive', due: v.deadline || null,
          purpose: v.note || '', kind: 'custom', min_rate: floor});
        invalidate(['money']);
      } else {
        await api('/watches', 'PUT', {source: route.source, target: route.target, amount: null, deadline: v.deadline || null, min_rate: floor, note: v.note || '', active: true});
      }
      toast(t(amount ? 'watch.saved_plan' : 'watch.saved'), 'good');
      await refreshAdvice(route);
    },
    async 'reminder-form'(f) {
      const route = routeOf(state.send.route), v = Object.fromEntries(new FormData(f));
      const s = state.send, recipient = (state.data.recipients || []).find(r => r.id === s.recipient);
      const amount = s.mode === 'send' ? s.amount && `${s.amount} ${route.source}` : s.receive && `${s.receive} ${route.target}`;
      const note = [amount, recipient?.name, s.purpose].filter(Boolean).join(' · ').slice(0, 120);
      const base = {source: route.source, target: route.target, note};
      const jobs = [];
      if (v.target) jobs.push({...base, condition: 'above', threshold: String(v.threshold || '').replace(',', '.')});
      if (v.favorable) jobs.push({...base, condition: 'percentile', threshold: String(100 - Number(v.top)), window: '90'});
      if (v.dated) jobs.push({...base, condition: 'date', due_date: v.due});
      if (!jobs.length) throw new Error(t('rem.pick_one'));
      if (v.notify) await enableNotifications(); else try { localStorage.setItem('dot.notify', '0'); } catch { /* storage blocked */ }
      for (const j of jobs) await api('/rate-alerts', 'POST', j);
      invalidate(['alerts', 'reminders']);
      state.send.rem = null;
      toast(t('rem.created', {n: jobs.length}), 'good');
      rerender();
    },
  },
};

export async function enableNotifications() {
  try {
    if (!('Notification' in window)) return false;
    const p = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission;
    localStorage.setItem('dot.notify', p === 'granted' ? '1' : '0');
    if (p !== 'granted') toast(t('rem.notify_denied'));
    return p === 'granted';
  } catch { return false; }
}

function schedule(delay = 380) {
  clearTimeout(timer);
  timer = setTimeout(compare, delay);
}

async function compare() {
  const s = state.send, route = routeOf(s.route);
  const box = document.getElementById('compare');
  if (!route) return;
  const amount = s.mode === 'send' ? s.amount : s.receive;
  if (!amount || !/^\d+(\.\d+)?$/.test(amount) || Number(amount) <= 0) { s.result = null; if (box) box.innerHTML = comparison(null); return; }
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
  if (target) { target.classList.remove('loading'); target.innerHTML = comparison(s.result); }
}

/* ---------- the route manager: which corridors appear above (formerly its own page) ---------- */
function routesDialog() {
  const routes = state.data.routes || [], economies = state.data.economies || [], owner = isOwner();
  const econ = economies.map(e => [e.code, region(e.code) + ' · ' + e.currency]);
  modal(t('routes.title'), `<p class="fine">${t('routes.note')}</p>
    <ul class="list rt-list">${routes.map(r => `<li class="row ${r.enabled ? '' : 'disabled'}"><div><b>${esc(region(r.send))} → ${esc(region(r.receive))}</b>
      <small>${esc(r.source)}/${esc(r.target)} · ${r.capabilities.sandbox_payment ? t('send.payable') : t('send.analysis_only')}</small></div>
      <button class="pill sm ${r.enabled ? 'on' : ''}" data-action="rt-toggle" data-id="${esc(r.id)}" data-field="enabled" data-value="${r.enabled ? 0 : 1}" ${owner ? '' : 'disabled'}>${t(r.enabled ? 'routes.enabled' : 'routes.disabled')}</button></li>`).join('')}</ul>
    ${econ.length ? `<form id="rt-form" class="form-block rt-add"><div class="grid-2">
      ${field('rt-send', t('routes.send'), `<select id="rt-send" name="send">${options(econ, 'AU')}</select>`)}
      ${field('rt-recv', t('routes.receive'), `<select id="rt-recv" name="receive">${options(econ, 'VN')}</select>`)}</div>
      <p class="fine">${t('routes.add_note')}</p><div class="form-error"></div>
      <div class="modal-actions"><button class="button" ${owner ? '' : 'disabled'}>${icons.plus}${t('routes.add_btn')}</button></div></form>` : ''}`, 'ROUTES / CORRIDORS', {wide: true});
}

async function pickPair(source, target) {
  const route = routeFor(source, target);
  Object.assign(state.send, {route: route.id, result: null, scen: null, recipient: '', send_bank: '', receive_bank: ''});
  await loadBanks(source, target);
  rerender(); schedule(0); scheduleScenarios(0);
}
