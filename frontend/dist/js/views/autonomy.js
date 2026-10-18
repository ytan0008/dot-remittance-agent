import {state, t, api, toast, isOwner, invalidate, rerender, value, closeModal, modal} from '../core.js';
import {esc, amt, panel, field, options, icons, empty, dl, chip, mono, short} from '../ui.js';
import {money, when, relative, plain} from '../i18n.js';

function tierRings(tier) {
  const owner = isOwner();
  return `<div class="tier-rings">
    <svg viewBox="0 0 300 300" class="rings" aria-hidden="true">${[3, 2, 1].map(n => `<circle class="tr ${n <= tier ? 'on' : ''}" cx="150" cy="150" r="${40 + n * 34}"/>`).join('')}<circle class="core" cx="150" cy="150" r="30"/><text x="150" y="156" text-anchor="middle" class="core-text">T${tier}</text></svg>
    <div class="tier-list">${[1, 2, 3].map(n => `<button class="tier-option ${n === tier ? 'on' : ''} ${n <= tier ? 'within' : ''}" data-action="set-tier" data-value="${n}" ${owner ? '' : 'disabled'}>
      <span class="tier-n">T${n}</span><span><b>${t('tier.' + n)}</b><small>${t('tier.' + n + '_d')}</small></span></button>`).join('')}</div></div>
    <p class="fine">${t('autonomy.tier_note')}</p>`;
}

function mandates() {
  const list = state.data.mandates || [];
  const wallet = state.data.wallet;
  const now = Date.now() / 1000;
  const rows = list.length ? `<ul class="list">${list.map(m => {
    const live = !m.revoked && m.expires > now;
    const used = Number(BigInt(m.used || '0') * 1000n / BigInt(m.total_budget || '1')) / 10;
    return `<li class="row mandate ${live ? '' : 'disabled'}"><div class="mandate-ring" aria-hidden="true"><svg viewBox="0 0 36 36"><circle cx="18" cy="18" r="15"/><circle class="used" cx="18" cy="18" r="15" stroke-dasharray="${(used * .9425).toFixed(2)} 94.25"/></svg></div>
      <div><b>${esc(m.recipient.name)} · ${live ? t('autonomy.active') : m.revoked ? t('autonomy.revoked') : t('autonomy.expired')}</b>
      <small>${t('autonomy.per')} ${esc(money(m.per_payment, 'ETH'))} · ${t('autonomy.budget')} ${esc(money(m.used, 'ETH'))} / ${esc(money(m.total_budget, 'ETH'))} ETH · ${live ? relative(m.expires) : when(m.expires)}</small><small class="mono">${esc(m.recipient.address)}</small></div>
      <button class="button sm ghost" data-action="revoke" data-id="${esc(m.id)}" ${live && isOwner() ? '' : 'disabled'}>${t('autonomy.revoke')}</button></li>`;
  }).join('')}</ul>` : empty(t('autonomy.no_mandates'));
  const evmRecipients = (state.data.recipients || []).filter(r => r.enabled && r.rail === 'evm');
  const form = wallet?.available ? `<form id="mandate-form" class="inline-form">
      <p class="note">${t('autonomy.mandate_intro')}</p>
      ${field('m-recipient', t('autonomy.fixed_recipient'), `<select id="m-recipient" name="recipient_id" required><option value="">—</option>${options(evmRecipients.map(r => [r.id, `${r.name} · ${r.address.slice(0, 10)}…`]), '')}</select>`, evmRecipients.length ? '' : t('autonomy.need_evm_recipient'))}
      <div class="grid-3">${field('m-per', t('autonomy.per') + ' (ETH)', `<input id="m-per" name="per_payment" inputmode="decimal" required placeholder="0.002">`)}
      ${field('m-budget', t('autonomy.budget') + ' (ETH)', `<input id="m-budget" name="total_budget" inputmode="decimal" required placeholder="0.005">`)}
      ${field('m-hours', t('autonomy.hours'), `<input id="m-hours" name="hours" type="number" min="1" max="168" value="24" required>`)}</div>
      <label class="check-label"><input type="checkbox" required> ${t('autonomy.grant_confirm')}</label>
      <div class="form-error"></div><button class="button primary" ${isOwner() ? '' : 'disabled'}>${t('autonomy.grant')}</button></form>`
    : `<p class="note">${t('autonomy.mandate_unavailable')}</p>`;
  return rows + form;
}

function limits() {
  const l = state.data.settings?.limits || {};
  return `<div class="limits">${Object.entries(l).map(([c, x]) => `<form class="limit-row" id="limit-${esc(c)}" data-currency="${esc(c)}" data-form="limit-form">
      <b class="cur">${esc(c)}</b>
      ${field('lp-' + c, t('autonomy.per'), `<input id="lp-${esc(c)}" name="per_payment" inputmode="decimal" value="${esc(plain(x.per_payment, c))}" ${isOwner() ? '' : 'disabled'}>`, t('autonomy.ceiling') + ' ' + esc(money(x.ceiling_per_payment, c)))}
      ${field('ld-' + c, t('autonomy.daily'), `<input id="ld-${esc(c)}" name="daily" inputmode="decimal" value="${esc(plain(x.daily, c))}" ${isOwner() ? '' : 'disabled'}>`, t('autonomy.ceiling') + ' ' + esc(money(x.ceiling_daily, c)))}
      <button class="button sm" ${isOwner() ? '' : 'disabled'}>${t('common.save')}</button><div class="form-error"></div></form>`).join('')}</div><p class="fine">${t('autonomy.limits_note')}</p>`;
}

function proposals() {
  const list = state.data.proposals || [];
  const pending = list.filter(p => p.status === 'pending');
  const done = list.filter(p => p.status !== 'pending').slice(0, 6);
  const show = p => `<li class="proposal p-${esc(p.status)}"><div class="proposal-head"><b>${esc(t('proposal.kind.' + p.kind))}</b>${chip(p.status, 'proposal.status')}<small>${esc(p.created_by)} · ${when(p.created)}</small></div>
    ${p.note ? `<p class="fine">“${esc(p.note)}”</p>` : ''}
    <dl class="facts compact">${Object.entries(p.payload).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
    ${p.status === 'pending' && isOwner() ? `<div class="row-actions"><button class="button sm primary" data-action="decide" data-id="${esc(p.id)}" data-accept="1">${t('autonomy.confirm_change')}</button><button class="button sm ghost" data-action="decide" data-id="${esc(p.id)}" data-accept="0">${t('autonomy.reject')}</button></div>` : ''}</li>`;
  return `${pending.length ? `<ul class="proposals">${pending.map(show).join('')}</ul>` : `<p class="fine">${t('autonomy.no_proposals')}</p>`}
    ${done.length ? `<details class="history"><summary>${t('autonomy.decided')} (${done.length})</summary><ul class="proposals">${done.map(show).join('')}</ul></details>` : ''}`;
}

function decisions() {
  const list = state.data.decisions || [];
  return list.length ? `<ul class="list">${list.slice(0, 8).map(d => `<li class="row"><span class="state-dot"></span><div><b>${esc(d.subject)}</b><small>${esc(d.actor)} · ${when(d.created)} · ${t('autonomy.no_money_moved')}</small></div></li>`).join('')}</ul>` : `<p class="fine">${t('autonomy.no_decisions')}</p>`;
}

export const view = {
  id: 'autonomy',
  needs: ['settings', 'mandates', 'wallet', 'recipients', 'proposals', 'decisions'],
  render() {
    const tier = state.data.settings?.agent_tier ?? 3;
    return `<div class="actions-legend reveal"><div><span class="eyebrow">A</span><b>${t('autonomy.kind_rec')}</b><small>${t('autonomy.kind_rec_d')}</small></div><div><span class="eyebrow">B</span><b>${t('autonomy.kind_change')}</b><small>${t('autonomy.kind_change_d')}</small></div><div><span class="eyebrow">C</span><b>${t('autonomy.kind_pay')}</b><small>${t('autonomy.kind_pay_d')}</small></div></div>
      <div class="split">
        ${panel(t('autonomy.tiers'), tierRings(tier), {cls: 'tilt'})}
        ${panel(t('autonomy.proposals'), proposals(), {sub: 'B'})}
      </div>
      ${panel(t('autonomy.mandates'), mandates(), {sub: t('kind.onchain')})}
      <div class="split">
        ${panel(t('autonomy.limits'), limits(), {sub: 'ADMIN'})}
        ${panel(t('autonomy.decisions'), decisions(), {sub: 'A'})}
      </div>`;
  },
  actions: {
    async 'set-tier'(el) { await api('/settings/tier', 'PUT', {tier: Number(el.dataset.value)}); invalidate(['settings']); toast(t('autonomy.tier_set', {n: el.dataset.value}), 'good'); rerender(); },
    async revoke(el) { await api(`/mandates/${encodeURIComponent(el.dataset.id)}/revoke`, 'POST', {}); invalidate(['mandates', 'wallet']); toast(t('autonomy.revoked_toast')); rerender(); },
    async decide(el) {
      await api(`/proposals/${encodeURIComponent(el.dataset.id)}/decide`, 'POST', {accept: el.dataset.accept === '1'});
      invalidate(); toast(t(el.dataset.accept === '1' ? 'autonomy.confirmed' : 'autonomy.rejected')); rerender();
    },
  },
  submit: {
    async 'mandate-form'(f) {
      await api('/mandates', 'POST', {recipient_id: value(f, 'recipient_id'), per_payment: value(f, 'per_payment'), total_budget: value(f, 'total_budget'),
        expires: Math.floor(Date.now() / 1000) + Number(value(f, 'hours')) * 3600});
      invalidate(['mandates', 'wallet']); toast(t('autonomy.granted'), 'good'); rerender();
    },
    async 'limit-form'(f) {
      await api('/settings/limits', 'PUT', {currency: f.dataset.currency, per_payment: value(f, 'per_payment'), daily: value(f, 'daily')});
      invalidate(['settings']); toast(t('autonomy.limits_saved'), 'good'); rerender();
    },
  },
};
