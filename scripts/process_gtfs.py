#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
process_gtfs.py  (Fase 1)
-------------------------
Descarga los GTFS estaticos de la Red Regional (DTPR/MTT), calcula metricas y
genera archivos livianos (JSON + GeoJSON) que consume la web estatica.

Salida por zona (data/<slug>/):
    summary.json     metricas de zona
    routes.geojson   trazados (shapes) con color/servicio/destino
    stops.geojson    paradas + servicios que pasan
    frequency.json   perfil de salidas/hora de la RED por tipo de dia
    services.json    metricas POR SERVICIO: km trazado, km mensual, expediciones,
                     tiempo de viaje programado y frecuencia/headway por hora

Uso:
    python process_gtfs.py
    python process_gtfs.py --only tocopilla
    python process_gtfs.py --local ruta/cl-tocopilla.zip --slug tocopilla --name "Tocopilla"
"""

import argparse
import calendar as calmod
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
SIMPLIFY_TOL = 0.00004
COORD_DECIMALS = 5


def log(*a):
    print(*a, flush=True)


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0088
    p1 = np.radians(lat1); p2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlmb = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def read_gtfs(zbytes):
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


def to_seconds(series):
    """HH:MM:SS -> segundos totales (soporta >24h). NaN si invalido."""
    parts = series.str.split(":", expand=True)
    if parts.shape[1] < 3:
        return pd.Series(np.nan, index=series.index)
    h = pd.to_numeric(parts[0], errors="coerce")
    m = pd.to_numeric(parts[1], errors="coerce")
    s = pd.to_numeric(parts[2], errors="coerce")
    return h * 3600 + m * 60 + s


def hour_from_seconds(sec):
    """hora entera 0-23 desde segundos (mod 24h)."""
    return ((sec // 3600) % 24).astype("Int64")


def service_days(cal):
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


def month_day_counts(ref=None):
    """Cuenta dias del mes en curso por dia de la semana y por tipo.
    Devuelve (por_weekday[0..6], por_tipo{laboral,sabado,domingo})."""
    ref = ref or datetime.now()
    ndays = calmod.monthrange(ref.year, ref.month)[1]
    per_wd = [0] * 7
    for d in range(1, ndays + 1):
        wd = datetime(ref.year, ref.month, d).weekday()  # 0=lun..6=dom
        per_wd[wd] += 1
    por_tipo = {
        "laboral": sum(per_wd[0:5]),
        "sabado": per_wd[5],
        "domingo": per_wd[6],
    }
    return per_wd, por_tipo


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

    routes["route_color"] = routes.get("route_color", "").fillna("").replace("", "888888")
    routes["route_text_color"] = routes.get("route_text_color", "").fillna("").replace("", "ffffff")
    routes["route_short_name"] = routes.get("route_short_name", "").fillna("")
    routes["route_long_name"]  = routes.get("route_long_name", "").fillna("")
    rinfo = routes.set_index("route_id")[
        ["route_short_name", "route_long_name", "route_color", "route_text_color"]
    ].to_dict("index")

    def color_of(rid):
        return "#" + str(rinfo.get(rid, {}).get("route_color", "888888")).lstrip("#")

    def short_of(rid):
        s = rinfo.get(rid, {}).get("route_short_name", "")
        return s if s else rid

    # --- largo de cada shape (km) ---
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
            d = haversine_km(lat[:-1], lon[:-1], lat[1:], lon[1:]).sum() if len(lat) >= 2 else 0.0
            shape_km[sid] = float(d)
            shape_pts[sid] = np.column_stack([lon, lat])

    # --- meta por shape (desde trips) ---
    def _mode(s):
        m = s.mode()
        return m.iloc[0] if len(m) else ""

    trips["trip_headsign"] = trips.get("trip_headsign", "").fillna("")
    trips["direction_id"]  = trips.get("direction_id", "").fillna("")
    shp_meta = {}
    if "shape_id" in trips.columns:
        for sid, grp in trips[trips["shape_id"] != ""].groupby("shape_id"):
            rid = _mode(grp["route_id"])
            shp_meta[sid] = {
                "route_id": rid,
                "servicio": short_of(rid),
                "nombre": rinfo.get(rid, {}).get("route_long_name", ""),
                "headsign": _mode(grp["trip_headsign"]),
                "direction_id": _mode(grp["direction_id"]),
                "color": color_of(rid),
                "text_color": "#" + str(rinfo.get(rid, {}).get("route_text_color", "ffffff")).lstrip("#"),
            }

    # --- routes.geojson ---
    route_features = []
    for sid, coords in shape_pts.items():
        meta = shp_meta.get(sid, {})
        if len(coords) >= 2:
            line = LineString(coords).simplify(SIMPLIFY_TOL, preserve_topology=False)
            xy = [[round(x, COORD_DECIMALS), round(y, COORD_DECIMALS)] for x, y in line.coords]
        else:
            xy = [[round(float(x), COORD_DECIMALS), round(float(y), COORD_DECIMALS)] for x, y in coords]
        route_features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": xy},
            "properties": {
                "shape_id": sid,
                "route_id": meta.get("route_id", ""),
                "servicio": meta.get("servicio", ""),
                "nombre": meta.get("nombre", ""),
                "destino": meta.get("headsign", ""),
                "direction_id": meta.get("direction_id", ""),
                "color": meta.get("color", "#888888"),
                "text_color": meta.get("text_color", "#ffffff"),
                "km": round(shape_km.get(sid, 0.0), 2),
            },
        })
    routes_geojson = {"type": "FeatureCollection", "features": route_features}

    # --- stops.geojson (servicios por parada) ---
    st_small = st[["trip_id", "stop_id"]].drop_duplicates()
    tr_small = trips[["trip_id", "route_id", "trip_headsign", "direction_id"]].copy()
    link = st_small.merge(tr_small, on="trip_id", how="left")
    link["servicio"] = link["route_id"].map(short_of)
    link["color"] = link["route_id"].map(color_of)
    link = link.drop_duplicates(subset=["stop_id", "servicio", "trip_headsign", "direction_id"])

    serv_by_stop = {}
    for sid, grp in link.groupby("stop_id"):
        items, seen = [], set()
        for _, r in grp.iterrows():
            key = (r["servicio"], r["trip_headsign"])
            if key in seen:
                continue
            seen.add(key)
            items.append({"servicio": r["servicio"], "destino": r["trip_headsign"],
                          "color": r["color"], "direction_id": r["direction_id"]})
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
            "properties": {"stop_id": sid, "stop_name": s.get("stop_name", ""),
                           "servicios": serv_by_stop.get(sid, [])},
        })
    stops_geojson = {"type": "FeatureCollection", "features": stop_features}

    # ------------------------------------------------------------------ #
    # Tiempos por trip: primera salida, ultima llegada, hora, duracion
    # ------------------------------------------------------------------ #
    stc = st[["trip_id", "stop_sequence", "departure_time", "arrival_time"]].copy()
    stc["stop_sequence"] = pd.to_numeric(stc["stop_sequence"], errors="coerce")
    stc["dep_sec"] = to_seconds(stc["departure_time"])
    stc["arr_sec"] = to_seconds(stc["arrival_time"])
    stc = stc.sort_values(["trip_id", "stop_sequence"])
    grp = stc.groupby("trip_id", as_index=True)
    first_dep = grp["dep_sec"].first()
    last_arr  = grp["arr_sec"].last()
    dur_min = ((last_arr - first_dep) / 60.0)
    dur_min = dur_min.where((dur_min > 0) & (dur_min < 600))  # descarta basura

    trips = trips.set_index("trip_id")
    trips["_dep_sec"] = first_dep
    trips["_hour"] = hour_from_seconds(first_dep)
    trips["_dur"] = dur_min
    trips["_km"] = trips["shape_id"].map(shape_km).fillna(0.0)
    trips["service_id"] = trips["service_id"].astype(str)
    # sentido normalizado: "reg" si direction_id==1, si no "ida"
    trips["_dir"] = trips["direction_id"].astype(str).str.strip().map(
        lambda d: "reg" if d in ("1", "1.0") else "ida")
    trips = trips.reset_index()

    sdays = service_days(cal)
    per_wd, mdays = month_day_counts()   # días del mes por weekday y por tipo
    WD_KEYS = DAY_COLS  # monday..sunday alineado con per_wd[0..6]

    # ------------------------------------------------------------------ #
    # Perfil de RED por tipo de dia
    # Frecuencia = TOTAL de salidas del mes de ese tipo / N° de días del tipo.
    # Como cada día de semana repite su patrón, esto equivale al promedio de
    # los weekday del tipo ponderado por cuántas veces aparece en el mes.
    # ------------------------------------------------------------------ #
    def red_hourly(svc_set):
        sub = trips[trips["service_id"].isin(svc_set)]
        vec = [0] * 24
        vc = sub["_hour"].dropna().astype(int).value_counts()
        for h, n in vc.items():
            if 0 <= int(h) <= 23:
                vec[int(h)] = int(n)
        return vec, float(sub["_km"].sum()), int(len(sub))

    def promedio_tipo(wd_indices):
        """Promedio ponderado por días del mes sobre los weekday indicados.
        wd_indices: lista de índices 0..6. Devuelve (freq24, veh_km_dia, exp_dia)."""
        acc_vec = [0.0] * 24; acc_km = 0.0; acc_exp = 0.0; ndias = 0
        for wd in wd_indices:
            cnt = per_wd[wd]
            if cnt == 0:
                continue
            v, km, n = red_hourly(sdays[WD_KEYS[wd]]) if sdays else ([0]*24, 0.0, 0)
            for h in range(24):
                acc_vec[h] += v[h] * cnt      # salidas de todos los días de ese wd en el mes
            acc_km += km * cnt
            acc_exp += n * cnt
            ndias += cnt
        if ndias == 0:
            return [0.0]*24, 0.0, 0
        return ([round(acc_vec[h] / ndias, 2) for h in range(24)],
                round(acc_km / ndias, 1), int(round(acc_exp / ndias)))

    freq, vehkm, trips_by_type = {}, {}, {}
    if sdays is not None:
        f, k, e = promedio_tipo([0, 1, 2, 3, 4]); freq["laboral"] = f; vehkm["laboral"] = k; trips_by_type["laboral"] = e
        f, k, e = promedio_tipo([5]);             freq["sabado"]  = f; vehkm["sabado"]  = k; trips_by_type["sabado"]  = e
        f, k, e = promedio_tipo([6]);             freq["domingo"] = f; vehkm["domingo"] = k; trips_by_type["domingo"] = e
    else:
        v, km, n = red_hourly(set(trips["service_id"]))
        freq = {"laboral": [float(x) for x in v], "sabado": [0]*24, "domingo": [0]*24}
        vehkm = {"laboral": round(km, 1), "sabado": 0.0, "domingo": 0.0}
        trips_by_type = {"laboral": n, "sabado": 0, "domingo": 0}

    # ------------------------------------------------------------------ #
    # Metricas POR SERVICIO -> services.json  (misma fórmula por tipo de día)
    # ------------------------------------------------------------------ #
    def route_metrics_for_day(svc_set, dir_filter=None):
        """dict route_id -> (expediciones, veh_km, vector24) para un weekday.
        dir_filter: None=todo, 'ida' o 'reg'."""
        sub = trips[trips["service_id"].isin(svc_set)]
        if dir_filter is not None:
            sub = sub[sub["_dir"] == dir_filter]
        out = {}
        if sub.empty:
            return out
        exp = sub.groupby("route_id").size()
        km  = sub.groupby("route_id")["_km"].sum()
        hh  = (sub.dropna(subset=["_hour"])
                  .assign(_hour=lambda d: d["_hour"].astype(int))
                  .groupby(["route_id", "_hour"]).size())
        for rid in exp.index:
            vec = [0]*24
            if rid in hh.index.get_level_values(0):
                for h, n in hh.loc[rid].items():
                    if 0 <= int(h) <= 23:
                        vec[int(h)] = int(n)
            out[rid] = (int(exp.get(rid, 0)), float(km.get(rid, 0.0)), vec)
        return out

    # métricas por weekday (0..6) y por sentido (todo/ida/reg)
    SENTIDOS = ("todo", "ida", "reg")
    wd_metrics = {sen: [] for sen in SENTIDOS}
    for wd in range(7):
        svc = sdays[WD_KEYS[wd]] if sdays is not None else set(trips["service_id"])
        wd_metrics["todo"].append(route_metrics_for_day(svc, None))
        wd_metrics["ida"].append(route_metrics_for_day(svc, "ida"))
        wd_metrics["reg"].append(route_metrics_for_day(svc, "reg"))
        if sdays is None:
            for sen in SENTIDOS:
                wd_metrics[sen] += [{}] * 6
            break

    def route_promedio(rid, wd_indices, sentido):
        """Promedia ponderado por días del mes para un route/sentido en los weekday dados."""
        met = wd_metrics[sentido]
        acc_vec = [0.0]*24; acc_km = 0.0; acc_exp = 0.0; ndias = 0
        for wd in wd_indices:
            cnt = per_wd[wd]
            if cnt == 0 or wd >= len(met):
                continue
            e, km, vec = met[wd].get(rid, (0, 0.0, [0]*24))
            for h in range(24):
                acc_vec[h] += vec[h] * cnt
            acc_km += km * cnt; acc_exp += e * cnt; ndias += cnt
        if ndias == 0:
            return [0.0]*24, 0.0, 0
        return ([round(acc_vec[h]/ndias, 2) for h in range(24)],
                round(acc_km/ndias, 1), int(round(acc_exp/ndias)))

    # tiempo de viaje promedio por route y por sentido
    dur_all = trips.dropna(subset=["_dur"])
    dur_by_route = dur_all.groupby("route_id")["_dur"].mean().to_dict()
    dur_by_route_dir = {}
    for (rid, sen), v in dur_all.groupby(["route_id", "_dir"])["_dur"].mean().items():
        dur_by_route_dir[(rid, sen)] = float(v)

    shapes_by_route = {}
    for sid, meta in shp_meta.items():
        shapes_by_route.setdefault(meta.get("route_id", ""), []).append(sid)

    def km_por_sentido(rid):
        ida = reg = 0.0
        for sid in shapes_by_route.get(rid, []):
            d = str(shp_meta.get(sid, {}).get("direction_id", "0")).strip()
            km = shape_km.get(sid, 0.0)
            if d in ("1", "1.0"):
                reg += km
            else:
                ida += km
        return round(ida, 2), round(reg, 2)

    def bloque_sentido(rid, sentido, km_trazado_sen, t_min):
        """Arma el bloque de métricas de un route para un sentido."""
        f_lab, k_lab, e_lab = route_promedio(rid, [0, 1, 2, 3, 4], sentido)
        f_sat, k_sat, e_sat = route_promedio(rid, [5], sentido)
        f_dom, k_dom, e_dom = route_promedio(rid, [6], sentido)
        km_mes = k_lab * mdays["laboral"] + k_sat * mdays["sabado"] + k_dom * mdays["domingo"]
        return {
            "km_trazado": km_trazado_sen,
            "km_mensual": round(float(km_mes), 0),
            "veh_km_dia": {"laboral": k_lab, "sabado": k_sat, "domingo": k_dom},
            "expediciones": {"laboral": e_lab, "sabado": e_sat, "domingo": e_dom},
            "t_viaje_min": round(float(t_min), 1) if t_min == t_min and t_min is not None else None,
            "freq": {"laboral": f_lab, "sabado": f_sat, "domingo": f_dom},
        }

    services = {}
    for rid, info in rinfo.items():
        km_ida, km_reg = km_por_sentido(rid)
        km_tot = round(km_ida + km_reg, 2)
        t_tot = dur_by_route.get(rid, float("nan"))
        t_ida = dur_by_route_dir.get((rid, "ida"), float("nan"))
        t_reg = dur_by_route_dir.get((rid, "reg"), float("nan"))

        services[short_of(rid)] = {
            "servicio": short_of(rid),
            "nombre": info.get("route_long_name", ""),
            "color": color_of(rid),
            "km_ida": km_ida,
            "km_regreso": km_reg,
            # métricas por sentido: todo / ida / reg
            "todo": bloque_sentido(rid, "todo", km_tot, t_tot),
            "ida":  bloque_sentido(rid, "ida", km_ida, t_ida),
            "reg":  bloque_sentido(rid, "reg", km_reg, t_reg),
        }

    # ------------------------------------------------------------------ #
    # Resumen de zona
    # ------------------------------------------------------------------ #
    red_km = round(sum(shape_km.values()), 1)
    km_mes_zona = round(sum(s["todo"]["km_mensual"] for s in services.values()), 0)
    n_routes = int(routes["route_id"].nunique())
    n_trips  = int(trips["trip_id"].nunique())
    n_stops  = int(stops["stop_id"].nunique())
    n_shapes = int(len(shape_km))
    t_prom_zona = round(float(np.nanmean(list(dur_by_route.values()))), 1) if dur_by_route else None

    bbox = [float(stops["stop_lon"].min()), float(stops["stop_lat"].min()),
            float(stops["stop_lon"].max()), float(stops["stop_lat"].max())]

    legend = []
    for rid, info in rinfo.items():
        legend.append({"servicio": info.get("route_short_name") or rid,
                       "nombre": info.get("route_long_name", ""),
                       "color": "#" + str(info.get("route_color", "888888")).lstrip("#")})
    legend.sort(key=lambda x: str(x["servicio"]))

    summary = {
        "name": name, "slug": slug,
        "n_servicios": n_routes, "n_expediciones": n_trips,
        "n_paradas": n_stops, "n_trazados": n_shapes,
        "red_km": red_km, "km_mensual": km_mes_zona,
        "t_viaje_prom_min": t_prom_zona,
        "veh_km": vehkm, "expediciones_tipo": trips_by_type,
        "dias_mes": mdays, "bbox": bbox, "legend": legend,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    return summary, routes_geojson, stops_geojson, {"freq": freq}, services


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


def write_zone(slug, summary, routes_gj, stops_gj, freq, services):
    d = DATA_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    (d / "routes.geojson").write_text(json.dumps(routes_gj, ensure_ascii=False), encoding="utf-8")
    (d / "stops.geojson").write_text(json.dumps(stops_gj, ensure_ascii=False), encoding="utf-8")
    (d / "frequency.json").write_text(json.dumps(freq, ensure_ascii=False), encoding="utf-8")
    (d / "services.json").write_text(json.dumps(services, ensure_ascii=False), encoding="utf-8")


def _index_entry(summary):
    return {"name": summary["name"], "slug": summary["slug"],
            "n_servicios": summary["n_servicios"], "n_paradas": summary["n_paradas"],
            "red_km": summary["red_km"], "n_expediciones": summary["n_expediciones"],
            "generated_at": summary["generated_at"]}


def run(zones, local=None, slug=None, name=None):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    index = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "zones": []}

    if local:
        g = read_gtfs(Path(local).read_bytes())
        summary, rgj, sgj, fq, svc = process_feed(name or slug, slug, g)
        write_zone(slug, summary, rgj, sgj, fq, svc)
        index["zones"].append(_index_entry(summary))
        (DATA_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        log(f"OK (local) {slug}: {summary['n_servicios']} serv, {summary['red_km']} km, "
            f"{summary['n_paradas']} paradas, {len(svc)} fichas de servicio")
        return

    ok, fail = 0, 0
    for nm, sl, url in zones:
        t0 = time.time()
        log(f"[{sl}] descargando…")
        try:
            g = read_gtfs(fetch_zip(url))
            summary, rgj, sgj, fq, svc = process_feed(nm, sl, g)
            write_zone(sl, summary, rgj, sgj, fq, svc)
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Procesa GTFS DTPR a data/ (JSON+GeoJSON)")
    ap.add_argument("--only")
    ap.add_argument("--local")
    ap.add_argument("--slug")
    ap.add_argument("--name")
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
