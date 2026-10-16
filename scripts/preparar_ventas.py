"""
Prepara la lista de Ventas (migración 060): agrega los celulares de quienes
publicaron inmuebles o pedidos y arma el gancho de cada mensaje (sin IA).

    python scripts/preparar_ventas.py              # sembrar + ganchos de los que no tienen
    python scripts/preparar_ventas.py --todos      # recalcula también los que ya tenían gancho
    python scripts/preparar_ventas.py --limite 50  # solo los 50 de más prioridad

Escribe en la base del .env (ventas_agentes). Se puede correr las veces que se quiera:
no toca el estado comercial ni las notas.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.services import ventas_service as ventas  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--todos", action="store_true", help="recalcular también los que ya tienen gancho")
    ap.add_argument("--limite", type=int, default=1000)
    args = ap.parse_args()

    t = time.time()
    print("Sembrando la lista…", flush=True)
    print("  ", ventas.sembrar(), flush=True)
    print("Calculando ganchos (sin IA)…", flush=True)
    res = ventas.calcular_ganchos(limite=args.limite, solo_sin_gancho=not args.todos,
                                  log=lambda m: print(m, flush=True))
    print("  ", res)
    print(f"Listo en {time.time() - t:.0f} s")


if __name__ == "__main__":
    main()
