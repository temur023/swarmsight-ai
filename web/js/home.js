import { api, esc, figure, h, pct } from './util.js';

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
        <a class="btn" href="#/trip">Run our Tashkent trip</a>
      </div>
    </section>

    <section class="flowline">
      <div><span class="label">Trip</span><b>Video + GPS</b><p>Dashcam or phone on a taxi. Optional GPX/CSV track.</p></div>
      <div><span class="label">Event Mining</span><b>Detect · track · propose</b><p>Road damage, collision risks, cut-ins, hard braking; clips with context; faces and plates blurred.</p></div>
      <div><span class="label">Review</span><b>Confirm · reject · correct</b><p>Nothing is published before a person decides; every decision is logged.</p></div>
      <div class="out"><span class="label">RoadSense</span><b>Verified road events</b><p>Deduplicated across taxis; map, GeoJSON and CIFS feeds for partners.</p></div>
      <div class="out"><span class="label">Safety</span><b>Explained episodes</b><p>Hard braking with what the camera saw before it. Never a fine, never public.</p></div>
      <div class="out"><span class="label">DataMine</span><b>Regional dataset</b><p>The rare, uncertain, well-exposed moments, with rights and a split by trip.</p></div>
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
}
