import {state, t, api, toast, isOwner, invalidate, rerender, modal, closeModal, formError, bus, need} from '../core.js';
import {indicatorPanel} from './habits.js';
import {esc, amt, panel, icons, empty, options, segmented} from '../ui.js';
import {money, day, lang, decimalsOf, plain} from '../i18n.js';

const CATEGORIES = ['rent', 'groceries', 'dining', 'transport', 'utilities', 'phone', 'subscriptions', 'tuition', 'shopping',
  'health', 'entertainment', 'travel', 'transfer', 'fees', 'income', 'other'];
const SPEECH = {en: 'en-US', 'zh-CN': 'zh-CN', 'zh-TW': 'zh-TW', vi: 'vi-VN', ja: 'ja-JP', ko: 'ko-KR'};
const ui = {month: new Date().toISOString().slice(0, 7), quick: '', preview: null, repeat: '', selected: new Set(), lastImport: null, period: 'week', tab: 'entries', fixedType: 'auto'};
let parseTimer = 0, recognizer = null, pasteHandler = null, scanned = [];

const catOptions = selected => options(CATEGORIES.map(c => [c, t('cat.' + c)]), selected);
const shiftMonth = (m, n) => { const d = new Date(m + '-01T00:00:00Z'); d.setUTCMonth(d.getUTCMonth() + n); return d.toISOString().slice(0, 7); };
const monthLabel = m => new Intl.DateTimeFormat(lang, {year: 'numeric', month: 'long', timeZone: 'UTC'}).format(new Date(m + '-01T00:00:00Z'));

function summary() {
  const s = state.data.spendSummary;
  const currencies = s ? Object.entries(s.currencies) : [];
  const body = currencies.length ? currencies.map(([cur, d]) => {
    const cats = Object.entries(d.categories).sort((a, b) => b[1] - a[1]);
    const top = cats[0]?.[1] || 1;
    const delta = d.previous ? Math.round((d.total - d.previous) / d.previous * 100) : null;
    return `<div class="spend-cur"><div class="spend-total"><span class="eyebrow">${esc(cur)}</span>${amt(d.total, cur, 'xl')}
        <small>${delta === null ? t('spend.no_prev') : t(delta > 0 ? 'spend.more' : 'spend.less', {p: Math.abs(delta)})}</small></div>
      <ul class="cat-bars">${cats.map(([c, v]) => `<li><span class="cat-name"><i class="cat-dot c-${c}"></i>${esc(t('cat.' + c))}</span><span class="cat-track"><i class="bar-fill" data-ratio="${(v / top).toFixed(3)}"></i></span>${amt(v, cur)}</li>`).join('')}</ul></div>`;
  }).join('') : empty(t('spend.empty_month'));
  return panel(`<span class="month-nav"><button class="icon-button sm" data-action="spend-month" data-n="-1" aria-label="${t('spend.prev')}">‹</button>${esc(monthLabel(ui.month))}<button class="icon-button sm" data-action="spend-month" data-n="1" aria-label="${t('spend.next')}">›</button></span>`,
    body + `<p class="fine">${t('spend.summary_note')}</p>`, {cls: 'spend-summary', sub: 'CONFIRMED'});
}

function quickAdd() {
  const p = ui.preview;
  const mic = 'SpeechRecognition' in window || 'webkitSpeechRecognition' in window;
  return `<div class="quick-add reveal">
    <form id="quick-form" class="quick-bar" autocomplete="off">
      <span class="quick-orb"><i></i></span>
      <input id="quick-input" name="text" maxlength="200" placeholder="${t('spend.quick_ph')}" value="${esc(ui.quick)}" aria-label="${t('spend.quick')}" ${isOwner() ? '' : 'disabled'}>
      ${mic ? `<button type="button" class="mic" data-action="spend-voice" aria-label="${t('spend.voice')}"><i></i></button>` : ''}
      <button type="button" class="button ghost sm quick-ai" data-action="quick-ai" ${ui.quick.trim() && isOwner() ? '' : 'disabled'} title="${t('spend.ai_read_d')}">${icons.agent}${t('spend.ai_read')}</button>
      <button class="button primary sm" ${p && isOwner() ? '' : 'disabled'}>${icons.check}${t('spend.save')}</button>
    </form>
    <div class="quick-preview ${p ? 'on' : ''}" id="quick-preview">${p ? previewCard(p) : `<small class="muted">${t('spend.quick_hint')}</small>`}</div>
    <div class="spend-actions">
      <label class="drop-zone" id="csv-drop"><input type="file" id="csv-file" accept=".csv,text/csv" hidden ${isOwner() ? '' : 'disabled'}>
        <span class="drop-icon">${icons.payments}</span><span><b>${t('spend.import')}</b><small>${t('spend.import_d')}</small></span></label>
      <label class="drop-zone" id="img-drop"><input type="file" id="receipt-file" accept="image/*" multiple hidden ${isOwner() ? '' : 'disabled'}>
        <span class="drop-icon">${icons.print}</span><span><b>${t('spend.scan')}</b><small>${t('spend.scan_d2')}</small></span></label>
    </div></div>`;
}

function previewCard(p) {
  const list = p.items || [p];
  const by = p.by === 'model' ? `<span class="tag">${icons.agent}${t('spend.by_ai')}</span>` : '';
  if (list.length === 1) {
    const x = list[0];
    return `${by}<span class="pv"><small>${t('spend.date')}</small><input type="date" data-pv="date" data-i="0" value="${esc(x.date)}"></span>
    <span class="pv"><small>${t('spend.amount')}</small><b>${esc(money(-x.amount, x.currency))} ${esc(x.currency)}</b></span>
    <span class="pv grow"><small>${t('spend.description')}</small><b>${esc(x.description)}</b></span>
    <span class="pv"><small>${t('spend.category')}</small><select data-pv="category" data-i="0">${catOptions(x.category)}</select></span>
    <span class="pv"><small>${t('spend.repeat')}</small><select id="pv-repeat">${options([['', t('spend.once')], ['monthly', t('habits.monthly')], ['weekly', t('spend.weekly')]], ui.repeat)}</select></span>`;
  }
  return `${by}<span class="pv-multi-head">${t('spend.n_items', {n: list.length})}</span>
    <ul class="pv-multi">${list.map((x, i) => `<li><input type="date" data-pv="date" data-i="${i}" value="${esc(x.date)}" aria-label="${t('spend.date')}">
      <b class="grow">${esc(x.description)}</b><b>${esc(money(-x.amount, x.currency))} ${esc(x.currency)}</b>
      <select data-pv="category" data-i="${i}" aria-label="${t('spend.category')}">${catOptions(x.category)}</select></li>`).join('')}</ul>`;
}

function reviewTable() {
  const rows = [...(state.data.spendPending || []), ...(state.data.spendExpected || [])];
  if (!rows.length) return '';
  const sel = ui.selected;
  return panel(`${t('spend.review')} <span class="muted">/ ${rows.length}</span>`, `
    <p class="fine">${t('spend.review_d')}</p>
    <div class="review-tools"><label class="check-label"><input type="checkbox" id="review-all" ${rows.every(r => sel.has(r.id)) ? 'checked' : ''}> ${t('spend.select_all')}</label>
      <label class="inline-select">${t('spend.set_category')} <select id="bulk-cat"><option value="">—</option>${catOptions('')}</select></label>
      <span class="grow"></span>
      <button class="button ghost sm" data-action="spend-skip" ${sel.size ? '' : 'disabled'}>${t('spend.skip_n', {n: sel.size})}</button>
      <button class="button primary sm" data-action="spend-confirm" ${sel.size ? '' : 'disabled'}>${icons.check}${t('spend.confirm_n', {n: sel.size})}</button></div>
    <div class="table-wrap"><table class="table review"><thead><tr><th></th><th>${t('spend.date')}</th><th>${t('spend.description')}</th><th>${t('spend.amount')}</th><th>${t('spend.category')}</th></tr></thead><tbody>
    ${rows.map(r => `<tr class="${r.duplicate_of ? 'dup' : ''} ${r.status}"><td><input type="checkbox" data-review="${esc(r.id)}" ${sel.has(r.id) ? 'checked' : ''} aria-label="${esc(r.description)}"></td>
      <td class="nowrap">${day(r.date)}</td>
      <td><b>${esc(r.description)}</b><small>${r.status === 'expected' ? `<span class="tag">${t('spend.expected')}</span> ` : ''}${r.duplicate_of ? `<span class="tag k-dup">${t('spend.duplicate')}</span> ` : ''}${esc(t('spend.src.' + r.source))}${r.suggested === 'learned' ? ' · ' + t('spend.learned') : ''}</small></td>
      <td class="nowrap ${r.amount > 0 ? 'income' : ''}">${r.status === 'expected' ? `<input class="amt-edit" data-amount="${esc(r.id)}" inputmode="decimal" value="${esc(plain(-r.amount, r.currency))}"> ${esc(r.currency)}` : amt(Math.abs(r.amount), r.currency)}</td>
      <td><select data-cat="${esc(r.id)}">${catOptions(r.category)}</select></td></tr>`).join('')}
    </tbody></table></div>`, {cls: 'review-panel', sub: 'REVIEW'});
}

function insightsPanel() {
  const r = state.data.spendInsights;
  if (!r) return '';
  const cur = r.currency;
  const change = r.change_pct === null ? t('insight.no_prev') : t(r.change_pct > 0 ? 'insight.up' : 'insight.down', {p: Math.abs(r.change_pct)});
  return panel(t('insight.title'), `<div class="insight-head">
      <div><span class="eyebrow">${t('insight.period_' + r.period)} · ${day(r.start)} – ${day(r.end)}</span>${amt(r.total, cur, 'xl')}<small class="${r.change_pct > 0 ? 'warn' : ''}">${change}</small></div>
      <div><span class="eyebrow">${t('insight.daily')}</span>${amt(r.daily_avg, cur)}</div>
      ${r.budget ? `<div><span class="eyebrow">${t('insight.budget')}</span>${amt(r.budget, cur)}</div>` : ''}
    </div>
    <ul class="tips">${r.tips.map(x => `<li class="tip sev-${esc(x.severity)}"><span class="tip-dot"></span><p>${esc(x.text)}</p></li>`).join('')}</ul>
    ${r.other_currencies.length ? `<p class="fine">${t('insight.other', {c: r.other_currencies.join(', ')})}</p>` : ''}
    <p class="fine">${t('insight.note')}</p>`,
    {cls: 'insight-panel', actions: segmented('period', [['week', t('insight.week')], ['month', t('insight.month')]], ui.period, 'insight-period')});
}

/* ---------- fixed costs: bills you pay, and charges that renew by themselves, in one list and one picture ---------- */
const SUB_CATS = ['subscriptions', 'phone'];
const monthlyOf = (amount, cadence) => cadence === 'weekly' ? Math.round(amount * 52 / 12) : cadence === 'monthly' ? amount : 0;

/** Bills (obligations) and automatic charges (recurring) as one shape. */
function fixedItems() {
  const r = state.data.recurring || {active: []};
  const auto = r.active.map(x => ({id: x.id, type: SUB_CATS.includes(x.category) ? 'sub' : 'auto', name: x.description, amount: x.amount, currency: x.currency,
    cadence: x.cadence, next: x.next_date, category: x.category, monthly: monthlyOf(x.amount, x.cadence)}));
  const bills = (state.data.obligations || []).map(o => ({id: o.id, type: 'bill', name: o.title, amount: o.amount, currency: o.currency,
    cadence: o.recurring === 'monthly' ? 'monthly' : 'once', next: o.due_date, category: o.category, state: o.state, paid: !!o.paid_at,
    monthly: o.recurring === 'monthly' ? o.amount : 0}));
  return [...bills, ...auto].sort((a, b) => String(a.next).localeCompare(String(b.next)));
}

function fixedChart(items) {
  const monthly = items.filter(x => x.monthly > 0);
  const byCur = {};
  for (const x of monthly) (byCur[x.currency] ||= []).push(x);
  const bars = Object.entries(byCur).map(([cur, list]) => {
    list.sort((a, b) => b.monthly - a.monthly);
    const top = Math.max(1, ...list.map(x => x.monthly)), total = list.reduce((sum, x) => sum + x.monthly, 0);
    return `<div class="rec-cur"><div class="rec-total"><span class="eyebrow">${esc(cur)}</span>${amt(total, cur, 'lg')}<small>${t('spend.sub_month')} · ${esc(money(total * 12, cur))} ${t('spend.sub_year')}</small></div>
      <ul class="cat-bars rec-bars">${list.map(x => `<li><span class="cat-name"><i class="cat-dot c-${esc(x.category)}"></i>${esc(x.name)}</span>
        <span class="cat-track"><i class="bar-fill" data-ratio="${(x.monthly / top).toFixed(3)}"></i></span>${amt(x.monthly, cur)}<span class="tag fx-${x.type}">${t('fixed.t.' + x.type)}</span></li>`).join('')}</ul></div>`;
  }).join('');
  const now = Date.now(), span = 30 * 864e5, dots = [];
  for (const x of items) {
    if (x.paid || !x.next) continue;
    let d = Date.parse(x.next);
    const step = x.cadence === 'weekly' ? 7 * 864e5 : x.cadence === 'monthly' ? 30.4 * 864e5 : Infinity;
    while (d <= now + span) { if (d >= now - 864e5) dots.push({x, d}); d += step; }
  }
  const big = Math.max(1, ...dots.map(o => o.x.amount));
  const strip = dots.length ? `<div class="rec-strip"><span class="eyebrow">${t('spend.rec_next30')}</span>
    <div class="rec-line" role="img" aria-label="${t('spend.rec_next30')}">${dots.map(o => `<i class="rec-dot ${o.x.type === 'bill' ? 'bill' : ''}" data-x="${(Math.max(0, (o.d - now) / span) * 100).toFixed(2)}" data-r="${Math.round(8 + 14 * o.x.amount / big)}" title="${esc(o.x.name)} · ${esc(money(o.x.amount, o.x.currency))} ${esc(o.x.currency)} · ${day(new Date(o.d).toISOString().slice(0, 10))}"></i>`).join('')}</div>
    <div class="rec-axis"><span>${t('spend.rec_today')}</span><span>+15</span><span>+30</span></div></div>` : '';
  return panel(t('fixed.chart'), (bars || `<p class="fine">${t('fixed.none_monthly')}</p>`) + strip, {cls: 'rec-panel', sub: t('fixed.chart_sub')});
}

function fixedList(items) {
  const owner = isOwner() ? '' : 'disabled';
  const r = state.data.recurring || {candidates: []};
  const rows = items.length ? `<ul class="list fixed-list">${items.map(x => `<li class="row fx-${x.type} ${x.paid ? 'paid' : ''}">
      <span class="cat-dot c-${esc(x.category)}"></span>
      <div><b>${esc(x.name)}</b><small>${t('fixed.t.' + x.type)} · ${t('fixed.c.' + x.cadence)} · ${x.paid ? t('fixed.paid') : t('spend.next_due', {d: day(x.next)})}</small></div>
      ${amt(x.amount, x.currency)}
      ${x.type === 'bill' && x.state ? `<span class="chip s-${esc(x.state)}"><i></i>${t('ob.' + x.state)}</span>` : '<span></span>'}
      <span class="row-actions">${x.type === 'bill'
        ? `${!x.paid ? `<button class="button sm" data-action="mark-paid" data-id="${esc(x.id)}" ${owner}>${t('habits.mark_paid')}</button>` : ''}<button class="x" data-action="ob-delete" data-id="${esc(x.id)}" aria-label="${t('common.archive')}" ${owner}>×</button>`
        : `<button class="link sm" data-action="spend-stop" data-id="${esc(x.id)}" ${owner}>${t('spend.sub_cancel')}</button>`}</span></li>`).join('')}</ul>` : `<p class="fine">${t('fixed.none')}</p>`;
  const cand = r.candidates.length ? `<div class="cand-list"><span class="eyebrow">${t('fixed.found')}</span>${r.candidates.map((c, i) => `<div class="cand"><span class="pulse"></span><div><b>${esc(c.description)}</b><small>${t('spend.looks', {cadence: t(c.cadence === 'weekly' ? 'spend.weekly' : 'habits.monthly'), n: c.occurrences})}</small></div>${amt(c.amount, c.currency)}<button class="button sm" data-action="spend-make-recurring" data-i="${i}" ${owner}>${t('spend.sub_track')}</button></div>`).join('')}</div>` : '';
  const today = new Date().toISOString().slice(0, 10);
  const form = `<form id="fixed-form" class="fixed-form" autocomplete="off">
      <div class="segmented fx-type" role="radiogroup">${['auto', 'bill'].map(v => `<button type="button" class="${ui.fixedType === v ? 'on' : ''}" data-action="fixed-type" data-v="${v}">${t('fixed.add_' + v)}</button>`).join('')}</div>
      <div class="fixed-fields">
        <input name="name" required maxlength="100" placeholder="${t(ui.fixedType === 'bill' ? 'habits.title_ph' : 'spend.sub_name_ph')}" aria-label="${t('spend.description')}" ${owner}>
        <input name="amount" inputmode="decimal" required placeholder="${t('spend.amount')}" aria-label="${t('spend.amount')}" ${owner}>
        <select name="currency" aria-label="${t('plans.currency')}" ${owner}>${options(['AUD', 'CNY', 'USD', 'EUR', 'GBP', 'JPY', 'KRW', 'VND'].map(c => [c, c]), (state.data.memory || {}).display_currency || 'AUD')}</select>
        <select name="cadence" aria-label="${t('spend.repeat')}" ${owner}>${options(ui.fixedType === 'bill' ? [['monthly', t('habits.monthly')], ['once', t('habits.once')]] : [['monthly', t('habits.monthly')], ['weekly', t('spend.weekly')]], 'monthly')}</select>
        <select name="category" aria-label="${t('spend.category')}" ${owner}>${ui.fixedType === 'bill'
          ? options(['rent', 'tuition', 'utility', 'loan', 'family', 'subscription', 'other'].map(c => [c, t('category.' + c)]), 'rent')
          : catOptions('subscriptions')}</select>
        <label class="fx-date"><small>${t(ui.fixedType === 'bill' ? 'habits.due' : 'spend.sub_last')}</small><input name="date" type="date" value="${today}" required ${owner}></label>
        <button class="button primary sm" ${owner}>${icons.plus}${t('spend.sub_add')}</button></div>
      <div class="form-error"></div></form>`;
  return panel(`${t('fixed.title')} <span class="muted">/ ${items.length}</span>`, `${rows}${cand}${form}<p class="fine">${t('fixed.note')}</p>`, {cls: 'fixed-panel'});
}

export const openFixed = () => { ui.tab = 'fixed'; };

function tabs() {
  return `<div class="page-tabs" role="tablist">${[['entries', t('spend.tab_entries')], ['fixed', t('spend.tab_fixed')]].map(([v, l]) =>
    `<button type="button" role="tab" aria-selected="${ui.tab === v}" class="${ui.tab === v ? 'on' : ''}" data-action="spend-tab" data-v="${v}">${v === 'fixed' ? icons.habits : icons.spending}${esc(l)}</button>`).join('')}</div>`;
}

function recentList() {
  const rows = (state.data.spendMonth || []).filter(r => r.status === 'confirmed');
  return panel(`${t('spend.recent')} <span class="muted">/ ${rows.length}</span>`, rows.length ? `<ul class="list spend-list">${rows.slice(0, 60).map(r => `<li class="row"><span class="cat-dot c-${esc(r.category)}"></span><div><b>${esc(r.description)}</b><small>${day(r.date)} · ${esc(t('spend.src.' + r.source))}</small></div>
      <select class="cat-inline" data-recat="${esc(r.id)}" ${isOwner() ? '' : 'disabled'}>${catOptions(r.category)}</select>
      <span class="${r.amount > 0 ? 'income' : ''}">${r.amount > 0 ? '+' : ''}${amt(Math.abs(r.amount), r.currency)}</span>
      <button class="x" data-action="spend-delete" data-id="${esc(r.id)}" aria-label="${t('common.delete')}" ${isOwner() ? '' : 'disabled'}>×</button></li>`).join('')}</ul>` : empty(t('spend.empty_list')));
}

export const view = {
  id: 'spending',
  needs: [],
  async load() {
    const [summ, month, pending, expected, recurring, insights] = await Promise.all([
      api('/expenses/summary?month=' + ui.month), api('/expenses?status=confirmed&month=' + ui.month),
      api('/expenses?status=pending'), api('/expenses?status=expected'), api('/recurring'),
      api(`/insights?period=${ui.period}&lang=${encodeURIComponent(lang)}`).catch(() => null)]);
    Object.assign(state.data, {spendSummary: summ, spendMonth: month, spendPending: pending, spendExpected: expected, recurring, spendInsights: insights});
    await need(['obligations', 'habits', 'transfers'], true);  // the fixed-costs tab: bills and the payment-habits indicator
    // New rows start selected, except likely duplicates which the student must opt into.
    for (const r of [...pending, ...expected]) if (!ui.known?.has(r.id)) { if (!r.duplicate_of) ui.selected.add(r.id); }
    ui.known = new Set([...pending, ...expected].map(r => r.id));
    for (const id of [...ui.selected]) if (!ui.known.has(id)) ui.selected.delete(id);
  },
  render() {
    if (ui.tab === 'fixed') {
      const items = fixedItems();
      return `${tabs()}${indicatorPanel()}${fixedChart(items)}${fixedList(items)}`;
    }
    return `${tabs()}${quickAdd()}${reviewTable()}${insightsPanel()}<div class="split wide-left">${summary()}${recentList()}</div>`;
  },
  mount(root) {
    root.querySelectorAll('.bar-fill[data-ratio]').forEach(el => el.style.setProperty('--ratio', el.dataset.ratio));
    root.querySelectorAll('.rec-dot[data-x]').forEach(el => { el.style.left = el.dataset.x + '%'; el.style.width = el.style.height = el.dataset.r + 'px'; });
    const input = root.querySelector('#quick-input');
    input?.addEventListener('input', () => { ui.quick = input.value; clearTimeout(parseTimer); parseTimer = setTimeout(parseQuick, 260); });
    root.querySelector('#quick-preview')?.addEventListener('change', e => {
      if (!ui.preview) return;
      const item = (ui.preview.items || [ui.preview])[Number(e.target.dataset.i)];
      if (item && e.target.dataset.pv) item[e.target.dataset.pv] = e.target.value;
      if (e.target.id === 'pv-repeat') ui.repeat = e.target.value;
    });
    root.querySelector('#csv-file')?.addEventListener('change', e => e.target.files[0] && importCsv(e.target.files[0]));
    root.querySelector('#receipt-file')?.addEventListener('change', e => { if (e.target.files.length) scanImages([...e.target.files]); e.target.value = ''; });
    const imgDrop = root.querySelector('#img-drop');
    if (imgDrop) {  // drag images in (several at once), with a soft jelly hover
      ['dragenter', 'dragover'].forEach(ev => imgDrop.addEventListener(ev, e => { e.preventDefault(); imgDrop.classList.add('over'); }));
      ['dragleave', 'drop'].forEach(ev => imgDrop.addEventListener(ev, e => { e.preventDefault(); imgDrop.classList.remove('over'); }));
      imgDrop.addEventListener('drop', e => { const files = [...e.dataTransfer.files].filter(f => f.type.startsWith('image/') || /\.(heic|heif)$/i.test(f.name)); if (files.length) scanImages(files); });
    }
    pasteHandler ??= e => {  // paste a screenshot anywhere on the Spending page
      if (state.view !== 'spending' || document.getElementById('modal').open) return;
      const files = [...(e.clipboardData?.files || [])].filter(f => f.type.startsWith('image/'));
      if (files.length) { e.preventDefault(); scanImages(files); }
    };
    document.removeEventListener('paste', pasteHandler); document.addEventListener('paste', pasteHandler);
    const drop = root.querySelector('#csv-drop');
    if (drop) {
      ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
      ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
      drop.addEventListener('drop', e => { const f = e.dataTransfer.files[0]; if (f) importCsv(f); });
    }
    root.querySelector('.review-panel')?.addEventListener('change', e => {
      const id = e.target.dataset.review;
      if (id) { e.target.checked ? ui.selected.add(id) : ui.selected.delete(id); syncReviewButtons(root); }
      if (e.target.id === 'review-all') {
        root.querySelectorAll('[data-review]').forEach(cb => { cb.checked = e.target.checked; e.target.checked ? ui.selected.add(cb.dataset.review) : ui.selected.delete(cb.dataset.review); });
        syncReviewButtons(root);
      }
      if (e.target.id === 'bulk-cat' && e.target.value) {
        root.querySelectorAll('[data-cat]').forEach(s => { if (ui.selected.has(s.dataset.cat)) { s.value = e.target.value; s.closest('tr').classList.add('flash'); } });
        e.target.value = '';
      }
    });
    root.querySelector('.spend-list')?.addEventListener('change', async e => {
      const id = e.target.dataset.recat;
      if (!id) return;
      try { await api('/expenses/' + encodeURIComponent(id), 'PATCH', {category: e.target.value}); toast(t('spend.learned_toast'), 'good'); await reload(); }
      catch (err) { toast(err.message, 'bad'); }
    });
  },
  actions: {
    async 'insight-period'(el) { ui.period = el.dataset.value; await reload(); },
    async 'spend-month'(el) { ui.month = shiftMonth(ui.month, Number(el.dataset.n)); await reload(); },
    async 'spend-confirm'() { await submitReview(true); },
    async 'spend-skip'() { await submitReview(false); },
    async 'spend-make-recurring'(el) {
      const c = state.data.recurring.candidates[Number(el.dataset.i)];
      await api('/recurring', 'POST', {description: c.description, amount: c.amount, currency: c.currency, category: c.category, cadence: c.cadence, last_date: c.last_date});
      toast(t('spend.recurring_saved'), 'good'); await reload();
    },
    async 'spend-stop'(el) { await api('/recurring/' + encodeURIComponent(el.dataset.id), 'DELETE'); await reload(); },
    async 'spend-delete'(el) { await api('/expenses/' + encodeURIComponent(el.dataset.id), 'DELETE'); await reload(); },
    'spend-voice'(el) { voice(el); },
    'spend-tab'(el) { ui.tab = el.dataset.v === 'fixed' ? 'fixed' : 'entries'; rerender(); scrollTo({top: 0, behavior: 'smooth'}); },
    'fixed-type'(el) { ui.fixedType = el.dataset.v === 'bill' ? 'bill' : 'auto'; rerender(); },
    async 'quick-ai'() { await parseQuick(true); },
  },
  submit: {
    async 'fixed-form'(f) {
      const v = Object.fromEntries(new FormData(f));
      const amount = String(v.amount).replace(',', '.').trim();
      if (!(Number(amount) > 0)) throw new Error(t('err.amount_invalid'));
      if (ui.fixedType === 'bill') {  // a bill you pay yourself; it counts toward the payment-habits indicator
        await api('/obligations', 'POST', {title: v.name.trim(), category: v.category, amount, currency: v.currency, due_date: v.date, recurring: v.cadence === 'monthly' ? 'monthly' : 'none'});
      } else {  // a charge that renews by itself
        await api('/recurring', 'POST', {description: v.name.trim(), amount: Math.round(Number(amount) * 10 ** decimalsOf(v.currency)), currency: v.currency,
          category: v.category, cadence: v.cadence, last_date: v.date});
      }
      invalidate(['obligations', 'habits', 'reminders']);
      toast(t('fixed.added'), 'good'); await reload();
    },
    async 'quick-form'() {
      if (!ui.preview) { if (ui.quick.trim()) await parseQuick(true); return; }  // Enter with nothing read yet: ask the AI
      const list = ui.preview.items || [ui.preview];
      for (const p of list) {
        await api('/expenses', 'POST', {date: p.date, amount: p.amount, currency: p.currency, description: p.description, category: p.category,
          source: ui.voiced ? 'voice' : 'quick', recurring: list.length === 1 ? ui.repeat || null : null});
      }
      Object.assign(ui, {quick: '', preview: null, repeat: '', voiced: false});
      toast(list.length > 1 ? t('spend.saved_n', {n: list.length}) : t('spend.saved'), 'good'); await reload();
      document.getElementById('quick-input')?.focus();
    },
    async 'receipt-form'(f) {
      const rows = [...f.querySelectorAll('[data-row]')].filter(r => r.querySelector('[name=pick]').checked);
      if (!rows.length) throw new Error(t('spend.pick_one'));
      for (const r of rows) {
        const val = n => r.querySelector(`[name=${n}]`).value.trim();
        const cur = val('currency').toUpperCase();
        const minor = Math.round(Number(val('amount').replace(',', '.')) * 10 ** decimalsOf(cur));
        if (!(minor > 0)) { r.classList.add('bad'); throw new Error(t('err.amount_invalid')); }
        const sign = r.dataset.in === '1' ? 1 : -1;
        await api('/expenses', 'POST', {date: val('date'), amount: sign * minor, currency: cur, description: val('description'), category: val('category'), source: 'receipt'});
      }
      closeModal(); toast(rows.length > 1 ? t('spend.saved_n', {n: rows.length}) : t('spend.saved'), 'good'); await reload();
    },
    'receipt-add-row'() {
      const tbody = document.querySelector('#receipt-form tbody');
      tbody?.insertAdjacentHTML('beforeend', scanRow({date: new Date().toISOString().slice(0, 10), amount: 0, currency: (state.data.memory || {}).display_currency || 'AUD', description: '', category: 'other'}, tbody.children.length));
    },
  },
};

async function reload() {
  invalidate(['reminders']);
  await view.load();
  if (state.view === 'spending') (bus.repaint || rerender)();
}

function syncReviewButtons(root) {
  const n = ui.selected.size;
  root.querySelector('[data-action="spend-confirm"]').disabled = !n;
  root.querySelector('[data-action="spend-skip"]').disabled = !n;
  root.querySelector('[data-action="spend-confirm"]').lastChild.textContent = t('spend.confirm_n', {n});
  root.querySelector('[data-action="spend-skip"]').textContent = t('spend.skip_n', {n});
}

async function submitReview(include) {
  const root = document.getElementById('view');
  const items = [...ui.selected].map(id => {
    const item = {id, include, category: root.querySelector(`[data-cat="${CSS.escape(id)}"]`)?.value};
    const a = root.querySelector(`[data-amount="${CSS.escape(id)}"]`);
    if (a) { const row = [...state.data.spendExpected].find(r => r.id === id); item.amount = Math.round(Number(a.value.replace(',', '.')) * 10 ** decimalsOf(row.currency)); }
    return item;
  });
  const r = await api('/expenses/review', 'POST', {items});
  ui.selected.clear();
  toast(include ? t('spend.confirmed', {n: r.confirmed}) + (r.learned ? ' · ' + t('spend.learned_n', {n: r.learned}) : '') : t('spend.skipped', {n: r.skipped}), 'good');
  await reload();
}

let parseSeq = 0;
async function parseQuick(ai = false) {
  const text = ui.quick.trim(), seq = ++parseSeq;
  const preview = () => document.getElementById('quick-preview');  // looked up each time: a refresh may rebuild the page meanwhile
  const say = html => { const box = preview(); if (box) { box.classList.remove('on'); box.innerHTML = html; } };
  if (!text) { ui.preview = null; say(`<small class="muted">${t('spend.quick_hint')}</small>`); syncQuick(); return; }
  if (ai) say(`<span class="thinking"><span class="think-orb"><i></i></span><span class="think-text">${t('spend.ai_reading')}</span></span>`);
  let r;
  try { r = await api('/expenses/parse', 'POST', {text, ai}); }
  catch (e) { if (seq !== parseSeq) return; ui.preview = null; say(`<small class="muted">${esc(e.message)}</small>`); syncQuick(); return; }
  if (seq !== parseSeq) return;
  if (r.needs_ai) {  // the rules found no amount; offer the AI instead of a dead end
    ui.preview = null;
    say(`<small class="muted">${t('spend.rules_miss')}</small> <button type="button" class="link sm" data-action="quick-ai">${t('spend.ai_read')} ${icons.arrow}</button>`);
    syncQuick(); return;
  }
  ui.preview = r;
  const box = preview();
  if (box) { box.classList.add('on'); box.innerHTML = previewCard(r); box.classList.remove('pop'); void box.offsetWidth; box.classList.add('pop'); }
  syncQuick();
}

function syncQuick() {
  const btn = document.querySelector('#quick-form button.primary');
  if (btn) btn.disabled = !ui.preview || !isOwner();
  const ai = document.querySelector('#quick-form .quick-ai');
  if (ai) ai.disabled = !ui.quick.trim() || !isOwner();
}

function voice(button) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return;
  if (recognizer) { recognizer.stop(); return; }
  recognizer = new SR();
  recognizer.lang = SPEECH[lang] || 'en-US';
  recognizer.interimResults = true;
  const input = document.getElementById('quick-input');
  button.classList.add('listening');
  recognizer.onresult = e => {
    ui.quick = [...e.results].map(r => r[0].transcript).join(' ');
    ui.voiced = true;
    if (input) input.value = ui.quick;
    clearTimeout(parseTimer); parseTimer = setTimeout(parseQuick, 200);
  };
  recognizer.onerror = () => toast(t('spend.voice_error'), 'bad');
  recognizer.onend = () => { button.classList.remove('listening'); recognizer = null; };
  recognizer.start();
}

async function readText(file) {
  const buf = await file.arrayBuffer();
  const utf8 = new TextDecoder('utf-8').decode(buf);
  if (!utf8.includes('�')) return utf8;
  try { return new TextDecoder('gbk').decode(buf); } catch { return utf8; }  // many Chinese bank exports are GBK
}

async function importCsv(file) {
  if (file.size > 2_000_000) { toast(t('err.csv_large'), 'bad'); return; }
  const drop = document.getElementById('csv-drop');
  drop?.classList.add('busy');
  try {
    const content = await readText(file);
    const r = await api('/expenses/import', 'POST', {filename: file.name, content, currency: (state.data.memory || {}).display_currency || null});
    ui.lastImport = r;
    const dups = r.rows.filter(x => x.duplicate_of).length;
    toast(t('spend.imported', {n: r.rows.length, d: dups}), 'good');
    await reload();
    document.querySelector('.review-panel')?.scrollIntoView({behavior: 'smooth', block: 'start'});
  } catch (e) { toast(e.message, 'bad'); }
  finally { drop?.classList.remove('busy'); }
}




/** Downscale on the device before upload: faster, cheaper, and no full-resolution photo leaves the phone. Tall phone
 *  screenshots keep enough height for their text to stay readable. */
async function shrink(file) {
  const url = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
  const tall = img.height > img.width * 1.6;
  const k = Math.min(1, (tall ? 2400 : 1800) / Math.max(img.width, img.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(img.width * k); canvas.height = Math.round(img.height * k);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);  // transparent PNGs would turn black as JPEG
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.85);
}

function scanRow(x, i) {
  const cur = x.currency || 'AUD';
  return `<tr data-row data-in="${x.amount > 0 ? 1 : 0}"><td><input type="checkbox" name="pick" checked aria-label="${t('spend.select_all')}"></td>
    <td><input type="date" name="date" value="${esc(x.date)}" required></td>
    <td><input name="description" value="${esc(x.description)}" maxlength="200" required></td>
    <td><input name="amount" inputmode="decimal" value="${x.amount ? esc(plain(Math.abs(x.amount), cur)) : ''}" required class="num"></td>
    <td><input name="currency" value="${esc(cur)}" maxlength="3" required class="cur"></td>
    <td><select name="category">${catOptions(x.category || 'other')}</select></td></tr>`;
}

/** Receipts and banking screenshots: up to four images, read by the AI model together, checked as a list before saving. */
async function scanImages(files) {
  files = files.slice(0, 4);
  if (files.some(f => /\.(heic|heif)$/i.test(f.name) || /heic|heif/i.test(f.type))) {
    // Most browsers cannot decode HEIC; Safari can, so try first and explain if it fails.
  }
  let images;
  try { images = await Promise.all(files.map(shrink)); }
  catch { toast(t('err.receipt_heic'), 'bad'); return; }
  scanned = images;
  modal(t('spend.scan'), `<div class="receipt-scan multi"><div class="receipt-imgs">${images.map(src => `<div class="receipt-img"><img src="${src}" alt=""><span class="scan-line"></span></div>`).join('')}</div>
    <div class="receipt-fields"><div class="thinking"><span class="think-orb"><i></i></span><span class="think-text">${t('spend.reading')}</span></div></div></div>`, 'RECEIPT / CHECK BEFORE SAVING', {wide: true});
  let r;
  try { r = await api('/expenses/receipt', 'POST', {images}); } catch (e) { r = {available: false, items: [], reason: e.message}; }
  const fields = document.querySelector('.receipt-fields');
  if (!fields || scanned !== images) return;
  document.querySelector('.receipt-scan')?.classList.add('done');
  const list = r.items?.length ? r.items : [{date: new Date().toISOString().slice(0, 10), amount: 0, currency: (state.data.memory || {}).display_currency || 'AUD', description: '', category: 'other'}];
  fields.innerHTML = `<form id="receipt-form" class="form-block">
    <p class="${r.available ? 'fine' : 'note warn'}">${r.available ? t(r.kind === 'transactions' || r.kind === 'statement' ? 'spend.check_list' : 'spend.check_note', {n: r.items.length}) : t('spend.manual_note') + (r.reason ? ' · ' + esc(r.reason) : '')}</p>
    <div class="table-wrap"><table class="table scan-table"><thead><tr><th></th><th>${t('spend.date')}</th><th>${t('spend.merchant')}</th><th>${t('spend.amount')}</th><th>${t('plans.currency')}</th><th>${t('spend.category')}</th></tr></thead>
      <tbody>${list.map(scanRow).join('')}</tbody></table></div>
    <button type="button" class="link sm" data-action="receipt-add-row">${icons.plus}${t('spend.add_row')}</button>
    <div class="form-error"></div><div class="modal-actions"><button class="button primary">${icons.check}${t('spend.save_selected')}</button></div></form>`;
}
