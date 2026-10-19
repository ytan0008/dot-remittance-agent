import {state, t, api, toast, isOwner, invalidate, rerender, modal, closeModal} from '../core.js';
import {esc, amt, panel, icons, options, empty, tag, field} from '../ui.js';
import {money, day, num, approx, decimalsOf} from '../i18n.js';
import {table} from './payments.js';
import {sandboxCard} from './sandbox.js';

/* Overview: how much you have -> how you plan to exchange it -> what that leaves (sandbox) -> where money is short (gaps). */

const CURRENCIES = ['AUD', 'CNY', 'USD', 'EUR', 'GBP', 'JPY', 'KRW', 'HKD', 'SGD', 'CAD', 'NZD', 'VND', 'INR', 'CHF'];
const ui = {editing: false};
// The currency of the estimated total is a per-viewer preference; the page works without storage.
const refCurrency = {get() { try { return localStorage.getItem('dot.refcur') || ''; } catch { return ''; } },
  set(c) { try { localStorage.setItem('dot.refcur', c); } catch { /* not kept */ } }};
const rateCache = {};
const owner = () => isOwner() ? '' : 'disabled';
const plain = (minor, cur) => money(minor, cur).replace(/,/g, '');
const fmt = (minor, cur) => `${money(minor, cur)} ${cur}`;
const share = (part, whole) => whole > 0 ? Math.max(0, part) / whole : 0;
const allCurrencies = m => [...new Set([...CURRENCIES, ...m.position.currencies.map(c => c.currency), ...m.simulation.rows.map(r => r.currency)])];

/* ---------- ① how much money you have, and in which currencies ---------- */
function structure(pos) {
  const rows = pos.currencies.filter(c => c.equivalent != null && c.amount > 0);
  const whole = rows.reduce((sum, c) => sum + c.equivalent, 0);
  let x = 0;
  const segs = rows.map((c, i) => {
    const w = share(c.equivalent, whole) * 100;
    const seg = `<rect class="seg s${i % 6}" x="${x.toFixed(3)}" y="0" width="${Math.max(0, w - .4).toFixed(3)}" height="10" rx="1.2"><title>${esc(c.currency)}</title></rect>`;
    x += w;
    return seg;
  }).join('');
  return {rows, whole, svg: rows.length > 1 ? `<svg class="ov-struct" viewBox="0 0 100 10" preserveAspectRatio="none" role="img" aria-label="${esc(t('ov.structure'))}">${segs}</svg>` : ''};
}

function cashPanel(m) {
  const pos = m.position;
  const st = structure(pos);
  const open = ui.editing || !pos.has_cash;
  const form = open ? `<form id="cash-form" class="cash-form" autocomplete="off">
      <select name="currency" aria-label="${t('plans.currency')}" ${owner()}>${options(CURRENCIES.map(c => [c, c]), pos.currencies[0]?.currency || pos.display)}</select>
      <input name="amount" inputmode="decimal" placeholder="${t('ov.enter_ph')}" aria-label="${t('ov.amount')}" ${owner()}>
      <button class="button primary" ${owner()}>${icons.check}${t('ov.save')}</button>
      <div class="form-error"></div></form>` : '';
  const cards = [...pos.currencies].sort((a, b) => (b.equivalent ?? -1) - (a.equivalent ?? -1)).map(c => {
    const i = st.rows.indexOf(c);
    return `<li class="ov-bal">
      <span class="ov-bal-head"><span class="sw s${i % 6} ${i < 0 ? 'none' : ''}"></span><b class="code">${esc(c.currency)}</b>
        ${i >= 0 && st.rows.length > 1 ? `<span class="pct">${Math.round(share(c.equivalent, st.whole) * 100)}%</span>` : ''}
        ${isOwner() ? `<button class="x" data-action="ov-clear" data-currency="${esc(c.currency)}" aria-label="${t('common.delete')}">×</button>` : ''}</span>
      <span class="ov-bal-amt" data-count="${approx(c.amount, c.currency)}" data-digits="${Math.min(2, decimalsOf(c.currency))}">${esc(money(c.amount, c.currency))}</span>
      <small>${esc(t('ov.source.' + c.source))} · ${day(c.as_of)}</small></li>`;
  }).join('');
  return `<article class="panel ov-cash reveal">
    <header class="ov-cash-head"><span class="eyebrow">${t('ov.cash_now')}</span></header>
    ${pos.has_cash ? `<ul class="ov-bals">${cards}</ul>
      ${st.svg}
      <p class="ov-ref">${esc(t('ov.ref_total', {a: money(pos.total, pos.display), c: '@@CUR@@'})).replace('@@CUR@@',
        `<select id="ov-ref" class="ov-ref-cur" aria-label="${t('ov.ref_cur')}">${options(allCurrencies(m).map(c => [c, c]), pos.display)}</select>`)}${pos.unconverted.length ? ' · ' + esc(t('ov.unconverted', {c: pos.unconverted.join(', ')})) : ''}</p>`
      : `<p class="ov-empty">${t('ov.empty')}</p>`}
    ${form}
    <div class="ov-cash-actions">${pos.has_cash ? `<button class="link" data-action="ov-edit">${icons.plus}${t('ov.edit')}</button>` : ''}
      <button class="link" data-action="go" data-view="spending">${t('ov.import')} ${icons.arrow}</button></div>
  </article>`;
}

/* ---------- ② how I plan to exchange it ---------- */
function planCard(p) {
  const other = p.side === 'receive' ? (p.spend != null ? `≈ ${fmt(p.spend, p.source)}` : t('ov.no_rate')) : (p.receive != null ? `≈ ${fmt(p.receive, p.target)}` : t('ov.no_rate'));
  const due = p.due ? `${day(p.due)} · ${p.days_left < 0 ? t('ov.p.overdue') : t('ov.p.days', {n: p.days_left})}` : t('ov.p.no_date');
  return `<button class="ov-plan ${p.days_left != null && p.days_left <= 7 ? 'soon' : ''} ${p.below_min_rate ? 'low' : ''}" data-action="plan-open" data-id="${esc(p.id)}">
    <span class="ov-plan-pair">${esc(p.source)} <i>→</i> ${esc(p.target)}</span>
    <b>${esc(money(p.total ?? p.amount, p.amount_currency))} <small>${esc(p.amount_currency)}</small></b>
    ${p.sent ? `<span class="ov-plan-prog"><span class="cat-track"><i class="bar-fill" data-ratio="${Math.min(1, (p.progress_pct || 0) / 100).toFixed(3)}"></i></span><small>${t('ov.p.sent', {a: money(p.sent, p.target), p: p.progress_pct})}</small></span>` : ''}
    <small class="ov-plan-other">${esc(other)}${p.rate ? ` · 1 ${esc(p.source)} = ${num(p.rate, 4)} ${esc(p.target)}` : ''}</small>
    <span class="ov-plan-foot"><span>${esc(p.purpose || t('ov.kind.' + p.kind))}${p.recipient_id ? ` · ${esc((state.data.recipients || []).find(r => r.id === p.recipient_id)?.name || p.recipient_id)}` : ''}</span><span>${esc(due)}</span></span>
    ${p.verdict ? tag('ai_' + p.verdict, 'ov-verdict') : ''}${p.below_min_rate ? `<span class="tag k-alert">${t('ov.p.below', {r: p.min_rate})}</span>` : ''}
  </button>`;
}

function plansPanel(m) {
  const sugg = m.suggestions.map((s, i) => `<li><span>${esc(t('ov.kind.' + s.kind))} · ${esc(s.purpose)}</span>
      <b>${esc(fmt(s.amount, s.target))}</b><small>${s.due ? day(s.due) : ''}${s.cost && s.source ? ` · ≈ ${esc(fmt(s.cost, s.source))}` : ''}</small>
      <button class="button sm" data-action="plan-adopt" data-i="${i}" ${owner()}>${t('ov.p.adopt')}</button></li>`).join('');
  const body = `${m.plans.length ? `<div class="ov-plans">${m.plans.map(planCard).join('')}</div>` : `<p class="ov-empty">${t('ov.p.empty')}</p>`}
    ${sugg ? `<div class="ov-sugg"><span class="eyebrow">${t('ov.p.suggested')}</span><ul>${sugg}</ul></div>` : ''}
    <p class="fine">${t('ov.p.note')}</p>`;
  return panel(`${t('ov.p.title')} <span class="muted">/ ${m.plans.length}</span>`, body,
    {cls: 'ov-plans-panel', sub: t('ov.p.sub'), actions: `<button class="button sm primary" data-action="plan-new" ${owner()}>${icons.plus}${t('ov.p.new')}</button>`});
}

/* ---------- ④ gaps: per currency, what is still short ---------- */
function gapChart(g) {
  const need = g.need + g.buffer;
  const max = Math.max(1, need, g.have + g.planned_in, g.after);
  const x = v => (share(v, max) * 100).toFixed(2);
  const have = Math.max(0, g.have - g.planned_out);
  const covered = Math.max(0, g.after);
  const hatch = 'gh-' + g.currency;
  return `<svg class="ov-gap-chart" viewBox="0 0 100 18" preserveAspectRatio="none" role="img" aria-label="${esc(t('ov.g.aria', {c: g.currency}))}">
    <defs><pattern id="${hatch}" width="2.2" height="2.2" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect class="hatch-bg" width="2.2" height="2.2"/><rect class="hatch" width="1" height="2.2"/></pattern></defs>
    <rect class="track" x="0" y="4" width="100" height="10" rx="2"/>
    <rect class="bar have" x="0" y="4" width="${x(have)}" height="10" rx="2"/>
    ${covered > have ? `<rect class="bar planned" x="${x(have)}" y="4" width="${(share(covered - have, max) * 100).toFixed(2)}" height="10"/>` : ''}
    ${need > covered ? `<rect class="bar gap" x="${x(covered)}" y="4" width="${(share(need - covered, max) * 100).toFixed(2)}" height="10" fill="url(#${hatch})"/>` : ''}
    ${g.buffer ? `<line class="buffer" x1="${x(g.need)}" x2="${x(g.need)}" y1="1" y2="17" vector-effect="non-scaling-stroke"/>` : ''}
    <line class="need" x1="${x(need)}" x2="${x(need)}" y1="0" y2="18" vector-effect="non-scaling-stroke"/></svg>`;
}

function gapsPanel(m) {
  const known = m.gaps.filter(g => g.known), unknown = m.gaps.filter(g => !g.known);
  const short = known.filter(g => g.gap_after > 0 || g.overdrawn);
  const rows = known.map(g => `<li class="ov-gap ${g.gap_after > 0 ? 'short' : 'ok'}">
      <header><b class="code">${esc(g.currency)}</b>
        <span>${g.overdrawn ? t('ov.g.overdrawn', {a: fmt(-g.after, g.currency)}) : g.gap_after > 0 ? t('ov.g.short', {a: fmt(g.gap_after, g.currency)}) : t('ov.g.covered')}</span>
        ${g.due ? `<small>${t('ov.g.by', {d: day(g.due)})}</small>` : ''}</header>
      ${gapChart(g)}
      <p class="ov-gap-legend"><span class="k have"></span>${t('ov.g.have')} ${esc(money(g.have, g.currency))}
        ${g.planned_in ? `<span class="k planned"></span>${t('ov.g.planned')} +${esc(money(g.planned_in, g.currency))}` : ''}
        <span class="k need"></span>${t('ov.g.need')} ${esc(money(g.need, g.currency))}${g.buffer ? ` + ${t('ov.g.buffer')} ${esc(money(g.buffer, g.currency))}` : ''}</p>
      <small class="ov-gap-what">${t('ov.g.now', {a: money(g.gap_now, g.currency)})} · ${t('ov.g.after', {a: money(g.gap_after, g.currency)})} · ${t('ov.g.stressed', {p: Math.abs(m.stress_pct), a: money(g.gap_stressed, g.currency)})}</small>
      ${g.gap_after > 0 && !g.overdrawn ? `<button class="button sm" data-action="gap-plan" data-currency="${esc(g.currency)}" ${owner()}>${icons.plus}${t('ov.g.fill')}</button>` : ''}
    </li>`).join('');
  const body = `${short.length ? '' : `<p class="ov-good">${icons.check}${t('ov.g.none', {n: m.horizon})}</p>`}
    ${rows ? `<ul class="ov-gaps">${rows}</ul>` : ''}
    ${unknown.length ? `<p class="fine">${t('ov.g.unknown', {c: unknown.map(g => g.currency).join(', ')})} <button class="link sm" data-action="ov-edit">${t('ov.edit')}</button></p>` : ''}
    <div class="ov-mail"><span>${t('ov.g.mail')}</span><button class="link" data-action="go" data-view="study">${t('ov.g.mail_set')} ${icons.arrow}</button></div>`;
  return panel(`${t('ov.g.title')}${short.length ? ` <span class="ov-badge">${short.length}</span>` : ''}`, body, {cls: 'ov-gaps-panel', sub: t('ov.g.sub', {n: m.horizon})});
}

/* ---------- next up and recent payments ---------- */
function nextPanel() {
  const list = (state.data.reminders || []).slice(0, 4);
  return panel(t('ov.next'), list.length ? `<ul class="list">${list.map(r => `<li class="row sev-${esc(r.severity)}"><span class="state-dot"></span>
      <div><b>${esc(t('reminder.' + r.kind, r.data))}</b>${r.data?.why ? `<small>${esc(r.data.why)}</small>` : ''}</div>
      <button class="x" data-action="dismiss" data-id="${r.id}" aria-label="${t('common.dismiss')}">×</button></li>`).join('')}</ul>` : `<p class="fine">${t('reminder.none')}</p>`);
}

function recentPanel() {
  const rows = (state.data.transfers || []).filter(p => p.status !== 'superseded' && !p.test);
  return panel(t('overview.recent'), rows.length ? table(rows, {limit: 3, compact: true}) : `<p class="fine">${t('ov.no_payments')}</p>`,
    {sub: t('ov.recent_sub'), actions: `<button class="link" data-action="go" data-view="payments">${t('common.view_all')} ${icons.arrow}</button>`});
}

/* ---------- the plan editor ---------- */
async function rateOf(source, target) {
  const k = source + '-' + target;
  if (!(k in rateCache)) {
    try { rateCache[k] = Number((await api(`/rates/latest?source=${source}&target=${target}`)).rate) || null; } catch { rateCache[k] = null; }
  }
  return rateCache[k];
}

function editor(p = {}) {
  const m = state.data.money, list = allCurrencies(m);
  const side = p.side || 'receive';
  const source = p.source || m.suggestions[0]?.source || m.position.currencies.find(c => c.currency !== m.position.display)?.currency || 'CNY';
  const target = p.target || m.position.display || 'AUD';
  const amount = p.amount != null ? plain(p.total ?? p.amount, p.amount_currency || (side === 'receive' ? target : source)) : '';
  const recips = (state.data.recipients || []).filter(r => r.enabled !== false);
  modal(p.id ? t('ov.e.edit') : t('ov.e.new'), `<form id="plan-form" class="form-block plan-form" data-id="${esc(p.id || '')}" data-kind="${esc(p.kind || 'custom')}" data-ref="${esc(p.need_ref || '')}">
      <div class="segmented pf-side" role="radiogroup">${['receive', 'spend'].map(s => `<button type="button" role="radio" class="${s === side ? 'on' : ''}" aria-checked="${s === side}" data-action="pf-side" data-v="${s}">${t('ov.e.side_' + s)}</button>`).join('')}</div>
      <input type="hidden" name="side" value="${side}">
      <div class="pf-pair"><label for="pf-source">${t('ov.e.from')}</label><span></span><label for="pf-target">${t('ov.e.to')}</label>
        <select id="pf-source" name="source" ${owner()}>${options(list.map(c => [c, c]), source)}</select>
        <span class="pf-arrow" aria-hidden="true">→</span>
        <select id="pf-target" name="target" ${owner()}>${options(list.map(c => [c, c]), target)}</select></div>
      <div class="field pf-amount"><label for="pf-amount" class="pf-amount-label"></label><input id="pf-amount" name="amount" inputmode="decimal" required value="${esc(amount)}" ${owner()}></div>
      <div class="pf-preview" aria-live="polite"></div>
      <div class="grid-2">${field('pf-due', t('ov.e.due'), `<input id="pf-due" name="due" type="date" value="${esc(p.due || '')}" ${owner()}>`)}
        ${field('pf-purpose', t('ov.e.purpose'), `<input id="pf-purpose" name="purpose" maxlength="120" value="${esc(p.purpose || '')}" placeholder="${t('ov.e.purpose_ph')}" ${owner()}>`)}</div>
      <div class="grid-2">${field('pf-recipient', t('ov.e.recipient'), `<select id="pf-recipient" name="recipient_id" ${owner()}><option value="">—</option>${options(recips.map(r => [r.id, `${r.name} · ${r.currency}`]), p.recipient_id || '')}</select>`)}
        ${field('pf-cat', t('ov.e.category'), `<select id="pf-cat" name="category" ${owner()}><option value="">—</option>${options(['family', 'tuition', 'rent', 'living', 'business', 'other'].map(c => [c, t('category.' + c)]), p.category || '')}</select>`)}</div>
      ${field('pf-min', t('ov.e.min_rate'), `<input id="pf-min" name="min_rate" inputmode="decimal" value="${esc(p.min_rate || '')}" ${owner()}>`, t('ov.e.min_rate_hint'))}
      <div class="form-error"></div>
      <div class="modal-actions">
        ${p.id && isOwner() ? `<button type="button" class="button ghost" data-action="plan-done" data-id="${esc(p.id)}">${icons.check}${t('ov.e.done')}</button>
          <button type="button" class="link" data-action="plan-delete" data-id="${esc(p.id)}">${t('common.delete')}</button>` : ''}
        <button type="button" class="button ghost" data-action="plan-send">${t('ov.go')} ${icons.arrow}</button>
        <button class="button primary" ${owner()}>${icons.check}${t('ov.e.save')}</button></div>
    </form>`, 'PLAN / EXCHANGE', {mount: root => {
    const form = root.querySelector('#plan-form');
    const refresh = () => preview(form, p);
    form.addEventListener('input', refresh);
    form.addEventListener('change', refresh);
    refresh();
  }});
}

let previewSeq = 0;
async function preview(form, original) {
  const seq = ++previewSeq;
  const v = Object.fromEntries(new FormData(form));
  const box = form.querySelector('.pf-preview'), label = form.querySelector('.pf-amount-label');
  const side = v.side, cur = side === 'receive' ? v.target : v.source;
  label.textContent = t('ov.e.amount_' + side, {c: cur});
  if (v.source === v.target) { box.innerHTML = `<p class="note warn">${t('ov.e.same')}</p>`; return; }
  const rate = await rateOf(v.source, v.target);
  if (seq !== previewSeq) return;
  const value = Number(String(v.amount || '').replace(/,/g, ''));
  if (!rate || !(value > 0)) { box.innerHTML = rate ? `<p class="fine">${t('ov.e.rate', {s: v.source, r: num(rate, 4), t: v.target})}</p>` : `<p class="note warn">${t('ov.no_rate')}</p>`; return; }
  const dS = decimalsOf(v.source), dT = decimalsOf(v.target);
  const receive = side === 'receive' ? Math.round(value * 10 ** dT) : Math.floor(value * rate * 10 ** dT);
  const spend = side === 'spend' ? Math.round(value * 10 ** dS) : Math.ceil(value / rate * 10 ** dS);
  // What the sandbox says each side holds after all plans, with this plan in place of its old version.
  const rows = Object.fromEntries(state.data.money.simulation.rows.map(r => [r.currency, r]));
  const old = original.id ? {spend: original.spend || 0, receive: original.receive || 0, source: original.source, target: original.target} : null;
  const after = (c, delta) => {
    let x = (rows[c]?.after || 0) + delta;
    if (old && old.source === c) x += old.spend;
    if (old && old.target === c) x -= old.receive;
    return x;
  };
  const srcAfter = after(v.source, -spend), tgtAfter = after(v.target, receive);
  const need = (rows[v.target]?.need || 0) + (rows[v.target]?.buffer || 0);
  const covers = need ? Math.min(100, Math.round(tgtAfter / need * 100)) : null;
  box.innerHTML = `<div class="pf-flow"><span><small>${t('ov.e.pay')}</small><b>${esc(fmt(spend, v.source))}</b></span><i>→</i>
      <span><small>${t('ov.e.get')}</small><b>${esc(fmt(receive, v.target))}</b></span></div>
    <p class="fine">${t('ov.e.rate', {s: v.source, r: num(rate, 4), t: v.target})}</p>
    <ul class="pf-after"><li class="${srcAfter < 0 ? 'neg' : ''}">${t('ov.e.left', {c: v.source})} <b>${esc(fmt(srcAfter, v.source))}</b></li>
      <li>${t('ov.e.left', {c: v.target})} <b>${esc(fmt(tgtAfter, v.target))}</b>${covers != null ? ` · ${t('ov.e.covers', {p: Math.max(0, covers)})}` : ''}</li></ul>
    ${srcAfter < 0 ? `<p class="note warn">${t('ov.e.overdraw', {c: v.source})}</p>` : ''}`;
}

export const view = {
  id: 'overview',
  needs: ['reminders', 'transfers', 'routes', 'recipients'],
  async load() {
    const cur = refCurrency.get();
    try { state.data.money = await api('/overview/money' + (cur ? '?display=' + encodeURIComponent(cur) : '')); delete state.errors.money; }
    catch (e) { state.errors.money = e.message; }
  },
  mount(root) {
    root.querySelectorAll('.bar-fill[data-ratio]').forEach(el => el.style.setProperty('--ratio', el.dataset.ratio));
    root.querySelector('#ov-ref')?.addEventListener('change', async e => { refCurrency.set(e.target.value); await view.load(); rerender(); });
  },
  render() {
    const m = state.data.money;
    if (!m) return panel(t('ov.cash_now'), empty(state.errors.money || t('common.loading')));
    return `${cashPanel(m)}${plansPanel(m)}<div class="ov-pair-panels">${gapsPanel(m)}${sandboxCard(m)}</div><div class="split">${nextPanel()}${recentPanel()}</div>`;
  },
  actions: {
    'ov-edit'() { ui.editing = !ui.editing; rerender(); },
    async 'ov-clear'(el) { await api('/cash/' + encodeURIComponent(el.dataset.currency), 'DELETE'); await reload(); },
    'plan-new'() { editor(); },
    'plan-open'(el) { editor(state.data.money.plans.find(p => p.id === el.dataset.id)); },
    'plan-adopt'(el) {
      const s = state.data.money.suggestions[Number(el.dataset.i)];
      if (s) editor({source: s.source, target: s.target, side: 'receive', amount: s.amount, amount_currency: s.target, due: s.due, purpose: s.purpose, kind: s.kind, need_ref: s.need_ref});
    },
    'gap-plan'(el) {
      const m = state.data.money, g = m.gaps.find(x => x.currency === el.dataset.currency);
      const s = m.suggestions.find(x => x.target === g.currency);
      editor(s ? {source: s.source, target: s.target, side: 'receive', amount: s.amount, amount_currency: s.target, due: s.due, purpose: s.purpose, kind: s.kind, need_ref: s.need_ref}
        : {target: g.currency, side: 'receive', amount: g.gap_after, amount_currency: g.currency, due: g.due});
    },
    'pf-side'(el) {
      const form = el.closest('form');
      form.querySelector('[name=side]').value = el.dataset.v;
      form.querySelectorAll('.pf-side button').forEach(b => { b.classList.toggle('on', b === el); b.setAttribute('aria-checked', String(b === el)); });
      form.dispatchEvent(new Event('change'));
    },
    async 'plan-done'(el) { await api(`/exchange-plans/${encodeURIComponent(el.dataset.id)}/status`, 'POST', {status: 'done'}); closeModal(); toast(t('ov.e.marked'), 'good'); await reload(); },
    async 'plan-delete'(el) { await api(`/exchange-plans/${encodeURIComponent(el.dataset.id)}`, 'DELETE'); closeModal(); await reload(); },
    'plan-send'(el) {
      const v = Object.fromEntries(new FormData(el.closest('form')));
      const route = (state.data.routes || []).find(r => r.enabled && r.source === v.source && r.target === v.target);
      if (route) Object.assign(state.send, {route: route.id, mode: v.side === 'receive' ? 'receive' : 'send', [v.side === 'receive' ? 'receive' : 'amount']: String(v.amount || ''), purpose: v.purpose || state.send.purpose, result: null});
      closeModal();
      location.hash = route ? 'send' : 'markets';
    },
  },
  submit: {
    async 'cash-form'(f) {
      const v = Object.fromEntries(new FormData(f));
      await api('/cash', 'PUT', {currency: v.currency, amount: String(v.amount || '').replace(/,/g, '').trim() || '0'});
      ui.editing = false;
      toast(t('ov.saved'), 'good');
      await reload();
    },
    async 'plan-form'(f) {
      const v = Object.fromEntries(new FormData(f));
      const body = {source: v.source, target: v.target, amount: String(v.amount || '').replace(/,/g, '').trim(), side: v.side, due: v.due || null,
        purpose: v.purpose || '', kind: f.dataset.kind || 'custom', need_ref: f.dataset.ref || null, min_rate: String(v.min_rate || '').replace(',', '.') || null,
        recipient_id: v.recipient_id || null, category: v.category || null};
      const id = f.dataset.id;
      await api(id ? `/exchange-plans/${encodeURIComponent(id)}` : '/exchange-plans', id ? 'PUT' : 'POST', body);
      closeModal();
      toast(t('ov.e.saved'), 'good');
      await reload();
    },
  },
};

async function reload() {
  invalidate(['reminders']);
  await view.load();
  if (state.view === 'overview') rerender();
}
