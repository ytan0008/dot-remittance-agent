import {state, t, api, toast, isOwner, rerender, invalidate} from '../core.js';
import {esc, panel, empty} from '../ui.js';
import {day, money} from '../i18n.js';
import {gauge, animateGauges} from '../charts.js';

const GROUPS = ['tracking', 'planning', 'habits', 'goals'];
const owner = () => isOwner() ? '' : 'disabled';

export function medal(earned, size = 54) {
  return `<svg viewBox="0 0 60 60" class="medal ${earned ? 'on' : 'off'}" width="${size}" height="${size}" aria-hidden="true">
    <circle cx="30" cy="30" r="26" class="m-ring"/><circle cx="30" cy="30" r="17" class="m-inner"/>${earned ? '<circle cx="30" cy="30" r="7" class="m-core"/>' : '<circle cx="30" cy="30" r="2.5" class="m-seed"/>'}</svg>`;
}

const challengeText = c => t('ch.' + c.kind + '_d', c.amount ? {amount: `${money(c.amount, c.currency)} ${c.currency}`} : {});

function levelPanel(m) {
  const pct = m.level / m.max_level * 100;
  const next = m.next ? `<div class="next-level"><span class="eyebrow">${t('prog.next', {n: m.next.level})}</span>
      <ul class="criteria">${m.next.needs.map(n => `<li class="${n.done ? 'done' : ''}"><span class="crit-dot"></span><div><b>${esc(t('badge.' + n.badge))}</b><small>${esc(t('badge.' + n.badge + '_d'))}</small></div></li>`).join('')}</ul></div>`
    : `<p class="fine">${t('prog.max')}</p>`;
  return panel(t('prog.level'), `<div class="level-hero">${gauge(pct, {size: 132, label: String(m.level), sub: t('prog.level')})}
      <div><h3>${esc(t('level.' + (m.level || 0)))}</h3><p class="fine">${esc(t('level.' + (m.level || 0) + '_d'))}</p>
      <ol class="level-ladder">${m.levels.map(l => `<li class="${l.reached ? 'on' : ''}" title="${esc(t('level.' + l.level))}"><i></i><span>${l.level}</span></li>`).join('')}</ol></div></div>${next}`,
    {cls: 'level-panel'});
}

function streakPanel(s) {
  const status = s.status === 'resting' ? t('prog.st.resting', {d: day(s.safe_until)}) : t('prog.st.' + s.status);
  return panel(t('prog.streak'), `<div class="streak-hero"><strong data-count="${s.current}" data-digits="0">${s.current}</strong><span>${t('prog.days')}</span></div>
    <p class="streak-status st-${esc(s.status)}">${esc(status)}</p>
    <div class="rhythm" aria-label="${t('prog.rhythm')}">${s.weeks.map(w => `<div class="week" title="${esc(day(w.start))}">${Array.from({length: 7}, (_, i) => `<i class="${i < w.days ? 'on' : ''}"></i>`).join('')}</div>`).join('')}</div>
    <div class="rhythm-foot"><span class="eyebrow">${t('prog.rhythm')}</span><small>${t('prog.longest', {n: s.longest})}</small></div>
    <p class="fine">${t('prog.streak_rule', {n: s.rest_days})}</p>`, {cls: 'streak-panel'});
}

function challengesPanel(m) {
  const active = m.active.length ? `<div class="ch-grid">${m.active.map(c => {
    const ratio = Math.min(1, c.progress / c.target);
    return `<article class="ch-card active reveal"><span class="eyebrow">${t('prog.days_left', {n: c.days_left})}</span><h3>${esc(t('ch.' + c.kind))}</h3>
      <p>${esc(challengeText(c))}</p>
      <div class="ch-bar"><i class="bar-fill" data-ratio="${ratio.toFixed(3)}"></i></div><small>${t('prog.progress', {p: c.progress, t: c.target})}</small>
      <div class="row-actions">${c.mode === 'self' ? `<button class="button sm primary" data-action="ch-done" data-id="${esc(c.id)}" ${owner()}>${t('prog.done')}</button>` : ''}
        <button class="link sm muted" data-action="ch-stop" data-id="${esc(c.id)}" ${owner()}>${t('prog.stop')}</button></div></article>`;
  }).join('')}</div>` : `<p class="fine">${t('prog.active_none')}</p>`;
  const sug = m.suggestions.length ? `<span class="eyebrow block sug-title">${t('prog.suggested')}</span><div class="ch-grid">${m.suggestions.map(s => `<article class="ch-card suggest">
      <h3>${esc(t('ch.' + s.kind))}</h3><p>${esc(t('ch.' + s.kind + '_d', s.suggested ? {amount: `${money(s.suggested.amount, s.suggested.currency)} ${s.suggested.currency}`} : {}))}</p>
      ${s.kind === 'set_aside' ? `<label class="inline-select">${t('prog.amount')} <input class="mini-input" inputmode="decimal" id="aside-amount" value="${esc(money(s.suggested.amount, s.suggested.currency).replace(/,/g, ''))}"> ${esc(s.suggested.currency)}</label><small class="muted">${t('prog.fits', {a: `${money(s.suggested.amount, s.suggested.currency)} ${s.suggested.currency}`})}</small>` : ''}
      <button class="button sm" data-action="ch-start" data-kind="${esc(s.kind)}" data-currency="${esc(s.suggested?.currency || '')}" ${owner()}>${t('prog.start')}</button></article>`).join('')}</div>` : '';
  const hist = m.history.length ? `<details class="history"><summary>${t('prog.history')} (${m.history.length})</summary><ul class="list">${m.history.map(c => `<li class="row"><span class="state-dot ${c.status === 'completed' ? '' : 'off'}"></span><div><b>${esc(t('ch.' + c.kind))}</b><small>${esc(t('prog.st_' + c.status))} · ${day(c.started)}</small></div></li>`).join('')}</ul></details>` : '';
  return panel(t('prog.challenges'), active + sug + hist, {cls: 'ch-panel', sub: t('prog.optional')});
}

function badgesPanel(m) {
  const earned = m.badges.filter(b => b.earned).length;
  return panel(`${t('prog.badges')} <span class="muted">/ ${earned} · ${m.badges.length}</span>`, GROUPS.map(g => `<div class="badge-group"><span class="eyebrow">${t('group.' + g)}</span>
    <div class="badge-grid">${m.badges.filter(b => b.group === g).map(b => `<div class="badge-tile ${b.earned ? 'on' : ''}">${medal(!!b.earned)}
      <div><b>${esc(t('badge.' + b.id))}</b><small>${b.earned ? t('prog.earned', {d: day(new Date(b.earned * 1000).toISOString().slice(0, 10))}) : esc(t('badge.' + b.id + '_d'))}</small></div></div>`).join('')}</div></div>`).join(''),
    {cls: 'badges-panel'});
}

function settingsPanel(m) {
  return panel(t('prog.principles'), `<ul class="principles">${m.principles.map(p => `<li><span class="crit-dot"></span>${esc(t('prog.p.' + p))}</li>`).join('')}</ul>
    <div class="prog-toggles"><label class="check-label"><input type="checkbox" data-mset="enabled" ${m.settings.enabled ? 'checked' : ''} ${owner()}> ${t('prog.enabled')}</label>
    <label class="check-label"><input type="checkbox" data-mset="celebrate" ${m.settings.celebrate ? 'checked' : ''} ${owner()}> ${t('prog.celebrate')}</label></div>`, {cls: 'principles-panel'});
}

export const view = {
  id: 'progress',
  needs: [],
  async load() {
    try { state.data.motivation = await api('/motivation'); delete state.errors.motivation; } catch (e) { state.errors.motivation = e.message; }
  },
  render() {
    const m = state.data.motivation;
    if (!m) return empty(state.errors.motivation || t('common.loading'));
    if (!m.settings.enabled) return `${panel(t('prog.title_off'), `<p class="fine">${t('prog.off')}</p>`)}${settingsPanel(m)}`;
    return `<div class="split">${levelPanel(m)}${streakPanel(m.streak)}</div>${challengesPanel(m)}${badgesPanel(m)}${settingsPanel(m)}`;
  },
  mount(root) {
    animateGauges(root);
    root.querySelectorAll('.bar-fill[data-ratio]').forEach(el => el.style.setProperty('--ratio', el.dataset.ratio));
    root.querySelector('.principles-panel')?.addEventListener('change', async e => {
      if (!e.target.dataset.mset) return;
      const s = {...state.data.motivation.settings, [e.target.dataset.mset]: e.target.checked};
      await api('/motivation/settings', 'PUT', s);
      toast(t('prog.saved'), 'good'); await reload();
    });
  },
  actions: {
    async 'ch-start'(el) {
      const body = {kind: el.dataset.kind};
      if (el.dataset.kind === 'set_aside') Object.assign(body, {amount: document.getElementById('aside-amount')?.value || null, currency: el.dataset.currency || null});
      await api('/challenges', 'POST', body);
      toast(t('prog.started'), 'good'); await reload();
    },
    async 'ch-done'(el) { await api(`/challenges/${encodeURIComponent(el.dataset.id)}/done`, 'POST', {}); toast(t('prog.completed'), 'good'); await reload(); },
    async 'ch-stop'(el) { await api(`/challenges/${encodeURIComponent(el.dataset.id)}/stop`, 'POST', {}); toast(t('prog.stopped')); await reload(); },
  },
};

async function reload() {
  invalidate(['reminders', 'celebrations', 'motivationSummary']);
  await view.load();
  if (state.view === 'progress') rerender();
}
