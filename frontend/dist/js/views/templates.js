import {state, t, api, toast, isOwner, rerender, modal, closeModal} from '../core.js';
import {esc, panel, field, options, icons, empty} from '../ui.js';
import {money, region} from '../i18n.js';

const FORMATS = ['swift', 'sepa', 'au_bsb', 'uk_fps', 'us_ach', 'cn_cnaps', 'in_neft'];
const CURRENCIES = ['AUD', 'USD', 'CNY', 'EUR', 'GBP', 'JPY', 'HKD', 'SGD', 'CAD', 'NZD', 'KRW', 'VND', 'INR', 'CHF'];
const ACCOUNT_KEYS = ['account', 'iban', 'account_number'];
const ui = {format: 'swift', values: {}, currency: 'AUD', name: '', amount: '', purpose: '', recipient: '', editing: null, check: null, tried: false};
const shown = (issues, id) => (issues || []).filter(i => i.field === id && (i.code !== 'required' || ui.tried));
let timer = 0, seq = 0;
const owner = () => isOwner() ? '' : 'disabled';

function input(f) {
  const v = ui.values[f.id] ?? '';
  const common = `id="tf-${f.id}" name="${f.id}" data-tf="${f.id}" ${owner()}`;
  if (f.kind === 'charges') return `<select ${common}>${options((state.data.tformats?.charges || []).map(c => [c, t('tf.charge.' + c)]), v || 'SHA')}</select>`;
  if (f.kind === 'purpose') return `<select ${common}><option value="">—</option>${options((state.data.tformats?.purposes || []).map(c => [c, `${c} · ${t('tf.purpose.' + c)}`]), v)}</select>`;
  if (f.kind === 'account_type') return `<select ${common}>${options([['checking', t('tf.checking')], ['savings', t('tf.savings')]], v || 'checking')}</select>`;
  const mono = ['bic', 'iban', 'account_or_iban', 'bsb', 'sort_code', 'aba', 'ifsc', 'cnaps', 'cn_account'].includes(f.kind) || f.kind.startsWith('digits');
  const area = f.id.endsWith('address');
  return area ? `<textarea ${common} rows="2" maxlength="${f.max}">${esc(v)}</textarea>`
    : `<input ${common} maxlength="${f.max + 8}" value="${esc(v)}" class="${mono ? 'mono' : ''}" autocomplete="off" spellcheck="false">`;
}

function fieldBlock(f) {
  const found = shown(ui.check?.issues, f.id);
  const level = found.some(i => i.level === 'error') ? 'error' : found.length ? 'warn' : (ui.values[f.id] ? 'ok' : '');
  return `<div class="field tf-field lv-${level}" data-field="${f.id}"><label for="tf-${f.id}">${t('tf.f.' + f.id)}${f.required ? '' : ` <small class="muted">${t('tf.optional')}</small>`}</label>
    ${input(f)}<small class="tf-msg">${found.length ? found.map(i => esc(t('tf.e.' + i.code))).join(' · ') : esc(t('tf.h.' + f.id))}</small></div>`;
}

function formPanel() {
  const fm = state.data.tformats?.formats?.[ui.format];
  if (!fm) return panel(t('tf.new'), empty(t('common.loading')));
  const recipients = (state.data.recipients || []).filter(r => r.rail !== 'evm');
  const fixed = fm.currency;
  const status = ui.check ? (ui.check.ok ? `<span class="tf-status ok">${icons.check}${t('tf.valid')}${ui.check.country ? ' · ' + esc(region(ui.check.country) || ui.check.country) : ''}</span>`
    : `<span class="tf-status bad">${t('tf.invalid')}</span>`) : '';
  return panel(ui.editing ? t('tf.edit') : t('tf.new'), `
    <div class="tf-formats hscroll" role="tablist">${FORMATS.map(f => `<button type="button" class="tf-fmt ${f === ui.format ? 'on' : ''}" data-action="tf-format" data-value="${f}" ${ui.editing ? 'disabled' : ''}>
      <b>${t('tf.fmt.' + f)}</b><small>${t('tf.fmt.' + f + '_d')}</small></button>`).join('')}</div>
    <form id="tf-form" class="form-block tf-form" autocomplete="off">
      <div class="grid-3">${field('tf-name', t('tf.name'), `<input id="tf-name" name="__name" maxlength="80" required value="${esc(ui.name)}" placeholder="${t('tf.name_ph')}" ${owner()}>`)}
        ${field('tf-currency', t('plans.currency'), fixed ? `<input id="tf-currency" value="${fixed}" disabled>` : `<select id="tf-currency" name="__currency" ${owner()}>${options(CURRENCIES.map(c => [c, c]), ui.currency)}</select>`)}
        ${field('tf-amount', t('tf.amount'), `<input id="tf-amount" name="__amount" inputmode="decimal" value="${esc(ui.amount)}" placeholder="${t('tf.optional')}" ${owner()}>`)}</div>
      <div class="tf-grid">${fm.fields.map(fieldBlock).join('')}</div>
      <div class="grid-2">${field('tf-purpose', t('tf.purpose_note'), `<input id="tf-purpose" name="__purpose" maxlength="200" value="${esc(ui.purpose)}" ${owner()}>`)}
        ${field('tf-recipient', t('tf.link_recipient'), `<select id="tf-recipient" name="__recipient" ${owner()}><option value="">—</option>${options(recipients.map(r => [r.id, `${r.name} · ${r.id}`]), ui.recipient)}</select>`)}</div>
      <div class="tf-actions">${status}<span class="grow"></span>
        ${ui.editing ? `<button type="button" class="button ghost" data-action="tf-cancel">${t('common.cancel')}</button>` : ''}
        <button class="button primary" ${owner()}>${icons.check}${t(ui.editing ? 'tf.update' : 'tf.save')}</button></div>
      <div class="form-error"></div></form>`, {cls: 'tf-panel', sub: t('tf.sub')});
}

function statusChip(x) {
  if (x.bank_changed && !x.confirmed) return `<span class="tag k-alert">${t('tf.changed')}</span>`;
  return x.confirmed ? `<span class="tag">${icons.check}${t('tf.confirmed')}</span>` : `<span class="tag k-dup">${t('tf.unconfirmed')}</span>`;
}

function listPanel() {
  const list = state.data.ttemplates || [];
  return panel(`${t('tf.saved')} <span class="muted">/ ${list.length}</span>`, list.length ? `<div class="tf-cards">${list.map(x => {
    const acc = ACCOUNT_KEYS.map(k => x.fields[k]).find(Boolean) || '';
    const bank = x.fields.bic || x.fields.bsb || x.fields.sort_code || x.fields.routing_number || x.fields.ifsc || x.fields.cnaps || x.fields.bank_name || '';
    const who = x.fields.beneficiary_name || x.fields.account_name || '';
    return `<article class="tf-card reveal ${x.confirmed ? '' : 'unconfirmed'}">
      <header><span class="tf-badge">${t('tf.fmt.' + x.format)}</span>${statusChip(x)}</header>
      <h3>${esc(x.name)}</h3><p><b>${esc(who)}</b><small class="mono">${esc(acc)} · ${esc(bank)}</small></p>
      <small class="muted">${esc(x.currency)}${x.amount ? ' · ' + esc(money(x.amount, x.currency)) : ''}${x.country ? ' · ' + esc(region(x.country) || x.country) : ''}${x.created_by === 'agent' ? ' · ' + t('tf.by_agent') : ''}</small>
      ${x.confirmed ? '' : `<p class="note warn">${t(x.bank_changed ? 'tf.changed_d' : 'tf.unconfirmed_d')}</p>`}
      <div class="row-actions">${x.confirmed ? `<button class="button sm primary" data-action="tf-sheet" data-id="${esc(x.id)}" ${owner()}>${t('tf.sheet')}</button>`
        : `<button class="button sm primary" data-action="tf-confirm" data-id="${esc(x.id)}" ${owner()}>${t('tf.confirm')}</button>`}
        <button class="button sm ghost" data-action="tf-plan" data-currency="${esc(x.currency)}" data-amount="${x.amount || ''}" data-purpose="${esc(x.purpose || '')}">${t('tf.plan')}</button>
        <button class="link sm" data-action="tf-edit" data-id="${esc(x.id)}" ${owner()}>${t('tf.edit_short')}</button>
        <button class="link sm muted" data-action="tf-delete" data-id="${esc(x.id)}" ${owner()}>${t('common.delete')}</button></div></article>`;
  }).join('')}</div>` : empty(t('tf.none')), {cls: 'tf-list'});
}

function guidePanel() {
  return panel(t('tf.guide'), `<ul class="tf-guide">${['swift', 'bic', 'iban', 'charges', 'names', 'scam'].map(k => `<li><b>${t('tf.g.' + k)}</b><p>${t('tf.g.' + k + '_d')}</p></li>`).join('')}</ul>`, {cls: 'tf-guide-panel'});
}

export const view = {
  id: 'templates',
  needs: ['recipients', 'routes'],
  async load() {
    const [formats, list] = await Promise.all([state.data.tformats ? Promise.resolve(state.data.tformats) : api('/transfer-formats'), api('/transfer-templates')]);
    Object.assign(state.data, {tformats: formats, ttemplates: list});
  },
  render() {
    return `<div class="split wide-left">${formPanel()}${guidePanel()}</div>${listPanel()}`;
  },
  mount(root) {
    root.querySelector('#tf-form')?.addEventListener('input', e => {
      const el = e.target;
      if (el.dataset.tf) { ui.values[el.dataset.tf] = el.value; schedule(); }
      if (el.name === '__name') ui.name = el.value;
      if (el.name === '__amount') ui.amount = el.value;
      if (el.name === '__purpose') ui.purpose = el.value;
      if (el.name === '__recipient') ui.recipient = el.value;
      if (el.name === '__currency') { ui.currency = el.value; schedule(); }
    });
  },
  actions: {
    'tf-format'(el) { Object.assign(ui, {format: el.dataset.value, values: {}, check: null, tried: false}); rerender(); },
    'tf-cancel'() { reset(); rerender(); },
    async 'tf-edit'(el) {
      const x = await api(`/transfer-templates/${encodeURIComponent(el.dataset.id)}?reveal=true`);
      Object.assign(ui, {editing: x.id, format: x.format, values: {...x.fields}, currency: x.currency, name: x.name,
        amount: x.amount ? money(x.amount, x.currency).replace(/,/g, '') : '', purpose: x.purpose || '', recipient: x.recipient_id || '', check: null});
      rerender(); schedule(0);
      document.querySelector('.tf-panel')?.scrollIntoView({behavior: 'smooth', block: 'start'});
    },
    async 'tf-delete'(el) { await api(`/transfer-templates/${encodeURIComponent(el.dataset.id)}`, 'DELETE'); await reload(); },
    'tf-confirm'(el) {
      const x = state.data.ttemplates.find(y => y.id === el.dataset.id);
      modal(t('tf.confirm_title'), `<form id="tf-confirm-form" class="form-block" data-id="${esc(x.id)}"><p class="intro">${t('tf.confirm_intro')}</p>
        <ul class="tf-guide compact"><li>${t('tf.confirm_1')}</li><li>${t('tf.confirm_2')}</li><li>${t('tf.confirm_3')}</li></ul>
        <label class="check-label"><input type="checkbox" required> ${t('tf.confirm_check')}</label>
        <div class="form-error"></div><div class="modal-actions"><button class="button primary">${t('tf.confirm')}</button></div></form>`, 'TEMPLATE / VERIFY');
    },
    async 'tf-sheet'(el) {
      const s = await api(`/transfer-templates/${encodeURIComponent(el.dataset.id)}/sheet`, 'POST', {});
      const label = f => f === 'amount' ? t('spend.amount') : f === 'currency' ? t('plans.currency') : t('tf.f.' + f);
      const text = s.rows.map(r => `${label(r.field)}: ${r.value}`).join('\n');
      modal(s.name, `<div class="tf-sheet"><p class="fine">${t('tf.sheet_d')}</p>
        <dl class="tf-rows">${s.rows.map(r => `<div><dt>${esc(label(r.field))}</dt><dd><span class="mono">${esc(r.value)}</span><button class="icon-button sm" data-action="copy" data-value="${esc(r.value)}" aria-label="${t('common.copy')}">${icons.copy}</button></dd></div>`).join('')}</dl>
        ${s.mt103 ? `<details class="tf-mt"><summary>${t('tf.mt103')}</summary><pre class="mono">${esc(s.mt103)}</pre><p class="fine">${t('tf.mt103_d')}</p></details>` : ''}
        <p class="note warn">${t('tf.g.scam_d')}</p>
        <div class="modal-actions"><button class="button ghost" data-action="copy" data-value="${esc(text)}">${icons.copy}${t('tf.copy_all')}</button>
        <a class="button" id="tf-download" download="${esc(s.name.replace(/[^\w.-]+/g, '_'))}.txt">${t('tf.download')}</a></div></div>`, `TEMPLATE / ${t('tf.fmt.' + s.format)}`, {wide: true, mount: root => {
        const a = root.querySelector('#tf-download');
        if (a) a.href = URL.createObjectURL(new Blob([text + (s.mt103 ? '\n\n' + s.mt103 : '') + '\n'], {type: 'text/plain'}));
      }});
    },
    'tf-plan'(el) {
      const route = (state.data.routes || []).find(r => r.enabled && r.target === el.dataset.currency) || (state.data.routes || []).find(r => r.enabled && r.source === el.dataset.currency);
      if (route) state.send.route = route.id;
      if (el.dataset.amount && route?.target === el.dataset.currency) Object.assign(state.send, {mode: 'receive', receive: money(Number(el.dataset.amount), el.dataset.currency).replace(/,/g, ''), result: null});
      if (el.dataset.purpose) state.send.purpose = el.dataset.purpose;
      location.hash = 'send';
    },
  },
  submit: {
    async 'tf-form'() {
      ui.tried = true;
      const body = {name: ui.name, format: ui.format, fields: clean(), currency: state.data.tformats.formats[ui.format].currency || ui.currency,
        amount: ui.amount.replace(',', '.') || null, purpose: ui.purpose, recipient_id: ui.recipient || null, notes: ''};
      try { await api(ui.editing ? `/transfer-templates/${encodeURIComponent(ui.editing)}` : '/transfer-templates', ui.editing ? 'PUT' : 'POST', body); }
      catch (e) { schedule(0); throw e; }
      toast(t('tf.saved_toast'), 'good');
      reset(); await reload();
    },
    async 'tf-confirm-form'(f) {
      await api(`/transfer-templates/${encodeURIComponent(f.dataset.id)}/confirm`, 'POST', {});
      closeModal(); toast(t('tf.confirmed_toast'), 'good'); await reload();
    },
  },
};

function clean() {
  const fields = state.data.tformats.formats[ui.format].fields.map(f => f.id);
  return Object.fromEntries(Object.entries(ui.values).filter(([k, v]) => fields.includes(k) && String(v).trim()));
}

function reset() { Object.assign(ui, {values: {}, name: '', amount: '', purpose: '', recipient: '', editing: null, check: null, tried: false}); }

function schedule(delay = 300) {
  clearTimeout(timer);
  timer = setTimeout(validate, delay);
}

/** Live check as you type; only the messages and status change, so the field being typed in keeps focus. */
async function validate() {
  const mine = ++seq;
  let r;
  try { r = await api('/transfer-templates/validate', 'POST', {format: ui.format, fields: clean(), currency: ui.currency}); } catch { return; }
  if (mine !== seq) return;
  ui.check = r;
  const fm = state.data.tformats.formats[ui.format];
  for (const f of fm.fields) {
    const box = document.querySelector(`.tf-field[data-field="${f.id}"]`);
    if (!box) continue;
    const found = shown(r.issues, f.id);
    const level = found.some(i => i.level === 'error') ? 'error' : found.length ? 'warn' : (ui.values[f.id] ? 'ok' : '');
    box.className = `field tf-field lv-${level}`;
    box.querySelector('.tf-msg').textContent = found.length ? found.map(i => t('tf.e.' + i.code)).join(' · ') : t('tf.h.' + f.id);
  }
  const actions = document.querySelector('.tf-actions');
  actions?.querySelector('.tf-status')?.remove();
  actions?.insertAdjacentHTML('afterbegin', r.ok ? `<span class="tf-status ok">${icons.check}${t('tf.valid')}${r.country ? ' · ' + esc(region(r.country) || r.country) : ''}</span>`
    : `<span class="tf-status bad">${t('tf.invalid')}</span>`);
}

async function reload() {
  await view.load();
  if (state.view === 'templates') rerender();
}

