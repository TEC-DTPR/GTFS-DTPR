#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_demanda_index.py
--------------------
Escanea data/demanda/<slug>/<AAAA-MM>.json y arma data/demanda/index.json,
detectando para cada zona qué meses hay y si el archivo trae APC, TRX o ambos.
Correr después de subir/actualizar los JSON de demanda.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEM = ROOT / "data" / "demanda"


def detecta_tipo(path):
    """Mira un JSON de demanda y decide si es apc, trx o apc-trx."""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return "apc"
    perfiles = list(d.get("perfiles", {}).values())[:400]
    hay_apc = any(any(v > 0 for v in p.get("carga_apc", [])) for p in perfiles)
    hay_trx = any(any(v > 0 for v in p.get("carga_trx", [])) for p in perfiles)
    if hay_apc and hay_trx:
        return "apc-trx"
    if hay_trx:
        return "trx"
    return "apc"


def run():
    if not DEM.exists():
        print("No existe data/demanda/, nada que indexar.")
        return
    idx = {"zonas": {}}
    for slug in sorted(os.listdir(DEM)):
        zdir = DEM / slug
        if not zdir.is_dir():
            continue
        meses = sorted(f[:-5] for f in os.listdir(zdir)
                       if f.endswith(".json") and f != "index.json")
        if not meses:
            continue
        # tipo se decide con el mes más reciente
        tipo = detecta_tipo(zdir / f"{meses[-1]}.json")
        idx["zonas"][slug] = {"meses": meses, "tipo": tipo}
        print(f"  {slug:<14} meses={meses} tipo={tipo}")
    (DEM / "index.json").write_text(
        json.dumps(idx, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"\nindex.json escrito con {len(idx['zonas'])} zonas.")


if __name__ == "__main__":
    run()
