import {state, need, api, t, modal, closeModal, toast, formError, isOwner, canPrepare, invalidate, rerender, newId, value} from '../core.js';
import {esc, chip, amt, empty, panel, dl, mono, short, icons, segmented, tag} from '../ui.js';
import {when, day, num, region, relative, has, phrase, eta} from '../i18n.js';
import {hold} from '../motion.js';

const STATUSES = ['all', 'draft', 'approved', 'pending', 'unknown', 'completed', 'failed', 'cancelled', 'superseded'];
export const ACTIVE = ['pending', 'unknown'];

export const envLabel = b => b.rail === 'evm' ? t(b.environment === 'live_chain' ? 'env.live' : 'env.sepolia') : t('env.sandbox');

export function table(list, {limit = 100, compact = false} = {}) {
  if (!list?.length) return empty(t('payments.empty'), `<button class="button" data-action="go" data-view="send">${icons.plus}${t('action.new_transfer')}</button>`);
  return `<div class="table-wrap"><table class="table"><thead><tr><th>${t('payments.col.recipient')}</th><th>${t('payments.col.amount')}</th>${compact ? '' : `<th>${t('payments.col.receive')}</th>`}<th>${t('payments.col.status')}</th><th>${t('payments.col.created')}</th></tr></thead><tbody>${list.slice(0, limit).map(p => {
    const b = p.details;
    return `<tr data-action="detail" data-id="${esc(p.id)}" tabindex="0"><td><div class="who"><span class="initial">${esc((b.recipient.name || '?').slice(0, 1))}</span><div><b>${esc(b.recipient.name)}</b><small>${esc(b.purpose)} · ${p.rail === 'evm' ? 'ETH' : esc(b.route_id || '')}</small></div></div></td><td>${amt(b.value, b.source)}</td>${compact ? '' : `<td>${amt(b.receive, b.target, 'muted')}</td>`}<td>${chip(p.status)}</td><td class="muted nowrap">${when(p.created)}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}

export const view = {
  id: 'payments',
  needs: ['transfers', 'balances'],
  render() {
    const all = state.data.transfers || [];
    const f = state.filters;
    const list = all.filter(p => (f.status === 'all' || p.status === f.status));
    const count = s => all.filter(p => p.status === s).length;
    const stats = [['draft', count('draft') + count('approved')], ['pending', count('pending') + count('unknown')], ['completed', count('completed')], ['failed', count('failed')]];
    return `<div class="stat-strip reveal">${stats.map(([s, n]) => `<button class="stat" data-action="filter" data-name="status" data-value="${s}"><span class="stat-n" data-count="${n}" data-digits="0">${n}</span><span>${chip(s)}</span></button>`).join('')}</div>
      ${panel(`${t('payments.title')} <span class="muted">/ ${list.length}</span>`, `
        <div class="toolbar"><div class="chips-scroll hscroll">${STATUSES.map(s => `<button class="pill ${f.status === s ? 'on' : ''}" data-action="filter" data-name="status" data-value="${s}">${s === 'all' ? t('common.all') : t('status.' + s)}</button>`).join('')}</div></div>
        ${table(list)}`, {actions: `<button class="button" data-action="go" data-view="send">${icons.plus}${t('action.new_transfer')}</button>`})}`;
  },
  actions: {
    filter(el) { state.filters[el.dataset.name] = el.dataset.value; rerender(); },
    detail(el) { return openDetail(el.dataset.id); },
    approve() {},
    async execute(el) {
      const result = await api(`/transfers/${encodeURIComponent(el.dataset.id)}/execute`, 'POST', {});
      invalidate(); renderDetail(result); toast(t('status.' + result.status));
    },
    async reconcile(el) {
      const result = await api(`/transfers/${encodeURIComponent(el.dataset.id)}/reconcile`, 'POST', {});
      invalidate(); renderDetail(result); toast(t('status.' + result.status));
    },
    async 'cancel-payment'(el) {
      const result = await api(`/transfers/${encodeURIComponent(el.dataset.id)}/cancel`, 'POST', {});
      invalidate(); renderDetail(result); toast(t('detail.cancelled'));
    },
    async 'rerun-checks'(el) {
      await api(`/transfers/${encodeURIComponent(el.dataset.id)}/checks`);
      await openDetail(el.dataset.id);
    },
    'show-modify'(el) { document.getElementById('modify-form')?.toggleAttribute('hidden'); },
    async requote(el) {
      const p = await api('/transfers/' + encodeURIComponent(el.dataset.id));
      const b = p.details;
      const result = await api('/transfers', 'POST', {amount: b.mode === 'receive' ? null : b.amount,
        receive_amount: b.mode === 'receive' ? b.target_receive : null, source: b.source, target: b.target,
        recipient_id: b.recipient.id, purpose: b.purpose, arrival_by: b.arrival_by, goal_id: b.goal_id, idempotency_key: newId()});
      invalidate(); renderDetail(result); toast(t('detail.requoted'));
    },
    receipt(el) { return openReceipt(el.dataset.id); },
    trail(el) { return openTrail(el.dataset.id); },
    print() { window.print(); },
  },
  submit: {
    async 'modify-form'(form) {
      const amount = value(form, 'amount'), purpose = value(form, 'purpose');
      const result = await api(`/transfers/${encodeURIComponent(form.dataset.id)}/modify`, 'POST', {
        idempotency_key: newId(), amount: form.dataset.mode === 'receive' ? null : amount || null,
        receive_amount: form.dataset.mode === 'receive' ? amount || null : null, purpose: purpose || null});
      invalidate(); renderDetail(result); toast(t('detail.modified'));
    },
  },
};

export async function openDetail(id) {
  try { renderDetail(await api('/transfers/' + encodeURIComponent(id))); } catch (e) { toast(e.message, 'bad'); }
}

const checkText = c => c.status === 'pass' ? t('check.pass') : c.code && has('err.' + c.code) ? t('err.' + c.code) : c.detail;

export function checkList(checks, id) {
  if (!checks?.length) return '';
  return `<div class="checks"><div class="checks-head"><span class="eyebrow">${t('detail.guardrails')}</span>${id ? `<button class="link" data-action="rerun-checks" data-id="${esc(id)}">${icons.reset}${t('detail.rerun')}</button>` : ''}</div><ul>${checks.map(c => `<li class="check c-${esc(c.status)}"><span class="check-icon"></span><span class="check-name">${esc(t('check.' + c.id))}</span><span class="check-detail">${esc(checkText(c))}</span></li>`).join('')}</ul></div>`;
}

function timeline(p) {
  const b = p.details;
  const steps = [
    ['draft', t('detail.step.quoted'), p.created, true],
    ['approved', p.authorized_by === 'owner_mandate' ? t('detail.step.mandate') : t('detail.step.approved'), p.approved_at || (p.authorized_by === 'owner_mandate' ? p.submitted : null), !!(p.approved_at || p.authorized_by === 'owner_mandate')],
    ['pending', t('detail.step.submitted'), p.submitted, !!p.submitted],
    [p.status === 'failed' ? 'failed' : 'completed', p.status === 'failed' ? t('status.failed') : t('detail.step.outcome'), p.completed_at, ['completed', 'failed'].includes(p.status)],
  ];
  return `<ol class="timeline">${steps.map(([s, label, at, done]) => `<li class="${done ? 'done' : ''} t-${s}"><i></i><b>${esc(label)}</b><small>${at ? when(at) : '—'}</small></li>`).join('')}</ol>${p.status === 'unknown' ? `<p class="note warn">${t('detail.unknown_note')}</p>` : ''}${p.status === 'pending' ? `<p class="note">${t('detail.pending_note')}</p>` : ''}`;
}

export function renderDetail(p) {
  const b = p.details, expired = b.expires * 1000 <= Date.now();
  const editable = ['draft', 'approved'].includes(p.status);
  const owner = isOwner();
  const recipient = b.recipient;
  const fee = b.fee_breakdown ? `${amt(b.fee, b.source)} <small class="muted">(${esc(b.fee_breakdown.fixed)} ${esc(b.source)} + ${num(b.fee_breakdown.percent, 3)}%)</small>` : amt(b.fee, b.source);
  const ref = b.reference ? `${num(b.reference.rate, 6)} · ${esc(b.reference.provider)} · ${day(b.reference.observed)}${b.reference.derived ? ' · ' + t('rates.derived') : ''}` : esc(t('detail.no_reference'));
  const actions = [];
  if (editable && owner) actions.push(`<button type="button" class="button ghost" data-action="cancel-payment" data-id="${esc(p.id)}">${t('action.cancel_payment')}</button>`);
  if (editable && canPrepare() && !expired) actions.push(`<button type="button" class="button ghost" data-action="show-modify">${t('action.modify')}</button>`);
  if (p.status === 'approved' && !expired && canPrepare()) actions.push(`<button type="button" class="button primary magnetic" data-action="execute" data-id="${esc(p.id)}">${t('action.submit')} ${icons.arrow}</button>`);
  if (ACTIVE.includes(p.status) && canPrepare()) actions.push(`<button type="button" class="button primary" data-action="reconcile" data-id="${esc(p.id)}">${icons.reset}${t('action.reconcile')}</button>`);
  if (editable && expired) actions.push(`<button type="button" class="button primary" data-action="requote" data-id="${esc(p.id)}">${t('action.requote')}</button>`);
  if (['completed', 'failed'].includes(p.status)) actions.push(`<button type="button" class="button" data-action="receipt" data-id="${esc(p.id)}">${icons.print}${t('action.receipt')}</button>`);
  if (owner) actions.push(`<button type="button" class="button ghost" data-action="trail" data-id="${esc(p.id)}">${icons.audit}${t('action.trail')}</button>`);
  const authorize = p.status === 'draft' && owner && !expired ? `<div class="authorize">
      <label class="check-label"><input type="checkbox" id="approve-check"> ${t('detail.confirm_text')}</label>
      <button type="button" class="hold-button" id="hold-approve" data-id="${esc(p.id)}" data-digest="${esc(p.approval_digest)}" disabled>
        <svg viewBox="0 0 44 44" aria-hidden="true"><circle cx="22" cy="22" r="19"/><circle class="hold-ring" cx="22" cy="22" r="19"/></svg>
        <span>${t('detail.hold')}</span></button>
      <p class="note">${t('detail.hold_note')}</p></div>` : '';
  const html = `
    <div class="detail-top"><span class="env env-${esc(b.rail || 'sandbox')}"><i></i>${esc(envLabel(b))}</span>${chip(p.status)}</div>
    <div class="detail-amount"><div><span class="eyebrow">${t('detail.you_send')}</span>${amt(b.value, b.source, 'xl')}</div><span class="detail-arrow">${icons.arrow}</span><div><span class="eyebrow">${t('detail.they_receive')}</span>${amt(b.receive, b.target, 'xl')}</div></div>
    <div class="recipient-card"><span class="initial lg">${esc((recipient.name || '?').slice(0, 1))}</span><div><b>${esc(recipient.name)}</b><small>${esc(recipient.id)}${recipient.country ? ' · ' + esc(region(recipient.country)) : ''}${recipient.account ? ' · ' + esc('•••• ' + recipient.account.slice(-4)) : ''}</small>${recipient.address ? `<small class="mono wrap">${esc(recipient.address)}</small>` : ''}</div></div>
    ${dl([
      [t('detail.fee'), fee],
      [t('detail.rate'), `${num(b.rate, 6)} <small class="muted">${esc(b.target)}/${esc(b.source)}</small>`],
      b.rail !== 'evm' ? [t('detail.reference'), `<small>${ref}</small>`] : null,
      b.spread_pct ? [t('detail.spread'), num(b.spread_pct, 3) + '%'] : null,
      [t('detail.max_debit'), amt(b.reserve, b.source)],
      [t('detail.eta'), esc(eta(b))],
      b.arrival_by ? [t('detail.arrival_by'), day(b.arrival_by)] : null,
      [t('detail.purpose'), esc(b.purpose)],
      [t('detail.mode'), t(b.mode === 'receive' ? 'send.mode_receive' : 'send.mode_send')],
      [t('detail.quote'), `${mono(short(b.quote_id))} · ${expired ? `<b class="bad">${t('detail.expired')}</b>` : `<span data-countdown="${b.expires}">${relative(b.expires)}</span>`}`],
      [t('detail.rate_kind'), `<small>${esc(phrase(b.rate_kind))}</small>`],
      [t('detail.unknown_charges'), `<small>${esc(phrase(b.unknown_charges) || '—')}</small>`],
      b.chain_id ? [t('detail.chain'), `${esc(b.chain_id)} · <span class="mono">${esc(b.sender)}</span>`] : null,
      p.reference ? [t('detail.reference_id'), p.explorer ? `<a class="mono" href="${esc(p.explorer)}" target="_blank" rel="noopener">${short(p.reference)}… ${icons.external}</a>` : mono(p.reference)] : null,
      p.actual_cost !== null ? [t('detail.actual_cost'), amt(p.actual_cost, b.source)] : null,
      p.authorized_by ? [t('detail.authorized_by'), esc(t('auth.' + p.authorized_by))] : null,
      p.supersedes ? [t('detail.supersedes'), mono(short(p.supersedes))] : null,
    ])}
    ${timeline(p)}
    ${checkList(p.checks, editable ? p.id : null)}
    <form id="modify-form" class="inline-form" data-id="${esc(p.id)}" data-mode="${esc(b.mode)}" hidden>
      <p class="note">${t('detail.modify_note')}</p>
      <div class="grid-2"><div class="field"><label for="mod-amount">${t(b.mode === 'receive' ? 'send.receive_amount' : 'send.amount')}</label><input id="mod-amount" name="amount" inputmode="decimal" value="${esc(b.mode === 'receive' ? b.target_receive : b.amount)}"></div>
      <div class="field"><label for="mod-purpose">${t('send.purpose')}</label><input id="mod-purpose" name="purpose" value="${esc(b.purpose)}" maxlength="200"></div></div>
      <div class="form-error"></div><button class="button">${t('action.save_change')}</button></form>
    ${authorize}
    <div class="digest"><span>${t('detail.transfer_id')} / ${mono(p.id)}</span><span>${t('detail.digest')} / ${mono(p.approval_digest)}</span></div>
    <div class="form-error"></div>
    <div class="modal-actions">${actions.join('')}</div>`;
  modal(t('detail.title'), html, t('detail.eyebrow'), {mount: root => {
    const check = root.querySelector('#approve-check'), button = root.querySelector('#hold-approve');
    if (check && button) {
      check.addEventListener('change', () => { button.disabled = !check.checked; });
      hold(button, 1200, async () => {
        try {
          const result = await api(`/transfers/${encodeURIComponent(button.dataset.id)}/approve`, 'POST', {approval_digest: button.dataset.digest});
          invalidate(); renderDetail(result); toast(t('detail.approved_toast'), 'good');
        } catch (e) { button.classList.remove('held'); formError(root, e); }
      });
    }
  }});
}

async function openReceipt(id) {
  const p = await api('/transfers/' + encodeURIComponent(id));
  const b = p.details;
  modal(t('receipt.title'), `<div class="receipt" id="receipt">
    <div class="receipt-head"><span class="brand-mark sm"><i></i></span><div><b>DOT</b><small>${esc(envLabel(b))}</small></div>${chip(p.status)}</div>
    <p class="receipt-label">${t(b.rail === 'evm' ? 'receipt.label_chain' : 'receipt.label_sandbox')}</p>
    ${dl([[t('receipt.reference'), mono(p.reference || '—')], [t('detail.transfer_id'), mono(p.id)], [t('detail.quote'), mono(b.quote_id)],
      [t('detail.you_send'), amt(b.value, b.source)], [t('detail.fee'), amt(b.fee, b.source)], [t('detail.they_receive'), amt(b.receive, b.target)],
      [t('detail.rate'), num(b.rate, 6)], [t('detail.actual_cost'), p.actual_cost !== null ? amt(p.actual_cost, b.source) : '—'],
      [t('detail.recipient'), esc(b.recipient.name)], [t('detail.purpose'), esc(b.purpose)],
      [t('receipt.created'), when(p.created, {dateStyle: 'medium', timeStyle: 'medium'})], [t('detail.step.approved'), when(p.approved_at, {dateStyle: 'medium', timeStyle: 'medium'})],
      [t('detail.step.submitted'), when(p.submitted, {dateStyle: 'medium', timeStyle: 'medium'})], [t('receipt.final'), when(p.completed_at, {dateStyle: 'medium', timeStyle: 'medium'})],
      [t('detail.authorized_by'), esc(t('auth.' + (p.authorized_by || 'none')))]])}
    <p class="note">${t('receipt.note')}</p></div>
    <div class="modal-actions"><button class="button" data-action="detail" data-id="${esc(p.id)}">${t('common.back')}</button><button class="button primary" data-action="print">${icons.print}${t('action.print')}</button></div>`, 'RECEIPT');
}

async function openTrail(id) {
  const trail = await api(`/transfers/${encodeURIComponent(id)}/trail`);
  const p = trail.transfer;
  const approval = trail.events.find(e => e.action === 'approve' && e.outcome === 'ok');
  const checks = [...trail.events].reverse().find(e => e.action.startsWith('guardrails.'));
  const detail = e => { try { return JSON.parse(e.detail); } catch { return {}; } };
  modal(t('trail.title'), `
    <div class="trail-summary">
      <div><span class="eyebrow">${t('trail.who')}</span><b>${esc(approval ? approval.actor : t('auth.' + (p.authorized_by || 'none')))}</b><small>${approval ? when(approval.time) : ''}</small></div>
      <div><span class="eyebrow">${t('trail.what')}</span><b>${approval ? esc(detail(approval).approved?.amount + ' ' + detail(approval).approved?.source) : '—'}</b><small class="mono">${approval ? esc(detail(approval).approved_digest?.slice(0, 16)) + '…' : ''}</small></div>
      <div><span class="eyebrow">${t('trail.checks')}</span><b>${checks ? (detail(checks).checks || []).filter(c => c.status === 'pass').length + ' / ' + (detail(checks).checks || []).length : '—'}</b><small>${checks ? esc(checks.action) : ''}</small></div>
      <div><span class="eyebrow">${t('trail.after')}</span><b>${t('status.' + p.status)}</b><small>${p.reference ? short(p.reference) : ''}</small></div>
    </div>
    ${trail.lineage.length > 1 ? `<p class="note">${t('trail.lineage', {n: trail.lineage.length - 1})}</p>` : ''}
    <ol class="event-list">${trail.events.map(e => `<li class="o-${esc(e.outcome)}"><time>${when(e.time, {hour: '2-digit', minute: '2-digit', second: '2-digit'})}</time><span class="dot"></span><div><b>${esc(e.action)}</b> <small>${esc(e.actor)} · ${esc(e.outcome)}</small><details><summary>${t('audit.detail')}</summary><pre>${esc(JSON.stringify(detail(e), null, 2))}</pre></details></div></li>`).join('')}</ol>
    <div class="modal-actions"><button class="button" data-action="detail" data-id="${esc(p.id)}">${t('common.back')}</button></div>`, 'AUDIT / TRAIL', {wide: true});
}
