import {state, t, api, toast, isOwner, invalidate, rerender, modal, closeModal, formError, bus} from '../core.js';
import {esc, amt, panel, icons, empty, options, segmented} from '../ui.js';
import {money, day, lang, decimalsOf, plain} from '../i18n.js';

const CATEGORIES = ['rent', 'groceries', 'dining', 'transport', 'utilities', 'phone', 'subscriptions', 'tuition', 'shopping',
  'health', 'entertainment', 'travel', 'transfer', 'fees', 'income', 'other'];
const SPEECH = {en: 'en-US', 'zh-CN': 'zh-CN', 'zh-TW': 'zh-TW', vi: 'vi-VN', ja: 'ja-JP', ko: 'ko-KR'};
const ui = {month: new Date().toISOString().slice(0, 7), quick: '', preview: null, repeat: '', selected: new Set(), lastImport: null, period: 'week'};
let parseTimer = 0, recognizer = null;

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
      <button class="button primary sm" ${p && isOwner() ? '' : 'disabled'}>${icons.check}${t('spend.save')}</button>
    </form>
    <div class="quick-preview ${p ? 'on' : ''}" id="quick-preview">${p ? previewCard(p) : `<small class="muted">${t('spend.quick_hint')}</small>`}</div>
    <div class="spend-actions">
      <label class="drop-zone" id="csv-drop"><input type="file" id="csv-file" accept=".csv,text/csv" hidden ${isOwner() ? '' : 'disabled'}>
        <span class="drop-icon">${icons.payments}</span><span><b>${t('spend.import')}</b><small>${t('spend.import_d')}</small></span></label>
      <label class="drop-zone"><input type="file" id="receipt-file" accept="image/*" capture="environment" hidden ${isOwner() ? '' : 'disabled'}>
        <span class="drop-icon">${icons.print}</span><span><b>${t('spend.scan')}</b><small>${t('spend.scan_d')}</small></span></label>
    </div></div>`;
}

function previewCard(p) {
  return `<span class="pv"><small>${t('spend.date')}</small><input type="date" id="pv-date" value="${esc(p.date)}"></span>
    <span class="pv"><small>${t('spend.amount')}</small><b>${esc(money(-p.amount, p.currency))} ${esc(p.currency)}</b></span>
    <span class="pv grow"><small>${t('spend.description')}</small><b>${esc(p.description)}</b></span>
    <span class="pv"><small>${t('spend.category')}</small><select id="pv-cat">${catOptions(p.category)}</select></span>
    <span class="pv"><small>${t('spend.repeat')}</small><select id="pv-repeat">${options([['', t('spend.once')], ['monthly', t('habits.monthly')], ['weekly', t('spend.weekly')]], ui.repeat)}</select></span>`;
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

function recurringPanel() {
  const r = state.data.recurring || {active: [], candidates: []};
  const cand = r.candidates.length ? `<div class="cand-list">${r.candidates.map((c, i) => `<div class="cand"><span class="pulse"></span><div><b>${esc(c.description)}</b><small>${t('spend.looks', {cadence: t(c.cadence === 'weekly' ? 'spend.weekly' : 'habits.monthly'), n: c.occurrences})}</small></div>${amt(c.amount, c.currency)}<button class="button sm" data-action="spend-make-recurring" data-i="${i}" ${isOwner() ? '' : 'disabled'}>${t('spend.make_recurring')}</button></div>`).join('')}</div>` : '';
  const active = r.active.length ? `<ul class="list">${r.active.map(x => `<li class="row"><span class="cat-dot c-${esc(x.category)}"></span><div><b>${esc(x.description)}</b><small>${esc(t('cat.' + x.category))} · ${t(x.cadence === 'weekly' ? 'spend.weekly' : 'habits.monthly')} · ${t('spend.next_due', {d: day(x.next_date)})}</small></div>${amt(x.amount, x.currency)}<button class="x" data-action="spend-stop" data-id="${esc(x.id)}" aria-label="${t('spend.stop')}" ${isOwner() ? '' : 'disabled'}>×</button></li>`).join('')}</ul>` : `<p class="fine">${t('spend.no_recurring')}</p>`;
  return panel(t('spend.recurring'), cand + active + `<p class="fine">${t('spend.recurring_d')}</p>`, {sub: 'AUTO'});
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
    // New rows start selected, except likely duplicates which the student must opt into.
    for (const r of [...pending, ...expected]) if (!ui.known?.has(r.id)) { if (!r.duplicate_of) ui.selected.add(r.id); }
    ui.known = new Set([...pending, ...expected].map(r => r.id));
    for (const id of [...ui.selected]) if (!ui.known.has(id)) ui.selected.delete(id);
  },
  render() {
    return `${quickAdd()}${reviewTable()}${insightsPanel()}<div class="split wide-left">${summary()}${recurringPanel()}</div>${recentList()}`;
  },
  mount(root) {
    root.querySelectorAll('.bar-fill[data-ratio]').forEach(el => el.style.setProperty('--ratio', el.dataset.ratio));
    const input = root.querySelector('#quick-input');
    input?.addEventListener('input', () => { ui.quick = input.value; clearTimeout(parseTimer); parseTimer = setTimeout(parseQuick, 260); });
    root.querySelector('#quick-preview')?.addEventListener('change', e => {
      if (!ui.preview) return;
      if (e.target.id === 'pv-cat') ui.preview.category = e.target.value;
      if (e.target.id === 'pv-date') ui.preview.date = e.target.value;
      if (e.target.id === 'pv-repeat') ui.repeat = e.target.value;
    });
    root.querySelector('#csv-file')?.addEventListener('change', e => e.target.files[0] && importCsv(e.target.files[0]));
    root.querySelector('#receipt-file')?.addEventListener('change', e => e.target.files[0] && scanReceipt(e.target.files[0]));
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
    async 'receipt-save'() {},
  },
  submit: {
    async 'quick-form'() {
      if (!ui.preview) return;
      const p = ui.preview;
      await api('/expenses', 'POST', {date: p.date, amount: p.amount, currency: p.currency, description: p.description, category: p.category,
        source: ui.voiced ? 'voice' : 'quick', recurring: ui.repeat || null});
      Object.assign(ui, {quick: '', preview: null, repeat: '', voiced: false});
      toast(t('spend.saved'), 'good'); await reload();
      document.getElementById('quick-input')?.focus();
    },
    async 'receipt-form'(f) {
      const v = Object.fromEntries(new FormData(f));
      const cur = v.currency.toUpperCase();
      const minor = Math.round(Number(String(v.amount).replace(',', '.')) * 10 ** decimalsOf(cur));
      if (!(minor > 0)) throw new Error(t('err.amount_invalid'));
      await api('/expenses', 'POST', {date: v.date, amount: -minor, currency: cur, description: v.description, category: v.category, source: 'receipt'});
      closeModal(); toast(t('spend.saved'), 'good'); await reload();
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

async function parseQuick() {
  const text = ui.quick.trim();
  const box = document.getElementById('quick-preview');
  if (!text) { ui.preview = null; if (box) { box.classList.remove('on'); box.innerHTML = `<small class="muted">${t('spend.quick_hint')}</small>`; } syncQuick(); return; }
  try { ui.preview = await api('/expenses/parse', 'POST', {text}); }
  catch (e) { ui.preview = null; if (box) { box.classList.remove('on'); box.innerHTML = `<small class="muted">${esc(e.message)}</small>`; } syncQuick(); return; }
  if (box) { box.classList.add('on'); box.innerHTML = previewCard(ui.preview); }
  syncQuick();
}

function syncQuick() {
  const btn = document.querySelector('#quick-form button.primary');
  if (btn) btn.disabled = !ui.preview || !isOwner();
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

/** Downscale on the device before upload: faster, cheaper, and no full-resolution photo leaves the phone. */
async function shrink(file, max = 1600) {
  const url = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
  const k = Math.min(1, max / Math.max(img.width, img.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(img.width * k); canvas.height = Math.round(img.height * k);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);  // transparent PNGs would turn black as JPEG
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.85);
}

async function scanReceipt(file) {
  let image;
  try { image = await shrink(file); } catch { toast(t('err.receipt_invalid'), 'bad'); return; }
  modal(t('spend.scan'), `<div class="receipt-scan"><div class="receipt-img"><img src="${image}" alt=""><span class="scan-line"></span></div><div class="receipt-fields"><div class="thinking"><span class="think-orb"><i></i></span><span class="think-text">${t('spend.reading')}</span></div></div></div>`, 'RECEIPT / CHECK BEFORE SAVING', {wide: true});
  let r;
  try { r = await api('/expenses/receipt', 'POST', {image}); } catch (e) { r = {available: false, reason: e.message}; }
  const cur = r.currency || (state.data.memory || {}).display_currency || 'AUD';
  const fields = document.querySelector('.receipt-fields');
  if (!fields) return;
  document.querySelector('.receipt-scan')?.classList.add('done');
  fields.innerHTML = `<form id="receipt-form" class="form-block">
    <p class="${r.available ? 'fine' : 'note warn'}">${r.available ? t('spend.check_note') : t('spend.manual_note') + (r.reason ? ' · ' + esc(r.reason) : '')}</p>
    <div class="field"><label for="rc-desc">${t('spend.merchant')}</label><input id="rc-desc" name="description" required maxlength="200" value="${esc(r.description || '')}"></div>
    <div class="grid-2"><div class="field"><label for="rc-amount">${t('spend.amount')}</label><input id="rc-amount" name="amount" inputmode="decimal" required value="${r.amount ? esc(plain(-r.amount, cur)) : ''}"></div>
    <div class="field"><label for="rc-cur">${t('plans.currency')}</label><input id="rc-cur" name="currency" required maxlength="3" value="${esc(cur)}"></div></div>
    <div class="grid-2"><div class="field"><label for="rc-date">${t('spend.date')}</label><input id="rc-date" name="date" type="date" required value="${esc(r.date || new Date().toISOString().slice(0, 10))}"></div>
    <div class="field"><label for="rc-cat">${t('spend.category')}</label><select id="rc-cat" name="category">${catOptions(r.category || 'other')}</select></div></div>
    <div class="form-error"></div><div class="modal-actions"><button class="button primary">${icons.check}${t('spend.save')}</button></div></form>`;
}
