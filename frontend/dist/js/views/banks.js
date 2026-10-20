import {state, t, api, toast, isOwner, rerender, modal, closeModal, bus} from '../core.js';
import {esc, panel, field, options, icons, empty} from '../ui.js';
import {num, when, lang} from '../i18n.js';

/* Bank rates and wire fees for a currency pair: read from the banks' public pages by the AI, or typed in by you.
   Shared by the Send page (pick your banks, get scenarios) and the Rates page (compare banks). */

const key = (s, t2) => `${s}-${t2}`;
export const banksFor = (s, t2) => (state.data.banks || {})[key(s, t2)] || null;

export async function loadBanks(source, target, force = false) {
  state.data.banks ??= {};
  if (!force && state.data.banks[key(source, target)]) return state.data.banks[key(source, target)];
  try { state.data.banks[key(source, target)] = await api(`/banks?source=${source}&target=${target}`); }
  catch { state.data.banks[key(source, target)] = []; }
  if (!force) autoRead(source, target);
  return state.data.banks[key(source, target)];
}

/* Every bank for the pair is read automatically (official pages, then third-party data, then the AI's estimate);
   figures younger than a day are kept. The screen shows how far it is and refreshes as results arrive. */
const auto = {};
async function autoRead(source, target) {
  const k = key(source, target);
  if (auto[k]?.running || !isOwner()) return;
  let st;
  try { st = await api('/banks/auto', 'POST', {source, target}); } catch { return; }
  if (!st.model || !st.pending.length) { delete auto[k]; return; }
  const count = x => ({total: x.pending.filter(b => b !== 'discovering').length + x.done.length + x.failed.length,
    pending: x.pending.filter(b => b !== 'discovering').length, discovering: x.pending.includes('discovering')});
  auto[k] = {running: true, ...count(st)};
  repaint();
  let seen = st.done.length + st.failed.length;
  while (auto[k]) {
    await new Promise(r => setTimeout(r, 3000));
    try { st = await api(`/banks/auto?source=${source}&target=${target}`); } catch { break; }
    const finished = st.done.length + st.failed.length, changed = finished !== seen;  // a bank's figures arrived
    if (changed || !st.pending.length) {
      seen = finished;
      await loadBanks(source, target, true);
      if (state.send) state.send.scen = null;  // scenarios are recomputed with the new figures
    }
    Object.assign(auto[k], count(st));  // the AI may have found more banks for this pair: the total grows
    if (!st.pending.length) { delete auto[k]; repaint(); break; }
    if (changed) repaint(); else progressLine(source, target);  // only the "reading 6 of 11" line moves
  }
}
/** Update the progress line where it is, without rebuilding the page. */
function progressLine(source, target) {
  const html = autoLine(source, target);
  document.querySelectorAll('.bank-auto').forEach(el => { el.outerHTML = html; });
}
const repaint = () => { if (['send', 'markets'].includes(state.view)) (bus.render || rerender)(); };  // only where banks are on screen; waits for typing or a drag

/** "Reading 3 of 11 banks…" while the automatic read runs; nothing otherwise. */
export function autoLine(source, target) {
  const a = auto[key(source, target)];
  return a ? `<span class="bank-auto"><span class="pulse"></span>${a.discovering ? t('bank.discovering', {s: source, t: target}) : t('bank.auto', {n: a.total - a.pending, m: a.total})}</span>` : '';
}

/** The bank's name in the reader's language where we know it (中国银行 rather than Bank of China). */
export const bankName = b => !b ? '' : String(lang).startsWith('zh') && b.name_zh ? b.name_zh : b.name;

const fee = f => f ? `${num(f.amount, 2)} ${esc(f.currency)}` : '—';
const origin = p => p.origin === 'user' ? t('bank.by_you') : p.origin === 'ai_knowledge' ? t('bank.by_knowledge', {y: p.as_of || '—'})
  : p.origin === 'third_party' ? t('bank.by_third', {d: p.rate_date || '—'}) : t('bank.by_ai');
// The exact page text each figure was read from: anyone can check it.
const evidence = p => [...Object.values(p.evidence || {}).slice(0, 2).map(q => `<br><q class="bank-quote">${esc(q)}</q>`),
  (p.unverified || []).length ? `<br><span class="muted">${t('bank.unverified', {f: p.unverified.map(f => t('scen.u.' + (f === 'rate' ? 'bank_rate' : f === 'fee_pct' ? 'send_fee' : f))).join(', ')})}</span>` : ''].join('');
const needsHand = p => !p || p.status !== 'ok';

/** Figures for a bank: read its pages, or use what the AI knows; only if both fail is a hand entry needed. */
export async function ensureBank(bank, source, target) {
  const b = (banksFor(source, target) || []).find(x => x.id === bank);
  if (!b || b.pricing?.status === 'ok') return b;
  try { state.data.banks[key(source, target)] = await api(`/banks/${encodeURIComponent(bank)}/refresh`, 'POST', {source, target}); }
  catch (e) { toast(e.message, 'bad'); await loadBanks(source, target, true); }
  return (banksFor(source, target) || []).find(x => x.id === bank);
}

/** One line about a bank's known pricing: rate, fees, where it came from and when. */
export function pricingLine(b) {
  const p = b?.pricing;
  if (!p) return `<span class="muted">${t('bank.none')}</span>`;
  if (p.status !== 'ok') return `<span class="muted">${esc(t('bank.st.' + p.status))}${p.error ? ' · ' + esc(p.error) : ''}</span>`;
  const bits = [p.rate ? `${t('bank.rate')} ${num(p.rate, 4)}${p.rate_origin === 'third_party' ? ` (${t('bank.rate_third', {d: p.rate_date || '—'})})` : ''}` : p.rate_margin_pct ? t('bank.margin', {p: num(p.rate_margin_pct, 2)}) : null, p.fee_send ? `${t('bank.fee_send')} ${fee(p.fee_send)}` : null,
    p.fee_pct ? `${num(p.fee_pct, 2)}%` : null, p.intermediary ? `${t('bank.intermediary')} ${fee(p.intermediary)}` : null,
    p.fee_receive ? `${t('bank.fee_receive')} ${fee(p.fee_receive)}` : null].filter(Boolean);
  return `${bits.join(' · ') || t('bank.nothing')} <small class="muted">· ${origin(p)} ${when(p.updated)}</small>`;
}

/** The bank's fee knowledge: every fee its pages state, each with the exact text, the page and when it was read. */
const host = u => { try { return new URL(u).hostname; } catch { return ''; } };
const kbValue = k => [k.amount && `${num(k.amount, 2)} ${esc(k.currency || '')}`, k.pct && `${num(k.pct, 3)}%`,
  (k.min || k.max) && t('bank.kb_range', {a: k.min ? num(k.min, 2) : '—', b: k.max ? num(k.max, 2) : '—'})].filter(Boolean).join(' · ');
export function knowledgeList(b) {
  const list = b?.knowledge || [];
  if (!list.length) return '';
  return `<details class="kb"><summary>${t('bank.kb_title', {n: list.length})}</summary><ul class="kb-list">${list.map(k => `<li>
      <div><span class="tag k-fee">${t('bank.k.' + k.kind)}</span> <b>${esc(k.label)}</b> <span class="kb-val">${kbValue(k)}</span></div>
      <q class="bank-quote">${esc(k.quote)}</q>
      <small class="muted"><a href="${esc(k.url)}" target="_blank" rel="noopener noreferrer">${esc(host(k.url))}</a> · ${t('bank.kb_read', {d: when(k.fetched)})}</small></li>`).join('')}</ul>
    <p class="fine">${t('bank.kb_note')}</p></details>`;
}

const actions = (b, s, t2) => isOwner() ? `<button class="link sm" data-action="bank-refresh" data-bank="${esc(b.id)}" data-s="${esc(s)}" data-t="${esc(t2)}">${icons.agent}${t('bank.read')}</button>
  ${needsHand(b.pricing) ? `<button class="link sm" data-action="bank-edit" data-bank="${esc(b.id)}" data-s="${esc(s)}" data-t="${esc(t2)}">${t('bank.edit')}</button>` : ''}` : '';

/** The Rates page panel: every bank that sends or receives this pair, with what is known. */
export function bankPanel(source, target) {
  const list = (banksFor(source, target) || []).filter(b => b.side);
  const body = list.length ? `<div class="table-wrap"><table class="table bank-table"><thead><tr><th>${t('bank.bank')}</th><th>${t('bank.side')}</th><th>${t('bank.rate')} <small>${esc(target)} / 1 ${esc(source)}</small></th><th>${t('bank.fees')}</th><th>${t('bank.source')}</th><th></th></tr></thead><tbody>
    ${list.map(b => { const p = b.pricing || {}; return `<tr class="${p.status === 'ok' ? '' : 'dim'}"><td><b>${esc(bankName(b))}</b><small class="muted block">${esc(b.country)}${b.origin === 'ai' ? ` · <span class="tag k-ai">${t('bank.found_ai')}</span>${b.website ? ` <a href="${esc(b.website)}" target="_blank" rel="noopener noreferrer">${esc(host(b.website))}</a>` : ''}` : ''}</small></td>
      <td>${(b.sides || [b.side]).map(x => t('bank.side_' + x)).join(' / ')}</td><td class="num">${p.rate ? num(p.rate, 4) + (p.rate_origin === 'third_party' ? `<small class="muted block">${t('bank.rate_third', {d: p.rate_date || '—'})}</small>` : '') : p.rate_margin_pct ? `<small>${t('bank.margin', {p: num(p.rate_margin_pct, 2)})}</small>` : '—'}</td>
      <td><small>${[p.fee_send && `${t('bank.fee_send')} ${fee(p.fee_send)}`, p.fee_pct && `${num(p.fee_pct, 2)}%`, p.intermediary && `${t('bank.intermediary')} ${fee(p.intermediary)}`, p.fee_receive && `${t('bank.fee_receive')} ${fee(p.fee_receive)}`].filter(Boolean).join('<br>') || '—'}</small></td>
      <td><small>${p.updated ? `${origin(p)} · ${when(p.updated)}` : t('bank.none')}${(p.sources || []).filter(u => u.startsWith('https://')).map(u => `<br><a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(new URL(u).hostname)}</a>`).join('')}${evidence(p)}</small></td>
      <td class="nowrap">${actions(b, source, target)}</td></tr>${(b.knowledge || []).length ? `<tr class="kb-row"><td colspan="6">${knowledgeList(b)}</td></tr>` : ''}`; }).join('')}</tbody></table></div>`
    : empty(t('bank.no_banks'));
  return panel(t('bank.title'), `${autoLine(source, target)}${body}<p class="fine">${t('bank.note')}</p>`, {cls: 'bank-panel', id: 'bank-panel', sub: `${esc(source)} → ${esc(target)}`});
}

export const view = {
  id: 'banks',
  needs: [],
  render() { return ''; },
  actions: {
    async 'bank-refresh'(el) {
      el.classList.add('busy');
      toast(t('bank.reading'));
      try {
        state.data.banks[key(el.dataset.s, el.dataset.t)] = await api(`/banks/${encodeURIComponent(el.dataset.bank)}/refresh`, 'POST', {source: el.dataset.s, target: el.dataset.t});
        const b = state.data.banks[key(el.dataset.s, el.dataset.t)].find(x => x.id === el.dataset.bank);
        toast(b?.pricing?.status === 'ok' ? t('bank.read_ok', {b: bankName(b)}) : t('bank.read_empty'), b?.pricing?.status === 'ok' ? 'good' : '');
      } catch (e) { toast(e.message, 'bad'); await loadBanks(el.dataset.s, el.dataset.t, true); }
      if (state.send) state.send.scen = null;  // the Send page recomputes its scenarios with the new figures
      rerender();
    },
    'bank-edit'(el) {
      const list = banksFor(el.dataset.s, el.dataset.t) || [], b = list.find(x => x.id === el.dataset.bank), p = b?.pricing || {};
      const money = (name, f, cur) => `<div class="grid-2">${field('bk-' + name, t('bank.' + name), `<input id="bk-${name}" name="${name}" inputmode="decimal" value="${esc(f?.amount || '')}">`)}
        ${field('bk-' + name + '-c', t('plans.currency'), `<input id="bk-${name}-c" name="${name}_currency" maxlength="3" value="${esc(f?.currency || cur)}">`)}</div>`;
      modal(esc(bankName(b)), `<form id="bank-form" class="form-block" data-bank="${esc(b.id)}" data-s="${esc(el.dataset.s)}" data-t="${esc(el.dataset.t)}">
        <p class="fine">${t('bank.edit_d')}</p>
        ${field('bk-rate', `${t('bank.rate')} (${esc(el.dataset.t)} / 1 ${esc(el.dataset.s)})`, `<input id="bk-rate" name="rate" inputmode="decimal" value="${esc(p.rate || '')}">`)}
        ${money('fee_send', p.fee_send, el.dataset.s)}${field('bk-pct', t('bank.fee_pct'), `<input id="bk-pct" name="fee_pct" inputmode="decimal" value="${esc(p.fee_pct || '')}">`)}
        ${money('intermediary', p.intermediary, el.dataset.s)}${money('fee_receive', p.fee_receive, el.dataset.t)}
        <div class="form-error"></div><div class="modal-actions"><button class="button primary">${icons.check}${t('common.save')}</button></div></form>`, 'BANK / RATES & FEES');
    },
  },
  submit: {
    async 'bank-form'(f) {
      const v = Object.fromEntries(new FormData(f));
      const m = n => v[n] ? {amount: v[n].replace(',', '.'), currency: (v[n + '_currency'] || '').toUpperCase()} : null;
      state.data.banks[key(f.dataset.s, f.dataset.t)] = await api(`/banks/${encodeURIComponent(f.dataset.bank)}/pricing`, 'PUT', {source: f.dataset.s, target: f.dataset.t,
        rate: v.rate ? v.rate.replace(',', '.') : null, fee_pct: v.fee_pct || null, fee_send: m('fee_send'), intermediary: m('intermediary'), fee_receive: m('fee_receive')});
      if (state.send) state.send.scen = null;
      closeModal(); toast(t('bank.saved'), 'good'); rerender();
    },
  },
};
