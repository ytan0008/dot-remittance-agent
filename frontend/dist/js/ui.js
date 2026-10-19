import {t, money} from './i18n.js';

export const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
export const attr = esc;

export const chip = (status, ns = 'status') => `<span class="chip s-${esc(status)}"><i></i>${esc(t(ns + '.' + status))}</span>`;
export const tag = (kind, extra = '') => `<span class="tag k-${esc(kind)} ${extra}">${esc(t('kind.' + kind))}</span>`;
export const amt = (minor, currency, cls = '') => `<span class="amt ${cls}">${esc(money(minor, currency))}<small>${esc(currency)}</small></span>`;
export const empty = (text, action = '') => `<div class="empty"><span class="empty-orb"><i></i></span><p>${esc(text)}</p>${action}</div>`;
export const mono = s => `<code class="mono">${esc(s)}</code>`;
export const short = id => esc(String(id || '').slice(0, 8));

export function panel(title, body, {sub = '', actions = '', cls = '', id = '', tilt = false} = {}) {
  return `<article class="panel reveal ${tilt ? 'tilt' : ''} ${cls}" ${id ? `id="${id}"` : ''}><header class="panel-head"><h2>${title}</h2>${sub ? `<span class="sub">${sub}</span>` : ''}${actions ? `<div class="panel-actions">${actions}</div>` : ''}</header>${body}</article>`;
}

export const field = (id, label, input, hint = '') =>
  `<div class="field"><label for="${id}">${esc(label)}</label>${input}${hint ? `<small>${hint}</small>` : ''}</div>`;

export const options = (list, selected) => list.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(selected ?? '') ? 'selected' : ''}>${esc(l)}</option>`).join('');

export const segmented = (name, list, selected, action) =>
  `<div class="segmented" role="radiogroup">${list.map(([v, l]) => `<button type="button" role="radio" aria-checked="${v === selected}" class="${v === selected ? 'on' : ''}" data-action="${action}" data-value="${esc(v)}" data-name="${name}">${esc(l)}</button>`).join('')}</div>`;

export const dl = rows => `<dl class="facts">${rows.filter(Boolean).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join('')}</dl>`;

const I = (paths, extra = '') => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" ${extra}>${paths}</svg>`;
export const icons = {
  overview: I('<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="2.6" class="fill"/>'),
  agent: I('<circle cx="12" cy="12" r="3.2"/><ellipse cx="12" cy="12" rx="9" ry="4.2"/><circle cx="20.2" cy="10.4" r="1.3" class="fill"/>'),
  send: I('<circle cx="12" cy="12" r="8.5"/><path d="M9 15l6-6M10 9h5v5"/>'),
  spending: I('<rect x="5" y="3.5" width="14" height="17" rx="2"/><path d="M8.5 8h7M8.5 12h7M8.5 16h4"/><circle cx="16" cy="16" r="1.3" class="fill"/>'),
  study: I('<path d="M3 9.5L12 5l9 4.5-9 4.5z"/><path d="M7 11.6V16c1.4 1.3 3 2 5 2s3.6-.7 5-2v-4.4"/><circle cx="20" cy="15" r="1.3" class="fill"/>'),
  progress: I('<circle cx="12" cy="12" r="8.5"/><path d="M8 13.5l2.6 2.4L16 9.5"/><circle cx="12" cy="3.5" r="1.3" class="fill"/>'),
  sandbox: I('<path d="M4 15.5h16"/><path d="M6 15.5l1.6-6h8.8l1.6 6"/><circle cx="9.5" cy="12.4" r="1.1" class="fill"/><circle cx="13.6" cy="11" r="1.1"/><path d="M5 19h14"/>'),
  templates: I('<rect x="4" y="4" width="16" height="16" rx="2.5"/><path d="M8 9h8M8 13h5"/><circle cx="16" cy="16" r="1.3" class="fill"/>'),
  payments: I('<path d="M5 7h14M5 12h14M5 17h9"/><circle cx="18" cy="17" r="1.4" class="fill"/>'),
  markets: I('<path d="M4 17l4.5-5 3.5 3 7-8"/><circle cx="19" cy="7" r="1.4" class="fill"/>'),
  plans: I('<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1.2" class="fill"/>'),
  habits: I('<rect x="4" y="5" width="16" height="15" rx="3"/><path d="M4 10h16"/><circle cx="9" cy="14.5" r="1.1" class="fill"/><circle cx="13" cy="14.5" r="1.1" class="fill"/><circle cx="17" cy="14.5" r="1.1"/>'),
  wallets: I('<rect x="3.5" y="6" width="17" height="13" rx="3"/><path d="M15 12.5h5.5"/><circle cx="16.5" cy="12.5" r="1.2" class="fill"/><path d="M6 6l9-3 1 3"/>'),
  autonomy: I('<circle cx="12" cy="12" r="8.5" stroke-dasharray="2 2.6"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.6" class="fill"/>'),
  memory: I('<path d="M12 4a6 6 0 0 0-6 6c0 2 1 3.3 2 4.3V18h8v-3.7c1-1 2-2.3 2-4.3a6 6 0 0 0-6-6z"/><path d="M10 21h4"/><circle cx="12" cy="10" r="1.6" class="fill"/>'),
  routes: I('<circle cx="5.5" cy="17" r="2"/><circle cx="18.5" cy="7" r="2"/><path d="M7.3 15.8C11 13 9 9 16.7 8" stroke-dasharray="2 2"/>'),
  audit: I('<path d="M8 4v16" stroke-dasharray="1.5 2.2"/><circle cx="8" cy="7" r="1.6" class="fill"/><circle cx="8" cy="12" r="1.6"/><circle cx="8" cy="17" r="1.6" class="fill"/><path d="M12 7h8M12 12h6M12 17h7"/>'),
  more: I('<circle cx="6" cy="12" r="1.5" class="fill"/><circle cx="12" cy="12" r="1.5" class="fill"/><circle cx="18" cy="12" r="1.5" class="fill"/>'),
  plus: I('<path d="M12 6v12M6 12h12"/>'),
  arrow: I('<path d="M8 16l8-8M9.5 8H16v6.5"/>'),
  check: I('<path d="M6 12.5l4 4 8-9"/>'),
  copy: I('<rect x="8" y="8" width="11" height="11" rx="2.5"/><path d="M5 15V7a2 2 0 0 1 2-2h8"/>'),
  swap: I('<path d="M7 7h11l-3-3M17 17H6l3 3"/>'),
  zoomIn: I('<circle cx="11" cy="11" r="6"/><path d="M11 8.5v5M8.5 11h5M16 16l4 4"/>'),
  zoomOut: I('<circle cx="11" cy="11" r="6"/><path d="M8.5 11h5M16 16l4 4"/>'),
  reset: I('<path d="M5 12a7 7 0 1 0 2.1-5"/><path d="M5 4v4h4"/>'),
  print: I('<path d="M7 9V4h10v5"/><rect x="4" y="9" width="16" height="7" rx="2"/><path d="M7 14h10v6H7z"/>'),
  external: I('<path d="M14 5h5v5M19 5l-8 8M18 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4"/>'),
};
