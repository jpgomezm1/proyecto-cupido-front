#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para limpiar propiedades que no son propias de la base de datos
"""

import sys
import os

# Configurar encoding para Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Agregar el directorio raiz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.database import DatabaseManager


def main():
    db = None
    try:
        db = DatabaseManager()
        db.connect()
        print("[OK] Conectado a la base de datos\n")

        # 1. Ver distribucion actual por fuente
        print("=" * 60)
        print("DISTRIBUCION ACTUAL DE PROPIEDADES POR FUENTE")
        print("=" * 60)

        db.cursor.execute("""
            SELECT
                fuente,
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE activa = true) as activas
            FROM propiedades
            GROUP BY fuente
            ORDER BY total DESC
        """)

        sources = db.cursor.fetchall()
        total_props = 0
        propias = 0

        for row in sources:
            fuente = row['fuente'] or 'NULL'
            total = row['total']
            activas = row['activas']
            total_props += total

            if fuente.lower() == 'propia':
                propias = total
                print(f"  [MANTENER] {fuente}: {total} ({activas} activas)")
            else:
                print(f"  [ELIMINAR] {fuente}: {total} ({activas} activas)")

        print("-" * 60)
        print(f"  TOTAL: {total_props} propiedades")
        print(f"  A MANTENER: {propias} propiedades (fuente = 'Propia')")
        print(f"  A ELIMINAR: {total_props - propias} propiedades")
        print("=" * 60)

        if total_props - propias == 0:
            print("\n[OK] No hay propiedades que eliminar.")
            return

        # 2. Eliminar SIN confirmar (el usuario ya confirmo en el chat)
        print("\n[...] Eliminando propiedades...")

        # Primero eliminar registros relacionados si existen
        db.cursor.execute("""
            DELETE FROM interacciones
            WHERE propiedad_id IN (
                SELECT id FROM propiedades WHERE LOWER(fuente) != 'propia' OR fuente IS NULL
            )
        """)
        interacciones_deleted = db.cursor.rowcount
        print(f"   - Interacciones eliminadas: {interacciones_deleted}")

        # Eliminar eventos_log relacionados
        db.cursor.execute("""
            DELETE FROM eventos_log
            WHERE propiedad_id IN (
                SELECT id FROM propiedades WHERE LOWER(fuente) != 'propia' OR fuente IS NULL
            )
        """)
        eventos_deleted = db.cursor.rowcount
        print(f"   - Eventos log eliminados: {eventos_deleted}")

        # Eliminar deals relacionados
        db.cursor.execute("""
            DELETE FROM deals
            WHERE propiedad_id IN (
                SELECT id FROM propiedades WHERE LOWER(fuente) != 'propia' OR fuente IS NULL
            )
        """)
        deals_deleted = db.cursor.rowcount
        print(f"   - Deals eliminados: {deals_deleted}")

        # Eliminar propiedades
        db.cursor.execute("""
            DELETE FROM propiedades
            WHERE LOWER(fuente) != 'propia' OR fuente IS NULL
        """)
        props_deleted = db.cursor.rowcount

        # Confirmar transaccion
        db.conn.commit()

        print(f"   - Propiedades eliminadas: {props_deleted}")
        print("\n[OK] Limpieza completada exitosamente!")

        # 4. Mostrar estado final
        print("\n" + "=" * 60)
        print("ESTADO FINAL DE LA BASE DE DATOS")
        print("=" * 60)

        db.cursor.execute("""
            SELECT
                fuente,
                COUNT(*) as total
            FROM propiedades
            GROUP BY fuente
            ORDER BY total DESC
        """)

        final_sources = db.cursor.fetchall()
        if final_sources:
            for row in final_sources:
                print(f"  {row['fuente']}: {row['total']} propiedades")
        else:
            print("  (Base de datos vacia)")

        db.cursor.execute("SELECT COUNT(*) as total FROM propiedades")
        final_total = db.cursor.fetchone()['total']
        print(f"\n  TOTAL FINAL: {final_total} propiedades")
        print("=" * 60)

    except Exception as e:
        print(f"\n[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        if db and db.conn:
            db.conn.rollback()
    finally:
        if db:
            db.disconnect()


if __name__ == "__main__":
    main()
