#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cruce_censo.py  (Fase 2 - nube)
-------------------------------
Para cada zona con censo_manzanas/<slug>.geojson, determina qué manzanas están
a <= 200 m de los TRAZADOS (routes.geojson) mediante join espacial por distancia
(sin construir buffers-unión, que se colgaban en zonas con cientos de servicios),
y escribe data/<slug>/censo.json { "zona": {...}, "servicios": {...} }.

Corre DESPUES de process_gtfs.py. Zona sin archivo se salta.
Requisitos: geopandas, shapely, pyproj
"""

import gc
import json
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CENSO_DIR = ROOT / "censo_manzanas"

BUFFER_M = 200
CRS_GEO = "EPSG:4674"
CRS_MET = "EPSG:32719"

POB_FIELDS = [
    "n_per", "n_hombres", "n_mujeres",
    "n_edad_0_5", "n_edad_6_1", "n_edad_14_", "n_edad_18_",
    "n_edad_25_", "n_edad_45_", "n_edad_60_",
    "n_transpor", "n_transp_1", "n_transp_2", "n_transp_3",
    "n_transp_4", "n_transp_5", "n_transp_6",
]
IDX_FIELDS = ["dim_acc", "dim_soc"]


def log(*a):
    print(*a, flush=True)


def load_manzanas(paths):
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
    inval = ~g.geometry.is_valid
    if inval.any():
        try:
            g.loc[inval, "geometry"] = g.loc[inval, "geometry"].make_valid()
        except Exception:
            g.loc[inval, "geometry"] = g.loc[inval, "geometry"].buffer(0)
        g = g[g.geometry.notna() & ~g.geometry.is_empty & g.geometry.is_valid].copy()
    g = g.reset_index(drop=True)
    return g


def manzanas_cercanas(manz, lineas_gdf, dist=BUFFER_M):
    """Índices de manzanas cuya geometría está a <= dist de alguna línea.
    Usa sjoin con predicate dwithin (rápido, sin construir buffers)."""
    left = manz[["geometry"]].copy()
    right = gpd.GeoDataFrame(geometry=list(lineas_gdf), crs=manz.crs)
    try:
        j = gpd.sjoin(left, right, how="inner", predicate="dwithin", distance=dist)
    except TypeError:
        # geopandas viejo sin 'distance' en dwithin: usa buffer del lado derecho
        rb = right.copy()
        rb["geometry"] = rb.geometry.buffer(dist)
        j = gpd.sjoin(left, rb, how="inner", predicate="intersects")
    return manz.index.isin(j.index.unique())


def agregar(manz, mask):
    """Suma los campos de las manzanas seleccionadas (conteo entero, sin fracción
    de área: una manzana a <=200 m se cuenta completa — criterio de cobertura)."""
    sel = manz[mask]
    if sel.empty:
        return None
    out = {}
    for c in POB_FIELDS:
        out[c] = int(sel[c].sum())
    for c in IDX_FIELDS:
        m = sel[c] > 0
        w = sel.loc[m, "n_per"]
        wsum = float(w.sum())
        out[c] = round(float((sel.loc[m, c] * w).sum() / wsum), 3) if wsum > 0 else None
    out["n_manzanas"] = int(len(sel))
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

    # ---- zona: manzanas cercanas a CUALQUIER trazado ----
    mask_zona = manzanas_cercanas(manz, routes.geometry.values, BUFFER_M)
    zona = agregar(manz, mask_zona)
    nserv = routes["servicio"].nunique() if "servicio" in routes.columns else 0
    log(f"[{slug}]   zona lista ({int(mask_zona.sum()):,} manzanas), {nserv} servicios…")

    # ---- por servicio ----
    servicios = {}
    if "servicio" in routes.columns:
        for ss, grp in routes.groupby("servicio"):
            if not str(ss).strip():
                continue
            mask_ss = manzanas_cercanas(manz, grp.geometry.values, BUFFER_M)
            agg = agregar(manz, mask_ss)
            if agg:
                servicios[str(ss)] = agg

    out = {"buffer_m": BUFFER_M, "zona": zona or {}, "servicios": servicios}
    (DATA_DIR / slug / "censo.json").write_text(
        json.dumps(out, ensure_ascii=False), encoding="utf-8")
    npob = (zona or {}).get("n_per", 0)
    log(f"[{slug}] censo OK · {npob:,} hab servidos · {len(servicios)} servicios")
    del manz, routes
    gc.collect()
    return True


def run():
    if not CENSO_DIR.exists():
        log(f"No existe {CENSO_DIR} — nada que cruzar.")
        return
    files = sorted(list(CENSO_DIR.glob("*.geojson")) + list(CENSO_DIR.glob("*.parquet")))
    if not files:
        log("censo_manzanas/ vacío — nada que cruzar.")
        return

    grupos = {}
    for f in files:
        base = re.sub(r"_\d+$", "", f.stem)
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
