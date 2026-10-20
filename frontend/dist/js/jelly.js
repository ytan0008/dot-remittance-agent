/* Jelly tiles — drag, fling and stack with springs only (no animation library).

   Every motion is an under-damped spring, integrated per frame-time so it feels the same at 60 or 120 Hz. A tile squashes
   when pressed and pops on release, stretches a little along its (smoothed) velocity and lifts its shadow while held.
   Tiles never push each other around (that is what made a crowded board tremble): a tile dropped, or flung to rest, onto
   others settles like a drop on top of that pile, offset down and to the side so every tile's title stays readable.
   tidy() lays the board out flat again. Haptics use navigator.vibrate in try/catch. Tile sizes come from the DOM; tiles
   can be added and removed at any time. */

const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

export function buzz(pattern) {
  try { if (navigator.vibrate) navigator.vibrate(pattern); } catch { /* unsupported */ }
}

export function jellyBoard(stage, {fixed = false} = {}) {
  const board = stage.querySelector('.jelly-board');
  if (!board) return null;
  if (still()) {
    board.classList.add('jelly-static');
    return {add(el) { if (!el.parentNode) board.appendChild(el); return el; }, remove(el) { el.remove(); }, tidy() {}, focus() {}, stop() {}};
  }
  board.classList.add('jelly-live');
  const GAP = 14, PAD = 12, FAN_X = 18, FAN_Y = 34;  // a stacked tile shows the one below by FAN_Y: its title row
  const tiles = [];
  let bw = board.clientWidth, bh = 0, raf = 0, last = performance.now(), top = 2;

  const make = el => ({el, x: PAD, y: PAD, vx: 0, vy: 0, w: el.offsetWidth, h: el.offsetHeight, dragging: false, tx: 0, ty: 0, gx: 0, gy: 0,
    home: null, settling: false, z: 2, wx: 0, wy: 0, wxv: 0, wyv: 0, press: 0, pv: 0, pt: 0, st: 0, sa: 0, moved: 0});

  function measure() {
    bw = board.clientWidth;
    for (const t of tiles) { t.w = t.el.offsetWidth; t.h = t.el.offsetHeight; }
    if (fixed) { bh = board.clientHeight; return; }
    const tallest = Math.max(110, ...tiles.map(t => t.h));
    const bottom = Math.max(0, ...tiles.map(t => (t.home ? t.home[1] : t.y) + t.h));
    bh = Math.max(bottom + PAD, tallest + PAD * 2);
    board.style.height = Math.round(bh) + 'px';
  }

  function flow() {  // side by side in rows, the way they arrived
    let x = PAD, y = PAD, row = 0;
    for (const t of tiles) {
      if (x + t.w > bw - PAD && x > PAD) { x = PAD; y += row + GAP; row = 0; }
      t.home = [x, y]; x += t.w + GAP; row = Math.max(row, t.h);
    }
  }

  function freeSpot(t) {
    const maxY = Math.max(bh, t.h + PAD * 2) - PAD - t.h;
    for (let y = PAD; y <= maxY; y += 20) {
      for (let x = PAD; x + t.w <= bw - PAD; x += 20) {
        if (!tiles.some(o => o !== t && x < o.x + o.w + 8 && x + t.w + 8 > o.x && y < o.y + o.h + 8 && y + t.h + 8 > o.y)) return [x, y];
      }
    }
    return [PAD, PAD];
  }

  const overlap = (a, b) => Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
  const clampX = (t, x) => clamp(x, PAD, Math.max(PAD, bw - PAD - t.w));
  const clampY = (t, y) => fixed ? clamp(y, PAD, Math.max(PAD, bh - PAD - t.h)) : Math.max(PAD, y);

  /** Where a tile at rest belongs: alone where it is, or fanned on top of the pile it covers. */
  function settle(t) {
    t.settling = false;
    const under = tiles.filter(o => o !== t && overlap(t, o) > .15 * Math.min(t.w * t.h, o.w * o.h));
    t.z = ++top; t.el.style.zIndex = String(t.z);
    if (!under.length) { t.home = [clampX(t, t.x), clampY(t, t.y)]; return; }
    const pile = under.reduce((a, b) => a.z > b.z ? a : b);  // the tile on top of that pile
    const [px, py] = pile.home || [pile.x, pile.y];
    const right = px + FAN_X + t.w <= bw - PAD;
    t.home = [clampX(t, right ? px + FAN_X : px - FAN_X), clampY(t, py + FAN_Y)];
    t.wyv -= .07; t.wxv += .05;  // lands soft, like a drop
    buzz(8);
    if (!fixed) measure();
  }

  for (const el of board.querySelectorAll('[data-jelly]')) tiles.push(make(el));
  measure(); flow();
  for (const t of tiles) [t.x, t.y] = t.home;
  measure();

  // ---------- pointer ----------
  let active = null, lastP = {x: 0, y: 0};
  const local = e => { const r = board.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  board.addEventListener('pointerdown', e => {
    const el = e.target.closest('[data-jelly]');
    if (!el || e.target.closest('button, a, input, select, textarea, label') || e.button > 0) return;
    const t = tiles.find(x => x.el === el);
    if (!t) return;
    const [px, py] = local(e);
    Object.assign(t, {dragging: true, gx: px - t.x, gy: py - t.y, tx: t.x, ty: t.y, pt: 1, moved: 0, home: null, settling: false});
    active = t; lastP = {x: px, y: py};
    el.setPointerCapture(e.pointerId);
    el.classList.add('grabbing');
    el.style.zIndex = '50';
  });
  board.addEventListener('pointermove', e => {
    if (!active) return;
    const [px, py] = local(e);
    active.moved += Math.hypot(px - lastP.x, py - lastP.y);
    active.tx = px - active.gx; active.ty = py - active.gy;
    lastP = {x: px, y: py};
  });
  const release = () => {
    if (!active) return;
    const t = active;
    active = null;
    t.dragging = false; t.pt = 0; t.wyv -= .06; t.wxv += .04;  // pop back up
    t.el.classList.remove('grabbing');
    t.settling = true;  // once it comes to rest, it finds its place
  };
  board.addEventListener('pointerup', release);
  board.addEventListener('pointercancel', release);
  const ro = new ResizeObserver(() => {
    measure();
    tiles.forEach(t => { if (t.home) t.home = [clampX(t, t.home[0]), clampY(t, t.home[1])]; });
  });
  ro.observe(board);

  // ---------- simulation ----------
  function physics(fs) {
    const fr = Math.pow(.9, fs);
    for (const t of tiles) {
      if (t.dragging) {  // a beat behind the finger
        t.vx = (t.vx + (t.tx - t.x) * .2 * fs) * Math.pow(.7, fs);
        t.vy = (t.vy + (t.ty - t.y) * .2 * fs) * Math.pow(.7, fs);
      } else if (t.home) {  // drawn to its place, a little past it, then still
        t.vx = (t.vx + (t.home[0] - t.x) * .12 * fs) * Math.pow(.74, fs);
        t.vy = (t.vy + (t.home[1] - t.y) * .12 * fs) * Math.pow(.74, fs);
      } else { t.vx *= fr; t.vy *= fr; }
      t.x += t.vx * fs; t.y += t.vy * fs;
      if (!t.dragging) {  // walls stop a fling; no tile ever pushes another
        const x = clampX(t, t.x), y = clampY(t, t.y);
        if (x !== t.x) { t.x = x; t.vx = 0; }
        if (y !== t.y) { t.y = y; t.vy = 0; }
      }
      if (t.settling && Math.hypot(t.vx, t.vy) < .4) settle(t);
      t.wxv = (t.wxv + (0 - t.wx) * .14 * fs) * Math.pow(.84, fs); t.wx += t.wxv * fs;
      t.wyv = (t.wyv + (0 - t.wy) * .14 * fs) * Math.pow(.84, fs); t.wy += t.wyv * fs;
      t.pv = (t.pv + (t.pt - t.press) * .26 * fs) * Math.pow(.66, fs); t.press += t.pv * fs;
    }
  }

  function draw() {
    for (const t of tiles) {
      const speed = Math.hypot(t.vx, t.vy);
      t.st += (Math.min(Math.max(0, speed - 2) * .008, .12) - t.st) * .2;  // only a real fling stretches
      if (speed > .5) {
        const d = Math.atan2(Math.sin(Math.atan2(t.vy, t.vx) - t.sa), Math.cos(Math.atan2(t.vy, t.vx) - t.sa));
        t.sa += d * .25;
      }
      const wx = clamp(t.wx, -.12, .12), wy = clamp(t.wy, -.12, .12);
      const sx = (1 + wx) * (1 + t.press * .04), sy = (1 + wy) * (1 - t.press * .06);
      t.el.style.transform = `translate3d(${t.x.toFixed(2)}px,${t.y.toFixed(2)}px,0)`
        + ` rotate(${t.sa.toFixed(4)}rad) scale(${(1 + t.st).toFixed(4)},${(1 - t.st * .45).toFixed(4)}) rotate(${(-t.sa).toFixed(4)}rad)`
        + ` scale(${sx.toFixed(4)},${sy.toFixed(4)})`;
    }
  }

  function step(now) {
    if (!board.isConnected) { ro.disconnect(); return; }
    raf = requestAnimationFrame(step);
    const f = clamp((now - last) / 16.667, .25, 3);
    last = now;
    if (document.hidden) return;
    const steps = Math.ceil(f);
    for (let i = 0; i < steps; i++) physics(f / steps);
    draw();
  }
  raf = requestAnimationFrame(step);

  return {
    /** Drop a new tile in from above, into the first free spot. */
    add(el) {
      if (!el.parentNode) board.appendChild(el);
      const t = make(el);
      tiles.push(t);
      t.w = el.offsetWidth; t.h = el.offsetHeight;
      const [x, y] = freeSpot(t);
      t.home = [x, y]; t.x = x; t.y = Math.max(PAD, y - 40); measure();
      t.z = ++top; el.style.zIndex = String(t.z);
      buzz(6);
      return el;
    },
    remove(el) {
      const t = tiles.find(x => x.el === el);
      if (!t) return;
      tiles.splice(tiles.indexOf(t), 1);
      el.remove();
    },
    focus(el) {  // bring a tile to the top of its pile with a little bounce
      const t = tiles.find(x => x.el === el);
      if (!t) return;
      t.z = ++top; el.style.zIndex = String(t.z);
      t.wyv -= .08; t.wxv += .06;
      buzz(10);
    },
    /** Lay every tile out flat again, side by side. */
    tidy() { measure(); flow(); tiles.forEach(t => { t.settling = false; }); measure(); buzz(8); },
    stop: () => { cancelAnimationFrame(raf); ro.disconnect(); },
  };
}
