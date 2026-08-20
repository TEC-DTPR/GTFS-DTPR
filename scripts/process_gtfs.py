#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
process_gtfs.py
---------------
Descarga los GTFS estaticos de la Red Regional (DTPR/MTT), calcula metricas y
genera archivos livianos (JSON + GeoJSON) que consume la web estatica.

Salida (carpeta data/):
    data/index.json              indice de zonas + resumen + timestamp
    data/<slug>/summary.json     metricas detalladas de la zona
    data/<slug>/routes.geojson   trazados (shapes) con color de route
    data/<slug>/stops.geojson    paradas con los servicios que pasan
    data/<slug>/frequency.json   perfil de salidas/hora por tipo de dia

Uso:
    python process_gtfs.py                 # procesa TODAS las zonas (baja los zips)
    python process_gtfs.py --only tocopilla
    python process_gtfs.py --local ruta/al/cl-tocopilla.zip --slug tocopilla --name "Tocopilla"

Requisitos: pandas, numpy, requests, shapely
"""

import argparse
import io
import json
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from shapely.geometry import LineString

# --------------------------------------------------------------------------- #
# Configuracion de zonas (nombre visible, slug de carpeta, URL del zip)
# --------------------------------------------------------------------------- #
ZONES = [
    ("Arica",                 "arica",        "https://gtfs.repository.transapp.cl/dtpr/arica/prod/gtfs/latest/cl-arica.zip"),
    ("Iquique - Alto Hospicio","iquique",     "https://gtfs.repository.transapp.cl/dtpr/prod/cl-iquique/gtfs/latest/cl-iquique.zip"),
    ("Tocopilla",             "tocopilla",    "https://gtfs.repository.transapp.cl/dtpr/prod/cl-tocopilla/gtfs/latest/cl-tocopilla.zip"),
    ("Calama",                "calama",       "https://gtfs.repository.transapp.cl/dtpr/prod/calama/gtfs/latest/calama.zip"),
    ("Antofagasta",           "antofagasta",  "https://gtfs.repository.transapp.cl/dtpr/prod/cl-antofagasta/gtfs/latest/cl-antofagasta.zip"),
    ("Copiapó",               "copiapo",      "https://gtfs.repository.transapp.cl/dtpr/prod/cl-copiapo/gtfs/latest/cl-copiapo.zip"),
    ("Coquimbo - La Serena",  "serena",       "https://gtfs.repository.transapp.cl/dtpr/prod/cl-serena/gtfs/latest/cl-serena.zip"),
    ("Gran Valparaíso",       "valparaiso",   "https://gtfs.repository.transapp.cl/dtpr/prod/cl-valparaiso/gtfs/latest/cl-valparaiso.zip"),
    ("Región Metropolitana",  "rm-sur",       "https://gtfs.repository.transapp.cl/dtpr/prod/cl-rm-sur/gtfs/latest/cl-rm-sur.zip"),
    ("Rancagua - Machalí",    "rancagua",     "https://gtfs.repository.transapp.cl/dtpr/prod/cl-rancagua/gtfs/latest/cl-rancagua.zip"),
    ("Talca",                 "talca",        "https://gtfs.repository.transapp.cl/dtpr/prod/cl-talca/gtfs/latest/cl-talca.zip"),
    ("Chillán",               "chillan",      "https://gtfs.repository.transapp.cl/dtpr/chillan/prod/gtfs/latest/cl-chillan.zip"),
    ("Gran Concepción",       "concepcion",   "https://gtfs.repository.transapp.cl/dtpr/prod/cl-concepcion/gtfs/latest/cl-concepcion.zip"),
    ("Villarrica",            "villarrica",   "https://gtfs.repository.transapp.cl/dtpr/prod/cl-villarrica/gtfs/latest/cl-villarrica.zip"),
    ("Temuco",                "temuco",       "https://gtfs.repository.transapp.cl/dtpr/prod/cl-temuco/gtfs/latest/cl-temuco.zip"),
    ("Valdivia",              "valdivia",     "https://gtfs.repository.transapp.cl/dtpr/prod/cl-valdivia/gtfs/latest/cl-valdivia.zip"),
    ("Osorno",                "osorno",       "https://gtfs.repository.transapp.cl/dtpr/prod/cl-osorno/gtfs/latest/cl-osorno.zip"),
    ("Puerto Montt",          "ptomontt",     "https://gtfs.repository.transapp.cl/dtpr/prod/cl-ptomontt/gtfs/latest/cl-ptomontt.zip"),
    ("Castro",                "castro",       "https://gtfs.repository.transapp.cl/dtpr/prod/cl-castro/gtfs/latest/cl-castro.zip"),
    ("Quellón",               "quellon",      "https://gtfs.repository.transapp.cl/dtpr/prod/cl-quellon/gtfs/latest/cl-quellon.zip"),
    ("Punta Arenas",          "punta-arenas", "https://gtfs.repository.transapp.cl/dtpr/prod/cl-punta-arenas/gtfs/latest/cl-punta-arenas.zip"),
]

DAY_COLS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY  = ["monday", "tuesday", "wednesday", "thursday", "friday"]

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SIMPLIFY_TOL = 0.00004      # ~4 m: simplifica shapes para bajar peso del geojson
COORD_DECIMALS = 5          # ~1 m de precision: suficiente para visualizar


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def log(*a):
    print(*a, flush=True)


def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia geodesica vectorizada en km."""
    R = 6371.0088
    p1 = np.radians(lat1); p2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlmb = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def read_gtfs(zbytes):
    """Lee los .txt necesarios del zip en un dict de DataFrames."""
    out = {}
    want = ["routes", "trips", "stops", "stop_times", "shapes",
            "calendar", "calendar_dates", "agency", "feed_info"]
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        names = {n.lower().split("/")[-1]: n for n in z.namelist()}
        for w in want:
            fn = names.get(w + ".txt")
            if fn is None:
                out[w] = None
                continue
            with z.open(fn) as f:
                out[w] = pd.read_csv(f, dtype=str, keep_default_na=False,
                                     encoding="utf-8-sig", low_memory=False)
    return out


def hhmmss_to_hour(series):
    """Hora entera (0-23) del campo HH:MM:SS de GTFS, soportando >24h."""
    hh = series.str.split(":", n=1, expand=True)[0]
    hh = pd.to_numeric(hh, errors="coerce")
    return (hh % 24).astype("Int64")


# --------------------------------------------------------------------------- #
# Clasificacion de servicios por tipo de dia (desde calendar.txt)
# --------------------------------------------------------------------------- #
def service_days(cal):
    """
    Devuelve dict day -> set(service_id activos ese dia de la semana),
    usando calendar.txt. Si no hay calendar, devuelve None.
    """
    if cal is None or cal.empty:
        return None
    cal = cal.copy()
    for c in DAY_COLS:
        if c not in cal.columns:
            cal[c] = "0"
        cal[c] = pd.to_numeric(cal[c], errors="coerce").fillna(0).astype(int)
    days = {}
    for d in DAY_COLS:
        days[d] = set(cal.loc[cal[d] == 1, "service_id"].astype(str))
    return days


# --------------------------------------------------------------------------- #
# Nucleo: procesa un GTFS ya en memoria
# --------------------------------------------------------------------------- #
def process_feed(name, slug, g):
    routes  = g["routes"]
    trips   = g["trips"]
    stops   = g["stops"]
    st      = g["stop_times"]
    shapes  = g["shapes"]
    cal     = g["calendar"]

    if any(x is None for x in (routes, trips, stops, st)):
        raise ValueError("faltan archivos GTFS obligatorios")

    # --- normalizacion ---
    for df in (stops, st):
        if "stop_id" in df.columns:
            df["stop_id"] = df["stop_id"].astype(str).str.strip()
    for col in ("stop_lat", "stop_lon"):
        stops[col] = pd.to_numeric(stops[col], errors="coerce")
    stops = stops.dropna(subset=["stop_lat", "stop_lon"]).copy()

    trips["shape_id"] = trips.get("shape_id", pd.Series(dtype=str)).astype(str).str.strip()
    trips["route_id"] = trips["route_id"].astype(str).str.strip()
    routes["route_id"] = routes["route_id"].astype(str).str.strip()

    # colores y nombres de route
    routes["route_color"] = routes.get("route_color", "").fillna("").replace("", "888888")
    routes["route_text_color"] = routes.get("route_text_color", "").fillna("").replace("", "ffffff")
    routes["route_short_name"] = routes.get("route_short_name", "").fillna("")
    routes["route_long_name"]  = routes.get("route_long_name", "").fillna("")
    rinfo = routes.set_index("route_id")[
        ["route_short_name", "route_long_name", "route_color", "route_text_color"]
    ].to_dict("index")

    def color_of(rid):
        c = rinfo.get(rid, {}).get("route_color", "888888")
        return "#" + str(c).lstrip("#")

    def short_of(rid):
        s = rinfo.get(rid, {}).get("route_short_name", "")
        return s if s else rid

    # --- largo de cada shape (km) via haversine ---
    shape_km = {}
    shape_pts = {}
    if shapes is not None and not shapes.empty:
        shapes = shapes.copy()
        shapes["shape_id"] = shapes["shape_id"].astype(str).str.strip()
        for c in ("shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"):
            shapes[c] = pd.to_numeric(shapes[c], errors="coerce")
        shapes = shapes.dropna(subset=["shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"])
        shapes = shapes.sort_values(["shape_id", "shape_pt_sequence"])
        for sid, grp in shapes.groupby("shape_id", sort=False):
            lat = grp["shape_pt_lat"].to_numpy()
            lon = grp["shape_pt_lon"].to_numpy()
            if len(lat) >= 2:
                d = haversine_km(lat[:-1], lon[:-1], lat[1:], lon[1:]).sum()
            else:
                d = 0.0
            shape_km[sid] = float(d)
            shape_pts[sid] = np.column_stack([lon, lat])  # (lon,lat) para geojson

    # --- metadatos por shape (route, headsign) desde trips ---
    def _mode(s):
        m = s.mode()
        return m.iloc[0] if len(m) else ""

    trips["trip_headsign"] = trips.get("trip_headsign", "").fillna("")
    trips["direction_id"]  = trips.get("direction_id", "").fillna("")
    shp_meta = {}
    if "shape_id" in trips.columns:
        gsh = trips[trips["shape_id"] != ""].groupby("shape_id")
        for sid, grp in gsh:
            rid = _mode(grp["route_id"])
            shp_meta[sid] = {
                "route_id": rid,
                "route_short_name": short_of(rid),
                "route_long_name": rinfo.get(rid, {}).get("route_long_name", ""),
                "headsign": _mode(grp["trip_headsign"]),
                "direction_id": _mode(grp["direction_id"]),
                "color": color_of(rid),
                "text_color": "#" + str(rinfo.get(rid, {}).get("route_text_color", "ffffff")).lstrip("#"),
            }

    # ------------------------------------------------------------------ #
    # routes.geojson (un LineString por shape)
    # ------------------------------------------------------------------ #
    route_features = []
    for sid, coords in shape_pts.items():
        meta = shp_meta.get(sid, {})
        if len(coords) >= 2:
            line = LineString(coords)
            line = line.simplify(SIMPLIFY_TOL, preserve_topology=False)
            xy = [[round(x, COORD_DECIMALS), round(y, COORD_DECIMALS)] for x, y in line.coords]
        else:
            xy = [[round(float(x), COORD_DECIMALS), round(float(y), COORD_DECIMALS)] for x, y in coords]
        route_features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": xy},
            "properties": {
                "shape_id": sid,
                "route_id": meta.get("route_id", ""),
                "servicio": meta.get("route_short_name", ""),
                "nombre": meta.get("route_long_name", ""),
                "destino": meta.get("headsign", ""),
                "direction_id": meta.get("direction_id", ""),
                "color": meta.get("color", "#888888"),
                "text_color": meta.get("text_color", "#ffffff"),
                "km": round(shape_km.get(sid, 0.0), 2),
            },
        })
    routes_geojson = {"type": "FeatureCollection", "features": route_features}

    # ------------------------------------------------------------------ #
    # stops.geojson (paradas + servicios que pasan con destino)
    # ------------------------------------------------------------------ #
    # cruce stop -> trip -> route/headsign  (pares unicos por parada)
    st_small = st[["trip_id", "stop_id"]].drop_duplicates()
    tr_small = trips[["trip_id", "route_id", "trip_headsign", "direction_id"]].copy()
    link = st_small.merge(tr_small, on="trip_id", how="left")
    link["servicio"] = link["route_id"].map(short_of)
    link["color"] = link["route_id"].map(color_of)
    link = link.drop_duplicates(subset=["stop_id", "servicio", "trip_headsign", "direction_id"])

    serv_by_stop = {}
    for sid, grp in link.groupby("stop_id"):
        items = []
        seen = set()
        for _, r in grp.iterrows():
            key = (r["servicio"], r["trip_headsign"])
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "servicio": r["servicio"],
                "destino": r["trip_headsign"],
                "color": r["color"],
                "direction_id": r["direction_id"],
            })
        items.sort(key=lambda x: (str(x["servicio"]), str(x["destino"])))
        serv_by_stop[sid] = items

    stop_features = []
    for _, s in stops.iterrows():
        sid = s["stop_id"]
        stop_features.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [round(float(s["stop_lon"]), COORD_DECIMALS),
                                         round(float(s["stop_lat"]), COORD_DECIMALS)]},
            "properties": {
                "stop_id": sid,
                "stop_name": s.get("stop_name", ""),
                "servicios": serv_by_stop.get(sid, []),
            },
        })
    stops_geojson = {"type": "FeatureCollection", "features": stop_features}

    # ------------------------------------------------------------------ #
    # Frecuencia: salidas/hora por tipo de dia
    # ------------------------------------------------------------------ #
    # salida = primer stop_time (menor stop_sequence) de cada trip
    st2 = st[["trip_id", "stop_sequence", "departure_time"]].copy()
    st2["stop_sequence"] = pd.to_numeric(st2["stop_sequence"], errors="coerce")
    first = (st2.sort_values(["trip_id", "stop_sequence"])
                .groupby("trip_id", as_index=False).first())
    first["hour"] = hhmmss_to_hour(first["departure_time"])
    trip_hour = first.set_index("trip_id")["hour"].to_dict()

    trips["_hour"]  = trips["trip_id"].map(trip_hour)
    trips["_km"]    = trips["shape_id"].map(shape_km).fillna(0.0)
    trips["service_id"] = trips["service_id"].astype(str)

    sdays = service_days(cal)

    def hourly_for_services(svc_set):
        """vector de 24 posiciones: n de salidas por hora para esos service_id."""
        sub = trips[trips["service_id"].isin(svc_set)]
        vec = [0] * 24
        vc = sub["_hour"].dropna().astype(int).value_counts()
        for h, n in vc.items():
            if 0 <= int(h) <= 23:
                vec[int(h)] = int(n)
        return vec, float(sub["_km"].sum()), int(len(sub))

    freq = {}
    vehkm = {}
    trips_by_type = {}
    if sdays is not None:
        # laboral = promedio lun-vie
        wk_vecs, wk_km, wk_tr = [], [], []
        for d in WEEKDAY:
            v, km, n = hourly_for_services(sdays[d])
            wk_vecs.append(v); wk_km.append(km); wk_tr.append(n)
        lab = [round(sum(vals) / len(vals), 2) for vals in zip(*wk_vecs)] if wk_vecs else [0] * 24
        freq["laboral"] = lab
        vehkm["laboral"] = round(float(np.mean(wk_km)), 1) if wk_km else 0.0
        trips_by_type["laboral"] = int(round(float(np.mean(wk_tr)))) if wk_tr else 0

        for key, day in (("sabado", "saturday"), ("domingo", "sunday")):
            v, km, n = hourly_for_services(sdays[day])
            freq[key] = [float(x) for x in v]
            vehkm[key] = round(km, 1)
            trips_by_type[key] = n
    else:
        # sin calendar: todo junto como "laboral"
        v, km, n = hourly_for_services(set(trips["service_id"]))
        freq = {"laboral": [float(x) for x in v], "sabado": [0]*24, "domingo": [0]*24}
        vehkm = {"laboral": round(km, 1), "sabado": 0.0, "domingo": 0.0}
        trips_by_type = {"laboral": n, "sabado": 0, "domingo": 0}

    # ------------------------------------------------------------------ #
    # Metricas resumen
    # ------------------------------------------------------------------ #
    red_km = round(sum(shape_km.values()), 1)   # largo de trazados unicos
    n_routes = int(routes["route_id"].nunique())
    n_trips  = int(trips["trip_id"].nunique())
    n_stops  = int(stops["stop_id"].nunique())
    n_shapes = int(len(shape_km))

    # bbox para centrar el mapa
    bbox = [float(stops["stop_lon"].min()), float(stops["stop_lat"].min()),
            float(stops["stop_lon"].max()), float(stops["stop_lat"].max())]

    # leyenda de servicios (para el panel lateral del mapa)
    legend = []
    for rid, info in rinfo.items():
        legend.append({
            "servicio": info.get("route_short_name") or rid,
            "nombre": info.get("route_long_name", ""),
            "color": "#" + str(info.get("route_color", "888888")).lstrip("#"),
        })
    legend.sort(key=lambda x: str(x["servicio"]))

    summary = {
        "name": name,
        "slug": slug,
        "n_servicios": n_routes,
        "n_expediciones": n_trips,
        "n_paradas": n_stops,
        "n_trazados": n_shapes,
        "red_km": red_km,
        "veh_km": vehkm,
        "expediciones_tipo": trips_by_type,
        "bbox": bbox,
        "legend": legend,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    return summary, routes_geojson, stops_geojson, {"freq": freq}


# --------------------------------------------------------------------------- #
# IO por zona
# --------------------------------------------------------------------------- #
def fetch_zip(url, retries=3, timeout=120):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.content
        except Exception as e:
            last = e
            log(f"    intento {i+1} fallo: {e}")
            time.sleep(3 * (i + 1))
    raise last


def write_zone(slug, summary, routes_gj, stops_gj, freq):
    d = DATA_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    (d / "routes.geojson").write_text(json.dumps(routes_gj, ensure_ascii=False), encoding="utf-8")
    (d / "stops.geojson").write_text(json.dumps(stops_gj, ensure_ascii=False), encoding="utf-8")
    (d / "frequency.json").write_text(json.dumps(freq, ensure_ascii=False), encoding="utf-8")


def run(zones, local=None, slug=None, name=None):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    index = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "zones": []}

    if local:
        zbytes = Path(local).read_bytes()
        g = read_gtfs(zbytes)
        summary, rgj, sgj, fq = process_feed(name or slug, slug, g)
        write_zone(slug, summary, rgj, sgj, fq)
        index["zones"].append(_index_entry(summary))
        (DATA_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        log(f"OK (local) {slug}: {summary['n_servicios']} serv, {summary['red_km']} km, {summary['n_paradas']} paradas")
        return

    ok, fail = 0, 0
    for nm, sl, url in zones:
        t0 = time.time()
        log(f"[{sl}] descargando…")
        try:
            zbytes = fetch_zip(url)
            g = read_gtfs(zbytes)
            summary, rgj, sgj, fq = process_feed(nm, sl, g)
            write_zone(sl, summary, rgj, sgj, fq)
            index["zones"].append(_index_entry(summary))
            ok += 1
            log(f"[{sl}] OK  {summary['n_servicios']} serv · {summary['red_km']} km · "
                f"{summary['n_paradas']} paradas  ({time.time()-t0:.1f}s)")
        except Exception as e:
            fail += 1
            index["zones"].append({"name": nm, "slug": sl, "error": str(e)})
            log(f"[{sl}] ERROR: {e}")

    index["zones"].sort(key=lambda z: z.get("name", ""))
    (DATA_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    log(f"\nListo. {ok} ok, {fail} con error.")
    if ok == 0:
        sys.exit(1)


def _index_entry(summary):
    return {
        "name": summary["name"],
        "slug": summary["slug"],
        "n_servicios": summary["n_servicios"],
        "n_paradas": summary["n_paradas"],
        "red_km": summary["red_km"],
        "n_expediciones": summary["n_expediciones"],
        "generated_at": summary["generated_at"],
    }


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Procesa GTFS DTPR a data/ (JSON+GeoJSON)")
    ap.add_argument("--only", help="slug unico a procesar (p.ej. tocopilla)")
    ap.add_argument("--local", help="ruta a un zip GTFS local (para pruebas)")
    ap.add_argument("--slug", help="slug para --local")
    ap.add_argument("--name", help="nombre visible para --local")
    args = ap.parse_args()

    if args.local:
        if not args.slug:
            ap.error("--local requiere --slug")
        run([], local=args.local, slug=args.slug, name=args.name)
    else:
        zs = ZONES
        if args.only:
            zs = [z for z in ZONES if z[1] == args.only]
            if not zs:
                ap.error(f"slug '{args.only}' no esta en ZONES")
        run(zs)
