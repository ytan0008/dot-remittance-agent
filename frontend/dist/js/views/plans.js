import {state, t, api, toast, isOwner, invalidate, rerender, value, modal, formError} from '../core.js';
import {esc, amt, panel, field, options, icons, empty, dl, chip, tag} from '../ui.js';
import {money, day, num, decimalsOf, phrase} from '../i18n.js';
import {gauge, animateGauges} from '../charts.js';

const PAIRS = [['AUD', 'CNY'], ['AUD', 'VND'], ['AUD', 'PHP'], ['USD', 'CNY'], ['USD', 'VND'], ['USD', 'PHP'], ['USD', 'MXN']];

function goalCard(g) {
  const done = g.target_amount ? Math.min(100, g.completed / g.target_amount * 100) : 0;
  return `<article class="goal-card tilt reveal"><div class="goal-ring">${gauge(done, {size: 108, label: num(done, 0) + '%', sub: t('plans.completed')})}</div>
    <div class="goal-body"><span class="eyebrow">${esc(t('category.' + g.category))} · ${esc(g.source)} → ${esc(g.target)}</span><h3>${esc(g.title)}</h3>
      ${dl([[t('plans.target'), amt(g.target_amount, g.target)], [t('plans.completed'), amt(g.completed, g.target)], [t('plans.planned'), amt(g.planned, g.target)],
        [t('plans.deadline'), `${day(g.deadline)} <small class="${g.days_left < 0 ? 'bad' : g.days_left <= 7 ? 'warn' : 'muted'}">${g.days_left < 0 ? t('plans.overdue') : t('plans.days_left', {n: g.days_left})}</small>`]])}
      <div class="row-actions"><button class="button sm" data-action="goal-plan" data-id="${esc(g.id)}">${t('plans.plan')} ${icons.arrow}</button>
      <button class="link sm" data-action="goal-send" data-id="${esc(g.id)}">${t('plans.send_now')}</button>
      ${isOwner() ? `<button class="link sm" data-action="goal-status" data-id="${esc(g.id)}" data-status="${g.status === 'active' ? 'done' : 'active'}">${t(g.status === 'active' ? 'plans.mark_done' : 'plans.reopen')}</button><button class="link sm muted" data-action="goal-status" data-id="${esc(g.id)}" data-status="archived">${t('common.archive')}</button>` : ''}</div>
    </div></article>`;
}

export const view = {
  id: 'plans',
  needs: ['goals', 'budget', 'recipients', 'balances', 'routes'],
  render() {
    const goals = state.data.goals || [], budget = state.data.budget || [];
    const owner = isOwner();
    const today = new Date().toISOString().slice(0, 10);
    return `<div class="goal-grid">${goals.length ? goals.map(goalCard).join('') : panel(t('plans.goals'), empty(t('plans.empty')))}</div>
      <div class="split">
        ${panel(t('plans.new_goal'), `<form id="goal-form" class="form-block">
          ${field('g-title', t('plans.title_field'), `<input id="g-title" name="title" required maxlength="100" placeholder="${t('plans.title_ph')}">`)}
          <div class="grid-2">${field('g-pair', t('plans.pair'), `<select id="g-pair" name="pair">${options(PAIRS.map(([a, b]) => [a + '-' + b, a + ' → ' + b]), 'AUD-CNY')}</select>`)}
          ${field('g-cat', t('plans.category'), `<select id="g-cat" name="category">${options(['family', 'tuition', 'rent', 'business', 'other'].map(c => [c, t('category.' + c)]), 'family')}</select>`)}</div>
          <div class="grid-2">${field('g-amount', t('plans.target_receive'), `<input id="g-amount" name="target_amount" inputmode="decimal" required>`)}
          ${field('g-deadline', t('plans.deadline'), `<input id="g-deadline" name="deadline" type="date" required min="${today}">`)}</div>
          <div class="form-error"></div><button class="button primary" ${owner ? '' : 'disabled'}>${icons.plus}${t('plans.create')}</button></form>`)}
        ${panel(t('plans.budget'), `<p class="fine">${t('plans.budget_note')}</p>
          ${budget.length ? `<ul class="list">${budget.map(b => `<li class="row"><span class="kind-dot b-${esc(b.kind)}"></span><div><b>${esc(b.label)}</b><small>${esc(t('budget.' + b.kind))}${b.date ? ' · ' + day(b.date) : ''}${b.kind === 'holding' ? ' · ' + t('plans.unverified') : ''}</small></div>${amt(b.amount, b.currency)}${owner ? `<button class="x" data-action="budget-delete" data-id="${esc(b.id)}" aria-label="${t('common.delete')}">×</button>` : ''}</li>`).join('')}</ul>` : empty(t('plans.budget_empty'))}
          <form id="budget-form" class="inline-form"><div class="grid-3">
            ${field('b-kind', t('plans.kind'), `<select id="b-kind" name="kind">${options(['income', 'expense', 'buffer', 'holding'].map(k => [k, t('budget.' + k)]), 'income')}</select>`)}
            ${field('b-label', t('plans.label'), `<input id="b-label" name="label" required maxlength="100">`)}
            ${field('b-currency', t('plans.currency'), `<select id="b-currency" name="currency">${options(['AUD', 'USD', 'CNY', 'VND', 'PHP'].map(c => [c, c]), 'AUD')}</select>`)}</div>
            <div class="grid-2">${field('b-amount', t('plans.amount'), `<input id="b-amount" name="amount" inputmode="decimal" required>`)}
            ${field('b-date', t('plans.date'), `<input id="b-date" name="date" type="date">`)}</div>
            <div class="form-error"></div><button class="button" ${owner ? '' : 'disabled'}>${icons.plus}${t('plans.add_entry')}</button></form>`)}
      </div>`;
  },
  mount(root) {
    animateGauges(root);
  },
  actions: {
    'goal-plan'(el) { return openPlan(el.dataset.id, 3); },
    'goal-send'(el) {
      const g = (state.data.goals || []).find(x => x.id === el.dataset.id);
      const route = (state.data.routes || []).find(r => r.source === g.source && r.target === g.target);
      Object.assign(state.send, {route: route?.id || state.send.route, mode: 'receive', receive: String(g.remaining / 10 ** decimalsOf(g.target)),
        purpose: g.purpose, goal: g.id, arrival: g.deadline, result: null});
      location.hash = 'send';
    },
    async 'goal-status'(el) { await api('/goals/' + encodeURIComponent(el.dataset.id), 'PATCH', {status: el.dataset.status}); invalidate(['goals', 'reminders']); rerender(); },
    async 'budget-delete'(el) { await api('/budget/' + encodeURIComponent(el.dataset.id), 'DELETE'); invalidate(['budget']); rerender(); },
    'plan-installments'(el) { return openPlan(el.dataset.id, Number(el.dataset.value)); },
  },
  submit: {
    async 'goal-form'(f) {
      const [source, target] = value(f, 'pair').split('-');
      await api('/goals', 'POST', {title: value(f, 'title'), source, target, target_amount: value(f, 'target_amount'), deadline: value(f, 'deadline'), category: value(f, 'category')});
      invalidate(['goals', 'reminders']); toast(t('plans.created'), 'good'); rerender();
    },
    async 'budget-form'(f) {
      await api('/budget', 'POST', {kind: value(f, 'kind'), label: value(f, 'label'), currency: value(f, 'currency'), amount: value(f, 'amount'), date: value(f, 'date') || null});
      invalidate(['budget']); toast(t('plans.entry_added'), 'good'); rerender();
    },
  },
};

async function openPlan(id, n) {
  let p;
  try { p = await api(`/goals/${encodeURIComponent(id)}/plan?installments=${n}`); } catch (e) { toast(e.message, 'bad'); return; }
  const g = p.goal;
  if (!p.available) { modal(esc(g.title), `<p class="note warn">${esc(p.reason)}</p>`, 'PLAN'); return; }
  const fd = p.funds, need = p.one_time.send;
  const cap = Math.max(0, fd.capacity);
  modal(esc(g.title), `
    <p class="intro">${t('plans.plan_intro', {r: esc(money(g.remaining, g.target)) + ' ' + esc(g.target), d: day(g.deadline)})}</p>
    <div class="installments">${[1, 2, 3, 4, 6, 12].map(k => `<button class="pill ${k === n ? 'on' : ''}" data-action="plan-installments" data-id="${esc(id)}" data-value="${k}">${k === 1 ? t('plans.one_time') : t('plans.n_parts', {n: k})}</button>`).join('')}</div>
    <div class="compare-2">
      <div class="plan-col"><span class="eyebrow">${t('plans.one_time')}</span>${amt(p.one_time.send, g.source, 'lg')}<small>${t('detail.fee')} ${esc(money(p.one_time.fee, g.source))} ${esc(g.source)}</small></div>
      <div class="plan-col"><span class="eyebrow">${t('plans.n_parts', {n: p.installments.count})}</span>${amt(p.installments.total_send, g.source, 'lg')}<small>${t('detail.fee')} ${esc(money(p.installments.total_fee, g.source))} ${esc(g.source)} · ${p.extra_fees_for_installments > 0 ? '+' : ''}${esc(money(p.extra_fees_for_installments, g.source))}</small></div>
    </div>
    <ol class="schedule">${p.installments.schedule.map((d, i) => `<li><i></i><b>${day(d)}</b><span>${amt(p.installments.each_send, g.source)} → ${amt(p.installments.each_receive, g.target)}</span></li>`).join('')}</ol>
    <div class="capacity"><div class="cap-bar"><i class="bar-fill" data-ratio="${need ? Math.min(1, cap / need).toFixed(3) : 1}"></i></div>
      ${dl([[t('plans.ledger'), amt(fd.ledger_available, g.source)], [t('budget.income'), amt(fd.planned_income, g.source)], [t('budget.expense'), '−' + amt(fd.planned_expense, g.source)],
        [t('budget.buffer'), '−' + amt(fd.safety_buffer, g.source)], [t('plans.capacity'), amt(fd.capacity, g.source)],
        [t('plans.shortfall'), fd.shortfall ? `<b class="bad">${amt(fd.shortfall, g.source)}</b>` : `<b class="good">${t('plans.covered')}</b>`],
        fd.user_entered_holdings ? [t('budget.holding'), amt(fd.user_entered_holdings, g.source) + ` <small class="muted">${t('plans.unverified')}</small>`] : null])}</div>
    <p class="fine">${tag('scenario')} ${esc(phrase(p.basis))} · ${p.assumptions.map(a => esc(phrase(a))).join(' · ')}</p>`, 'PLAN / GOAL', {wide: true, mount: root => root.querySelectorAll('.bar-fill[data-ratio]').forEach(el => el.style.setProperty('--ratio', el.dataset.ratio))});
}
