#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para ejecutar migraciones SQL usando la conexión de la aplicación
"""

import sys
import os
import io

# Configurar UTF-8 para evitar errores de encoding en Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.db.database import DatabaseManager


def run_migration(migration_file: str):
    """Ejecuta un archivo de migración SQL"""

    # Verificar que el archivo existe
    if not os.path.exists(migration_file):
        print(f"[ERROR] Archivo no encontrado: {migration_file}")
        return False

    print(f"[INFO] Leyendo migracion: {migration_file}")

    with open(migration_file, 'r', encoding='utf-8') as f:
        sql = f.read()

    print("[INFO] Ejecutando migracion...")

    db = None
    try:
        db = DatabaseManager()
        db.connect()

        # Ejecutar el SQL completo
        db.cursor.execute(sql)
        db.conn.commit()

        db.disconnect()
        print("[OK] Migracion ejecutada correctamente")
        return True

    except Exception as e:
        print(f"[ERROR] Error ejecutando migracion: {e}")
        if db and db.conn:
            db.conn.rollback()
            db.disconnect()
        return False


def main():
    # Migración por defecto o desde argumento
    if len(sys.argv) > 1:
        migration_file = sys.argv[1]
    else:
        # Migración de conversaciones
        migration_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'db', 'migrations', '005_conversations.sql'
        )

    print("=" * 60)
    print("EJECUTOR DE MIGRACIONES")
    print("=" * 60)

    success = run_migration(migration_file)

    if success:
        print("\n[DONE] Migracion completada exitosamente")
    else:
        print("\n[FAIL] La migracion fallo")
        sys.exit(1)


if __name__ == '__main__':
    main()
