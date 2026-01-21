#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para ejecutar migraciones de base de datos.
Ejecuta todos los archivos SQL en db/migrations/ en orden numérico.
Trackea las migraciones aplicadas en una tabla 'schema_migrations'.
"""

import os
import sys
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.database import DatabaseManager
from dotenv import load_dotenv

load_dotenv()

MIGRATIONS_DIR = Path(__file__).parent.parent / "db" / "migrations"


def get_applied_migrations(db):
    """Obtiene lista de migraciones ya aplicadas."""
    # Crear tabla de migraciones si no existe
    db.cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id SERIAL PRIMARY KEY,
            migration_name VARCHAR(255) NOT NULL UNIQUE,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.conn.commit()

    db.cursor.execute("SELECT migration_name FROM schema_migrations ORDER BY migration_name")
    return {row['migration_name'] for row in db.cursor.fetchall()}


def get_pending_migrations():
    """Obtiene lista de archivos de migración pendientes."""
    if not MIGRATIONS_DIR.exists():
        print(f"[ERROR] Directorio de migraciones no encontrado: {MIGRATIONS_DIR}")
        return []

    migrations = []
    for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        migrations.append(file.name)

    return migrations


def run_migration(db, migration_name):
    """Ejecuta una migración específica."""
    migration_path = MIGRATIONS_DIR / migration_name

    print(f"\n{'='*60}")
    print(f"[RUNNING] {migration_name}")
    print('='*60)

    try:
        with open(migration_path, 'r', encoding='utf-8') as f:
            sql = f.read()

        # Ejecutar el SQL
        db.cursor.execute(sql)

        # Registrar la migración como aplicada
        db.cursor.execute(
            "INSERT INTO schema_migrations (migration_name) VALUES (%s)",
            (migration_name,)
        )
        db.conn.commit()

        print(f"[OK] {migration_name} aplicada correctamente")
        return True

    except Exception as e:
        db.conn.rollback()
        print(f"[ERROR] Error en {migration_name}: {e}")
        return False


def main():
    print("\n" + "="*60)
    print("   MIGRATION RUNNER - Proyecto Cupido")
    print("="*60)

    # Obtener todas las migraciones disponibles
    all_migrations = get_pending_migrations()

    if not all_migrations:
        print("\n[INFO] No hay archivos de migración en db/migrations/")
        return

    print(f"\n[INFO] Migraciones encontradas: {len(all_migrations)}")

    with DatabaseManager() as db:
        # Obtener migraciones ya aplicadas
        applied = get_applied_migrations(db)
        print(f"[INFO] Migraciones ya aplicadas: {len(applied)}")

        # Filtrar las pendientes
        pending = [m for m in all_migrations if m not in applied]

        if not pending:
            print("\n[OK] La base de datos está al día. No hay migraciones pendientes.")
            print("\nMigraciones aplicadas:")
            for m in sorted(applied):
                print(f"  ✓ {m}")
            return

        print(f"\n[INFO] Migraciones pendientes: {len(pending)}")
        for m in pending:
            print(f"  → {m}")

        # Confirmar ejecución
        print("\n" + "-"*60)
        response = input("¿Ejecutar migraciones pendientes? (s/N): ").strip().lower()

        if response != 's':
            print("\n[CANCELLED] Operación cancelada por el usuario.")
            return

        # Ejecutar migraciones
        success_count = 0
        fail_count = 0

        for migration in pending:
            if run_migration(db, migration):
                success_count += 1
            else:
                fail_count += 1
                print(f"\n[STOP] Deteniendo ejecución debido a error en {migration}")
                break

        # Resumen
        print("\n" + "="*60)
        print("   RESUMEN")
        print("="*60)
        print(f"  Exitosas: {success_count}")
        print(f"  Fallidas: {fail_count}")
        print(f"  Total:    {success_count + fail_count}/{len(pending)}")

        if fail_count == 0:
            print("\n[OK] Todas las migraciones se aplicaron correctamente!")
        else:
            print("\n[WARNING] Algunas migraciones fallaron. Revisa los errores arriba.")


if __name__ == "__main__":
    main()
