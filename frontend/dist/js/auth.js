/* Sign in / sign up — one question at a time, asked by a living dot.

   No boxes and no wall of fields. A big jelly dot sits in the middle of the page: it leans toward the cursor, its pupil
   follows you, it stretches along its own velocity and wobbles after every impact (under-damped springs, integrated per
   frame time so 60 and 120 Hz feel the same). Grab it and it squashes and pulls; let go and it bounces back. It nods at
   each key you type, closes its eye while you type a password, shakes its head (and the phone) when something is wrong,
   and swells to fill the screen when you are in. Haptics use navigator.vibrate where it exists; every jolt is also a
   visible shake. With reduced motion everything stays still and the flow works the same. */
import {t, api} from './core.js';
import {LANGS, lang, setLang} from './i18n.js';
import {esc} from './ui.js';
import {buzz} from './jelly.js';

const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

/** The physics of the dot: position, velocity, squash, a bounce spring, a shake spring and the pupil. */
function creature(stage, blob, pupil) {
  const s = {x: 0, y: 0, vx: 0, vy: 0, b: 1, vb: 0, sh: 0, vsh: 0, px: 0, py: 0, vpx: 0, vpy: 0, lid: 1, wob: 0, mx: null, my: null,
    grab: null, closed: false, thinking: false, alive: true};
  let last = performance.now(), raf = 0;
  const center = () => { const r = stage.getBoundingClientRect(); return {cx: r.left + r.width / 2, cy: r.top + r.height / 2, r: Math.min(r.width, r.height) / 2}; };
  const onMove = e => { s.mx = e.clientX; s.my = e.clientY; if (s.grab) e.preventDefault(); };
  const onDown = e => {
    if (!blob.contains(e.target)) return;
    s.grab = {id: e.pointerId}; blob.setPointerCapture?.(e.pointerId); s.vb -= .12; buzz(8);
  };
  const onUp = () => { if (!s.grab) return; s.grab = null; s.vb += .22; s.wob = 1; buzz(12); };
  addEventListener('pointermove', onMove, {passive: false});
  blob.addEventListener('pointerdown', onDown);
  addEventListener('pointerup', onUp);
  addEventListener('pointercancel', onUp);

  function frame(now) {
    if (!s.alive) return;
    const dt = clamp((now - last) / 16.67, .2, 3); last = now;
    const {cx, cy, r} = center();
    // where it wants to be: dragged under the finger, or leaning a little toward the cursor
    let tx = 0, ty = 0;
    if (s.mx != null) {
      const dx = s.mx - cx, dy = s.my - cy;
      if (s.grab) { tx = clamp(dx, -r * 1.6, r * 1.6); ty = clamp(dy, -r * 1.6, r * 1.6); }
      else { const d = Math.hypot(dx, dy) || 1, pull = Math.min(36, d * .08); tx = dx / d * pull; ty = dy / d * pull; }
    }
    const k = s.grab ? .18 : .07, damp = Math.pow(s.grab ? .7 : .84, dt);
    s.vx = (s.vx + (tx - s.x) * k * dt) * damp; s.vy = (s.vy + (ty - s.y) * k * dt) * damp;
    s.x += s.vx * dt; s.y += s.vy * dt;
    s.vb = (s.vb + (1 - s.b) * .16 * dt) * Math.pow(.8, dt); s.b += s.vb * dt;            // bounce
    s.vsh = (s.vsh + (0 - s.sh) * .22 * dt) * Math.pow(.78, dt); s.sh += s.vsh * dt;      // head shake
    s.wob *= Math.pow(.96, dt);
    // pupil: toward the cursor, inside the body
    let ptx = 0, pty = 0;
    if (s.mx != null) { const dx = s.mx - cx - s.x, dy = s.my - cy - s.y, d = Math.hypot(dx, dy) || 1, m = Math.min(r * .34, d * .12); ptx = dx / d * m; pty = dy / d * m; }
    if (s.thinking) { ptx = Math.cos(now / 260) * r * .22; pty = Math.sin(now / 260) * r * .22; }
    s.vpx = (s.vpx + (ptx - s.px) * .2 * dt) * Math.pow(.72, dt); s.vpy = (s.vpy + (pty - s.py) * .2 * dt) * Math.pow(.72, dt);
    s.px += s.vpx * dt; s.py += s.vpy * dt;
    s.lid += ((s.closed ? .12 : 1) - s.lid) * .25 * dt;
    // squash and stretch along the velocity, plus a gooey outline that ripples after impacts
    const speed = Math.hypot(s.vx, s.vy), a = Math.atan2(s.vy, s.vx), st = 1 + Math.min(.28, speed * .018);
    const w = s.wob * 9 + (s.thinking ? 4 : 0), ph = now / 140;
    const rad = [0, 1, 2, 3].map(i => 50 + Math.sin(ph + i * 1.7) * w);
    blob.style.borderRadius = `${rad[0]}% ${100 - rad[0]}% ${rad[1]}% ${100 - rad[1]}% / ${rad[2]}% ${rad[3]}% ${100 - rad[3]}% ${100 - rad[2]}%`;
    blob.style.transform = `translate(${s.x + s.sh}px, ${s.y}px) rotate(${a}rad) scale(${st * s.b}, ${s.b / st}) rotate(${-a}rad)`;
    pupil.style.transform = `translate(${s.px}px, ${s.py}px) scaleY(${s.lid})`;
    raf = requestAnimationFrame(frame);
  }
  if (!still()) raf = requestAnimationFrame(frame);
  return {
    nod() { s.vb -= .07; s.vy += 2.2; },
    hop() { s.vb += .3; s.wob = 1; s.vy -= 6; },
    shake() { s.vsh += 26; setTimeout(() => { s.vsh -= 30; }, 90); setTimeout(() => { s.vsh += 20; }, 190); s.wob = .8; },
    eye(closed) { s.closed = closed; },
    think(on) { s.thinking = on; if (on) s.wob = .6; },
    stop() { s.alive = false; cancelAnimationFrame(raf); removeEventListener('pointermove', onMove); removeEventListener('pointerup', onUp); removeEventListener('pointercancel', onUp); },
  };
}

/** The dot flies into the app: it becomes the brand ring (desktop) or your avatar (phone) while the app fades in under it.
    Shared-element expansion in reverse: the source and the target are the same shape, a black circle with a light centre. */
function handoff(host, blob, pupil) {
  const pick = ['.sidebar .brand-mark', '#avatar'].map(sel => document.querySelector(sel)).find(el => el && el.getBoundingClientRect().width > 0);
  document.body.classList.add('auth-reveal');
  document.body.classList.remove('auth-on');
  const finish = () => {
    host.remove();
    document.body.classList.remove('auth-reveal', 'auth-reveal-in');
    if (pick) { pick.classList.remove('handoff-pop'); void pick.offsetWidth; pick.classList.add('handoff-pop'); }
  };
  if (still() || !pick) { finish(); return Promise.resolve(); }
  host.classList.add('handoff');
  requestAnimationFrame(() => document.body.classList.add('auth-reveal-in'));
  const from = blob.getBoundingClientRect(), to = pick.getBoundingClientRect();
  const dx = (to.left + to.width / 2) - (from.left + from.width / 2), dy = (to.top + to.height / 2) - (from.top + from.height / 2);
  const k = to.width / from.width, ring = pick.id !== 'avatar';
  const now = getComputedStyle(blob).transform;
  blob.style.borderRadius = '50%';
  const fly = blob.animate([
    {transform: now === 'none' ? 'none' : now},
    {transform: `translate(${dx * 1.03}px, ${dy * 1.03}px) scale(${k * .92})`, offset: .78},
    {transform: `translate(${dx}px, ${dy}px) scale(${k})`}], {duration: 760, easing: 'cubic-bezier(.65,0,.25,1)', fill: 'forwards'});
  // the pupil opens into the ring's hole (15 of 28 px), or fades for the avatar's letter
  pupil.animate([{transform: getComputedStyle(pupil).transform, opacity: 1},
    {transform: ring ? 'scale(2.45)' : 'scale(.4)', opacity: ring ? 1 : 0}], {duration: 760, easing: 'cubic-bezier(.65,0,.25,1)', fill: 'forwards'});
  return fly.finished.then(finish, finish);
}

/** Shows the sign-in stage; resolves once signed in and the app is on screen. onSignedIn: builds the app underneath
    (session, first page) before the dot hands over, so nothing pops in after the curtain. */
export function authScreen(health = {}, onSignedIn = async () => {}) {
  return new Promise(resolve => {
    document.body.classList.add('auth-on');
    const host = document.createElement('div');
    host.id = 'auth';
    host.className = 'auth';
    host.setAttribute('role', 'dialog');
    host.setAttribute('aria-modal', 'true');
    host.setAttribute('aria-labelledby', 'auth-q');
    host.innerHTML = `<div class="auth-brand"><span class="brand-word">dot<em>.</em></span><small>${esc(t('shell.tagline'))}</small></div>
      <label class="auth-lang"><span class="sr-only">${esc(t('settings.language'))}</span><select aria-label="${esc(t('settings.language'))}">${LANGS.map(([c, n]) => `<option value="${c}" ${c === lang ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></label>
      <div class="auth-stage" aria-hidden="true"><div class="auth-halo"></div><div class="auth-blob"><i class="auth-pupil"></i></div></div>
      <form class="auth-flow" novalidate autocomplete="on"></form>
      <div class="auth-steps" aria-hidden="true"></div>
      <p class="auth-note">${esc(t('auth.note'))}</p>`;
    document.body.appendChild(host);
    const form = host.querySelector('.auth-flow'), steps = host.querySelector('.auth-steps');
    const blob = host.querySelector('.auth-blob'), pupil = host.querySelector('.auth-pupil');
    const dot = creature(host.querySelector('.auth-stage'), blob, pupil);
    const flow = {mode: null, step: 'choose', email: '', password: '', name: '', token: ''};
    const order = () => flow.mode === 'register' ? ['email', 'password', 'name'] : flow.mode === 'login' ? ['email', 'password']
      : flow.mode === 'claim' ? ['email', 'password', 'owner'] : flow.mode === 'token' ? ['token'] : [];
    // switching the language re-says everything on the stage, without losing the step you are on
    host.querySelector('.auth-lang select').addEventListener('change', async e => {
      await setLang(e.target.value);
      document.documentElement.lang = lang;
      host.querySelector('.auth-brand small').textContent = t('shell.tagline');
      host.querySelector('.auth-note').textContent = t('auth.note');
      const typed = form.querySelector('#auth-in')?.value;
      render(0);
      if (typed != null && form.querySelector('#auth-in')) form.querySelector('#auth-in').value = typed;
      buzz(6);
    });

    function strength(p) {
      let n = 0;
      if (p.length >= 8) n++;
      if (p.length >= 12) n++;
      if (/[0-9]/.test(p) && /[a-zA-Z]/.test(p)) n++;
      if (/[^a-zA-Z0-9]/.test(p) || /[一-鿿]/.test(p)) n++;
      return Math.min(3, n);
    }

    function render(dir = 1) {
      const q = flow.step;
      dot.eye(q === 'password' || q === 'token');
      const seq = order();
      steps.innerHTML = seq.map(x => `<i class="${x === q ? 'on' : seq.indexOf(x) < seq.indexOf(q) ? 'done' : ''}"></i>`).join('');
      let body;
      if (q === 'choose') {
        body = `<h1 id="auth-q" class="auth-q">${esc(t(health.accounts ? 'auth.hello_back' : 'auth.hello'))}</h1>
          <p class="auth-sub">${esc(t('auth.sub'))}</p>
          <div class="auth-pills">
            <button type="button" class="auth-pill solid" data-go="login">${esc(t('auth.login'))}</button>
            ${health.signup !== false ? `<button type="button" class="auth-pill" data-go="register">${esc(t(health.accounts ? 'auth.register' : 'auth.register_first'))}</button>` : ''}
          </div>
          <div class="auth-links">${health.demo_login ? `<button type="button" class="link sm" data-go="demo">${esc(t('auth.demo'))}</button>` : ''}
            <button type="button" class="link sm" data-go="claim">${esc(t('auth.claim_link'))}</button>
            <button type="button" class="link sm" data-go="token">${esc(t('auth.token_link'))}</button></div>`;
      } else {
        const input = q === 'email' ? `<input id="auth-in" name="email" type="email" inputmode="email" autocomplete="username" required maxlength="254" value="${esc(flow.email)}" placeholder="you@example.com">`
          : q === 'password' ? `<input id="auth-in" name="password" type="password" autocomplete="${flow.mode === 'login' ? 'current-password' : 'new-password'}" required maxlength="200" placeholder="••••••••">
              <button type="button" class="auth-peek" data-peek aria-label="${esc(t('auth.peek'))}"><i></i></button>`
          : q === 'name' ? `<input id="auth-in" name="name" autocomplete="nickname" maxlength="60" value="${esc(flow.name)}" placeholder="${esc(t('auth.name_ph'))}">`
          : q === 'owner' ? `<input id="auth-in" name="owner_token" type="password" autocomplete="off" required minlength="24" placeholder="OWNER_TOKEN">`
          : `<input id="auth-in" name="token" type="password" autocomplete="off" required minlength="24" placeholder="Owner / Agent / Viewer">`;
        body = `<button type="button" class="auth-back" data-back aria-label="${esc(t('common.back'))}">←</button>
          <label for="auth-in" id="auth-q" class="auth-q">${esc(t(`auth.q.${q}${q === 'password' ? '_' + (flow.mode === 'claim' ? 'register' : flow.mode) : ''}`))}</label>
          <div class="auth-line">${input}<span class="auth-ink"></span>
            <button class="auth-go" aria-label="${esc(t('auth.next'))}">→</button></div>
          ${q === 'password' && flow.mode !== 'login' ? `<div class="auth-meter" aria-hidden="true"><i></i><i></i><i></i></div>` : ''}
          <p class="auth-hint" id="auth-hint">${esc(t(`auth.h.${q}${q === 'password' ? '_' + (flow.mode === 'claim' ? 'register' : flow.mode) : ''}`))}</p>
          <p class="auth-err" role="alert"></p>
          ${q === 'name' ? `<button type="button" class="link sm" data-skip>${esc(t('auth.skip'))}</button>` : ''}`;
      }
      form.classList.remove('in', 'back');
      form.innerHTML = body;
      void form.offsetWidth;
      form.classList.add('in', dir < 0 ? 'back' : 'fwd');
      const input = form.querySelector('#auth-in');
      if (input) {
        input.setAttribute('aria-describedby', 'auth-hint');
        setTimeout(() => input.focus({preventScroll: true}), 60);
        input.addEventListener('input', () => {
          dot.nod();
          const ink = form.querySelector('.auth-ink');
          ink?.classList.remove('kick'); void ink?.offsetWidth; ink?.classList.add('kick');
          form.querySelector('.auth-err').textContent = '';
          const meter = form.querySelector('.auth-meter');
          if (meter) { const n = strength(input.value); meter.querySelectorAll('i').forEach((el, i) => el.classList.toggle('on', i < n)); }
        });
      }
    }

    function fail(message) {
      dot.think(false); dot.shake(); buzz([40, 30, 40]);
      const err = form.querySelector('.auth-err');
      if (err) err.textContent = message;
      form.classList.remove('nope'); void form.offsetWidth; form.classList.add('nope');
    }

    async function finish(call) {
      dot.think(true); form.classList.add('busy');
      try {
        await call();
        buzz([12, 40, 24]);
        host.classList.add('entering');           // the question fades; the dot keeps thinking while the app is built
        try { await onSignedIn(); } catch { /* the app shows its own errors */ }
        dot.think(false); dot.stop();
        await handoff(host, blob, pupil);
        resolve();
      } catch (e) {
        form.classList.remove('busy');
        const code = e.code || '';
        if (['auth_email', 'auth_exists'].includes(code)) { flow.step = 'email'; render(-1); }
        else if (['auth_token', 'auth_claimed'].includes(code)) { flow.step = 'owner'; render(-1); }
        else if (['auth_password_short', 'auth_password_weak', 'auth_failed'].includes(code)) { flow.step = 'password'; render(-1); }
        setTimeout(() => fail(e.message), 30);
      }
    }

    function next() {
      const input = form.querySelector('#auth-in'), v = input ? input.value : '';
      const q = flow.step;
      if (q === 'email') {
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(v.trim())) return fail(t('auth.e.email'));
        flow.email = v.trim();
      }
      if (q === 'password') {
        if (flow.mode !== 'login' && v.length < 8) return fail(t('auth.e.short'));
        if (!v) return fail(t('auth.e.empty'));
        flow.password = v;
      }
      if (q === 'name') flow.name = v.trim();
      if (q === 'owner') {
        if (v.length < 24) return fail(t('auth.e.token'));
        return finish(() => api('/auth/register', 'POST', {email: flow.email, password: flow.password, owner_token: v}));
      }
      if (q === 'token') {
        if (v.length < 24) return fail(t('auth.e.token'));
        return finish(() => api('/session', 'POST', {token: v}));
      }
      const seq = order(), i = seq.indexOf(q);
      if (i < seq.length - 1) { flow.step = seq[i + 1]; dot.hop(); buzz(10); render(1); return; }
      if (flow.mode === 'login') return finish(() => api('/auth/login', 'POST', {email: flow.email, password: flow.password}));
      return finish(() => api('/auth/register', 'POST', {email: flow.email, password: flow.password, name: flow.name}));
    }

    form.addEventListener('submit', e => { e.preventDefault(); next(); });
    form.addEventListener('click', e => {
      const go = e.target.closest('[data-go]')?.dataset.go;
      if (go === 'demo') { buzz(8); return finish(() => api('/session/demo', 'POST', {})); }
      if (go) { flow.mode = go; flow.step = order()[0]; dot.hop(); buzz(8); render(1); return; }
      if (e.target.closest('[data-back]')) {
        const seq = order(), i = seq.indexOf(flow.step);
        if (i > 0) flow.step = seq[i - 1]; else { flow.mode = null; flow.step = 'choose'; }
        dot.nod(); render(-1); return;
      }
      if (e.target.closest('[data-skip]')) { flow.name = ''; next(); return; }
      if (e.target.closest('[data-peek]')) {
        const input = form.querySelector('#auth-in'), show = input.type === 'password';
        input.type = show ? 'text' : 'password'; dot.eye(!show); e.target.closest('[data-peek]').classList.toggle('open', show); input.focus();
      }
    });
    render(1);
  });
}
