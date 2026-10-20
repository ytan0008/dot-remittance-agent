/* DOT on every page: the effortless way in.

   A small black dot — the same character as on the sign-in stage, its pupil following you — waits at the edge of every
   page. Drag it anywhere; it leans with its speed and, released, is drawn to the nearest side (stronger the closer it is)
   and springs into place. Tap it, or press Ctrl+K, and a compact conversation opens: the same conversation as on the
   assistant page, aware of the page you are on, with two suggestions that fit it. Forms the assistant needs open right
   inside. On a phone it is a bottom sheet you can drag away. Hidden on the assistant page itself. */
import {state, t} from './core.js';
import {esc} from './ui.js';
import {buzz} from './jelly.js';
import {chatLog, composer, send, paint} from './views/agent.js';
import {dragDismiss} from './tactile.js';

const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const SUGGEST = {
  overview: ['aip.overview1', 'aip.overview2'], markets: ['aip.markets1', 'aip.markets2'], send: ['aip.send1', 'aip.send2'],
  spending: ['aip.spending1', 'aip.spending2'], study: ['aip.study1', 'aip.study2'], sandbox: ['aip.sandbox1', 'aip.sandbox2'],
  payments: ['aip.payments1', 'aip.payments2'], progress: ['aip.progress1', 'aip.progress2'],
};
let orb, pop, open = false, pos = null;

function savePos() { try { localStorage.setItem('dot.orb', JSON.stringify(pos)); } catch { /* per-viewer only */ } }
function loadPos() { try { return JSON.parse(localStorage.getItem('dot.orb')); } catch { return null; } }
const phone = () => matchMedia('(max-width: 860px)').matches;

/* Where the dot rests: on one of the four edges (clear of the top bar and the phone dock), at a position along it. */
function rest(x, y) {
  const w = innerWidth, h = innerHeight, size = 56, m = 18, top = 76, bottom = phone() ? 96 : m;
  const dist = {left: x - m, right: w - size - m - x, top: y - top, bottom: h - size - bottom - y};
  const edge = Object.keys(dist).reduce((a, b) => Math.abs(dist[a]) <= Math.abs(dist[b]) ? a : b);
  const cx = clamp(x, m, w - size - m), cy = clamp(y, top, h - size - bottom);
  const to = edge === 'left' ? [m, cy] : edge === 'right' ? [w - size - m, cy] : edge === 'top' ? [cx, top] : [cx, h - size - bottom];
  return {edge, x: to[0], y: to[1]};
}

let springRaf = 0;
/** Release: a real spring toward the nearest edge — it overshoots, hits, squashes along the impact and wobbles back. */
function place(x, y, animate, vx = 0, vy = 0) {
  const r = rest(x + vx * 7, y + vy * 7);  // a fling carries it further before an edge takes it
  pos = {edge: r.edge, x: r.x, y: r.y, side: r.edge === 'left' ? 'left' : 'right'};
  savePos();
  cancelAnimationFrame(springRaf);
  if (!animate || still()) { orb.style.transform = `translate(${r.x}px, ${r.y}px)`; return; }
  const normal = r.edge === 'left' || r.edge === 'right' ? 'x' : 'y';
  let px = x, py = y, sq = 0, sv = 0, last = performance.now(), frames = 0;
  let side = Math.sign((normal === 'x' ? r.x - px : r.y - py)) || 1;
  const step = now => {
    const dt = clamp((now - last) / 16.67, .3, 2.5); last = now;
    vx = (vx + (r.x - px) * .085 * dt) * Math.pow(.83, dt);
    vy = (vy + (r.y - py) * .085 * dt) * Math.pow(.83, dt);
    px += vx * dt; py += vy * dt;
    const now_side = Math.sign(normal === 'x' ? r.x - px : r.y - py) || side;
    if (now_side !== side) {  // it crossed the edge line: the impact squashes it, harder when faster
      sv += clamp(Math.abs(normal === 'x' ? vx : vy) * .022, .06, .32);
      side = now_side;
      if (frames > 2) buzz(6);
    }
    sv = (sv + (0 - sq) * .28 * dt) * Math.pow(.74, dt); sq += sv * dt;
    const a = 1 - sq, b = 1 + sq * .8;
    orb.style.transform = `translate(${px.toFixed(2)}px, ${py.toFixed(2)}px) scale(${(normal === 'x' ? a : b).toFixed(4)}, ${(normal === 'x' ? b : a).toFixed(4)})`;
    frames++;
    const settled = Math.hypot(r.x - px, r.y - py) < .4 && Math.hypot(vx, vy) < .3 && Math.abs(sq) < .004 && Math.abs(sv) < .004;
    if (settled || frames > 240) { orb.style.transform = `translate(${r.x}px, ${r.y}px)`; return; }
    springRaf = requestAnimationFrame(step);
  };
  springRaf = requestAnimationFrame(step);
}

function render() {
  const page = state.view, chips = (SUGGEST[page] || ['agent.s1', 'agent.s2']).map(k => t(k));
  pop.innerHTML = `<header class="ai-pop-head"><span class="agent-orb sm"><i></i></span><div><b>DOT</b><small>${esc(t('aip.on', {p: t('nav.' + page)}))}</small></div>
      <a class="icon-button sm" href="#agent" data-ai-full aria-label="${esc(t('aip.full'))}" title="${esc(t('aip.full'))}">↗</a>
      <button class="icon-button sm" data-ai-close aria-label="${esc(t('common.close'))}">×</button></header>
    <div class="chat-log" id="ai-pop-log">${chatLog(8, true)}</div>
    ${state.chat.messages.length ? '' : `<div class="ai-chips">${chips.map(c => `<button class="pill" data-ai-prompt="${esc(c)}">${esc(c)}</button>`).join('')}</div>`}
    <div id="side-form-host" class="side-form-host ai-form-host"></div>
    ${composer('ai-pop-form')}
    <p class="chat-privacy">${esc(t('privacy.chat_note'))}</p>`;
  const log = pop.querySelector('#ai-pop-log');
  log.scrollTop = log.scrollHeight;
}

export function toggle(force) {
  open = force ?? !open;
  if (open && state.view === 'agent') { open = false; return; }
  pop.hidden = !open;
  orb.classList.toggle('open', open);
  orb.setAttribute('aria-expanded', String(open));
  if (open) {
    if (!phone() && pos) {  // open beside the dot, wherever it rests
      const left = pos.x + 28 < innerWidth / 2;
      const top = Math.round(pos.y + 68), bottom = Math.round(innerHeight - pos.y + 12);
      // open towards whichever side of the dot has more room; it grows with the conversation, never past the screen
      const below = innerHeight - top - 16, above = innerHeight - bottom - 16, high = below >= above;
      Object.assign(pop.style, {left: left ? '18px' : 'auto', right: left ? 'auto' : '18px',
        top: high ? top + 'px' : 'auto', bottom: high ? 'auto' : bottom + 'px', maxHeight: Math.max(above, below) + 'px'});
    } else Object.assign(pop.style, {left: '', right: '', top: '', bottom: '', maxHeight: ''});
    render();
    if (!still()) pop.animate([{opacity: 0, transform: 'translateY(12px) scale(.96)'}, {opacity: 1, transform: 'none'}], {duration: 320, easing: 'cubic-bezier(.2,1.2,.4,1)'});
    setTimeout(() => pop.querySelector('textarea')?.focus(), 60);
    buzz(8);
  }
}

/** Show or hide with the page: never on the sign-in stage or the assistant page; keeps the conversation fresh. */
export function syncAssistant() {
  if (!orb) return;
  const hidden = !state.role || state.view === 'agent' || document.body.classList.contains('auth-on');
  orb.hidden = hidden;
  if (hidden && open) toggle(false);
  if (open) { render(); }
}

export function mountAssistant() {
  if (orb) return;
  orb = document.createElement('button');
  orb.id = 'ai-orb';
  orb.type = 'button';
  orb.setAttribute('aria-label', t('aip.open'));
  orb.setAttribute('aria-expanded', 'false');
  orb.innerHTML = '<i class="ai-pupil"></i>';
  pop = document.createElement('section');
  pop.id = 'ai-pop';
  pop.hidden = true;
  pop.setAttribute('aria-label', 'DOT');
  document.body.append(orb, pop);
  const saved = loadPos();
  place(saved?.x ?? innerWidth, saved?.y ?? innerHeight - 140, false);
  addEventListener('resize', () => place(pos.x, pos.y, false));

  // the pupil follows the pointer
  const pupil = orb.querySelector('.ai-pupil');
  addEventListener('pointermove', e => {
    if (still() || orb.hidden) return;
    const r = orb.getBoundingClientRect(), dx = e.clientX - (r.left + 28), dy = e.clientY - (r.top + 28), d = Math.hypot(dx, dy) || 1, m = Math.min(7, d * .05);
    pupil.style.transform = `translate(${(dx / d * m).toFixed(1)}px, ${(dy / d * m).toFixed(1)}px)`;
  }, {passive: true});

  // drag with lean and stretch; release is drawn to the nearest side
  let drag = null;
  orb.addEventListener('pointerdown', e => {
    cancelAnimationFrame(springRaf);  // caught mid-bounce: it stays where it is and follows the finger
    orb.setPointerCapture(e.pointerId);
    const r = orb.getBoundingClientRect();
    drag = {sx: e.clientX, sy: e.clientY, ox: e.clientX - r.left, oy: e.clientY - r.top, moved: false, x: r.left, y: r.top, vx: 0, vy: 0, t: performance.now()};
  });
  orb.addEventListener('pointermove', e => {
    if (!drag) return;
    if (!drag.moved && Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) < 6) return;
    drag.moved = true;
    const now = performance.now(), dt = Math.max(8, now - drag.t), x = e.clientX - drag.ox, y = e.clientY - drag.oy;
    drag.vx += ((x - drag.x) / dt * 16.67 - drag.vx) * .4; drag.vy += ((y - drag.y) / dt * 16.67 - drag.vy) * .4;
    Object.assign(drag, {x, y, t: now});
    const sp = Math.min(.25, Math.hypot(drag.vx, drag.vy) * .012), a = Math.atan2(drag.vy, drag.vx);
    orb.style.transform = still() ? `translate(${x}px, ${y}px)` : `translate(${x}px, ${y}px) rotate(${a}rad) scale(${1 + sp}, ${1 - sp * .6}) rotate(${-a}rad)`;
    orb.classList.add('dragging');
  });
  const up = () => {
    if (!drag) return;
    const was = drag; drag = null;
    orb.classList.remove('dragging');
    if (!was.moved) { toggle(); return; }
    place(was.x, was.y, true, was.vx, was.vy);
    buzz(10);
  };
  orb.addEventListener('pointerup', up);
  orb.addEventListener('pointercancel', () => { if (drag) { const was = drag; drag = null; orb.classList.remove('dragging'); place(was.x, was.y, true); } });

  pop.addEventListener('submit', () => pop.querySelector('.ai-chips')?.remove(), true);
  pop.addEventListener('click', e => {
    if (e.target.closest('[data-ai-close]')) toggle(false);
    if (e.target.closest('[data-ai-full]')) toggle(false);
    const chip = e.target.closest('[data-ai-prompt]');
    if (chip) { pop.querySelector('.ai-chips')?.remove(); send(chip.dataset.aiPrompt); }
  });
  addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k' && state.role && state.view !== 'agent') { e.preventDefault(); toggle(); }
    if (e.key === 'Escape' && open) toggle(false);
  });
  dragDismiss(pop, () => toggle(false), 'y');
  syncAssistant();
  // the conversation repaints in place while it streams (agent.js paints every #...-log it finds)
  void paint;
}
