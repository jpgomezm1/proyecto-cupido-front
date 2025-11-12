#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para probar la conexión con Neon PostgreSQL
"""

import os
from dotenv import load_dotenv

print("=" * 60)
print("  TEST DE CONEXIÓN - NEON POSTGRESQL")
print("=" * 60)
print()

# Cargar variables de entorno
load_dotenv()

# Verificar que .env existe
if not os.path.exists('.env'):
    print("❌ Archivo .env no encontrado")
    print()
    print("Pasos para configurar:")
    print("1. cp .env.example .env")
    print("2. Editar .env y agregar tu DATABASE_URL de Neon")
    print()
    exit(1)

print("✅ Archivo .env encontrado")

# Verificar que DATABASE_URL está definida
database_url = os.getenv('DATABASE_URL')
if not database_url:
    print("❌ DATABASE_URL no está definida en .env")
    print()
    print("Edita el archivo .env y agrega:")
    print("DATABASE_URL=postgresql://tu_usuario:tu_password@host/database")
    print()
    exit(1)

print("✅ DATABASE_URL encontrada")
print(f"   Host: {database_url.split('@')[1].split('/')[0] if '@' in database_url else 'N/A'}")
print()

# Probar importación de módulos
print("Verificando módulos de Python...")
try:
    import psycopg2
    print("✅ psycopg2 instalado")
except ImportError:
    print("❌ psycopg2 NO instalado")
    print("   Instala con: pip install psycopg2-binary")
    exit(1)

try:
    from database import DatabaseManager
    print("✅ database.py encontrado")
except ImportError:
    print("❌ database.py NO encontrado")
    exit(1)

print()

# Probar conexión
print("Probando conexión a Neon PostgreSQL...")
try:
    db = DatabaseManager()
    if db.connect():
        print("✅ Conexión exitosa a Neon PostgreSQL")
        print()

        # Verificar/crear tablas
        print("Creando/verificando tablas...")
        if db.create_tables():
            print("✅ Tablas verificadas correctamente")
        else:
            print("⚠️  Error al crear tablas (revisar schema.sql)")

        print()

        # Obtener estadísticas
        print("Obteniendo estadísticas de la base de datos...")
        stats = db.get_statistics()

        print(f"\n📊 ESTADÍSTICAS:")
        print(f"   • Total propiedades: {stats.get('total_propiedades', 0)}")

        if stats.get('por_fuente'):
            print(f"   • Por fuente:")
            for fuente, total in stats['por_fuente'].items():
                print(f"     - {fuente}: {total}")

        if stats.get('por_ciudad'):
            print(f"   • Top 5 ciudades:")
            for i, (ciudad, total) in enumerate(list(stats['por_ciudad'].items())[:5], 1):
                print(f"     {i}. {ciudad}: {total}")

        if stats.get('precios', {}).get('promedio'):
            print(f"   • Precio promedio: ${stats['precios']['promedio']:,.0f} COP")

        # Cerrar conexión
        db.disconnect()
        print()
        print("=" * 60)
        print("✅ TEST COMPLETADO EXITOSAMENTE")
        print("=" * 60)
        print()
        print("Puedes ejecutar el scraper con:")
        print("  python scrapper_wasi.py")
        print()

    else:
        print("❌ No se pudo conectar a la base de datos")
        print()
        print("Verifica:")
        print("1. Que DATABASE_URL sea correcta")
        print("2. Que Neon esté activo (no en sleep)")
        print("3. Que tengas conexión a internet")

except Exception as e:
    print(f"❌ Error durante el test: {e}")
    print()
    print("Revisa:")
    print("1. DATABASE_URL en .env")
    print("2. Conexión a internet")
    print("3. Estado del proyecto en Neon")
