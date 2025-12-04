#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script rápido para probar qué modelo de Claude está disponible
"""

import os
from dotenv import load_dotenv

load_dotenv()

try:
    import anthropic
except ImportError:
    print("❌ Módulo anthropic no instalado")
    print("Ejecuta: pip install anthropic")
    exit(1)

api_key = os.getenv('ANTHROPIC_API_KEY')
if not api_key:
    print("❌ ANTHROPIC_API_KEY no configurada en .env")
    exit(1)

print(f"✅ API Key encontrada: {api_key[:20]}...")
print()

client = anthropic.Anthropic(api_key=api_key)

# Lista de modelos a probar
modelos = [
    "claude-3-5-sonnet-20241022",
    "claude-3-5-sonnet-20240620",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
    "claude-3-haiku-20240307"
]

print("🔍 Probando modelos disponibles...")
print()

modelo_disponible = None

for modelo in modelos:
    try:
        print(f"Probando: {modelo}...", end=" ")
        response = client.messages.create(
            model=modelo,
            max_tokens=10,
            messages=[{"role": "user", "content": "test"}]
        )
        print("✅ DISPONIBLE")
        if not modelo_disponible:
            modelo_disponible = modelo
    except anthropic.NotFoundError:
        print("❌ No encontrado")
    except Exception as e:
        print(f"⚠️  Error: {e}")
        if not modelo_disponible:
            modelo_disponible = modelo

print()
if modelo_disponible:
    print(f"✅ Modelo recomendado: {modelo_disponible}")
else:
    print("❌ No se pudo detectar ningún modelo disponible")
