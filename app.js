/* ============================================================
   Red Regional · Visor GTFS  —  app.js
   ============================================================ */
'use strict';

const DATA = './data';
const DAY_LABEL = { laboral: 'Laboral', sabado: 'Sábado', domingo: 'Domingo' };

const state = {
  zones: [],
  current: null,      // slug
  day: 'laboral',
  freq: null,         // {laboral:[],sabado:[],domingo:[]}
  layers: { routes: null, stops: null },
  show: { routes: true, stops: true },
  chart: null,
};

/* ---------- helpers ---------- */
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const fmt = (n) => Number(n).toLocaleString('es-CL');
const fmt1 = (n) => Number(n).toLocaleString('es-CL', { maximumFractionDigits: 1 });

async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

function readableText(hex) {
  // elige texto claro/oscuro segun luminancia del color del servicio
  const h = (hex || '').replace('#', '');
  if (h.length < 6) return '#fff';
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  const L = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return L > 0.6 ? '#151E2C' : '#fff';
}

/* ============================================================
   Mapa
   ============================================================ */
const map = L.map('map', { preferCanvas: true, zoomControl: true, attributionControl: true })
  .setView([-33.45, -70.66], 11);

L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; OpenStreetMap &copy; CARTO · GTFS DTPR/MTT',
  subdomains: 'abcd', maxZoom: 20,
}).addTo(map);

/* ============================================================
   Carga inicial: indice de zonas
   ============================================================ */
async function boot() {
  let index;
  try {
    index = await getJSON(`${DATA}/index.json`);
  } catch (e) {
    $('#loader').innerHTML = '<span>No se pudo cargar data/index.json.<br>Ejecuta el workflow o el script de procesamiento.</span>';
    return;
  }
  state.zones = index.zones || [];
  if (index.generated_at) {
    const d = new Date(index.generated_at);
    $('#updated').textContent = d.toLocaleString('es-CL', { dateStyle: 'medium', timeStyle: 'short' });
  }
  renderZoneList(state.zones);

  // primera zona valida
  const first = state.zones.find((z) => !z.error);
  $('#loader').classList.add('hide');
  if (first) selectZone(first.slug);
}

/* ---------- sidebar ---------- */
function renderZoneList(zones) {
  const list = $('#zone-list');
  list.innerHTML = '';
  zones.forEach((z) => {
    const b = document.createElement('button');
    b.className = 'zone-item' + (z.error ? ' is-error' : '');
    b.dataset.slug = z.slug;
    b.innerHTML = z.error
      ? `<span class="zi-name">${z.name}</span><span class="zi-meta">sin datos</span>`
      : `<span class="zi-name">${z.name}</span><span class="zi-meta">${fmt(z.n_servicios)} serv</span>`;
    if (!z.error) b.addEventListener('click', () => selectZone(z.slug));
    list.appendChild(b);
  });
}

$('#zone-search').addEventListener('input', (e) => {
  const q = e.target.value.trim().toLowerCase();
  $$('.zone-item').forEach((el) => {
    const name = el.querySelector('.zi-name').textContent.toLowerCase();
    el.style.display = name.includes(q) ? '' : 'none';
  });
});

/* ============================================================
   Seleccion de zona
   ============================================================ */
async function selectZone(slug) {
  if (state.current === slug) return;
  state.current = slug;

  $$('.zone-item').forEach((el) => el.classList.toggle('is-active', el.dataset.slug === slug));
  hideTotem();

  let summary, routes, stops, freq;
  try {
    [summary, routes, stops, freq] = await Promise.all([
      getJSON(`${DATA}/${slug}/summary.json`),
      getJSON(`${DATA}/${slug}/routes.geojson`),
      getJSON(`${DATA}/${slug}/stops.geojson`),
      getJSON(`${DATA}/${slug}/frequency.json`),
    ]);
  } catch (e) {
    console.error(e);
    return;
  }

  $('#zone-name').textContent = summary.name;
  $('#daychips').hidden = false;
  state.freq = freq.freq;

  renderMetrics(summary);
  renderLegend(summary.legend);
  drawRoutes(routes);
  drawStops(stops);
  fitTo(summary.bbox);
  renderChart();
}

/* ---------- metricas ---------- */
function renderMetrics(s) {
  const veh = s.veh_km[state.day] ?? s.veh_km.laboral ?? 0;
  const exp = s.expediciones_tipo?.[state.day] ?? s.n_expediciones;
  const cards = [
    { label: 'Servicios', value: fmt(s.n_servicios), unit: '', foot: `${fmt(s.n_trazados)} trazados` },
    { label: 'Km de red', value: fmt1(s.red_km), unit: 'km', foot: 'trazados únicos' },
    { label: 'Paradas', value: fmt(s.n_paradas), unit: '', foot: 'stop_id únicos' },
    { label: 'Veh-km / día', value: fmt1(veh), unit: 'km', foot: `<b>${DAY_LABEL[state.day]}</b> · ${fmt(exp)} exp.` },
  ];
  $('#metrics').innerHTML = cards.map((c) => `
    <div class="metric">
      <div class="m-label">${c.label}</div>
      <div class="m-value">${c.value}<span class="m-unit">${c.unit}</span></div>
      <div class="m-foot">${c.foot}</div>
    </div>`).join('');
}

/* ---------- leyenda ---------- */
function renderLegend(legend = []) {
  $('#legend-count').textContent = `${legend.length}`;
  $('#legend').innerHTML = legend.map((l) => `
    <li title="${l.nombre || ''}">
      <span class="lg-patch" style="background:${l.color}"></span>
      <span class="lg-serv">${l.servicio}</span>
      <span class="lg-name">${l.nombre || ''}</span>
    </li>`).join('');
}

/* ---------- trazados ---------- */
function drawRoutes(geojson) {
  if (state.layers.routes) map.removeLayer(state.layers.routes);
  state.layers.routes = L.geoJSON(geojson, {
    style: (f) => ({
      color: f.properties.color || '#888',
      weight: 3, opacity: 0.9, lineCap: 'round', lineJoin: 'round',
    }),
    onEachFeature: (f, layer) => {
      const p = f.properties;
      layer.bindTooltip(
        `<b>${p.servicio}</b> → ${p.destino || '—'} · ${fmt1(p.km)} km`,
        { sticky: true, className: 'stop-tip' }
      );
      layer.on('mouseover', () => layer.setStyle({ weight: 6, opacity: 1 }));
      layer.on('mouseout', () => layer.setStyle({ weight: 3, opacity: 0.9 }));
    },
  });
  if (state.show.routes) state.layers.routes.addTo(map);
}

/* ---------- paradas ---------- */
function drawStops(geojson) {
  if (state.layers.stops) map.removeLayer(state.layers.stops);
  state.layers.stops = L.geoJSON(geojson, {
    pointToLayer: (f, latlng) => L.circleMarker(latlng, {
      radius: 4, weight: 1.4, color: '#0E1420',
      fillColor: '#F5B324', fillOpacity: 1,
    }),
    onEachFeature: (f, layer) => {
      const p = f.properties;
      layer.bindTooltip(p.stop_name || p.stop_id, { className: 'stop-tip', direction: 'top' });
      layer.on('click', () => showTotem(p));
      layer.on('mouseover', () => layer.setStyle({ radius: 6, fillColor: '#FFD36B' }));
      layer.on('mouseout',  () => layer.setStyle({ radius: 4, fillColor: '#F5B324' }));
    },
  });
  if (state.show.stops) state.layers.stops.addTo(map);
}

function fitTo(bbox) {
  if (!bbox || bbox.length !== 4) return;
  const [w, s, e, n] = bbox;
  map.fitBounds([[s, w], [n, e]], { padding: [30, 30], maxZoom: 15 });
}

/* ============================================================
   Signature: tótem de parada
   ============================================================ */
function showTotem(p) {
  $('#totem-id').textContent = p.stop_id;
  $('#totem-name').textContent = p.stop_name || '';
  const servs = p.servicios || [];
  $('#totem-sub').textContent = servs.length
    ? `${servs.length} servicio${servs.length > 1 ? 's' : ''} · destino`
    : 'Sin servicios asociados';
  $('#totem-list').innerHTML = servs.map((s) => `
    <li class="totem-row">
      <span class="serv-patch" style="background:${s.color};color:${readableText(s.color)}">${s.servicio}</span>
      <span class="serv-dest"><span class="arrow">→</span><span class="dname">${s.destino || '—'}</span></span>
    </li>`).join('');
  $('#totem').hidden = false;
}
function hideTotem() { $('#totem').hidden = true; }
$('#totem-close').addEventListener('click', hideTotem);

/* ============================================================
   Perfil de frecuencia (Chart.js)
   ============================================================ */
function renderChart() {
  if (!state.freq) return;
  const data = state.freq[state.day] || [];
  const labels = [...Array(24).keys()].map((h) => String(h).padStart(2, '0'));
  const ctx = $('#freq-chart');

  if (state.chart) {
    state.chart.data.datasets[0].data = data;
    state.chart.update();
    return;
  }
  state.chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data, backgroundColor: '#F5B324', hoverBackgroundColor: '#FFD36B',
        borderRadius: 2, barPercentage: 0.95, categoryPercentage: 0.9,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1B2637', borderColor: '#273246', borderWidth: 1,
          titleColor: '#E8EDF4', bodyColor: '#F5B324',
          callbacks: {
            title: (it) => `${it[0].label}:00 – ${it[0].label}:59 h`,
            label: (it) => ` ${fmt1(it.parsed.y)} salidas`,
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#5C6B80', font: { family: "'IBM Plex Mono'", size: 9 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
        y: { beginAtZero: true, grid: { color: '#1F2A3B' }, ticks: { color: '#5C6B80', font: { family: "'IBM Plex Mono'", size: 9 }, precision: 0 } },
      },
      animation: { duration: 250 },
    },
  });
}

/* ============================================================
   Controles: tipo de dia + capas
   ============================================================ */
$('#daychips').addEventListener('click', (e) => {
  const btn = e.target.closest('.daychip');
  if (!btn) return;
  state.day = btn.dataset.day;
  $$('.daychip').forEach((b) => b.classList.toggle('is-on', b === btn));
  renderChart();
  // refrescar veh-km / expediciones que dependen del tipo de dia
  const z = state.zones.find((x) => x.slug === state.current);
  if (z) getJSON(`${DATA}/${state.current}/summary.json`).then(renderMetrics);
});

$('#tg-routes').addEventListener('click', () => {
  state.show.routes = !state.show.routes;
  $('#tg-routes').classList.toggle('is-on', state.show.routes);
  if (!state.layers.routes) return;
  state.show.routes ? state.layers.routes.addTo(map) : map.removeLayer(state.layers.routes);
});
$('#tg-stops').addEventListener('click', () => {
  state.show.stops = !state.show.stops;
  $('#tg-stops').classList.toggle('is-on', state.show.stops);
  if (!state.layers.stops) return;
  state.show.stops ? state.layers.stops.addTo(map) : map.removeLayer(state.layers.stops);
});

boot();
