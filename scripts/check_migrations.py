#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para verificar y ejecutar migraciones de base de datos.

Uso:
    python scripts/check_migrations.py          # Ver estado de migraciones
    python scripts/check_migrations.py --run    # Ejecutar migraciones pendientes
    python scripts/check_migrations.py --force <nombre>  # Forzar una migración específica

Este script NO se debe subir al repositorio (está en .gitignore).
"""

import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración
MIGRATIONS_DIR = Path(__file__).parent.parent / "db" / "migrations"
DATABASE_URL = os.getenv("DATABASE_URL")

# Colores para output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def get_connection():
    """Obtiene conexión a la base de datos."""
    if not DATABASE_URL:
        print(f"{Colors.RED}Error: DATABASE_URL no está configurada en .env{Colors.END}")
        sys.exit(1)
    return psycopg2.connect(DATABASE_URL)


def ensure_migrations_table(conn):
    """Crea la tabla de seguimiento de migraciones si no existe."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id SERIAL PRIMARY KEY,
                migration_name VARCHAR(255) NOT NULL UNIQUE,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                checksum VARCHAR(64),
                execution_time_ms INTEGER
            );

            COMMENT ON TABLE schema_migrations IS 'Registro de migraciones aplicadas a la base de datos';
        """)
        conn.commit()


def get_applied_migrations(conn):
    """Obtiene lista de migraciones ya aplicadas."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT migration_name, applied_at
            FROM schema_migrations
            ORDER BY applied_at
        """)
        return {row[0]: row[1] for row in cur.fetchall()}


def get_migration_files():
    """Obtiene lista de archivos de migración ordenados."""
    if not MIGRATIONS_DIR.exists():
        print(f"{Colors.RED}Error: Directorio de migraciones no encontrado: {MIGRATIONS_DIR}{Colors.END}")
        return []

    migrations = []
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        migrations.append(f.name)
    return migrations


def calculate_checksum(content: str) -> str:
    """Calcula checksum MD5 del contenido."""
    import hashlib
    return hashlib.md5(content.encode()).hexdigest()


def show_status(conn):
    """Muestra el estado de las migraciones."""
    applied = get_applied_migrations(conn)
    files = get_migration_files()

    print(f"\n{Colors.BOLD}{'=' * 70}{Colors.END}")
    print(f"{Colors.BOLD}  ESTADO DE MIGRACIONES - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.END}")
    print(f"{Colors.BOLD}{'=' * 70}{Colors.END}\n")

    pending_count = 0
    applied_count = 0

    for migration in files:
        if migration in applied:
            applied_at = applied[migration].strftime("%Y-%m-%d %H:%M")
            print(f"  {Colors.GREEN}✓{Colors.END} {migration}")
            print(f"    {Colors.BLUE}Aplicada: {applied_at}{Colors.END}")
            applied_count += 1
        else:
            print(f"  {Colors.YELLOW}○{Colors.END} {migration}")
            print(f"    {Colors.YELLOW}Pendiente{Colors.END}")
            pending_count += 1

    print(f"\n{Colors.BOLD}{'=' * 70}{Colors.END}")
    print(f"  Total: {len(files)} | {Colors.GREEN}Aplicadas: {applied_count}{Colors.END} | {Colors.YELLOW}Pendientes: {pending_count}{Colors.END}")
    print(f"{Colors.BOLD}{'=' * 70}{Colors.END}\n")

    return pending_count


def run_migration(conn, migration_name: str, force: bool = False):
    """Ejecuta una migración específica."""
    migration_path = MIGRATIONS_DIR / migration_name

    if not migration_path.exists():
        print(f"{Colors.RED}Error: Migración no encontrada: {migration_name}{Colors.END}")
        return False

    # Verificar si ya fue aplicada
    applied = get_applied_migrations(conn)
    if migration_name in applied and not force:
        print(f"{Colors.YELLOW}Migración ya aplicada: {migration_name}{Colors.END}")
        return True

    # Leer contenido
    content = migration_path.read_text(encoding='utf-8')
    checksum = calculate_checksum(content)

    print(f"\n{Colors.BLUE}Ejecutando: {migration_name}{Colors.END}")
    print(f"  Checksum: {checksum[:16]}...")

    try:
        start_time = datetime.now()

        with conn.cursor() as cur:
            # Ejecutar la migración
            cur.execute(content)

            # Registrar la migración
            if force and migration_name in applied:
                cur.execute("""
                    UPDATE schema_migrations
                    SET applied_at = CURRENT_TIMESTAMP,
                        checksum = %s,
                        execution_time_ms = %s
                    WHERE migration_name = %s
                """, (checksum, int((datetime.now() - start_time).total_seconds() * 1000), migration_name))
            else:
                cur.execute("""
                    INSERT INTO schema_migrations (migration_name, checksum, execution_time_ms)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (migration_name) DO UPDATE
                    SET applied_at = CURRENT_TIMESTAMP,
                        checksum = EXCLUDED.checksum,
                        execution_time_ms = EXCLUDED.execution_time_ms
                """, (migration_name, checksum, int((datetime.now() - start_time).total_seconds() * 1000)))

        conn.commit()
        elapsed = (datetime.now() - start_time).total_seconds() * 1000
        print(f"  {Colors.GREEN}✓ Completada en {elapsed:.0f}ms{Colors.END}")
        return True

    except Exception as e:
        conn.rollback()
        print(f"  {Colors.RED}✗ Error: {e}{Colors.END}")
        return False


def run_pending_migrations(conn):
    """Ejecuta todas las migraciones pendientes."""
    applied = get_applied_migrations(conn)
    files = get_migration_files()

    pending = [f for f in files if f not in applied]

    if not pending:
        print(f"\n{Colors.GREEN}No hay migraciones pendientes.{Colors.END}\n")
        return True

    print(f"\n{Colors.BOLD}Ejecutando {len(pending)} migración(es) pendiente(s)...{Colors.END}")

    success_count = 0
    for migration in pending:
        if run_migration(conn, migration):
            success_count += 1
        else:
            print(f"\n{Colors.RED}Ejecución detenida debido a error.{Colors.END}")
            break

    print(f"\n{Colors.BOLD}Resultado: {success_count}/{len(pending)} migraciones aplicadas{Colors.END}\n")
    return success_count == len(pending)


def verify_tables(conn):
    """Verifica que las tablas principales existan."""
    print(f"\n{Colors.BOLD}Verificando tablas principales...{Colors.END}\n")

    tables_to_check = [
        'propiedades',
        'agentes',
        'conversaciones_busqueda',
        'mensajes_conversacion',
        'chat_users',
        'ai_usage_log',
        'deals',
        'schema_migrations'
    ]

    with conn.cursor() as cur:
        for table in tables_to_check:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = %s
                )
            """, (table,))
            exists = cur.fetchone()[0]

            if exists:
                # Contar registros
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cur.fetchone()[0]
                    print(f"  {Colors.GREEN}✓{Colors.END} {table}: {count:,} registros")
                except:
                    print(f"  {Colors.GREEN}✓{Colors.END} {table}: existe")
            else:
                print(f"  {Colors.RED}✗{Colors.END} {table}: NO EXISTE")

    print()


def list_all_tables(conn):
    """Lista todas las tablas en la base de datos."""
    print(f"\n{Colors.BOLD}Todas las tablas en la base de datos:{Colors.END}\n")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = cur.fetchall()

        for table in tables:
            table_name = table[0]
            try:
                cur.execute(f"SELECT COUNT(*) FROM \"{table_name}\"")
                count = cur.fetchone()[0]
                print(f"  {Colors.BLUE}•{Colors.END} {table_name}: {count:,} registros")
            except:
                print(f"  {Colors.BLUE}•{Colors.END} {table_name}")

    print(f"\n  Total: {len(tables)} tablas\n")


def mark_as_applied(conn, migration_name: str):
    """Marca una migración como aplicada sin ejecutarla (para migraciones ya existentes)."""
    migration_path = MIGRATIONS_DIR / migration_name

    if not migration_path.exists():
        print(f"{Colors.RED}Error: Migración no encontrada: {migration_name}{Colors.END}")
        return False

    content = migration_path.read_text(encoding='utf-8')
    checksum = calculate_checksum(content)

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO schema_migrations (migration_name, checksum, execution_time_ms)
            VALUES (%s, %s, 0)
            ON CONFLICT (migration_name) DO NOTHING
        """, (migration_name, checksum))
        conn.commit()

    print(f"  {Colors.GREEN}✓{Colors.END} Marcada como aplicada: {migration_name}")
    return True


def mark_existing_migrations(conn):
    """Marca las migraciones existentes como aplicadas basándose en las tablas que ya existen."""
    print(f"\n{Colors.BOLD}Detectando migraciones ya aplicadas...{Colors.END}\n")

    # Mapeo de migraciones a tablas que crean (nombres reales en DB)
    migration_table_map = {
        '003_vector_search.sql': ['property_embeddings'],
        '004_deals_module.sql': ['deals', 'deal_documentos', 'deal_actividades'],
        '005_conversations.sql': ['conversaciones_busqueda', 'mensajes_conversacion'],
        '006_chat_users.sql': ['chat_users'],
        '007_trigram_search.sql': [],  # Solo crea extensión e índices
        '008_fix_conversations_user_id.sql': [],  # Solo modifica columna
        '009_chat_favorites.sql': ['chat_user_favorites'],
        '010_ai_usage_tracking.sql': ['ai_usage_log'],
        'add_descripcion_ai.sql': [],  # Solo agrega columnas
        'add_validation_fields.sql': [],  # Solo agrega columnas
    }

    marked_count = 0

    with conn.cursor() as cur:
        for migration, tables in migration_table_map.items():
            # Si la migración no tiene tablas específicas, verificar si ya está en schema_migrations
            if not tables:
                # Marcar directamente las que no crean tablas nuevas
                mark_as_applied(conn, migration)
                marked_count += 1
                continue

            # Verificar si alguna de las tablas existe
            all_exist = True
            for table in tables:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = %s
                    )
                """, (table,))
                if not cur.fetchone()[0]:
                    all_exist = False
                    break

            if all_exist:
                mark_as_applied(conn, migration)
                marked_count += 1

    print(f"\n  {Colors.GREEN}Marcadas: {marked_count} migraciones{Colors.END}\n")


def main():
    parser = argparse.ArgumentParser(description='Gestión de migraciones de base de datos')
    parser.add_argument('--run', action='store_true', help='Ejecutar migraciones pendientes')
    parser.add_argument('--force', metavar='MIGRATION', help='Forzar ejecución de una migración específica')
    parser.add_argument('--verify', action='store_true', help='Verificar tablas principales')
    parser.add_argument('--list', action='store_true', help='Listar todas las tablas')
    parser.add_argument('--mark-existing', action='store_true', help='Marcar migraciones existentes como aplicadas')

    args = parser.parse_args()

    try:
        conn = get_connection()
        ensure_migrations_table(conn)

        if args.force:
            run_migration(conn, args.force, force=True)
        elif args.run:
            run_pending_migrations(conn)
        elif args.list:
            list_all_tables(conn)
        elif args.mark_existing:
            mark_existing_migrations(conn)
            show_status(conn)
        elif args.verify:
            verify_tables(conn)
        else:
            show_status(conn)
            verify_tables(conn)

        conn.close()

    except psycopg2.OperationalError as e:
        print(f"\n{Colors.RED}Error de conexión a la base de datos:{Colors.END}")
        print(f"  {e}")
        print(f"\n{Colors.YELLOW}Verifica que DATABASE_URL esté correctamente configurada en .env{Colors.END}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}Error inesperado: {e}{Colors.END}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
