#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para analizar los logs de testing y generar insights
"""

import os
import json
import sys
from collections import defaultdict

def analizar_logs(log_dir):
    """Analiza todos los logs en un directorio"""

    if not os.path.exists(log_dir):
        print(f"❌ Directorio no encontrado: {log_dir}")
        return

    # Cargar resumen consolidado
    resumen_file = os.path.join(log_dir, "RESUMEN_CONSOLIDADO.json")
    if not os.path.exists(resumen_file):
        print(f"❌ RESUMEN_CONSOLIDADO.json no encontrado en {log_dir}")
        return

    with open(resumen_file, 'r', encoding='utf-8') as f:
        resumen = json.load(f)

    print("=" * 80)
    print("  ANÁLISIS DE LOGS DEL SISTEMA DE BÚSQUEDA")
    print("=" * 80)
    print()

    # Estadísticas generales
    total_tests = resumen['total_tests']
    tests_exitosos = sum(1 for t in resumen['tests'] if t['success'])
    tests_fallidos = total_tests - tests_exitosos

    print("📊 ESTADÍSTICAS GENERALES")
    print("-" * 80)
    print(f"Total de tests: {total_tests}")
    print(f"Tests exitosos: {tests_exitosos} ({tests_exitosos/total_tests*100:.1f}%)")
    print(f"Tests fallidos: {tests_fallidos} ({tests_fallidos/total_tests*100:.1f}%)")
    print()

    if tests_exitosos == 0:
        print("⚠️  No hay tests exitosos para analizar")
        return

    # Cargar logs individuales
    logs_data = []
    for test in resumen['tests']:
        if test['success'] and test.get('log_file'):
            try:
                with open(test['log_file'], 'r', encoding='utf-8') as f:
                    log_data = json.load(f)
                    logs_data.append(log_data)
            except Exception as e:
                print(f"⚠️  Error al cargar {test['log_file']}: {e}")

    if not logs_data:
        print("❌ No se pudieron cargar logs individuales")
        return

    # Análisis de criterios extraídos
    print("📋 ANÁLISIS DE CRITERIOS EXTRAÍDOS")
    print("-" * 80)

    criterios_counts = defaultdict(int)
    total_criterios = 0

    for log in logs_data:
        criteria = log.get('criteria', {})
        total_criterios += len(criteria)
        for key in criteria.keys():
            criterios_counts[key] += 1

    promedio_criterios = total_criterios / len(logs_data)
    print(f"Promedio de criterios por búsqueda: {promedio_criterios:.2f}")
    print()
    print("Criterios más extraídos:")
    for criterio, count in sorted(criterios_counts.items(), key=lambda x: x[1], reverse=True):
        porcentaje = (count / len(logs_data)) * 100
        print(f"  • {criterio}: {count}/{len(logs_data)} ({porcentaje:.1f}%)")
    print()

    # Análisis de resultados
    print("🏠 ANÁLISIS DE RESULTADOS")
    print("-" * 80)

    total_resultados = sum(len(log.get('results', [])) for log in logs_data)
    promedio_resultados = total_resultados / len(logs_data)

    tests_sin_resultados = sum(1 for log in logs_data if len(log.get('results', [])) == 0)
    tests_con_5_resultados = sum(1 for log in logs_data if len(log.get('results', [])) == 5)

    print(f"Promedio de resultados por búsqueda: {promedio_resultados:.2f}")
    print(f"Tests sin resultados: {tests_sin_resultados}")
    print(f"Tests con 5 resultados (ideal): {tests_con_5_resultados}/{len(logs_data)} ({tests_con_5_resultados/len(logs_data)*100:.1f}%)")
    print()

    # Análisis de scores
    print("⭐ ANÁLISIS DE MATCH SCORES")
    print("-" * 80)

    all_scores = []
    for log in logs_data:
        for result in log.get('results', []):
            score = result.get('match_score', 0)
            all_scores.append(score)

    if all_scores:
        promedio_score = sum(all_scores) / len(all_scores)
        max_score = max(all_scores)
        min_score = min(all_scores)

        print(f"Total de propiedades analizadas: {len(all_scores)}")
        print(f"Score promedio: {promedio_score:.2f} pts")
        print(f"Score máximo: {max_score} pts")
        print(f"Score mínimo: {min_score} pts")
        print()

        # Distribución de scores
        rangos = {
            "Excelente (40-60)": 0,
            "Bueno (25-39)": 0,
            "Aceptable (15-24)": 0,
            "Bajo (5-14)": 0,
            "Muy bajo (0-4)": 0
        }

        for score in all_scores:
            if 40 <= score <= 60:
                rangos["Excelente (40-60)"] += 1
            elif 25 <= score < 40:
                rangos["Bueno (25-39)"] += 1
            elif 15 <= score < 25:
                rangos["Aceptable (15-24)"] += 1
            elif 5 <= score < 15:
                rangos["Bajo (5-14)"] += 1
            else:
                rangos["Muy bajo (0-4)"] += 1

        print("Distribución de scores:")
        for rango, count in rangos.items():
            porcentaje = (count / len(all_scores)) * 100 if all_scores else 0
            barra = "█" * int(porcentaje / 5)
            print(f"  {rango:20} | {barra} {count} ({porcentaje:.1f}%)")
        print()

    # Análisis de razones de coincidencia
    print("✨ ANÁLISIS DE MATCH REASONS")
    print("-" * 80)

    reasons_counts = defaultdict(int)
    total_reasons = 0

    for log in logs_data:
        for result in log.get('results', []):
            reasons = result.get('match_reasons', [])
            total_reasons += len(reasons)
            for reason in reasons:
                # Extraer el tipo de razón (primera parte antes de ":")
                reason_type = reason.split(':')[0].strip() if ':' in reason else reason.strip()
                reasons_counts[reason_type] += 1

    promedio_reasons = total_reasons / len(all_scores) if all_scores else 0
    print(f"Promedio de razones por resultado: {promedio_reasons:.2f}")
    print()
    print("Razones más frecuentes:")
    for reason, count in sorted(reasons_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  • {reason}: {count} veces")
    print()

    # Top resultados
    print("🏆 TOP 5 MEJORES MATCHES")
    print("-" * 80)

    all_results_with_test = []
    for log in logs_data:
        test_id = log.get('test_id', 'Unknown')
        for result in log.get('results', []):
            result_copy = result.copy()
            result_copy['_test_id'] = test_id
            all_results_with_test.append(result_copy)

    # Ordenar por score
    all_results_with_test.sort(key=lambda x: x.get('match_score', 0), reverse=True)

    for i, result in enumerate(all_results_with_test[:5], 1):
        score = result.get('match_score', 0)
        titulo = result.get('titulo', 'Sin título')
        precio = result.get('precio_texto', 'N/A')
        test_id = result.get('_test_id', 'Unknown')
        reasons = result.get('match_reasons', [])

        print(f"\n#{i} - Score: {score} pts ({test_id})")
        print(f"   {titulo}")
        print(f"   Precio: {precio}")
        if reasons:
            print(f"   Razones: {', '.join(reasons[:3])}")

    print()

    # Problemas detectados
    print("⚠️  PROBLEMAS DETECTADOS")
    print("-" * 80)

    problemas = []

    # Tests sin resultados
    for log in logs_data:
        if len(log.get('results', [])) == 0:
            test_id = log.get('test_id', 'Unknown')
            problemas.append(f"Test {test_id}: No encontró resultados")

    # Tests con scores muy bajos
    for log in logs_data:
        test_id = log.get('test_id', 'Unknown')
        results = log.get('results', [])
        if results:
            max_score_in_test = max(r.get('match_score', 0) for r in results)
            if max_score_in_test < 15:
                problemas.append(f"Test {test_id}: Score máximo muy bajo ({max_score_in_test} pts)")

    # Tests con pocos criterios
    for log in logs_data:
        test_id = log.get('test_id', 'Unknown')
        criterios = log.get('criteria', {})
        if len(criterios) < 3:
            problemas.append(f"Test {test_id}: Pocos criterios extraídos ({len(criterios)})")

    if problemas:
        for problema in problemas:
            print(f"  • {problema}")
    else:
        print("  ✅ No se detectaron problemas significativos")

    print()

    # Recomendaciones
    print("💡 RECOMENDACIONES")
    print("-" * 80)

    recomendaciones = []

    if promedio_resultados < 3:
        recomendaciones.append("• Considerar relajar los criterios de búsqueda o agregar más propiedades a la DB")

    if promedio_score < 20:
        recomendaciones.append("• Ajustar el sistema de scoring para dar más puntos a coincidencias relevantes")

    if tests_sin_resultados > len(logs_data) * 0.3:
        recomendaciones.append("• Muchos tests sin resultados - revisar la generación de consultas SQL")

    if promedio_criterios < 4:
        recomendaciones.append("• Mejorar el prompt de Claude para extraer más criterios de las consultas")

    if rangos["Muy bajo (0-4)"] > len(all_scores) * 0.3:
        recomendaciones.append("• Muchos resultados con score muy bajo - revisar la lógica de ranking")

    if recomendaciones:
        for rec in recomendaciones:
            print(rec)
    else:
        print("  ✅ El sistema está funcionando correctamente")

    print()
    print("=" * 80)
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Buscar el directorio de logs más reciente
        log_dirs = [d for d in os.listdir('.') if d.startswith('test_logs_')]
        if log_dirs:
            log_dirs.sort(reverse=True)
            log_dir = log_dirs[0]
            print(f"📁 Usando directorio más reciente: {log_dir}")
            print()
        else:
            print("❌ No se encontraron directorios de logs")
            print()
            print("Uso:")
            print("  python analizar_logs.py [directorio]")
            print()
            print("Ejemplo:")
            print("  python analizar_logs.py test_logs_20251031_153045")
            sys.exit(1)
    else:
        log_dir = sys.argv[1]

    analizar_logs(log_dir)
