/* Tactile motion, chosen per place — not every effect everywhere.

   liquid()        Liquid Tab Indicator — page tabs, segmented choices, the sidebar and the dock. One indicator moves
                   between items while the items never move. Each edge is its own under-damped spring: the leading edge
                   is stiffer, the trailing edge lags, so the shape stretches, then gathers with a slight rebound. The
                   indicator inverts what it covers (mix-blend-mode: difference), so every label stays readable even
                   mid-flight. A new click starts from the shape currently on screen. Geometry is remembered by a stable
                   key, because tabs are re-rendered after a click.
   gesturePages()  Gesture-driven Transition — swiping between pages on a phone. The page follows the finger; the
                   direction is locked after a few pixels (vertical keeps scrolling); release completes or cancels from
                   distance AND velocity; screen edges are left to the system back gesture.
   dragDismiss()   Gesture-driven Transition — closing the bottom sheet and the reminders drawer by dragging them away.
   centerFocus()   Center-focus Scaling — a horizontal row of cards on small screens: the one in the middle of the row
                   is a little larger; layout never changes, only a transform; positions are measured once per resize.
   expandFrom()    Shared-element Expansion — a dialog grows out of the card that opened it and returns to it on close
                   (or fades if that card is gone). Text appears only after the shape has arrived, never stretched.

   All of it is compositor-friendly (transform, opacity, clip-path) and goes still with prefers-reduced-motion. */

const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

/* ---------- Liquid Tab Indicator ---------- */
const liquidState = new Map();  // key -> {a, b, samples, start}
const ACTIVE = ':scope > .on, :scope > .active, :scope > [aria-selected="true"], :scope > [aria-checked="true"], :scope > .nav-group > a.active';

/** Two springs, one per edge; returns frames [[a, b], ...] at 60 fps until both settle. */
function simulate(a0, va0, b0, vb0, a1, b1) {
  const forward = a1 + b1 > a0 + b0;  // moving toward larger coordinates: b leads
  const lead = {k: .2, d: .7}, trail = {k: .085, d: .74};
  const pa = forward ? trail : lead, pb = forward ? lead : trail;
  let a = a0, b = b0, va = va0, vb = vb0;
  const out = [];
  for (let i = 0; i < 120; i++) {
    va = (va + (a1 - a) * pa.k) * pa.d; vb = (vb + (b1 - b) * pb.k) * pb.d;
    a += va; b += vb;
    if (b < a + 6) b = a + 6;  // never inside out
    out.push([a, b]);
    if (Math.abs(a1 - a) < .3 && Math.abs(b1 - b) < .3 && Math.abs(va) < .3 && Math.abs(vb) < .3) break;
  }
  out.push([a1, b1]);
  return out;
}

export function liquid(container, {axis = 'x', key = container?.id || '', extend = 0, pad = 0} = {}) {
  if (!container) return;
  key = key || container.className;
  let ind = container.querySelector(':scope > .liquid');
  if (!ind) {
    ind = document.createElement('span');
    ind.className = 'liquid';
    ind.setAttribute('aria-hidden', 'true');
    container.appendChild(ind);
  }
  container.classList.add('has-liquid');
  Object.assign(container.dataset, {liquidKey: key, liquidAxis: axis, liquidExtend: String(extend)});
  const act = container.querySelector(ACTIVE);
  if (!act) { ind.style.opacity = '0'; return; }
  ind.style.opacity = '1';
  ind.style.width = ind.style.height = '0px';  // measure the container without the indicator in it
  const W = container.scrollWidth, H = container.scrollHeight;
  ind.style.width = W + 'px'; ind.style.height = H + 'px';
  // Layout offsets, not screen boxes: a dialog that is still growing (scaled) must not distort the measurement.
  let left = act.offsetLeft, top = act.offsetTop;
  for (let el = act.offsetParent; el && el !== container && container.contains(el); el = el.offsetParent) { left += el.offsetLeft; top += el.offsetTop; }
  left -= pad;
  const r = {width: act.offsetWidth, height: act.offsetHeight};
  if (!r.width) { ind.style.opacity = '0'; return; }
  const t = axis === 'x' ? {a: left, b: left + r.width + pad * 2, c0: top, c1: top + r.height}
                         : {a: top, b: top + r.height, c0: left, c1: left + r.width + extend};
  const clip = (a, b) => axis === 'x'
    ? `inset(${t.c0.toFixed(1)}px ${(W - b).toFixed(1)}px ${(H - t.c1).toFixed(1)}px ${a.toFixed(1)}px round 999px)`
    : `inset(${a.toFixed(1)}px ${(W - t.c1).toFixed(1)}px ${(H - b).toFixed(1)}px ${t.c0.toFixed(1)}px round 12px)`;
  const s = liquidState.get(key);
  liquidState.set(key, {a: t.a, b: t.b, samples: null, start: 0});
  ind.getAnimations?.().forEach(x => x.cancel());
  ind.style.clipPath = clip(t.a, t.b);
  if (!s || still() || (Math.abs(s.a - t.a) < .5 && Math.abs(s.b - t.b) < .5)) return;
  // Continue from what is on screen: position and velocity of the running animation, if any.
  let a0 = s.a, b0 = s.b, va = 0, vb = 0;
  if (s.samples) {
    const i = clamp(Math.floor((performance.now() - s.start) / 16.67), 0, s.samples.length - 1);
    [a0, b0] = s.samples[i];
    if (i > 0) { va = s.samples[i][0] - s.samples[i - 1][0]; vb = s.samples[i][1] - s.samples[i - 1][1]; }
  }
  const frames = simulate(a0, va, b0, vb, t.a, t.b);
  liquidState.set(key, {a: t.a, b: t.b, samples: frames, start: performance.now()});
  ind.animate(frames.map(([a, b]) => ({clipPath: clip(a, b)})), {duration: frames.length * 16.67, easing: 'linear'});
}

const relayout = c => { if (c.isConnected) liquid(c, {axis: c.dataset.liquidAxis, key: c.dataset.liquidKey, extend: Number(c.dataset.liquidExtend) || 0}); };
// Choices that switch without a re-render (a class flip) still move the indicator: after any click, re-measure.
addEventListener('click', e => {
  const c = e.target.closest?.('.has-liquid');
  if (c) setTimeout(() => relayout(c), 0);
});
// The window changed size: every indicator re-measures (the dock appears on phones, labels reflow).
let resizeTimer = 0;
addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => document.querySelectorAll('.has-liquid').forEach(relayout), 120);
});

/* ---------- Gesture-driven page transition ---------- */
export function gesturePages(area, view, {canGo, go}) {
  if (!area || !view) return;
  let g = null;
  const skip = el => el.closest('input,textarea,select,button,a[href].button,.no-swipe,.hscroll,.table-wrap,svg,dialog,.jelly-board,.ov-plans,.page-tabs,.segmented,[draggable],.card-block .panel-head,#ai-orb,#ai-pop');
  area.addEventListener('touchstart', e => {
    const p = e.touches[0];
    if (e.touches.length !== 1 || skip(e.target) || p.clientX < 24 || p.clientX > innerWidth - 24) { g = null; return; }  // edges: the system back gesture
    g = {x: p.clientX, y: p.clientY, dx: 0, lock: null, hist: [[p.clientX, performance.now()]]};
  }, {passive: true});
  area.addEventListener('touchmove', e => {
    if (!g) return;
    const p = e.touches[0], dx = p.clientX - g.x, dy = p.clientY - g.y;
    if (!g.lock) {
      if (Math.hypot(dx, dy) < 10) return;
      g.lock = Math.abs(dx) > Math.abs(dy) * 1.3 ? 'x' : 'y';  // decided once for this gesture
      if (g.lock === 'y') { g = null; return; }
      g.dir = dx < 0 ? 'left' : 'right';
      g.allowed = canGo(g.dir);
    }
    if (still()) return;
    g.dx = dx;
    g.hist.push([p.clientX, performance.now()]); if (g.hist.length > 6) g.hist.shift();
    const resist = g.allowed && Math.sign(dx) === (g.dir === 'left' ? -1 : 1) ? 1 : .25;  // past the first or last page: rubber band
    const x = dx * resist;
    view.style.transform = `translateX(${x}px)`;
    view.style.opacity = String(1 - Math.min(.5, Math.abs(x) / innerWidth));
  }, {passive: true});
  const end = cancelled => {
    if (!g || g.lock !== 'x') { g = null; return; }
    const [x0, t0] = g.hist[0], [x1, t1] = g.hist[g.hist.length - 1];
    const v = (x1 - x0) / Math.max(1, t1 - t0);  // px/ms over the last few moves, not the total distance
    const dir = g.dx < 0 ? 'left' : 'right', toward = (dir === 'left' ? -1 : 1);
    const commit = !cancelled && g.allowed && dir === g.dir && (Math.abs(g.dx) > innerWidth * .32 || (v * toward > .45 && Math.abs(g.dx) > 30));
    const from = view.style.transform || 'translateX(0px)', fromO = view.style.opacity || '1';
    g = null;
    if (still()) { view.style.transform = view.style.opacity = ''; if (commit) go(dir); return; }
    if (commit) {
      view.animate([{transform: from, opacity: fromO}, {transform: `translateX(${toward * innerWidth * .6}px)`, opacity: 0}],
        {duration: 180, easing: 'cubic-bezier(.3,.6,.4,1)', fill: 'forwards'}).finished.then(() => {
        view.style.transform = ''; view.style.opacity = '0';
        view.getAnimations().forEach(x => x.cancel());
        go(dir);
      }).catch(() => {});
    } else {
      view.animate([{transform: from, opacity: fromO}, {transform: 'translateX(0)', opacity: 1}], {duration: 380, easing: 'cubic-bezier(.2,1.3,.4,1)'});
      view.style.transform = view.style.opacity = '';
    }
  };
  area.addEventListener('touchend', () => end(false), {passive: true});
  area.addEventListener('touchcancel', () => end(true), {passive: true});
}

/* ---------- drag a sheet or drawer away ---------- */
export function dragDismiss(panel, close, axis = 'y') {
  if (!panel || panel.dataset.drag) return;
  panel.dataset.drag = '1';
  let d = null;
  panel.addEventListener('touchstart', e => {
    if (e.touches.length !== 1 || e.target.closest('input,textarea,select')) return;
    if (axis === 'y' && panel.scrollTop > 0) return;  // scrolled content scrolls first
    const p = e.touches[0];
    d = {x: p.clientX, y: p.clientY, lock: null, hist: [[axis === 'y' ? p.clientY : p.clientX, performance.now()]], off: 0};
  }, {passive: true});
  panel.addEventListener('touchmove', e => {
    if (!d) return;
    const p = e.touches[0], dx = p.clientX - d.x, dy = p.clientY - d.y;
    if (!d.lock) {
      if (Math.hypot(dx, dy) < 8) return;
      d.lock = (axis === 'y' ? Math.abs(dy) > Math.abs(dx) && dy > 0 : Math.abs(dx) > Math.abs(dy) && dx > 0) ? axis : 'no';
      if (d.lock === 'no') { d = null; return; }
      panel.style.transition = 'none';
    }
    d.off = Math.max(0, axis === 'y' ? dy : dx);
    d.hist.push([axis === 'y' ? p.clientY : p.clientX, performance.now()]); if (d.hist.length > 6) d.hist.shift();
    panel.style.transform = axis === 'y' ? `translateY(${d.off}px)` : `translateX(${d.off}px)`;
  }, {passive: true});
  const end = () => {
    if (!d || !d.lock || d.lock === 'no') { d = null; return; }
    const [p0, t0] = d.hist[0], [p1, t1] = d.hist[d.hist.length - 1];
    const v = (p1 - p0) / Math.max(1, t1 - t0), size = axis === 'y' ? panel.offsetHeight : panel.offsetWidth;
    const shut = d.off > size * .3 || (v > .5 && d.off > 24);
    panel.style.transition = ''; panel.style.transform = '';
    d = null;
    if (shut) close();
  };
  panel.addEventListener('touchend', end, {passive: true});
  panel.addEventListener('touchcancel', () => { if (d) { panel.style.transition = ''; panel.style.transform = ''; d = null; } }, {passive: true});
}

/* ---------- Center-focus Scaling ---------- */
export function centerFocus(scroller, itemSel) {
  if (!scroller || scroller.dataset.focus) return;
  scroller.dataset.focus = '1';
  let items = [], raf = 0;
  const measure = () => { items = [...scroller.querySelectorAll(itemSel)].map(el => ({el, c: el.offsetLeft + el.offsetWidth / 2})); paint(); };
  const paint = () => {
    raf = 0;
    const scrolls = scroller.scrollWidth > scroller.clientWidth + 4;
    const mid = scroller.scrollLeft + scroller.clientWidth / 2, span = scroller.clientWidth * .75;
    for (const {el, c} of items) {
      if (!scrolls || still()) { el.style.transform = el.style.opacity = ''; continue; }
      const k = clamp(Math.abs(c - mid) / span, 0, 1);
      el.style.transform = `scale(${(1 - k * .08).toFixed(3)})`;
      el.style.opacity = (1 - k * .3).toFixed(3);
    }
  };
  scroller.addEventListener('scroll', () => { raf ||= requestAnimationFrame(paint); }, {passive: true});
  new ResizeObserver(measure).observe(scroller);
  measure();
}

/* ---------- Shared-element Expansion (dialogs) ---------- */
const SOURCES = '.ov-plan, .acard, .scen-card, .option, .spend-list li, .list li.row, .table tr[data-action], .acct-chip, .fixed-list li';
let lastSource = null;
addEventListener('pointerdown', e => { lastSource = e.target.closest?.(SOURCES) || null; }, {capture: true});

const visible = el => {
  if (!el?.isConnected) return null;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.bottom > 0 && r.top < innerHeight ? r : null;
};

/** Call right after showModal(); returns a closer that animates back to the source (or false to use the plain exit). */
export function expandFrom(dialog, shell) {
  const src = lastSource, from = visible(src);
  lastSource = null;
  if (!from || still()) return null;
  const to = shell.getBoundingClientRect();
  const radius = parseFloat(getComputedStyle(src).borderRadius) || 14;
  const flip = r => `translate(${(r.left - to.left).toFixed(1)}px, ${(r.top - to.top).toFixed(1)}px) scale(${(r.width / to.width).toFixed(4)}, ${(r.height / to.height).toFixed(4)})`;
  dialog.classList.add('from-source');
  src.classList.add('source-hidden');  // one shape on screen, not two
  const kids = [...shell.children];
  kids.forEach(k => { k.style.opacity = '0'; });
  shell.animate([{transform: flip(from), borderRadius: `${radius}px`, transformOrigin: '0 0'}, {transform: 'none', borderRadius: '22px', transformOrigin: '0 0'}],
    {duration: 460, easing: 'cubic-bezier(.2,.9,.25,1)'}).finished.then(() => {
    kids.forEach(k => k.animate([{opacity: 0, transform: 'translateY(6px)'}, {opacity: 1, transform: 'none'}], {duration: 220, easing: 'ease-out'}));
    kids.forEach(k => { k.style.opacity = ''; });
    src.classList.remove('source-hidden');
  }).catch(() => { kids.forEach(k => { k.style.opacity = ''; }); src.classList.remove('source-hidden'); });
  return () => {
    const back = visible(src);
    if (!back) return false;  // the card is gone or scrolled away: use the ordinary exit
    const now = shell.getBoundingClientRect();
    kids.forEach(k => { k.style.opacity = '0'; });
    const anim = shell.animate([{transform: 'none', borderRadius: '22px', transformOrigin: '0 0'},
      {transform: `translate(${(back.left - now.left).toFixed(1)}px, ${(back.top - now.top).toFixed(1)}px) scale(${(back.width / now.width).toFixed(4)}, ${(back.height / now.height).toFixed(4)})`,
        borderRadius: `${radius}px`, transformOrigin: '0 0', opacity: .4}], {duration: 300, easing: 'cubic-bezier(.4,0,.2,1)', fill: 'forwards'});
    return anim.finished.then(() => { kids.forEach(k => { k.style.opacity = ''; }); anim.cancel(); dialog.classList.remove('from-source'); });
  };
}
