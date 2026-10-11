import { api, clipPlayer, esc, figure, h, locText, typeName } from './util.js';
import { evidenceText, statusChip } from './components.js';

const TYPES = ['hard_braking', 'forward_collision_risk', 'vru_near_path', 'cut_in'];

export default async function safety(root) {
  const ui = h(`<div class="wrap">
    <section class="page-head">
      <span class="label">Module · Safety</span>
      <h1>A hard brake, with what the camera saw before it.</h1>
      <p class="lead">Safety episodes for the fleet's safety team: collision risks, pedestrians or riders in our path, cut-ins and hard
        braking, each with its clip. They are for coaching, never a fine and never public, and none of them claims a cause or a fault.</p>
    </section>
    <div id="body"><p class="faint">Loading…</p></div>
  </div>`);
  root.append(ui);
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
  const counts = TYPES.map(t => [t, obs.filter(o => o.label === t).length]);
  body.append(h(`<section class="section"><div class="section-head"><span class="label">By type</span>
    <div><p class="muted">What one front camera and the phone's telemetry can support, nothing more.</p></div></div>
    <div class="scroll-x"><table class="tbl"><tbody>${counts.map(([t, c]) => `<tr><td>${esc(typeName(t))}</td><td class="r">${c}</td></tr>`).join('')}</tbody></table></div>
  </section>`));
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
        <p class="evtext">${esc(evidenceText(o))}</p>
        <p class="note" style="margin-top:.5rem">cause: not established · driver fault: not determined</p>
      </div>
    </article>`));
  }
}
