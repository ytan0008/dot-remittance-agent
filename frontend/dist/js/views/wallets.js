import {state, t, api, toast, isOwner, invalidate, rerender, value, modal, closeModal, need} from '../core.js';
import {esc, amt, panel, field, options, icons, empty, dl, mono, tag} from '../ui.js';
import {money, day, num, when, region, currencyName, plain} from '../i18n.js';

const ECON = ['AU', 'BN', 'CA', 'CL', 'CN', 'HK', 'ID', 'JP', 'KR', 'MY', 'MX', 'NZ', 'PG', 'PE', 'PH', 'RU', 'SG', 'TW', 'TH', 'US', 'VN'];
const CUR = {AU: 'AUD', BN: 'BND', CA: 'CAD', CL: 'CLP', CN: 'CNY', HK: 'HKD', ID: 'IDR', JP: 'JPY', KR: 'KRW', MY: 'MYR', MX: 'MXN', NZ: 'NZD', PG: 'PGK', PE: 'PEN', PH: 'PHP', RU: 'RUB', SG: 'SGD', TW: 'TWD', TH: 'THB', US: 'USD', VN: 'VND'};

export function ledgerPanel() {
  return panel(t('wallets.ledger'), ledger(), {sub: t('kind.simulation'), cls: 'ledger-panel'});
}

export function recipientsPanels() {
  return `${panel(t('wallets.recipients'), recipients(), {actions: `<button class="button" data-action="new-recipient" ${isOwner() ? '' : 'disabled'}>${icons.plus}${t('action.add_recipient')}</button>`})}
    ${panel(t('autonomy.limits'), limits(), {sub: t('wallets.limits_sub')})}`;
}

/** Bars and the display-currency switch of the test-money ledger, wherever it is shown. */
export function mountLedger(root) {
  root.querySelectorAll('.ledger .bar-fill[data-ratio]').forEach(el => el.style.setProperty('--ratio', el.dataset.ratio));
  root.querySelector('#display-currency')?.addEventListener('change', async e => {
    state.display = e.target.value; invalidate(['equivalents']); await need(['equivalents']); rerender();
  });
}

const SANDBOX_CURRENCIES = ['AUD', 'CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'NZD', 'CAD', 'SGD', 'KRW', 'VND'];

function ledger() {
  const list = (state.data.balances || []).filter(b => b.rail === 'sandbox');
  const eq = Object.fromEntries((state.data.equivalents || []).map(e => [e.currency, e]));
  // only what you hold (from the overview) or added here yourself; anything else is one tap away
  const add = isOwner() ? `<button class="button sm ghost" data-action="sandbox-add">${icons.plus}${t('wallets.add_currency')}</button>` : '';
  if (!list.length) return `<div class="ledger-empty"><p>${t('wallets.ledger_empty')}</p><div class="row-actions">${add}
    <button class="link sm" data-action="go" data-view="overview">${t('wallets.ledger_record')} ${icons.arrow}</button></div></div>`;
  return `<div class="ledger">${list.map(b => {
    const ratio = Number(b.total) > 0 ? Number(b.reserved) / Number(b.total) : 0;
    const e = eq[b.currency];
    return `<div class="ledger-row reveal"><div class="cur-badge"><b>${esc(b.currency)}</b><small>${esc(currencyName(b.currency))}</small></div>
      <div class="ledger-main"><div class="ledger-amt">${amt(b.available, b.currency, 'lg')}<small>${t('wallets.available')}</small></div>
        <div class="split-bar"><i class="bar-fill" data-ratio="${(1 - ratio).toFixed(4)}"></i></div>
        <div class="ledger-facts"><span>${t('wallets.total')} ${esc(money(b.total, b.currency))}</span><span>${t('wallets.reserved')} ${esc(money(b.reserved, b.currency))}</span>
        ${e && b.currency !== state.display ? `<span class="equiv">${e.total !== null ? `≈ ${esc(money(e.total, state.display))} ${esc(state.display)} <small>${t('wallets.equiv_label', {p: esc(e.provider || ''), d: day(e.observed)})}</small>` : t('wallets.equiv_unavailable')}</span>` : ''}</div></div>
      ${isOwner() ? `<div class="ledger-acts"><button class="button sm ghost" data-action="fund" data-currency="${esc(b.currency)}">${icons.plus}${t('wallets.fund')}</button>
        ${b.basis === 'test_funds' && b.reserved === '0' ? `<button class="link sm" data-action="sandbox-remove" data-currency="${esc(b.currency)}">${t('wallets.remove_currency')}</button>` : ''}</div>` : ''}</div>`;
  }).join('')}</div>
  <div class="toolbar">${add}<label class="inline-select">${t('wallets.display')} <select id="display-currency">${options(['AUD', 'USD', 'CNY', 'EUR', 'JPY', 'VND'].map(c => [c, c]), state.display)}</select></label><span class="fine">${t('wallets.ledger_note')}</span></div>`;
}

const last4 = a => a ? ' ····' + String(a).slice(-4) : '';
const ME_BANKS = ['中国银行', 'Bank of China (Australia)', '工商银行', '建设银行', '招商银行', 'Commonwealth Bank', 'Westpac', 'ANZ', 'NAB'];

/** My own accounts: always "me", one per bank card; a payment between them is a move of my own money. */
function myAccounts() {
  const list = (state.data.recipients || []).filter(r => r.kind === 'self');
  return `<div class="my-accounts"><div class="my-head"><b>${t('wallets.my_accounts')}</b><small>${t('wallets.my_accounts_d')}</small></div>
    ${list.length ? `<ul class="list">${list.map(r => `<li class="row"><span class="initial me">${esc(t('recipient.me_short'))}</span><div><b>${esc(t('recipient.me'))} · ${esc(r.bank || '—')}</b>
      <small>${esc(r.currency)}${r.country ? ' · ' + esc(region(r.country)) : ''}${esc(last4(r.account))} · <span class="mono">${esc(r.id)}</span></small></div>
      <button class="x" data-action="own-remove" data-id="${esc(r.id)}" aria-label="${t('common.delete')}" ${isOwner() ? '' : 'disabled'}>×</button></li>`).join('')}</ul>` : ''}
    <button class="button sm ghost" data-action="own-account" ${isOwner() ? '' : 'disabled'}>${icons.plus}${t('wallets.add_mine')}</button></div>`;
}

/** Add one of my own bank accounts. The name is fixed ("me"); only the bank, currency and number are mine to fill in. */
export function ownAccountForm({currency = '', country = '', pick = ''} = {}) {
  if (!isOwner()) { toast(t('err.owner_required'), 'bad'); return; }
  modal(t('wallets.add_mine'), `<form id="own-form" class="form-block" data-pick="${esc(pick)}"><p class="intro">${t('wallets.own_note')}</p>
      <div class="grid-2">${field('o-name', t('wallets.r_name'), `<input id="o-name" value="${esc(t('recipient.me'))}" disabled>`, t('wallets.own_fixed'))}
        ${field('o-currency', t('wallets.r_currency'), `<select id="o-currency" name="currency" required>${options([...new Set(Object.values(CUR))].map(c => [c, c]), currency || 'AUD')}</select>`)}</div>
      <div class="grid-2">${field('o-bank', t('wallets.own_bank'), `<input id="o-bank" name="bank" maxlength="80" list="own-banks" required placeholder="${t('wallets.own_bank_ph')}"><datalist id="own-banks">${ME_BANKS.map(b => `<option value="${esc(b)}">`).join('')}</datalist>`)}
        ${field('o-country', t('wallets.r_country'), `<select id="o-country" name="country"><option value="">—</option>${options(ECON.map(c => [c, region(c)]), country)}</select>`)}</div>
      ${field('o-account', t('wallets.r_account'), `<input id="o-account" name="account" maxlength="34" placeholder="${t('wallets.r_account_ph')}">`, t('wallets.r_account_hint'))}
      <div class="form-error"></div><div class="modal-actions"><button class="button primary">${t('wallets.save_mine')} ${icons.arrow}</button></div></form>`, 'ME / MY ACCOUNT');
}

function recipients() {
  const list = (state.data.recipients || []).filter(r => r.rail !== 'evm' && r.kind !== 'self');
  return `${myAccounts()}${list.length ? `<ul class="list">${list.map(r => `<li class="row ${r.enabled ? '' : 'disabled'}"><span class="initial">${esc((r.name || '?').slice(0, 1))}</span><div><b>${esc(r.name)}</b><small>${esc(r.id)} · ${esc(r.currency)}${r.country ? ' · ' + esc(region(r.country)) : ''}${r.account ? ' · •••• ' + esc(r.account.slice(-4)) : ''} · ${esc(t('recipient.' + (r.kind || 'individual')))}</small></div>
      <button class="link sm" data-action="toggle-recipient" data-id="${esc(r.id)}" ${isOwner() ? '' : 'disabled'}>${r.enabled ? t('wallets.disable') : t('wallets.enable')}</button></li>`).join('')}</ul>` : empty(t('wallets.no_recipients'))}
    <p class="fine">${t('wallets.recipient_note')}</p>`;
}

export function recipientForm({currency = '', country = ''} = {}) {
  if (!isOwner()) { toast(t('err.owner_required'), 'bad'); return; }
  modal(t('wallets.add_recipient'), `<form id="recipient-form" class="form-block">
      <div class="grid-2">${field('r-name', t('wallets.r_name'), `<input id="r-name" name="name" required maxlength="100">`)}
      ${field('r-id', t('wallets.r_id'), `<input id="r-id" name="recipient_id" required pattern="[A-Za-z0-9_\\-]{1,64}" maxlength="64">`, t('wallets.r_id_hint'))}</div>
      <div class="grid-3">${field('r-country', t('wallets.r_country'), `<select id="r-country" name="country"><option value="">—</option>${options(ECON.map(c => [c, region(c)]), country)}</select>`)}
          ${field('r-currency', t('wallets.r_currency'), `<select id="r-currency" name="currency" required>${options([...new Set(Object.values(CUR))].map(c => [c, c]), currency || 'CNY')}</select>`)}
          ${field('r-kind', t('wallets.r_kind'), `<select id="r-kind" name="kind">${options([['individual', t('recipient.individual')], ['business', t('recipient.business')]], 'individual')}</select>`)}</div>
          ${field('r-account', t('wallets.r_account'), `<input id="r-account" name="account" maxlength="34" placeholder="${t('wallets.r_account_ph')}">`, t('wallets.r_account_hint'))}
      <p class="fine">${t('wallets.r_note')}</p>
      <div class="form-error"></div><div class="modal-actions"><button class="button primary">${t('wallets.save_recipient')} ${icons.arrow}</button></div></form>`, 'RECIPIENT / TRUSTED', {mount: root => {
        root.querySelector('#r-country')?.addEventListener('change', e => { const c = CUR[e.target.value]; const sel = root.querySelector('#r-currency'); if (c && sel && [...sel.options].some(o => o.value === c)) sel.value = c; });
      }});
}

/* Payment limits: your own safety caps on each sandbox payment (the assistant can never change them). */
function limits() {
  const l = state.data.settings?.limits || {};
  return `<div class="limits">${Object.entries(l).filter(([c]) => c !== 'ETH').map(([c, x]) => `<form class="limit-row" id="limit-${esc(c)}" data-currency="${esc(c)}" data-form="limit-form">
      <b class="cur">${esc(c)}</b>
      ${field('lp-' + c, t('autonomy.per'), `<input id="lp-${esc(c)}" name="per_payment" inputmode="decimal" value="${esc(plain(x.per_payment, c))}" ${isOwner() ? '' : 'disabled'}>`, t('autonomy.ceiling') + ' ' + esc(money(x.ceiling_per_payment, c)))}
      ${field('ld-' + c, t('autonomy.daily'), `<input id="ld-${esc(c)}" name="daily" inputmode="decimal" value="${esc(plain(x.daily, c))}" ${isOwner() ? '' : 'disabled'}>`, t('autonomy.ceiling') + ' ' + esc(money(x.ceiling_daily, c)))}
      <button class="button sm" ${isOwner() ? '' : 'disabled'}>${t('common.save')}</button><div class="form-error"></div></form>`).join('')}</div><p class="fine">${t('autonomy.limits_note')}</p>`;
}

export const view = {
  id: 'wallets',
  needs: ['balances', 'recipients', 'equivalents', 'settings'],
  render() {
    return `${panel(t('wallets.ledger'), ledger(), {sub: t('kind.simulation')})}
    ${panel(t('wallets.recipients'), recipients(), {actions: `<button class="button" data-action="new-recipient" ${isOwner() ? '' : 'disabled'}>${icons.plus}${t('action.add_recipient')}</button>`})}
    ${panel(t('autonomy.limits'), limits(), {sub: t('wallets.limits_sub')})}`;
  },
  mount(root) {
    root.querySelectorAll('.bar-fill[data-ratio]').forEach(el => el.style.setProperty('--ratio', el.dataset.ratio));
    root.querySelector('#display-currency')?.addEventListener('change', async e => {
      state.display = e.target.value; invalidate(['equivalents']); await need(['equivalents']); rerender();
    });
  },
  actions: {
    'new-recipient'(el) { recipientForm({currency: el.dataset.currency || '', country: el.dataset.country || ''}); },
    'own-account'(el) { ownAccountForm({currency: el.dataset.currency || '', country: el.dataset.country || ''}); },
    async 'own-remove'(el) {
      if (!confirm(t('wallets.own_remove_q'))) return;
      await api(`/recipients/me/${encodeURIComponent(el.dataset.id)}`, 'DELETE');
      invalidate(['recipients']); rerender();
    },
    async 'toggle-recipient'(el) {
      const r = state.data.recipients.find(x => x.id === el.dataset.id);
      await api('/recipients', 'POST', {recipient_id: r.id, name: r.name, address: r.address || '', currency: r.currency || '', country: r.country || '', account: r.account || '', kind: r.kind || 'individual', enabled: !r.enabled});
      invalidate(['recipients']); toast(t(r.enabled ? 'wallets.disabled' : 'wallets.enabled')); rerender();
    },
    fund(el) {
      modal(t('wallets.fund_title', {c: el.dataset.currency}), `<form id="fund-form" data-currency="${esc(el.dataset.currency)}" class="form-block"><p class="intro">${t('wallets.fund_note')}</p>
        ${field('f-amount', t('plans.amount'), `<input id="f-amount" name="amount" inputmode="decimal" required value="500">`)}
        <div class="form-error"></div><div class="modal-actions"><button class="button primary">${t('wallets.fund')}</button></div></form>`, 'SANDBOX / TEST FUNDS');
    },
    async copy(el) { try { await navigator.clipboard.writeText(el.dataset.value); toast(t('common.copied'), 'good'); } catch { toast(el.dataset.value); } },
    'sandbox-add'() {
      const have = new Set((state.data.balances || []).map(b => b.currency));
      const choices = SANDBOX_CURRENCIES.filter(c => !have.has(c));
      modal(t('wallets.add_currency'), `<form id="sandbox-add-form" class="form-block"><p class="intro">${t('wallets.add_currency_note')}</p>
        <div class="grid-2">${field('sa-currency', t('wallets.r_currency'), `<select id="sa-currency" name="currency" required>${options(choices.map(c => [c, `${c} · ${currencyName(c)}`]), choices[0])}</select>`)}
        ${field('sa-amount', t('wallets.add_currency_amount'), `<input id="sa-amount" name="amount" inputmode="decimal" placeholder="0">`)}</div>
        <div class="form-error"></div><div class="modal-actions"><button class="button primary">${icons.plus}${t('wallets.add_currency')}</button></div></form>`, 'SANDBOX / CURRENCY');
    },
    async 'sandbox-remove'(el) {
      await api(`/sandbox/currencies/${encodeURIComponent(el.dataset.currency)}`, 'DELETE');
      invalidate(['balances', 'equivalents']); toast(t('wallets.removed_currency', {c: el.dataset.currency})); rerender();
    },
  },
  submit: {
    async 'limit-form'(f) {
      await api('/settings/limits', 'PUT', {currency: f.dataset.currency, per_payment: value(f, 'per_payment'), daily: value(f, 'daily')});
      invalidate(['settings']); toast(t('autonomy.limits_saved'), 'good'); rerender();
    },
    async 'recipient-form'(f) {
      const id = value(f, 'recipient_id');
      if ((state.data.recipients || []).some(r => r.id === id)) throw new Error(t('wallets.r_exists'));
      await api('/recipients', 'POST', {recipient_id: id, name: value(f, 'name'), address: '', currency: value(f, 'currency'),
        country: value(f, 'country'), account: value(f, 'account').replace(/\s+/g, ''), kind: value(f, 'kind'), enabled: true});
      if (state.view === 'send' && state.send) state.send.recipient = id;  // added from the Send form: pick it right away
      invalidate(['recipients']); closeModal(); toast(t('wallets.saved'), 'good'); rerender();
    },
    async 'sandbox-add-form'(f) {
      await api('/sandbox/currencies', 'POST', {currency: value(f, 'currency'), amount: value(f, 'amount') || null});
      invalidate(['balances', 'equivalents']); closeModal(); toast(t('wallets.added_currency', {c: value(f, 'currency')}), 'good'); rerender();
    },
    async 'own-form'(f) {
      const r = await api('/recipients/me', 'POST', {currency: value(f, 'currency'), bank: value(f, 'bank'), account: value(f, 'account').replace(/\s+/g, ''), country: value(f, 'country')});
      if (state.send && f.dataset.pick === 'recipient') state.send.recipient = r.id;  // added from the Send form: picked at once
      if (state.send && f.dataset.pick === 'from_account') state.send.from = r.id;
      invalidate(['recipients']); closeModal(); toast(t('wallets.saved_mine'), 'good'); rerender();
    },
    async 'fund-form'(f) {
      await api('/sandbox/fund', 'POST', {currency: f.dataset.currency, amount: value(f, 'amount')});
      invalidate(['balances', 'equivalents']); closeModal(); toast(t('wallets.funded'), 'good'); rerender();
    },
  },
};
