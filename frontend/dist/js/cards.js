/* The page as cards you arrange yourself — each one on its own.

   Every card of a page goes into one 12-column grid (cards that sat side by side are taken apart and keep the share of
   the row they had). Drag any card by its title (on a phone: press and hold the title) anywhere in two dimensions. While
   it moves it leans and stretches a little with its own speed (velocity from position over real time, smoothed, capped;
   it relaxes as soon as the pointer rests). The cards it comes near are pushed aside with a springy overshoot, and when
   you let go it springs into the free place at the grid's spacing — cards never overlap and never end up glued together.
   The slot it would take is chosen with hysteresis, so nothing flickers on a boundary; Esc or a lost pointer springs it
   back and changes nothing. The grip in a card's lower right corner changes its width, one column at a time (4–12).
   Alt+↑/↓ moves a focused card, Alt+←/→ narrows or widens it.

   Less on screen: one focus card per page (lifted, never outlined); cards that would only say "nothing here" step aside;
   secondary detail starts folded. Hovering a card lifts it, its shadow moving with the
   cursor as if lit from there. Order, widths and folds are remembered per page in this browser only. */
import {buzz} from './jelly.js';

const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const phone = () => matchMedia('(max-width: 860px)').matches;
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* a per-viewer convenience only */ } },
};
const GENERIC = new Set(['panel', 'reveal', 'in', 'tilt', 'card-block', 'card-focus', 'panel-focus', 'folded', 'lit', 'dragging', 'card-empty', 'resizing']);
const INTERACTIVE = 'button, a, input, select, textarea, label, [data-action], [contenteditable], .chart-host, summary, .card-size, .drop-zone';
const FOLDED = {markets: ['forecast-panel', 'analysis-panel', 'scenario-panel'], spending: ['insight-panel']};
const FOCUS = {markets: 'decide-panel', send: 'send-panel'};
const SKIP = new Set(['agent']);  // the assistant page has its own board
const MIN = 4;
const LIFT = 'article.panel, .ov-plan, .ov-bal, .scen-card, .option, .stat, .rcard, .route-chip, .tier-option, .proposal, .proposal-card, .drop-zone, .acct-chip, .budget-bar, .save-card, .decide-wait, .rec-cur, .cand, .fixed-list li';

/** The card a press may pick up: by its title, or by the top 64 px of a card that has no title bar. */
function handleOf(e) {
  const grip = e.target.closest?.('.card-grip');
  if (grip) return grip.closest('.deck > .card-block');
  if (e.target.closest(INTERACTIVE)) return null;
  const card = e.target.closest('.deck > .card-block');
  if (!card) return null;
  const head = e.target.closest('.panel-head');
  if (head && head.closest('.card-block') === card) return card;
  if (!card.querySelector(':scope > .panel-head, :scope > article.panel > .panel-head') && e.clientY - card.getBoundingClientRect().top < 64) return card;
  return null;
}

const keyOf = el => [...el.classList].filter(c => !GENERIC.has(c)).join('.') || el.id || 'card';

/** Arrange #view into the deck. Call after every paint. */
export function deck(root, view, t) {
  if (SKIP.has(view)) { wire(root, t); root.dataset.deckView = view; return; }
  // Every component of the page becomes a card of its own — panels and tools alike — except the title and the tab bar
  // (navigation). Layout wrappers are taken apart all the way down; each piece keeps the share of the row it had.
  const tops = [...root.children].filter(el => !el.matches('.page-head, .page-tabs, .deck, script, template'));
  if (!tops.length) { wire(root, t); return; }
  const leaves = [];
  const collect = el => {
    if (el.matches('article.panel') || !el.querySelector('article.panel')) { leaves.push(el); return; }
    [...el.children].forEach(collect);  // a wrapper: its children are the cards
  };
  tops.forEach(collect);
  const width = root.clientWidth || 1;
  const span = new Map(leaves.map(el => [el, clamp(Math.round(12 * el.getBoundingClientRect().width / width), MIN, 12)]));
  const homes = new Map(leaves.map(el => [el, el.parentElement]));
  // pieces from one row fill it exactly: the rounding remainder goes to the widest
  const groups = new Map();
  for (const el of leaves) if (homes.get(el) !== root) (groups.get(homes.get(el)) || groups.set(homes.get(el), []).get(homes.get(el))).push(el);
  for (const list of groups.values()) {
    const sum = list.reduce((a, x) => a + span.get(x), 0);
    if (list.length > 1 && sum !== 12 && sum > 6 && sum < 18) { const wide = list.reduce((a, b) => span.get(a) >= span.get(b) ? a : b); span.set(wide, clamp(span.get(wide) + 12 - sum, MIN, 12)); }
  }
  const grid = document.createElement('div');
  grid.className = 'deck';
  tops[0].before(grid);
  leaves.forEach(el => grid.appendChild(el));
  pack(grid);
  tops.forEach(el => { if (el.isConnected && el !== grid && !grid.contains(el) && !el.querySelector('article.panel, input, select, button, canvas, svg') && !el.textContent.trim()) el.remove(); });
  // keys, saved order and widths
  const cards = [...grid.children], seen = {};
  for (const el of cards) {
    let k = keyOf(el);
    seen[k] = (seen[k] || 0) + 1;
    if (seen[k] > 1) k += ':' + seen[k];
    el.dataset.card = k;
    el.classList.add('card-block');
  }
  const saved = store.get('dot.deck.' + view, null);
  if (saved?.length) {
    const at = new Map(saved.map((x, i) => [x.k, i]));
    cards.sort((a, b) => (at.get(a.dataset.card) ?? 1e3 + cards.indexOf(a)) - (at.get(b.dataset.card) ?? 1e3 + cards.indexOf(b)));
    cards.forEach(el => grid.appendChild(el));
    for (const x of saved) { const el = cards.find(c => c.dataset.card === x.k); if (el && x.s) span.set(el, x.s); }
  }
  cards.forEach(el => setSpan(el, span.get(el) || 12));
  for (const el of cards) {
    if (!el.querySelector(':scope > .card-grip')) {
      const g = document.createElement('span');
      g.className = 'card-grip'; g.setAttribute('aria-hidden', 'true'); g.title = t('cards.hint'); g.innerHTML = '<i></i><i></i><i></i><i></i><i></i><i></i>';
      el.appendChild(g);
    }
  }
  // empty cards step aside; one focus card
  cards.forEach((el, i) => {
    const empty = el.querySelector('.empty') && !el.querySelector('form, input, select, textarea, .panel-actions button, button.primary, button.button, [data-action]:not([data-action=go]):not(.card-fold)');
    el.classList.toggle('card-empty', !!empty && i > 0);
  });
  const shown = cards.filter(el => !el.classList.contains('card-empty'));
  const lead = (FOCUS[view] && grid.querySelector(`article.panel.${FOCUS[view]}`)) || shown.find(el => el.matches('article.panel'));
  lead?.classList.add('panel-focus');
  // width grips on every card
  for (const el of cards) if (!el.querySelector(':scope > .card-size')) {
    const g = document.createElement('span');
    g.className = 'card-size'; g.setAttribute('aria-hidden', 'true'); g.title = t('cards.size');
    el.appendChild(g);
  }
  // folds, fold buttons, title handles
  const folds = store.get('dot.folds.' + view, null);
  for (const panel of grid.querySelectorAll('article.panel')) {
    const head = panel.querySelector(':scope > .panel-head');
    if (!head) continue;
    const folded = folds ? folds.includes(panel.dataset.card || keyOf(panel)) : (FOLDED[view] || []).some(c => panel.classList.contains(c));
    panel.classList.toggle('folded', folded);
    if (!head.querySelector('.card-fold')) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'card-fold'; b.setAttribute('aria-label', t('cards.fold')); b.innerHTML = '<i></i>';
      head.appendChild(b);
    }
    head.querySelector('.card-fold').setAttribute('aria-expanded', String(!folded));
    head.tabIndex = 0;
    head.setAttribute('aria-roledescription', t('cards.handle'));
    head.title = t('cards.hint');
  }
  root.dataset.deckView = view;
  wire(root, t);
}

function setSpan(el, s) { el.dataset.span = String(s); el.style.setProperty('--span', s); }

// Masonry: the deck's rows are 1px tall and every card takes its own height plus the gap, so the space below and beside
// each card is the same everywhere (no holes under a short card next to a tall one). Sizes follow content as it changes.
const GAP = 18;
const fit = el => {
  if (el.parentElement?.classList.contains('deck') && !el.classList.contains('dragging'))
    el.style.gridRowEnd = `span ${Math.max(1, Math.ceil(el.offsetHeight + GAP))}`;
};
const sizer = new ResizeObserver(entries => entries.forEach(e => fit(e.target)));
function pack(grid) {
  [...grid.children].forEach(el => { sizer.observe(el); fit(el); });
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => { if (n.nodeType === 1) { sizer.observe(n); fit(n); } })))
    .observe(grid, {childList: true});
}

function save(root) {
  const grid = root.querySelector('.deck');
  if (!grid) return;
  store.set('dot.deck.' + root.dataset.deckView, [...grid.children].filter(el => el.dataset.card).map(el => ({k: el.dataset.card, s: Number(el.dataset.span) || 12})));
}

/** FLIP: whatever moved since `first` glides to its new place with a little overshoot — the push. */
function flip(nodes, first) {
  if (still()) return;
  for (const el of nodes) {
    const a = first.get(el), b = el.getBoundingClientRect();
    if (!a) continue;
    const dx = a.left - b.left, dy = a.top - b.top;
    if (Math.abs(dy) < 1 && Math.abs(dx) < 1) continue;
    el.animate([{transform: `translate(${dx}px, ${dy}px)`}, {transform: 'none'}], {duration: 460, easing: 'cubic-bezier(.22,1.4,.36,1)'});
  }
}
const snapshot = grid => new Map([...grid.children].map(el => [el, el.getBoundingClientRect()]));

function toggleFold(root, panel) {
  const view = root.dataset.deckView, key = panel.dataset.card || keyOf(panel);
  const folded = !panel.classList.contains('folded');
  const all = [...root.querySelectorAll('article.panel.folded')].map(p => p.dataset.card || keyOf(p)).filter(k => k !== key);
  if (folded) all.push(key);
  store.set('dot.folds.' + view, all);
  const grid = root.querySelector('.deck'), first = grid ? snapshot(grid) : null;
  panel.classList.toggle('folded', folded);
  panel.querySelector('.card-fold')?.setAttribute('aria-expanded', String(!folded));
  if (grid) flip([...grid.children].filter(el => el !== panel), first);
  buzz(6);
}

let wired = false;
function wire(root, t) {
  if (wired) return;
  wired = true;
  let d = null;

  // ---------- hover: the card lifts toward you, its shadow moving with the cursor ----------
  root.addEventListener('pointermove', e => {
    if (e.pointerType !== 'mouse' || d || still()) return;
    const el = e.target.closest(LIFT);
    if (!el) return;
    const r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
    el.style.setProperty('--sx', (-x * 18).toFixed(1) + 'px');
    el.style.setProperty('--sy', (16 - y * 10).toFixed(1) + 'px');
  }, {passive: true});

  root.addEventListener('click', e => {
    const fold = e.target.closest('.card-fold');
    if (fold) { e.preventDefault(); toggleFold(root, fold.closest('article.panel')); }
  });
  root.addEventListener('dblclick', e => {
    const head = e.target.closest('.panel-head');
    if (head && head.closest('.deck') && !e.target.closest(INTERACTIVE)) toggleFold(root, head.closest('article.panel'));
  });
  // keyboard: Alt+↑/↓ moves, Alt+←/→ resizes
  root.addEventListener('keydown', e => {
    const head = e.target.closest?.('.panel-head');
    const card = head?.closest('.card-block');
    if (!card || !e.altKey || !card.parentElement.matches('.deck')) return;
    const grid = card.parentElement, first = snapshot(grid);
    if (e.key === 'ArrowUp' && card.previousElementSibling) card.previousElementSibling.before(card);
    else if (e.key === 'ArrowDown' && card.nextElementSibling) card.nextElementSibling.after(card);
    else if (e.key === 'ArrowLeft') setSpan(card, Math.max(MIN, Number(card.dataset.span) - 1));
    else if (e.key === 'ArrowRight') setSpan(card, Math.min(12, Number(card.dataset.span) + 1));
    else return;
    e.preventDefault(); flip([...grid.children], first); save(root); head.focus(); buzz(6);
  });
  // ---------- width: drag the corner grip, one column at a time ----------
  root.addEventListener('pointerdown', e => {
    const grip = e.target.closest('.card-size');
    if (!grip || phone()) return;
    e.preventDefault(); e.stopPropagation();
    const card = grip.closest('.card-block'), grid = card.parentElement, col = (grid.clientWidth + 18) / 12;
    const start = e.clientX, s0 = Number(card.dataset.span) || 12;
    card.classList.add('resizing'); buzz(8);
    const move = ev => {
      const s = clamp(Math.round(s0 + (ev.clientX - start) / col), MIN, 12);
      if (s === Number(card.dataset.span)) return;
      const first = snapshot(grid);
      setSpan(card, s); flip([...grid.children], first); buzz(4);
    };
    const up = () => { removeEventListener('pointermove', move); removeEventListener('pointerup', up); card.classList.remove('resizing'); save(root); dispatchEvent(new Event('dot:arranged')); };
    addEventListener('pointermove', move); addEventListener('pointerup', up);
  }, true);

  // ---------- dragging any card in two dimensions ----------
  const begin = (card, x, y) => {
    const grid = card.parentElement, r = card.getBoundingClientRect();
    const slot = document.createElement('div');
    slot.className = 'card-slot';
    slot.style.height = r.height + 'px';
    setSpan(slot, Number(card.dataset.span) || 12);
    card.before(slot);
    card.classList.add('dragging');
    Object.assign(card.style, {position: 'fixed', left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px', zIndex: 70, margin: 0, pointerEvents: 'none'});
    d = {card, grid, slot, ox: x - r.left, oy: y - r.top, x, y, px: r.left, py: r.top, vx: 0, vy: 0, last: performance.now(),
         start: [r.left, r.top], home: slot.nextElementSibling === card ? card.nextElementSibling : slot.nextElementSibling, raf: 0, w: r.width, h: r.height,
         span: Number(card.dataset.span) || 12, shared: new Map()};
    grid.appendChild(card);  // out of the flow while it flies
    root.classList.add('arranging');
    buzz(10);
    d.raf = requestAnimationFrame(frame);
  };

  const pick = () => {
    const cx = d.x, cy = d.y;  // where the finger or pointer aims, not the card's centre (a wide card held by its edge)
    const items = [...d.grid.children].filter(el => el !== d.card && el !== d.slot && !el.classList.contains('card-empty'));
    if (!items.length) return;
    // distance to a card's edge (0 when the pointer is over it), so a wide card is as easy to reach as a narrow one
    const centre = el => { const r = el.getBoundingClientRect(); return {r, x: r.left + r.width / 2, y: r.top + r.height / 2,
      dist: Math.hypot(Math.max(r.left - cx, 0, cx - r.right), Math.max(r.top - cy, 0, cy - r.bottom))}; };
    let best = null;
    for (const el of items) { const c = centre(el); if (!best || c.dist < best.dist || (c.dist === best.dist && Math.hypot(c.x - cx, c.y - cy) < Math.hypot(best.x - cx, best.y - cy))) best = {el, ...c}; }
    const here = centre(d.slot).dist;
    if (here === 0 || best.dist > here - 24) return;  // hysteresis: over the slot, or nothing clearly closer, keeps it
    const sameRow = Math.abs(cy - best.y) < best.r.height * .3;
    const before = sameRow ? cx < best.x : cy < best.y;
    const adjacent = (before && best.el.previousElementSibling === d.slot) || (!before && best.el.nextElementSibling === d.slot);
    const share = sameRow && !phone() && Number(d.slot.dataset.span) + Number(best.el.dataset.span) > 12 && !d.shared.has(best.el);
    if (adjacent && !share) return;
    const first = snapshot(d.grid);
    if (!adjacent) { if (before) best.el.before(d.slot); else best.el.after(d.slot); }
    // give back what neighbours lent, unless they are still beside the slot
    for (const [el, s0] of d.shared) {
      if (el !== best.el || !sameRow) { setSpan(el, s0); d.shared.delete(el); }
    }
    if (share) { d.shared.set(best.el, Number(best.el.dataset.span)); setSpan(best.el, 6); setSpan(d.slot, 6); }
    else if (!d.shared.size) setSpan(d.slot, d.span);
    flip([...d.grid.children].filter(el => el !== d.card), first);
    buzz(4);
  };

  function frame(now) {
    if (!d) return;
    const dt = clamp(now - d.last, 8, 50); d.last = now;
    let tx = d.x - d.ox, ty = d.y - d.oy;
    const s = d.slot.getBoundingClientRect(), dist = Math.hypot(tx - s.left, ty - s.top), R = 110;
    if (dist < R) { const w = Math.pow(1 - dist / R, 2) * .55; tx += (s.left - tx) * w; ty += (s.top - ty) * w; }  // drawn into the slot, smoothly
    const nx = d.px + (tx - d.px) * .5, ny = d.py + (ty - d.py) * .5;
    d.vx += ((nx - d.px) / dt * 16.67 - d.vx) * .35; d.vy += ((ny - d.py) / dt * 16.67 - d.vy) * .35;
    d.px = nx; d.py = ny;
    const base = `translate(${d.px - d.start[0]}px, ${d.py - d.start[1]}px)`;
    if (still()) d.card.style.transform = base;
    else {
      const sp = Math.hypot(d.vx, d.vy), a = Math.atan2(d.vy, d.vx), st = 1 + clamp(sp * .004, 0, .05);
      d.card.style.transform = `${base} rotate(${clamp(d.vx * .35, -3.5, 3.5)}deg) rotate(${a}rad) scale(${(st * 1.015).toFixed(4)}, ${(1.015 / st).toFixed(4)}) rotate(${-a}rad)`;
    }
    if (d.y < 70) scrollBy(0, -12); else if (d.y > innerHeight - 70) scrollBy(0, 12);
    pick();
    d.raf = requestAnimationFrame(frame);
  }

  const finish = cancel => {
    if (!d) return;
    const {card, slot, grid} = d;
    cancelAnimationFrame(d.raf);
    if (cancel) {
      const first = snapshot(grid);
      for (const [el, s0] of d.shared) setSpan(el, s0);
      setSpan(slot, d.span);
      if (d.home && d.home !== card && d.home.parentElement === grid) d.home.before(slot);
      flip([...grid.children].filter(el => el !== card), first);
    }
    const landed = Number(slot.dataset.span) || d.span;
    const to = slot.getBoundingClientRect(), current = card.style.transform;
    const base = current.replace(/rotate\([^)]*\)|scale\([^)]*\)/g, '').trim();
    const dx = to.left - d.px, dy = to.top - d.py;
    const end = () => {
      card.getAnimations().forEach(a => a.cancel());
      slot.replaceWith(card);
      setSpan(card, landed);  // side by side: it takes the half it was given
      card.classList.remove('dragging');
      ['position', 'left', 'top', 'width', 'height', 'zIndex', 'margin', 'pointerEvents', 'transform'].forEach(p => { card.style[p] = ''; });
      root.classList.remove('arranging');
      if (!cancel) save(root);
      dispatchEvent(new Event('dot:arranged'));  // a refresh held back during the drag may run now
      buzz(cancel ? 6 : [10, 30, 8]);
    };
    d = null;
    if (still()) { end(); return; }
    // spring into the slot: a little past it, then settle at the grid's spacing
    card.animate([{transform: current}, {transform: `${base} translate(${dx * 1.06}px, ${dy * 1.06}px) scale(1.01, .99)`, offset: .62},
      {transform: `${base} translate(${dx * .985}px, ${dy * .985}px) scale(.995, 1.005)`, offset: .84}, {transform: `${base} translate(${dx}px, ${dy}px)`}],
      {duration: 520, easing: 'cubic-bezier(.3,.9,.4,1)', fill: 'forwards'}).finished.then(end, end);
  };

  root.addEventListener('pointerdown', e => {
    if (e.pointerType !== 'mouse' || e.button !== 0) return;
    const card = handleOf(e);
    if (!card) return;
    const sx = e.clientX, sy = e.clientY;
    const move = ev => {
      if (!d && Math.hypot(ev.clientX - sx, ev.clientY - sy) > 6) { begin(card, sx, sy); getSelection()?.removeAllRanges(); }
      if (d) { d.x = ev.clientX; d.y = ev.clientY; }
    };
    const stop = cancel => () => { removeEventListener('pointermove', move); removeEventListener('pointerup', up); removeEventListener('pointercancel', cc); finish(cancel); };
    const up = stop(false), cc = stop(true);
    addEventListener('pointermove', move); addEventListener('pointerup', up); addEventListener('pointercancel', cc);
  });
  addEventListener('keydown', e => { if (e.key === 'Escape' && d) finish(true); });
  addEventListener('blur', () => { if (d) finish(true); });

  let hold = null;
  root.addEventListener('touchstart', e => {
    if (e.touches.length !== 1) return;
    const p = e.touches[0], card = handleOf({target: e.target, clientY: p.clientY});
    if (!card) return;
    hold = {x: p.clientX, y: p.clientY, timer: setTimeout(() => begin(card, hold.x, hold.y), 320)};
  }, {passive: true});
  root.addEventListener('touchmove', e => {
    const p = e.touches[0];
    if (d) { e.preventDefault(); d.x = p.clientX; d.y = p.clientY; return; }
    if (hold && Math.hypot(p.clientX - hold.x, p.clientY - hold.y) > 8) { clearTimeout(hold.timer); hold = null; }
  }, {passive: false});
  root.addEventListener('touchend', () => { if (hold) clearTimeout(hold.timer); hold = null; finish(false); }, {passive: true});
  root.addEventListener('touchcancel', () => { if (hold) clearTimeout(hold.timer); hold = null; finish(true); }, {passive: true});
}
