/* ── State ── */
let currentPage = 1;
let pendingModalId = null;

/* ── DOM refs ── */
const filterForm    = document.getElementById('filter-form');
const chart         = document.getElementById('chart');
const chartEmpty    = document.getElementById('chart-empty');
const actBody       = document.getElementById('act-body');
const noActivities  = document.getElementById('no-activities');
const pagination    = document.getElementById('pagination');
const actCount      = document.getElementById('activity-count');
const filterStats   = document.getElementById('filter-stats');
const syncBtn       = document.getElementById('sync-btn');
const syncLabel     = document.getElementById('sync-label');
const typeModal     = document.getElementById('type-modal');
const modalActName  = document.getElementById('modal-activity-name');
const toast         = document.getElementById('toast');

/* ── Utils ── */
function buildParams(extraPage) {
  const fd = new FormData(filterForm);
  const params = new URLSearchParams();

  for (const [k, v] of fd.entries()) {
    if (k === 'session_types') continue;
    if (v !== '') params.set(k, v);
  }

  const types = [...filterForm.querySelectorAll('input[name="session_types"]:checked')]
    .map(el => el.value);
  if (types.length) params.set('session_types', types.join(','));

  if (extraPage) params.set('page', extraPage);
  return params;
}

function showToast(msg, type = 'success') {
  toast.textContent = msg;
  toast.className = `toast ${type}`;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => toast.classList.add('hidden'), 3000);
}

const TYPE_LABELS = { VMA: 'VMA', SEUIL: 'Seuil', EF: 'EF', OTHER: 'Autre' };

function badgeHtml(act) {
  const t = act.session_type;
  const isOverride = !!act.session_type_override;
  return `<button class="type-badge ${t}" data-id="${act.id}" data-name="${escHtml(act.name)}" title="${isOverride ? 'Override manuel' : 'Auto-classifié'}">
    ${isOverride ? '<span class="override-dot"></span>' : ''}
    ${TYPE_LABELS[t] || t}
  </button>`;
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Chart ── */
let chartInitialized = false;

async function loadChart() {
  const params = buildParams();
  const res = await fetch('/api/chart-data?' + params);
  const data = await res.json();

  if (!data.traces || data.traces.length === 0 || data.count === 0) {
    chart.classList.add('hidden');
    chartEmpty.classList.remove('hidden');
    return;
  }

  chart.classList.remove('hidden');
  chartEmpty.classList.add('hidden');

  const config = { responsive: true, displayModeBar: false };
  if (!chartInitialized) {
    Plotly.newPlot('chart', data.traces, data.layout, config);
    chartInitialized = true;
  } else {
    Plotly.react('chart', data.traces, data.layout, config);
  }
}

/* ── Activity table ── */
async function loadActivities(page = 1) {
  currentPage = page;
  const params = buildParams(page);
  const res = await fetch('/api/activities?' + params);
  const data = await res.json();

  actCount.textContent = data.total + ' séance' + (data.total > 1 ? 's' : '');

  if (!data.activities.length) {
    actBody.innerHTML = '';
    noActivities.classList.remove('hidden');
    pagination.innerHTML = '';
    return;
  }

  noActivities.classList.add('hidden');
  actBody.innerHTML = data.activities.map(act => `
    <tr>
      <td>${act.date}</td>
      <td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escHtml(act.name)}">${escHtml(act.name)}</td>
      <td>${badgeHtml(act)}</td>
      <td>${act.distance_km} km</td>
      <td>${act.duration_min} min</td>
      <td>${act.pace}</td>
      <td>${act.elevation ? act.elevation + ' m' : '—'}</td>
      <td>${act.avg_hr ? act.avg_hr + ' bpm' : '—'}</td>
    </tr>
  `).join('');

  // Bind type badge clicks
  actBody.querySelectorAll('.type-badge').forEach(btn => {
    btn.addEventListener('click', () => openTypeModal(+btn.dataset.id, btn.dataset.name));
  });

  renderPagination(data.page, data.pages);
}

function renderPagination(page, pages) {
  if (pages <= 1) { pagination.innerHTML = ''; return; }

  let html = `<button class="page-btn" ${page <= 1 ? 'disabled' : ''} data-p="${page - 1}">‹</button>`;
  const start = Math.max(1, page - 2);
  const end   = Math.min(pages, page + 2);
  if (start > 1) html += `<button class="page-btn" data-p="1">1</button>${start > 2 ? '<span style="color:var(--muted)">…</span>' : ''}`;
  for (let p = start; p <= end; p++) {
    html += `<button class="page-btn ${p === page ? 'active' : ''}" data-p="${p}">${p}</button>`;
  }
  if (end < pages) html += `${end < pages - 1 ? '<span style="color:var(--muted)">…</span>' : ''}<button class="page-btn" data-p="${pages}">${pages}</button>`;
  html += `<button class="page-btn" ${page >= pages ? 'disabled' : ''} data-p="${page + 1}">›</button>`;

  pagination.innerHTML = html;
  pagination.querySelectorAll('.page-btn:not([disabled])').forEach(btn => {
    btn.addEventListener('click', () => loadActivities(+btn.dataset.p));
  });
}

/* ── Filter form ── */
filterForm.addEventListener('submit', async e => {
  e.preventDefault();
  currentPage = 1;
  await Promise.all([loadChart(), loadActivities(1)]);
});

/* ── Sync ── */
syncBtn.addEventListener('click', async () => {
  syncBtn.disabled = true;
  syncLabel.textContent = '⟳ Synchronisation…';
  try {
    const res = await fetch('/api/sync', { method: 'POST' });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    showToast(`${data.synced} séance(s) importée(s)`, 'success');
    if (data.synced > 0) await Promise.all([loadChart(), loadActivities(currentPage)]);
  } catch (err) {
    showToast('Erreur sync : ' + err.message, 'error');
  } finally {
    syncBtn.disabled = false;
    syncLabel.textContent = '⟳ Synchroniser';
  }
});

/* ── Type modal ── */
function openTypeModal(actId, actName) {
  pendingModalId = actId;
  modalActName.textContent = actName;
  typeModal.classList.remove('hidden');
}

typeModal.querySelector('.modal-backdrop').addEventListener('click', closeModal);
document.getElementById('modal-cancel').addEventListener('click', closeModal);

function closeModal() {
  typeModal.classList.add('hidden');
  pendingModalId = null;
}

typeModal.querySelectorAll('.modal-type-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    if (!pendingModalId) return;
    const newType = btn.dataset.type;
    try {
      const res = await fetch(`/api/activities/${pendingModalId}/type`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_type: newType }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      showToast('Type mis à jour', 'success');
      closeModal();
      await Promise.all([loadChart(), loadActivities(currentPage)]);
    } catch (err) {
      showToast('Erreur : ' + err.message, 'error');
    }
  });
});

/* ── Init ── */
(async () => {
  await Promise.all([loadChart(), loadActivities(1)]);
})();
