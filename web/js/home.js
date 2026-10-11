import { api, esc, figure, fmtTime, h, media, pct, typeName } from './util.js';

export default async function home(root) {
  const [m, d] = await Promise.all([api('/api/v1/metrics').catch(() => ({})), api('/api/v1/datasets/summary').catch(() => ({}))]);
  const live = m.live || {}, rd = m.road_damage_eval, tk = m.tashkent_eval, ev = m.event_mining_eval;
  const verified = live.events?.verified || 0;
  const reviewed = (live.observations?.confirmed || 0) + (live.observations?.corrected || 0);
  root.append(h(`<div class="wrap">
    <section class="page-head hero">
      <span class="label">SwarmSight · Taxi fleet intelligence network · Tashkent</span>
      <h1>Every taxi trip makes roads safer and AI smarter.</h1>
      <p class="lead">Taxi fleets already drive every street, every day. SwarmSight turns their dashcams and phones into road sensors:
        a trip becomes a handful of short, anonymised, verifiable clips that feed three products at once.</p>
      <div class="row" style="margin-top:1.8rem">
        <a class="btn primary" href="#/trip">Upload a trip <span class="arr">→</span></a>
        <a class="btn" href="#/trip">Run a sample trip</a>
      </div>
    </section>

    <section class="section">
      <div class="section-head"><span class="label">How it works</span><div><h2>Two steps, then three modules</h2></div></div>
      <div class="fl-steps">
        <a class="fl-step" href="#/trip"><span class="label">Step 1 · Upload</span><b>A trip goes in</b>
          <p>Dashcam or phone video, a GPS track if there is one. The server finds the few moments that matter, cuts a short clip for each and blurs faces and plates.</p></a>
        <a class="fl-step" href="#/review"><span class="label">Step 2 · Review</span><b>A person decides</b>
          <p>Every event is a candidate until someone confirms, rejects or corrects it. Every decision is logged.</p></a>
      </div>
      <div class="fl-modules">
        <a class="fl-module m-road" href="#/map"><span class="label">Module · RoadSense</span><b>Verified road events</b>
          <p>Potholes and cracks, merged across taxis, with position and uncertainty. A map and partner feeds (GeoJSON, CIFS).</p>
          <span class="who">for maps · road services · fleets</span><span class="go">Open RoadSense <span class="arr">→</span></span></a>
        <a class="fl-module m-safety" href="#/safety"><span class="label">Module · Safety</span><b>Explained safety episodes</b>
          <p>Collision risks, pedestrians in our path, cut-ins and hard braking, with what the camera saw. For coaching; never a fine, never public.</p>
          <span class="who">for fleet safety teams</span><span class="go">Open Safety <span class="arr">→</span></span></a>
        <a class="fl-module m-data" href="#/datamine"><span class="label">Module · DataMine</span><b>Regional dataset</b>
          <p>The rare, uncertain, well-exposed moments plus ordinary driving, with rights, split by trip, exported as versions.</p>
          <span class="who">for automotive AI · ADAS teams</span><span class="go">Open DataMine <span class="arr">→</span></span></a>
      </div>
    </section>

    <section class="section">
      <div class="section-head"><span class="label">Data exchange</span><div><h2>One car sees it, others confirm it</h2>
        <p class="muted">How a sighting becomes a fact on the map. Today this chain runs for road damage (potholes and cracks);
          safety episodes stay inside the fleet, and traffic jams or crashes as map events are pilot work.</p></div></div>
      <ol class="xchain">
        <li><b>Seen</b><span>A taxi's camera finds damage and keeps the frame with the model's box.</span></li>
        <li><b>Sent</b><span>Only a short clip and a position go to the server, not the whole drive.</span></li>
        <li><b>Compared</b><span>Sightings from other cars within the GPS error merge into one event. Confidence grows only with independent sources: another car and another recording.</span></li>
        <li><b>Checked</b><span>A moderator confirms or rejects. Every decision changes how much the system trusts that device.</span></li>
        <li><b>Confirmed</b><span>The event goes to the map and the partner feed, and expires unless cars see it again.</span></li>
      </ol>
      <div id="xlive"></div>
    </section>

    <section class="section">
      <div class="section-head"><span class="label">On this server</span><div><h2>Live, from real uploads</h2></div></div>
      <div class="nums4">
        ${figure(live.trips ?? 0, '', 'trips processed')}
        ${figure(d.kept_ratio != null ? (100 * d.kept_ratio).toFixed(0) : null, '%', 'of video kept as clips', 'the rest is analysed and discarded')}
        ${figure(reviewed, '', 'events reviewed by a person')}
        ${figure(verified, '', 'verified road events in the partner feed')}
      </div>
    </section>

    <section class="section">
      <div class="section-head"><span class="label">Measured</span><div><h2>On data the models never saw</h2></div></div>
      <div class="nums4">
        ${rd ? figure(rd.test.map50.toFixed(2), 'mAP@.5', 'road-damage detector we trained', `RDD2022 · ${rd.n_test_images.toLocaleString('en')} held-out images, 6 countries`) : ''}
        ${tk ? figure(tk.ap_image.toFixed(2), 'AP', 'on Tashkent street photos', `precision ${pct(tk.precision_at_thr)} at the operating point`) : ''}
        ${ev ? figure(ev.detection?.overall?.recall != null ? ev.detection.overall.recall.toFixed(2) : null, '', 'event recall on labelled trips', `${ev.detection?.overall?.tp ?? 0} of ${ev.detection?.overall?.gt ?? 0} labelled events · ${ev.detection?.overall?.fp ?? 0} false alerts · ${ev.videos?.length ?? 0} trips`) : ''}
        ${ev ? figure(ev.reduction?.kept_ratio_event_clips_only != null ? (100 * ev.reduction.kept_ratio_event_clips_only).toFixed(0) : null, '%', 'of labelled video kept in event clips', ev.reduction?.event_retention != null ? `${pct(ev.reduction.event_retention)} of labelled events inside them` : '') : ''}
      </div>
      <p class="note" style="margin-top:1.4rem">Sources, splits, licences and failure cases: <a href="#/evidence">Evidence</a>.
        What SwarmSight is not: an autopilot, a way to blame drivers from one camera, or access to Yandex or carmaker data.</p>
    </section>
  </div>`));
  liveChain(root.querySelector('#xlive'));
}

// The chain of one real event on this server: its observations from each car and its history.
async function liveChain(el) {
  if (!el) return;
  const pick = async st => (await api(`/api/v1/events?status=${st}`).catch(() => ({ features: [] }))).features
    .sort((a, b) => b.properties.observations - a.properties.observations)[0];
  const f = (await pick('verified')) || (await pick('corroborated')) || (await pick('candidate'));
  if (!f) { el.innerHTML = '<p class="note">No road event on this server yet. <a href="#/trip">Upload a trip</a> with a GPS track to start a chain.</p>'; return; }
  const e = await api(`/api/v1/events/${f.properties.id}`);
  const devs = new Set(e.observations.map(o => o.device_id));
  el.append(h(`<div class="panel xlive">
    <div class="row between"><span class="label">Live example · road event #${e.id}</span><a href="#/map/${e.id}">Open on the map →</a></div>
    <h3>${esc(typeName(e.type))} <span class="status s-${e.status}">${esc(e.status)}</span></h3>
    <p class="faint" style="font-size:.86rem">${esc(e.validity_reason || '')} · ${e.observations.length} observation(s) from ${devs.size} device(s) · ±${Math.round(e.radius_m)} m</p>
    <div class="xobs">${e.observations.slice(0, 6).map(o => `<div class="xo">${o.thumb ? `<img src="${media(o.thumb)}" alt="">` : ''}
      <span class="mono">${esc(o.device_id)}</span><span class="mono faint">${fmtTime(o.observed_at)} · conf ${o.conf.toFixed(2)}</span>
      <span class="status s-${o.review_status === 'confirmed' ? 'verified' : o.review_status === 'rejected' ? 'rejected' : 'candidate'}">${esc(o.review_status.replace('_', ' '))}</span></div>`).join('')}</div>
    <div class="xhist">${e.history.map(x => `<span>${esc(x.action)}<i>${esc(x.by)}</i></span>`).join('<b>→</b>')}</div>
  </div>`));
}
