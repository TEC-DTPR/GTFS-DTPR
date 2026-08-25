#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cruce_censo.py  (Fase 2 - nube)
-------------------------------
Para cada zona que tenga censo_manzanas/<slug>.geojson, hace un buffer de 200 m
sobre los TRAZADOS (routes.geojson generado por process_gtfs.py), lo intersecta
con las manzanas censales ponderando por fraccion de area, y escribe:

    data/<slug>/censo.json   { "zona": {...}, "servicios": { "<ss>": {...} } }

Se ejecuta DESPUES de process_gtfs.py (necesita data/<slug>/routes.geojson).
Si una zona no tiene censo_manzanas/<slug>.geojson, se salta sin error.

Requisitos: geopandas, shapely, pyproj
"""

import json
import gc
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CENSO_DIR = ROOT / "censo_manzanas"

BUFFER_M = 200
CRS_GEO = "EPSG:4674"     # SIRGAS 2000 geografico (censo)
CRS_MET = "EPSG:32719"    # UTM 19S metrico (Chile continental)

# campos que se SUMAN ponderados por fraccion de area
POB_FIELDS = [
    "n_per", "n_hombres", "n_mujeres",
    "n_edad_0_5", "n_edad_6_1", "n_edad_14_", "n_edad_18_",
    "n_edad_25_", "n_edad_45_", "n_edad_60_",
    "n_transpor", "n_transp_1", "n_transp_2", "n_transp_3",
    "n_transp_4", "n_transp_5", "n_transp_6",
]
# indices que se PROMEDIAN ponderados por poblacion (0 = sin dato -> excluir)
IDX_FIELDS = ["dim_acc", "dim_soc"]


def log(*a):
    print(*a, flush=True)


def load_manzanas(paths):
    """Carga una o varias partes (geojson/parquet) de una zona y las concatena."""
    parts = []
    for path in paths:
        g = gpd.read_file(path)
        if g.crs is None:
            g = g.set_crs(CRS_GEO)
        parts.append(g.to_crs(CRS_MET))
    g = pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]
    g = gpd.GeoDataFrame(g, geometry="geometry", crs=CRS_MET)
    for c in POB_FIELDS + IDX_FIELDS:
        if c not in g.columns:
            g[c] = 0
        g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0)
    g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
    # repara geometrias invalidas (auto-intersecciones tipicas del shapefile)
    inval = ~g.geometry.is_valid
    if inval.any():
        try:
            g.loc[inval, "geometry"] = g.loc[inval, "geometry"].make_valid()
        except Exception:
            g.loc[inval, "geometry"] = g.loc[inval, "geometry"].buffer(0)
        g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
        g = g[g.geometry.is_valid].copy()
    g["_area_mz"] = g.geometry.area
    g = g[g["_area_mz"] > 0].copy()
    return g


def buffer_union_lotes(geoms, dist, lote=400):
    """Buffer de cada geometría y unión por lotes. Mucho más liviano en RAM que
    unary_union de miles de líneas crudas de golpe."""
    import numpy as np
    geoms = list(geoms)
    if not geoms:
        return None
    parciales = []
    for i in range(0, len(geoms), lote):
        sub = geoms[i:i + lote]
        try:
            u = unary_union(sub).buffer(dist)
        except Exception:
            u = unary_union([g.buffer(0) for g in sub]).buffer(dist)
        parciales.append(u)
    return unary_union(parciales) if len(parciales) > 1 else parciales[0]


def aggregate_in_buffer(manz, buffer_geom, sindex=None):
    """Recorta manzanas al buffer y agrega campos ponderando por fraccion de area.
    Usa el indice espacial para tocar solo las manzanas candidatas (rapido y liviano)."""
    # 1) prefiltro por bounding box via indice espacial
    if sindex is not None:
        idx = list(sindex.query(buffer_geom, predicate="intersects"))
        if not idx:
            return None
        cand = manz.iloc[idx]
    else:
        cand = manz[manz.geometry.intersects(buffer_geom)]
    if cand.empty:
        return None

    # 2) interseccion solo sobre candidatas (vectorizado, con reparacion puntual)
    geoms = cand.geometry.values
    try:
        inter = geoms.intersection(buffer_geom)
    except Exception:
        inter = geoms.buffer(0).intersection(buffer_geom.buffer(0))

    clip = cand.copy()
    clip["geometry"] = inter
    clip = clip[clip.geometry.notna() & ~clip.geometry.is_empty].copy()
    if clip.empty:
        return None

    clip["_frac"] = (clip.geometry.area / clip["_area_mz"]).clip(0, 1)

    out = {}
    for c in POB_FIELDS:
        out[c] = int(round(float((clip[c] * clip["_frac"]).sum())))

    w = clip["n_per"] * clip["_frac"]
    for c in IDX_FIELDS:
        mask = clip[c] > 0
        wsum = float(w[mask].sum())
        out[c] = round(float((clip.loc[mask, c] * w[mask]).sum() / wsum), 3) if wsum > 0 else None

    out["n_manzanas"] = int(len(clip))
    return out


def process_zone(slug, manz_paths):
    routes_path = DATA_DIR / slug / "routes.geojson"
    if not routes_path.exists():
        log(f"[{slug}] sin routes.geojson (¿corriste process_gtfs?) — salto")
        return False

    routes = gpd.read_file(routes_path)
    if routes.crs is None:
        routes = routes.set_crs("EPSG:4326")
    routes = routes.to_crs(CRS_MET)
    routes = routes[routes.geometry.notna() & ~routes.geometry.is_empty].copy()
    if routes.empty:
        log(f"[{slug}] routes vacío — salto")
        return False

    manz = load_manzanas(manz_paths)
    log(f"[{slug}]   manzanas cargadas: {len(manz):,}")
    _ = manz.sindex   # fuerza construir el índice una vez
    sindex = manz.sindex

    # ---- buffer de zona: unir trazados por lotes (evita un unary_union gigante) ----
    zona_buf = buffer_union_lotes(routes.geometry.values, BUFFER_M)
    zona = aggregate_in_buffer(manz, zona_buf, sindex)
    del zona_buf
    gc.collect()
    log(f"[{slug}]   zona lista, procesando {routes['servicio'].nunique() if 'servicio' in routes.columns else 0} servicios…")

    # ---- buffer por servicio ----
    servicios = {}
    if "servicio" in routes.columns:
        for ss, grp in routes.groupby("servicio"):
            if not str(ss).strip():
                continue
            buf = buffer_union_lotes(grp.geometry.values, BUFFER_M)
            agg = aggregate_in_buffer(manz, buf, sindex)
            if agg:
                servicios[str(ss)] = agg

    out = {
        "buffer_m": BUFFER_M,
        "zona": zona or {},
        "servicios": servicios,
    }
    (DATA_DIR / slug / "censo.json").write_text(
        json.dumps(out, ensure_ascii=False), encoding="utf-8")
    npob = (zona or {}).get("n_per", 0)
    log(f"[{slug}] censo OK · {npob:,} hab servidos · {len(servicios)} servicios")
    del manz, sindex, routes
    gc.collect()
    return True


def run():
    if not CENSO_DIR.exists():
        log(f"No existe {CENSO_DIR} — nada que cruzar. (Sube censo_manzanas/<slug>.geojson)")
        return
    files = sorted(list(CENSO_DIR.glob("*.geojson")) + list(CENSO_DIR.glob("*.parquet")))
    if not files:
        log("censo_manzanas/ vacío — nada que cruzar.")
        return

    # agrupa por slug: "rm-sur.geojson" y "rm-sur_1.geojson"/"rm-sur_2" -> "rm-sur"
    import re
    grupos = {}
    for f in files:
        base = re.sub(r"_\d+$", "", f.stem)   # quita sufijo _1, _2, …
        grupos.setdefault(base, []).append(f)

    ok = 0
    for slug, paths in sorted(grupos.items()):
        try:
            if process_zone(slug, sorted(paths)):
                ok += 1
        except Exception as e:
            log(f"[{slug}] ERROR censo: {e}")
    log(f"\nCruce censo listo. {ok}/{len(grupos)} zonas.")


if __name__ == "__main__":
    run()
