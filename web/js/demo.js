// One demo trip per module: the video, the facts of its latest run on this server, accuracy against the team's own
// labels of that footage, and the moments (click one to jump the video there). Everything comes from the server;
// with no run yet, the block offers to run it.
import { api, esc, h, pct, sec, typeName } from './util.js';

const DAMAGE = new Set(['pothole', 'alligator_crack', 'transverse_crack', 'longitudinal_crack']);
const SAFETY = new Set(['forward_collision_risk', 'vru_near_path', 'cut_in', 'hard_braking']);
const FAMILY = { road: DAMAGE, safety: SAFETY };

export async function demoBlock(el, sampleId, family, moduleName) {
  const samples = (await api('/api/v1/samples').catch(() => ({ samples: [] }))).samples;
  const s = samples.find(x => x.id === sampleId);
  if (!s) { el.innerHTML = ''; return; }
  const trips = (await api('/api/v1/trips').catch(() => ({ trips: [] }))).trips;
  const t = trips.find(x => x.filename === s.video && x.status === 'done');
  const ru = document.documentElement.lang === 'ru';
  el.innerHTML = '';
  const box = h(`<section class="demo panel">
    <div class="row between"><span class="label">Demo trip · ${esc(moduleName)}</span>${t ? `<a href="#/trip/${t.id}">Full trip report →</a>` : ''}</div>
    <h2>${esc(s.title)}</h2>
    <div class="demo-grid">
      <video src="/samples/${esc(s.video)}" controls muted playsinline preload="metadata" poster="/samples/${esc(s.poster)}"></video>
      <div class="demo-side"></div>
    </div>
    <div class="demo-moments"></div>
  </section>`);
  el.append(box);
  const side = box.querySelector('.demo-side'), moments = box.querySelector('.demo-moments'), video = box.querySelector('video');
  if (!t) {
    side.append(h(`<div class="stack"><p class="muted">Not run on this server yet. The system processes it exactly like an upload; the facts and the accuracy appear here.</p>
      <button class="btn primary">Run the demo trip <span class="arr">→</span></button><p class="mono faint run-msg" style="font-size:.76rem"></p></div>`));
    side.querySelector('button').onclick = async e => {
      e.target.disabled = true;
      const msg = side.querySelector('.run-msg');
      try {
        const r = await api(`/api/v1/samples/${sampleId}/run`, { method: 'POST' });
        for (;;) {
          const j = await api(`/api/v1/jobs/${r.job_id}`);
          msg.textContent = `processing · ${Math.round((j.progress || 0) * 100)}%`;
          if (j.status === 'done' || j.status === 'error') break;
          await new Promise(res => setTimeout(res, 1000));
        }
        demoBlock(el, sampleId, family, moduleName);
      } catch (err) { msg.textContent = err.message; e.target.disabled = false; }
    };
    return;
  }
  const [rep, ref] = await Promise.all([api(`/api/v1/trips/${t.id}`), api(`/api/v1/trips/${t.id}/reference`).catch(() => ({ available: false }))]);
  const fam = FAMILY[family];
  const obs = rep.observations.filter(o => fam.has(o.type));
  const labels = ref.available ? ref.labels.filter(g => fam.has(g.type)) : [];
  const refObs = ref.available ? ref.observations.filter(o => fam.has(o.type)) : [];
  const found = labels.filter(g => g.found).length, ok = refObs.filter(o => o.correct).length;
  const info = rep.trip.info || {}, perf = rep.trip.perf || {};
  side.append(h(`<div class="stack">
    <div class="facts">
      <div><span class="label">Video</span><b>${sec(rep.trip.analysed_s)} · ${perf.frames} frames · ${info.provider === 'CUDAExecutionProvider' ? 'GPU' : 'CPU'}</b></div>
      <div><span class="label">Location</span><b>${rep.trip.gps_source ? 'GPS track' : 'no GPS'}</b></div>
      <div><span class="label">Found by the system</span><b>${obs.length} observation(s)</b></div>
      ${ref.available ? `<div><span class="label">Accuracy against our labels</span><b>${found}/${labels.length} labelled moments found · ${ok}/${refObs.length} observations correct · ${refObs.length - ok} false alert(s)</b></div>`
        : '<div><span class="label">Accuracy</span><b>no labels for this footage</b></div>'}
    </div>
    ${ref.available && labels.length ? `<div class="demo-acc"><span style="width:${(100 * found / labels.length).toFixed(0)}%"></span></div><p class="faint" style="font-size:.8rem">recall ${pct(found / labels.length)}${refObs.length ? ` · precision ${pct(ok / refObs.length)}` : ''}</p>` : ''}
  </div>`));
  const seek = x => { video.currentTime = Math.max(0, x - 0.5); video.play().catch(() => {}); };
  const rows = labels.length ? labels.map(g => ({ t: g.start_s, t1: g.end_s, type: g.type, text: ru && g.note_ru ? g.note_ru : g.note, status: g.found ? 'found' : 'missed' }))
    : obs.map(o => ({ t: o.t_start, t1: o.t_end, type: o.label, text: '', status: 'system' }));
  const fa = refObs.filter(o => !o.correct).map(o => ({ t: o.t_peak, t1: o.t_peak, type: o.type, text: 'no labelled moment here', status: 'false alert' }));
  const all = [...rows, ...fa].sort((a, b) => a.t - b.t);
  moments.innerHTML = `<span class="label">Moments · click to watch</span><div class="mlist">${all.map((m, i) => `<button class="mrow" data-i="${i}">
    <span class="mono">${m.t.toFixed(1)}${m.t1 > m.t ? `–${m.t1.toFixed(1)}` : ''} s</span><b>${esc(typeName(m.type))}</b>
    <span class="mtext" data-noi18n>${esc(m.text)}</span>
    <span class="status ${m.status === 'found' ? 's-verified' : m.status === 'missed' ? 's-rejected' : m.status === 'false alert' ? 's-candidate' : ''}">${esc(m.status)}</span></button>`).join('') || '<p class="faint">No moments of this module in this trip.</p>'}</div>`;
  moments.onclick = e => { const b = e.target.closest('.mrow'); if (b) seek(all[+b.dataset.i].t); };
}
