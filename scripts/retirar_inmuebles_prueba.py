"""
Retira (activa = FALSE) inmuebles de prueba que el equipo publicó en Fynder y que los agentes
ven en Findy y en el Inventario. Solo toca publicaciones con fuente 'Fynder' (nunca inventario
de portales). Sin --aplicar muestra lo que haría.

    venv/Scripts/python scripts/retirar_inmuebles_prueba.py 58662 59138 59437 61813
    venv/Scripts/python scripts/retirar_inmuebles_prueba.py 58662 59138 59437 61813 --aplicar
"""
import io
import os
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.services.db import fetch_all, get_db  # noqa: E402


def main(ids, aplicar: bool) -> None:
    with get_db() as db:
        cur = db.cursor
        filas = fetch_all(cur, """
            SELECT id, fuente, activa, titulo, precio_texto, fecha_creacion::date AS creado
            FROM propiedades WHERE id = ANY(%s) ORDER BY id
        """, (ids,))
        for f in filas:
            print(f"  {f['id']}  {f['fuente']:7} {'activa' if f['activa'] else 'inactiva':8} {f['creado']}  "
                  f"{f['precio_texto'] or ''}  {(f['titulo'] or '')[:60]}")
        faltan = set(ids) - {f["id"] for f in filas}
        if faltan:
            print(f"No existen: {sorted(faltan)}")
        retirar = [f["id"] for f in filas if f["fuente"] == "Fynder" and f["activa"]]
        otros = [f["id"] for f in filas if f["fuente"] != "Fynder"]
        if otros:
            print(f"No se tocan (no son publicaciones de Fynder): {otros}")
        if not aplicar:
            print(f"\nSe retirarían {len(retirar)}. Corre con --aplicar para hacerlo.")
            return
        if retirar:
            cur.execute("UPDATE propiedades SET activa = FALSE WHERE id = ANY(%s) AND fuente = 'Fynder'", (retirar,))
            db.conn.commit()
        print(f"\n✅ Retirados: {retirar}")


if __name__ == "__main__":
    ids = [int(a) for a in sys.argv[1:] if a.isdigit()]
    if not ids:
        sys.exit(__doc__)
    main(ids, "--aplicar" in sys.argv)
