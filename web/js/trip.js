import { api, baseLayer, C, clipPlayer, deviceId, drawBox, dropZone, esc, fitCanvas, geolocate, h, KIND, locText, media, pct, pretty, sec, streamJob, TASHKENT, typeName } from './util.js';
import { evidenceText, kindChip, reviewControls, statusChip } from './components.js';
import { queueBadge } from './app.js';

export default async function trip(root, rest) {
  if (rest[0]) return report(root, rest[0]);
  return upload(root);
}

// ------------------------------------------------------------------------------------------- upload
function drawFrame(ov, stage, fr) {
  const r = stage.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const ctx = fitCanvas(ov, Math.round(r.width * dpr), Math.round(r.height * dpr));
  ctx.clearRect(0, 0, ov.width, ov.height);
  if (!fr) return;
  const s = ov.width / fr.w;
  for (const u of fr.users || []) {
    if (u.ttc && u.ttc < 3) drawBox(ctx, u.bbox, `${pretty(u.cls)} · contact ${u.ttc} s`, C.critical, { scale: s, lw: 2.5 });
    else { ctx.save(); ctx.globalAlpha = 0.5; drawBox(ctx, u.bbox, '', C.own, { scale: s, lw: 1.2 }); ctx.restore(); }
  }
  for (const d of fr.damage || []) drawBox(ctx, d.bbox, `${pretty(d.cls)} ${Math.round(d.conf * 100)}%`, C.hazard, { scale: s, fill: true, lw: 2 });
}

async function upload(root) {
  const ui = h(`<div class="wrap">
    <section class="page-head">
      <span class="label">01 · Upload a trip</span>
      <h1>A trip goes in. A few verifiable moments come out.</h1>
      <p class="lead">Drop dashcam or phone footage from a drive. The server detects and tracks road users and road damage,
        proposes events, cuts each one into a short clip with context before and after, blurs faces and plates,
        and sends them to review. Nothing is published before a person confirms it.</p>
    </section>
    <div class="work">
      <div class="stack">
        <label class="drop" id="drop"><input type="file" accept="video/*,image/*">
          <b>Drop a trip video or a road photo</b><span class="again">Drop another trip or photo</span>
          <span class="faint">MP4, MOV, WEBM up to 300 MB · the first 2 minutes are analysed · or a JPG/PNG road photo</span></label>
        <div id="run" class="hidden stack">
          <div class="instrument" id="stage">
            <video id="vid" muted playsinline class="hidden"></video><img id="img" class="hidden" alt="uploaded photo">
            <canvas class="overlay" id="ov"></canvas><span class="tag" id="tag">input</span>
          </div>
          <div class="progress" id="prog"><div></div></div>
          <p class="mono faint" id="stagetxt" style="font-size:.78rem">uploading…</p>
        </div>
        <div class="panel" id="samples">
          <span class="label">No footage at hand</span>
          <div class="sample-trip" id="sample-trip"></div>
          <div class="row between" style="margin:1.1rem 0 .5rem"><span class="label">Or a Tashkent street photo · captions are our labels</span>
            <span class="mono faint" style="font-size:.7rem">Mapillary · CC BY-SA 4.0</span></div>
          <div class="samples" id="photos"></div>
        </div>
      </div>
      <aside>
        <div class="panel">
          <span class="label">Where it was driven (optional)</span>
          <label class="field-l">GPS track · GPX or CSV (t, lat, lon[, speed_kmh][, accel_long_ms2])
            <input type="file" id="track" accept=".gpx,.csv,text/csv,application/gpx+xml"></label>
          <label class="field-l">Track time at the start of the video, s <input class="field" id="offset" type="number" step="0.1" value="0"></label>
          <p class="faint" style="font-size:.84rem;margin:.6rem 0">No track? Pin one position for the whole video:</p>
          <div id="minimap" class="map small"></div>
          <div class="row" style="margin-top:.6rem"><button class="btn" id="gps">Use device GPS</button><button class="btn quiet" id="clear">Clear</button></div>
          <p class="mono faint" id="geo" style="margin-top:.5rem;font-size:.74rem">No location: events get no coordinates. We never invent them; a moderator can place an event by hand.</p>
        </div>
        <div class="panel">
          <span class="label">Rights</span>
          <label class="check"><input type="radio" name="rights" value="road_only" checked> Road events only</label>
          <label class="check"><input type="radio" name="rights" value="road_and_dataset"> Road events and the regional dataset</label>
          <p class="faint" style="font-size:.8rem;margin-top:.5rem">Choose the dataset only for footage you have the right to share for model training.
            Faces and plates are blurred either way; the original upload is deleted after processing.</p>
        </div>
      </aside>
    </div>
  </div>`);
  root.append(ui);

  // location: a track file, or one pin
  let pin = null, marker = null;
  const map = L.map(ui.querySelector('#minimap'), { zoomControl: false }).setView(TASHKENT, 12);
  baseLayer().addTo(map);
  const setPin = (g, label) => {
    pin = g;
    if (marker) marker.remove();
    marker = g ? L.circleMarker([g.lat, g.lon], { radius: 6, color: '#111316', weight: 2, fillColor: '#fff', fillOpacity: 1 }).addTo(map) : null;
    if (g) map.setView([g.lat, g.lon], Math.max(map.getZoom(), 15));
    ui.querySelector('#geo').textContent = g ? `${g.lat.toFixed(5)}, ${g.lon.toFixed(5)} · ±${Math.round(g.acc || 15)} m · ${label}` :
      'No location: events get no coordinates. We never invent them; a moderator can place an event by hand.';
  };
  map.on('click', e => setPin({ lat: e.latlng.lat, lon: e.latlng.lng, acc: 15 }, 'pinned on the map'));
  ui.querySelector('#gps').onclick = async () => { const g = await geolocate(); if (g) setPin(g, 'device GPS'); else ui.querySelector('#geo').textContent = 'GPS unavailable.'; };
  ui.querySelector('#clear').onclick = () => setPin(null);

  const stage = ui.querySelector('#stage'), vid = ui.querySelector('#vid'), img = ui.querySelector('#img'), ov = ui.querySelector('#ov');
  const prog = ui.querySelector('#prog > div'), stxt = ui.querySelector('#stagetxt');
  let job = null, raf = 0, frames = [];
  const loop = () => {
    const t = vid.currentTime;
    let best = null;
    for (const f of frames) { if (f.t <= t + 0.05) best = f; else break; }
    if (best && t - best.t > 0.6) best = null;
    drawFrame(ov, stage, best);
    raf = requestAnimationFrame(loop);
  };

  function follow(res, { videoSrc, imageSrc, tag }) {
    ui.querySelector('#run').classList.remove('hidden');
    ui.querySelector('#samples').classList.add('hidden');
    ui.querySelector('#drop').classList.add('compact');
    ui.querySelector('#tag').textContent = tag.slice(0, 48);
    frames = [];
    vid.classList.toggle('hidden', !videoSrc); img.classList.toggle('hidden', !imageSrc);
    if (videoSrc) { vid.src = videoSrc; vid.loop = true; }
    if (imageSrc) img.src = imageSrc;
    cancelAnimationFrame(raf); raf = requestAnimationFrame(loop);
    let started = false;
    stxt.textContent = 'queued on the server…';
    job = streamJob(res.job_id, {
      frame: m => {
        frames.push(m.frame);
        if (!started && frames.length > 2) { started = true; vid.play().catch(() => {}); }
        stxt.textContent = `analysing · ${frames.length} frames · t = ${m.frame.t.toFixed(1)} s · ${Math.round(m.frame.ms)} ms per frame`;
      },
      progress: p => { prog.style.width = `${Math.round(p * 100)}%`; if (p > 0.8) stxt.textContent = 'cutting clips, blurring faces and plates…'; },
      done: () => { prog.style.width = '100%'; queueBadge(); location.hash = `#/trip/${res.trip_id}`; },
      error: e => { stxt.innerHTML = `<span class="error">${esc(e)}</span>`; },
    });
  }

  async function send(file, extra = {}) {
    const fd = new FormData();
    fd.append('video', file);
    fd.append('device_id', deviceId());
    fd.append('rights_scope', ui.querySelector('input[name=rights]:checked').value);
    const tr = ui.querySelector('#track').files[0];
    if (tr) { fd.append('track', tr); fd.append('track_offset_s', ui.querySelector('#offset').value || '0'); }
    const g = extra.pin || pin;
    if (!tr && g) { fd.append('lat', g.lat); fd.append('lon', g.lon); fd.append('gps_accuracy_m', g.acc || 15); }
    const isImg = file.type.startsWith('image') || /\.(jpe?g|png|webp)$/i.test(file.name);
    ui.querySelector('#run').classList.remove('hidden');
    stxt.textContent = `uploading ${(file.size / 1e6).toFixed(1)} MB…`;
    try {
      const res = await api('/api/v1/trips', { method: 'POST', body: fd });
      const url = URL.createObjectURL(file);
      follow(res, isImg ? { imageSrc: url, tag: extra.tag || file.name } : { videoSrc: url, tag: extra.tag || file.name });
    } catch (e) { stxt.innerHTML = `<span class="error">${esc(e.message)}</span>`; }
  }
  dropZone(ui.querySelector('#drop'), 'video/*,image/*', fs => send(fs[0]));

  const s = await api('/api/v1/samples').catch(() => ({ samples: [], photos: [] }));
  const st = s.samples[0];
  if (st) {
    ui.querySelector('#sample-trip').append(h(`<div class="trip-card">
      <img src="/samples/${esc(st.poster)}" alt="">
      <div><b>${esc(st.title)}</b><p class="faint" style="font-size:.86rem;margin:.3rem 0 .7rem">${esc(st.about)}</p>
        <button class="btn primary" id="run-sample">Run this trip through the pipeline <span class="arr">→</span></button>
        <p class="mono faint" style="font-size:.72rem;margin-top:.5rem">same code path as an upload · ${st.duration_s} s · with its GPS track · dataset rights: ours</p></div>
    </div>`));
    ui.querySelector('#run-sample').onclick = async () => {
      const res = await api(`/api/v1/samples/${st.id}/run?device_id=${encodeURIComponent(deviceId())}`, { method: 'POST' });
      follow(res, { videoSrc: `/samples/${st.video}`, tag: st.title });
    };
  }
  const ph = ui.querySelector('#photos');
  ph.innerHTML = (s.photos || []).map((p, i) => `<button class="sample" data-i="${i}" title="our label: ${esc(p.our_label.map(typeName).join(', ') || 'no damage')}">
    <img src="${esc(p.image)}" alt="Tashkent street" loading="lazy"><span>${esc(p.our_label.length ? typeName(p.our_label[0]) + (p.our_label.length > 1 ? ` +${p.our_label.length - 1}` : '') : 'No damage')}</span></button>`).join('');
  ph.onclick = async e => {
    const b = e.target.closest('.sample'); if (!b) return;
    const p = s.photos[+b.dataset.i];
    const blob = await (await fetch(p.image)).blob();
    send(new File([blob], `tashkent-${p.id}.jpg`, { type: 'image/jpeg' }), { pin: { lat: p.lat, lon: p.lon, acc: 10 }, tag: `Tashkent · Mapillary ${p.id}` });
  };

  return () => { if (job) job.cancel(); cancelAnimationFrame(raf); map.remove(); };
}

// ------------------------------------------------------------------------------------------- report
async function report(root, id) {
  const wrap = h('<div class="wrap"><p class="faint" style="padding:3rem 0">Loading the trip…</p></div>');
  root.append(wrap);
  let r, labels = {};
  for (;;) {
    r = await api(`/api/v1/trips/${id}`).catch(e => ({ error: e.message }));
    if (r.error || r.trip.status !== 'processing') break;
    wrap.innerHTML = '<p class="faint" style="padding:3rem 0">Still processing on the server…</p>';
    await new Promise(res => setTimeout(res, 1500));
    if (!document.body.contains(wrap)) return;
  }
  if (r.error) { wrap.innerHTML = `<p class="error" style="padding:3rem 0">${esc(r.error)}</p>`; return; }
  labels = (await api('/api/v1/observations?limit=1').catch(() => ({ labels: {} }))).labels;
  const t = r.trip, red = t.reduction || {}, perf = t.perf || {}, info = t.info || {};
  const isPhoto = info.input === 'photo';
  const evs = r.observations.filter(o => o.kind !== 'baseline');
  const base = r.observations.filter(o => o.kind === 'baseline');
  const dur = t.analysed_s || 0;
  wrap.innerHTML = '';
  if (t.status === 'error') { wrap.append(h(`<section class="page-head"><span class="label">Trip ${esc(t.id)}</span><h1>Processing failed</h1><p class="lead error">${esc(t.error)}</p></section>`)); return; }
  const by = k => evs.filter(o => o.kind === k).length;
  wrap.append(h(`<section class="page-head">
    <span class="label">Trip ${esc(t.id)} · ${esc(t.filename || '')}</span>
    <h1>${evs.length ? `${evs.length} event${evs.length > 1 ? 's' : ''} ${isPhoto ? 'in one photo' : `in ${sec(dur)} of driving`}` : isPhoto ? 'No road damage in this photo' : `No events in ${sec(dur)} of driving`}</h1>
    <p class="lead">${evs.length ? `${by('road')} road · ${by('safety')} safety. Each is a candidate until a person confirms it.` :
      'That is a valid result: we do not invent an event when the footage has none.'}</p>
  </section>`));
  const facts = isPhoto ? [
    ['Input', 'one photo'], ['Analysed in', `${perf.ms_per_frame_p50} ms`], ['Location', t.gps_source ? { exif: 'photo EXIF', pin: 'pin' }[t.gps_source] || t.gps_source : 'none'],
    ['Rights', t.rights_scope === 'road_and_dataset' ? 'road + dataset' : 'road only']] : [
    ['Kept for review', `${sec(red.kept_s)} of ${sec(dur)} · ${pct(red.kept_ratio)}`], ['Clips', `${red.n_clips}${red.baseline_s ? ' (1 baseline)' : ''}`],
    ['Analysed', `${perf.frames} frames at ${info.sample_fps?.toFixed(1)} fps · ${perf.ms_per_frame_p50} ms per frame · ${info.provider === 'CUDAExecutionProvider' ? 'GPU' : 'CPU'}`],
    ['Server time', `${perf.wall_s} s for ${sec(dur)} of video (${perf.clips_s} s cutting clips)`],
    ['Location', t.gps_source ? { gpx: 'GPS track (GPX)', csv: 'GPS track (CSV)', single_point: 'one pin for the whole video' }[t.gps_source] || t.gps_source : 'none: events have no coordinates'],
    ['Rights', t.rights_scope === 'road_and_dataset' ? 'road events + regional dataset' : 'road events only']];
  wrap.append(h(`<div class="factrow">${facts.map(([k, v]) => `<div><span class="label">${k}</span><b>${esc(v)}</b></div>`).join('')}</div>`));

  if (!isPhoto && dur > 0) {
    const pos = x => `${(100 * x / dur).toFixed(2)}%`;
    const tl = h(`<section class="section"><div class="section-head"><span class="label">Timeline</span>
      <div><p class="muted">Shaded: what is kept as clips. Everything else is analysed and discarded.</p></div></div>
      <div class="ttl">${r.clips.map(c => `<span class="seg-kept" style="left:${pos(c.t0)};width:${pos(c.t1 - c.t0)}"></span>`).join('')}
        ${r.observations.map(o => `<a class="mark" href="#/trip/${t.id}" data-o="${o.id}" style="left:${pos(o.t_peak)};background:${KIND[o.kind]?.col}" title="${esc(typeName(o.label))} · ${o.t_peak} s"></a>`).join('')}</div>
      <div class="row between mono faint" style="font-size:.72rem;margin-top:.4rem"><span>0 s</span><span>${sec(dur)}</span></div>
      <div class="legend" style="margin-top:.8rem">${Object.entries(KIND).map(([k, v]) => `<span><i style="background:${v.col}"></i>${v.name} → ${v.dest}</span>`).join('')}</div>
    </section>`);
    tl.querySelector('.ttl').onclick = e => { const m = e.target.closest('.mark'); if (!m) return; e.preventDefault(); wrap.querySelector(`#o${m.dataset.o}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }); };
    wrap.append(tl);
  }

  const list = h(`<section class="section"><div class="section-head"><span class="label">Events</span>
    <div><p class="muted">Review here or in the <a href="#/review">review center</a>. Confirmed road damage with a location becomes a verified road event.</p></div></div>
    <div class="cards" id="cards"></div></section>`);
  wrap.append(list);
  const cards = list.querySelector('#cards');
  const card = o => {
    const el = h(`<article class="ecard" id="o${o.id}">
      <div class="media">${clipPlayer(o)}</div>
      <div class="body">
        <div class="row between">${kindChip(o.kind)}${statusChip(o)}</div>
        <h3>${esc(typeName(o.label))}${o.label !== o.type ? ` <span class="faint" style="font-weight:400">(model: ${esc(typeName(o.type))})</span>` : ''}</h3>
        <table class="kv"><tbody>
          ${isPhoto ? '' : `<tr><th>When</th><td>${o.t_start.toFixed(1)}–${o.t_end.toFixed(1)} s · peak ${o.t_peak.toFixed(1)} s</td></tr>`}
          ${o.kind !== 'baseline' ? `<tr><th>Model</th><td>confidence ${o.conf.toFixed(2)} · severity ${o.severity.toFixed(2)}</td></tr>` : ''}
          <tr><th>Where</th><td>${esc(locText(o))}</td></tr>
          <tr><th>Goes to</th><td>${esc(KIND[o.kind]?.dest || '')}${o.event ? ` · <a href="#/map/${o.event.id}">road event #${o.event.id}</a> <span class="status s-${o.event.status}">${o.event.status}</span>` : ''}</td></tr>
          <tr><th>Data value</th><td>${o.data_value ?? '—'} <span class="faint">${o.value_parts ? Object.entries(o.value_parts).map(([k, v]) => `${k.replace('_', ' ')} ${v}`).join(' · ') : ''}</span></td></tr>
        </tbody></table>
        <p class="evtext">${esc(evidenceText(o))}</p>
        <div class="revslot"></div>
      </div>
    </article>`);
    if (o.review_status === 'needs_review') {
      el.querySelector('.revslot').append(reviewControls(o, labels, async () => { queueBadge(); const nr = await api(`/api/v1/trips/${id}`); const no = nr.observations.find(x => x.id === o.id); el.replaceWith(card(no)); }));
    }
    return el;
  };
  for (const o of [...evs, ...base]) cards.append(card(o));
  if (!evs.length && !base.length) cards.append(h('<p class="faint">Nothing to review.</p>'));

  const pts = r.track.length ? r.track : [];
  const located = r.observations.filter(o => o.lat != null);
  if (pts.length || located.length) {
    const sec2 = h(`<section class="section"><div class="section-head"><span class="label">Route</span><div><p class="muted">The trip's GPS track (internal: never in the partner feed) and where each event was observed.</p></div></div>
      <div class="map" id="tmap" style="height:380px"></div></section>`);
    wrap.append(sec2);
    const m = L.map(sec2.querySelector('#tmap')).setView(TASHKENT, 13);
    baseLayer().addTo(m);
    const layers = [];
    if (pts.length > 1) layers.push(L.polyline(pts.map(p => [p[1], p[2]]), { color: '#111316', weight: 3, opacity: .7 }).addTo(m));
    for (const o of located) layers.push(L.circleMarker([o.lat, o.lon], { radius: 7, color: '#111316', weight: 1.5, fillColor: getComputedStyle(document.body).getPropertyValue(KIND[o.kind].col.slice(4, -1)) || '#d4800f', fillOpacity: .9 })
      .bindTooltip(`${typeName(o.label)} · ${o.t_peak} s`).addTo(m));
    const g = L.featureGroup(layers);
    if (layers.length) m.fitBounds(g.getBounds().pad(0.4), { maxZoom: 18 });
  }
  wrap.append(h(`<p class="mono faint" style="font-size:.74rem;margin:1rem 0 2rem">model ${esc(info.model_version || '')} · ${esc(info.provider || '')}${perf.ms_per_frame_p95 ? ` · p95 ${perf.ms_per_frame_p95} ms per frame` : ''}</p>`));
}
