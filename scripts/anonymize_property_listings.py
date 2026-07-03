#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anonimiza/reescribe el titulo y la descripcion de las propiedades cargadas.

PROBLEMA QUE RESUELVE:
    El scraper guarda titulo y descripcion casi textuales del portal de origen
    (Wasi/Lobbie/tu360). Como el portal publico de Fynder muestra ese mismo
    texto, al googlear el nombre o una frase de la propiedad aparece el aviso
    original en el otro portal -> el comprador se salta a Fynder.

QUE HACE:
    Para cada propiedad reescribe con IA (Claude) un titulo y una descripcion
    100% originales que:
      - NO coinciden literalmente con el texto del portal de origen.
      - ELIMINAN identificadores unicos (nombre de edificio/conjunto, numero de
        unidad/apto, direccion exacta, telefonos, asesor/inmobiliaria, codigo de
        portal, URLs) que permitirian encontrar la propiedad en otro lado.
      - CONSERVAN los datos verificos genericos (tipo, ciudad, zona, area,
        habitaciones, banos, parqueaderos, estrato, precio, amenidades).
    El texto original se respalda en titulo_original / descripcion_original
    antes de sobrescribir (requiere migracion 031).

USO:
    # Ver que pasaria con una muestra (no escribe en la BD):
    python scripts/anonymize_property_listings.py --dry-run --limit 5

    # Aplicar a una muestra real para validar calidad:
    python scripts/anonymize_property_listings.py --apply --limit 5

    # Aplicar a TODAS las pendientes (reanudable; reejecutar continua donde quedo):
    python scripts/anonymize_property_listings.py --apply

    # Reprocesar incluso las ya anonimizadas:
    python scripts/anonymize_property_listings.py --apply --force

Es IDEMPOTENTE: solo procesa filas con anonimizado_at IS NULL (salvo --force),
asi que puede interrumpirse y reanudarse sin reescribir dos veces.
"""

import sys
import os
import io
import json
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# UTF-8 en Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.db.database import DatabaseManager
from src.core.listing_anonymizer import (
    ANONIMIZADO_VERSION,
    DEFAULT_MODEL,
    rewrite_listing,
)


def fetch_pending(db, limit, force):
    cond = "" if force else "AND anonimizado_at IS NULL"
    query = f"""
        SELECT id, codigo_propiedad, fuente, tipo_propiedad, tipo_negocio,
               ciudad, zona, area_construida, habitaciones, banos, parqueaderos,
               estrato, ano_construccion, precio, precio_texto, administracion,
               amenidades_internas, amenidades_externas,
               titulo, descripcion,
               titulo_original, descripcion_original
        FROM propiedades
        WHERE activa = TRUE {cond}
        ORDER BY id
    """
    if limit:
        query += f" LIMIT {int(limit)}"
    db.cursor.execute(query)
    return db.cursor.fetchall()


def apply_update(db, prop, nuevo_titulo, nueva_desc):
    """Respalda el original (si aun no) y escribe los textos nuevos."""
    # Respaldo solo la primera vez (no machacar el respaldo en reprocesos)
    titulo_original = prop.get('titulo_original') or prop.get('titulo')
    descripcion_original = prop.get('descripcion_original') or prop.get('descripcion')

    final_titulo = nuevo_titulo if nuevo_titulo else prop.get('titulo')
    final_desc = nueva_desc if nueva_desc is not None else prop.get('descripcion')
    desc_len = len(final_desc) if final_desc else 0

    db.cursor.execute(
        """
        UPDATE propiedades
        SET titulo = %s,
            descripcion = %s,
            descripcion_length = %s,
            titulo_original = COALESCE(titulo_original, %s),
            descripcion_original = COALESCE(descripcion_original, %s),
            anonimizado_at = CURRENT_TIMESTAMP,
            anonimizado_version = %s
        WHERE id = %s
        """,
        (final_titulo, final_desc, desc_len,
         titulo_original, descripcion_original,
         ANONIMIZADO_VERSION, prop['id']),
    )


def main():
    parser = argparse.ArgumentParser(description='Anonimiza titulo/descripcion de propiedades')
    parser.add_argument('--apply', action='store_true', help='Escribe los cambios en la BD')
    parser.add_argument('--dry-run', action='store_true', help='Solo muestra (default)')
    parser.add_argument('--limit', type=int, default=None, help='Procesar solo N propiedades')
    parser.add_argument('--force', action='store_true', help='Reprocesar incluso las ya anonimizadas')
    parser.add_argument('--model', default=DEFAULT_MODEL, help=f'Modelo Claude (default {DEFAULT_MODEL})')
    parser.add_argument('--workers', type=int, default=6, help='Llamadas IA concurrentes (default 6)')
    args = parser.parse_args()

    dry_run = not args.apply

    print("=" * 70)
    print("  ANONIMIZACION DE TITULO/DESCRIPCION DE PROPIEDADES")
    print("=" * 70)
    print(f"  Modo: {'DRY-RUN (no escribe)' if dry_run else 'APPLY (escribe en BD)'}")
    print(f"  Modelo: {args.model}")
    if args.limit:
        print(f"  Limite: {args.limit}")
    if args.force:
        print(f"  Force: reprocesando ya anonimizadas")
    print("=" * 70)

    ok = 0
    fail = 0

    def process(prop):
        """Worker: solo llama a la IA (red). Devuelve (prop, titulo, desc, err)."""
        try:
            t, d = rewrite_listing(prop, args.model)
            return prop, t, d, None
        except Exception as e:
            return prop, None, None, e

    with DatabaseManager() as db:
        props = fetch_pending(db, args.limit, args.force)
        total = len(props)
        print(f"\nPropiedades a procesar: {total} | workers={args.workers}\n")

        done = 0
        # Las llamadas IA corren en paralelo; las escrituras a 'propiedades'
        # se hacen aqui (hilo principal, una sola conexion -> seguro).
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(process, p): p for p in props}
            for fut in as_completed(futures):
                prop, nuevo_titulo, nueva_desc, err = fut.result()
                done += 1
                pid = prop['id']

                if err is not None:
                    fail += 1
                    print(f"[{done}/{total}] ID {pid} -> ERROR IA: {err}")
                    continue

                if not nuevo_titulo and nueva_desc is None:
                    fail += 1
                    print(f"[{done}/{total}] ID {pid} -> respuesta IA invalida, se omite (reanudable)")
                    continue

                if dry_run:
                    print(f"\n[{done}/{total}] ID {pid} | {prop['fuente']} | {prop.get('ciudad')}/{prop.get('zona')}")
                    print(f"  TITULO  antes: {prop.get('titulo')}")
                    print(f"  TITULO ahora : {nuevo_titulo}")
                    if nueva_desc:
                        print(f"  DESC ahora   : {nueva_desc[:280]}{'...' if len(nueva_desc) > 280 else ''}")
                    ok += 1
                else:
                    try:
                        apply_update(db, prop, nuevo_titulo, nueva_desc)
                        db.conn.commit()
                        ok += 1
                    except Exception as e:
                        db.conn.rollback()
                        fail += 1
                        print(f"[{done}/{total}] ID {pid} -> ERROR DB: {e}")
                        continue
                    if done % 25 == 0 or done == total:
                        print(f"[{done}/{total}] aplicadas={ok} fallidas={fail}")

    print("\n" + "=" * 70)
    print(f"  Terminado. Procesadas OK: {ok} | Fallidas/omitidas: {fail}")
    if dry_run:
        print("  (DRY-RUN: no se escribio nada. Usa --apply para aplicar.)")
    print("=" * 70)


if __name__ == '__main__':
    main()
