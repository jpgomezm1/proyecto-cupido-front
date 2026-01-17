#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para eliminar registros de Lobbie de la base de datos.
Estos registros fueron scrappeados incorrectamente con título "Lobiapp" y descripción vacía.

Ejecutar: python scripts/delete_lobbie_records.py
"""

import os
import sys

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.database import DatabaseManager


def main():
    print("=" * 60)
    print("ELIMINAR REGISTROS DE LOBBIE")
    print("=" * 60)

    with DatabaseManager() as db:
        # 1. Contar registros de Lobbie
        db.cursor.execute("""
            SELECT COUNT(*) as total
            FROM propiedades
            WHERE fuente = 'Lobbie' OR fuente ILIKE '%lobbie%'
        """)
        result = db.cursor.fetchone()
        total = result['total'] if result else 0

        print(f"\nRegistros de Lobbie encontrados: {total}")

        if total == 0:
            print("No hay registros de Lobbie para eliminar.")
            return

        # 2. Mostrar los registros que se van a eliminar
        db.cursor.execute("""
            SELECT id, titulo, ciudad, zona, fuente, fecha_extraccion
            FROM propiedades
            WHERE fuente = 'Lobbie' OR fuente ILIKE '%lobbie%'
            ORDER BY fecha_extraccion DESC
        """)
        records = db.cursor.fetchall()

        print("\nRegistros a eliminar:")
        print("-" * 60)
        for r in records:
            titulo = r['titulo'][:40] if r['titulo'] else 'Sin título'
            print(f"  ID: {r['id']} | {titulo} | {r['ciudad']} | {r['fuente']}")
        print("-" * 60)

        # 3. Confirmar eliminación
        confirm = input(f"\n¿Eliminar {total} registro(s)? (s/n): ").strip().lower()

        if confirm != 's':
            print("Operación cancelada.")
            return

        # 4. Obtener IDs de propiedades a eliminar
        db.cursor.execute("""
            SELECT id FROM propiedades
            WHERE fuente = 'Lobbie' OR fuente ILIKE '%lobbie%'
        """)
        prop_ids = [r['id'] for r in db.cursor.fetchall()]

        # 5. Eliminar registros relacionados en eventos_log
        if prop_ids:
            db.cursor.execute("""
                DELETE FROM eventos_log
                WHERE propiedad_id = ANY(%s)
            """, (prop_ids,))
            eventos_deleted = db.cursor.rowcount
            print(f"\n🗑️  {eventos_deleted} registro(s) de eventos_log eliminados.")

            # 6. Eliminar registros relacionados en interacciones (si existe)
            try:
                db.cursor.execute("""
                    DELETE FROM interacciones
                    WHERE propiedad_id = ANY(%s)
                """, (prop_ids,))
                interacciones_deleted = db.cursor.rowcount
                if interacciones_deleted > 0:
                    print(f"🗑️  {interacciones_deleted} registro(s) de interacciones eliminados.")
            except Exception:
                pass  # Tabla puede no existir o no tener FK

        # 7. Eliminar propiedades
        db.cursor.execute("""
            DELETE FROM propiedades
            WHERE fuente = 'Lobbie' OR fuente ILIKE '%lobbie%'
        """)
        deleted = db.cursor.rowcount
        db.conn.commit()

        print(f"✅ {deleted} propiedad(es) eliminada(s) exitosamente.")


if __name__ == "__main__":
    main()
