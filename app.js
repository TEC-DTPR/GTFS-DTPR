'use strict';

const DATA = './data';
const DAY_LABEL = { laboral: 'Laboral', sabado: 'Sábado', domingo: 'Domingo' };

const state = {
  zones: [], current: null, day: 'laboral',
  freq: null, services: null, summary: null, censo: null,
  layers: { routes: null, stops: null },
  show: { routes: true, stops: true },
  sel: null,               // servicio seleccionado
  chart: null, svChart: null, edadChart: null, modalChart: null,
};

const EDAD_LABELS = ['0-5', '6-13', '14-17', '18-24', '25-44', '45-59', '60+'];
const EDAD_KEYS = ['n_edad_0_5', 'n_edad_6_1', 'n_edad_14_', 'n_edad_18_', 'n_edad_25_', 'n_edad_45_', 'n_edad_60_'];
const MODO_LABELS = ['Auto', 'T. Público', 'Caminata', 'Bicicleta', 'Moto', 'Acuático', 'Otros'];
const MODO_KEYS = ['n_transpor', 'n_transp_1', 'n_transp_2', 'n_transp_3', 'n_transp_4', 'n_transp_5', 'n_transp_6'];
const MODO_COLORS = ['#4F86C6', '#F5B324', '#48B27A', '#8E7BE0', '#E5734D', '#3FB8C4', '#7A889C'];

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const fmt  = (n) => Number(n).toLocaleString('es-CL');
const fmt1 = (n) => Number(n).toLocaleString('es-CL', { maximumFractionDigits: 1 });

async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}
function readableText(hex) {
  const h = (hex || '').replace('#', '');
  if (h.length < 6) return '#fff';
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? '#151E2C' : '#fff';
}
function headwayLabel(salidas) {
  if (!salidas || salidas <= 0) return '—';
  const h = 60 / salidas;
  return h >= 60 ? `${fmt1(h / 60)} h` : `${Math.round(h)} min`;
}

const map = L.map('map', { preferCanvas: true, zoomControl: true }).setView([-33.45, -70.66], 11);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; OpenStreetMap &copy; CARTO · GTFS DTPR/MTT', subdomains: 'abcd', maxZoom: 20,
}).addTo(map);

/* ---------------- boot ---------------- */
async function boot() {
  let index;
  try { index = await getJSON(`${DATA}/index.json`); }
  catch (e) { $('#loader').innerHTML = '<span>No se pudo cargar data/index.json.</span>'; return; }
  state.zones = index.zones || [];
  if (index.generated_at) {
    const d = new Date(index.generated_at);
    $('#updated').textContent = d.toLocaleString('es-CL', { dateStyle: 'medium', timeStyle: 'short' });
  }
  renderZoneList(state.zones);
  const first = state.zones.find((z) => !z.error);
  $('#loader').classList.add('hide');
  if (first) selectZone(first.slug);
}

function renderZoneList(zones) {
  const list = $('#zone-list'); list.innerHTML = '';
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
  $$('.zone-item').forEach((el) => { el.style.display = el.querySelector('.zi-name').textContent.toLowerCase().includes(q) ? '' : 'none'; });
});

/* ---------------- zona ---------------- */
async function selectZone(slug) {
  if (state.current === slug) return;
  state.current = slug;
  $$('.zone-item').forEach((el) => el.classList.toggle('is-active', el.dataset.slug === slug));
  hideTotem(); closeService();

  let summary, routes, stops, freq, services, censo;
  try {
    [summary, routes, stops, freq, services, censo] = await Promise.all([
      getJSON(`${DATA}/${slug}/summary.json`),
      getJSON(`${DATA}/${slug}/routes.geojson`),
      getJSON(`${DATA}/${slug}/stops.geojson`),
      getJSON(`${DATA}/${slug}/frequency.json`),
      getJSON(`${DATA}/${slug}/services.json`).catch(() => ({})),
      getJSON(`${DATA}/${slug}/censo.json`).catch(() => null),
    ]);
  } catch (e) { console.error(e); return; }

  state.summary = summary; state.freq = freq.freq; state.services = services || {}; state.censo = censo;
  $('#zone-name').textContent = summary.name;
  $('#daychips').hidden = false;

  renderMetrics(); renderLegend(summary.legend);
  drawRoutes(routes); drawStops(stops); fitTo(summary.bbox); renderChart();
  renderCenso('zona');
}

function renderMetrics() {
  const s = state.summary;
  const veh = s.veh_km[state.day] ?? s.veh_km.laboral ?? 0;
  const exp = s.expediciones_tipo?.[state.day] ?? s.n_expediciones;
  const tviaje = s.t_viaje_prom_min != null ? `${fmt1(s.t_viaje_prom_min)}<span class="m-unit">min</span>` : '—';
  const cards = [
    { label: 'Servicios', value: fmt(s.n_servicios), foot: `${fmt(s.n_trazados)} trazados` },
    { label: 'Km de red', value: `${fmt1(s.red_km)}<span class="m-unit">km</span>`, foot: `${fmt(s.km_mensual)} km/mes` },
    { label: 'Paradas', value: fmt(s.n_paradas), foot: 'stop_id únicos' },
    { label: 'Veh-km / día', value: `${fmt1(veh)}<span class="m-unit">km</span>`, foot: `<b>${DAY_LABEL[state.day]}</b> · ${fmt(exp)} exp.` },
  ];
  $('#metrics').innerHTML = cards.map((c) => `
    <div class="metric"><div class="m-label">${c.label}</div>
      <div class="m-value">${c.value}</div><div class="m-foot">${c.foot}</div></div>`).join('');
}

function renderLegend(legend = []) {
  $('#legend-count').textContent = `${legend.length}`;
  $('#legend').innerHTML = legend.map((l) => `
    <li data-serv="${l.servicio}" title="${l.nombre || ''}">
      <span class="lg-patch" style="background:${l.color}"></span>
      <span class="lg-serv">${l.servicio}</span>
      <span class="lg-name">${l.nombre || ''}</span></li>`).join('');
  $$('#legend li').forEach((li) => li.addEventListener('click', () => selectService(li.dataset.serv)));
}

/* ---------------- capas ---------------- */
function drawRoutes(geojson) {
  if (state.layers.routes) map.removeLayer(state.layers.routes);
  state.layers.routes = L.geoJSON(geojson, {
    style: (f) => ({ color: f.properties.color || '#888', weight: 3, opacity: .9, lineCap: 'round', lineJoin: 'round' }),
    onEachFeature: (f, layer) => {
      const p = f.properties;
      layer.bindTooltip(`<b>${p.servicio}</b> → ${p.destino || '—'} · ${fmt1(p.km)} km`, { sticky: true, className: 'stop-tip' });
      layer.on('click', () => selectService(p.servicio));
    },
  }).addTo(map);
  if (!state.show.routes) map.removeLayer(state.layers.routes);
}
function drawStops(geojson) {
  if (state.layers.stops) map.removeLayer(state.layers.stops);
  state.layers.stops = L.geoJSON(geojson, {
    pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 4, weight: 1.4, color: '#0E1420', fillColor: '#F5B324', fillOpacity: 1 }),
    onEachFeature: (f, layer) => {
      const p = f.properties;
      layer.bindTooltip(p.stop_name || p.stop_id, { className: 'stop-tip', direction: 'top' });
      layer.on('click', () => showTotem(p));
    },
  }).addTo(map);
  if (!state.show.stops) map.removeLayer(state.layers.stops);
}
function fitTo(bbox) {
  if (!bbox || bbox.length !== 4) return;
  const [w, s, e, n] = bbox;
  map.fitBounds([[s, w], [n, e]], { padding: [30, 30], maxZoom: 15 });
}

/* ---------------- highlight servicio ---------------- */
function selectService(ss) {
  if (!ss) return;
  state.sel = ss;
  $('#tg-reset').hidden = false;
  $$('#legend li').forEach((li) => li.classList.toggle('is-sel', li.dataset.serv === ss));

  const bounds = [];
  if (state.layers.routes) state.layers.routes.eachLayer((l) => {
    const on = l.feature.properties.servicio === ss;
    l.setStyle(on
      ? { opacity: 1, weight: 6, color: l.feature.properties.color || '#F5B324' }
      : { opacity: .1, weight: 2, color: '#5C6B80' });
    if (on) { l.bringToFront(); bounds.push(l.getBounds()); }
  });
  if (state.layers.stops) state.layers.stops.eachLayer((l) => {
    const on = (l.feature.properties.servicios || []).some((x) => x.servicio === ss);
    l.setStyle(on ? { radius: 5, fillColor: '#FFD36B', fillOpacity: 1, opacity: 1 }
                   : { radius: 2.5, fillColor: '#3a4759', fillOpacity: .5, opacity: .4 });
    if (on) l.bringToFront();
  });
  if (bounds.length) {
    let b = bounds[0]; bounds.slice(1).forEach((x) => { b = b.extend(x); });
    map.fitBounds(b, { padding: [40, 40], maxZoom: 15 });
  }
  openService(ss);
  renderCenso(ss);
}

function clearHighlight() {
  state.sel = null;
  $('#tg-reset').hidden = true;
  $$('#legend li').forEach((li) => li.classList.remove('is-sel'));
  if (state.layers.routes) state.layers.routes.eachLayer((l) =>
    l.setStyle({ opacity: .9, weight: 3, color: l.feature.properties.color || '#888' }));
  if (state.layers.stops) state.layers.stops.eachLayer((l) =>
    l.setStyle({ radius: 4, fillColor: '#F5B324', fillOpacity: 1, opacity: 1 }));
}

/* ---------------- tótem parada ---------------- */
function showTotem(p) {
  $('#totem-id').textContent = p.stop_id;
  $('#totem-name').textContent = p.stop_name || '';
  const servs = p.servicios || [];
  $('#totem-sub').textContent = servs.length ? `${servs.length} servicio${servs.length > 1 ? 's' : ''} · toca para ver` : 'Sin servicios asociados';
  $('#totem-list').innerHTML = servs.map((s) => `
    <li class="totem-row" data-serv="${s.servicio}">
      <span class="serv-patch" style="background:${s.color};color:${readableText(s.color)}">${s.servicio}</span>
      <span class="serv-dest"><span class="arrow">→</span><span class="dname">${s.destino || '—'}</span></span></li>`).join('');
  $$('#totem-list .totem-row').forEach((li) => li.addEventListener('click', () => selectService(li.dataset.serv)));
  $('#totem').hidden = false;
}
function hideTotem() { $('#totem').hidden = true; }
$('#totem-close').addEventListener('click', hideTotem);

/* ---------------- ficha de servicio ---------------- */
function openService(ss) {
  const d = (state.services || {})[ss];
  const legend = (state.summary?.legend || []).find((l) => l.servicio === ss);
  const color = d?.color || legend?.color || '#F5B324';
  const nombre = d?.nombre || legend?.nombre || '';

  $('#sv-patch').style.background = color;
  $('#sv-patch').style.color = readableText(color);
  $('#sv-patch').textContent = ss;
  $('#sv-name').textContent = nombre || `Servicio ${ss}`;
  $('#sv-sub').textContent = `Servicio ${ss}`;

  if (d) {
    const exp = d.expediciones?.[state.day] ?? 0;
    const veh = d.veh_km_dia?.[state.day] ?? 0;
    const cards = [
      { l: 'Km de trazado', v: fmt1(d.km_trazado), u: 'km', f: 'ida + regreso' },
      { l: 'Km mensuales', v: fmt(d.km_mensual), u: 'km', f: 'mes en curso' },
      { l: 'Expediciones', v: fmt(exp), u: '', f: `${DAY_LABEL[state.day]} / día` },
      { l: 'Veh-km / día', v: fmt1(veh), u: 'km', f: `${DAY_LABEL[state.day]}` },
      { l: 'Tiempo de viaje', v: d.t_viaje_min != null ? fmt1(d.t_viaje_min) : '—', u: d.t_viaje_min != null ? 'min' : '', f: 'programado, prom.' },
      { l: 'Frecuencia punta', v: peakHeadway(d), u: '', f: 'headway mín.' },
    ];
    $('#sv-metrics').innerHTML = cards.map((c) => `
      <div class="dock-metric"><div class="dm-label">${c.l}</div>
        <div class="dm-value">${c.v}${c.u ? `<small>${c.u}</small>` : ''}</div>
        <div class="dm-foot">${c.f}</div></div>`).join('');
    renderSvChart(d);
  } else {
    $('#sv-metrics').innerHTML = '<div class="dock-metric"><div class="dm-foot">Sin ficha para este servicio.</div></div>';
  }
  $('#service-dock').hidden = false;
}
function peakHeadway(d) {
  const arr = d.freq?.[state.day] || [];
  const max = Math.max(0, ...arr);
  return headwayLabel(max);
}
function closeService() {
  $('#service-dock').hidden = true;
  clearHighlight();
  renderCenso('zona');
}
$('#sv-close').addEventListener('click', closeService);
$('#tg-reset').addEventListener('click', closeService);

/* ---------------- charts ---------------- */
const AXIS = { color: '#5C6B80', font: { family: "'IBM Plex Mono'", size: 9 } };
function renderChart() {
  if (!state.freq) return;
  const data = state.freq[state.day] || [];
  const labels = [...Array(24).keys()].map((h) => String(h).padStart(2, '0'));
  if (state.chart) { state.chart.data.datasets[0].data = data; state.chart.update(); return; }
  state.chart = new Chart($('#freq-chart'), {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: '#F5B324', hoverBackgroundColor: '#FFD36B', borderRadius: 2, barPercentage: .95, categoryPercentage: .9 }] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: {
        backgroundColor: '#1B2637', borderColor: '#273246', borderWidth: 1, titleColor: '#E8EDF4', bodyColor: '#F5B324',
        callbacks: { title: (i) => `${i[0].label}:00–${i[0].label}:59 h`, label: (i) => ` ${fmt1(i.parsed.y)} salidas` } } },
      scales: { x: { grid: { display: false }, ticks: { ...AXIS, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
                y: { beginAtZero: true, grid: { color: '#1F2A3B' }, ticks: { ...AXIS, precision: 0 } } },
      animation: { duration: 220 } },
  });
}
function renderSvChart(d) {
  const data = d.freq?.[state.day] || [];
  const labels = [...Array(24).keys()].map((h) => String(h).padStart(2, '0'));
  $('#sv-chart-note').textContent = 'salidas/hora · headway en tooltip';
  if (state.svChart) { state.svChart.data.datasets[0].data = data; state.svChart.data.datasets[0].backgroundColor = d.color || '#F5B324'; state.svChart.update(); return; }
  state.svChart = new Chart($('#sv-chart'), {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: d.color || '#F5B324', borderRadius: 2, barPercentage: .95, categoryPercentage: .9 }] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: {
        backgroundColor: '#1B2637', borderColor: '#273246', borderWidth: 1, titleColor: '#E8EDF4', bodyColor: '#FFD36B',
        callbacks: { title: (i) => `${i[0].label}:00–${i[0].label}:59 h`,
          label: (i) => [` ${fmt1(i.parsed.y)} salidas`, ` headway ${headwayLabel(i.parsed.y)}`] } } },
      scales: { x: { grid: { display: false }, ticks: { ...AXIS, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
                y: { beginAtZero: true, grid: { color: '#1F2A3B' }, ticks: { ...AXIS, precision: 0 } } },
      animation: { duration: 220 } },
  });
}

/* ---------------- censo / población ---------------- */
function renderCenso(scope) {
  const c = state.censo;
  if (!c || !c.zona || !Object.keys(c.zona).length) { $('#censo-panel').hidden = true; return; }
  const d = (scope !== 'zona' && c.servicios && c.servicios[scope]) ? c.servicios[scope] : c.zona;
  const isZona = d === c.zona;
  $('#censo-scope').textContent = (isZona ? 'Zona' : `Servicio ${scope}`) + ` · buffer ${c.buffer_m || 200} m sobre trazado`;

  const modosTotal = MODO_KEYS.reduce((a, k) => a + (d[k] || 0), 0) || 1;
  const pctTP = (100 * (d.n_transp_1 || 0) / modosTotal);
  const pctMuj = d.n_per ? (100 * (d.n_mujeres || 0) / d.n_per) : 0;

  const cards = [
    { l: 'Población servida', v: fmt(d.n_per || 0), u: 'hab', f: `${d.n_manzanas || 0} manzanas` },
    { l: 'Hombres / Mujeres', v: `${fmt(d.n_hombres || 0)} / ${fmt(d.n_mujeres || 0)}`, u: '', f: `${fmt1(pctMuj)}% mujeres` },
    { l: 'Usa T. Público', v: fmt1(pctTP), u: '%', f: 'partición modal declarada' },
    { l: 'Índices', v: d.dim_acc != null ? fmt1(d.dim_acc) : '—', u: 'acc', f: d.dim_soc != null ? `<b>${fmt1(d.dim_soc)}</b> soc · pond. población` : 'sin dato' },
  ];
  $('#censo-cards').innerHTML = cards.map((x) => `
    <div class="censo-card"><div class="cz-label">${x.l}</div>
      <div class="cz-value">${x.v}${x.u ? `<small>${x.u}</small>` : ''}</div>
      <div class="cz-foot">${x.f}</div></div>`).join('');

  renderEdadChart(EDAD_KEYS.map((k) => d[k] || 0));
  renderModalChart(MODO_KEYS.map((k) => d[k] || 0));
  $('#censo-panel').hidden = false;
}

function renderEdadChart(vals) {
  if (state.edadChart) { state.edadChart.data.datasets[0].data = vals; state.edadChart.update(); return; }
  state.edadChart = new Chart($('#edad-chart'), {
    type: 'bar',
    data: { labels: EDAD_LABELS, datasets: [{ data: vals, backgroundColor: '#4F86C6', hoverBackgroundColor: '#6BA0DC', borderRadius: 3 }] },
    options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { backgroundColor: '#1B2637', borderColor: '#273246', borderWidth: 1, titleColor: '#E8EDF4', bodyColor: '#9BC0EC', callbacks: { label: (i) => ` ${fmt(i.parsed.x)} hab` } } },
      scales: { x: { beginAtZero: true, grid: { color: '#1F2A3B' }, ticks: { ...AXIS } }, y: { grid: { display: false }, ticks: { ...AXIS } } },
      animation: { duration: 220 } },
  });
}
function renderModalChart(vals) {
  if (state.modalChart) { state.modalChart.data.datasets[0].data = vals; state.modalChart.update(); return; }
  state.modalChart = new Chart($('#modal-chart'), {
    type: 'doughnut',
    data: { labels: MODO_LABELS, datasets: [{ data: vals, backgroundColor: MODO_COLORS, borderColor: '#151E2C', borderWidth: 2 }] },
    options: { responsive: true, maintainAspectRatio: false, cutout: '58%',
      plugins: { legend: { position: 'right', labels: { color: '#8A99AD', font: { family: "'IBM Plex Sans'", size: 10 }, boxWidth: 10, padding: 6 } },
        tooltip: { backgroundColor: '#1B2637', borderColor: '#273246', borderWidth: 1, titleColor: '#E8EDF4', bodyColor: '#E8EDF4',
          callbacks: { label: (i) => { const t = i.dataset.data.reduce((a, b) => a + b, 0) || 1; return ` ${i.label}: ${fmt(i.parsed)} (${fmt1(100 * i.parsed / t)}%)`; } } } },
      animation: { duration: 220 } },
  });
}

/* ---------------- controles ---------------- */
$('#daychips').addEventListener('click', (e) => {
  const btn = e.target.closest('.daychip'); if (!btn) return;
  state.day = btn.dataset.day;
  $$('.daychip').forEach((b) => b.classList.toggle('is-on', b === btn));
  renderMetrics(); renderChart();
  if (state.sel) openService(state.sel);
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
