import {state, t, api, toast, isOwner, invalidate, rerender, value} from '../core.js';
import {esc, panel, field, options, icons, empty} from '../ui.js';
import {region, day, when, lang} from '../i18n.js';

const CAPS = ['reference_rates', 'historical_analysis', 'simulated_comparison', 'sandbox_payment'];
// Approximate positions on a dot-matrix Pacific rim map (percent of the panel).
const POS = {AU: [74, 78], BN: [56, 54], CA: [16, 18], CL: [30, 86], CN: [52, 30], HK: [56, 40], ID: [58, 62], JP: [68, 28], KR: [64, 28],
  MY: [52, 55], MX: [16, 44], NZ: [88, 86], PG: [72, 62], PE: [26, 70], PH: [62, 46], RU: [58, 10], SG: [54, 58], TW: [62, 38],
  TH: [50, 46], US: [16, 30], VN: [54, 47]};

function map(routes) {
  const economies = state.data.economies || [];
  const lines = routes.filter(r => r.enabled).map(r => {
    const [x1, y1] = POS[r.send] || [0, 0], [x2, y2] = POS[r.receive] || [0, 0];
    const mx = (x1 + x2) / 2, my = Math.min(y1, y2) - 10;
    return `<path class="arc ${r.capabilities.sandbox_payment ? 'pay' : ''}" d="M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}"/>`;
  }).join('');
  const grid = [];
  for (let x = 2; x < 100; x += 3) for (let y = 2; y < 100; y += 4) grid.push(`<circle cx="${x}" cy="${y}" r=".28"/>`);
  return `<div class="apec-map no-swipe"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><g class="map-grid">${grid.join('')}</g>${lines}</svg>
    ${economies.map(e => { const [x, y] = POS[e.code] || [0, 0]; return `<button class="econ" data-x="${x}" data-y="${y}" data-action="pick-econ" data-value="${e.code}" title="${esc(region(e.code))}"><i></i><span>${esc(e.code)}</span></button>`; }).join('')}</div>`;
}

export const view = {
  id: 'routes',
  needs: ['routes', 'economies'],
  render() {
    const routes = state.data.routes || [], economies = state.data.economies || [], owner = isOwner();
    const focus = state.routeFocus;
    const shown = focus ? routes.filter(r => r.send === focus || r.receive === focus) : routes;
    const econ = focus && economies.find(e => e.code === focus);
    return `<div class="split wide-left">
      ${panel(t('routes.map'), `${map(routes)}${econ ? `<div class="econ-card"><b>${esc(region(econ.code))}</b><small>${esc(econ.currency)} · ${econ.languages.map(esc).join(', ')} · ${econ.time_zones.map(esc).join(', ')}</small><button class="link" data-action="pick-econ" data-value="">${t('common.reset')}</button></div>` : `<p class="fine">${t('routes.map_hint')}</p>`}`, {cls: 'map-panel'})}
      ${panel(t('routes.add'), `<form id="route-form" class="form-block"><div class="grid-2">
        ${field('rt-send', t('routes.send'), `<select id="rt-send" name="send">${options(economies.map(e => [e.code, region(e.code) + ' · ' + e.currency]), 'AU')}</select>`)}
        ${field('rt-recv', t('routes.receive'), `<select id="rt-recv" name="receive">${options(economies.map(e => [e.code, region(e.code) + ' · ' + e.currency]), 'VN')}</select>`)}</div>
        <p class="fine">${t('routes.add_note')}</p><div class="form-error"></div><button class="button" ${owner ? '' : 'disabled'}>${icons.plus}${t('routes.add_btn')}</button></form>
        <p class="fine">${t('routes.independent')}</p>`)}
    </div>
    ${panel(`${t('routes.title')} <span class="muted">/ ${shown.length}</span>`, shown.length ? `<div class="table-wrap"><table class="table routes"><thead><tr><th>${t('routes.route')}</th>${CAPS.map(c => `<th>${t('cap.' + c)}</th>`).join('')}<th>${t('routes.controls')}</th></tr></thead><tbody>${shown.map(r => `
      <tr class="${r.enabled ? '' : 'disabled'}"><td><b>${esc(region(r.send))} → ${esc(region(r.receive))}</b><small>${esc(r.source)}/${esc(r.target)} · ${esc(r.time_zones.send)} → ${esc(r.time_zones.receive)}</small>${r.reference_check ? `<small class="muted">${r.reference_check.available ? esc(r.reference_check.provider) + ' · ' + day(r.reference_check.observed) : esc(t('routes.ref_unavailable'))} · ${t('routes.checked')} ${when(r.reference_check.checked)}</small>` : ''}</td>
      ${CAPS.map(c => { const v = r.capabilities[c]; return `<td><span class="cap ${v === true ? 'yes' : v === false ? 'no' : 'unknown'}" title="${t(v === true ? 'cap.yes' : v === false ? 'cap.no' : 'cap.unverified')}"><i></i>${t(v === true ? 'cap.yes' : v === false ? 'cap.no' : 'cap.unverified')}</span></td>`; }).join('')}
      <td class="nowrap"><button class="link sm" data-action="verify-route" data-id="${esc(r.id)}">${icons.reset}${t('routes.verify')}</button>
        <button class="pill sm ${r.enabled ? 'on' : ''}" data-action="route-toggle" data-id="${esc(r.id)}" data-field="enabled" data-value="${r.enabled ? 0 : 1}" ${owner ? '' : 'disabled'}>${t(r.enabled ? 'routes.enabled' : 'routes.disabled')}</button>
        <button class="pill sm ${r.payments_enabled ? 'on' : ''}" data-action="route-toggle" data-id="${esc(r.id)}" data-field="payments_enabled" data-value="${r.payments_enabled ? 0 : 1}" ${owner && (r.provider_supported || r.payments_enabled) ? '' : 'disabled'} title="${r.provider_supported ? '' : esc(t('routes.provider_no'))}">${t(r.payments_enabled ? 'routes.payments_on' : 'routes.payments_off')}</button></td></tr>`).join('')}</tbody></table></div>` : empty(t('routes.empty')))}
    <p class="fine">${t('routes.note')}</p>`;
  },
  mount(root) {
    root.querySelectorAll('.econ').forEach(b => { b.style.left = b.dataset.x + '%'; b.style.top = b.dataset.y + '%'; b.classList.toggle('on', b.dataset.value === state.routeFocus); });
  },
  actions: {
    'pick-econ'(el) { state.routeFocus = el.dataset.value || null; rerender(); },
    async 'verify-route'(el) { await api(`/routes/${encodeURIComponent(el.dataset.id)}/verify`, 'POST', {}); invalidate(['routes']); toast(t('routes.verified')); rerender(); },
    async 'route-toggle'(el) {
      await api('/routes/' + encodeURIComponent(el.dataset.id), 'PATCH', {[el.dataset.field]: el.dataset.value === '1'});
      invalidate(['routes']); rerender();
    },
  },
  submit: {
    async 'route-form'(f) {
      await api('/routes', 'POST', {send: value(f, 'send'), receive: value(f, 'receive')});
      invalidate(['routes']); toast(t('routes.added'), 'good'); rerender();
    },
  },
};
