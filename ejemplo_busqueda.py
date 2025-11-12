#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ejemplo simple de uso del sistema de búsqueda inteligente
"""

import os
from busqueda_propiedades import PropertySearchAgent

# Verificar que existe la API key
if not os.getenv('ANTHROPIC_API_KEY'):
    print("❌ Error: Configura ANTHROPIC_API_KEY en el archivo .env")
    print()
    print("1. Obtén tu API key en: https://console.anthropic.com/")
    print("2. Agrega a .env:")
    print("   ANTHROPIC_API_KEY=tu_api_key_aqui")
    print()
    exit(1)

print("=" * 80)
print("  EJEMPLO DE BÚSQUEDA INTELIGENTE")
print("=" * 80)
print()

# Crear el agente
agent = PropertySearchAgent()

# Ejemplo de consulta (puedes cambiarla)
consulta = """
Busco apartamento para cliente en Laureles o El Poblado
Hasta 800 millones
2 o 3 habitaciones
Con gimnasio y piscina si es posible
Es urgente!
"""

print("📝 Consulta del agente:")
print(consulta)
print()

# Realizar búsqueda
print("🔍 Buscando propiedades...")
print()

resultados = agent.search(consulta, limit=5)

# Mostrar resultados formateados
print()
mensaje = agent.format_results_for_agent(resultados)
print(mensaje)

# Guardar resultados en JSON
if resultados.get('success'):
    import json
    from datetime import datetime

    archivo = f"ejemplo_resultado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(archivo, 'w', encoding='utf-8') as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)

    print()
    print(f"💾 Resultados guardados en: {archivo}")
    print()
