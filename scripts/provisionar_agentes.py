"""
C1 — Provisiona cuentas de portal para los captadores con más inventario que
aún no tienen cuenta. Imprime el acceso (email + clave temporal) para el cold
WhatsApp. Ideal para pilotear con pocos agentes.

Uso:
    python scripts/provisionar_agentes.py --limit 10
    python scripts/provisionar_agentes.py --limit 10 --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()


def top_captadores(limit):
    conn = psycopg2.connect(os.getenv("DATABASE_URL"), cursor_factory=RealDictCursor)
    cur = conn.cursor()
    cur.execute("""
        SELECT RIGHT(REGEXP_REPLACE(agente_captador_telefono,'[^0-9]','','g'),10) AS tel10,
               MAX(agente_captador_telefono) AS telefono, COUNT(*) AS inventario
        FROM propiedades
        WHERE agente_captador_telefono IS NOT NULL
          AND RIGHT(REGEXP_REPLACE(agente_captador_telefono,'[^0-9]','','g'),10) NOT IN (
              SELECT RIGHT(REGEXP_REPLACE(COALESCE(telefono,''),'[^0-9]','','g'),10)
              FROM chat_users WHERE telefono IS NOT NULL)
        GROUP BY tel10
        ORDER BY inventario DESC
        LIMIT %s
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    captadores = top_captadores(args.limit)
    print(f"Captadores sin cuenta (top {args.limit} por inventario): {len(captadores)}\n")

    if args.dry_run:
        for c in captadores:
            print(f"  {c['telefono']}  ·  {c['inventario']} inmueble(s)")
        print("\n(dry-run: no se creó ninguna cuenta)")
        return

    from src.services.acquisition_service import provisionar_captador
    for c in captadores:
        res = provisionar_captador(c["telefono"])
        if res.get("error"):
            print(f"  ✗ {c['telefono']}: {res['error']}")
            continue
        print(f"  ✓ {res['email']}  |  clave: {res.get('password_temporal','(existente)')}  "
              f"|  {res['inventario']} inmueble(s)  |  {res['login_url']}")


if __name__ == "__main__":
    main()
