#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Salud de la verificación de links (lo usa el skill /validate-links).

El trabajo diario lo hace el worker (`revalidar_lote` cada 30 min). Este script
sirve para mirar y para casos puntuales; usa los mismos detectores por portal
de src/services/disponibilidad_service.py.

Uso:
    python scripts/validate_property_urls.py --reporte
        Frescura por portal (meta: verificada hace ≤ 8 días) y qué hizo el
        validador la última semana. Solo lectura.

    python scripts/validate_property_urls.py --muestra 40
        Revisa en vivo N activas y N/2 inactivas por portal y compara el
        veredicto con lo que dice la base. No escribe nada. Sirve para detectar
        que un portal cambió su HTML (suben los "inciertos" o los desacuerdos).

    python scripts/validate_property_urls.py --rescatar [--dias 90] [--aplicar]
        Busca inmuebles inactivos que NO bajó el validador (los bajó un script
        viejo o una persona) y que hoy siguen publicados. Sin --aplicar solo los
        lista; con --aplicar los reactiva y deja constancia.

    python scripts/validate_property_urls.py --lote 200
        Fuerza ya una corrida de revalidación de N inmuebles (escribe).
"""

import argparse
import collections
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.services.db import get_db, fetch_all  # noqa: E402
from src.services import disponibilidad_service as disp  # noqa: E402

_PORTALES = {"wasi": r"wasi\.co", "lobbie": r"lobbieapp\.com", "pulppo": r"pulppo"}


def _diag(fila):
    return fila, disp.diagnosticar(disp.build_session(), fila["url"])


def reporte() -> None:
    s = disp.salud()
    print(f"\nActivas: {s['activas']} · verificadas en ≤ 8 días: {s['frescas']} ({s['pct_sla']} %)\n")
    print(f"{'portal':10} {'activas':>8} {'frescas':>8} {'%':>6} {'nunca':>7}")
    for r in s["por_portal"]:
        pct = round(100 * r["frescas"] / r["activas"], 1) if r["activas"] else 0
        print(f"{r['portal']:10} {r['activas']:>8} {r['frescas']:>8} {pct:>6} {r['nunca_revisadas']:>7}")
    print("\nÚltimos 7 días (veredictos del validador):")
    for r in s["ultima_semana"]:
        print(f"  {r['portal']:8} {r['veredicto']:9} {r['n']:>6}  "
              f"desactivadas {r['desactivadas']:>4} · reactivadas {r['reactivadas']:>4}")
    if s["inciertos_frecuentes"]:
        print("\nInciertos más frecuentes (si crecen, revisar el detector de ese portal):")
        for r in s["inciertos_frecuentes"]:
            print(f"  {r['portal']:8} {r['motivo']:45} {r['n']:>5}")


def muestra(n: int) -> None:
    with get_db() as db:
        filas = []
        for portal, rx in _PORTALES.items():
            for activa, k in ((True, n), (False, max(1, n // 2))):
                filas += [dict(f, portal=portal) for f in fetch_all(db.cursor, """
                    SELECT id, url, activa FROM propiedades
                    WHERE url ~* %s AND activa = %s ORDER BY random() LIMIT %s
                """, (rx, activa, k))]
    with ThreadPoolExecutor(8) as pool:
        resultados = list(pool.map(_diag, filas))

    print("\nVeredicto en vivo vs. la base (nada se escribe):")
    cuenta = collections.Counter(
        (f["portal"], "activa" if f["activa"] else "inactiva", v.veredicto) for f, v in resultados)
    for (portal, db_estado, ver), k in sorted(cuenta.items()):
        alerta = ""
        if (db_estado == "activa" and ver == "muerto") or (db_estado == "inactiva" and ver == "vivo"):
            alerta = "  ← desacuerdo"
        elif ver == "incierto":
            alerta = "  ← incierto"
        print(f"  {portal:8} en base {db_estado:8} → {ver:9} {k:>4}{alerta}")
    raros = [(f, v) for f, v in resultados if v.veredicto == "incierto"]
    for f, v in raros[:10]:
        print(f"    #{f['id']} {v.motivo}  {f['url'][:80]}")


def rescatar(dias: int, aplicar: bool) -> None:
    with get_db() as db:
        filas = fetch_all(db.cursor, f"""
            SELECT id, url, titulo FROM propiedades
            WHERE NOT activa AND desactivada_por IS NULL
              AND url IS NOT NULL AND url <> '' AND {disp._SQL_SIN_PROPIOS}
              AND fecha_actualizacion > NOW() - (%s * INTERVAL '1 day')
            ORDER BY fecha_actualizacion DESC
        """, (dias,))
    print(f"\nRevisando {len(filas)} inactivos de los últimos {dias} días que no bajó el validador…")
    with ThreadPoolExecutor(8) as pool:
        vivos = [(f, v) for f, v in pool.map(_diag, filas) if v.veredicto == "vivo"]

    print(f"Siguen publicados: {len(vivos)}")
    for f, v in vivos[:40]:
        print(f"  #{f['id']:>6} {v.portal:7} {(f['titulo'] or '')[:60]}")
    if len(vivos) > 40:
        print(f"  … y {len(vivos) - 40} más")
    if not aplicar or not vivos:
        if vivos:
            print("\nPara reactivarlos: --rescatar --aplicar")
        return

    with get_db() as db:
        for f, v in vivos:
            db.cursor.execute("""
                UPDATE propiedades
                SET activa = TRUE, fecha_actualizacion = NOW(), validaciones_fallidas_consecutivas = 0,
                    fecha_ultima_validacion = NOW(), fecha_ultimo_intento = NOW(),
                    disponibilidad_motivo = %s
                WHERE id = %s AND NOT activa
            """, (v.motivo, f["id"]))
            db.cursor.execute("""
                INSERT INTO verificaciones_disponibilidad
                    (propiedad_id, veredicto, motivo, status_code, portal, origen, cambio)
                VALUES (%s, 'vivo', %s, %s, %s, 'rescate', 'reactivada')
            """, (f["id"], v.motivo, v.status, v.portal))
        db.conn.commit()
    print(f"Reactivados: {len(vivos)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--reporte", action="store_true")
    g.add_argument("--muestra", type=int, metavar="N")
    g.add_argument("--rescatar", action="store_true")
    g.add_argument("--lote", type=int, metavar="N")
    ap.add_argument("--dias", type=int, default=90)
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()

    if not os.getenv("DATABASE_URL"):
        sys.exit("DATABASE_URL no configurada")
    if a.reporte:
        reporte()
    elif a.muestra:
        muestra(a.muestra)
    elif a.rescatar:
        rescatar(a.dias, a.aplicar)
    else:
        print(disp.revalidar_lote(n=a.lote))


if __name__ == "__main__":
    main()
