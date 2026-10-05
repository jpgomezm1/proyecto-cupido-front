"""
Carga inicial: estructura con Claude Haiku los pedidos recientes que no tienen
`criterios` (migración 041). Después lo mantiene el worker cada 15 minutos.

    python scripts/estructurar_pedidos.py            # últimos 120 días
    python scripts/estructurar_pedidos.py --dias 180 --lote 200

Costo aproximado: ~USD 0,0015 por pedido (Haiku 4.5).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from src.services.pedidos_ia import estructurar_pendientes  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=120)
    ap.add_argument("--lote", type=int, default=150)
    ap.add_argument("--concurrencia", type=int, default=8)
    args = ap.parse_args()
    total = errores = 0
    while True:
        r = estructurar_pendientes(dias=args.dias, limit=args.lote, concurrencia=args.concurrencia)
        total += r["procesados"]
        errores += r["errores"]
        print(f"lote: {r} · acumulado {total} ({errores} errores)", flush=True)
        if r["procesados"] == 0:
            break
    print(f"Listo: {total} pedidos estructurados, {errores} errores.")
