/* ── Constants ── */
const TYPE_COLORS = { VMA: '#EF4444', SEUIL: '#F59E0B', EF: '#10B981', OTHER: '#6B7280' };
const TYPE_LABELS = { VMA: 'VMA', SEUIL: 'Seuil', EF: 'EF', OTHER: 'Autre' };

/* ── State ── */
let mapInstance, allActivities = [], polylineLayers = [];
let selectedTypes = new Set(
  [...document.querySelectorAll('.type-filter:checked')].map(cb => cb.value)
);
let panelChartsInitialized = false;

/* ── Polyline decoder (Google Encoded Polyline Algorithm) ── */
function decodePolyline(str) {
  const coords = [];
  let i = 0, lat = 0, lng = 0;
  while (i < str.length) {
    let b, shift = 0, res = 0;
    do { b = str.charCodeAt(i++) - 63; res |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
    lat += (res & 1) ? ~(res >> 1) : (res >> 1);
    shift = 0; res = 0;
    do { b = str.charCodeAt(i++) - 63; res |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
    lng += (res & 1) ? ~(res >> 1) : (res >> 1);
    coords.push([lat / 1e5, lng / 1e5]);
  }
  return coords;
}

/* ── Map init ── */
function initMap() {
  mapInstance = L.map('map-view', { zoomControl: true }).setView([46.5, 2.5], 6);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(mapInstance);
}

/* ── Load & render ── */
async function loadActivities() {
  const res = await fetch('/api/map-data');
  const data = await res.json();
  allActivities = data.activities || [];

  const missing = data.without_polyline || 0;
  const countEl = document.getElementById('map-count');
  countEl.textContent = `${allActivities.length} tracé${allActivities.length > 1 ? 's' : ''}`;
  if (allActivities.length === 0) {
    countEl.innerHTML += `<br><span style="color:var(--orange);font-size:10px">Cliquez "Synchroniser" sur le Dashboard pour charger les tracés</span>`;
  } else if (missing > 0) {
    countEl.innerHTML += `<br><span style="color:var(--muted);font-size:10px">${missing} sans tracé GPS</span>`;
  }

  renderPolylines();
}

function renderPolylines() {
  polylineLayers.forEach(l => mapInstance.removeLayer(l));
  polylineLayers = [];
  const bounds = [];

  allActivities
    .filter(a => selectedTypes.has(a.type))
    .forEach(act => {
      if (!act.polyline) return;
      const coords = decodePolyline(act.polyline);
      if (!coords.length) return;
      const line = L.polyline(coords, {
        color: TYPE_COLORS[act.type] || '#6B7280',
        weight: 3,
        opacity: 0.55,
      });
      line.on('click', () => openPanel(act));
      line.on('mouseover', function () { this.setStyle({ weight: 5, opacity: 0.85 }); });
      line.on('mouseout',  function () { this.setStyle({ weight: 3, opacity: 0.55 }); });
      line.addTo(mapInstance);
      polylineLayers.push(line);
      coords.forEach(c => bounds.push(c));
    });

  if (bounds.length) mapInstance.fitBounds(bounds, { padding: [20, 20] });
}

/* ── Panel ── */
function openPanel(act) {
  const panel = document.getElementById('map-panel');
  panel.classList.remove('hidden');

  document.getElementById('panel-name').textContent = act.name;
  document.getElementById('panel-meta').innerHTML =
    `${act.date} · <span class="type-badge ${act.type}" style="display:inline-flex">${TYPE_LABELS[act.type]}</span>`;
  document.getElementById('panel-stats').innerHTML =
    `<span>${act.distance_km} km</span><span>${act.duration_min} min</span>` +
    `<span>${act.pace} /km</span>` +
    (act.avg_hr ? `<span>${act.avg_hr} bpm</span>` : '') +
    (act.elevation ? `<span>${act.elevation} m D+</span>` : '') +
    `<a href="https://www.strava.com/activities/${act.strava_id}" target="_blank" rel="noopener" class="strava-link panel-strava">Voir sur Strava ↗</a>`;

  document.getElementById('panel-loading').classList.remove('hidden');
  ['panel-chart-hr', 'panel-chart-pace', 'panel-chart-alt', 'panel-no-streams'].forEach(id => {
    document.getElementById(id).classList.add('hidden');
  });
  panelChartsInitialized = false;

  loadStreams(act.strava_id);
}

async function loadStreams(stravaId) {
  try {
    const res = await fetch(`/api/activities/${stravaId}/streams`);
    const s = await res.json();
    document.getElementById('panel-loading').classList.add('hidden');

    const dist = (s.distance || []).map(d => Math.round(d / 10) / 100); // km
    if (!dist.length) {
      document.getElementById('panel-no-streams').classList.remove('hidden');
      return;
    }

    const cfg = { responsive: true, displayModeBar: false };
    const layout = (title, yreversed) => ({
      paper_bgcolor: '#0F172A', plot_bgcolor: '#1E293B',
      font: { color: '#F1F5F9', family: 'Inter, system-ui, sans-serif', size: 10 },
      margin: { l: 45, r: 10, t: 6, b: 32 },
      hovermode: 'closest',
      xaxis: { title: 'km', gridcolor: '#334155', zerolinecolor: '#334155', tickformat: '.1f' },
      yaxis: { title, gridcolor: '#334155', zerolinecolor: '#334155',
               ...(yreversed ? { autorange: 'reversed', tickformat: '.2f' } : {}) },
      showlegend: false,
    });

    if (s.heartrate && s.heartrate.length) {
      const el = document.getElementById('panel-chart-hr');
      el.classList.remove('hidden');
      const fn = panelChartsInitialized ? Plotly.react : Plotly.newPlot;
      fn('panel-chart-hr', [{ x: dist, y: s.heartrate, type: 'scatter', mode: 'lines',
        line: { color: '#EF4444', width: 1.5 }, hovertemplate: '%{y} bpm<extra></extra>' }],
        layout('FC (bpm)', false), cfg);
    }

    if (s.velocity && s.velocity.length) {
      const pace = s.velocity.map(v => v > 0 ? 1000 / (v * 60) : null);
      const el = document.getElementById('panel-chart-pace');
      el.classList.remove('hidden');
      const fn = panelChartsInitialized ? Plotly.react : Plotly.newPlot;
      fn('panel-chart-pace', [{ x: dist, y: pace, type: 'scatter', mode: 'lines',
        line: { color: '#10B981', width: 1.5 }, hovertemplate: '%{y:.2f} min/km<extra></extra>' }],
        layout('Allure (min/km)', true), cfg);
    }

    if (s.altitude && s.altitude.length) {
      const el = document.getElementById('panel-chart-alt');
      el.classList.remove('hidden');
      const fn = panelChartsInitialized ? Plotly.react : Plotly.newPlot;
      fn('panel-chart-alt', [{ x: dist, y: s.altitude, type: 'scatter', mode: 'lines',
        fill: 'tozeroy', fillcolor: 'rgba(59,130,246,0.15)',
        line: { color: '#3B82F6', width: 1.5 }, hovertemplate: '%{y:.0f} m<extra></extra>' }],
        layout('Altitude (m)', false), cfg);
    }

    if (!s.heartrate?.length && !s.velocity?.length && !s.altitude?.length) {
      document.getElementById('panel-no-streams').classList.remove('hidden');
    }

    panelChartsInitialized = true;
  } catch {
    document.getElementById('panel-loading').classList.add('hidden');
    document.getElementById('panel-no-streams').classList.remove('hidden');
  }
}

/* ── Event listeners ── */
document.getElementById('panel-close').addEventListener('click', () => {
  document.getElementById('map-panel').classList.add('hidden');
});

document.querySelectorAll('.type-filter').forEach(cb => {
  cb.addEventListener('change', () => {
    if (cb.checked) selectedTypes.add(cb.value);
    else selectedTypes.delete(cb.value);
    renderPolylines();
  });
});

/* ── Boot ── */
initMap();
loadActivities();
