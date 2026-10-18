import en from './locales/en.js';

export const LANGS = [
  ['en', 'English'], ['zh-CN', '简体中文'], ['zh-TW', '繁體中文'], ['vi', 'Tiếng Việt'], ['ja', '日本語'], ['ko', '한국어'],
];
const DECIMALS = {JPY: 0, KRW: 0, VND: 0, CLP: 0, PYG: 0, ISK: 0, ETH: 18};
let dict = en;
export let lang = 'en';

function pick() {
  let saved = null;
  try { saved = localStorage.getItem('dot.lang'); } catch {}
  if (LANGS.some(([c]) => c === saved)) return saved;
  const nav = (navigator.languages || [navigator.language || 'en']).map(x => x.toLowerCase());
  for (const n of nav) {
    if (n.startsWith('zh')) return /tw|hk|mo|hant/.test(n) ? 'zh-TW' : 'zh-CN';
    const base = n.split('-')[0];
    if (['vi', 'ja', 'ko', 'en'].includes(base)) return base;
  }
  return 'en';
}

export async function setLang(code) {
  if (!LANGS.some(([c]) => c === code)) code = 'en';
  dict = code === 'en' ? en : (await import(`./locales/${code}.js`)).default;
  lang = code;
  document.documentElement.lang = code;
  try { localStorage.setItem('dot.lang', code); } catch {}
  return code;
}

export const initLang = () => setLang(pick());

export function t(key, params) {
  let s = dict[key] ?? en[key];
  if (s === undefined) return key;
  if (params) s = s.replace(/\{(\w+)\}/g, (_, k) => params[k] ?? '');
  return s;
}

export const has = key => key in dict || key in en;

/** Known backend sentences are translated; anything else stays as the server wrote it. */
export const phrase = text => text && has('p.' + text) ? t('p.' + text) : text;

export function eta(b) {
  if (b.rail === 'evm') { const n = /\d+/.exec(b.eta || '')?.[0]; return n ? t('eta.chain', {n}) : b.eta; }
  return b.eta_seconds !== undefined ? t('eta.sandbox_n', {n: b.eta_seconds}) : b.eta;
}
export const decimalsOf = c => DECIMALS[c] ?? 2;

/** Formats minor units exactly (BigInt), grouped for the current locale. */
export function money(value, currency, {maxFraction} = {}) {
  if (value === null || value === undefined || value === '') return '—';
  let n;
  try { n = BigInt(String(value)); } catch { return '—'; }
  const d = decimalsOf(currency);
  const neg = n < 0n; if (neg) n = -n;
  const s = n.toString().padStart(d + 1, '0');
  const whole = BigInt(d ? s.slice(0, -d) : s);
  let frac = d ? s.slice(-d) : '';
  const limit = maxFraction ?? (currency === 'ETH' ? 6 : d);
  if (frac.length > limit) frac = frac.slice(0, limit);
  if (currency === 'ETH') frac = frac.replace(/0+$/, '');
  const fmt = new Intl.NumberFormat(lang);
  const sep = fmt.formatToParts(1.5).find(p => p.type === 'decimal')?.value || '.';
  return (neg ? '-' : '') + fmt.format(whole) + (frac ? sep + frac : '');
}

/** Converts minor units to a plain JS number for animation only; never used for display of final values. */
export const approx = (value, currency) => Number(value) / 10 ** decimalsOf(currency);

export function num(value, digits = 4) {
  const n = Number(value);
  if (!isFinite(n)) return '—';
  return new Intl.NumberFormat(lang, {maximumFractionDigits: digits}).format(n);
}

export function pct(value, digits = 2) {
  const n = Number(value);
  if (!isFinite(n)) return '—';
  return new Intl.NumberFormat(lang, {maximumFractionDigits: digits, signDisplay: 'exceptZero'}).format(n) + '%';
}

export function when(seconds, opts = {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) {
  if (!seconds) return '—';
  return new Intl.DateTimeFormat(lang, {hour12: false, ...opts}).format(new Date(seconds * 1000));
}

export function day(iso) {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-').map(Number);
  return new Intl.DateTimeFormat(lang, {year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'}).format(Date.UTC(y, m - 1, d));
}

export function relative(seconds) {
  const diff = seconds - Date.now() / 1000;
  const rtf = new Intl.RelativeTimeFormat(lang, {numeric: 'auto'});
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(Math.round(diff), 'second');
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
  return rtf.format(Math.round(diff / 86400), 'day');
}

export function region(code) {
  if (has('region.' + code)) return t('region.' + code);
  try { return new Intl.DisplayNames([lang], {type: 'region'}).of(code) || code; } catch { return code; }
}

export function currencyName(code) {
  if (code === 'ETH') return 'Ether';
  try { return new Intl.DisplayNames([lang], {type: 'currency'}).of(code) || code; } catch { return code; }
}

/** Locale-neutral decimal string for form inputs (no grouping, '.' decimal point). */
export function plain(value, currency) {
  try {
    const n = BigInt(String(value)), d = decimalsOf(currency);
    const s = (n < 0n ? -n : n).toString().padStart(d + 1, '0');
    const frac = d ? s.slice(-d).replace(/0+$/, '') : '';
    return (n < 0n ? '-' : '') + (d ? s.slice(0, -d) : s) + (frac ? '.' + frac : '');
  } catch { return ''; }
}
