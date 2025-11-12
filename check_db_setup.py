#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script rápido para verificar qué falta para la integración con DB
"""

import sys

print("=" * 60)
print("  VERIFICACIÓN DE SETUP DE BASE DE DATOS")
print("=" * 60)
print()

# 1. Verificar archivo .env
print("1. Verificando archivo .env...")
try:
    with open('.env', 'r') as f:
        content = f.read()
        if 'DATABASE_URL=' in content and 'postgresql://' in content:
            print("   ✅ Archivo .env encontrado y contiene DATABASE_URL")
        else:
            print("   ⚠️  Archivo .env encontrado pero DATABASE_URL no está configurada")
            print("   Edita .env y agrega: DATABASE_URL=postgresql://...")
except FileNotFoundError:
    print("   ❌ Archivo .env NO encontrado")
    print("   Crea uno con: cp .env.example .env")
    print("   Luego edita y agrega tu DATABASE_URL de Neon")

print()

# 2. Verificar python-dotenv
print("2. Verificando python-dotenv...")
try:
    import dotenv
    print("   ✅ python-dotenv instalado")
except ImportError:
    print("   ❌ python-dotenv NO instalado")
    print("   Instala con: pip install python-dotenv")

print()

# 3. Verificar psycopg2
print("3. Verificando psycopg2-binary...")
try:
    import psycopg2
    print("   ✅ psycopg2-binary instalado")
except ImportError:
    print("   ❌ psycopg2-binary NO instalado")
    print("   Instala con: pip install psycopg2-binary")

print()

# 4. Verificar database.py
print("4. Verificando módulo database.py...")
try:
    import database
    print("   ✅ database.py encontrado y se puede importar")
except ImportError as e:
    print(f"   ❌ Error al importar database.py: {e}")
    print("   Verifica que database.py esté en la misma carpeta")
except Exception as e:
    print(f"   ⚠️  database.py encontrado pero hay un error: {e}")

print()

# 5. Intentar importar la función específica
print("5. Verificando función save_properties_to_db...")
try:
    from database import save_properties_to_db
    print("   ✅ Función save_properties_to_db disponible")
except ImportError as e:
    print(f"   ❌ No se pudo importar: {e}")
except Exception as e:
    print(f"   ⚠️  Error: {e}")

print()

# 6. Verificar conexión si todo está OK
print("6. Probando conexión a Neon (si todo lo anterior está OK)...")
try:
    from database import DatabaseManager
    db = DatabaseManager()
    if db.connect():
        print("   ✅ Conexión exitosa a Neon PostgreSQL!")
        db.disconnect()
    else:
        print("   ❌ No se pudo conectar a Neon")
        print("   Verifica DATABASE_URL en .env")
except Exception as e:
    print(f"   ⚠️  Error: {e}")

print()
print("=" * 60)
print()

# Resumen
print("📋 RESUMEN:")
print()
print("Para que el guardado en DB funcione necesitas:")
print("  ✓ Archivo .env con DATABASE_URL configurada")
print("  ✓ pip install python-dotenv")
print("  ✓ pip install psycopg2-binary")
print("  ✓ Tablas creadas en Neon (ejecutar schema.sql)")
print()
print("Luego ejecuta: python scrapper_wasi.py")
print()
