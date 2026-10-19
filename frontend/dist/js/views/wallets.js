import {state, t, api, toast, isOwner, invalidate, rerender, value, modal, closeModal, need} from '../core.js';
import {esc, amt, panel, field, options, icons, empty, dl, mono, tag} from '../ui.js';
import {money, day, num, when, region, currencyName} from '../i18n.js';

const ECON = ['AU', 'BN', 'CA', 'CL', 'CN', 'HK', 'ID', 'JP', 'KR', 'MY', 'MX', 'NZ', 'PG', 'PE', 'PH', 'RU', 'SG', 'TW', 'TH', 'US', 'VN'];
const CUR = {AU: 'AUD', BN: 'BND', CA: 'CAD', CL: 'CLP', CN: 'CNY', HK: 'HKD', ID: 'IDR', JP: 'JPY', KR: 'KRW', MY: 'MYR', MX: 'MXN', NZ: 'NZD', PG: 'PGK', PE: 'PEN', PH: 'PHP', RU: 'RUB', SG: 'SGD', TW: 'TWD', TH: 'THB', US: 'USD', VN: 'VND'};

function ledger() {
  const list = (state.data.balances || []).filter(b => b.rail === 'sandbox');
  const eq = Object.fromEntries((state.data.equivalents || []).map(e => [e.currency, e]));
  return `<div class="ledger">${list.map(b => {
    const ratio = Number(b.total) > 0 ? Number(b.reserved) / Number(b.total) : 0;
    const e = eq[b.currency];
    return `<div class="ledger-row reveal"><div class="cur-badge"><b>${esc(b.currency)}</b><small>${esc(currencyName(b.currency))}</small></div>
      <div class="ledger-main"><div class="ledger-amt">${amt(b.available, b.currency, 'lg')}<small>${t('wallets.available')}</small></div>
        <div class="split-bar"><i class="bar-fill" data-ratio="${(1 - ratio).toFixed(4)}"></i></div>
        <div class="ledger-facts"><span>${t('wallets.total')} ${esc(money(b.total, b.currency))}</span><span>${t('wallets.reserved')} ${esc(money(b.reserved, b.currency))}</span>
        ${e && b.currency !== state.display ? `<span class="equiv">${e.total !== null ? `≈ ${esc(money(e.total, state.display))} ${esc(state.display)} <small>${t('wallets.equiv_label', {p: esc(e.provider || ''), d: day(e.observed)})}</small>` : t('wallets.equiv_unavailable')}</span>` : ''}</div></div>
      ${isOwner() ? `<button class="button sm ghost" data-action="fund" data-currency="${esc(b.currency)}">${icons.plus}${t('wallets.fund')}</button>` : ''}</div>`;
  }).join('')}</div>
  <div class="toolbar"><label class="inline-select">${t('wallets.display')} <select id="display-currency">${options(['AUD', 'USD', 'CNY', 'EUR', 'JPY', 'VND'].map(c => [c, c]), state.display)}</select></label><span class="fine">${t('wallets.ledger_note')}</span></div>`;
}

function recipients() {
  const list = (state.data.recipients || []).filter(r => r.rail !== 'evm');
  return `${list.length ? `<ul class="list">${list.map(r => `<li class="row ${r.enabled ? '' : 'disabled'}"><span class="initial">${esc((r.name || '?').slice(0, 1))}</span><div><b>${esc(r.name)}</b><small>${esc(r.id)} · ${esc(r.currency)}${r.country ? ' · ' + esc(region(r.country)) : ''}${r.account ? ' · •••• ' + esc(r.account.slice(-4)) : ''} · ${esc(t('recipient.' + (r.kind || 'individual')))}</small></div>
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

export const view = {
  id: 'wallets',
  needs: ['balances', 'recipients', 'equivalents'],
  render() {
    return `${panel(t('wallets.ledger'), ledger(), {sub: t('kind.simulation')})}
    ${panel(t('wallets.recipients'), recipients(), {actions: `<button class="button" data-action="new-recipient" ${isOwner() ? '' : 'disabled'}>${icons.plus}${t('action.add_recipient')}</button>`})}`;
  },
  mount(root) {
    root.querySelectorAll('.bar-fill[data-ratio]').forEach(el => el.style.setProperty('--ratio', el.dataset.ratio));
    root.querySelector('#display-currency')?.addEventListener('change', async e => {
      state.display = e.target.value; invalidate(['equivalents']); await need(['equivalents']); rerender();
    });
  },
  actions: {
    'new-recipient'(el) { recipientForm({currency: el.dataset.currency || '', country: el.dataset.country || ''}); },
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
  },
  submit: {
    async 'recipient-form'(f) {
      const id = value(f, 'recipient_id');
      if ((state.data.recipients || []).some(r => r.id === id)) throw new Error(t('wallets.r_exists'));
      await api('/recipients', 'POST', {recipient_id: id, name: value(f, 'name'), address: '', currency: value(f, 'currency'),
        country: value(f, 'country'), account: value(f, 'account').replace(/\s+/g, ''), kind: value(f, 'kind'), enabled: true});
      invalidate(['recipients']); closeModal(); toast(t('wallets.saved'), 'good'); rerender();
    },
    async 'fund-form'(f) {
      await api('/sandbox/fund', 'POST', {currency: f.dataset.currency, amount: value(f, 'amount')});
      invalidate(['balances', 'equivalents']); closeModal(); toast(t('wallets.funded'), 'good'); rerender();
    },
  },
};
