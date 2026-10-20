import {state, t, api, toast, isOwner, invalidate, rerender, value, modal} from '../core.js';
import {esc, amt, panel, field, options, icons, empty, tag} from '../ui.js';
import {money, day, lang} from '../i18n.js';
import {gauge, animateGauges} from '../charts.js';


const CURRENCIES = ['AUD', 'USD', 'CNY', 'GBP', 'EUR', 'CAD', 'NZD', 'JPY', 'KRW', 'VND', 'HKD', 'SGD'];
const STAGES = ['researching', 'preparing', 'submitted', 'interview', 'awarded', 'rejected'];
const KINDS = ['scholarship', 'grant', 'bursary', 'prize'];
const DOCS = ['transcript', 'cv', 'statement', 'references', 'enrolment', 'id', 'financial', 'portfolio'];
const ui = {currency: null, afford: null, form: {amount: '', currency: '', date: '', label: '', payer: 'me'}};
// what the "someone else" option is called: the name on an account someone else pays, else "someone else"
const otherName = () => (state.data.accounts || []).find(a => a.paid_by === 'other')?.payer_name || t('acct.other_default');
const today = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };  // local date
const owner = () => isOwner() ? '' : 'disabled';

function currencies() {
  const seen = new Set([...(state.data.terms || []).map(x => x.currency), ...(state.data.balances || []).map(b => b.currency), ...CURRENCIES]);
  seen.delete('ETH');
  return [...seen];
}

/* ---------- can I afford this? ---------- */
function verdictMark(v) {
  const inner = v === 'yes' ? '<circle cx="40" cy="40" r="14" class="fill"/>' : v === 'careful' ? '<path d="M40 26a14 14 0 0 1 0 28z" class="fill"/>' : '<path d="M30 50L50 30"/>';
  return `<svg viewBox="0 0 80 80" class="verdict-mark v-${v}" aria-hidden="true"><circle cx="40" cy="40" r="34" class="ring"/>${inner}</svg>`;
}

function reasonText(r, cur) {
  const m = x => `${money(x, cur)} ${cur}`;
  const p = {amount: r.amount !== undefined ? m(r.amount) : '', date: r.date ? day(r.date) : '', remaining: r.remaining !== undefined ? m(r.remaining) : '',
    budget: r.budget !== undefined ? m(r.budget) : '', label: r.kind === 'tuition' ? t('study.tuition_of', {t: r.label}) : r.label || ''};
  return t('afford.r.' + r.code, {...p, n: esc(otherName())});
}

function affordChart(a) {
  const pts = a.series || [];
  if (pts.length < 2) return '';
  const values = pts.flatMap(p => [p[1], p[2]]).concat([0, a.buffer || 0]);
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1, W = 320, H = 90;
  const x = i => (i / (pts.length - 1) * W).toFixed(1), y = v => (H - (v - lo) / span * H).toFixed(1);
  const line = k => pts.map((p, i) => `${x(i)},${y(p[k])}`).join(' ');
  return `<svg viewBox="0 -4 ${W} ${H + 8}" class="afford-chart" aria-hidden="true" preserveAspectRatio="none">
    <line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" class="zero"/>${a.buffer ? `<line x1="0" x2="${W}" y1="${y(a.buffer)}" y2="${y(a.buffer)}" class="buffer"/>` : ''}
    <polyline points="${line(1)}" class="before"/><polyline points="${line(2)}" class="after"/></svg>
    <div class="legend-row"><span class="lg-dash"></span>${t('afford.before')}<span class="lg-line"></span>${t('afford.after')}${a.buffer ? `<span class="lg-buffer"></span>${t('afford.buffer')}` : ''}</div>`;
}

function affordResult() {
  const a = ui.afford;
  if (!a) return `<div class="afford-empty"><span class="empty-orb"><i></i></span><p>${t('afford.empty')}</p></div>`;
  const cur = a.currency;
  return `<div class="afford-result v-${a.verdict}">
    <div class="verdict">${verdictMark(a.verdict)}<div><span class="eyebrow">${esc(a.label || t('afford.this'))} · ${amt(a.amount, cur)}</span>
      <h3>${t('afford.v.' + a.verdict)}</h3>${a.wait_until ? `<p class="wait">${t('afford.wait', {d: day(a.wait_until)})}</p>` : ''}</div></div>
    ${a.payer === 'other' ? `<div class="afford-facts">
      <div><span class="eyebrow">${t('afford.payer')}</span><b>${t('acct.paid_by_x', {n: esc(otherName())})}</b></div>
      <div><span class="eyebrow">${t('afford.month_left')}</span>${a.month_remaining === null ? '<b>—</b>' : amt(a.month_remaining, cur)}</div>
    </div>` : `<div class="afford-facts">
      <div><span class="eyebrow">${t('afford.cash')}</span>${amt(a.cash, cur)}</div>
      <div><span class="eyebrow">${t('afford.lowest')}</span>${amt(a.lowest_after, cur)}<small>${day(a.lowest_date)}</small></div>
      <div><span class="eyebrow">${t('afford.buffer')}</span>${amt(a.buffer, cur)}</div>
      <div><span class="eyebrow">${t('afford.month_left')}</span>${a.month_remaining === null ? '<b>—</b>' : amt(a.month_remaining, cur)}</div>
    </div>`}
    ${affordChart(a)}
    <ul class="reasons">${a.reasons.map(r => `<li class="r-${esc(r.code)}">${esc(reasonText(r, cur))}</li>`).join('')}</ul>
    <p class="fine">${a.payer === 'other' ? t('afford.note_other', {n: esc(otherName())}) : t('afford.note')}${a.notes.includes('holdings_unverified') ? ' ' + t('study.note.holdings_unverified') : ''}</p></div>`;
}

function affordPanel() {
  const f = ui.form, cur = f.currency || state.data.cashflow?.currency || 'AUD';
  return panel(t('afford.title'), `<form id="afford-form" class="afford-form" autocomplete="off">
      <div class="afford-input"><input name="amount" inputmode="decimal" required placeholder="0.00" value="${esc(f.amount)}" aria-label="${t('spend.amount')}">
        <select name="currency" aria-label="${t('plans.currency')}">${options(currencies().map(c => [c, c]), cur)}</select></div>
      <div class="segmented afford-payer" role="radiogroup" aria-label="${t('afford.payer')}">${['me', 'other'].map(p => `<label class="${f.payer === p ? 'on' : ''}"><input type="radio" name="payer" value="${p}" ${f.payer === p ? 'checked' : ''}> ${p === 'me' ? t('afford.payer_me') : t('acct.paid_by_x', {n: esc(otherName())})}</label>`).join('')}</div>
      <input name="label" maxlength="80" placeholder="${t('afford.label_ph')}" value="${esc(f.label)}" aria-label="${t('afford.label')}">
      <input name="date" type="date" min="${today()}" value="${esc(f.date || today())}" aria-label="${t('afford.date')}">
      <button class="button primary">${t('afford.check')} ${icons.arrow}</button>
      <div class="form-error"></div></form>
    <div id="afford-out">${affordResult()}</div>`, {cls: 'afford-panel', sub: t('afford.sub')});
}

/* ---------- term cash flow ---------- */
function cashChart(cf) {
  const rows = cf.months;
  if (!rows.length) return '';
  const vals = rows.flatMap(r => [r.closing, r.low]).concat([0]);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1, H = 150, W = 640, bw = W / rows.length;
  const y = v => H - (v - lo) / span * H;
  return `<svg viewBox="0 -14 ${W} ${H + 34}" class="cash-chart" aria-hidden="true">
    <line x1="0" x2="${W}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" class="zero"/>
    ${rows.map((r, i) => {
      const top = Math.min(y(r.closing), y(0)), h = Math.max(1.5, Math.abs(y(r.closing) - y(0)));
      return `<g class="${r.closing < 0 ? 'neg' : r.low < cf.buffer ? 'low' : ''}"><rect x="${(i * bw + bw * .22).toFixed(1)}" y="${top.toFixed(1)}" width="${(bw * .56).toFixed(1)}" height="${h.toFixed(1)}" rx="3"/>
        <circle cx="${(i * bw + bw / 2).toFixed(1)}" cy="${y(r.low).toFixed(1)}" r="2.6" class="low-dot"/>
        <text x="${(i * bw + bw / 2).toFixed(1)}" y="${H + 16}" text-anchor="middle">${esc(r.month.slice(5))}</text></g>`;
    }).join('')}</svg>`;
}

function cashflowPanel() {
  const cf = state.data.cashflow;
  if (!cf) return panel(t('study.cashflow'), empty(state.errors.cashflow || t('common.loading')));
  const cur = cf.currency;
  const short = cf.first_negative;
  const head = `<div class="cash-summary">
      <div><span class="eyebrow">${t('study.opening')}</span>${amt(cf.opening.total, cur)}</div>
      <div><span class="eyebrow">${t('study.lowest')}</span>${amt(cf.lowest.amount, cur)}<small>${day(cf.lowest.date)}</small></div>
      <div class="${short ? 'bad' : ''}"><span class="eyebrow">${t('study.shortfall')}</span><b>${short ? day(short) : t('study.none')}</b></div>
    </div>`;
  const table = `<div class="table-wrap"><table class="table cash-table"><thead><tr><th>${t('study.month')}</th><th>${t('study.in')}</th><th>${t('study.living')}</th>${cf.others_monthly ? `<th>${t('study.others_pay')}</th>` : ''}<th>${t('study.tuition')}</th><th>${t('study.closing')}</th></tr></thead><tbody>
    ${cf.months.map(r => `<tr class="${r.closing < 0 ? 'neg' : ''}"><td class="nowrap">${esc(r.month)}</td><td>${amt(r.income + r.other_in, cur)}</td><td>${amt(r.living + r.other_out, cur)}</td>${cf.others_monthly ? `<td>${r.others ? '+' + money(r.others, cur) : '—'}</td>` : ''}<td>${r.tuition ? amt(r.tuition, cur) : '—'}</td><td>${amt(r.closing, cur)}</td></tr>`).join('')}
    </tbody></table></div>`;
  const notes = cf.notes.map(n => `<p class="fine">· ${t('study.note.' + n)}</p>`).join('') +
    (cf.other_currency_terms.length ? `<p class="fine">· ${t('study.note.other_currency', {names: cf.other_currency_terms.join(', ')})}</p>` : '');
  return panel(t('study.cashflow'), head + cashChart(cf) + `<div class="legend-row"><span class="lg-bar"></span>${t('study.closing')}<span class="lg-dot"></span>${t('study.month_low')}</div>` + table + notes,
    {cls: 'cash-panel', actions: `<label class="inline-select">${t('plans.currency')} <select id="cf-currency">${options(currencies().map(c => [c, c]), cur)}</select></label>`});
}

function termsPanel() {
  const terms = state.data.terms || [];
  const list = terms.length ? `<ul class="list term-list">${terms.map(x => `<li class="row"><span class="term-ring"></span><div><b>${esc(x.name)}</b>
      <small>${day(x.start)} – ${day(x.end)} · ${t('study.living')} ${esc(money(x.living, x.currency))}/${t('study.mo')} · ${t('study.in')} ${esc(money(x.income, x.currency))}/${t('study.mo')}${x.tuition ? ` · ${t('study.tuition')} ${esc(money(x.tuition, x.currency))} ${t('study.due', {d: day(x.tuition_due)})}` : ''}</small></div>
      <span class="tag">${esc(x.currency)}</span><button class="x" data-action="term-delete" data-id="${esc(x.id)}" aria-label="${t('common.delete')}" ${owner()}>×</button></li>`).join('')}</ul>` : `<p class="fine">${t('study.no_terms')}</p>`;
  const cur = state.data.cashflow?.currency || 'AUD';
  return panel(t('study.terms'), `${list}
    <details class="add-block" ${terms.length ? '' : 'open'}><summary>${icons.plus}${t('study.add_term')}</summary>
    <form id="term-form" class="form-block">
      <div class="grid-2">${field('tm-name', t('study.term_name'), `<input id="tm-name" name="name" required maxlength="80" placeholder="${t('study.term_ph')}">`)}
      ${field('tm-cur', t('plans.currency'), `<select id="tm-cur" name="currency">${options(currencies().map(c => [c, c]), cur)}</select>`)}</div>
      <div class="grid-2">${field('tm-start', t('study.start'), `<input id="tm-start" name="start" type="date" required>`)}${field('tm-end', t('study.end'), `<input id="tm-end" name="end" type="date" required>`)}</div>
      <div class="grid-2">${field('tm-tuition', t('study.tuition'), `<input id="tm-tuition" name="tuition" inputmode="decimal" placeholder="0">`)}${field('tm-due', t('study.tuition_due'), `<input id="tm-due" name="tuition_due" type="date">`)}</div>
      <div class="grid-2">${field('tm-living', t('study.living_mo'), `<input id="tm-living" name="living" inputmode="decimal" placeholder="0">`, t('study.living_hint'))}
      ${field('tm-income', t('study.income_mo'), `<input id="tm-income" name="income" inputmode="decimal" placeholder="0">`, t('study.income_hint'))}</div>
      <div class="form-error"></div><button class="button" ${owner()}>${icons.plus}${t('study.save_term')}</button></form></details>
    <p class="fine">${t('study.terms_note')}</p>`);
}

/* ---------- scholarships and grants ---------- */
function scholarshipCard(s) {
  const pct = s.docs_total ? s.docs_done / s.docs_total * 100 : 0;
  const days = s.days_left;
  const ring = s.deadline ? gauge(days === null || days < 0 ? 0 : Math.max(4, Math.min(100, 100 - days / 60 * 100)),
    {size: 76, stroke: 5, label: days < 0 ? '—' : String(days), sub: t('study.days')}) : '';
  return `<article class="sch-card reveal st-${esc(s.status)} ${s.open && days !== null && days <= 7 && days >= 0 ? 'urgent' : ''}">
    <header><div><span class="eyebrow">${esc(t('sch.kind.' + s.kind))}${s.provider ? ' · ' + esc(s.provider) : ''}</span><h3>${esc(s.name)}</h3>
      <small>${s.amount ? amt(s.amount, s.currency) : ''}${s.deadline ? ` ${t('study.deadline_on', {d: day(s.deadline)})}` : ''}</small></div>${ring}</header>
    <label class="inline-select">${t('study.status')} <select data-sch-status="${esc(s.id)}" ${owner()}>${options(STAGES.map(x => [x, t('sch.stage.' + x)]), s.status)}</select></label>
    ${s.status === 'awarded' ? `<label class="inline-select">${t('study.payout')} <input type="date" data-sch-payout="${esc(s.id)}" value="${esc(s.payout_date || '')}" ${owner()}></label>` : ''}
    ${s.docs_total ? `<div class="docs"><div class="docs-head"><span class="eyebrow">${t('study.documents')}</span><small>${s.docs_done}/${s.docs_total}</small></div>
      <span class="docs-bar"><i class="bar-fill" data-ratio="${(pct / 100).toFixed(3)}"></i></span>
      <ul>${s.documents.map((d, i) => `<li><label class="check-label"><input type="checkbox" data-doc="${esc(s.id)}" data-i="${i}" ${d.done ? 'checked' : ''} ${owner()}> <span>${esc(d.name)}</span></label></li>`).join('')}</ul></div>` : ''}
    ${s.notes ? `<p class="fine">${esc(s.notes)}</p>` : ''}
    <footer>${s.url ? `<a class="link sm" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${t('study.open_link')} ${icons.external || ''}</a>` : '<span></span>'}
      <button class="link sm muted" data-action="sch-delete" data-id="${esc(s.id)}" ${owner()}>${t('common.delete')}</button></footer></article>`;
}

function scholarshipsPanel() {
  const list = state.data.scholarships || [];
  const open = list.filter(s => s.open).length;
  return panel(`${t('study.scholarships')} <span class="muted">/ ${open} ${t('study.open')}</span>`, `
    ${list.length ? `<div class="sch-grid">${list.map(scholarshipCard).join('')}</div>` : empty(t('study.no_scholarships'))}
    <details class="add-block" ${list.length ? '' : 'open'}><summary>${icons.plus}${t('study.add_scholarship')}</summary>
    <form id="sch-form" class="form-block">
      <div class="grid-2">${field('sc-name', t('study.sch_name'), `<input id="sc-name" name="name" required maxlength="120">`)}${field('sc-provider', t('study.provider'), `<input id="sc-provider" name="provider" maxlength="120">`)}</div>
      <div class="grid-3">${field('sc-kind', t('study.kind'), `<select id="sc-kind" name="kind">${options(KINDS.map(k => [k, t('sch.kind.' + k)]), 'scholarship')}</select>`)}
      ${field('sc-amount', t('spend.amount'), `<input id="sc-amount" name="amount" inputmode="decimal" placeholder="0">`)}
      ${field('sc-cur', t('plans.currency'), `<select id="sc-cur" name="currency">${options(currencies().map(c => [c, c]), state.data.cashflow?.currency || 'AUD')}</select>`)}</div>
      <div class="grid-2">${field('sc-deadline', t('study.deadline'), `<input id="sc-deadline" name="deadline" type="date">`)}${field('sc-url', t('study.link'), `<input id="sc-url" name="url" type="url" maxlength="500" placeholder="https://">`)}</div>
      <div class="field"><label>${t('study.documents')}</label><div class="doc-chips">${DOCS.map(d => `<label class="chip-check"><input type="checkbox" name="doc" value="${esc(t('doc.' + d))}"><span>${esc(t('doc.' + d))}</span></label>`).join('')}</div>
        <input name="more_docs" maxlength="300" placeholder="${t('study.more_docs')}"></div>
      ${field('sc-notes', t('study.notes'), `<input id="sc-notes" name="notes" maxlength="600">`)}
      <div class="form-error"></div><button class="button primary" ${owner()}>${icons.plus}${t('study.track')}</button></form></details>`, {cls: 'sch-panel'});
}

/* ---------- extra income, costs and the safety buffer for the term plan (formerly "budget" on the goals page) ---------- */
function budgetPanel() {
  const list = (state.data.budget || []).filter(b => b.kind !== 'holding');  // what you hold is the overview's balances now
  const owner = isOwner() ? '' : 'disabled';
  return panel(t('study.budget'), `<p class="fine">${t('study.budget_d')}</p>
    ${list.length ? `<ul class="list">${list.map(b => `<li class="row"><span class="kind-dot b-${esc(b.kind)}"></span><div><b>${esc(b.label)}</b><small>${esc(t('budget.' + b.kind))}${b.date ? ' · ' + day(b.date) : ''}</small></div>${amt(b.amount, b.currency)}${isOwner() ? `<button class="x" data-action="budget-delete" data-id="${esc(b.id)}" aria-label="${t('common.delete')}">×</button>` : ''}</li>`).join('')}</ul>` : `<p class="fine">${t('plans.budget_empty')}</p>`}
    <form id="budget-form" class="inline-form"><div class="grid-3">
      ${field('b-kind', t('plans.kind'), `<select id="b-kind" name="kind" ${owner}>${options(['income', 'expense', 'buffer'].map(k => [k, t('budget.' + k)]), 'buffer')}</select>`)}
      ${field('b-label', t('plans.label'), `<input id="b-label" name="label" required maxlength="100" ${owner}>`)}
      ${field('b-currency', t('plans.currency'), `<select id="b-currency" name="currency" ${owner}>${options(['AUD', 'USD', 'CNY', 'EUR', 'GBP', 'VND', 'PHP'].map(c => [c, c]), 'AUD')}</select>`)}</div>
      <div class="grid-2">${field('b-amount', t('plans.amount'), `<input id="b-amount" name="amount" inputmode="decimal" required ${owner}>`)}
      ${field('b-date', t('plans.date'), `<input id="b-date" name="date" type="date" ${owner}>`)}</div>
      <div class="form-error"></div><button class="button" ${owner}>${icons.plus}${t('plans.add_entry')}</button></form>`, {cls: 'budget-panel'});
}

/* ---------- email reports (shown in Settings) ---------- */
/** Redraw the email section in place (it lives in the Settings dialog) — visible at once, not waiting for an entrance. */
async function repaintEmail() {
  try { state.data.email = await api('/email'); } catch { return; }
  const box = document.querySelector('.email-sec');
  if (!box) return;
  box.innerHTML = emailPanel();
  box.querySelectorAll('.reveal').forEach(el => el.classList.add('in'));
}
export function emailPanel() {
  if (!isOwner()) return '';
  const e = state.data.email;
  if (!e) return panel(t('email.title'), empty(state.errors.email || t('common.loading')));
  return panel(t('email.title'), `
    <p class="note ${e.configured ? '' : 'warn'}">${e.configured ? t('email.ready') + (e.provider ? ` · ${e.provider === 'resend' ? 'Resend' : 'SMTP'}` : '') : t('email.unconfigured')}</p>
    <form id="email-form" class="form-block">
      ${field('em-address', t('email.address'), `<input id="em-address" name="address" type="email" maxlength="254" value="${esc(e.address)}" placeholder="you@university.edu">`)}
      <div class="grid-2">${field('em-digest', t('email.digest'), `<select id="em-digest" name="digest">${options(['off', 'daily', 'weekly', 'monthly'].map(x => [x, t('email.d.' + x)]), e.digest)}</select>`)}
        ${field('em-weekday', t('email.weekday'), `<select id="em-weekday" name="weekday" ${e.digest === 'weekly' ? '' : 'disabled'}>${options([0, 1, 2, 3, 4, 5, 6].map(n => [n, t('email.wd.' + n)]), e.weekday ?? 0)}</select>`)}</div>
      <label class="check-label em-rem"><input type="checkbox" name="reminders" ${e.reminders ? 'checked' : ''}> ${t('email.reminders')}</label>
      <small class="fine">${t('email.reminders_d')}</small>
      <label class="check-label"><input type="checkbox" name="skip_quiet" ${e.skip_quiet !== false ? 'checked' : ''}> ${t('email.skip_quiet')}</label>
      <div class="form-error"></div>
      <div class="row-actions"><button class="button">${t('common.save')}</button>
        <button type="button" class="button ghost" data-action="email-preview" data-period="day">${t('email.preview_day')}</button>
        <button type="button" class="button ghost" data-action="email-preview" data-period="week">${t('email.preview_week')}</button>
        <button type="button" class="button ghost" data-action="email-preview" data-period="month">${t('email.preview_month')}</button>
        <button type="button" class="button primary" data-action="email-send" ${e.configured && e.address ? '' : 'disabled'}>${t('email.send_now')}</button></div>
    </form>
    ${e.log.length ? `<ul class="list email-log">${e.log.map(l => `<li class="row"><span class="state-dot ${l.status === 'sent' ? '' : 'off'}"></span><div><b>${esc(l.subject)}</b><small>${esc(t('email.k.' + l.kind))} · ${esc(l.recipient)} · ${esc(l.status === 'sent' ? t('email.sent') : t('email.failed') + (l.error ? ' (' + l.error + ')' : ''))}</small></div></li>`).join('')}</ul>` : ''}
    <p class="fine">${t('email.note')}</p>`, {cls: 'email-panel'});
}

export const view = {
  id: 'study',
  needs: ['balances', 'budget'],
  async load() {
    const cur = ui.currency ? '?currency=' + encodeURIComponent(ui.currency) : '';
    const jobs = {scholarships: api('/scholarships'), terms: api('/terms'), cashflow: api('/cashflow' + cur), accounts: api('/accounts')};
    if (isOwner()) jobs.email = api('/email');
    const keys = Object.keys(jobs), results = await Promise.allSettled(Object.values(jobs));
    keys.forEach((k, i) => { if (results[i].status === 'fulfilled') { state.data[k] = results[i].value; delete state.errors[k]; } else state.errors[k] = results[i].reason?.message; });
  },
  render() {
    return `${affordPanel()}
      <div class="split wide-left">${cashflowPanel()}${termsPanel()}</div>
      <div class="split">${budgetPanel()}${scholarshipsPanel()}</div>`;
  },
  mount(root) {
    animateGauges(root);
    root.querySelector('#em-digest')?.addEventListener('change', e => { const wd = root.querySelector('#em-weekday'); if (wd) wd.disabled = e.target.value !== 'weekly'; });
    root.querySelectorAll('.bar-fill[data-ratio]').forEach(el => el.style.setProperty('--ratio', el.dataset.ratio));
    root.querySelector('#afford-form')?.addEventListener('input', e => { if (e.target.name) ui.form[e.target.name] = e.target.value; });
    root.querySelector('#afford-form')?.addEventListener('change', e => {  // the chosen payer lights up
      if (e.target.name === 'payer') e.currentTarget.querySelectorAll('.afford-payer label').forEach(l => l.classList.toggle('on', l.querySelector('input').checked));
    });
    root.querySelector('#cf-currency')?.addEventListener('change', async e => { ui.currency = e.target.value; await view.load(); rerender(); });
    root.querySelector('.sch-panel')?.addEventListener('change', async e => {
      const el = e.target;
      try {
        if (el.dataset.schStatus) await api('/scholarships/' + encodeURIComponent(el.dataset.schStatus), 'PATCH', {status: el.value});
        else if (el.dataset.schPayout) await api('/scholarships/' + encodeURIComponent(el.dataset.schPayout), 'PATCH', {payout_date: el.value || null});
        else if (el.dataset.doc) {
          const s = state.data.scholarships.find(x => x.id === el.dataset.doc);
          const documents = s.documents.map((d, i) => i === Number(el.dataset.i) ? {...d, done: el.checked} : d);
          await api('/scholarships/' + encodeURIComponent(s.id), 'PATCH', {documents});
        } else return;
        await reload();
      } catch (err) { toast(err.message, 'bad'); }
    });
  },
  actions: {
    async 'budget-delete'(el) { await api('/budget/' + encodeURIComponent(el.dataset.id), 'DELETE'); invalidate(['budget']); await reload(); },
    async 'term-delete'(el) { await api('/terms/' + encodeURIComponent(el.dataset.id), 'DELETE'); await reload(); },
    async 'sch-delete'(el) { await api('/scholarships/' + encodeURIComponent(el.dataset.id), 'DELETE'); await reload(); },
    async 'email-preview'(el) {
      const r = await api('/email/preview', 'POST', {period: el.dataset.period, language: lang});
      modal(r.subject, `<pre class="email-preview">${esc(r.text)}</pre>`, 'EMAIL / PREVIEW', {wide: true});
    },
    async 'email-send'() {
      let r;
      try { r = await api('/email/send', 'POST', {period: {daily: 'day', monthly: 'month'}[state.data.email?.digest] || 'week'}); }
      catch (error) {  // say why, after the log is redrawn (redrawing first would wipe the message)
        await repaintEmail();
        const box = document.querySelector('.email-sec .form-error');
        if (box) box.textContent = error.message;
        toast(error.message, 'bad');
        return;
      }
      await repaintEmail();
      toast(t('email.sent_to', {to: r.to}), 'good');
    },
  },
  submit: {
    async 'afford-form'(f) {
      const v = Object.fromEntries(new FormData(f));
      ui.afford = await api('/afford', 'POST', {amount: String(v.amount).replace(',', '.'), currency: v.currency, date: v.date || null, label: v.label, payer: v.payer || 'me'});
      const out = document.getElementById('afford-out');
      if (out) { out.innerHTML = affordResult(); out.querySelector('.afford-result')?.classList.add('pop-in'); }
    },
    async 'term-form'(f) {
      const v = Object.fromEntries(new FormData(f));
      await api('/terms', 'POST', {name: v.name, currency: v.currency, start: v.start, end: v.end, tuition: v.tuition || '', tuition_due: v.tuition_due || null,
        living: v.living || '', income: v.income || ''});
      ui.currency = v.currency;
      toast(t('study.term_saved'), 'good'); await reload();
    },
    async 'sch-form'(f) {
      const fd = new FormData(f);
      const docs = [...fd.getAll('doc'), ...String(fd.get('more_docs') || '').split(/[,，、;]/).map(x => x.trim()).filter(Boolean)];
      await api('/scholarships', 'POST', {name: value(f, 'name'), provider: value(f, 'provider'), kind: value(f, 'kind'), amount: value(f, 'amount'),
        currency: value(f, 'currency'), deadline: value(f, 'deadline') || null, url: value(f, 'url'), notes: value(f, 'notes'), documents: docs});
      toast(t('study.sch_saved'), 'good'); await reload();
    },
    async 'budget-form'(f) {
      await api('/budget', 'POST', {kind: value(f, 'kind'), label: value(f, 'label'), currency: value(f, 'currency'), amount: value(f, 'amount'), date: value(f, 'date') || null});
      invalidate(['budget']); toast(t('plans.entry_added'), 'good'); await reload();
    },
    async 'email-form'(f) {
      await api('/email', 'PUT', {address: value(f, 'address'), digest: value(f, 'digest'), reminders: f.reminders.checked, language: lang,
        weekday: Number(value(f, 'weekday') || state.data.email?.weekday || 0), skip_quiet: f.skip_quiet.checked});
      toast(t('email.saved'), 'good');
      await repaintEmail();
    },
  },
};

async function reload() {
  invalidate(['reminders']);
  await view.load();
  if (state.view === 'study') rerender();
}
