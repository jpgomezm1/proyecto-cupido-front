#!/usr/bin/env python3
"""
Completa con IA la ficha de los inmuebles (tabla propiedades_ficha).

    python scripts/enriquecer_fichas.py --todas            # backfill del inventario activo
    python scripts/enriquecer_fichas.py --lote 200         # una tanda
    python scripts/enriquecer_fichas.py --estado           # cuántas faltan

El worker hace lo mismo cada 10 min para lo nuevo o lo que cambió.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.services import ficha_service  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--todas", action="store_true")
    g.add_argument("--lote", type=int)
    g.add_argument("--estado", action="store_true")
    ap.add_argument("--hilos", type=int, default=8)
    a = ap.parse_args()

    if a.estado:
        print(f"Pendientes: {len(ficha_service.pendientes(100000))}")
        return
    if a.lote:
        print(ficha_service.enriquecer(limite=a.lote, hilos=a.hilos))
        return
    total, t0 = 0, time.time()
    while True:
        r = ficha_service.enriquecer(limite=400, hilos=a.hilos)
        total += r["procesadas"]
        print(f"{r} · total {total} · {round(time.time() - t0)} s", flush=True)
        if r["procesadas"] == 0:
            break


if __name__ == "__main__":
    main()
