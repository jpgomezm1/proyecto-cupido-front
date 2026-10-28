"""
Corrige los títulos viejos de conversaciones de Findy: «3.0 hab» → «3 hab» y «$1.8B» / «$650M» → «$1.800 M» / «$650 M».
Solo toca el nombre (no la fecha de actualización). Sin --aplicar solo muestra lo que cambiaría.

    venv/Scripts/python scripts/corregir_nombres_conversaciones.py
    venv/Scripts/python scripts/corregir_nombres_conversaciones.py --aplicar
"""
import io
import os
import re
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.services.db import fetch_all, get_db  # noqa: E402


def corregir(nombre: str) -> str:
    n = re.sub(r"(\d+)\.0 hab\b", r"\1 hab", nombre)
    n = re.sub(r"\$(\d+(?:\.\d+)?)B\b", lambda m: "$" + f"{round(float(m.group(1)) * 1000):,}".replace(",", ".") + " M", n)
    n = re.sub(r"\$(\d+)M\b", r"$\1 M", n)
    return n


def main(aplicar: bool) -> None:
    with get_db() as db:
        filas = fetch_all(db.cursor, r"""SELECT id, nombre FROM conversaciones_busqueda
                                         WHERE nombre ~ '\.0 hab|\$[0-9.]+[BM]\M'""")
        cambios = [(f["id"], f["nombre"], corregir(f["nombre"])) for f in filas]
        cambios = [c for c in cambios if c[1] != c[2]]
        for _, viejo, nuevo in cambios[:15]:
            print(f"  {viejo}  →  {nuevo}")
        if aplicar:
            for cid, _, nuevo in cambios:
                db.cursor.execute("UPDATE conversaciones_busqueda SET nombre = %s WHERE id = %s", (nuevo, cid))
            db.conn.commit()
            print(f"\n✅ {len(cambios)} títulos corregidos.")
        else:
            print(f"\nSe corregirían {len(cambios)}. Corre con --aplicar para hacerlo.")


if __name__ == "__main__":
    main("--aplicar" in sys.argv)
