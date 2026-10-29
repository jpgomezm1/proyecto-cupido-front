"""
Crea un código de acceso para la beta (migración 066): quien lo pone al registrarse o en
Mi cuenta › Plan queda con el plan Fundador (gratis hasta el 15-ene, luego $50.000 fijos).
Sin --aplicar solo muestra lo que crearía.

    venv/Scripts/python scripts/crear_codigo_acceso.py BETA-FYNDER --usos 10 --vence 2026-11-30
    venv/Scripts/python scripts/crear_codigo_acceso.py BETA-FYNDER --usos 10 --vence 2026-11-30 --aplicar
    venv/Scripts/python scripts/crear_codigo_acceso.py --lista
"""
import argparse
import io
import os
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.services import codigos_acceso_service as codigos  # noqa: E402
from src.services import fundador_service as fundador  # noqa: E402
from src.services.db import fetch_all, get_db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("codigo", nargs="?")
    ap.add_argument("--usos", type=int, default=1)
    ap.add_argument("--vence", help="AAAA-MM-DD (fin de ese día en Bogotá)")
    ap.add_argument("--notas")
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--lista", action="store_true")
    a = ap.parse_args()

    cupos = fundador.cupos()
    if a.lista or not a.codigo:
        with get_db() as db:
            for f in fetch_all(db.cursor, """SELECT c.codigo, c.usos, c.usos_max, c.vence_at::date AS vence, c.activo,
                                                   ARRAY_AGG(u.nombre) FILTER (WHERE u.id IS NOT NULL) AS quienes
                                            FROM codigos_acceso c
                                            LEFT JOIN codigos_acceso_canjes k ON k.codigo = c.codigo
                                            LEFT JOIN chat_users u ON u.id = k.user_id
                                            GROUP BY c.codigo ORDER BY c.created_at"""):
                print(f"  {f['codigo']:20} {f['usos']}/{f['usos_max']}  vence {f['vence'] or '—'}  "
                      f"{'activo' if f['activo'] else 'apagado'}  {', '.join(f['quienes'] or [])}")
        print(f"\nCupos de fundador: {cupos}")
        return

    vence = f"{a.vence} 23:59:59-05" if a.vence else None
    c = codigos.normalizar(a.codigo)
    print(f"Código {c}: {a.usos} usos, vence {a.vence or 'nunca'} → plan Fundador. Cupos de fundador: {cupos}")
    libres = cupos.get("libres", cupos.get("cupos_libres"))
    if isinstance(libres, int) and a.usos > libres:
        print(f"⚠️  Solo quedan {libres} cupos de fundador: los usos de más fallarán («ya se ocuparon los cupos»).")
    if not a.aplicar:
        print("\nCorre con --aplicar para crearlo.")
        return
    print("✅", codigos.crear(c, a.usos, vence, a.notas, "script"))


if __name__ == "__main__":
    main()
