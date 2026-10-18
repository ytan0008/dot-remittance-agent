import {state, t, isOwner, invalidate, need, rerender} from '../core.js';
import {esc, panel, empty, options} from '../ui.js';
import {when} from '../i18n.js';

let searchTimer = 0;

function parse(detail) { try { return JSON.parse(detail); } catch { return {}; } }

export const view = {
  id: 'audit',
  needs: ['audit'],
  render() {
    if (!isOwner()) return panel(t('audit.title'), empty(t('audit.owner_only')));
    const events = state.data.audit || [];
    const groups = [];
    for (const e of events) {
      const key = e.request_id || 'e' + e.id;
      const g = groups.at(-1);
      if (g && g.key === key) g.items.push(e); else groups.push({key, items: [e]});
    }
    const a = state.audit;
    return panel(`${t('audit.title')} <span class="muted">/ ${events.length}</span>`, `
      <div class="toolbar audit-tools"><input id="audit-q" type="search" placeholder="${t('audit.search')}" value="${esc(a.q)}" aria-label="${t('audit.search')}">
        <select id="audit-outcome" aria-label="${t('audit.outcome')}">${options([['', t('audit.any_outcome')], ['ok', 'ok'], ['denied', 'denied'], ['pass', 'pass'], ['warn', 'warn'], ['fail', 'fail'], ['completed', 'completed'], ['failed', 'failed'], ['unknown', 'unknown']], a.outcome)}</select>
        <select id="audit-actor" aria-label="${t('audit.actor')}">${options([['', t('audit.any_actor')], ['owner', 'owner'], ['agent', 'agent'], ['system', 'system'], ['api', 'api'], ['viewer', 'viewer']], a.actor)}</select></div>
      <p class="fine">${t('audit.note')}</p>
      ${groups.length ? `<ol class="audit-groups">${groups.map(g => `<li class="audit-group reveal"><div class="group-head"><span class="mono">${g.items[0].request_id ? esc(g.items[0].request_id) : '—'}</span><small>${when(g.items.at(-1).time, {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'})}</small></div>
        <ol class="event-list">${g.items.map(e => { const d = parse(e.detail); return `<li class="o-${esc(e.outcome)}"><time>${when(e.time, {hour: '2-digit', minute: '2-digit', second: '2-digit'})}</time><span class="dot"></span><div><b>${esc(e.action)}</b> <span class="outcome">${esc(e.outcome)}</span><small>${esc(e.actor)}${e.correlation ? ` · <button class="link mono" data-action="audit-filter" data-value="${esc(e.correlation)}">${esc(e.correlation.slice(0, 12))}</button>` : ''}${d.reason ? ' · ' + esc(d.reason) : ''}</small>${Object.keys(d).length ? `<details><summary>${t('audit.detail')}</summary><pre>${esc(JSON.stringify(d, null, 2))}</pre></details>` : ''}</div></li>`; }).join('')}</ol></li>`).join('')}</ol>` : empty(t('audit.empty'))}`, {sub: 'APPEND-ONLY'});
  },
  mount(root) {
    const apply = async () => { invalidate(['audit']); await need(['audit']); rerender(); };
    root.querySelector('#audit-q')?.addEventListener('input', e => { state.audit.q = e.target.value.trim(); clearTimeout(searchTimer); searchTimer = setTimeout(apply, 350); });
    root.querySelector('#audit-outcome')?.addEventListener('change', e => { state.audit.outcome = e.target.value; apply(); });
    root.querySelector('#audit-actor')?.addEventListener('change', e => { state.audit.actor = e.target.value; apply(); });
  },
  actions: {
    async 'audit-filter'(el) { state.audit.q = el.dataset.value; invalidate(['audit']); await need(['audit']); rerender(); },
  },
};
