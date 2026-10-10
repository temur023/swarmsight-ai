import { api, esc, figure, h, pct, typeName } from './util.js';

export default async function evidence(root) {
  const [m, hl, reg] = await Promise.all([api('/api/v1/metrics').catch(() => ({})), api('/api/v1/health').catch(() => ({})), api('/api/v1/data').catch(() => ({}))]);
  const rd = m.road_damage_eval, tk = m.tashkent_eval, ev = m.event_mining_eval, live = m.live || {};
  const ui = h(`<div class="wrap">
    <section class="page-head">
      <span class="label">Evidence</span>
      <h1>What we measured, on data the models never saw.</h1>
      <p class="lead">A good detector score does not prove a good event. We report the detector, the events, the data reduction and
        the speed separately, with the data behind each number and where it fails.</p>
    </section>
    <section class="section"><div class="section-head"><span class="label">Events</span>
      <div><h2>Event mining on labelled trips</h2><p class="muted">Each trip's events marked by the team as time intervals; a mined event counts when it overlaps one of the same type.
        Script: <span class="mono">benchmarks/event_mining_eval.py</span>.</p></div></div>
      <div id="ev"></div></section>
    <section class="section"><div class="section-head"><span class="label">Live</span>
      <div><h2>Precision as moderators decide on this server</h2><p class="muted">Of the candidates a person has decided on, how many the model got right. Grows with every review.</p></div></div>
      <div id="live"></div></section>
    <section class="section"><div class="section-head"><span class="label">Detector</span>
      <div><h2>Road damage, trained by us</h2><p class="muted">YOLO11n trained on RDD2022 (6,000 images, 6 countries), evaluated on 1,500 held-out images and on our Tashkent test set.</p></div></div>
      <div id="det"></div></section>
    <section class="section"><div class="section-head"><span class="label">Speed</span>
      <div><h2>On the server that runs this site</h2></div></div><div id="speed"></div></section>
    <section class="section"><div class="section-head"><span class="label">Known failures</span><div>
      <ul class="rules">
        <li><b>Distant and small objects.</b> A motorcycle 25–50 px tall is missed (our own Tashkent crossing trip): the conflict in that video is not mined.</li>
        <li><b>Our own car turning</b> moves every box sideways; the cut-in rule compensates with the scene's median motion, which fails when few other cars are tracked.</li>
        <li><b>Time to contact from box growth</b> also fires when we brake normally behind a queue. That is why safety episodes go to review, never straight to a score.</li>
        <li><b>Shadows, patches, manholes, wet asphalt</b> look like damage; night and rain reduce recall (−58% mAP at night in our robustness test).</li>
        <li><b>One forward camera</b> does not see side lanes; GPS on a phone is ±5–15 m, so a pothole can land in the next lane. Positions carry their uncertainty.</li>
        <li><b>Privacy</b> blurring comes from detector boxes: a face or plate the detector misses can stay visible. Production needs dedicated face and plate models.</li>
      </ul></div></div></section>
    <section class="section"><div class="section-head"><span class="label">Data</span><div><h2>Datasets, licences, models</h2></div></div>
      <table class="tbl"><thead><tr><th>Data</th><th>Role</th><th>Licence</th><th>Source</th></tr></thead><tbody id="reg"></tbody></table></section>
  </div>`);
  root.append(ui);

  // events
  const evEl = ui.querySelector('#ev');
  if (ev) {
    const o = ev.overall || {};
    evEl.append(h(`<div class="nums4">
      ${figure(o.precision != null ? o.precision.toFixed(2) : null, '', 'event precision', `${o.tp ?? '—'} of ${o.predictions ?? '—'} mined events are real`)}
      ${figure(o.recall != null ? o.recall.toFixed(2) : null, '', 'event recall', `${o.tp ?? '—'} of ${o.ground_truth ?? '—'} labelled events found`)}
      ${figure(o.false_alerts_per_hour != null ? Math.round(o.false_alerts_per_hour) : null, '/h', 'false alerts per hour of video')}
      ${figure(ev.reduction?.kept_ratio != null ? (100 * ev.reduction.kept_ratio).toFixed(0) : null, '%', 'of video kept', ev.reduction?.event_retention != null ? `while keeping ${pct(ev.reduction.event_retention)} of labelled events` : '')}
    </div>`));
    evEl.append(h(`<p class="note" style="margin-top:1rem">${esc((ev.caveats || []).join(' · ') || '')} · ${ev.videos?.length ?? '?'} labelled trip(s), ${Math.round(ev.total_video_s || 0)} s of video.</p>`));
  } else evEl.append(h('<p class="note">No labelled trips evaluated yet.</p>'));

  // live precision
  const lp = live.review_precision || {};
  ui.querySelector('#live').append(h(Object.keys(lp).length ? `<table class="tbl"><thead><tr><th>Mined as</th><th class="r">Decided</th><th class="r">Right</th><th class="r">Precision</th></tr></thead>
    <tbody>${Object.entries(lp).map(([k, v]) => `<tr><td>${esc(typeName(k))}</td><td class="r">${v.decided}</td><td class="r">${v.correct}</td><td class="r">${v.precision.toFixed(2)}</td></tr>`).join('')}</tbody></table>`
    : '<p class="note">No moderator decisions yet on this server.</p>'));

  // detector
  if (rd) {
    const pc = rd.per_country || {};
    ui.querySelector('#det').append(h(`<div><div class="nums4">
      ${figure(rd.test.map50.toFixed(2), 'mAP@.5', 'all four damage types, 1,500 held-out RDD2022 images')}
      ${figure(rd.test.per_class.pothole.ap50.toFixed(2), 'AP@.5', 'potholes')}
      ${tk ? figure(tk.ap_image.toFixed(2), 'AP', `Tashkent street photos, image level (${tk.n_images} images; random ${(tk.n_positive / tk.n_images).toFixed(2)})`) : ''}
      ${tk ? figure(pct(tk.precision_at_thr), '', `precision in Tashkent at the operating threshold · recall ${pct(tk.recall_at_thr)}`) : ''}
    </div>
    <p class="note" style="margin-top:1rem">By country (mAP@.5): ${Object.entries(pc).map(([k, v]) => `${k.replace('_', ' ')} ${v.map50.toFixed(2)}`).join(' · ')}.
      Tashkent labels: ${esc(tk?.labels || '')}.</p></div>`));
  }

  // speed
  const fm = hl.frame_ms;
  ui.querySelector('#speed').append(h(`<div class="nums4">
    ${figure(fm ? Math.round(fm.p50) : null, 'ms', 'per analysed frame, both detectors (p50, live on this server)', fm ? `${fm.n} frames · p95 ${Math.round(fm.p95)} ms` : 'no trips processed yet')}
    ${figure(hl.inference ? hl.inference.split(' ')[0] : null, '', 'inference device', esc(hl.inference || ''))}
    ${figure(ev?.latency?.wall_s_per_video_min != null ? ev.latency.wall_s_per_video_min.toFixed(0) : null, 's', 'server time per minute of video, including clips', ev?.latency?.provider || '')}
    ${figure(hl.hardware?.cpu_count, 'vCPU', esc(hl.clips || ''))}
  </div>`));

  // registry
  ui.querySelector('#reg').innerHTML = (reg.datasets || []).map(d => `<tr><td><b>${esc(d.name)}</b></td><td>${esc(d.role)}</td><td>${esc(d.license)}</td>
    <td>${d.source?.startsWith('http') ? `<a href="${esc(d.source)}" target="_blank" rel="noopener">source</a>` : esc(d.source || '')}</td></tr>`).join('')
    + (reg.models || []).map(d => `<tr><td><b>${esc(d.name)}</b></td><td>${esc(d.role)}</td><td>${esc(d.license)}</td><td>${esc(d.source || '')}</td></tr>`).join('');
}
