#!/usr/bin/env python3
"""Test directo del query de la API"""

import os
from dotenv import load_dotenv
load_dotenv()

from src.db.database import DatabaseManager

db = DatabaseManager()
db.connect()

# Este es el MISMO query que usa la API
slug = "9611087"  # La última propiedad

query = """
    SELECT
        p.id,
        p.codigo_propiedad as slug,
        p.titulo as title,
        p.agente_captador_telefono as owner_phone,
        p.grupo_origen as source_group,
        a.nombre as owner_name
    FROM propiedades p
    LEFT JOIN agentes a ON a.telefono = p.agente_captador_telefono
    WHERE p.codigo_propiedad = %s AND p.activa = true
"""

db.cursor.execute(query, (slug,))
result = db.cursor.fetchone()

print("=" * 60)
print(f"QUERY PARA PROPIEDAD: {slug}")
print("=" * 60)

if result:
    print(f"✅ Propiedad encontrada:")
    print(f"   id: {result['id']}")
    print(f"   slug: {result['slug']}")
    print(f"   title: {result['title'][:50] if result['title'] else 'N/A'}...")
    print(f"   owner_phone: {result['owner_phone']}")
    print(f"   owner_name: {result['owner_name']}")
    print(f"   source_group: {result['source_group']}")
else:
    print("❌ Propiedad NO encontrada")

db.disconnect()
