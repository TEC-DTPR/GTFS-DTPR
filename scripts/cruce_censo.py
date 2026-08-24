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


def aggregate_in_buffer(manz, buffer_geom):
    """Recorta manzanas al buffer y agrega campos ponderando por fraccion de area."""
    try:
        clip = gpd.clip(manz, buffer_geom)
    except Exception:
        m2 = manz.copy()
        m2["geometry"] = m2.geometry.buffer(0)
        m2 = m2[m2.geometry.is_valid & ~m2.geometry.is_empty]
        try:
            clip = gpd.clip(m2, buffer_geom.buffer(0))
        except Exception:
            buf = buffer_geom.buffer(0)
            rows = []
            for _, r in m2.iterrows():
                try:
                    inter = r.geometry.intersection(buf)
                    if not inter.is_empty:
                        rr = r.copy(); rr["geometry"] = inter; rows.append(rr)
                except Exception:
                    continue
            if not rows:
                return None
            clip = gpd.GeoDataFrame(rows, crs=manz.crs)
    if clip.empty:
        return None
    clip = clip[clip.geometry.notna() & ~clip.geometry.is_empty].copy()
    if clip.empty:
        return None
    # fraccion de cada manzana que cae dentro del buffer
    clip["_frac"] = (clip.geometry.area / clip["_area_mz"]).clip(0, 1)

    out = {}
    for c in POB_FIELDS:
        out[c] = int(round(float((clip[c] * clip["_frac"]).sum())))

    # indices: promedio ponderado por poblacion en la interseccion (excluye 0)
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

    # ---- buffer de zona (union de todos los trazados) ----
    zona_buf = unary_union(routes.geometry.values).buffer(BUFFER_M)
    zona = aggregate_in_buffer(manz, zona_buf)

    # ---- buffer por servicio ----
    servicios = {}
    if "servicio" in routes.columns:
        for ss, grp in routes.groupby("servicio"):
            if not str(ss).strip():
                continue
            buf = unary_union(grp.geometry.values).buffer(BUFFER_M)
            agg = aggregate_in_buffer(manz, buf)
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
