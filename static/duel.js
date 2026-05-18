/* ── Utils ── */
function fmtPace(v) {
  if (!v) return '—';
  const m = Math.floor(v);
  const s = Math.round((v - m) * 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function fmtMin(min) {
  if (!min) return '0 min';
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h > 0 ? `${h}h${String(m).padStart(2, '0')}` : `${m} min`;
}

function fmtDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
}

/* ── Render ── */
function renderCard(cardId, period, winners, side) {
  const { label, start, end, stats } = period;
  const el = document.getElementById(cardId);
  const w = winners;

  function row(label, value, winKey) {
    const isWinner = winKey && w[winKey] === side;
    const badge = isWinner ? '<span class="win-badge">✓</span>' : '';
    return `<div class="stat-row${isWinner ? ' winner' : ''}">
      <span class="stat-label">${label}</span>
      <span class="stat-value">${value}${badge}</span>
    </div>`;
  }

  const typeColors = { VMA: '#EF4444', SEUIL: '#F59E0B', EF: '#10B981', OTHER: '#6B7280' };
  const typeLabels = { VMA: 'VMA', SEUIL: 'Seuil', EF: 'EF', OTHER: 'Autre' };
  const typeBreakdown = Object.entries(stats.by_type)
    .filter(([, n]) => n > 0)
    .map(([t, n]) => `<span style="color:${typeColors[t]}">${typeLabels[t]}&nbsp;${n}</span>`)
    .join('  ');

  el.innerHTML = `
    <div class="card-label">${label}</div>
    <div class="card-dates">${fmtDate(start)} → ${fmtDate(end)}</div>
    <div class="stat-list">
      ${row('Séances',    stats.count,                       'count')}
      ${row('Distance',   stats.km + ' km',                  'km')}
      ${row('Durée',      fmtMin(stats.min),                 null)}
      ${row('Dénivelé+',  stats.elevation + ' m',            'elevation')}
      ${row('Allure moy', fmtPace(stats.avg_pace) + ' /km',  'pace')}
      ${stats.avg_hr ? row('FC moy', stats.avg_hr + ' bpm',  null) : ''}
    </div>
    ${typeBreakdown ? `<div class="type-breakdown">${typeBreakdown}</div>` : ''}
  `;
}

async function loadDuel(period) {
  const res = await fetch(`/api/duel?period=${period}`);
  const data = await res.json();
  if (data.error) return;

  renderCard('card-a', data.period_a, data.winners, 'a');
  renderCard('card-b', data.period_b, data.winners, 'b');

  const scoreEl = document.getElementById('duel-score');
  const { a, b } = data.score;
  if (a === b) {
    scoreEl.textContent = 'Égalité !';
    scoreEl.className = 'duel-score tie';
  } else if (a > b) {
    scoreEl.textContent = `${data.period_a.label} gagne ${a}/${a + b} métriques`;
    scoreEl.className = 'duel-score win-a';
  } else {
    scoreEl.textContent = `${data.period_b.label} gagne ${b}/${a + b} métriques`;
    scoreEl.className = 'duel-score win-b';
  }
  scoreEl.classList.remove('hidden');
}

/* ── Controls ── */
let currentPeriod = 'week';

document.querySelectorAll('.period-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentPeriod = btn.dataset.period;
    loadDuel(currentPeriod);
  });
});

/* ── Boot ── */
loadDuel(currentPeriod);
