/* Jelly tiles — drag, fling, bounce, join and split with springs only (no animation library).

   Every motion is an under-damped spring  v = (v + (target - x) * k) * damping, integrated per frame-time so it feels the
   same at 60 or 120 Hz. A tile squashes when pressed and pops on release, stretches along its (smoothed) velocity, wobbles
   on two axes after any impact, softly blurs when moving fast, and lifts its shadow while held. Near another tile it is
   pulled in and a liquid neck previews the join; drop it there and the two are tied by a soft spring and a gooey bridge
   that thins as they stretch apart. Double-click splits a tile out; scatter() blows the board apart. Haptics use
   navigator.vibrate in try/catch, and every jolt also shakes the board with a damped spring (iPhones and desktops
   cannot vibrate). Tile sizes come from the DOM; tiles can be added and removed at any time. */

const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const SVG = 'http://www.w3.org/2000/svg';

export function buzz(pattern) {
  try { if (navigator.vibrate) navigator.vibrate(pattern); } catch { /* unsupported: the on-screen shake carries it */ }
}

export function jellyBoard(stage, {link = () => '', onJoin = () => {}, onSplit = () => {}, fixed = false, axis = 'auto'} = {}) {
  const board = stage.querySelector('.jelly-board');
  if (!board) return null;
  if (still()) {
    board.classList.add('jelly-static');
    return {add(el) { if (!el.parentNode) board.appendChild(el); return el; }, remove(el) { el.remove(); }, scatter() {}, focus() {}, split() {}, stop() {}};
  }
  board.classList.add('jelly-live');
  const goo = document.createElementNS(SVG, 'svg');
  goo.setAttribute('class', 'jelly-goo');
  goo.setAttribute('aria-hidden', 'true');
  board.prepend(goo);
  const GAP = 14, PAD = 12;
  const tiles = [], links = [];
  let bw = board.clientWidth, bh = 0, raf = 0, last = performance.now();
  const shake = {x: 0, y: 0, vx: 0, vy: 0, r: 0, vr: 0};
  const pulse = {s: 0, v: 0};

  const make = el => ({el, x: PAD, y: PAD, vx: 0, vy: 0, w: el.offsetWidth, h: el.offsetHeight, dragging: false, tx: 0, ty: 0, gx: 0, gy: 0,
    wx: 0, wy: 0, wxv: 0, wyv: 0, press: 0, pv: 0, pt: 0, st: 0, sa: 0, blur: 0, moved: 0, near: null});

  function measure() {
    bw = board.clientWidth;
    for (const t of tiles) { t.w = t.el.offsetWidth; t.h = t.el.offsetHeight; }
    if (fixed) { bh = board.clientHeight; return; }
    const tallest = Math.max(110, ...tiles.map(t => t.h));
    const bottom = Math.max(0, ...tiles.map(t => t.y + t.h));
    bh = Math.max(bottom + Math.min(tallest * .8, 110) + PAD, tallest * 1.8 + PAD * 2);
    board.style.height = Math.round(bh) + 'px';
  }

  function flow() {
    let x = PAD, y = PAD, row = 0;
    for (const t of tiles) {
      if (x + t.w > bw - PAD && x > PAD) { x = PAD; y += row + GAP; row = 0; }
      t.x = x; t.y = y; x += t.w + GAP; row = Math.max(row, t.h);
    }
  }

  function freeSpot(t) {
    const maxY = Math.max(bh, t.h + PAD * 2) - PAD - t.h;
    for (let y = PAD; y <= maxY; y += 20) {
      for (let x = PAD; x + t.w <= bw - PAD; x += 20) {
        if (!tiles.some(o => o !== t && x < o.x + o.w + 8 && x + t.w + 8 > o.x && y < o.y + o.h + 8 && y + t.h + 8 > o.y)) return [x, y];
      }
    }
    return [PAD + Math.random() * Math.max(1, bw - t.w - PAD * 2), PAD];
  }

  for (const el of board.querySelectorAll('[data-jelly]')) tiles.push(make(el));
  measure(); flow(); measure();

  const group = t => {
    const seen = new Set([t]), stack = [t];
    while (stack.length) {
      const c = stack.pop();
      for (const l of links) for (const [p, q] of [[l.a, l.b], [l.b, l.a]]) if (p === c && !seen.has(q)) { seen.add(q); stack.push(q); }
    }
    return seen;
  };
  const center = t => [t.x + t.w / 2, t.y + t.h / 2];
  const linked = (a, b) => links.some(l => (l.a === a && l.b === b) || (l.a === b && l.b === a));

  function hit(t, strength, ax) {  // squash along the axis of an impact, bulge across it
    if (strength < 1.2) return;  // resting contact, not an impact
    const s = Math.min(.12, (strength - 1.2) * .01);
    if (ax === 'x') { t.wxv -= s; t.wyv += s * .7; } else { t.wyv -= s; t.wxv += s * .7; }
  }
  function jolt(amount, pattern) {
    const a = Math.random() * Math.PI * 2;
    shake.vx += Math.cos(a) * amount; shake.vy += Math.sin(a) * amount; shake.vr += (Math.random() - .5) * amount * .08;
    pulse.v += amount * .0014;
    buzz(pattern);
  }
  function ripple(x, y, strong = false) {
    const r = document.createElement('span');
    r.className = 'jelly-ripple' + (strong ? ' strong' : '');
    r.style.left = x + 'px'; r.style.top = y + 'px';
    board.appendChild(r);
    r.addEventListener('animationend', () => r.remove(), {once: true});
  }

  function restFor(a, b) {
    // Side by side when there is room, otherwise stacked; the dropped tile keeps the side it came from.
    const [ax, ay] = center(a), [bx, by] = center(b);
    const horizontal = axis === 'x' || (axis === 'auto' && (a.w + b.w + 20 + PAD * 2 <= bw) && Math.abs(ax - bx) >= Math.abs(ay - by) * .6);
    // Never ask for more room than the board has: a pair that cannot sit apart overlaps like a fanned stack.
    const room = (span, sa, sb) => Math.max(36, Math.min((sa + sb) / 2 + 10, span - PAD * 2 - (sa + sb) / 2));
    if (horizontal) return [(ax < bx ? -1 : 1) * room(bw, a.w, b.w), 0];
    return [0, (ay < by ? -1 : 1) * room(fixed ? bh : 1e5, a.h, b.h)];
  }

  function join(a, b) {
    if (group(a).has(b)) return;
    const [rx, ry] = restFor(a, b);
    const pill = document.createElement('div');
    pill.className = 'jelly-link';
    pill.innerHTML = link(a.el, b.el);
    board.appendChild(pill);
    const path = document.createElementNS(SVG, 'path');
    goo.appendChild(path);
    links.push({a, b, rx, ry, pill, path});
    // Snap in with a squelch: the dropped tile rushes to its place, both wobble in opposite phase.
    const [bx, by] = center(b);
    a.vx += (bx + rx - (a.x + a.w / 2)) * .2; a.vy += (by + ry - (a.y + a.h / 2)) * .2;
    hit(a, 9, rx ? 'x' : 'y'); hit(b, 9, rx ? 'x' : 'y'); b.wxv *= -1; b.wyv *= -1;
    ripple(bx + rx / 2, by + ry / 2, true);
    jolt(7, [18, 30, 26]);
    onJoin(a.el, b.el);
  }

  function unlink(l) { l.pill.remove(); l.path.remove(); links.splice(links.indexOf(l), 1); }

  function split(t) {
    const mine = links.filter(l => l.a === t || l.b === t);
    if (!mine.length) { t.wxv += .08; t.wyv -= .08; jolt(3, 10); return; }
    const mates = [...group(t)].filter(m => m !== t);
    const gx = mates.reduce((s, m) => s + center(m)[0], 0) / mates.length, gy = mates.reduce((s, m) => s + center(m)[1], 0) / mates.length;
    const [cx, cy] = center(t);
    const d = Math.hypot(cx - gx, cy - gy) || 1;
    t.vx += (cx - gx) / d * 14; t.vy += (cy - gy) / d * 10 - 4;
    mine.forEach(unlink);
    hit(t, 12, 'x'); mates.forEach(m => hit(m, 6, 'y'));
    ripple(cx, cy);
    jolt(6, [12, 40, 12]);
    onSplit(t.el);
  }

  function scatter() {
    [...links].forEach(unlink);
    for (const t of tiles) {
      const [cx, cy] = center(t);
      const ang = Math.atan2(cy - bh / 2, cx - bw / 2) + (Math.random() - .5) * 1.4;
      const speed = 18 + Math.random() * 12;
      t.vx += Math.cos(ang) * speed; t.vy += Math.sin(ang) * speed - 5;
      t.wxv += (Math.random() - .5) * .4; t.wyv += (Math.random() - .5) * .4;
    }
    ripple(bw / 2, bh / 2, true);
    jolt(18, [30, 50, 30, 50, 70]);
  }

  // ---------- pointer ----------
  let active = null, lastP = {x: 0, y: 0};
  const local = e => { const r = board.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  board.addEventListener('pointerdown', e => {
    const el = e.target.closest('[data-jelly]');
    if (!el || e.target.closest('button, a, input, select, textarea, label') || e.button > 0) return;
    const t = tiles.find(x => x.el === el);
    if (!t) return;
    const [px, py] = local(e);
    Object.assign(t, {dragging: true, gx: px - t.x, gy: py - t.y, tx: t.x, ty: t.y, pt: 1, moved: 0});
    active = t; lastP = {x: px, y: py};
    el.setPointerCapture(e.pointerId);
    el.classList.add('grabbing');
    const g = group(t);
    tiles.forEach(x => { x.el.style.zIndex = x === t ? '5' : g.has(x) ? '4' : '2'; });
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
    t.dragging = false; t.pt = 0; t.wyv -= .09; t.wxv += .05;  // pop back up
    t.el.classList.remove('grabbing');
    const target = t.near;
    t.near = null;
    tiles.forEach(o => o.el.classList.remove('magnet'));
    if (t.moved >= 4 && target) join(t, target);
  };
  board.addEventListener('pointerup', release);
  board.addEventListener('pointercancel', release);
  board.addEventListener('dblclick', e => {
    const el = e.target.closest('[data-jelly]');
    const t = el && tiles.find(x => x.el === el);
    if (t && !e.target.closest('button, a, input, select, textarea')) split(t);
  });
  const ro = new ResizeObserver(() => {
    measure();
    tiles.forEach(t => { t.x = clamp(t.x, PAD, Math.max(PAD, bw - PAD - t.w)); });
  });
  ro.observe(board);

  // ---------- simulation ----------
  function neck(a, b, preview = false) {
    // A liquid bridge between two tile edges: wide where it meets each tile, pinched in the middle, thinner when stretched.
    const [ax, ay] = center(a), [bx, by] = center(b);
    const dx = bx - ax, dy = by - ay, d = Math.hypot(dx, dy) || 1, ux = dx / d, uy = dy / d, nx = -uy, ny = ux;
    const across = Math.abs(ux) > Math.abs(uy);
    const ha = (across ? a.h : a.w) * .17, hb = (across ? b.h : b.w) * .17;
    const gap = Math.max(1, d - ((across ? a.w + b.w : a.h + b.h) / 2));
    const waist = Math.min(ha, hb) * clamp(.5 - gap / 260, .14, .5) * (preview ? .7 : 1);  // pinched; thinner as they pull apart
    const ea = (across ? a.w : a.h) / 2 - 8, eb = (across ? b.w : b.h) / 2 - 8;
    const p1 = [ax + ux * ea, ay + uy * ea], p2 = [bx - ux * eb, by - uy * eb], m = [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2];
    const f = n => n.toFixed(1);
    return `M${f(p1[0] + nx * ha)} ${f(p1[1] + ny * ha)} Q${f(m[0] + nx * waist)} ${f(m[1] + ny * waist)} ${f(p2[0] + nx * hb)} ${f(p2[1] + ny * hb)}`
      + ` L${f(p2[0] - nx * hb)} ${f(p2[1] - ny * hb)} Q${f(m[0] - nx * waist)} ${f(m[1] - ny * waist)} ${f(p1[0] - nx * ha)} ${f(p1[1] - ny * ha)}Z`;
  }
  let previewPath = null;

  function physics(fs) {
    const fr = Math.pow(.94, fs);
    for (const t of tiles) {
      if (t.dragging) {  // lag + overshoot behind the finger
        t.vx = (t.vx + (t.tx - t.x) * .2 * fs) * Math.pow(.7, fs);
        t.vy = (t.vy + (t.ty - t.y) * .2 * fs) * Math.pow(.7, fs);
      } else { t.vx *= fr; t.vy *= fr; }
    }
    for (const l of links) {  // soft springs: the rest of a group follows a beat late
      const ex = (l.b.x + l.b.w / 2 + l.rx) - (l.a.x + l.a.w / 2), ey = (l.b.y + l.b.h / 2 + l.ry) - (l.a.y + l.a.h / 2);
      const k = .05 * fs;
      if (!l.a.dragging) { l.a.vx += ex * k; l.a.vy += ey * k; }
      if (!l.b.dragging) { l.b.vx -= ex * k; l.b.vy -= ey * k; }
    }
    if (active) {  // magnet: the nearest tile leans in and a neck previews the join
      const cx = active.tx + active.w / 2, cy = active.ty + active.h / 2, g = group(active);
      let best = null, bd = Infinity;
      for (const o of tiles) {
        if (g.has(o)) continue;
        const [ox, oy] = center(o);
        const d = Math.hypot(ox - cx, oy - cy);
        if (d < Math.max(o.w, o.h) * .75 && d < bd) { best = o; bd = d; }
      }
      if (best !== active.near) {
        active.near?.el.classList.remove('magnet');
        best?.el.classList.add('magnet');
        if (best) { hit(best, 4, 'x'); buzz(6); }
        active.near = best;
      }
      if (best) { const [ox, oy] = center(best); best.vx += (cx - ox) * .01 * fs; best.vy += (cy - oy) * .01 * fs; }
    }
    for (const t of tiles) {
      t.x += t.vx * fs; t.y += t.vy * fs;
      const maxY = Math.max(bh, t.h + PAD * 2);
      if (t.x < PAD) { t.x = PAD; hit(t, Math.abs(t.vx), 'x'); t.vx = Math.abs(t.vx) * .5; }
      if (t.x + t.w > bw - PAD) { t.x = Math.max(PAD, bw - PAD - t.w); hit(t, Math.abs(t.vx), 'x'); t.vx = -Math.abs(t.vx) * .5; }
      if (t.y < PAD) { t.y = PAD; hit(t, Math.abs(t.vy), 'y'); t.vy = Math.abs(t.vy) * .5; }
      if (t.y + t.h > maxY - PAD) { t.y = maxY - PAD - t.h; hit(t, Math.abs(t.vy), 'y'); t.vy = -Math.abs(t.vy) * .5; }
    }
    for (let i = 0; i < tiles.length; i++) {  // free tiles bump into each other; a held tile floats above
      for (let j = i + 1; j < tiles.length; j++) {
        const a = tiles[i], b = tiles[j];
        if (a.dragging || b.dragging || linked(a, b)) continue;
        const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x), oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
        if (ox <= 0 || oy <= 0) continue;
        if (ox < oy) {
          const s = a.x < b.x ? -1 : 1; a.x += s * ox / 2; b.x -= s * ox / 2;
          const rel = a.vx - b.vx;
          if (rel * s < 0) { const e = Math.abs(rel) < 2 ? .5 : .78; a.vx -= rel * e; b.vx += rel * e; hit(a, Math.abs(rel), 'x'); hit(b, Math.abs(rel), 'x'); if (Math.abs(rel) > 9) jolt(Math.abs(rel) * .22, 8); }
        } else {
          const s = a.y < b.y ? -1 : 1; a.y += s * oy / 2; b.y -= s * oy / 2;
          const rel = a.vy - b.vy;
          if (rel * s < 0) { const e = Math.abs(rel) < 2 ? .5 : .78; a.vy -= rel * e; b.vy += rel * e; hit(a, Math.abs(rel), 'y'); hit(b, Math.abs(rel), 'y'); if (Math.abs(rel) > 9) jolt(Math.abs(rel) * .22, 8); }
        }
      }
    }
    for (const t of tiles) {  // two-axis wobble and press squash, each its own under-damped spring
      t.wxv = (t.wxv + (0 - t.wx) * .14 * fs) * Math.pow(.87, fs); t.wx += t.wxv * fs;
      t.wyv = (t.wyv + (0 - t.wy) * .14 * fs) * Math.pow(.87, fs); t.wy += t.wyv * fs;
      t.pv = (t.pv + (t.pt - t.press) * .26 * fs) * Math.pow(.66, fs); t.press += t.pv * fs;
    }
    shake.vx = (shake.vx + (0 - shake.x) * .3 * fs) * Math.pow(.8, fs); shake.x += shake.vx * fs;
    shake.vy = (shake.vy + (0 - shake.y) * .3 * fs) * Math.pow(.8, fs); shake.y += shake.vy * fs;
    shake.vr = (shake.vr + (0 - shake.r) * .3 * fs) * Math.pow(.8, fs); shake.r += shake.vr * fs;
    pulse.v = (pulse.v + (0 - pulse.s) * .22 * fs) * Math.pow(.78, fs); pulse.s += pulse.v * fs;
  }

  function draw() {
    for (const t of tiles) {
      const speed = Math.hypot(t.vx, t.vy);
      t.st += (Math.min(Math.max(0, speed - 1.5) * .011, .2) - t.st) * .2;  // smoothed, and resting jitter never stretches
      if (speed > .5) {
        const d = Math.atan2(Math.sin(Math.atan2(t.vy, t.vx) - t.sa), Math.cos(Math.atan2(t.vy, t.vx) - t.sa));
        t.sa += d * .25;
      }
      const wx = clamp(t.wx, -.25, .25), wy = clamp(t.wy, -.25, .25);
      const sx = (1 + wx) * (1 + t.press * .06), sy = (1 + wy) * (1 - t.press * .1);
      t.el.style.transform = `translate3d(${t.x.toFixed(2)}px,${t.y.toFixed(2)}px,0)`
        + ` rotate(${t.sa.toFixed(4)}rad) scale(${(1 + t.st).toFixed(4)},${(1 - t.st * .45).toFixed(4)}) rotate(${(-t.sa).toFixed(4)}rad)`
        + ` scale(${sx.toFixed(4)},${sy.toFixed(4)})`;
      const blur = speed > 8 ? Math.min((speed - 8) * .06, 2.2) : 0;  // motion blur only when really fast
      if (Math.abs(blur - t.blur) > .08) { t.blur = blur; t.el.style.filter = blur > .08 ? `blur(${blur.toFixed(2)}px)` : ''; }
    }
    for (const l of links) {
      l.path.setAttribute('d', neck(l.a, l.b));
      const [ax] = center(l.a), [bx] = center(l.b);
      const top = Math.min(l.a.y, l.b.y), bottom = Math.max(l.a.y + l.a.h, l.b.y + l.b.h), ph = l.pill.offsetHeight, pw = l.pill.offsetWidth;
      const above = top - ph - 10 >= 0;
      const px = clamp((ax + bx) / 2, pw / 2 + 4, Math.max(pw / 2 + 4, bw - pw / 2 - 4));
      const py = above ? top - 10 : Math.min(bottom + 10, Math.max(ph + 4, (fixed ? bh : bottom + ph + 20) - ph - 6));
      l.pill.style.transform = `translate3d(${px.toFixed(1)}px,${py.toFixed(1)}px,0) translate(-50%,${above ? '-100%' : '0'})`;
    }
    const near = active?.near;
    if (near) {
      if (!previewPath) { previewPath = document.createElementNS(SVG, 'path'); previewPath.setAttribute('class', 'preview'); goo.appendChild(previewPath); }
      previewPath.setAttribute('d', neck(active, near, true));
    } else if (previewPath) { previewPath.remove(); previewPath = null; }
    const moving = Math.abs(shake.x) + Math.abs(shake.y) + Math.abs(shake.r) > .05 || Math.abs(pulse.s) > .0005;
    stage.style.transform = moving ? `translate3d(${shake.x.toFixed(2)}px,${shake.y.toFixed(2)}px,0) rotate(${shake.r.toFixed(3)}deg) scale(${(1 + pulse.s).toFixed(4)})` : '';
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
      t.x = x; t.y = y; measure();
      t.y = Math.max(PAD, y - 50); t.vy = 6; t.vx = (Math.random() - .5) * 3; t.wyv = -.1; t.wxv = .07;
      el.style.zIndex = '2';
      buzz(6);
      return el;
    },
    remove(el) {
      const t = tiles.find(x => x.el === el);
      if (!t) return;
      links.filter(l => l.a === t || l.b === t).forEach(unlink);
      tiles.splice(tiles.indexOf(t), 1);
      el.remove();
    },
    focus(el) {  // bring a tile forward with a little bounce
      const t = tiles.find(x => x.el === el);
      if (!t) return;
      tiles.forEach(x => { x.el.style.zIndex = x === t ? '5' : '2'; });
      t.wyv -= .12; t.wxv += .09; t.vy -= 3;
      ripple(t.x + t.w / 2, t.y + t.h / 2);
      buzz(10);
    },
    scatter,
    split: el => { const t = tiles.find(x => x.el === el); if (t) split(t); },
    stop: () => { cancelAnimationFrame(raf); ro.disconnect(); },
  };
}
