import {t, has} from './i18n.js';

export class ApiError extends Error {
  constructor(message, code, data) { super(message); this.code = code; this.data = data; }
}

function translate(code, fallback, data) {
  if (code && has('err.' + code)) return t('err.' + code, data);
  if (fallback === 'session required') return t('err.session_required');
  if (fallback === 'invalid credential') return t('err.invalid_credential');
  return fallback || t('err.generic');
}

/** The middle rate of the last 90 days for a pair (half the days were above it, half below), cached per pair. */
const medians = {};
export function medianRate(source, target) {
  if (!source || !target || source === target) return Promise.resolve(null);
  const k = source + '-' + target;
  medians[k] ??= api(`/rates?source=${source}&target=${target}&days=90`).then(r => Number(r.median) || null, () => { delete medians[k]; return null; });
  return medians[k];
}

/** A "lowest acceptable rate" field shows that median in grey as a starting point — a suggestion, never a value. */
export function suggestMinRate(form, pair) {
  const input = form?.querySelector('[name=min_rate]');
  if (!input) return;
  const fill = async () => {
    const [s, t] = pair(), m = await medianRate(s, t);
    const [s2, t2] = pair();
    if (s2 === s && t2 === t) input.placeholder = m ? m.toFixed(m >= 100 ? 2 : 4) : '';
  };
  form.addEventListener('change', e => { if (['source', 'target'].includes(e.target.name)) fill(); });
  fill();
}

export async function api(path, method = 'GET', body) {
  let res;
  try {
    res = await fetch('/api' + path, {
      method, credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-Workspace-Request': '1'},
      ...(body !== undefined ? {body: JSON.stringify(body)} : {}),
    });
  } catch { throw new ApiError(t('err.offline'), 'offline'); }
  let value;
  try { value = await res.json(); } catch { throw new ApiError(t('err.offline'), 'offline'); }
  if (!res.ok) {
    // The session ended (signed out elsewhere, expired, server restarted): the app goes back to the sign-in stage.
    if (res.status === 401 && !/^\/(session|auth)/.test(path)) dispatchEvent(new CustomEvent('dot:signed-out'));
    let message = value.error || value.detail || '';
    if (Array.isArray(message)) message = message.map(e => e.msg).join('; ');
    throw new ApiError(translate(value.code, message, value), value.code || 'http_' + res.status, value);
  }
  return value;
}

/** POST that yields server-sent events as they arrive (agent pipeline). */
export async function* stream(path, body) {
  const res = await fetch('/api' + path, {
    method: 'POST', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json', 'X-Workspace-Request': '1'}, body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    let value = {};
    try { value = await res.json(); } catch {}
    throw new ApiError(translate(value.code, value.error || value.detail, value), value.code);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const {value, done} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});
    let cut;
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const chunk = buffer.slice(0, cut); buffer = buffer.slice(cut + 2);
      const line = chunk.split('\n').find(l => l.startsWith('data: '));
      if (line) yield JSON.parse(line.slice(6));
    }
  }
}
