import { api, baseLayer, esc, fmtTime, h, media, TASHKENT, typeName } from './util.js';
import { demoBlock } from './demo.js';

const COL = { candidate: '#d4800f', corroborated: '#2350d1', verified: '#1d7f55', rejected: '#c23a2e', expired: '#8b9099' };
const FILTERS = { verified: 'verified', open: 'candidate,corroborated', all: 'candidate,corroborated,verified,rejected,expired' };

export default async function map(root, rest) {
  const ui = h(`<div class="wrap">
    <section class="page-head">
      <span class="label">Module · RoadSense · road events and partner API</span>
      <h1>Five taxis, one pothole, one event.</h1>
      <p class="lead">Observations of the same damage from different trips merge into one event. Confidence grows only with
        independent devices; a moderator's confirmation makes it verified. Only verified events reach partners, without
        device identities, routes or video.</p>
    </section>
    <div id="demo"></div>
    <div class="row between" style="margin-bottom:1rem">
      <div class="seg" id="f"><button data-f="verified">Verified</button><button data-f="open">Open</button><button data-f="all">All</button></div>
      <div class="legend">${Object.entries(COL).map(([k, c]) => `<span><i style="background:${c};height:8px;width:8px;border-radius:50%"></i>${k}</span>`).join('')}</div>
    </div>
    <div class="work">
      <div class="map" id="emap"></div>
      <aside><div class="panel" id="side"><span class="label">Event</span><p class="faint">Click an event on the map.</p></div></aside>
    </div>
    <details class="more"><summary>Partner API: feeds for maps, road services and fleets</summary>
    <section class="section">
      <div class="section-head"><span class="label">Partner API</span>
        <div><h2>Read-only feeds for maps, road services and fleets</h2>
          <p class="muted">Live on this server. In a pilot: API keys, rate limits, an audit log and a data-use agreement per partner.</p></div></div>
      <div class="scroll-x"><table class="tbl"><thead><tr><th>Endpoint</th><th>What it returns</th><th class="r">Now</th></tr></thead><tbody id="apis"></tbody></table></div>
    </section></details>
  </div>`);
  root.append(ui);
  demoBlock(ui.querySelector('#demo'), 'tashkent-redmi', 'road', 'RoadSense');
  const m = L.map(ui.querySelector('#emap')).setView(TASHKENT, 12);
  baseLayer().addTo(m);
  const layer = L.layerGroup().addTo(m);
  let filter = rest[0] ? 'all' : 'verified';

  async function load(focus) {
    ui.querySelectorAll('#f button').forEach(b => b.classList.toggle('active', b.dataset.f === filter));
    const g = await api(`/api/v1/events?status=${FILTERS[filter]}`);
    layer.clearLayers();
    const pts = [];
    for (const f of g.features) {
      const [lon, lat] = f.geometry.coordinates, p = f.properties;
      pts.push([lat, lon]);
      L.circle([lat, lon], { radius: p.location_uncertainty_m, color: COL[p.status], weight: 1, fillOpacity: .08 }).addTo(layer);
      L.circleMarker([lat, lon], { radius: 7, color: '#111316', weight: 1.5, fillColor: COL[p.status], fillOpacity: 1 })
        .bindTooltip(`${typeName(p.event_type)} · ${p.status}`).on('click', () => detail(p.id)).addTo(layer);
    }
    if (pts.length && !focus) m.fitBounds(L.latLngBounds(pts).pad(0.3), { maxZoom: 16 });
    if (!pts.length) ui.querySelector('#side').innerHTML = `<span class="label">Event</span><p class="faint">${filter === 'verified' ? 'No verified events yet. Confirm road damage in the <a href="#/review">review center</a>, or look at open events.' : 'No events yet. <a href="#/trip">Upload a trip</a> with a GPS track or a pin.'}</p>`;
  }
  ui.querySelector('#f').onclick = e => { const b = e.target.closest('button'); if (b) { filter = b.dataset.f; load(); } };

  async function detail(id) {
    const e = await api(`/api/v1/events/${id}`);
    m.setView([e.lat, e.lon], Math.max(m.getZoom(), 16));
    const ev = e.observations.find(o => o.thumb);
    ui.querySelector('#side').innerHTML = `<span class="label">Road event #${e.id}</span>
      ${ev ? `<img class="evidence" src="${media(ev.thumb)}" alt="evidence" style="margin-bottom:.8rem">` : ''}
      <h3>${esc(typeName(e.type))} <span class="status s-${e.status}">${e.status}</span></h3>
      <p class="faint" style="font-size:.84rem;margin:.3rem 0 .6rem">${esc(e.validity_reason || '')}</p>
      <table class="kv"><tbody>
        <tr><th>Confidence</th><td>${e.confidence.toFixed(2)} · ${e.n_sources} device(s) · ${e.n_obs} observation(s)</td></tr>
        <tr><th>Position</th><td>${e.lat.toFixed(5)}, ${e.lon.toFixed(5)} · ±${Math.round(e.radius_m)} m</td></tr>
        <tr><th>Seen</th><td>${fmtTime(e.first_seen)} → ${fmtTime(e.last_seen)}</td></tr>
        <tr><th>Valid until</th><td>${fmtTime(e.expires_at)} unless re-observed</td></tr>
      </tbody></table>
      <span class="label" style="display:block;margin:1rem 0 .3rem">Observations</span>
      <div class="list">${e.observations.map(o => `<a class="item" href="#/review"><div><div class="t">${esc(typeName(o.label))} · ${esc(o.review_status.replace('_', ' '))}</div>
        <div class="m">${esc(o.device_id)} (reliability ${o.device_reliability}) · conf ${o.conf.toFixed(2)} · ±${Math.round(o.loc_uncertainty_m || 10)} m ${esc(o.loc_source || '')}</div></div></a>`).join('')}</div>
      <span class="label" style="display:block;margin:1rem 0 .3rem">History</span>
      <div class="list">${e.history.map(x => `<div class="item"><div><div class="t">${esc(x.action)}</div><div class="m">${esc(x.by)} · ${fmtTime(x.t)}${x.note ? ` · ${esc(x.note)}` : ''}</div></div></div>`).join('')}</div>`;
  }

  await load(rest[0]);
  if (rest[0]) detail(+rest[0]).catch(() => {});
  const feeds = [
    ['/api/v1/partners/road-feed', 'Verified road events, GeoJSON: type, status, confidence, independent sources, position uncertainty, validity'],
    ['/api/v1/partners/road-feed?format=cifs', 'The same events as CIFS-style incidents (the format Waze for Cities ingests); not a certified feed'],
    ['/api/v1/events?status=candidate,corroborated', 'Open candidates (internal): what is waiting for confirmation'],
    ['/api/v1/safety/reviews', 'Safety episodes for the fleet safety team (internal role, never in partner feeds)'],
    ['/api/v1/datasets/summary', 'DataMine: samples by label, level and split; exports'],
  ];
  const counts = await Promise.all(feeds.map(([u]) => api(u).then(r => r.features?.length ?? r.incidents?.length ?? r.observations?.length ?? r.with_dataset_rights ?? '—').catch(() => '—')));
  ui.querySelector('#apis').innerHTML = feeds.map(([u, d], i) => `<tr><td><a class="mono" href="${u}" target="_blank" rel="noopener">GET ${esc(u)}</a></td><td>${esc(d)}</td><td class="r">${counts[i]}</td></tr>`).join('');
  return () => m.remove();
}
