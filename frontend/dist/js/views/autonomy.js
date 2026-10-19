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

function limits() {
  const l = state.data.settings?.limits || {};
  return `<div class="limits">${Object.entries(l).filter(([c]) => c !== 'ETH').map(([c, x]) => `<form class="limit-row" id="limit-${esc(c)}" data-currency="${esc(c)}" data-form="limit-form">
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
  needs: ['settings', 'proposals', 'decisions'],
  render() {
    const tier = state.data.settings?.agent_tier ?? 3;
    return `<div class="actions-legend reveal"><div><span class="eyebrow">A</span><b>${t('autonomy.kind_rec')}</b><small>${t('autonomy.kind_rec_d')}</small></div><div><span class="eyebrow">B</span><b>${t('autonomy.kind_change')}</b><small>${t('autonomy.kind_change_d')}</small></div><div><span class="eyebrow">C</span><b>${t('autonomy.kind_pay')}</b><small>${t('autonomy.kind_pay_d')}</small></div></div>
      <div class="split">
        ${panel(t('autonomy.tiers'), tierRings(tier), {cls: 'tilt'})}
        ${panel(t('autonomy.proposals'), proposals(), {sub: 'B'})}
      </div>
      <div class="split">
        ${panel(t('autonomy.limits'), limits(), {sub: 'ADMIN'})}
        ${panel(t('autonomy.decisions'), decisions(), {sub: 'A'})}
      </div>`;
  },
  actions: {
    async 'set-tier'(el) { await api('/settings/tier', 'PUT', {tier: Number(el.dataset.value)}); invalidate(['settings']); toast(t('autonomy.tier_set', {n: el.dataset.value}), 'good'); rerender(); },
    async decide(el) {
      await api(`/proposals/${encodeURIComponent(el.dataset.id)}/decide`, 'POST', {accept: el.dataset.accept === '1'});
      invalidate(); toast(t(el.dataset.accept === '1' ? 'autonomy.confirmed' : 'autonomy.rejected')); rerender();
    },
  },
  submit: {
    async 'limit-form'(f) {
      await api('/settings/limits', 'PUT', {currency: f.dataset.currency, per_payment: value(f, 'per_payment'), daily: value(f, 'daily')});
      invalidate(['settings']); toast(t('autonomy.limits_saved'), 'good'); rerender();
    },
  },
};
