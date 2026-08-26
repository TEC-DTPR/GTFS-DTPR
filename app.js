'use strict';

const DATA = './data';
const DAY_LABEL = { laboral: 'Laboral', sabado: 'Sábado', domingo: 'Domingo' };

/* URLs oficiales de descarga GTFS por slug (TransApp / DTPR) */
const GTFS_URL = {
  arica: 'https://gtfs.repository.transapp.cl/dtpr/arica/prod/gtfs/latest/cl-arica.zip',
  iquique: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-iquique/gtfs/latest/cl-iquique.zip',
  tocopilla: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-tocopilla/gtfs/latest/cl-tocopilla.zip',
  calama: 'https://gtfs.repository.transapp.cl/dtpr/prod/calama/gtfs/latest/calama.zip',
  antofagasta: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-antofagasta/gtfs/latest/cl-antofagasta.zip',
  copiapo: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-copiapo/gtfs/latest/cl-copiapo.zip',
  serena: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-serena/gtfs/latest/cl-serena.zip',
  valparaiso: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-valparaiso/gtfs/latest/cl-valparaiso.zip',
  'rm-sur': 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-rm-sur/gtfs/latest/cl-rm-sur.zip',
  rancagua: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-rancagua/gtfs/latest/cl-rancagua.zip',
  talca: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-talca/gtfs/latest/cl-talca.zip',
  chillan: 'https://gtfs.repository.transapp.cl/dtpr/chillan/prod/gtfs/latest/cl-chillan.zip',
  concepcion: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-concepcion/gtfs/latest/cl-concepcion.zip',
  villarrica: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-villarrica/gtfs/latest/cl-villarrica.zip',
  temuco: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-temuco/gtfs/latest/cl-temuco.zip',
  valdivia: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-valdivia/gtfs/latest/cl-valdivia.zip',
  osorno: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-osorno/gtfs/latest/cl-osorno.zip',
  ptomontt: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-ptomontt/gtfs/latest/cl-ptomontt.zip',
  castro: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-castro/gtfs/latest/cl-castro.zip',
  quellon: 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-quellon/gtfs/latest/cl-quellon.zip',
  'punta-arenas': 'https://gtfs.repository.transapp.cl/dtpr/prod/cl-punta-arenas/gtfs/latest/cl-punta-arenas.zip',
};

const state = {
  zones: [], current: null, day: 'laboral',
  freq: null, services: null, summary: null, censo: null,
  layers: { routes: null, stops: null, manz: null },
  show: { routes: true, stops: true, manz: false },
  manzData: null, choro: null,      // geojson de manzanas + atributo activo
  sel: null, dir: 'todo',
  chart: null, svChart: null, edadChart: null, modalChart: null,
};

const EDAD_LABELS = ['0-5', '6-13', '14-17', '18-24', '25-44', '45-59', '60+'];
const EDAD_KEYS = ['n_edad_0_5', 'n_edad_6_1', 'n_edad_14_', 'n_edad_18_', 'n_edad_25_', 'n_edad_45_', 'n_edad_60_'];
const MODO_LABELS = ['Auto', 'T. Público', 'Caminata', 'Bicicleta', 'Moto', 'Acuático', 'Otros'];
const MODO_KEYS = ['n_transpor', 'n_transp_1', 'n_transp_2', 'n_transp_3', 'n_transp_4', 'n_transp_5', 'n_transp_6'];
/* paleta Red: rojo principal + naranjo + grises */
const MODO_COLORS = ['#888B8D', '#C8102E', '#FF9E1B', '#4FD1C5', '#6B7280', '#3FA7D6', '#B0B4B8'];

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
/* escala secuencial amarillo→naranjo→rojo (mapa claro, alta saturación) */
function choroColor(t) {
  t = Math.max(0, Math.min(1, t));
  const stops = [[255, 245, 176], [255, 158, 27], [200, 16, 46]]; // #FFF5B0, naranjo, rojo
  const seg = t < 0.5 ? 0 : 1;
  const lt = t < 0.5 ? t / 0.5 : (t - 0.5) / 0.5;
  const a = stops[seg], b = stops[seg + 1];
  const c = a.map((v, i) => Math.round(v + (b[i] - v) * lt));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

const map = L.map('map', { preferCanvas: true, zoomControl: true }).setView([-33.45, -70.66], 11);
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; OpenStreetMap &copy; CARTO · GTFS DTPR · STP Regional', subdomains: 'abcd', maxZoom: 20,
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
  $('#loader').classList.add('hide');
  // inicio general: vista de Chile, sin ciudad seleccionada
  map.setView([-38.5, -71.5], 5);
}

function renderZoneList(zones) {
  const list = $('#zone-list'); list.innerHTML = '';
  // cabecera de tabla
  const head = document.createElement('div');
  head.className = 'zt-head';
  head.innerHTML = `<span>Zona</span><span>Pob.</span><span>%TP</span>`;
  list.appendChild(head);
  zones.forEach((z) => {
    const b = document.createElement('button');
    b.className = 'zone-item' + (z.error ? ' is-error' : '');
    b.dataset.slug = z.slug;
    const c = z.censo;
    const pob = c ? fmtK(c.n_per) : '—';
    const tp = c ? `${c.pct_tp}%` : '—';
    b.innerHTML = `<span class="zi-name">${z.name}</span><span class="zi-pob">${pob}</span><span class="zi-tp">${tp}</span>`;
    if (!z.error) b.addEventListener('click', () => selectZone(z.slug));
    list.appendChild(b);
  });
}
function fmtK(n) { return n >= 1000 ? `${fmt1(n / 1000)}k` : fmt(n); }
$('#zone-search').addEventListener('input', (e) => {
  const q = e.target.value.trim().toLowerCase();
  $$('.zone-item').forEach((el) => { el.style.display = el.querySelector('.zi-name').textContent.toLowerCase().includes(q) ? '' : 'none'; });
});

/* ---------------- zona ---------------- */
async function selectZone(slug) {
  if (state.current === slug) return;
  state.current = slug;
  $$('.zone-item').forEach((el) => el.classList.toggle('is-active', el.dataset.slug === slug));
  hideTotem(); closeService(); clearChoro();

  // reset capa manzanas de la zona anterior
  if (state.layers.manz) { map.removeLayer(state.layers.manz); state.layers.manz = null; }
  state.manzData = null; state.show.manz = false;
  $('#tg-manz').classList.remove('is-on'); $('#tg-manz').hidden = true;

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

  // botón descarga GTFS
  const dl = $('#dl-gtfs');
  if (GTFS_URL[slug]) { dl.href = GTFS_URL[slug]; dl.hidden = false; } else dl.hidden = true;

  renderMetrics(); renderLegend(summary.legend);
  drawRoutes(routes); drawStops(stops); fitTo(summary.bbox);
  $('#freq-title').textContent = 'Frecuencia de la red';
  renderChart(state.freq);
  renderCenso('zona');

  // capa de manzanas disponible?
  fetch(`${DATA}/${slug}/manzanas.geojson`, { method: 'HEAD' })
    .then((r) => { if (r.ok) $('#tg-manz').hidden = false; })
    .catch(() => {});
}

function renderMetrics() {
  const s = state.summary;
  const veh = s.veh_km[state.day] ?? s.veh_km.laboral ?? 0;
  const exp = s.expediciones_tipo?.[state.day] ?? s.n_expediciones;
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
      layer.on('mouseover', () => { if (state.sel !== p.servicio) layer.setStyle({ weight: 5, opacity: 1 }); });
      layer.on('mouseout', () => { if (state.sel !== p.servicio) layer.setStyle({ weight: state.sel ? 2 : 3, opacity: state.sel ? .1 : .9 }); });
    },
  }).addTo(map);
  if (!state.show.routes) map.removeLayer(state.layers.routes);
}
function drawStops(geojson) {
  if (state.layers.stops) map.removeLayer(state.layers.stops);
  state.layers.stops = L.geoJSON(geojson, {
    pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 4, weight: 1.4, color: '#fff', fillColor: '#C8102E', fillOpacity: 1 }),
    onEachFeature: (f, layer) => {
      const p = f.properties;
      layer.bindTooltip(p.stop_name || p.stop_id, { className: 'stop-tip', direction: 'top' });
      layer.on('click', () => showTotem(p));
      layer.on('mouseover', () => layer.setStyle({ radius: 6, fillColor: '#FF9E1B' }));
      layer.on('mouseout', () => {
        const on = state.sel && (f.properties.servicios || []).some((x) => x.servicio === state.sel);
        layer.setStyle(on ? { radius: 5, fillColor: '#FF9E1B' } : { radius: state.sel ? 2.5 : 4, fillColor: state.sel ? '#3a4250' : '#C8102E' });
      });
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
  state.dir = 'todo';
  $('#tg-reset').hidden = false;
  $$('#legend li').forEach((li) => li.classList.toggle('is-sel', li.dataset.serv === ss));

  const bounds = [];
  if (state.layers.routes) state.layers.routes.eachLayer((l) => {
    const on = l.feature.properties.servicio === ss;
    l.setStyle(on ? { opacity: 1, weight: 6, color: l.feature.properties.color || '#C8102E' } : { opacity: .1, weight: 2, color: '#626C78' });
    if (on) { l.bringToFront(); bounds.push(l.getBounds()); }
  });
  if (state.layers.stops) state.layers.stops.eachLayer((l) => {
    const on = (l.feature.properties.servicios || []).some((x) => x.servicio === ss);
    l.setStyle(on ? { radius: 5, fillColor: '#FF9E1B', fillOpacity: 1, opacity: 1 } : { radius: 2.5, fillColor: '#B8C2CF', fillOpacity: .6, opacity: .5 });
    if (on) l.bringToFront();
  });
  if (bounds.length) {
    let b = bounds[0]; bounds.slice(1).forEach((x) => { b = b.extend(x); });
    map.fitBounds(b, { padding: [40, 40], maxZoom: 15 });
  }
  openService(ss);
  renderCenso(ss);
  const sd = (state.services || {})[ss];
  const bb = sd ? (sd[state.dir] || sd.todo) : null;
  $('#freq-title').textContent = `Frecuencia · ${ss}` + (state.dir !== 'todo' ? ` (${state.dir === 'ida' ? 'ida' : 'reg'})` : '');
  renderChart(bb?.freq || state.freq, true);
}

function clearHighlight() {
  state.sel = null; state.dir = 'todo';
  $('#tg-reset').hidden = true;
  $$('#legend li').forEach((li) => li.classList.remove('is-sel'));
  if (state.layers.routes) state.layers.routes.eachLayer((l) => l.setStyle({ opacity: .9, weight: 3, color: l.feature.properties.color || '#888' }));
  if (state.layers.stops) state.layers.stops.eachLayer((l) => l.setStyle({ radius: 4, fillColor: '#C8102E', fillOpacity: 1, opacity: 1 }));
}

/* muestra solo trazados/paradas del sentido elegido (dir=1 => regreso, resto ida) */
function isReg(v) { const d = String(v).trim(); return d === '1' || d === '1.0'; }
function applyDirFilter(ss) {
  const dir = state.dir;
  if (state.layers.routes) state.layers.routes.eachLayer((l) => {
    const p = l.feature.properties;
    const on = p.servicio === ss;
    let show = on;
    if (on && dir !== 'todo') show = dir === 'reg' ? isReg(p.direction_id) : !isReg(p.direction_id);
    l.setStyle(show ? { opacity: 1, weight: 6, color: p.color || '#C8102E' } : (on ? { opacity: .05, weight: 1, color: '#626C78' } : { opacity: .1, weight: 2, color: '#626C78' }));
    if (show) l.bringToFront();
  });
  // paradas: en dir!=todo solo las del sentido; el geojson de paradas no trae dirección,
  // así que en ida/reg atenuamos todas salvo las del servicio (se mantienen resaltadas)
  if (state.layers.stops) state.layers.stops.eachLayer((l) => {
    const on = (l.feature.properties.servicios || []).some((x) => x.servicio === ss);
    l.setStyle(on ? { radius: 5, fillColor: '#FF9E1B', fillOpacity: 1, opacity: 1 } : { radius: 2.5, fillColor: '#B8C2CF', fillOpacity: .6, opacity: .5 });
  });
}

/* ---------------- tótem ---------------- */
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
  const color = d?.color || legend?.color || '#C8102E';
  const nombre = d?.nombre || legend?.nombre || '';

  $('#sv-patch').style.background = color;
  $('#sv-patch').style.color = readableText(color);
  $('#sv-patch').textContent = ss;
  $('#sv-name').textContent = nombre || `Servicio ${ss}`;
  $('#sv-sub').textContent = `Servicio ${ss} · ${DAY_LABEL[state.day]}`;

  if (d && d.todo) {
    const b = d[state.dir] || d.todo;
    const exp = b.expediciones?.[state.day] ?? 0;
    const veh = b.veh_km_dia?.[state.day] ?? 0;
    const dirLabel = { todo: 'ida + regreso', ida: 'solo ida', reg: 'solo regreso' }[state.dir];
    const cards = [
      { l: 'Km de trazado', v: fmt1(b.km_trazado), u: 'km', f: state.dir === 'todo' ? `ida ${fmt1(d.km_ida ?? 0)} · reg ${fmt1(d.km_regreso ?? 0)}` : dirLabel },
      { l: 'Km mensuales', v: fmt(b.km_mensual), u: 'km', f: 'mes en curso' },
      { l: 'Expediciones', v: fmt(exp), u: '', f: `${DAY_LABEL[state.day]} / día` },
      { l: 'Veh-km / día', v: fmt1(veh), u: 'km', f: `${DAY_LABEL[state.day]}` },
      { l: 'Tiempo de viaje', v: b.t_viaje_min != null ? fmt1(b.t_viaje_min) : '—', u: b.t_viaje_min != null ? 'min' : '', f: 'programado, prom.' },
      { l: 'Frecuencia punta', v: peakHeadway(b), u: '', f: 'headway mín.' },
    ];
    $('#sv-metrics').innerHTML = svSwitch(state.dir) + cards.map((c) => `
      <div class="dock-metric"><div class="dm-label">${c.l}</div>
        <div class="dm-value">${c.v}${c.u ? `<small>${c.u}</small>` : ''}</div>
        <div class="dm-foot">${c.f}</div></div>`).join('');
    $$('#sv-metrics .dir-btn').forEach((btn) => btn.addEventListener('click', () => {
      state.dir = btn.dataset.dir;
      openService(ss);
      const bb = state.services[ss][state.dir] || state.services[ss].todo;
      $('#freq-title').textContent = `Frecuencia · ${ss}` + (state.dir !== 'todo' ? ` (${state.dir === 'ida' ? 'ida' : 'reg'})` : '');
      renderChart(bb.freq, true);
      applyDirFilter(ss);   // filtra el mapa por sentido
    }));
    renderSvChart(b, color);
  } else {
    $('#sv-metrics').innerHTML = '<div class="dock-metric"><div class="dm-foot">Sin ficha para este servicio.</div></div>';
  }
  $('#service-dock').hidden = false;
}
function svSwitch(active) {
  const opts = [['todo', 'Ida + Reg'], ['ida', 'Ida'], ['reg', 'Regreso']];
  return `<div class="dir-switch">${opts.map(([k, l]) =>
    `<button class="dir-btn${k === active ? ' is-on' : ''}" data-dir="${k}">${l}</button>`).join('')}</div>`;
}
function peakHeadway(b) {
  const arr = b.freq?.[state.day] || [];
  return headwayLabel(Math.max(0, ...arr));
}
function closeService() {
  $('#service-dock').hidden = true;
  clearHighlight();
  renderCenso('zona');
  $('#freq-title').textContent = 'Frecuencia de la red';
  renderChart(state.freq);
}
$('#sv-close').addEventListener('click', closeService);
$('#tg-reset').addEventListener('click', closeService);

/* ---------------- censo / población ---------------- */
function renderCenso(scope) {
  const c = state.censo;
  if (!c || !c.zona || !Object.keys(c.zona).length) { $('#censo-panel').hidden = true; return; }
  const d = (scope !== 'zona' && c.servicios && c.servicios[scope]) ? c.servicios[scope] : c.zona;
  const isZona = d === c.zona;
  $('#censo-scope').textContent = (isZona ? 'Zona' : `Servicio ${scope}`) + ` · cobertura ${c.buffer_m || 200} m`;

  const modosTotal = MODO_KEYS.reduce((a, k) => a + (d[k] || 0), 0) || 1;
  const pctTP = 100 * (d.n_transp_1 || 0) / modosTotal;
  const pctAuto = 100 * (d.n_transpor || 0) / modosTotal;
  const pctMuj = d.n_per ? 100 * (d.n_mujeres || 0) / d.n_per : 0;
  const cards = [
    { l: 'Población cubierta', v: fmt(d.n_per || 0), u: 'hab', f: `${d.n_manzanas || 0} manzanas` },
    { l: 'Hombres / Mujeres', v: `${fmt(d.n_hombres || 0)} / ${fmt(d.n_mujeres || 0)}`, u: '', f: `${fmt1(pctMuj)}% mujeres` },
    { l: 'Usa T. Público', v: fmt1(pctTP), u: '%', f: 'partición modal declarada' },
    { l: 'Usa Automóvil', v: fmt1(pctAuto), u: '%', f: 'partición modal declarada' },
    { l: 'Índices', v: d.dim_acc != null ? fmt1(d.dim_acc) : '—', u: 'acc', f: d.dim_soc != null ? `<b>${fmt1(d.dim_soc)}</b> soc · pond. pob.` : 'sin dato' },
  ];
  $('#censo-cards').innerHTML = cards.map((x) => `
    <div class="censo-card"><div class="cz-label">${x.l}</div>
      <div class="cz-value">${x.v}${x.u ? `<small>${x.u}</small>` : ''}</div>
      <div class="cz-foot">${x.f}</div></div>`).join('');
  renderEdadChart(EDAD_KEYS.map((k) => d[k] || 0));
  renderModalChart(MODO_KEYS.map((k) => d[k] || 0));
  $('#censo-panel').hidden = false;
}

const AXIS = { color: '#626C78', font: { family: "'TS Info'", size: 9 } };
const TT = { backgroundColor: '#1E242D', borderColor: '#2A313C', borderWidth: 1, titleColor: '#EDF0F3' };

function renderEdadChart(vals) {
  if (state.edadChart) { state.edadChart.data.datasets[0].data = vals; state.edadChart.update(); return; }
  state.edadChart = new Chart($('#edad-chart'), {
    type: 'bar',
    data: { labels: EDAD_LABELS, datasets: [{ data: vals, backgroundColor: '#C8102E', hoverBackgroundColor: '#FF9E1B', borderRadius: 3 }] },
    options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      onClick: (e, els) => { if (els.length) mapChoro('edad', EDAD_KEYS[els[0].index], EDAD_LABELS[els[0].index]); },
      plugins: { legend: { display: false }, tooltip: { ...TT, bodyColor: '#FF9E1B', callbacks: { label: (i) => ` ${fmt(i.parsed.x)} hab` } } },
      scales: { x: { beginAtZero: true, grid: { color: '#20262F' }, ticks: AXIS }, y: { grid: { display: false }, ticks: AXIS } },
      animation: { duration: 220 } },
  });
}
function renderModalChart(vals) {
  if (state.modalChart) { state.modalChart.data.datasets[0].data = vals; state.modalChart.update(); return; }
  state.modalChart = new Chart($('#modal-chart'), {
    type: 'doughnut',
    data: { labels: MODO_LABELS, datasets: [{ data: vals, backgroundColor: MODO_COLORS, borderColor: '#161A21', borderWidth: 2 }] },
    options: { responsive: true, maintainAspectRatio: false, cutout: '58%',
      onClick: (e, els) => { if (els.length) mapChoro('modo', MODO_KEYS[els[0].index], MODO_LABELS[els[0].index]); },
      plugins: { legend: { position: 'right', labels: { color: '#97A0AB', font: { family: "'TS Info'", size: 10 }, boxWidth: 10, padding: 6 } },
        tooltip: { ...TT, bodyColor: '#EDF0F3', callbacks: { label: (i) => { const t = i.dataset.data.reduce((a, b) => a + b, 0) || 1; return ` ${i.label}: ${fmt(i.parsed)} (${fmt1(100 * i.parsed / t)}%)`; } } } },
      animation: { duration: 220 } },
  });
}

/* ---------------- charts frecuencia ---------------- */
function renderChart(freqObj, isService) {
  if (!freqObj) return;
  const data = freqObj[state.day] || [];
  const labels = [...Array(24).keys()].map((h) => String(h).padStart(2, '0'));
  const color = isService ? '#FF9E1B' : '#C8102E';
  if (state.chart) {
    state.chart.data.datasets[0].data = data;
    state.chart.data.datasets[0].backgroundColor = color;
    state.chart.update(); return;
  }
  state.chart = new Chart($('#freq-chart'), {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: color, hoverBackgroundColor: '#FF5A6E', borderRadius: 2, barPercentage: .95, categoryPercentage: .9 }] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { ...TT, bodyColor: '#FF9E1B',
        callbacks: { title: (i) => `${i[0].label}:00–${i[0].label}:59 h`, label: (i) => [` ${fmt1(i.parsed.y)} salidas`, ` headway ${headwayLabel(i.parsed.y)}`] } } },
      scales: { x: { grid: { display: false }, ticks: { ...AXIS, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
                y: { beginAtZero: true, grid: { color: '#20262F' }, ticks: { ...AXIS, precision: 0 } } },
      animation: { duration: 220 } },
  });
}
function renderSvChart(b, color) {
  const data = b.freq?.[state.day] || [];
  const col = color || b.color || '#C8102E';
  const labels = [...Array(24).keys()].map((h) => String(h).padStart(2, '0'));
  $('#sv-chart-note').textContent = `${DAY_LABEL[state.day]} · headway en tooltip`;
  if (state.svChart) { state.svChart.data.datasets[0].data = data; state.svChart.data.datasets[0].backgroundColor = col; state.svChart.update(); return; }
  state.svChart = new Chart($('#sv-chart'), {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: col, borderRadius: 2, barPercentage: .95, categoryPercentage: .9 }] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { ...TT, bodyColor: '#FF9E1B',
        callbacks: { title: (i) => `${i[0].label}:00–${i[0].label}:59 h`, label: (i) => [` ${fmt1(i.parsed.y)} salidas`, ` headway ${headwayLabel(i.parsed.y)}`] } } },
      scales: { x: { grid: { display: false }, ticks: { ...AXIS, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
                y: { beginAtZero: true, grid: { color: '#20262F' }, ticks: { ...AXIS, precision: 0 } } },
      animation: { duration: 220 } },
  });
}

/* ---------------- capa manzanas (coroplético) ---------------- */
async function ensureManzanas() {
  if (state.manzData) return state.manzData;
  try {
    const gj = await getJSON(`${DATA}/${state.current}/manzanas.geojson`);
    state.manzData = gj;
    return gj;
  } catch (e) { console.error('sin manzanas', e); return null; }
}
async function toggleManzanas() {
  state.show.manz = !state.show.manz;
  $('#tg-manz').classList.toggle('is-on', state.show.manz);
  if (!state.show.manz) {
    if (state.layers.manz) map.removeLayer(state.layers.manz);
    clearChoro(); return;
  }
  const gj = await ensureManzanas();
  if (!gj) { state.show.manz = false; $('#tg-manz').classList.remove('is-on'); return; }
  // por defecto pinta por población total
  mapChoro('pob', 'n_per', 'Población');
}
function clearChoro() {
  if (state.layers.manz) { map.removeLayer(state.layers.manz); state.layers.manz = null; }
  $('#choro-legend').hidden = true;
  state.choro = null;
}
async function mapChoro(kind, field, label) {
  const gj = await ensureManzanas();
  if (!gj) return;
  state.show.manz = true; $('#tg-manz').classList.add('is-on');
  state.choro = { field, label };

  // max para escalar
  let max = 0;
  gj.features.forEach((f) => { const v = +f.properties[field] || 0; if (v > max) max = v; });
  max = max || 1;

  if (state.layers.manz) map.removeLayer(state.layers.manz);
  state.layers.manz = L.geoJSON(gj, {
    renderer: L.canvas(),
    style: (f) => {
      const v = +f.properties[field] || 0;
      return { fillColor: choroColor(v / max), fillOpacity: v > 0 ? .9 : .25, weight: 0.3, color: '#94A0B0', opacity: .4 };
    },
    onEachFeature: (f, layer) => {
      const v = +f.properties[field] || 0;
      layer.bindTooltip(`${label}: <b>${fmt(v)}</b>`, { className: 'stop-tip', sticky: true });
    },
  }).addTo(map);
  state.layers.manz.bringToBack();

  // leyenda
  $('#choro-title').textContent = label;
  $('#choro-sub').textContent = kind === 'modo' ? 'personas (modo declarado) por manzana' : (kind === 'edad' ? 'personas del grupo por manzana' : 'habitantes por manzana');
  $('#choro-max').textContent = fmt(max);
  $('#choro-legend').hidden = false;
}
$('#choro-close').addEventListener('click', () => { state.show.manz = false; $('#tg-manz').classList.remove('is-on'); clearChoro(); });

/* ---------------- controles ---------------- */
$('#daychips').addEventListener('click', (e) => {
  const btn = e.target.closest('.daychip'); if (!btn) return;
  state.day = btn.dataset.day;
  $$('.daychip').forEach((b) => b.classList.toggle('is-on', b === btn));
  renderMetrics();
  if (state.sel) {
    const sd = state.services[state.sel];
    const bb = sd ? (sd[state.dir] || sd.todo) : null;
    renderChart(bb?.freq || state.freq, true);
    openService(state.sel);
    renderCenso(state.sel);
  } else {
    renderChart(state.freq);
    renderCenso('zona');
  }
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
$('#tg-manz').addEventListener('click', toggleManzanas);

boot();
