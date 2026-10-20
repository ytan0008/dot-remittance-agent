/* Motion: dot field, depth transitions, reveal, tilt, count-up, swipe, hold-to-confirm.
   Everything degrades to static when the user prefers reduced motion. */
export const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/* ---------- background: dot grid with a magnifying lens and a drifting constellation ---------- */
export function field(canvas) {
  const ctx = canvas.getContext('2d');
  const gap = 26;
  let w = 0, h = 0, dpr = 1, raf = 0, last = 0;
  const pointer = {x: -999, y: -999, tx: -999, ty: -999, active: 0};
  const nodes = Array.from({length: 16}, (_, i) => ({
    x: Math.random(), y: Math.random(), r: i % 5 === 0 ? 18 + Math.random() * 30 : 1.6 + Math.random() * 1.8,
    vx: (Math.random() - .5) * .00008, vy: (Math.random() - .5) * .00008, ring: i % 5 === 0,
  }));
  function size() {
    dpr = Math.min(2, devicePixelRatio || 1);
    w = innerWidth; h = innerHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  function frame(time) {
    const dt = Math.min(48, time - last || 16); last = time;
    pointer.x += (pointer.tx - pointer.x) * .14; pointer.y += (pointer.ty - pointer.y) * .14;
    pointer.active += ((pointer.tx > -900 ? 1 : 0) - pointer.active) * .06;
    ctx.clearRect(0, 0, w, h);
    const ink = css('--field-ink') || '#111';
    const scroll = scrollY * .12;
    // Lens: grid dots near the pointer swell and push outward (the base grid itself is CSS).
    if (pointer.active > .02) {
      const R = 150, ox = 0, oy = -(scroll % gap);
      const x0 = Math.floor((pointer.x - R) / gap) * gap, y0 = Math.floor((pointer.y - R - oy) / gap) * gap;
      ctx.fillStyle = ink;
      for (let gx = x0; gx < pointer.x + R; gx += gap) {
        for (let gy = y0; gy < pointer.y + R; gy += gap) {
          const px = gx + ox + gap / 2, py = gy + oy + gap / 2;
          const dx = px - pointer.x, dy = py - pointer.y, d = Math.hypot(dx, dy);
          if (d > R) continue;
          const k = (1 - d / R) ** 2 * pointer.active;
          ctx.globalAlpha = .08 + k * .5;
          ctx.beginPath();
          ctx.arc(px + dx * k * .25, py + dy * k * .25, .9 + k * 2.6, 0, 6.283);
          ctx.fill();
        }
      }
    }
    // Constellation: points, thin lines and hollow circles drifting slowly.
    const pts = nodes.map(n => {
      n.x += n.vx * dt; n.y += n.vy * dt;
      if (n.x < -.05 || n.x > 1.05) n.vx *= -1;
      if (n.y < -.05 || n.y > 1.05) n.vy *= -1;
      let x = n.x * w, y = n.y * h - scroll * (n.ring ? .4 : .8);
      y = ((y % (h + 80)) + h + 80) % (h + 80) - 40;
      const dx = pointer.x - x, dy = pointer.y - y, d = Math.hypot(dx, dy);
      if (d < 220) { x += dx * .04 * pointer.active; y += dy * .04 * pointer.active; }
      return {x, y, n};
    });
    ctx.strokeStyle = ink; ctx.lineWidth = .6;
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const d = Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y);
        if (d < 230) {
          ctx.globalAlpha = (1 - d / 230) * .16;
          ctx.setLineDash(d > 140 ? [2, 4] : []);
          ctx.beginPath(); ctx.moveTo(pts[i].x, pts[i].y); ctx.lineTo(pts[j].x, pts[j].y); ctx.stroke();
        }
      }
    }
    ctx.setLineDash([]);
    for (const p of pts) {
      if (p.n.ring) {
        ctx.globalAlpha = .12; ctx.beginPath(); ctx.arc(p.x, p.y, p.n.r, 0, 6.283); ctx.stroke();
        ctx.globalAlpha = .3; ctx.beginPath();
        const a = time / 2400 + p.n.r;
        ctx.arc(p.x + Math.cos(a) * p.n.r, p.y + Math.sin(a) * p.n.r, 2, 0, 6.283); ctx.fillStyle = ink; ctx.fill();
      } else {
        ctx.globalAlpha = .28; ctx.fillStyle = ink; ctx.beginPath(); ctx.arc(p.x, p.y, p.n.r, 0, 6.283); ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
    raf = requestAnimationFrame(frame);
  }
  function start() { cancelAnimationFrame(raf); if (!document.hidden && !reduced()) raf = requestAnimationFrame(frame); else ctx.clearRect(0, 0, w, h); }
  size();
  addEventListener('resize', size);
  addEventListener('pointermove', e => { if (e.pointerType === 'mouse') { pointer.tx = e.clientX; pointer.ty = e.clientY; } }, {passive: true});
  document.addEventListener('pointerleave', () => { pointer.tx = pointer.ty = -999; });
  document.addEventListener('visibilitychange', start);
  matchMedia('(prefers-reduced-motion: reduce)').addEventListener?.('change', start);
  start();
}

/* ---------- view transitions: push far / pull close with blur, or slide for swipes ---------- */
export async function transition(update, mode = 'forward') {
  const root = document.documentElement;
  if (reduced()) { await update(); return; }
  root.dataset.vt = mode;
  if (document.startViewTransition) {
    const vt = document.startViewTransition(update);
    try { await vt.finished; } catch {}
    delete root.dataset.vt;
    return;
  }
  const view = document.getElementById('view');
  const out = {forward: 'scale(.95)', back: 'scale(1.05)', left: 'translateX(-48px)', right: 'translateX(48px)'}[mode];
  await view.animate([{opacity: 1, transform: 'none', filter: 'blur(0)'}, {opacity: 0, transform: out, filter: 'blur(8px)'}],
    {duration: 160, easing: 'cubic-bezier(.4,0,1,1)', fill: 'forwards'}).finished.catch(() => {});
  await update();
  const from = {forward: 'scale(1.05)', back: 'scale(.95)', left: 'translateX(48px)', right: 'translateX(-48px)'}[mode];
  view.animate([{opacity: 0, transform: from, filter: 'blur(10px)'}, {opacity: 1, transform: 'none', filter: 'blur(0)'}],
    {duration: 420, easing: 'cubic-bezier(.16,1,.3,1)'});
  delete root.dataset.vt;
}

/* ---------- scroll reveal with stagger ---------- */
let observer;
export function reveal(root) {
  const items = root.querySelectorAll('.reveal:not(.in)');
  if (reduced() || !('IntersectionObserver' in window)) { items.forEach(el => el.classList.add('in')); return; }
  observer ??= new IntersectionObserver(entries => {
    for (const e of entries) if (e.isIntersecting) { e.target.classList.add('in'); observer.unobserve(e.target); }
  }, {rootMargin: '0px 0px -6% 0px', threshold: .04});
  items.forEach((el, i) => { el.style.transitionDelay = Math.min(i, 8) * 55 + 'ms'; observer.observe(el); });
}

/* ---------- (no tilt, no magnetic buttons) ----------
   Removed on purpose: a key button must not chase the cursor (its hit area becomes unpredictable), and tilting a whole data
   panel is not layered parallax — these pages have no foreground/background layers to separate. Kept as a no-op so callers
   stay simple. */
export function interactive() {}

/* ---------- count-up numbers: animate approximately, land on the exact formatted text ---------- */
export function countUp(root, format) {
  root.querySelectorAll('[data-count]').forEach(el => {
    const target = Number(el.dataset.count), final = el.textContent;
    if (reduced() || !isFinite(target) || el.dataset.counted === final) return;
    el.dataset.counted = final;
    const from = Number(el.dataset.from || 0), start = performance.now(), dur = 900;
    const digits = Number(el.dataset.digits ?? 2);
    const step = now => {
      const k = Math.min(1, (now - start) / dur), e = 1 - (1 - k) ** 4;
      el.textContent = k < 1 ? format(from + (target - from) * e, digits) : final;
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

/* ---------- swipe between sections on touch screens ---------- */
export function swipe(el, onSwipe) {
  let start = null;
  el.addEventListener('touchstart', e => {
    const t = e.touches[0];
    if (e.touches.length !== 1 || e.target.closest('input,textarea,select,.no-swipe,.hscroll,.table-wrap,svg,dialog')) { start = null; return; }
    start = {x: t.clientX, y: t.clientY, time: Date.now()};
  }, {passive: true});
  el.addEventListener('touchend', e => {
    if (!start) return;
    const t = e.changedTouches[0], dx = t.clientX - start.x, dy = t.clientY - start.y;
    if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.6 && Date.now() - start.time < 600) onSwipe(dx < 0 ? 'left' : 'right');
    start = null;
  }, {passive: true});
}

/* ---------- press and hold to confirm (deliberate authorization) ---------- */
export function hold(button, ms, done) {
  let timer = 0, startTime = 0;
  const begin = e => {
    if (button.disabled || timer) return;
    if (e.type === 'keydown' && !['Enter', ' '].includes(e.key)) return;
    e.preventDefault();
    startTime = performance.now();
    button.classList.add('holding');
    button.style.setProperty('--hold', ms + 'ms');
    timer = setTimeout(() => { timer = 0; button.classList.remove('holding'); button.classList.add('held'); done(); }, ms);
  };
  const cancel = () => { if (!timer) return; clearTimeout(timer); timer = 0; button.classList.remove('holding'); };
  button.addEventListener('pointerdown', begin);
  button.addEventListener('keydown', begin);
  for (const ev of ['pointerup', 'pointerleave', 'pointercancel', 'keyup', 'blur']) button.addEventListener(ev, cancel);
  button.addEventListener('click', e => e.preventDefault());
}

/* ---------- scroll progress hairline ---------- */
export function progress(el) {
  const update = () => {
    const max = document.documentElement.scrollHeight - innerHeight;
    el.style.transform = `scaleX(${max > 0 ? Math.min(1, scrollY / max) : 0})`;
  };
  addEventListener('scroll', update, {passive: true}); addEventListener('resize', update); update();
}
