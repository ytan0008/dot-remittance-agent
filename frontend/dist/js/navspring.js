/* The ink blob behind the active navigation item.

   The motion runs on the compositor (Web Animations, transform only), so it stays smooth even while the new page is
   being built on the main thread. The items never change size. On a switch the blob takes the new item's size and glides
   from wherever it currently is (mid-flight included) with a smooth ease-out: no overshoot, no squash, no bounce.
   In the sidebar it reaches EXTEND pixels past the item's right edge, so the active item reads as longer. */

const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const blobs = new Map();
const EXTEND = 22;
const EASE = 'cubic-bezier(.22,.8,.26,1)';

function measure(container, axis) {
  const act = container.querySelector('a.active, button.active');
  if (!act) return null;
  const box = container.getBoundingClientRect(), r = act.getBoundingClientRect();
  return {x: r.left - box.left + container.scrollLeft, y: r.top - box.top + container.scrollTop,
          w: r.width + (axis === 'y' ? EXTEND : 0), h: r.height, itemW: r.width};
}

export function springNav(container, axis = 'y') {
  if (!container) return;
  let s = blobs.get(container.id);
  if (!s || !s.el.isConnected) {
    const el = document.createElement('span');
    el.className = 'nav-blob';
    el.setAttribute('aria-hidden', 'true');
    el.innerHTML = '<i></i>';
    s = {el, w: 0, h: 0, x: null, y: null, anim: null};
    blobs.set(container.id, s);
  }
  if (container.firstChild !== s.el) container.prepend(s.el);
  container.classList.add('has-blob');
  const t = measure(container, axis);
  if (!t || !t.h) { s.el.style.opacity = '0'; return; }
  s.el.style.opacity = '1';
  const final = `translate3d(${t.x}px,${t.y}px,0) scale(1,1)`;
  const first = s.x === null || still();
  if (!first && s.x === t.x && s.y === t.y && s.w === t.w && s.h === t.h) return;  // nothing moved
  // Where the blob is right now (an animation may be running), in pixels.
  const now = new DOMMatrixReadOnly(getComputedStyle(s.el).transform === 'none' ? undefined : getComputedStyle(s.el).transform);
  const oldX = now.e, oldY = now.f, oldW = s.w * now.a, oldH = s.h * now.d;
  s.anim?.cancel();
  s.el.style.width = t.w + 'px'; s.el.style.height = t.h + 'px';
  s.el.style.transform = final;
  const moved = Math.abs(oldY - t.y) + Math.abs(oldX - t.x);
  Object.assign(s, {w: t.w, h: t.h, x: t.x, y: t.y});
  if (first || !moved && !oldW) return;
  const from = `translate3d(${oldX}px,${oldY}px,0) scale(${(oldW / t.w).toFixed(4)},${(oldH / t.h).toFixed(4)})`;
  const ms = Math.round(Math.min(380, 240 + moved * .25));
  s.anim = s.el.animate([{transform: from}, {transform: final}], {duration: ms, easing: EASE});
}

let resizing = 0;
addEventListener('resize', () => {
  clearTimeout(resizing);
  resizing = setTimeout(() => { for (const id of blobs.keys()) springNav(document.getElementById(id), id === 'dock' ? 'x' : 'y'); }, 80);
});
