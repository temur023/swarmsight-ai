import { api, clipPlayer, esc, figure, h, locText, typeName } from './util.js';
import { evidenceText, statusChip } from './components.js';
import { demoBlock } from './demo.js';

const TYPES = ['hard_braking', 'forward_collision_risk', 'vru_near_path', 'cut_in'];

export default async function safety(root) {
  const ui = h(`<div class="wrap">
    <section class="page-head">
      <span class="label">Module · Safety</span>
      <h1>A hard brake, with what the camera saw before it.</h1>
      <p class="lead">Safety episodes for the fleet's safety team: collision risks, pedestrians or riders in our path, cut-ins and hard
        braking, each with its clip. They are for coaching, never a fine and never public, and none of them claims a cause or a fault.</p>
    </section>
    <div id="demo"></div>
    <div id="body"><p class="faint">Loading…</p></div>
  </div>`);
  root.append(ui);
  demoBlock(ui.querySelector('#demo'), 'stcroix-taxi', 'safety', 'Safety');
  const r = await api('/api/v1/safety/reviews?limit=60').catch(() => ({ observations: [] }));
  const obs = r.observations || [];
  const body = ui.querySelector('#body');
  body.innerHTML = '';
  const n = s => obs.filter(o => o.review_status === s).length;
  body.append(h(`<div class="nums4">
    ${figure(obs.length, '', 'safety episodes on this server')}
    ${figure(n('needs_review'), '', 'waiting for a person', 'every episode goes to review')}
    ${figure(n('confirmed') + n('corrected'), '', 'confirmed by a reviewer')}
    ${figure(n('rejected'), '', 'rejected as false alerts')}
  </div>`));
  body.append(h(`<section class="section"><div class="section-head"><span class="label">Sensors vs video</span>
    <div><h2>What the phone's sensors know, and what the camera adds</h2>
      <p class="muted">Driving-style scores today come from the accelerometer and GPS: they register that a car braked hard, not why.
        For each episode below, the left column is all that sensors alone could report for that moment; the right column is what the system read from the video.</p></div></div>
    <div class="cols c2 vs"><div class="panel"><span class="label">Sensors only</span><p>"Hard braking": a penalty point, with no way to tell a careless driver from one who avoided a pedestrian. A near miss without braking is invisible.</p></div>
      <div class="panel"><span class="label">Sensors + video</span><p>The same moment with the clip and what was ahead seconds before: a pedestrian in our path, a car cutting in, the time to contact. A person then decides; the system never claims a cause or a fault.</p></div></div>
  </section>`));
  // per trip: is there telemetry, and which hard-braking moments did it register
  const trips = {};
  await Promise.all([...new Set(obs.map(o => o.trip_id))].map(async id => {
    const t = await api(`/api/v1/trips/${id}`).catch(() => null);
    trips[id] = t ? { gps: t.trip.gps_source, braking: t.observations.filter(x => x.type === 'hard_braking') } : null;
  }));
  const sensorsOnly = o => {
    const t = trips[o.trip_id];
    if (o.type === 'hard_braking') return evidenceText({ evidence: { peak_decel_ms2: o.evidence?.peak_decel_ms2, signal: o.evidence?.signal, speed_before_kmh: o.evidence?.speed_before_kmh, speed_after_kmh: o.evidence?.speed_after_kmh } }) + ' · no reason';
    if (!t || !t.gps) return 'no telemetry in this trip: sensors know nothing about this moment';
    const b = t.braking.find(x => Math.abs(x.t_peak - o.t_peak) <= 4);
    return b ? `hard braking at ${b.t_peak.toFixed(1)} s · no reason` : 'no hard braking: for sensors this moment does not exist';
  };
  const counts = TYPES.map(t => [t, obs.filter(o => o.label === t).length]);
  body.append(h(`<details class="more"><summary>Episodes by type</summary><section class="section"><div class="section-head"><span class="label">By type</span>
    <div><p class="muted">What one front camera and the phone's telemetry can support, nothing more.</p></div></div>
    <div class="scroll-x"><table class="tbl"><tbody>${counts.map(([t, c]) => `<tr><td>${esc(typeName(t))}</td><td class="r">${c}</td></tr>`).join('')}</tbody></table></div>
  </section></details>`));
  const list = h(`<section class="section"><div class="section-head"><span class="label">Episodes</span>
    <div><p class="muted">Newest first. Decide on them in the <a href="#/review">review center</a> (Safety tab).</p></div></div>
    <div class="cards" id="cards"></div></section>`);
  body.append(list);
  const cards = list.querySelector('#cards');
  if (!obs.length) cards.append(h('<p class="faint">No safety episodes yet. <a href="#/trip">Upload a trip</a> or run one of the sample trips.</p>'));
  for (const o of obs) {
    cards.append(h(`<article class="ecard">
      <div class="media">${clipPlayer(o)}</div>
      <div class="body">
        <div class="row between"><span class="kchip"><i style="background:var(--critical)"></i>Safety</span>${statusChip(o)}</div>
        <h3>${esc(typeName(o.label))}</h3>
        <table class="kv"><tbody>
          <tr><th>Trip</th><td><a href="#/trip/${o.trip_id}">${esc(o.trip_id)}</a> · ${o.t_start.toFixed(1)}–${o.t_end.toFixed(1)} s</td></tr>
          <tr><th>Model</th><td>confidence ${o.conf.toFixed(2)}</td></tr>
          <tr><th>Where</th><td>${esc(locText(o))}</td></tr>
        </tbody></table>
        <table class="kv vsrow"><tbody>
          <tr><th>Sensors only</th><td>${esc(sensorsOnly(o))}</td></tr>
          <tr><th>Sensors + video</th><td>${esc(evidenceText(o))}</td></tr>
        </tbody></table>
        <p class="note" style="margin-top:.5rem">cause: not established · driver fault: not determined</p>
      </div>
    </article>`));
  }
}
