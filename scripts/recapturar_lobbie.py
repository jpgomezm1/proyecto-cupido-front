"""Vuelve a leer los inmuebles de Lobbie que entraron sin ubicación ni cifras (la página de
compartir cambió en oct-2026) y llena SOLO los campos vacíos.

    python scripts/recapturar_lobbie.py               # revisión: cuántos y una muestra, no escribe
    python scripts/recapturar_lobbie.py --aplicar     # escribe

No toca lo que el dueño editó (campos_editados) ni lo que ya tiene valor. La ficha del
buscador se recalcula sola en el worker (cada 30 min), porque cambia su huella.
"""
import argparse
import contextlib
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.database import DatabaseManager  # noqa: E402
from src.scrapers.lobbie import LobbieScraper  # noqa: E402

CAMPOS = ["tipo_propiedad", "tipo_negocio", "ciudad", "zona", "departamento", "direccion_completa",
          "area_construida", "habitaciones", "banos", "parqueaderos", "administracion", "titulo"]
NUMERICOS = {"area_construida", "habitaciones", "banos", "parqueaderos", "administracion"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--desde", default="2026-09-01")
    ap.add_argument("--limite", type=int, default=500)
    a = ap.parse_args()

    with DatabaseManager() as db:
        db.cursor.execute("""
            SELECT id, url, campos_editados FROM propiedades
            WHERE origen = 'Lobbie_Captado' AND activa AND fecha_creacion >= %s
              AND (COALESCE(ciudad, '') = '' OR COALESCE(tipo_propiedad, '') = '' OR area_construida IS NULL)
            ORDER BY fecha_creacion DESC LIMIT %s
        """, (a.desde, a.limite))
        filas = db.cursor.fetchall()
    print(f"{len(filas)} inmuebles de Lobbie incompletos desde {a.desde}")

    scraper = LobbieScraper()
    llenos = fallidos = 0
    for f in filas:
        with contextlib.redirect_stdout(io.StringIO()):
            d = scraper.extract_property_data(f["url"])
        if not d:
            fallidos += 1
            continue
        editados = set(f["campos_editados"] or [])
        nuevos = {c: d.get(c) for c in CAMPOS if d.get(c) not in (None, "") and c not in editados}
        if not nuevos:
            fallidos += 1
            continue
        if llenos < 5 or not a.aplicar:
            print(f"  #{f['id']}: " + ", ".join(f"{k}={v}" for k, v in list(nuevos.items())[:6]))
        if a.aplicar:
            # Solo donde está vacío: COALESCE(actual, nuevo); en texto, '' también cuenta como vacío.
            sets = ", ".join(
                f"{c} = COALESCE({c}, %({c})s)" if c in NUMERICOS else f"{c} = COALESCE(NULLIF({c}, ''), %({c})s)"
                for c in nuevos)
            with DatabaseManager() as db:
                db.cursor.execute(f"UPDATE propiedades SET {sets} WHERE id = %(id)s", {**nuevos, "id": f["id"]})
                db.conn.commit()
        llenos += 1
        time.sleep(0.5)  # no martillar a Lobbie
    print(f"{'Actualizados' if a.aplicar else 'Se actualizarían'}: {llenos} · sin datos: {fallidos}")


if __name__ == "__main__":
    main()
