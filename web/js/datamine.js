import { api, esc, figure, fmtTime, h, media, pct, typeName } from './util.js';
import { demoBlock } from './demo.js';

export default async function datamine(root) {
  let lastMsg = '';
  const ui = h(`<div class="wrap">
    <section class="page-head">
      <span class="label">Module · DataMine</span>
      <h1>Not every hour of driving. The moments worth labelling.</h1>
      <p class="lead">The same clips that feed road events become a regional dataset for automotive AI: chosen by how new,
        uncertain and well exposed they are, balanced with ordinary driving, split by trip and exported with their rights.</p>
    </section>
    <div id="demo"></div>
    <div id="body"><p class="faint">Loading…</p></div>
  </div>`);
  root.append(ui);
  demoBlock(ui.querySelector('#demo'), 'tashkent-redmi', 'road', 'DataMine');
  async function load() {
    const s = await api('/api/v1/datasets/summary');
    const lv = s.by_level || {};
    const body = ui.querySelector('#body');
    body.innerHTML = '';
    body.append(h(`<div class="nums4">
      ${figure(s.trips, '', 'trips processed on this server')}
      ${figure(s.kept_ratio != null ? (100 * s.kept_ratio).toFixed(0) : null, '%', `of ${Math.round(s.analysed_s)} s of video kept as clips`, 'the rest is analysed and discarded')}
      ${figure(s.with_dataset_rights, '', 'clips with dataset rights', `${lv.reviewed || 0} reviewed · ${lv.raw_candidate || 0} raw · ${lv.rejected || 0} rejected`)}
      ${figure((s.exports || []).length, '', 'dataset versions exported')}
    </div>`));
    const bar = (obj, nameFn = x => x) => Object.keys(obj).length ? Object.entries(obj).sort((a, b) => b[1] - a[1]).map(([k, v]) => `<tr><td>${esc(nameFn(k))}</td><td class="r">${v}</td></tr>`).join('') : '<tr><td class="faint">none yet</td><td></td></tr>';
    body.append(h(`<section class="section"><div class="section-head"><span class="label">Coverage</span>
      <div><p class="muted">Clips from trips uploaded with dataset rights, excluding rejected ones. Train, val and test are split by trip, never by frame.</p></div></div>
      <div class="cols c3">
        <div><span class="label">By label</span><table class="tbl"><tbody>${bar(s.by_label, typeName)}</tbody></table></div>
        <div><span class="label">By line</span><table class="tbl"><tbody>${bar(s.by_kind)}</tbody></table></div>
        <div><span class="label">Reviewed, by split</span><table class="tbl"><tbody>${bar(s.by_split)}</tbody></table></div>
      </div></section>`));
    body.append(h(`<section class="section"><div class="section-head"><span class="label">Most valuable</span>
      <div><h2>Data value = ${Object.entries(s.weights).map(([k, v]) => `${v} × ${k.replace('_', ' ')}`).join(' + ')}</h2>
        <p class="muted">Novelty against what is already collected, model uncertainty, image quality and how rare the label still is.
          The weights are our starting point, not a tuned standard.</p></div></div>
      <div class="vgrid">${(s.top_value || []).map(o => `<a class="vcard" href="#/review"><img src="${media(o.thumb)}" alt="">
        <span><b>${esc(typeName(o.label))}</b><span class="mono">${o.data_value}</span></span></a>`).join('') || '<p class="faint">Upload a trip with dataset rights to see its clips ranked here.</p>'}</div></section>`));
    const ex = h(`<section class="section"><div class="section-head"><span class="label">Export</span>
      <div><h2>Versioned, with provenance</h2><p class="muted">A ZIP with a manifest (label after review, the model's label, interval, location and its source,
        rights scope, data value), anonymised clips, key frames with YOLO boxes and COCO-style annotations. Boxes are model
        pre-annotations, not checked by a person: we do not call any sample "benchmark-ready".</p></div></div>
      <div class="row"><button class="btn primary" id="exp">Export reviewed samples</button>
        <label class="check"><input type="checkbox" id="raw"> include unreviewed (raw candidates)</label></div>
      <p class="mono faint" id="emsg" style="font-size:.76rem;margin-top:.5rem">${esc(lastMsg)}</p>
      <div class="scroll-x" style="margin-top:1rem"><table class="tbl"><thead><tr><th>Version</th><th>Created</th><th class="r">Samples</th><th>Contents</th><th></th></tr></thead>
        <tbody>${(s.exports || []).map(e => `<tr><td class="mono">${esc(e.version)}</td><td>${fmtTime(e.created_at)}</td><td class="r">${e.n_samples}</td>
          <td class="mono faint" style="font-size:.76rem">${esc(Object.entries(e.summary.by_label || {}).map(([k, v]) => `${k} ${v}`).join(' · '))}${e.summary.include_unreviewed ? ' · incl. unreviewed' : ''}</td>
          <td><a class="btn" href="/api/v1/datasets/exports/${encodeURIComponent(e.version)}">Download · ${(e.summary.bytes / 1e6).toFixed(1)} MB</a></td></tr>`).join('') || '<tr><td colspan="5" class="faint">No exports yet.</td></tr>'}</tbody></table></div>
    </section>`);
    body.append(ex);
    ex.querySelector('#exp').onclick = async () => {
      ex.querySelector('#emsg').textContent = 'exporting…';
      try {
        const r = await api('/api/v1/datasets/exports', { method: 'POST', json: { include_unreviewed: ex.querySelector('#raw').checked } });
        lastMsg = `exported ${r.version}: ${r.n_samples} sample${r.n_samples === 1 ? '' : 's'}${r.n_samples ? '' : ' (confirm clips from trips uploaded with dataset rights first)'}`;
        load();
      } catch (e) { ex.querySelector('#emsg').textContent = e.message; }
    };
    body.append(h(`<details class="more"><summary>Rules of the dataset</summary><section class="section"><div class="section-head"><span class="label">Rules</span><div>
      <ul class="rules">
        <li><b>Rights first.</b> ${esc(s.rights.road_and_dataset)}. Trips uploaded as "${esc(s.rights.road_only)}" never enter an export.</li>
        <li><b>Not only incidents.</b> Each trip adds one random stretch of ordinary driving, so the dataset can still tell how rare an incident is.</li>
        <li><b>No leakage.</b> Split by trip: frames of one drive never sit in both train and test.</li>
        <li><b>Honest levels.</b> raw candidate → reviewed (a person confirmed the label). Boxes are model pre-annotations.</li>
        <li><b>Privacy.</b> Faces and plate areas are blurred from detector boxes before anything is stored. Best effort, not a guarantee.</li>
      </ul></div></div></section></details>`));
  }
  await load();
}
