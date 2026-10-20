import {state, t, api, toast, isOwner, invalidate, rerender, refreshView, value, modal, closeModal} from '../core.js';
import {esc, amt, tag, panel, field, options, segmented, icons, empty, dl, chip} from '../ui.js';
import {num, day, pct, when, currencyName, phrase} from '../i18n.js';
import {alertText} from './send.js';
import {bankPanel, loadBanks, banksFor, bankName} from './banks.js';
import {lineChart, forecastChart, gauge, animateGauges} from '../charts.js';

/* ---------- the decision card: where today sits, what waiting may cost or gain in your money, rules acted on later ---------- */
const signed = (v, cur) => `${Number(v) > 0 ? '+' : Number(v) < 0 ? '−' : ''}${num(Math.abs(Number(v)), 0)} ${esc(cur)}`;

function waitHtml() {
  const w = state.data.wait, m = state.markets;
  if (!w) return `<p class="fine">${t('common.loading')}</p>`;
  if (w.error) return `<p class="note warn">${esc(w.error)}</p>`;
  const pos = w.position_pct != null ? `<p class="decide-pos">${t(w.position_basis === 'bank' ? 'decide.pos_bank' : 'decide.pos', {p: w.position_pct, d: w.position_days})}</p>` : '';
  if (!w.available) return `${pos}<p class="fine">${t('decide.no_forecast')}</p>`;
  const lean = w.p_better >= 56 ? 'wait' : w.p_better <= 44 ? 'now' : 'even';
  return `${pos}
    <div class="decide-wait k-${lean}"><span class="decide-p">${w.p_better}<small>%</small></span>
      <div><b>${t('decide.wait', {d: day(w.horizon), p: w.p_better})}</b>
        <small>${t('decide.range', {e: signed(w.expected, w.unit), lo: signed(w.worst, w.unit), hi: signed(w.best, w.unit)})}</small>
        <small class="decide-lean">${t('decide.lean_' + lean)}</small></div></div>
    ${w.beats_baseline ? '' : `<p class="note">${t('decide.weak')}</p>`}
    ${w.can_wait === false ? `<p class="note warn">${t('decide.no_time', {d: day(w.latest_start)})}</p>` : ''}
    <p class="fine">${t('decide.basis', {r: num(w.rate_now, 4), b: w.rate_basis === 'bank' ? bankName((banksFor(m.source, m.target) || []).find(x => x.id === w.bank)) : t('decide.reference')})}</p>`;
}

function rulesHtml() {
  const m = state.markets, list = (state.data.fxRules || []).filter(r => r.source === m.source && r.target === m.target && r.status !== 'cancelled');
  if (!list.length) return '';
  return `<ul class="list rule-list">${list.map(r => {
    const res = r.result, saved = res?.saved?.saved;
    return `<li class="row rule-${esc(r.status)}"><span class="state-dot"></span>
      <div><b>${t('rule.line', {a: num(r.amount / 10 ** (r.source === 'JPY' || r.source === 'KRW' || r.source === 'VND' ? 0 : 2), 0), s: esc(r.source), r: num(r.min_rate, 4), t: esc(r.target)})}</b>
        <small>${t('rule.mode_' + r.mode)}${r.due ? ' · ' + t('rule.by', {d: day(r.due)}) : ''} · ${t('rule.st_' + r.status)}${res ? ' · ' + t('rule.done_at', {r: num(res.rate, 4)}) : ''}</small>
        ${saved && Number(saved) > 0 ? `<small class="rule-saved">${t('rule.saved', {a: num(saved, 0), c: esc(r.source)})}</small>` : ''}</div>
      <span class="row-actions">${r.status === 'triggered' ? `<button class="button sm primary" data-action="rule-run" data-id="${esc(r.id)}">${t('rule.run')}</button>` : ''}
        ${['active', 'triggered'].includes(r.status) ? `<button class="link sm" data-action="rule-cancel" data-id="${esc(r.id)}">${t('common.cancel')}</button>` : ''}
        ${saved && Number(saved) > 0 ? `<button class="link sm" data-action="rule-share" data-id="${esc(r.id)}">${t('rule.share')}</button>` : ''}</span></li>`;
  }).join('')}</ul>`;
}

function decideCard(l) {
  const m = state.markets, banks = (banksFor(m.source, m.target) || []).filter(b => b.pricing?.status === 'ok' && b.pricing?.rate && b.sides?.length);
  const facts = l ? `<details class="facts-more"><summary>${t('decide.facts')}</summary>${dl([[t('markets.source'), esc(l.provider)], [t('markets.observed'), day(l.observed)],
    [t('markets.frequency'), esc(phrase(l.frequency))], [t('markets.retrieved'), when(Date.parse(l.retrieved_at) / 1000)], [t('markets.derivation'), `<small>${esc(phrase(l.derivation))}</small>`]])}</details>` : '';
  return `<div class="decide">
    <div class="latest-rate"><strong>${l ? num(l.rate, 4) : '—'}</strong><span>${esc(m.target)} / 1 ${esc(m.source)}</span>${l?.change_pct ? `<small class="change ${Number(l.change) >= 0 ? 'up' : 'down'}">${pct(l.change_pct, 2)}</small>` : ''}</div>
    <form id="decide-form" class="decide-form" autocomplete="off">
      <label><small>${t('decide.amount', {c: esc(m.source)})}</small><input name="amount" inputmode="decimal" value="${esc(m.waitAmount)}"></label>
      <label><small>${t('decide.bank')}</small><select name="bank"><option value="">${t('decide.reference')}</option>${options(banks.map(b => [b.id, bankName(b)]), m.waitBank || '')}</select></label>
    </form>
    <div id="decide-out">${waitHtml()}</div>
    <div class="decide-actions"><button class="button primary" data-action="rule-new" ${isOwner() ? '' : 'disabled'}>${icons.plus}${t('rule.new')}</button>
      <button class="button ghost" data-action="go" data-view="send">${t('decide.to_send')} ${icons.arrow}</button></div>
    <div id="rules-out">${rulesHtml()}</div>
    ${facts}
  </div>`;
}

let waitTimer = 0;
async function loadWait() {
  const m = state.markets;
  const q = new URLSearchParams({source: m.source, target: m.target, amount: m.waitAmount || '10000', side: 'spend'});
  if (m.waitBank) q.set('bank', m.waitBank);
  try { state.data.wait = await api('/decide/wait?' + q); } catch (e) { state.data.wait = {error: e.message}; }
  const box = document.getElementById('decide-out');
  if (box) box.innerHTML = waitHtml();
}

function ruleForm() {
  const m = state.markets, now = Number(state.data.latest?.rate || state.data.wait?.rate_now || 0);
  const banks = (banksFor(m.source, m.target) || []).filter(b => b.pricing?.status === 'ok' && b.pricing?.rate && b.sides?.length);
  modal(t('rule.title'), `<form id="rule-form" class="form-block" autocomplete="off">
    <p class="fine">${t('rule.intro', {s: esc(m.source), t: esc(m.target)})}</p>
    <div class="grid-2">${field('rl-amount', t('rule.amount', {c: esc(m.source)}), `<input id="rl-amount" name="amount" inputmode="decimal" required value="${esc(m.waitAmount)}">`)}
      ${field('rl-rate', t('rule.rate', {s: esc(m.source), t: esc(m.target)}), `<input id="rl-rate" name="min_rate" inputmode="decimal" required value="${now ? (now * 1.003).toFixed(4) : ''}">`, t('rule.rate_hint', {r: num(now, 4)}))}</div>
    <div class="grid-2">${field('rl-due', t('rule.due'), `<input id="rl-due" name="due" type="date">`, t('rule.due_hint'))}
      ${field('rl-mode', t('rule.mode'), `<select id="rl-mode" name="mode">${options([['confirm', t('rule.mode_confirm')], ['auto', t('rule.mode_auto')]], 'confirm')}</select>`, t('rule.mode_hint'))}</div>
    ${banks.length ? field('rl-bank', t('decide.bank'), `<select id="rl-bank" name="bank"><option value="">${t('decide.reference')}</option>${options(banks.map(b => [b.id, bankName(b)]), m.waitBank || '')}</select>`) : ''}
    <p class="fine">${t('rule.safety')}</p>
    <div class="form-error"></div><div class="modal-actions"><button class="button primary">${t('rule.save')} ${icons.arrow}</button></div></form>`, 'RULE');
}

/** The target-rate reminder: pick what to watch, then one input and one button. */
function alertsBody(l) {
  const m = state.markets, cond = m.alertCond || 'above';
  const alerts = (state.data.alerts || []).filter(a => a.source === m.source && a.target === m.target);
  const input = cond === 'date'
    ? `<input id="al-due" name="due" type="date" required aria-label="${t('rem.date')}">`
    : `<span class="al-input"><input id="al-th" name="threshold" inputmode="decimal" ${cond === 'percentile' ? 'value="80"' : `placeholder="${esc(l?.rate ? num(l.rate, 4) : '')}"`} aria-label="${t('markets.threshold')}" required>
        <small>${cond === 'percentile' ? t('markets.al_pct_unit') : `${esc(m.target)} / 1 ${esc(m.source)}`}</small></span>`;
  return `${segmented('al-cond', [['above', t('markets.above')], ['below', t('markets.below')], ['percentile', t('rem.favorable')], ['date', t('rem.date')]], cond, 'alert-cond')}
    <form id="alert-form" class="alert-form"><input type="hidden" name="condition" value="${cond}">
      <div class="al-row">${input}<button class="button primary" ${isOwner() ? '' : 'disabled'}>${icons.plus}${t('markets.add_alert')}</button></div>
      <small class="fine">${t('markets.al_hint.' + cond, {s: m.source, t: m.target})}</small><div class="form-error"></div></form>
    ${alerts.length ? `<ul class="list al-list">${alerts.map(a => `<li class="row"><div><b>${esc(alertText(a))}</b><small>${a.last_rate ? t('markets.last_checked', {r: num(a.last_rate, 6), at: when(a.last_checked)}) : t('markets.not_checked')}${a.triggered_at ? ' · ' + t('markets.triggered', {at: when(a.triggered_at)}) : ''}</small></div><button class="pill ${a.active ? 'on' : ''}" data-action="toggle-alert" data-id="${esc(a.id)}" data-active="${a.active ? 0 : 1}" ${isOwner() ? '' : 'disabled'}>${a.active ? t('markets.armed') : t('markets.rearm')}</button></li>`).join('')}</ul>` : `<p class="fine">${t('markets.no_alerts')}</p>`}
    <p class="fine">${t('markets.alert_note')}</p>`;
}

const CURRENCIES = ['AUD', 'USD', 'CNY', 'VND', 'PHP', 'MXN', 'JPY', 'KRW', 'HKD', 'TWD', 'SGD', 'NZD', 'CAD', 'MYR', 'THB', 'IDR', 'CLP', 'PEN', 'EUR', 'GBP'];
let chart = null, scenarioTimer = 0;

export const view = {
  id: 'markets',
  needs: ['alerts', 'balances'],
  async load() {
    const m = state.markets, key = `${m.source}-${m.target}-${m.days}`;
    await loadBanks(m.source, m.target);
    m.waitAmount ??= '10000';
    try { state.data.fxRules = await api('/fx-rules'); } catch { state.data.fxRules = []; }
    loadWait();
    if (state.data.marketKey === key && state.data.history) return;
    state.data.marketKey = key;
    const results = await Promise.allSettled([
      api(`/rates?source=${m.source}&target=${m.target}&days=${m.days}`),
      api(`/rates/latest?source=${m.source}&target=${m.target}`),
      api(`/rates/forecast?source=${m.source}&target=${m.target}`),
    ]);
    [state.data.history, state.data.latest, state.data.forecast] = results.map(r => r.status === 'fulfilled' ? r.value : null);
    state.errors.history = results[0].status === 'rejected' ? results[0].reason.message : null;
    state.data.scenario = null;
    runScenario(0);
  },
  render() {
    const m = state.markets, h = state.data.history, l = state.data.latest, f = state.data.forecast;
    const picker = `<div class="pair-picker reveal">
      <label class="pair-select"><span>${t('markets.from')}</span><select data-pair="source">${CURRENCIES.map(c => `<option value="${esc(c)}" ${c === m.source ? 'selected' : ''} ${c === m.target ? 'disabled' : ''}>${esc(c)}</option>`).join('')}</select><small>${esc(currencyName(m.source))}</small></label>
      <button class="swap" data-action="swap-pair" aria-label="${t('markets.swap')}">${icons.swap}</button>
      <label class="pair-select"><span>${t('markets.to')}</span><select data-pair="target">${CURRENCIES.map(c => `<option value="${esc(c)}" ${c === m.target ? 'selected' : ''} ${c === m.source ? 'disabled' : ''}>${esc(c)}</option>`).join('')}</select><small>${esc(currencyName(m.target))}</small></label>
      ${segmented('days', [['30', '30D'], ['90', '90D'], ['365', '1Y']], m.days, 'market-days')}
    </div>`;
    if (!h) return picker + panel(t('markets.title'), `<div class="rate-error">${esc(state.errors.history || t('common.loading'))}</div><p class="fine">${t('markets.no_invent')}</p>`);
    const sending = m.direction === 'send';
    const favorableNow = sending ? h.position === 'high' : h.position === 'low';
    const latest = l ? `<div class="latest">
        <span class="eyebrow">${tag('reference')}</span>
        <div class="latest-rate"><strong data-count="${Number(l.rate)}" data-digits="4">${num(l.rate, 6)}</strong><span>${esc(m.target)} / 1 ${esc(m.source)}</span></div>
        <div class="change ${Number(l.change) >= 0 ? 'up' : 'down'}">${l.change_pct ? pct(l.change_pct, 3) : '—'} <small>${t('markets.vs_prev')}</small></div>
        ${dl([[t('markets.source'), esc(l.provider)], [t('markets.observed'), day(l.observed)], [t('markets.frequency'), esc(phrase(l.frequency))],
          [t('markets.retrieved'), when(Date.parse(l.retrieved_at) / 1000)], [t('markets.derivation'), `<small>${esc(phrase(l.derivation))}</small>`]])}
      </div>` : '';
    const stats = `<div class="stat-grid">
      <div class="gauge-box">${gauge(Number(h.percentile), {size: 132, label: num(h.percentile, 0), sub: t('rates.percentile')})}</div>
      ${dl([[t('markets.min'), num(h.minimum, 6)], [t('markets.max'), num(h.maximum, 6)], [t('markets.avg'), num(h.average, 6)],
        [t('markets.trend'), pct(h.trend_pct, 2)], [t('markets.position'), t('rates.position.' + h.position)],
        [t('markets.coverage'), `${h.observations} ${t('rates.obs')} · ${num(h.coverage_pct, 0)}%`], [t('markets.window'), `${day(h.first)} – ${day(h.last)}`]])}
      <div class="flags">${h.new_high ? `<span class="flag">${t('markets.new_high')}</span>` : ''}${h.new_low ? `<span class="flag">${t('markets.new_low')}</span>` : ''}${h.near_high && !h.new_high ? `<span class="flag">${t('markets.near_high')}</span>` : ''}${h.near_low && !h.new_low ? `<span class="flag">${t('markets.near_low')}</span>` : ''}</div>
    </div>
    <div class="direction">${segmented('direction', [['send', t('markets.dir_send', {s: m.source, t: m.target})], ['receive', t('markets.dir_receive', {s: m.target, t: m.source})]], m.direction, 'market-direction')}
      <p class="interpret ${favorableNow ? 'good' : ''}">${t(sending ? 'markets.read_send' : 'markets.read_receive', {s: m.source, t: m.target, pos: t('rates.position.' + h.position), p: num(h.percentile, 0), d: m.days})}</p>
      <p class="fine">${t('markets.percentile_note')}</p></div>`;
    const forecast = !f ? '' : f.available ? `<div class="forecast">
        <div class="forecast-head">${tag('forecast')}<span class="fine">${t('markets.generated')} ${when(Date.parse(f.generated_at) / 1000)} · ${t('markets.cutoff')} ${day(f.data_cutoff)} · ${t('markets.horizon', {n: f.horizon_days})}</span></div>
        <p class="fc-read">${t('markets.fc_read', {n: f.horizon_days, lo: num(f.interval_80[0], 5), hi: num(f.interval_80[1], 5), point: num(f.point, 5), base: num(f.baseline_point, 5), t: esc(m.target), s: esc(m.source)})}</p>
        <div class="chart-host no-swipe" id="forecast-chart"></div>
        <div class="fc-legend"><span><i class="lg-actual"></i>${t('markets.fc_actual')}</span><span><i class="lg-pred"></i>${t('markets.fc_past')}</span><span><i class="lg-model"></i>${t('markets.fc_model_line')}</span><span><i class="lg-base"></i>${t('markets.baseline')}</span><span><i class="lg-fan"></i>${t('markets.interval')}</span></div>
        <p class="fine">${t('markets.fc_how')}</p>
        <div class="forecast-main"><div><span class="eyebrow">${t('markets.point')}</span><b>${num(f.point, 6)}</b></div><div><span class="eyebrow">${t('markets.interval')}</span><b>${num(f.interval_80[0], 6)} – ${num(f.interval_80[1], 6)}</b></div><div><span class="eyebrow">${t('markets.baseline')}</span><b>${num(f.baseline_point, 6)}</b></div></div>
        <div class="mae"><div><span>${t('markets.model_error')}</span><i class="bar-fill" data-ratio="${(Number(f.model_mae) / Math.max(Number(f.model_mae), Number(f.baseline_mae))).toFixed(3)}"></i><b>${num(f.model_mae, 6)}</b></div>
          <div><span>${t('markets.baseline_error')}</span><i class="bar-fill" data-ratio="${(Number(f.baseline_mae) / Math.max(Number(f.model_mae), Number(f.baseline_mae))).toFixed(3)}"></i><b>${num(f.baseline_mae, 6)}</b></div></div>
        <p class="interpret ${f.beats_baseline ? '' : 'warn'}">${f.beats_baseline ? t('forecast.beats') : t('forecast.not_beats')} · ${t('markets.coverage_eval', {p: num(f.holdout_interval_coverage, 1), n: f.backtest_origins})}</p>
        <p class="fine">${t('markets.forecast_caveat')}</p></div>`
      : `<div class="forecast unavailable">${tag('forecast')}<p>${t('markets.forecast_unavailable')}</p><small class="muted">${esc(f.reason)}</small></div>`;
    return `${picker}
      <div class="markets-layout">
        ${panel(`${esc(m.source)} <span class="muted">→</span> ${esc(m.target)}`, `<div class="chart-host no-swipe" id="rate-chart"></div>
          <div class="chart-tools"><span class="fine">${t('markets.chart_hint')}</span><span><button class="icon-button sm" data-chart="in" aria-label="${t('common.zoom_in')}">${icons.zoomIn}</button><button class="icon-button sm" data-chart="out" aria-label="${t('common.zoom_out')}">${icons.zoomOut}</button><button class="icon-button sm" data-chart="reset" aria-label="${t('common.reset')}">${icons.reset}</button></span></div>
          <div class="legend-row"><span class="lg-line"></span>${t('markets.legend_ref')}<span class="lg-avg"></span>${t('markets.avg')}${f?.available ? `<span class="lg-cone"></span>${t('markets.legend_forecast')}` : ''}</div>`, {cls: 'chart-panel'})}
        ${panel(t('decide.title'), decideCard(l), {cls: 'decide-panel'})}
      </div>
      <div class="markets-layout">
        ${panel(t('markets.forecast'), forecast, {cls: 'forecast-panel'})}
        ${panel(t('markets.analysis'), stats, {cls: 'analysis-panel'})}
      </div>
      <div class="markets-layout">
        ${panel(t('markets.scenario'), `<form id="scenario-form" class="scenario"><div class="grid-2">${field('sc-amount', t('send.amount') + ' (' + esc(m.source) + ')', `<input id="sc-amount" name="amount" inputmode="decimal" value="${esc(m.scenarioAmount)}">`)}
            <div class="field"><label for="sc-change">${t('markets.rate_change')} <b id="sc-out">${pct(m.scenario, 1)}</b></label><input id="sc-change" name="change" type="range" min="-10" max="10" step="0.5" value="${esc(m.scenario)}"></div></div></form>
          <div id="scenario-out">${scenarioHtml()}</div>`, {cls: 'scenario-panel'})}
        ${panel(t('markets.alerts'), `<div id="alerts-body">${alertsBody(l)}</div>`, {cls: 'mk-alerts'})}
      </div>
      ${bankPanel(m.source, m.target)}`;
  },
  mount(root) {
    const h = state.data.history;
    root.querySelectorAll('select[data-pair]').forEach(sel => sel.addEventListener('change', () => {
      state.markets[sel.dataset.pair] = sel.value;
      if (state.markets.source === state.markets.target) state.markets[sel.dataset.pair === 'source' ? 'target' : 'source'] = sel.dataset.pair === 'source' ? 'CNY' : 'AUD';
      reload();
    }));
    root.querySelectorAll('.bar-fill[data-ratio]').forEach(el => el.style.setProperty('--ratio', el.dataset.ratio));
    animateGauges(root);
    const host = root.querySelector('#rate-chart');
    if (host && h) {
      const f = state.data.forecast;
      chart = lineChart(host, h.series, {format: v => num(v, 5), dateFormat: d => day(d), forecast: f?.available ? f : null,
        label: t('markets.chart_label', {s: state.markets.source, t: state.markets.target})});
      root.querySelectorAll('[data-chart]').forEach(b => b.addEventListener('click', () => ({in: () => chart.zoom(.7), out: () => chart.zoom(1.4), reset: () => chart.reset()})[b.dataset.chart]()));
    }
    const fhost = root.querySelector('#forecast-chart');
    if (fhost) forecastChart(fhost, state.data.forecast, {format: v => num(v, 5), dateFormat: d => day(d), labels: {
      cutoff: t('markets.cutoff'), horizon: t('markets.horizon', {n: state.data.forecast.horizon_days}), high: t('markets.fc_high'), low: t('markets.fc_low'),
      point: t('markets.fc_model'), baseline: t('markets.baseline'), predicted: t('markets.fc_predicted'),
      aria: t('markets.forecast')}});
    root.querySelector('#decide-form')?.addEventListener('input', e => {
      if (e.target.name === 'amount') state.markets.waitAmount = e.target.value;
      if (e.target.name === 'bank') state.markets.waitBank = e.target.value;
      clearTimeout(waitTimer); waitTimer = setTimeout(loadWait, 350);
    });
    const sc = root.querySelector('#scenario-form');
    sc?.addEventListener('input', e => {
      if (e.target.name === 'change') { state.markets.scenario = e.target.value; root.querySelector('#sc-out').textContent = pct(e.target.value, 1); }
      if (e.target.name === 'amount') state.markets.scenarioAmount = e.target.value;
      runScenario();
    });
  },
  actions: {
    'swap-pair'() { const m = state.markets; [m.source, m.target] = [m.target, m.source]; reload(); },
    'market-days'(el) { state.markets.days = el.dataset.value; reload(); },
    'market-direction'(el) { state.markets.direction = el.dataset.value; rerender(); },
    'alert-cond'(el) {  // only the reminder form changes; the charts stay as they are
      state.markets.alertCond = el.dataset.value;
      const box = document.getElementById('alerts-body');
      if (box) box.innerHTML = alertsBody(state.data.latest);
      box?.querySelector('input:not([type=hidden])')?.focus();
    },
    'rule-new'() { ruleForm(); },
    async 'rule-run'(el) {
      await api('/fx-rules/' + encodeURIComponent(el.dataset.id) + '/execute', 'POST', {});
      state.data.fxRules = await api('/fx-rules'); invalidate(['money', 'reminders']); toast(t('rule.ran'), 'good'); rerender();
    },
    async 'rule-cancel'(el) {
      state.data.fxRules = await api('/fx-rules/' + encodeURIComponent(el.dataset.id), 'DELETE'); rerender();
    },
    async 'rule-share'(el) {
      const r = (state.data.fxRules || []).find(x => x.id === el.dataset.id), res = r?.result;
      if (!res) return;
      const text = t('rule.share_text', {d: day(new Date(res.at * 1000).toISOString().slice(0, 10)), a: num(res.spent / 100, 0), s: r.source,
        b: num(res.received / 100, 2), t: r.target, x: num(res.saved?.saved || 0, 0)});
      try { await navigator.clipboard.writeText(text); toast(t('rule.copied'), 'good'); } catch { toast(text); }
    },
    async 'toggle-alert'(el) { await api('/rate-alerts/' + encodeURIComponent(el.dataset.id), 'PATCH', {active: el.dataset.active === '1'}); invalidate(['alerts']); rerender(); },
  },
  submit: {
    async 'alert-form'(f) {
      const condition = value(f, 'condition'), body = {source: state.markets.source, target: state.markets.target, condition};
      if (condition === 'date') body.due_date = value(f, 'due');
      else if (condition === 'percentile') Object.assign(body, {threshold: value(f, 'threshold') || '80', window: '90'});
      else body.threshold = value(f, 'threshold');
      await api('/rate-alerts', 'POST', body);
      invalidate(['alerts', 'reminders']); toast(t('markets.alert_added'), 'good'); rerender();
    },
    'scenario-form'() {},
    'decide-form'() {},
    async 'rule-form'(f) {
      const m = state.markets;
      await api('/fx-rules', 'POST', {source: m.source, target: m.target, amount: value(f, 'amount'), min_rate: value(f, 'min_rate'),
        due: value(f, 'due') || null, mode: value(f, 'mode'), bank: value(f, 'bank') || null});
      state.data.fxRules = await api('/fx-rules'); closeModal(); toast(t('rule.saved_toast'), 'good'); rerender();
    },
  },
};

function reload() {
  state.data.history = null; state.data.marketKey = null;
  refreshView();
}

function scenarioHtml() {
  const s = state.data.scenario, m = state.markets;
  if (!s) return `<p class="fine">${t('markets.scenario_hint')}</p>`;
  if (s.error) return `<p class="fine">${esc(s.error)}</p>`;
  return `<div class="scenario-result">
    <div><span class="eyebrow">${t('scenario.now')}</span>${amt(s.receive_now, s.target, 'lg')}</div>
    <div><span class="eyebrow">${t('scenario.then', {p: pct(s.rate_change_pct, 1)})}</span>${amt(s.receive_scenario, s.target, 'lg')}<small class="${s.receive_difference < 0 ? 'bad' : ''}">${s.receive_difference >= 0 ? '+' : ''}${amt(s.receive_difference, s.target)}</small></div>
    <div><span class="eyebrow">${t('scenario.extra')}</span>${amt(Math.max(0, s.extra_needed), s.source, 'lg')}<small>${s.shortfall ? t('scenario.shortfall', {v: amt(s.shortfall, s.source)}) : s.available !== null ? t('scenario.covered') : ''}</small></div>
  </div><p class="fine">${tag('scenario')} ${esc(phrase(s.basis))} · ${s.assumptions.map(a => esc(phrase(a))).join(' · ')}</p>`;
}

function runScenario(delay = 300) {
  clearTimeout(scenarioTimer);
  scenarioTimer = setTimeout(async () => {
    const m = state.markets;
    if (!/^\d+(\.\d+)?$/.test(m.scenarioAmount || '') || Number(m.scenarioAmount) <= 0) return;
    try { state.data.scenario = await api('/scenario', 'POST', {source: m.source, target: m.target, amount: m.scenarioAmount, rate_change_pct: String(m.scenario)}); }
    catch (e) { state.data.scenario = {error: e.message}; }
    const out = document.getElementById('scenario-out');
    if (!out) return;
    const had = out.querySelector('.scenario-result');
    out.innerHTML = scenarioHtml();
    if (had) out.querySelector('.scenario-result')?.classList.add('live');  // values change; the boxes stay put
  }, delay);
}
