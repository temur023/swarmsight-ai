import { api, esc, h, KIND, REVIEW, typeName } from './util.js';

const reviewer = () => { try { return localStorage.getItem('swarmsight.reviewer') || 'web-moderator'; } catch { return 'web-moderator'; } };

// Confirm / reject / correct for one observation. Calls onDone(updatedObservation).
export function reviewControls(o, labels, onDone) {
  const kinds = Object.entries(labels);
  const opts = kinds.map(([k, ls]) => `<optgroup label="${esc(KIND[k]?.name || k)}">${ls.map(l => `<option value="${l}" ${l === o.label ? 'selected' : ''}>${esc(typeName(l))}</option>`).join('')}</optgroup>`).join('');
  const el = h(`<div class="rev">
    <div class="row">
      <button class="btn primary" data-a="confirm" title="Y">Confirm</button>
      <button class="btn" data-a="reject" title="N">Reject</button>
      <select class="sel" aria-label="correct the type">${opts}</select>
      <button class="btn" data-a="correct">Correct type</button>
    </div>
    <input class="field" placeholder="note for the audit log (optional)" maxlength="300">
    <p class="mono faint msg" style="font-size:.74rem"></p>
  </div>`);
  el.onclick = async e => {
    const a = e.target.closest('button')?.dataset.a;
    if (!a) return;
    el.querySelectorAll('button').forEach(b => { b.disabled = true; });
    try {
      const r = await api(`/api/v1/observations/${o.id}/review`, { method: 'POST', json: {
        action: a, label: a === 'correct' ? el.querySelector('select').value : null, note: el.querySelector('input').value, reviewer: reviewer() } });
      onDone(r);
    } catch (err) {
      el.querySelector('.msg').textContent = err.message;
      el.querySelectorAll('button').forEach(b => { b.disabled = false; });
    }
  };
  return el;
}

export function statusChip(o) {
  const cls = { needs_review: 's-candidate', confirmed: 's-verified', corrected: 's-corroborated', rejected: 's-rejected' }[o.review_status] || '';
  return `<span class="status ${cls}">${esc(REVIEW[o.review_status] || o.review_status)}</span>`;
}

export function kindChip(kind) {
  const k = KIND[kind] || { name: kind, col: 'var(--ink-3)' };
  return `<span class="kchip"><i style="background:${k.col}"></i>${esc(k.name)}</span>`;
}

// What the system read from the evidence, in words (no causal claims for safety episodes).
export function evidenceText(o) {
  const e = o.evidence || {};
  const bits = [];
  if (e.min_ttc_s != null) bits.push(`time to contact ${e.min_ttc_s} s`);
  if (e.road_user) bits.push(String(e.road_user).replace(/_/g, ' '));
  if (e.from_side) bits.push(`moved in from the ${e.from_side} over ${e.over_s} s`);
  if (e.peak_decel_ms2 != null) bits.push(`peak deceleration ${e.peak_decel_ms2} m/s² (${e.signal === 'imu' ? 'IMU' : 'GPS speed'}), ${e.speed_before_kmh} → ${e.speed_after_kmh} km/h`);
  if (e.interpretation) bits.push(e.interpretation);
  if (e.frames_seen) bits.push(`seen in ${e.frames_seen} analysed frame${e.frames_seen === 1 ? '' : 's'}`);
  if (e.instances) bits.push(`${e.instances} instance(s) in the photo`);
  if (e.also) bits.push(`also: ${e.also.map(a => typeName(a.type)).join(', ')}`);
  if (e.selection) bits.push(e.selection);
  if (e.causal_claim) bits.push('cause: not established · driver fault: not determined');
  return bits.join(' · ');
}
