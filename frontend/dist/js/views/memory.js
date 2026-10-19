import {state, t, api, toast, isOwner, invalidate, rerender, value} from '../core.js';
import {esc, panel, field, options, icons, empty, short} from '../ui.js';
import {when, relative} from '../i18n.js';

const KINDS = ['fact', 'person', 'routine', 'preference'];

function notes(list) {
  if (!list.length) return empty(t('memory.empty'));
  return `<ul class="list memory-notes">${list.map(n => `<li class="row reveal"><span class="note-kind k-${esc(n.kind)}">${esc(t('memory.kind.' + n.kind))}</span>
    <div><b>${esc(n.text)}</b><small>${esc(t('memory.source.' + n.source))} · ${when(n.created)}${n.uses ? ' · ' + t('memory.used', {n: n.uses}) : ''}${n.last_used ? ' · ' + relative(n.last_used) : ''}</small></div>
    ${isOwner() ? `<button class="x" data-action="forget-note" data-id="${n.id}" aria-label="${t('memory.forget')}">×</button>` : ''}</li>`).join('')}</ul>`;
}

function episodes(list) {
  if (!list.length) return empty(t('memory.no_episodes'));
  return `<ol class="episodes">${list.map(e => `<li class="episode reveal"><span class="dot"></span><div>
    <div class="episode-head"><time>${when(e.time)}</time><span class="mode-badge m-${esc(e.mode)}">${t('agent.mode.' + e.mode)}</span>${e.intent ? `<span class="tag">${esc(t('intent.' + e.intent) !== 'intent.' + e.intent ? t('intent.' + e.intent) : e.intent)}</span>` : ''}</div>
    <p class="episode-request">“${esc(e.request)}”</p>
    ${e.tools.length ? `<div class="episode-tools">${e.tools.map(x => { const [name, blocked] = x.split(':'); return `<span class="pill sm ${blocked ? 'blocked' : ''}">${esc(t('tool.' + name))}${blocked ? ' · ' + t('memory.blocked') : ''}</span>`; }).join('')}</div>` : ''}
    ${e.outcome ? `<small class="muted">${esc(e.outcome)}</small>` : ''}
    ${e.refs.length ? `<div class="row-actions">${e.refs.map(id => `<button class="link sm mono" data-action="detail" data-id="${esc(id)}">${short(id)} ${icons.arrow}</button>`).join('')}</div>` : ''}
  </div></li>`).join('')}</ol>`;
}

export const view = {
  id: 'memory',
  needs: ['agentMemory'],
  render() {
    const m = state.data.agentMemory || {notes: [], episodes: []};
    const owner = isOwner();
    return `<div class="actions-legend reveal">${[1, 2, 3].map(n => `<div><span class="eyebrow">0${n}</span><b>${t('memory.layer' + n)}</b><small>${t('memory.layer' + n + '_d')}</small></div>`).join('')}</div>
      <div class="split">
        ${panel(`${t('memory.notes')} <span class="muted">/ ${m.notes.length}</span>`, `${notes(m.notes)}
          <form id="note-form" class="inline-form"><div class="grid-note">${field('note-text', t('memory.text'), `<input id="note-text" name="text" required minlength="3" maxlength="300" placeholder="${t('memory.text_ph')}" ${owner ? '' : 'disabled'}>`)}
          ${field('note-kind', t('memory.kind'), `<select id="note-kind" name="kind" ${owner ? '' : 'disabled'}>${options(KINDS.map(k => [k, t('memory.kind.' + k)]), 'fact')}</select>`)}</div>
          <div class="form-error"></div><button class="button" ${owner ? '' : 'disabled'}>${icons.plus}${t('memory.add')}</button></form>`, {sub: 'LONG-TERM'})}
        ${panel(t('memory.episodes'), episodes(m.episodes), {sub: 'EPISODIC'})}
      </div>
      <p class="fine memory-rule">${t('memory.note')}</p>`;
  },
  actions: {
    async 'forget-note'(el) {
      await api('/agent/memory/' + el.dataset.id, 'DELETE');
      invalidate(['agentMemory']); toast(t('memory.forgotten')); rerender();
    },
  },
  submit: {
    async 'note-form'(f) {
      await api('/agent/memory', 'POST', {text: value(f, 'text'), kind: value(f, 'kind')});
      invalidate(['agentMemory']); toast(t('memory.saved'), 'good'); rerender();
    },
  },
};
