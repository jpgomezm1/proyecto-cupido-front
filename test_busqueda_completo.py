#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Testing Completo del Sistema de Búsqueda
Genera logs detallados para análisis y mejora del agente
"""

import os
import json
from datetime import datetime
from busqueda_propiedades import PropertySearchAgent
from dotenv import load_dotenv

load_dotenv()

# Verificar configuración
if not os.getenv('ANTHROPIC_API_KEY'):
    print("❌ Error: ANTHROPIC_API_KEY no configurada en .env")
    exit(1)

print("=" * 80)
print("  TEST COMPLETO DEL SISTEMA DE BÚSQUEDA INTELIGENTE")
print("=" * 80)
print()

# Consultas de prueba (casos reales variados)
test_queries = [
    {
        "id": "TEST-001",
        "nombre": "Apartamento Laureles - Presupuesto Alto",
        "query": """Busco apto cliente tu 360 en ciudad del Río o Laureles
Persona mayor primer piso. 2 o 3 habitaciones.
Con portería.
Presupuesto 1000 millones.
Rocío Escudero Vega
3103721706"""
    },
    {
        "id": "TEST-002",
        "nombre": "Apartamento El Poblado - Requisitos Específicos",
        "query": """Busco para una cliente de tu 360inmobiliario
Súper compradora !!!!!!!!

Hasta $800 millones
Apartamento de dos alcobas CADA UNA CON BAÑO.
BALCON
Baño social
Ojalá con un estudio o que la alcoba principal sea amplia
80 m2 o más
Ojalá unidad con piscina
Directo por favor !
LE GUSTA :
Loma de san Julián
Loma del encierro
Castropol
Lalinde

Ma Cecilia Gaviria
3117645997"""
    },
    {
        "id": "TEST-003",
        "nombre": "Apartamento Envigado - Presupuesto Medio",
        "query": """APTO EL TRIANON EL DORADO LA CUENCA LAS ANTILLAS ALCALA

✅500.000 MILLONES
 3 HABITACIONES
Ojala unidad completa

Soy Sandra Echeverri Asesora inmobiliaria
📲Contáctame:
Cel :3235075028"""
    },
    {
        "id": "TEST-004",
        "nombre": "Casa Familiar - Presupuesto Alto",
        "query": """Busco casa para familia grande
El Poblado o Envigado
4 o 5 habitaciones
Garaje para 2 carros
Jardín
Hasta 1.5 billones
Urgente por favor!"""
    },
    {
        "id": "TEST-005",
        "nombre": "Apartamento Pequeño - Presupuesto Bajo",
        "query": """Cliente busca apto pequeño
Laureles, Estadio o Buenos Aires
1 o 2 habitaciones
Hasta 300 millones
Puede ser usado
No importa el piso"""
    },
    {
        "id": "TEST-006",
        "nombre": "Penthouse Lujo - Sin límite presupuesto",
        "query": """Busco penthouse de lujo
El Poblado sector exclusivo
3 habitaciones mínimo
Balcón grande con vista
Gimnasio y piscina en la unidad
Acabados premium
Presupuesto flexible hasta 2 billones"""
    },
    {
        "id": "TEST-007",
        "nombre": "Apartamento Nuevo - Zona Norte",
        "query": """Apto nuevo en Castilla, Robledo o La América
2 habitaciones
1 baño mínimo
Parqueadero
600 millones máximo
Preferiblemente con terraza"""
    },
    {
        "id": "TEST-008",
        "nombre": "Duplex - Sabaneta/Envigado",
        "query": """Cliente quiere duplex
Sabaneta o Envigado
2 o 3 alcobas
Estrato 4 o 5
Hasta 700 millones
Con zona de lavandería"""
    },
    {
        "id": "TEST-009",
        "nombre": "Apartamento Estudiante - Presupuesto Ajustado",
        "query": """Busco para estudiante
Cerca a universidades
1 habitación
Amoblado o sin amoblar
Máximo 250 millones
Laureles, Estadio, La América"""
    },
    {
        "id": "TEST-010",
        "nombre": "Apartamento Inversión - Arriendo",
        "query": """Busco apto para invertir y arrendar
Belén, La América o Robledo
2 habitaciones
Buena zona
Entre 300 y 500 millones
Que tenga buenos acabados para arrendar fácil"""
    }
]

# Crear agente
print("🤖 Inicializando agente de búsqueda...")
try:
    agent = PropertySearchAgent()
except Exception as e:
    print(f"❌ Error al crear agente: {e}")
    exit(1)

print(f"✅ Agente creado exitosamente")
print()

# Timestamp para los logs
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
log_dir = f"test_logs_{timestamp}"
os.makedirs(log_dir, exist_ok=True)

print(f"📁 Logs se guardarán en: {log_dir}/")
print()

# Resultados consolidados
resultados_consolidados = {
    "timestamp": timestamp,
    "total_tests": len(test_queries),
    "tests": []
}

# Ejecutar cada prueba
for i, test_case in enumerate(test_queries, 1):
    test_id = test_case["id"]
    nombre = test_case["nombre"]
    query = test_case["query"]

    print("=" * 80)
    print(f"  TEST {i}/{len(test_queries)}: {test_id} - {nombre}")
    print("=" * 80)
    print()

    print(f"📝 Consulta:")
    print(f"{query[:150]}..." if len(query) > 150 else query)
    print()

    # Ejecutar búsqueda (siempre 5 resultados)
    try:
        resultado = agent.search(query, limit=5)

        # Agregar metadatos del test
        resultado['test_id'] = test_id
        resultado['test_nombre'] = nombre
        resultado['query_original'] = query

        # Guardar log individual (sanitizar nombre de archivo)
        nombre_sanitizado = nombre.replace(' ', '_').replace('/', '_').replace('\\', '_')
        log_file = f"{log_dir}/{test_id}_{nombre_sanitizado}.json"
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(resultado, f, indent=2, ensure_ascii=False)

        # Mostrar resumen
        if resultado.get('success'):
            criterios = resultado.get('criteria', {})
            num_resultados = len(resultado.get('results', []))

            print("✅ Búsqueda exitosa")
            print(f"📊 Criterios extraídos: {len(criterios)} campos")
            print(f"🏠 Propiedades encontradas: {num_resultados}")

            # Mostrar scores de los resultados
            if num_resultados > 0:
                print()
                print("⭐ Ranking de resultados:")
                for idx, prop in enumerate(resultado['results'], 1):
                    score = prop.get('match_score', 0)
                    titulo = prop.get('titulo', 'Sin título')[:50]
                    precio = prop.get('precio_texto', 'N/A')
                    print(f"   #{idx}: {score} pts - {titulo} - {precio}")
            else:
                print("⚠️  No se encontraron propiedades que coincidan")

            # Agregar a consolidado
            resultados_consolidados['tests'].append({
                'test_id': test_id,
                'nombre': nombre,
                'success': True,
                'criterios_extraidos': len(criterios),
                'resultados_encontrados': num_resultados,
                'log_file': log_file
            })

        else:
            error = resultado.get('error', 'Error desconocido')
            print(f"❌ Error: {error}")

            resultados_consolidados['tests'].append({
                'test_id': test_id,
                'nombre': nombre,
                'success': False,
                'error': error,
                'log_file': log_file
            })

    except Exception as e:
        print(f"❌ Excepción durante la búsqueda: {e}")

        resultados_consolidados['tests'].append({
            'test_id': test_id,
            'nombre': nombre,
            'success': False,
            'error': str(e),
            'log_file': None
        })

    print()
    print(f"💾 Log guardado: {log_file}")
    print()

    # Pausa entre tests para no saturar la API
    if i < len(test_queries):
        import time
        print("⏳ Esperando 2 segundos antes del siguiente test...")
        print()
        time.sleep(2)

# Guardar resumen consolidado
print("=" * 80)
print("  RESUMEN FINAL")
print("=" * 80)
print()

resumen_file = f"{log_dir}/RESUMEN_CONSOLIDADO.json"
with open(resumen_file, 'w', encoding='utf-8') as f:
    json.dump(resultados_consolidados, f, indent=2, ensure_ascii=False)

# Calcular estadísticas
tests_exitosos = sum(1 for t in resultados_consolidados['tests'] if t['success'])
tests_fallidos = len(test_queries) - tests_exitosos

print(f"📊 Tests ejecutados: {len(test_queries)}")
print(f"✅ Exitosos: {tests_exitosos}")
print(f"❌ Fallidos: {tests_fallidos}")
print()

if tests_exitosos > 0:
    # Estadísticas de criterios y resultados
    criterios_promedio = sum(
        t.get('criterios_extraidos', 0)
        for t in resultados_consolidados['tests']
        if t['success']
    ) / tests_exitosos

    resultados_promedio = sum(
        t.get('resultados_encontrados', 0)
        for t in resultados_consolidados['tests']
        if t['success']
    ) / tests_exitosos

    print(f"📈 Estadísticas:")
    print(f"   • Criterios extraídos (promedio): {criterios_promedio:.1f}")
    print(f"   • Resultados encontrados (promedio): {resultados_promedio:.1f}")
    print()

print(f"📁 Todos los logs guardados en: {log_dir}/")
print(f"📄 Resumen consolidado: {resumen_file}")
print()

# Generar reporte de texto legible
print("📝 Generando reporte de texto...")

reporte_file = f"{log_dir}/REPORTE_ANALISIS.txt"
with open(reporte_file, 'w', encoding='utf-8') as f:
    f.write("=" * 80 + "\n")
    f.write("  REPORTE DE ANÁLISIS - SISTEMA DE BÚSQUEDA INTELIGENTE\n")
    f.write("=" * 80 + "\n")
    f.write(f"\nFecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write(f"Total de tests: {len(test_queries)}\n")
    f.write(f"Tests exitosos: {tests_exitosos}\n")
    f.write(f"Tests fallidos: {tests_fallidos}\n")
    f.write("\n")

    f.write("=" * 80 + "\n")
    f.write("  DETALLE POR TEST\n")
    f.write("=" * 80 + "\n\n")

    for i, test_case in enumerate(test_queries, 1):
        test_id = test_case["id"]
        nombre = test_case["nombre"]
        query = test_case["query"]

        f.write(f"\n{'=' * 80}\n")
        f.write(f"TEST {i}: {test_id} - {nombre}\n")
        f.write(f"{'=' * 80}\n\n")

        f.write("CONSULTA ORIGINAL:\n")
        f.write("-" * 80 + "\n")
        f.write(query + "\n")
        f.write("-" * 80 + "\n\n")

        # Buscar el resultado correspondiente
        test_result = next(
            (t for t in resultados_consolidados['tests'] if t['test_id'] == test_id),
            None
        )

        if test_result and test_result['success']:
            # Cargar el log individual
            try:
                with open(test_result['log_file'], 'r', encoding='utf-8') as log_f:
                    log_data = json.load(log_f)

                criterios = log_data.get('criteria', {})
                resultados = log_data.get('results', [])

                f.write("CRITERIOS EXTRAÍDOS:\n")
                f.write("-" * 80 + "\n")
                for key, value in criterios.items():
                    f.write(f"  • {key}: {value}\n")
                f.write("\n")

                f.write(f"PROPIEDADES ENCONTRADAS: {len(resultados)}\n")
                f.write("-" * 80 + "\n")

                if resultados:
                    for idx, prop in enumerate(resultados, 1):
                        score = prop.get('match_score', 0)
                        titulo = prop.get('titulo', 'Sin título')
                        precio = prop.get('precio_texto', 'N/A')
                        zona = prop.get('zona', 'N/A')
                        reasons = prop.get('match_reasons', [])

                        f.write(f"\n  Resultado #{idx} - Score: {score} pts\n")
                        f.write(f"  {titulo}\n")
                        f.write(f"  Precio: {precio}\n")
                        f.write(f"  Zona: {zona}\n")
                        if reasons:
                            f.write(f"  Razones: {', '.join(reasons)}\n")
                else:
                    f.write("  No se encontraron propiedades que coincidan\n")

            except Exception as e:
                f.write(f"ERROR al cargar log: {e}\n")
        else:
            error = test_result.get('error', 'Desconocido') if test_result else 'No disponible'
            f.write(f"❌ TEST FALLIDO\n")
            f.write(f"Error: {error}\n")

        f.write("\n")

    f.write("\n" + "=" * 80 + "\n")
    f.write("  FIN DEL REPORTE\n")
    f.write("=" * 80 + "\n")

print(f"✅ Reporte generado: {reporte_file}")
print()

print("=" * 80)
print("  TESTING COMPLETADO")
print("=" * 80)
print()
print("📂 Archivos generados:")
print(f"   • {len(test_queries)} logs individuales (JSON)")
print(f"   • 1 resumen consolidado (JSON)")
print(f"   • 1 reporte de análisis (TXT)")
print()
print(f"🔍 Revisa los logs en: {log_dir}/")
print()
print("💡 Siguiente paso:")
print("   1. Revisa REPORTE_ANALISIS.txt para análisis rápido")
print("   2. Revisa logs individuales JSON para detalles técnicos")
print("   3. Comparte los archivos para mejorar el agente")
print()
