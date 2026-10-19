import {reduced} from './motion.js';

const NS = 'http://www.w3.org/2000/svg';
const el = (name, attrs = {}, parent) => {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  parent?.appendChild(node);
  return node;
};

/** Interactive line chart. Wheel/pinch zooms the time axis, drag pans, hover reads values, double-click resets. */
export function lineChart(host, series, {format = v => v, dateFormat = d => d, forecast = null, label = ''} = {}) {
  host.textContent = '';
  if (!series?.length) return;
  const W = 760, H = 280, P = {l: 8, r: 64, t: 18, b: 30};
  const svg = el('svg', {viewBox: `0 0 ${W} ${H}`, class: 'chart', role: 'img', 'aria-label': label}, host);
  const values = series.map(s => Number(s.rate));
  const extra = forecast ? Math.max(3, Math.round(series.length * .08)) : 0;
  const total = series.length - 1 + extra;
  let lo = 0, hi = total;
  const defs = el('defs', {}, svg);
  const grad = el('linearGradient', {id: 'area-fill', x1: 0, y1: 0, x2: 0, y2: 1}, defs);
  el('stop', {offset: '0%', 'stop-color': 'currentColor', 'stop-opacity': '.12'}, grad);
  el('stop', {offset: '100%', 'stop-color': 'currentColor', 'stop-opacity': '0'}, grad);
  const clip = el('clipPath', {id: 'plot-clip'}, defs);
  el('rect', {x: P.l, y: 0, width: W - P.l - P.r, height: H}, clip);
  const grid = el('g', {class: 'chart-grid'}, svg);
  const plot = el('g', {'clip-path': 'url(#plot-clip)'}, svg);
  const cone = el('path', {class: 'chart-cone'}, plot);
  const area = el('path', {class: 'chart-area', fill: 'url(#area-fill)'}, plot);
  const line = el('path', {class: 'chart-line'}, plot);
  const fline = el('path', {class: 'chart-forecast'}, plot);
  const avgLine = el('line', {class: 'chart-avg'}, plot);
  const axis = el('g', {class: 'chart-axis'}, svg);
  const cross = el('g', {class: 'chart-cross', opacity: 0}, svg);
  const vline = el('line', {y1: P.t, y2: H - P.b}, cross);
  const dot = el('circle', {r: 4.5}, cross);
  const ring = el('circle', {r: 10, class: 'ring'}, cross);
  const tip = el('g', {class: 'chart-tip'}, cross);
  const tipBg = el('rect', {rx: 8, height: 40, width: 120}, tip);
  const tipA = el('text', {x: 10, y: 17}, tip);
  const tipB = el('text', {x: 10, y: 32, class: 'muted'}, tip);

  function draw() {
    const i0 = Math.max(0, Math.floor(lo)), i1 = Math.min(series.length - 1, Math.ceil(hi));
    const visible = values.slice(i0, i1 + 1);
    let min = Math.min(...visible), max = Math.max(...visible);
    if (forecast && hi > series.length - 1) {
      min = Math.min(min, Number(forecast.interval_80[0])); max = Math.max(max, Number(forecast.interval_80[1]));
    }
    const pad = (max - min) * .12 || max * .002 || 1;
    min -= pad; max += pad;
    const x = i => P.l + (i - lo) / (hi - lo) * (W - P.l - P.r);
    const y = v => P.t + (1 - (v - min) / (max - min)) * (H - P.t - P.b);
    const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    line.setAttribute('d', 'M' + pts.join('L'));
    area.setAttribute('d', `M${x(0)},${H - P.b}L${pts.join('L')}L${x(values.length - 1)},${H - P.b}Z`);
    const avg = visible.reduce((a, b) => a + b, 0) / visible.length;
    avgLine.setAttribute('x1', P.l); avgLine.setAttribute('x2', W - P.r);
    avgLine.setAttribute('y1', y(avg)); avgLine.setAttribute('y2', y(avg));
    if (forecast) {
      const last = values.length - 1, end = total;
      const [a, b] = forecast.interval_80.map(Number);
      fline.setAttribute('d', `M${x(last)},${y(values[last])}L${x(end)},${y(Number(forecast.point))}`);
      cone.setAttribute('d', `M${x(last)},${y(values[last])}L${x(end)},${y(b)}L${x(end)},${y(a)}Z`);
    }
    grid.textContent = ''; axis.textContent = '';
    for (let k = 0; k <= 3; k++) {
      const v = min + (max - min) * (k + .5) / 4, yy = y(v);
      el('line', {x1: P.l, x2: W - P.r, y1: yy, y2: yy}, grid);
      el('text', {x: W - P.r + 10, y: yy + 4}, axis).textContent = format(v);
    }
    const ticks = 4;
    for (let k = 0; k <= ticks; k++) {
      const i = Math.round(lo + (hi - lo) * k / ticks);
      if (i < 0 || i > series.length - 1) continue;
      el('text', {x: x(i), y: H - 8, 'text-anchor': k === 0 ? 'start' : k === ticks ? 'end' : 'middle'}, axis).textContent = dateFormat(series[i].date);
    }
    return {x, y};
  }
  let scale = draw();
  if (!reduced() && !document.documentElement.dataset.quiet) {
    const len = line.getTotalLength?.() || 1000;
    line.style.strokeDasharray = len; line.style.strokeDashoffset = len;
    line.getBoundingClientRect();
    line.style.transition = 'stroke-dashoffset 1.2s cubic-bezier(.16,1,.3,1)';
    line.style.strokeDashoffset = 0;
    setTimeout(() => { line.style.strokeDasharray = ''; line.style.transition = ''; }, 1300);
  }
  const toLocal = e => { const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; return p.matrixTransform(svg.getScreenCTM().inverse()); };
  const indexAt = px => lo + (px - P.l) / (W - P.l - P.r) * (hi - lo);
  function hover(e) {
    const p = toLocal(e);
    const i = Math.max(0, Math.min(series.length - 1, Math.round(indexAt(p.x))));
    const cx = scale.x(i), cy = scale.y(values[i]);
    cross.setAttribute('opacity', 1);
    vline.setAttribute('x1', cx); vline.setAttribute('x2', cx);
    dot.setAttribute('cx', cx); dot.setAttribute('cy', cy); ring.setAttribute('cx', cx); ring.setAttribute('cy', cy);
    tipA.textContent = format(values[i]); tipB.textContent = dateFormat(series[i].date);
    const width = Math.max(tipA.getComputedTextLength?.() || 60, tipB.getComputedTextLength?.() || 60) + 20;
    tipBg.setAttribute('width', width);
    const tx = cx + 14 + width > W - P.r ? cx - 14 - width : cx + 14;
    tip.setAttribute('transform', `translate(${tx} ${Math.max(P.t, Math.min(H - P.b - 40, cy - 48))})`);
  }
  const pointers = new Map();
  let drag = null, pinch = null;
  svg.addEventListener('pointermove', e => {
    if (pointers.has(e.pointerId)) {
      pointers.set(e.pointerId, e.clientX);
      if (pinch && pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        const span = Math.max(6, Math.min(total, pinch.span * pinch.d / Math.max(10, Math.abs(a - b))));
        lo = Math.max(0, pinch.c - span / 2); hi = Math.min(total, lo + span); lo = Math.max(0, hi - span);
        scale = draw();
      } else if (drag) {
        const shift = (toLocal(e).x - drag.x) / (W - P.l - P.r) * (hi - lo);
        const span = hi - lo;
        lo = Math.max(0, Math.min(total - span, drag.lo - shift)); hi = lo + span;
        scale = draw();
      }
    }
    hover(e);
  });
  svg.addEventListener('pointerdown', e => {
    svg.setPointerCapture(e.pointerId); pointers.set(e.pointerId, e.clientX);
    if (pointers.size === 1) drag = {x: toLocal(e).x, lo};
    if (pointers.size === 2) { const [a, b] = [...pointers.values()]; pinch = {d: Math.abs(a - b), span: hi - lo, c: (lo + hi) / 2}; drag = null; }
    svg.classList.add('grabbing');
  });
  const up = e => { pointers.delete(e.pointerId); if (pointers.size < 2) pinch = null; if (!pointers.size) { drag = null; svg.classList.remove('grabbing'); } };
  svg.addEventListener('pointerup', up); svg.addEventListener('pointercancel', up);
  svg.addEventListener('pointerleave', () => cross.setAttribute('opacity', 0));
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    const at = indexAt(toLocal(e).x), span = Math.max(6, Math.min(total, (hi - lo) * Math.exp(e.deltaY * .0018)));
    const k = (at - lo) / (hi - lo);
    lo = Math.max(0, at - span * k); hi = Math.min(total, lo + span); lo = Math.max(0, hi - span);
    scale = draw(); hover(e);
  }, {passive: false});
  svg.addEventListener('dblclick', () => { lo = 0; hi = total; scale = draw(); });
  return {reset: () => { lo = 0; hi = total; scale = draw(); }, zoom: f => {
    const c = (lo + hi) / 2, span = Math.max(6, Math.min(total, (hi - lo) * f));
    lo = Math.max(0, c - span / 2); hi = Math.min(total, lo + span); lo = Math.max(0, hi - span); scale = draw();
  }};
}

export function sparkline(series, w = 220, h = 56) {
  if (!series?.length) return '';
  const v = series.map(s => Number(s.rate)), min = Math.min(...v), max = Math.max(...v), r = max - min || 1;
  const pts = v.map((n, i) => `${(i / Math.max(1, v.length - 1) * (w - 8) + 4).toFixed(1)},${(h - 6 - (n - min) / r * (h - 14)).toFixed(1)}`);
  const last = pts.at(-1).split(',');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true"><path class="spark-area" d="M4 ${h} L${pts.join(' L')} L${w - 4} ${h}Z"/><polyline class="spark-line" points="${pts.join(' ')}"/><circle cx="${last[0]}" cy="${last[1]}" r="3"/><circle class="spark-ping" cx="${last[0]}" cy="${last[1]}" r="3"/></svg>`;
}

/** Circular gauge; value 0-100. Pure SVG attributes (CSP-safe). */
export function gauge(value, {size = 120, stroke = 7, label = '', sub = ''} = {}) {
  const r = (size - stroke) / 2 - 4, c = 2 * Math.PI * r, v = Math.max(0, Math.min(100, Number(value) || 0));
  const ticks = Array.from({length: 40}, (_, i) => {
    const a = i / 40 * 2 * Math.PI - Math.PI / 2, r1 = r + stroke / 2 + 3, r2 = r1 + (i % 5 ? 2 : 4);
    return `<line x1="${(size / 2 + Math.cos(a) * r1).toFixed(1)}" y1="${(size / 2 + Math.sin(a) * r1).toFixed(1)}" x2="${(size / 2 + Math.cos(a) * r2).toFixed(1)}" y2="${(size / 2 + Math.sin(a) * r2).toFixed(1)}"/>`;
  }).join('');
  return `<svg class="gauge" viewBox="0 0 ${size + 16} ${size + 16}" role="img" aria-label="${label} ${v.toFixed(0)}"><g transform="translate(8 8)"><g class="gauge-ticks">${ticks}</g><circle class="gauge-track" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke-width="${stroke}"/><circle class="gauge-value" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke-width="${stroke}" stroke-dasharray="${c.toFixed(2)}" stroke-dashoffset="${(c * (1 - v / 100)).toFixed(2)}" transform="rotate(-90 ${size / 2} ${size / 2})" data-length="${c.toFixed(2)}"/><text x="${size / 2}" y="${size / 2 + 2}" text-anchor="middle" class="gauge-label">${label}</text><text x="${size / 2}" y="${size / 2 + 20}" text-anchor="middle" class="gauge-sub">${sub}</text></g></svg>`;
}

/** Animates gauges from empty when they mount. */
export function animateGauges(root) {
  if (reduced() || document.documentElement.dataset.quiet) return;
  root.querySelectorAll('.gauge-value:not([data-done])').forEach(c => {
    c.dataset.done = 1;
    const target = c.getAttribute('stroke-dashoffset');
    c.style.strokeDashoffset = c.dataset.length;
    c.getBoundingClientRect();
    c.style.transition = 'stroke-dashoffset 1.1s cubic-bezier(.16,1,.3,1)';
    requestAnimationFrame(() => requestAnimationFrame(() => { c.style.strokeDashoffset = target; }));
  });
}

/** Forecast picture: recent actual rate, past model predictions (backtest dots with error lines), and the 7-day fan. */
export function forecastChart(host, f, {format = v => v, dateFormat = d => d, labels = {}} = {}) {
  host.textContent = '';
  if (!f?.available || !f.recent?.length) return;
  const W = 760, H = 300, P = {l: 8, r: 112, t: 24, b: 32};
  const day = 86400000, ts = d => Date.parse(d + 'T00:00:00Z');
  const all_ = f.recent.map(r => ({t: ts(r.date), v: Number(r.rate), date: r.date}));
  const cut = all_.at(-1).t, end = cut + f.horizon_days * day, t1 = end;
  const recent = all_.filter(r => r.t >= cut - 56 * day);  // true time scale: last 8 weeks + the 7-day horizon
  const t0 = recent[0].t;
  const checks = (f.backtest || []).map(b => ({t: ts(b.date), a: Number(b.actual), p: Number(b.predicted), date: b.date})).filter(b => b.t >= t0);
  const [lo, hi] = f.interval_80.map(Number), point = Number(f.point), base = Number(f.baseline_point);
  const all = [...recent.map(r => r.v), ...checks.map(c => c.p), lo, hi];
  let min = Math.min(...all), max = Math.max(...all);
  const pad = (max - min) * .12 || max * .002; min -= pad; max += pad;
  const x = t => P.l + (t - t0) / (t1 - t0) * (W - P.l - P.r);
  const y = v => P.t + (1 - (v - min) / (max - min)) * (H - P.t - P.b);
  const svg = el('svg', {viewBox: `0 0 ${W} ${H}`, class: 'chart fchart', role: 'img', 'aria-label': labels.aria || ''}, host);
  const defs = el('defs', {}, svg);
  const g = el('linearGradient', {id: 'fan-fill', x1: 0, y1: 0, x2: 1, y2: 0}, defs);
  el('stop', {offset: '0%', 'stop-color': 'currentColor', 'stop-opacity': '.05'}, g);
  el('stop', {offset: '100%', 'stop-color': 'currentColor', 'stop-opacity': '.18'}, g);
  const grid = el('g', {class: 'chart-grid'}, svg), axis = el('g', {class: 'chart-axis'}, svg);
  for (let k = 0; k <= 3; k++) {
    const v = min + (max - min) * (k + .5) / 4;
    el('line', {x1: P.l, x2: W - P.r, y1: y(v), y2: y(v)}, grid);
  }
  el('rect', {x: x(cut), y: P.t - 6, width: x(end) - x(cut), height: H - P.t - P.b + 6, class: 'future-zone'}, svg);
  el('line', {x1: x(cut), x2: x(cut), y1: P.t - 12, y2: H - P.b, class: 'cutoff'}, svg);
  el('text', {x: x(cut) - 6, y: P.t - 12, 'text-anchor': 'end', class: 'fc-label'}, svg).textContent = labels.cutoff || 'data cutoff';
  el('text', {x: (x(cut) + x(end)) / 2, y: P.t - 12, 'text-anchor': 'middle', class: 'fc-label'}, svg).textContent = labels.horizon || '+7d';
  [[t0, 'start'], [cut, 'end'], [end, 'start']].forEach(([t, a]) => {
    el('text', {x: x(t) + (a === 'start' && t !== t0 ? 4 : a === 'end' ? -4 : 0), y: H - 10, 'text-anchor': a}, axis).textContent = dateFormat(new Date(t).toISOString().slice(0, 10));
  });
  // Backtest: what the model predicted for each past date versus what actually happened.
  const errs = el('g', {class: 'fc-errors'}, svg);
  checks.forEach(c => {
    el('line', {x1: x(c.t), x2: x(c.t), y1: y(c.a), y2: y(c.p), class: 'fc-err'}, errs);
    el('circle', {cx: x(c.t), cy: y(c.p), r: 2.6, class: 'fc-pred'}, errs);
  });
  const line = el('path', {class: 'chart-line', d: 'M' + recent.map(r => `${x(r.t).toFixed(1)},${y(r.v).toFixed(1)}`).join('L')}, svg);
  const last = recent.at(-1), fan = el('g', {class: 'fc-fan'}, svg);
  el('path', {d: `M${x(cut)},${y(last.v)}L${x(end)},${y(hi)}L${x(end)},${y(lo)}Z`, fill: 'url(#fan-fill)', class: 'fc-cone'}, fan);
  el('line', {x1: x(cut), y1: y(last.v), x2: x(end), y2: y(base), class: 'fc-base'}, fan);
  el('line', {x1: x(cut), y1: y(last.v), x2: x(end), y2: y(point), class: 'chart-forecast'}, fan);
  const tags = [[hi, labels.high || '90%', 'fc-bound'], [point, labels.point || 'model', 'fc-point'], [lo, labels.low || '10%', 'fc-bound']];
  if (Math.abs(y(base) - y(point)) > 12 && Math.abs(y(base) - y(hi)) > 12 && Math.abs(y(base) - y(lo)) > 12) tags.push([base, labels.baseline || 'baseline', 'fc-base-dot']);
  tags.forEach(([v, name, cls]) => {
    el('circle', {cx: x(end), cy: y(v), r: cls === 'fc-point' ? 4.5 : 3, class: cls}, fan);
    el('text', {x: x(end) + 10, y: y(v) + 4, class: 'fc-value ' + (cls === 'fc-point' ? 'strong' : cls === 'fc-base-dot' ? 'muted' : '')}, fan).textContent = `${format(v)} · ${name}`;
  });
  el('circle', {cx: x(cut), cy: y(last.v), r: 4, class: 'fc-today'}, svg);
  // Hover: date, actual rate, and the model's backtest prediction for that date when there is one.
  const cross = el('g', {class: 'chart-cross', opacity: 0}, svg);
  const vline = el('line', {y1: P.t, y2: H - P.b}, cross), dot = el('circle', {r: 4}, cross);
  const tip = el('g', {class: 'chart-tip'}, cross), bg = el('rect', {rx: 8, height: 40, width: 150}, tip);
  const ta = el('text', {x: 10, y: 17}, tip), tb = el('text', {x: 10, y: 32, class: 'muted'}, tip);
  svg.addEventListener('pointermove', e => {
    const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
    const px = pt.matrixTransform(svg.getScreenCTM().inverse()).x;
    const r = recent.reduce((b, c) => Math.abs(x(c.t) - px) < Math.abs(x(b.t) - px) ? c : b);
    const c = checks.find(k => k.date === r.date);
    cross.setAttribute('opacity', 1);
    vline.setAttribute('x1', x(r.t)); vline.setAttribute('x2', x(r.t)); dot.setAttribute('cx', x(r.t)); dot.setAttribute('cy', y(r.v));
    ta.textContent = `${format(r.v)}${c ? ` · ${labels.predicted || 'predicted'} ${format(c.p)}` : ''}`;
    tb.textContent = dateFormat(r.date);
    const w = Math.max(ta.getComputedTextLength?.() || 80, tb.getComputedTextLength?.() || 80) + 20;
    bg.setAttribute('width', w);
    tip.setAttribute('transform', `translate(${x(r.t) + 14 + w > W - P.r ? x(r.t) - 14 - w : x(r.t) + 14} ${Math.max(P.t, y(r.v) - 50)})`);
  });
  svg.addEventListener('pointerleave', () => cross.setAttribute('opacity', 0));
  if (!reduced() && !document.documentElement.dataset.quiet) {
    const len = line.getTotalLength?.() || 1000;
    line.style.strokeDasharray = len; line.style.strokeDashoffset = len; line.getBoundingClientRect();
    line.style.transition = 'stroke-dashoffset 1.1s cubic-bezier(.16,1,.3,1)'; line.style.strokeDashoffset = 0;
    fan.style.transformOrigin = `${x(cut)}px ${y(last.v)}px`; fan.style.transformBox = 'view-box';
    fan.animate([{transform: 'scaleX(0)', opacity: 0}, {transform: 'scaleX(1)', opacity: 1}], {duration: 900, delay: 700, easing: 'cubic-bezier(.16,1,.3,1)', fill: 'backwards'});
    errs.animate([{opacity: 0}, {opacity: 1}], {duration: 600, delay: 1000, fill: 'backwards'});
  }
}
