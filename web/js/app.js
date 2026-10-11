import { $, $$, api } from './util.js';
import { startI18n } from './i18n.js';
import home from './home.js';
import trip from './trip.js';
import review from './review.js';
import map from './map.js';
import datamine from './datamine.js';
import evidence from './evidence.js';
import safety from './safety.js';

const routes = { '': home, trip, review, map, safety, datamine, evidence };
let cleanup = null;

async function render() {
  const [route, ...rest] = location.hash.replace(/^#\/?/, '').split('/');
  const view = routes[route] || home;
  if (cleanup) { try { cleanup(); } catch {} cleanup = null; }
  $$('#nav a').forEach(a => a.classList.toggle('active', a.dataset.route === (routes[route] ? route : '')));
  const root = $('#view');
  root.innerHTML = '';
  window.scrollTo(0, 0);
  cleanup = (await view(root, rest)) || null;
}

async function status() {
  const el = $('#server');
  try {
    const s = await api('/api/v1/health');
    el.className = 'server ok';
    el.querySelector('span').textContent = `server · ${s.inference.split(' ')[0]} · ${Object.keys(s.models).length} models`;
    el.title = Object.entries(s.models).map(([k, m]) => `${k}: ${m.file} (${m.provider})`).join('\n') + `\nclips: ${s.clips}\nblurring: ${s.anonymization || '—'}`;
  } catch {
    el.className = 'server bad';
    el.querySelector('span').textContent = 'server unreachable';
  }
  queueBadge();
}

export async function queueBadge() {
  try {
    const q = await api('/api/v1/observations?limit=1');
    const n = Object.values(q.queue).reduce((a, b) => a + b, 0);
    const b = $('#qbadge');
    b.textContent = n; b.classList.toggle('hidden', !n);
  } catch {}
}

startI18n();
window.addEventListener('hashchange', render);
render();
status();
setInterval(status, 30000);
