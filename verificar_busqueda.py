#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para verificar que el sistema de búsqueda está correctamente configurado
"""

import os
import sys
from dotenv import load_dotenv

print("=" * 80)
print("  VERIFICACIÓN DEL SISTEMA DE BÚSQUEDA INTELIGENTE")
print("=" * 80)
print()

# Cargar variables de entorno
load_dotenv()

# Verificaciones
errores = []
advertencias = []
exitos = []

# 1. Verificar archivo .env
print("1️⃣  Verificando archivo .env...")
if os.path.exists('.env'):
    exitos.append("✅ Archivo .env existe")
else:
    errores.append("❌ Archivo .env no encontrado")
    print("   Crea el archivo .env copiando .env.example")

# 2. Verificar DATABASE_URL
print("2️⃣  Verificando DATABASE_URL...")
database_url = os.getenv('DATABASE_URL')
if database_url:
    if 'neon' in database_url or 'postgres' in database_url:
        exitos.append("✅ DATABASE_URL configurada")
    else:
        advertencias.append("⚠️  DATABASE_URL no parece ser de Neon/PostgreSQL")
else:
    errores.append("❌ DATABASE_URL no configurada en .env")

# 3. Verificar ANTHROPIC_API_KEY
print("3️⃣  Verificando ANTHROPIC_API_KEY...")
api_key = os.getenv('ANTHROPIC_API_KEY')
if api_key:
    if api_key.startswith('sk-ant-'):
        exitos.append("✅ ANTHROPIC_API_KEY configurada (formato correcto)")
    elif api_key == 'tu_api_key_aqui':
        errores.append("❌ ANTHROPIC_API_KEY es el valor por defecto, cámbiala por tu API key real")
    else:
        advertencias.append("⚠️  ANTHROPIC_API_KEY configurada pero formato inusual")
else:
    errores.append("❌ ANTHROPIC_API_KEY no configurada en .env")
    print("   Obtén tu API key en: https://console.anthropic.com/")

# 4. Verificar módulo anthropic
print("4️⃣  Verificando módulo anthropic...")
try:
    import anthropic
    exitos.append("✅ Módulo 'anthropic' instalado")

    # Verificar versión
    try:
        version = anthropic.__version__
        exitos.append(f"   Versión: {version}")
    except:
        pass

except ImportError:
    errores.append("❌ Módulo 'anthropic' no instalado")
    print("   Instala con: pip install anthropic")

# 5. Verificar módulo database
print("5️⃣  Verificando módulo database...")
try:
    from database import DatabaseManager
    exitos.append("✅ Módulo 'database' disponible")
except ImportError as e:
    errores.append(f"❌ Error al importar database: {e}")

# 6. Verificar conexión a base de datos
print("6️⃣  Verificando conexión a base de datos...")
if database_url:
    try:
        from database import DatabaseManager
        with DatabaseManager() as db:
            stats = db.get_statistics()
            total = stats.get('total_propiedades', 0)
            exitos.append(f"✅ Conexión exitosa a Neon ({total} propiedades en DB)")

            if total == 0:
                advertencias.append("⚠️  La base de datos está vacía")
                print("   Carga propiedades con: python cargar_pulppo_auto.py")

    except Exception as e:
        errores.append(f"❌ Error al conectar a DB: {e}")
else:
    errores.append("❌ No se puede verificar DB sin DATABASE_URL")

# 7. Verificar archivo de búsqueda
print("7️⃣  Verificando archivo busqueda_propiedades.py...")
if os.path.exists('busqueda_propiedades.py'):
    exitos.append("✅ Script de búsqueda existe")

    # Intentar importar
    try:
        from busqueda_propiedades import PropertySearchAgent
        exitos.append("✅ PropertySearchAgent importable")
    except Exception as e:
        errores.append(f"❌ Error al importar PropertySearchAgent: {e}")
else:
    errores.append("❌ busqueda_propiedades.py no encontrado")

# 8. Verificar que puede crear un agente
print("8️⃣  Verificando creación de agente...")
if api_key and api_key != 'tu_api_key_aqui':
    try:
        from busqueda_propiedades import PropertySearchAgent
        agent = PropertySearchAgent()
        exitos.append("✅ PropertySearchAgent creado correctamente")
    except Exception as e:
        errores.append(f"❌ Error al crear agente: {e}")
else:
    advertencias.append("⚠️  No se puede crear agente sin API key válida")

print()
print("=" * 80)
print("  RESULTADOS")
print("=" * 80)
print()

# Mostrar resultados
if exitos:
    print("✅ ÉXITOS:")
    for exito in exitos:
        print(f"   {exito}")
    print()

if advertencias:
    print("⚠️  ADVERTENCIAS:")
    for advertencia in advertencias:
        print(f"   {advertencia}")
    print()

if errores:
    print("❌ ERRORES:")
    for error in errores:
        print(f"   {error}")
    print()

# Conclusión
print("=" * 80)
if errores:
    print("❌ HAY ERRORES QUE CORREGIR")
    print()
    print("Pasos siguientes:")
    if any('ANTHROPIC_API_KEY' in e for e in errores):
        print("  1. Obtén tu API key en: https://console.anthropic.com/")
        print("  2. Agrégala al archivo .env:")
        print("     ANTHROPIC_API_KEY=sk-ant-api03-xxxxx")
    if any('anthropic' in e for e in errores):
        print("  3. Instala dependencias:")
        print("     pip install anthropic")
    if any('database' in e.lower() for e in errores):
        print("  4. Verifica DATABASE_URL en .env")
    sys.exit(1)
elif advertencias:
    print("⚠️  SISTEMA FUNCIONAL CON ADVERTENCIAS")
    print()
    print("El sistema puede funcionar pero hay algunas advertencias.")
    sys.exit(0)
else:
    print("✅ SISTEMA COMPLETAMENTE CONFIGURADO")
    print()
    print("🚀 Listo para usar!")
    print()
    print("Ejecuta:")
    print("  python busqueda_propiedades.py   # Ejemplo con consultas de prueba")
    print("  python ejemplo_busqueda.py       # Ejemplo simple personalizable")
    print()
    sys.exit(0)
