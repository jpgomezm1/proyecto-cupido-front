"""
Marca como 'reemplazado' el pedido anterior que cada actualización reemplaza («actualizo el pedido…»,
«sigo buscando…»): el más parecido del mismo agente en los 45 días previos. Así no cuenta como otro comprador.
Los pedidos nuevos ya lo hacen solos al extraerse (pedidos_ia.estructurar_pendientes); esto es para los de antes.

Sin --aplicar solo muestra cuántos se marcarían.

    venv/Scripts/python scripts/marcar_actualizaciones.py
    venv/Scripts/python scripts/marcar_actualizaciones.py --aplicar
"""
import io
import os
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.services import pedidos_ia  # noqa: E402
from src.services.db import fetch_all, get_db  # noqa: E402


def main(aplicar: bool) -> None:
    with get_db() as db:
        cur = db.cursor
        acts = fetch_all(cur, """SELECT id, criterios FROM pedidos WHERE (criterios->>'es_actualizacion')::boolean
                                 ORDER BY fecha_captura""")
        marcados = []
        for a in acts:
            viejo = (pedidos_ia.marcar_reemplazado if aplicar else pedidos_ia.pedido_reemplazado)(cur, a["id"], a["criterios"])
            if viejo:
                marcados.append((a["id"], viejo))
        for nuevo, viejo in marcados:
            print(f"  #{nuevo} reemplaza a #{viejo}")
        if aplicar:
            db.conn.commit()
            print(f"\n✅ {len(marcados)} pedidos marcados como reemplazados (de {len(acts)} actualizaciones).")
        else:
            print(f"\nSe marcarían {len(marcados)} de {len(acts)}. Corre con --aplicar para hacerlo.")


if __name__ == "__main__":
    main("--aplicar" in sys.argv)
