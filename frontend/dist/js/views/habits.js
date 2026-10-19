import {state, t, api, toast, isOwner, invalidate, rerender, value, modal} from '../core.js';
import {esc, amt, panel, field, options, icons, empty, chip} from '../ui.js';
import {day, num} from '../i18n.js';
import {gauge, animateGauges} from '../charts.js';

const LESSONS = ['history', 'on_time', 'utilization', 'reports', 'remittance', 'scams'];

/** The payment-habits indicator (on-time share, streak) — shown on the Student money page. */
export function indicatorPanel() {
  const h = state.data.habits;
  if (!h) return '';
  const stat = (v, k, cls = '') => `<div class="hb-stat ${cls}"><b data-count="${v}" data-digits="0">${v}</b><small>${t(k)}</small></div>`;
  return panel(t('habits.indicator'), `<div class="habit-hero">
      <div class="hb-gauge">${gauge(Number(h.on_time_pct ?? 0), {size: 132, label: h.on_time_pct ? num(h.on_time_pct, 0) + '%' : '—', sub: t('habits.on_time')})}</div>
      <div class="hb-stats">${stat(h.streak, 'habits.streak', 'lead')}${stat(h.on_time, 'habits.on_time_n')}${stat(h.late, 'habits.late')}${stat(h.overdue, 'habits.overdue', h.overdue ? 'warn' : '')}</div>
      <div class="hb-note"><span class="label-strong">${t('habits.not_score')}</span>
        <ul class="disclaimers">${['habits.d1', 'habits.d2', 'habits.d3'].map(k => `<li>${t(k)}</li>`).join('')}</ul>
        <button class="link sm" data-action="go" data-view="plans">${t('plans.bills')} ${icons.arrow}</button></div></div>`, {cls: 'habit-panel', sub: t('habits.sub')});
}

/** Bills: add one, the list with mark-paid, and the short lessons — shown on the Goals, budget & bills page. */
export function billsPanels() {
  const list = state.data.obligations || [];
  const owner = isOwner();
  const rows = list.length ? `<ul class="list">${list.map(o => `<li class="row ob-${esc(o.state)}"><span class="state-dot"></span><div><b>${esc(o.title)}</b><small>${esc(t('category.' + o.category))} · ${t('habits.due')} ${day(o.due_date)}${o.recurring === 'monthly' ? ' · ' + t('habits.monthly') : ''}${o.transfer_id ? ' · ' + t('habits.sandbox_evidence') : ''}</small></div>${amt(o.amount, o.currency)}<span class="chip s-${esc(o.state)}"><i></i>${t('ob.' + o.state)}</span>
      ${!o.paid_at && owner ? `<button class="button sm" data-action="mark-paid" data-id="${esc(o.id)}">${t('habits.mark_paid')}</button>` : ''}
      ${owner ? `<button class="x" data-action="ob-delete" data-id="${esc(o.id)}" aria-label="${t('common.archive')}">×</button>` : ''}</li>`).join('')}</ul>` : empty(t('habits.empty'));
  return `<div class="split">
      ${panel(t('habits.obligations'), rows)}
      ${panel(t('habits.add'), `<form id="ob-form" class="form-block">
        ${field('o-title', t('habits.title_field'), `<input id="o-title" name="title" required maxlength="100" placeholder="${t('habits.title_ph')}">`)}
        <div class="grid-3">${field('o-cat', t('plans.category'), `<select id="o-cat" name="category">${options(['rent', 'tuition', 'utility', 'loan', 'family', 'subscription', 'other'].map(c => [c, t('category.' + c)]), 'rent')}</select>`)}
        ${field('o-amount', t('plans.amount'), `<input id="o-amount" name="amount" inputmode="decimal" required>`)}
        ${field('o-cur', t('plans.currency'), `<select id="o-cur" name="currency">${options(['AUD', 'USD', 'CNY', 'VND', 'PHP'].map(c => [c, c]), 'AUD')}</select>`)}</div>
        <div class="grid-2">${field('o-due', t('habits.due'), `<input id="o-due" name="due_date" type="date" required>`)}
        ${field('o-rec', t('habits.recurring'), `<select id="o-rec" name="recurring">${options([['none', t('habits.once')], ['monthly', t('habits.monthly')]], 'none')}</select>`)}</div>
        <div class="form-error"></div><button class="button primary" ${owner ? '' : 'disabled'}>${icons.plus}${t('habits.add_btn')}</button></form>`)}
    </div>
    <section class="lessons">${LESSONS.map((k, i) => `<details class="lesson reveal tilt"><summary><span class="lesson-n">${String(i + 1).padStart(2, '0')}</span><b>${t('lesson.' + k)}</b><i></i></summary><p>${t('lesson.' + k + '_d')}</p></details>`).join('')}</section>`;
}

export const view = {
  id: 'habits',
  needs: ['habits', 'obligations', 'transfers'],
  render() { return indicatorPanel() + billsPanels(); },
  mount(root) { animateGauges(root); },
  actions: {
    'mark-paid'(el) {
      const completed = (state.data.transfers || []).filter(p => p.status === 'completed');
      const today = new Date().toISOString().slice(0, 10);
      modal(t('habits.mark_paid'), `<form id="paid-form" data-id="${esc(el.dataset.id)}" class="form-block">
        ${field('p-date', t('habits.paid_on'), `<input id="p-date" name="paid_date" type="date" value="${today}" max="${today}">`)}
        ${field('p-transfer', t('habits.link_transfer'), `<select id="p-transfer" name="transfer_id"><option value="">${t('common.none')}</option>${options(completed.map(p => [p.id, `${p.details.recipient.name} · ${p.details.amount} ${p.details.source} · ${day(new Date(p.completed_at * 1000).toISOString().slice(0, 10))}`]), '')}</select>`, t('habits.link_note'))}
        <div class="form-error"></div><div class="modal-actions"><button class="button primary">${t('habits.record')}</button></div></form>`, 'HABITS');
    },
    async 'ob-delete'(el) { await api('/obligations/' + encodeURIComponent(el.dataset.id), 'DELETE'); invalidate(['obligations', 'habits']); rerender(); },
  },
  submit: {
    async 'ob-form'(f) {
      await api('/obligations', 'POST', {title: value(f, 'title'), category: value(f, 'category'), amount: value(f, 'amount'), currency: value(f, 'currency'), due_date: value(f, 'due_date'), recurring: value(f, 'recurring')});
      invalidate(['obligations', 'habits', 'reminders']); toast(t('habits.added'), 'good'); rerender();
    },
    async 'paid-form'(f) {
      const transfer = value(f, 'transfer_id');
      await api(`/obligations/${encodeURIComponent(f.dataset.id)}/paid`, 'POST', transfer ? {transfer_id: transfer} : {paid_date: value(f, 'paid_date')});
      invalidate(['obligations', 'habits', 'reminders']);
      document.getElementById('modal').close();
      toast(t('habits.recorded'), 'good'); rerender();
    },
  },
};
