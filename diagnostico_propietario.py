#!/usr/bin/env python3
"""Diagnóstico de propietarios de propiedades"""

import os
from dotenv import load_dotenv
load_dotenv()

from src.db.database import DatabaseManager

db = DatabaseManager()
db.connect()

print("=" * 60)
print("DIAGNÓSTICO DE PROPIETARIOS")
print("=" * 60)

# 1. Ver últimas 5 propiedades
print("\n📋 ÚLTIMAS 5 PROPIEDADES:")
db.cursor.execute("""
    SELECT id, codigo_propiedad, titulo, agente_captador_telefono, fuente, fecha_creacion
    FROM propiedades 
    ORDER BY fecha_creacion DESC 
    LIMIT 5
""")
for row in db.cursor.fetchall():
    print(f"  ID: {row['id']}")
    print(f"  Código: {row['codigo_propiedad']}")
    print(f"  Título: {row['titulo'][:50] if row['titulo'] else 'N/A'}...")
    print(f"  Agente Captador Tel: {row['agente_captador_telefono'] or 'NULL ❌'}")
    print(f"  Fuente: {row['fuente']}")
    print(f"  Fecha: {row['fecha_creacion']}")
    print("-" * 40)

# 2. Ver agentes
print("\n👥 AGENTES EN LA DB:")
db.cursor.execute("""
    SELECT id, telefono, nombre, fecha_registro
    FROM agentes 
    ORDER BY fecha_registro DESC 
    LIMIT 10
""")
for row in db.cursor.fetchall():
    print(f"  ID: {row['id']} | Tel: {row['telefono']} | Nombre: {row['nombre'] or 'NULL ❌'}")

# 3. Verificar JOIN
print("\n🔗 VERIFICAR JOIN (últimas 5 propiedades con agente):")
db.cursor.execute("""
    SELECT 
        p.id,
        p.codigo_propiedad,
        p.agente_captador_telefono,
        a.nombre as owner_name,
        a.telefono as agente_telefono
    FROM propiedades p
    LEFT JOIN agentes a ON a.telefono = p.agente_captador_telefono
    ORDER BY p.fecha_creacion DESC
    LIMIT 5
""")
for row in db.cursor.fetchall():
    print(f"  Propiedad ID: {row['id']} | Código: {row['codigo_propiedad']}")
    print(f"    -> agente_captador_telefono: {row['agente_captador_telefono'] or 'NULL'}")
    print(f"    -> JOIN agente.telefono: {row['agente_telefono'] or 'NULL'}")
    print(f"    -> owner_name: {row['owner_name'] or 'NULL'}")
    print("-" * 40)

db.disconnect()
