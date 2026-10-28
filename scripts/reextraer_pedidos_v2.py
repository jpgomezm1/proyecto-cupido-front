"""
Re-extrae los pedidos recientes con la versión 2 (pedidos_ia.estructurar_pedido): ubicaciones con nivel,
unidades, opciones con «O», cómo paga, urgencia, perfil y comisión. Las claves de la versión 1 se siguen
llenando, así que compradores, alertas y encargos funcionan igual mientras pasan al esquema nuevo.

Sin --aplicar solo cuenta cuántos faltan y estima el costo (Haiku con caché de prompt: ~US$0,0035 por pedido).
Con --aplicar procesa por tandas y guarda cada tanda: si se corta, al volver a correrlo sigue donde iba
(solo toma los que no están en versión 2). Al final reasigna los barrios de los pedidos tocados.

    venv/Scripts/python scripts/reextraer_pedidos_v2.py                  # cuenta y costo
    venv/Scripts/python scripts/reextraer_pedidos_v2.py --aplicar        # re-extrae (120 días)
    venv/Scripts/python scripts/reextraer_pedidos_v2.py --aplicar --dias 30 --limite 200
"""
import argparse
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.services import pedidos_ia  # noqa: E402
from src.services.db import fetch_all, fetch_one, get_db  # noqa: E402

COSTO_POR_PEDIDO = 0.0035
TANDA = 100


def _pendientes(dias: int, limite: int):
    with get_db() as db:
        return fetch_all(db.cursor, """
            SELECT id, texto_pedido FROM pedidos
            WHERE fecha_captura > NOW() - make_interval(days => %s)
              AND texto_pedido IS NOT NULL AND LENGTH(TRIM(texto_pedido)) > 10
              AND (criterios IS NULL OR criterios->>'_v' IS DISTINCT FROM %s)
            ORDER BY fecha_captura DESC
            LIMIT %s
        """, (dias, str(pedidos_ia.VERSION), limite))


def _uno(f):
    try:
        return f["id"], pedidos_ia.estructurar_pedido(f["texto_pedido"]), None
    except Exception as e:  # noqa: BLE001 — un pedido malo no frena el lote
        return f["id"], None, f"{type(e).__name__}: {str(e)[:120]}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--dias", type=int, default=120)
    ap.add_argument("--limite", type=int, default=5000)
    ap.add_argument("--concurrencia", type=int, default=6)
    a = ap.parse_args()

    filas = _pendientes(a.dias, a.limite)
    print(f"Pedidos de los últimos {a.dias} días sin versión {pedidos_ia.VERSION}: {len(filas)} "
          f"(costo estimado ≈ US${len(filas) * COSTO_POR_PEDIDO:.2f})")
    if not a.aplicar or not filas:
        if not a.aplicar:
            print("Sin --aplicar no se escribe ni se gasta nada.")
        return

    ok = errores = 0
    tocados = []
    t0 = time.time()
    for i in range(0, len(filas), TANDA):
        tanda = filas[i:i + TANDA]
        with ThreadPoolExecutor(max_workers=a.concurrencia) as ex:
            res = list(ex.map(_uno, tanda))
        buenos = [(pid, crit) for pid, crit, err in res if crit]
        for pid, _, err in res:
            if err:
                errores += 1
                print(f"  pedido {pid}: {err}")
        if buenos:
            with get_db() as db:
                for pid, crit in buenos:
                    db.cursor.execute(
                        "UPDATE pedidos SET criterios = %s, criterios_at = NOW(), barrio_at = NULL WHERE id = %s",
                        (json.dumps(crit, ensure_ascii=False), pid))
                db.conn.commit()
            tocados += [pid for pid, _ in buenos]
        ok += len(buenos)
        print(f"  {min(i + TANDA, len(filas))}/{len(filas)} · ok {ok} · errores {errores} · {time.time() - t0:.0f} s")

    from src.services import barrios_service
    print(f"Barrios reasignados: {barrios_service.asignar_pedidos()} pedidos")
    with get_db() as db:
        v = fetch_one(db.cursor, """SELECT COUNT(*) FILTER (WHERE criterios->>'_v' = %s) v2, COUNT(*) total FROM pedidos
                                    WHERE fecha_captura > NOW() - make_interval(days => %s)""",
                      (str(pedidos_ia.VERSION), a.dias))
    print(f"\n✅ Listo: {ok} re-extraídos, {errores} con error. En versión 2: {v['v2']} de {v['total']}.")


if __name__ == "__main__":
    main()
