/* Titles that swell and lean with the cursor.

   Each letter is a measured "ghost" (invisible, keeps the line's layout) with the visible glyph laid over it. The glyph
   grows by real font-size, never by transform scaling, so it stays sharp at any size. Near the cursor a letter grows,
   gets a little heavier and a little flatter, drifts toward the cursor, and leans and stretches the way the cursor is
   moving — like soft jelly being pushed. Neighbours slide outward by exactly the width the swollen letters gained, so
   nothing overlaps. Every letter's strength is an under-damped spring, so it swells and settles back smoothly (no
   snapping when the cursor leaves). Sizes come from the title's computed font size; nothing is hard-coded per page. */

const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const fine = () => matchMedia('(hover: hover) and (pointer: fine)').matches;
const pointer = {x: -1e4, y: -1e4, sx: -1e4, sy: -1e4, vx: 0, vy: 0, inside: false};
let letters = [], running = false, listening = false;

const GROW = .42, WEIGHT = 180, clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const smoothstep = t => t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t);

function listen() {
  if (listening) return;
  listening = true;
  addEventListener('pointermove', e => {
    if (e.pointerType !== 'mouse') return;
    if (!pointer.inside) { pointer.sx = e.clientX; pointer.sy = e.clientY; }  // no sweep in from the corner
    pointer.x = e.clientX; pointer.y = e.clientY; pointer.inside = true;
  }, {passive: true});
  document.addEventListener('pointerleave', () => { pointer.inside = false; });
  addEventListener('blur', () => { pointer.inside = false; });
}

/** Split the text of every title in root into ghost/glyph letter pairs (idempotent). */
export function deformTitles(root, selector = '.page-head h1') {
  if (still() || !fine()) return;
  root.querySelectorAll(selector).forEach(el => {
    if (el.dataset.deform) return;
    el.dataset.deform = '1';
    // Read the title, not its letters (the decorative trailing dot is an <i> and is skipped).
    el.setAttribute('aria-label', [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').replace(/\s+/g, ' ').trim());
    const style = getComputedStyle(el);
    const base = Number(style.fontWeight) || 500;
    const walk = node => {
      for (const child of [...node.childNodes]) {
        if (child.nodeType === 3) {
          const frag = document.createDocumentFragment();
          for (const ch of child.textContent) {
            if (/\s/.test(ch)) { frag.appendChild(document.createTextNode(ch)); continue; }  // keep natural line breaks
            const outer = document.createElement('span');
            outer.className = 'dl';
            outer.setAttribute('aria-hidden', 'true');
            const ghost = document.createElement('span');
            ghost.className = 'dl-g';
            ghost.textContent = ch;
            const glyph = document.createElement('span');
            glyph.className = 'dl-i';
            glyph.textContent = ch;
            outer.append(ghost, glyph);
            frag.appendChild(outer);
            letters.push({outer, glyph, title: el, base, size: 0, g: 0, gv: 0, sk: 0, skv: 0, ox: 0, oy: 0, r: null, live: false});
          }
          child.replaceWith(frag);
        } else if (child.nodeType === 1) {
          walk(child);
        }
      }
    };
    walk(el);
  });
  letters = letters.filter(l => l.outer.isConnected);
  listen();
  if (!running && letters.length) { running = true; requestAnimationFrame(frame); }
}

function rest(l) {
  if (!l.live) return;
  l.live = false;
  l.glyph.style.fontSize = l.glyph.style.fontVariationSettings = l.glyph.style.transform = '';
}

let sizes = new Map(), sizedAt = 0;
function frame(now) {
  letters = letters.filter(l => l.outer.isConnected);
  if (!letters.length) { running = false; return; }
  requestAnimationFrame(frame);
  if (document.hidden) return;
  if (now - sizedAt > 500) { sizes = new Map(); sizedAt = now; }  // responsive titles change size; re-read twice a second
  const px = pointer.sx, py = pointer.sy;
  pointer.sx += (pointer.x - pointer.sx) * .3;
  pointer.sy += (pointer.y - pointer.sy) * .3;
  pointer.vx += ((pointer.sx - px) - pointer.vx) * .25;  // smoothed cursor velocity, px per frame
  pointer.vy += ((pointer.sy - py) - pointer.vy) * .25;
  const vh = innerHeight;
  const titles = new Map();
  for (const l of letters) {
    if (!sizes.has(l.title)) sizes.set(l.title, parseFloat(getComputedStyle(l.title).fontSize) || 32);
    l.size = sizes.get(l.title);
    const r = l.outer.getBoundingClientRect();
    l.r = r;
    if (r.bottom < -40 || r.top > vh + 40) { l.r = null; rest(l); continue; }
    let target = 0;
    if (pointer.inside) {
      const dx = (pointer.sx - (r.left + r.width / 2)) / (l.size * 2.2);
      const dy = (pointer.sy - (r.top + r.height / 2)) / (l.size * 1.25);
      target = smoothstep(1 - Math.hypot(dx, dy));
    }
    // An under-damped spring: swells with a soft overshoot and settles back without a snap.
    l.gv = (l.gv + (target - l.g) * .14) * .7;
    l.g += l.gv;
    if (Math.abs(l.g) < .0015 && Math.abs(l.gv) < .0015 && target === 0) { l.g = l.gv = 0; }
    if (!titles.has(l.title)) titles.set(l.title, []);
    titles.get(l.title).push(l);
  }
  for (const list of titles.values()) {
    const lines = [];
    for (const l of list) {
      const ln = lines.find(x => Math.abs(x.top - l.r.top) < l.size * .5);
      if (ln) ln.items.push(l); else lines.push({top: l.r.top, items: [l]});
    }
    for (const {items} of lines) {
      items.sort((a, b) => a.r.left - b.r.left);
      const cx = pointer.sx;
      for (const l of items) l.shift = 0;
      // Make room: letters left of the cursor slide left by what the swollen letters between them gained; right side mirrors.
      let acc = 0;
      for (const l of [...items].filter(l => l.r.left + l.r.width / 2 < cx).reverse()) {
        const extra = l.r.width * GROW * Math.max(0, l.g);
        l.shift = -(acc + extra / 2); acc += extra;
      }
      acc = 0;
      for (const l of items.filter(l => l.r.left + l.r.width / 2 >= cx)) {
        const extra = l.r.width * GROW * Math.max(0, l.g);
        l.shift = acc + extra / 2; acc += extra;
      }
      const first = items[0];  // the title's start barely moves: slide the line right instead of pushing letters out
      const lead = Math.min(0, first.shift - first.r.width * GROW * Math.max(0, first.g) / 2 + first.size * .15);
      if (lead < 0) for (const l of items) l.shift -= lead;
      for (const l of items) {
        const g = l.g;
        // follow the cursor a little, and lean / stretch the way it moves
        const tx = clamp((pointer.sx - (l.r.left + l.r.width / 2)) * .14 * g, -l.size * .22, l.size * .22);
        const ty = clamp((pointer.sy - (l.r.top + l.r.height / 2)) * .2 * g, -l.size * .16, l.size * .16);
        l.ox += (tx - l.ox) * .25; l.oy += (ty - l.oy) * .25;
        const lean = clamp(-pointer.vx * 1.1, -16, 16) * Math.max(0, g);
        l.skv = (l.skv + (lean - l.sk) * .16) * .72; l.sk += l.skv;
        if (g === 0 && Math.abs(l.shift) < .05 && Math.abs(l.sk) < .05 && Math.abs(l.ox) < .05 && Math.abs(l.oy) < .05) { rest(l); continue; }
        l.live = true;
        const stretch = 1 + Math.min(Math.hypot(pointer.vx, pointer.vy) * .006, .1) * Math.max(0, g);
        l.glyph.style.fontSize = (l.size * (1 + GROW * g)).toFixed(2) + 'px';
        l.glyph.style.fontVariationSettings = `'wght' ${Math.round(Math.min(900, l.base + WEIGHT * Math.max(0, g)))}`;
        l.glyph.style.transform = `translate(calc(-50% + ${(l.shift + l.ox).toFixed(2)}px), ${(l.oy + l.size * .06 * g).toFixed(2)}px) skewX(${l.sk.toFixed(2)}deg) scale(${stretch.toFixed(4)}, ${(1 - .05 * Math.max(0, g)).toFixed(4)})`;
      }
    }
  }
}
