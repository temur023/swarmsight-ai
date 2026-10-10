import { api, baseLayer, clipPlayer, esc, fmtTime, h, KIND, locText, media, TASHKENT, typeName } from './util.js';
import { evidenceText, kindChip, reviewControls, statusChip } from './components.js';
import { queueBadge } from './app.js';

const TABS = [['all', 'All open'], ['road', 'Road'], ['safety', 'Safety'], ['baseline', 'Baseline'], ['decided', 'Decided']];

export default async function review(root) {
  const ui = h(`<div class="wrap">
    <section class="page-head">
      <span class="label">02 · Review center</span>
      <h1>A person decides what the model only suspects.</h1>
      <p class="lead">Every mined event waits here as a candidate: confirm it, reject it or correct its type. Decisions are logged,
        change each device's reliability, turn confirmed road damage into verified road events and make clips eligible for the dataset.</p>
    </section>
    <div class="row between" style="margin-bottom:1rem">
      <div class="seg" id="tabs">${TABS.map(([k, n]) => `<button data-k="${k}">${n}<span class="cnt" data-c="${k}"></span></button>`).join('')}</div>
      <label class="mono faint" style="font-size:.76rem">reviewer <input class="field inline" id="who" placeholder="your name" maxlength="40"></label>
    </div>
    <div class="revgrid">
      <div class="queue" id="queue"></div>
      <div class="panel" id="detail"><p class="faint">Pick an item from the queue. Keys: <span class="mono">Y</span> confirm · <span class="mono">N</span> reject · <span class="mono">J/K</span> next/previous.</p></div>
    </div>
  </div>`);
  root.append(ui);
  const who = ui.querySelector('#who');
  try { who.value = localStorage.getItem('swarmsight.reviewer') || ''; } catch {}
  who.onchange = () => { try { localStorage.setItem('swarmsight.reviewer', who.value); } catch {} };

  let tab = 'all', items = [], cur = -1, labels = {}, mini = null;
  async function load() {
    ui.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.k === tab));
    const q = tab === 'decided' ? '?status=confirmed,corrected,rejected&limit=200' : `?status=needs_review&kind=${tab === 'all' ? 'all' : tab}&limit=200`;
    const r = await api(`/api/v1/observations${q}`);
    labels = r.labels;
    items = r.observations;
    const total = Object.values(r.queue).reduce((a, b) => a + b, 0);
    ui.querySelectorAll('.cnt').forEach(c => { const k = c.dataset.c; const n = k === 'all' ? total : r.queue[k]; c.textContent = n ? ` ${n}` : ''; });
    const qel = ui.querySelector('#queue');
    qel.innerHTML = items.length ? items.map((o, i) => `<button class="qitem" data-i="${i}">
        ${o.thumb ? `<img src="${media(o.thumb)}" alt="">` : '<span class="noimg"></span>'}
        <span><b>${esc(typeName(o.label))}</b><br><span class="mono faint">${esc(KIND[o.kind]?.name || o.kind)} · ${o.t_peak.toFixed(1)} s · ${esc((o.filename || '').slice(0, 22))}</span></span>
        ${tab === 'decided' ? statusChip(o) : `<span class="mono faint">${o.conf.toFixed(2)}</span>`}</button>`).join('')
      : `<p class="faint" style="padding:1rem 0">${tab === 'decided' ? 'No decisions yet.' : 'The queue is empty. <a href="#/trip">Upload a trip</a> to fill it.'}</p>`;
    if (items.length) show(Math.min(Math.max(cur, 0), items.length - 1)); else ui.querySelector('#detail').innerHTML = '<p class="faint">Nothing selected.</p>';
  }
  ui.querySelector('#queue').onclick = e => { const b = e.target.closest('.qitem'); if (b) show(+b.dataset.i); };
  ui.querySelector('#tabs').onclick = e => { const b = e.target.closest('button'); if (b) { tab = b.dataset.k; cur = 0; load(); } };

  async function show(i) {
    cur = i;
    ui.querySelectorAll('.qitem').forEach(b => b.classList.toggle('active', +b.dataset.i === i));
    const o = await api(`/api/v1/observations/${items[i].id}`);
    const d = ui.querySelector('#detail');
    if (mini) { mini.remove(); mini = null; }
    d.innerHTML = '';
    d.append(h(`<div class="stack">
      <div class="clipbox">${clipPlayer(o, { autoplay: true })}</div>
      <div class="row between">${kindChip(o.kind)}${statusChip(o)}</div>
      <h2 style="font-size:1.4rem">${esc(typeName(o.label))}${o.label !== o.type ? ` <span class="faint" style="font-weight:400;font-size:1rem">model said ${esc(typeName(o.type))}</span>` : ''}</h2>
      <p class="evtext">${esc(evidenceText(o))}</p>
      <table class="kv"><tbody>
        <tr><th>Trip</th><td><a href="#/trip/${o.trip_id}">${o.trip_id}</a> · ${o.evidence?.input === 'photo' ? 'photo report' : `${o.t_start.toFixed(1)}–${o.t_end.toFixed(1)} s`}</td></tr>
        <tr><th>Model</th><td>${o.kind === 'baseline' ? 'selected at random (seeded), not by the model' : `confidence ${o.conf.toFixed(2)} · uncertainty ${o.uncertainty} · ${esc(o.model_version)}`}</td></tr>
        <tr><th>Device</th><td>${esc(o.device_id)} · reliability ${o.device_reliability}</td></tr>
        <tr><th>Where</th><td>${esc(locText(o))}</td></tr>
        <tr><th>Goes to</th><td>${esc(KIND[o.kind]?.dest || '')}${o.event ? ` · <a href="#/map/${o.event.id}">road event #${o.event.id}</a> <span class="status s-${o.event.status}">${o.event.status}</span>` : ''}</td></tr>
      </tbody></table>
      <div id="rv"></div>
      <div id="loc"></div>
      ${o.reviews.length ? `<div><span class="label">Audit log</span><div class="list">${o.reviews.map(r => `<div class="item"><div><div class="t">${esc(r.action)}${r.old_label !== r.new_label ? ` · ${esc(typeName(r.old_label))} → ${esc(typeName(r.new_label))}` : ''}</div>
        <div class="m">${esc(r.reviewer)} · ${fmtTime(r.t)}${r.note ? ` · ${esc(r.note)}` : ''}</div></div></div>`).join('')}</div></div>` : ''}
    </div>`));
    const after = async () => { queueBadge(); const keep = cur; await load(); if (tab !== 'decided' && items.length) show(Math.min(keep, items.length - 1)); };
    if (o.review_status === 'needs_review' || tab === 'decided') d.querySelector('#rv').append(reviewControls(o, labels, after));
    if (o.kind === 'road' && o.lat == null) {
      const box = h(`<div><span class="label">No location</span><p class="faint" style="font-size:.84rem;margin:.3rem 0 .6rem">The video had no GPS. Click where the damage is to place it by hand (recorded as "set by a moderator").</p>
        <div class="map small" id="lmap"></div><p class="mono faint" id="lmsg" style="font-size:.74rem;margin-top:.4rem"></p></div>`);
      d.querySelector('#loc').append(box);
      mini = L.map(box.querySelector('#lmap'), { zoomControl: false }).setView(TASHKENT, 12);
      baseLayer().addTo(mini);
      mini.on('click', async e => {
        try {
          await api(`/api/v1/observations/${o.id}/location`, { method: 'POST', json: { lat: e.latlng.lat, lon: e.latlng.lng, uncertainty_m: 25, reviewer: who.value || 'web-moderator' } });
          show(cur);
        } catch (err) { box.querySelector('#lmsg').textContent = err.message; }
      });
    }
  }

  const keys = e => {
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
    if (e.key === 'j' && cur < items.length - 1) show(cur + 1);
    else if (e.key === 'k' && cur > 0) show(cur - 1);
    else if (e.key === 'y' || e.key === 'n') ui.querySelector(`#rv button[data-a="${e.key === 'y' ? 'confirm' : 'reject'}"]`)?.click();
  };
  document.addEventListener('keydown', keys);
  await load();
  return () => { document.removeEventListener('keydown', keys); if (mini) mini.remove(); };
}
