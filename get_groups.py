#!/usr/bin/env python3
"""Script para obtener los grupos de WhatsApp de UltraMSG"""

import requests

INSTANCE_ID = "instance57259"
TOKEN = "vz3m8h4w90l0gdhi"
BUSCAR = "Pruebas Fynder"  # Grupo a buscar

url = f"https://api.ultramsg.com/{INSTANCE_ID}/groups?token={TOKEN}"

response = requests.get(url)
groups = response.json()

print(f"\n{'='*50}")
print(f"Buscando grupo: '{BUSCAR}'")
print(f"{'='*50}\n")

encontrado = None
for group in groups:
    nombre = group.get('name', '')
    if BUSCAR.lower() in nombre.lower():
        encontrado = group
        print(f"ENCONTRADO!")
        print(f"Nombre: {nombre}")
        print(f"ID: {group.get('id')}")
        break

if not encontrado:
    print(f"No se encontro el grupo '{BUSCAR}'")
    print(f"\nGrupos disponibles:")
    for g in groups:
        print(f"  - {g.get('name')}")
