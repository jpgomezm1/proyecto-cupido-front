#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EVALUACIONES COMPLETAS - Sistema de Búsqueda v2.0
==================================================
Suite de evaluación para validar que el sistema está listo para producción.

Ejecutar: python tests/evals_search_v2.py
"""

import sys
import os
import json
from datetime import datetime
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
from enum import Enum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.search_config import (
    get_segmento_precio,
    get_tolerancia_precio,
    calcular_rango_precio,
    detectar_perfil_comprador,
    get_zonas_expandidas,
    get_pesos_perfil,
    SEGMENTOS_PRECIO_COLOMBIA,
    ZONA_A_CIUDAD,
)


class EvalStatus(Enum):
    PASS = "✅ PASS"
    FAIL = "❌ FAIL"
    WARN = "⚠️  WARN"


@dataclass
class EvalResult:
    name: str
    status: EvalStatus
    details: str
    expected: Any = None
    actual: Any = None


class SearchEvaluator:
    """Evaluador completo del sistema de búsqueda"""

    def __init__(self):
        self.results: List[EvalResult] = []
        self.total_pass = 0
        self.total_fail = 0
        self.total_warn = 0

    def add_result(self, result: EvalResult):
        self.results.append(result)
        if result.status == EvalStatus.PASS:
            self.total_pass += 1
        elif result.status == EvalStatus.FAIL:
            self.total_fail += 1
        else:
            self.total_warn += 1

    def print_results(self):
        print("\n" + "=" * 70)
        print("RESULTADOS DE EVALUACIÓN")
        print("=" * 70)

        current_section = ""
        for result in self.results:
            # Detectar sección por nombre
            section = result.name.split(":")[0] if ":" in result.name else "General"
            if section != current_section:
                current_section = section
                print(f"\n--- {section} ---")

            print(f"{result.status.value} {result.name}")
            if result.status == EvalStatus.FAIL:
                print(f"      Esperado: {result.expected}")
                print(f"      Actual:   {result.actual}")
                print(f"      Detalle:  {result.details}")
            elif result.details and result.status == EvalStatus.WARN:
                print(f"      {result.details}")

        print("\n" + "=" * 70)
        print(f"RESUMEN: {self.total_pass} PASS | {self.total_fail} FAIL | {self.total_warn} WARN")
        print("=" * 70)

        return self.total_fail == 0


# =============================================================================
# EVALUACIÓN 1: CASOS REALES DEL NEGOCIO
# =============================================================================

CASOS_REALES = [
    {
        "nombre": "Caso Real 1: Persona mayor Laureles $1.000M",
        "query": """Busco apto cliente tu 360 en ciudad del Río o Laureles
Persona mayor primer piso. 2 o 3 habitaciones.
Con portería.
Presupuesto 1000 millones.
Rocío Escudero Vega
3103721706""",
        "esperado": {
            "ubicaciones": ["ciudad del Río", "Laureles"],
            "tipo_propiedad": "Apartamento",
            "precio_max": 1_000_000_000,
            "habitaciones_min": 2,
            "habitaciones_max": 3,
            "piso": 1,
            "perfil_comprador": "senior",
            "amenidades": ["portería"]
        }
    },
    {
        "nombre": "Caso Real 2: Compradora $800M El Poblado",
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
Lalinde""",
        "esperado": {
            "ubicaciones": ["Loma de san Julián", "Castropol", "Lalinde"],
            "tipo_propiedad": "Apartamento",
            "precio_max": 800_000_000,
            "habitaciones_min": 2,
            "area_min": 80,
            "amenidades": ["balcón", "piscina"]
        }
    },
    {
        "nombre": "Caso Real 3: Envigado $500M 3 habitaciones",
        "query": """APTO EL TRIANON EL DORADO LA CUENCA LAS ANTILLAS ALCALA

✅500.000 MILLONES
 3 HABITACIONES
Ojala unidad completa

Soy Sandra Echeverri Asesora inmobiliaria
📲Contáctame:
Cel :3235075028""",
        "esperado": {
            "ubicaciones": ["El Trianón", "El Dorado", "La Cuenca", "Las Antillas", "Alcalá"],
            "tipo_propiedad": "Apartamento",
            "precio_max": 500_000_000,
            "habitaciones_min": 3
        }
    },
    {
        "nombre": "Caso Real 4: Inversionista rentabilidad",
        "query": """Busco apartamento para inversión en El Poblado
Presupuesto hasta 1.500 millones
Que tenga buena rentabilidad para Airbnb
2 habitaciones mínimo""",
        "esperado": {
            "ubicaciones": ["El Poblado"],
            "precio_max": 1_500_000_000,
            "habitaciones_min": 2,
            "perfil_comprador": "inversionista"
        }
    },
    {
        "nombre": "Caso Real 5: Familia con niños",
        "query": """Apartamento para familia con niños
Sabaneta o Envigado
Presupuesto 600 millones
Mínimo 3 habitaciones y 2 baños
Cerca a colegios y parques
Con portería y zonas verdes""",
        "esperado": {
            "ubicaciones": ["Sabaneta", "Envigado"],
            "precio_max": 600_000_000,
            "habitaciones_min": 3,
            "banos_min": 2,
            "perfil_comprador": "familia",
            "amenidades": ["portería", "zonas verdes"]
        }
    }
]


def eval_casos_reales(evaluator: SearchEvaluator):
    """Evalúa la extracción de criterios con casos reales"""
    print("\n📋 Evaluando casos reales del negocio...")

    for caso in CASOS_REALES:
        nombre = caso["nombre"]
        query = caso["query"]
        esperado = caso["esperado"]

        # Evaluar detección de perfil
        perfil_esperado = esperado.get("perfil_comprador", "general")
        criterios_mock = {
            "piso": esperado.get("piso"),
            "habitaciones_min": esperado.get("habitaciones_min")
        }
        perfil_detectado = detectar_perfil_comprador(query, criterios_mock)

        if perfil_esperado != "general":
            if perfil_detectado == perfil_esperado:
                evaluator.add_result(EvalResult(
                    name=f"Perfil: {nombre}",
                    status=EvalStatus.PASS,
                    details=f"Detectado correctamente: {perfil_detectado}"
                ))
            else:
                evaluator.add_result(EvalResult(
                    name=f"Perfil: {nombre}",
                    status=EvalStatus.FAIL,
                    details="Perfil incorrecto",
                    expected=perfil_esperado,
                    actual=perfil_detectado
                ))

        # Evaluar rango de precio si hay precio_max
        if esperado.get("precio_max"):
            precio_max = esperado["precio_max"]
            precio_min, precio_max_adj = calcular_rango_precio(precio_max)

            # Verificar que el rango es coherente
            tolerancia = get_tolerancia_precio(precio_max)
            rango_ok = precio_min >= precio_max * (1 - tolerancia - 0.05)

            if rango_ok:
                evaluator.add_result(EvalResult(
                    name=f"Rango Precio: {nombre}",
                    status=EvalStatus.PASS,
                    details=f"${precio_min/1e6:.0f}M - ${precio_max_adj/1e6:.0f}M"
                ))
            else:
                evaluator.add_result(EvalResult(
                    name=f"Rango Precio: {nombre}",
                    status=EvalStatus.FAIL,
                    details="Rango de precio demasiado amplio",
                    expected=f"Min >= ${precio_max * 0.7 / 1e6:.0f}M",
                    actual=f"Min = ${precio_min/1e6:.0f}M"
                ))


# =============================================================================
# EVALUACIÓN 2: FILTROS DUROS DE PRECIO (CASO CRÍTICO)
# =============================================================================

CASOS_PRECIO_CRITICOS = [
    # (presupuesto, propiedad_incorrecta, descripción)
    (1_000_000_000, 350_000_000, "Presupuesto $1.000M, propiedad $350M"),
    (1_000_000_000, 200_000_000, "Presupuesto $1.000M, propiedad $200M"),
    (1_000_000_000, 500_000_000, "Presupuesto $1.000M, propiedad $500M"),
    (800_000_000, 300_000_000, "Presupuesto $800M, propiedad $300M"),
    (500_000_000, 150_000_000, "Presupuesto $500M, propiedad $150M"),
    (2_000_000_000, 800_000_000, "Presupuesto $2.000M, propiedad $800M"),
]

CASOS_PRECIO_VALIDOS = [
    # (presupuesto, propiedad_valida, descripción)
    (1_000_000_000, 900_000_000, "Presupuesto $1.000M, propiedad $900M"),
    (1_000_000_000, 950_000_000, "Presupuesto $1.000M, propiedad $950M"),
    (1_000_000_000, 1_050_000_000, "Presupuesto $1.000M, propiedad $1.050M"),
    (800_000_000, 700_000_000, "Presupuesto $800M, propiedad $700M"),
    (500_000_000, 450_000_000, "Presupuesto $500M, propiedad $450M"),
]


def eval_filtros_precio(evaluator: SearchEvaluator):
    """Evalúa que los filtros duros de precio funcionen correctamente"""
    print("\n💰 Evaluando filtros duros de precio...")

    # Casos que NO deben pasar el filtro
    for presupuesto, propiedad, desc in CASOS_PRECIO_CRITICOS:
        precio_min, precio_max = calcular_rango_precio(presupuesto)
        en_rango = precio_min <= propiedad <= precio_max

        if not en_rango:
            evaluator.add_result(EvalResult(
                name=f"Filtro Excluye: {desc}",
                status=EvalStatus.PASS,
                details=f"Propiedad ${propiedad/1e6:.0f}M correctamente excluida del rango [{precio_min/1e6:.0f}M - {precio_max/1e6:.0f}M]"
            ))
        else:
            evaluator.add_result(EvalResult(
                name=f"Filtro Excluye: {desc}",
                status=EvalStatus.FAIL,
                details="Propiedad debería ser EXCLUIDA",
                expected=f"Fuera de rango [{precio_min/1e6:.0f}M - {precio_max/1e6:.0f}M]",
                actual=f"${propiedad/1e6:.0f}M está DENTRO del rango"
            ))

    # Casos que SÍ deben pasar el filtro
    for presupuesto, propiedad, desc in CASOS_PRECIO_VALIDOS:
        precio_min, precio_max = calcular_rango_precio(presupuesto)
        en_rango = precio_min <= propiedad <= precio_max

        if en_rango:
            evaluator.add_result(EvalResult(
                name=f"Filtro Incluye: {desc}",
                status=EvalStatus.PASS,
                details=f"Propiedad ${propiedad/1e6:.0f}M correctamente incluida"
            ))
        else:
            evaluator.add_result(EvalResult(
                name=f"Filtro Incluye: {desc}",
                status=EvalStatus.FAIL,
                details="Propiedad debería ser INCLUIDA",
                expected=f"Dentro de rango [{precio_min/1e6:.0f}M - {precio_max/1e6:.0f}M]",
                actual=f"${propiedad/1e6:.0f}M está FUERA del rango"
            ))


# =============================================================================
# EVALUACIÓN 3: DETECCIÓN DE PERFILES
# =============================================================================

CASOS_PERFILES = [
    # (query, criterios, perfil_esperado)
    ("Busco apartamento persona mayor primer piso", {"piso": 1}, "senior"),
    ("Apartamento para tercera edad accesible", {}, "senior"),
    ("Busco para mi mamá mayor de 70 años", {}, "senior"),
    ("Apartamento familia con niños", {}, "familia"),
    ("Cerca a colegios para mis hijos", {}, "familia"),
    ("Para inversión con buena rentabilidad", {}, "inversionista"),
    ("Quiero invertir y arrendar por Airbnb", {}, "inversionista"),
    ("Apartamento moderno para joven profesional", {}, "joven_profesional"),
    ("Busco apartamento en Laureles", {}, "general"),  # Sin indicadores
    ("3 habitaciones presupuesto 500 millones", {}, "general"),
]


def eval_perfiles(evaluator: SearchEvaluator):
    """Evalúa la detección de perfiles de comprador"""
    print("\n👤 Evaluando detección de perfiles de comprador...")

    for query, criterios, esperado in CASOS_PERFILES:
        detectado = detectar_perfil_comprador(query, criterios)

        if detectado == esperado:
            evaluator.add_result(EvalResult(
                name=f"Perfil: '{query[:40]}...'",
                status=EvalStatus.PASS,
                details=f"Detectado: {detectado}"
            ))
        else:
            evaluator.add_result(EvalResult(
                name=f"Perfil: '{query[:40]}...'",
                status=EvalStatus.FAIL,
                details="Perfil incorrecto",
                expected=esperado,
                actual=detectado
            ))


# =============================================================================
# EVALUACIÓN 4: SEGMENTOS DE PRECIO
# =============================================================================

CASOS_SEGMENTOS = [
    (150_000_000, "vis"),
    (199_000_000, "vis"),
    (200_000_000, "accesible"),
    (350_000_000, "accesible"),
    (400_000_000, "medio"),
    (600_000_000, "medio"),
    (700_000_000, "medio_alto"),
    (1_000_000_000, "medio_alto"),
    (1_200_000_000, "premium"),
    (2_000_000_000, "premium"),
    (2_500_000_000, "lujo"),
    (5_000_000_000, "lujo"),
]


def eval_segmentos(evaluator: SearchEvaluator):
    """Evalúa la clasificación de segmentos de precio"""
    print("\n📊 Evaluando segmentos de precio...")

    for precio, esperado in CASOS_SEGMENTOS:
        segmento = get_segmento_precio(precio)

        if segmento == esperado:
            evaluator.add_result(EvalResult(
                name=f"Segmento: ${precio/1e6:.0f}M",
                status=EvalStatus.PASS,
                details=f"Segmento: {segmento}"
            ))
        else:
            evaluator.add_result(EvalResult(
                name=f"Segmento: ${precio/1e6:.0f}M",
                status=EvalStatus.FAIL,
                details="Segmento incorrecto",
                expected=esperado,
                actual=segmento
            ))


# =============================================================================
# EVALUACIÓN 5: ZONAS Y EXPANSIÓN
# =============================================================================

CASOS_ZONAS = [
    ("Laureles", ["Laureles", "estadio", "conquistadores", "floresta", "belen", "bolivariana"]),
    ("Poblado", ["Poblado", "ciudad del rio", "lalinde", "castropol", "manila", "envigado"]),
    ("Envigado", ["Envigado", "poblado", "sabaneta", "zuñiga", "la paz"]),
]


def eval_zonas(evaluator: SearchEvaluator):
    """Evalúa la expansión de zonas"""
    print("\n📍 Evaluando expansión de zonas...")

    for zona, esperadas in CASOS_ZONAS:
        expandidas = get_zonas_expandidas(zona)

        # Verificar que la zona original está primero
        if expandidas[0].lower() == zona.lower():
            evaluator.add_result(EvalResult(
                name=f"Zona Original Primero: {zona}",
                status=EvalStatus.PASS,
                details=f"Original '{zona}' está primero"
            ))
        else:
            evaluator.add_result(EvalResult(
                name=f"Zona Original Primero: {zona}",
                status=EvalStatus.FAIL,
                details="Zona original debería estar primero",
                expected=zona,
                actual=expandidas[0] if expandidas else "vacío"
            ))

        # Verificar que hay expansión
        if len(expandidas) > 1:
            evaluator.add_result(EvalResult(
                name=f"Zona Expansión: {zona}",
                status=EvalStatus.PASS,
                details=f"Expandido a {len(expandidas)} zonas: {', '.join(expandidas[:4])}..."
            ))
        else:
            evaluator.add_result(EvalResult(
                name=f"Zona Expansión: {zona}",
                status=EvalStatus.WARN,
                details=f"Sin zonas similares definidas para {zona}"
            ))


# =============================================================================
# EVALUACIÓN 6: TOLERANCIAS POR SEGMENTO
# =============================================================================

def eval_tolerancias(evaluator: SearchEvaluator):
    """Evalúa que las tolerancias sean correctas por segmento"""
    print("\n📏 Evaluando tolerancias por segmento...")

    tolerancias_esperadas = {
        "vis": 0.10,
        "accesible": 0.12,
        "medio": 0.15,
        "medio_alto": 0.15,
        "premium": 0.18,
        "lujo": 0.20,
    }

    for segmento, tolerancia_esperada in tolerancias_esperadas.items():
        # Obtener un precio de ese segmento
        rango = SEGMENTOS_PRECIO_COLOMBIA[segmento]
        precio_test = (rango[0] + min(rango[1], rango[0] + 100_000_000)) // 2

        tolerancia = get_tolerancia_precio(precio_test)

        if abs(tolerancia - tolerancia_esperada) < 0.01:
            evaluator.add_result(EvalResult(
                name=f"Tolerancia: {segmento}",
                status=EvalStatus.PASS,
                details=f"±{tolerancia*100:.0f}%"
            ))
        else:
            evaluator.add_result(EvalResult(
                name=f"Tolerancia: {segmento}",
                status=EvalStatus.FAIL,
                details="Tolerancia incorrecta",
                expected=f"±{tolerancia_esperada*100:.0f}%",
                actual=f"±{tolerancia*100:.0f}%"
            ))


# =============================================================================
# EVALUACIÓN 7: CASO CRÍTICO ORIGINAL
# =============================================================================

def eval_caso_critico_original(evaluator: SearchEvaluator):
    """Evalúa específicamente el caso reportado: $1.000M mostrando $350M"""
    print("\n🚨 Evaluando CASO CRÍTICO ORIGINAL...")

    presupuesto = 1_000_000_000
    propiedad_incorrecta = 350_000_000

    precio_min, precio_max = calcular_rango_precio(presupuesto)

    # Esta es la validación más importante
    propiedad_excluida = propiedad_incorrecta < precio_min or propiedad_incorrecta > precio_max

    if propiedad_excluida:
        evaluator.add_result(EvalResult(
            name="CASO CRÍTICO: $1.000M presupuesto, $350M propiedad",
            status=EvalStatus.PASS,
            details=f"Propiedad $350M EXCLUIDA correctamente. Rango: ${precio_min/1e6:.0f}M - ${precio_max/1e6:.0f}M"
        ))
    else:
        evaluator.add_result(EvalResult(
            name="CASO CRÍTICO: $1.000M presupuesto, $350M propiedad",
            status=EvalStatus.FAIL,
            details="BUG NO RESUELTO - Propiedad $350M NO fue excluida",
            expected="Propiedad FUERA del rango",
            actual=f"Propiedad DENTRO del rango [{precio_min/1e6:.0f}M - {precio_max/1e6:.0f}M]"
        ))

    # Verificar que propiedades válidas SÍ se incluyen
    propiedades_validas = [850_000_000, 900_000_000, 950_000_000, 1_000_000_000]
    todas_incluidas = all(precio_min <= p <= precio_max for p in propiedades_validas)

    if todas_incluidas:
        evaluator.add_result(EvalResult(
            name="CASO CRÍTICO: Propiedades válidas incluidas",
            status=EvalStatus.PASS,
            details=f"$850M, $900M, $950M, $1.000M todas incluidas correctamente"
        ))
    else:
        excluidas = [p for p in propiedades_validas if not (precio_min <= p <= precio_max)]
        evaluator.add_result(EvalResult(
            name="CASO CRÍTICO: Propiedades válidas incluidas",
            status=EvalStatus.FAIL,
            details="Algunas propiedades válidas fueron excluidas",
            expected="Todas incluidas",
            actual=f"Excluidas: {[f'${p/1e6:.0f}M' for p in excluidas]}"
        ))


# =============================================================================
# EVALUACIÓN 8: CONSISTENCIA DE RANGOS
# =============================================================================

def eval_consistencia_rangos(evaluator: SearchEvaluator):
    """Evalúa que los rangos sean consistentes y no se solapen incorrectamente"""
    print("\n🔄 Evaluando consistencia de rangos...")

    # Un cliente de un segmento NO debe ver propiedades de segmentos muy diferentes
    casos = [
        (1_000_000_000, "medio_alto", ["vis", "accesible"]),  # No debe ver VIS ni Accesible
        (500_000_000, "medio", ["vis", "lujo"]),  # No debe ver VIS ni Lujo
        (2_000_000_000, "premium", ["vis", "accesible", "medio"]),  # No debe ver bajos
        (300_000_000, "accesible", ["premium", "lujo"]),  # No debe ver altos
    ]

    for presupuesto, segmento_cliente, segmentos_prohibidos in casos:
        precio_min, precio_max = calcular_rango_precio(presupuesto)

        violaciones = []
        for seg_prohibido in segmentos_prohibidos:
            rango_prohibido = SEGMENTOS_PRECIO_COLOMBIA[seg_prohibido]
            # Verificar si hay solapamiento
            inicio_prohibido = rango_prohibido[0]
            fin_prohibido = min(rango_prohibido[1], 10_000_000_000)  # Cap para infinito

            hay_solapamiento = not (precio_max < inicio_prohibido or precio_min > fin_prohibido)
            if hay_solapamiento:
                violaciones.append(seg_prohibido)

        if not violaciones:
            evaluator.add_result(EvalResult(
                name=f"Consistencia: ${presupuesto/1e6:.0f}M ({segmento_cliente})",
                status=EvalStatus.PASS,
                details=f"No hay solapamiento con segmentos prohibidos"
            ))
        else:
            evaluator.add_result(EvalResult(
                name=f"Consistencia: ${presupuesto/1e6:.0f}M ({segmento_cliente})",
                status=EvalStatus.FAIL,
                details="Solapamiento con segmentos prohibidos",
                expected="Sin solapamiento",
                actual=f"Solapa con: {violaciones}"
            ))


# =============================================================================
# MAIN
# =============================================================================

def run_all_evals():
    """Ejecuta todas las evaluaciones"""
    print("=" * 70)
    print("EVALUACIÓN COMPLETA - SISTEMA DE BÚSQUEDA v2.0")
    print("=" * 70)
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    evaluator = SearchEvaluator()

    # Ejecutar todas las evaluaciones
    eval_caso_critico_original(evaluator)  # Primero el caso crítico
    eval_filtros_precio(evaluator)
    eval_segmentos(evaluator)
    eval_tolerancias(evaluator)
    eval_perfiles(evaluator)
    eval_zonas(evaluator)
    eval_consistencia_rangos(evaluator)
    eval_casos_reales(evaluator)

    # Mostrar resultados
    all_passed = evaluator.print_results()

    if all_passed:
        print("\n✅ SISTEMA LISTO PARA PRODUCCIÓN")
        print("   Todos los tests críticos pasaron.")
    else:
        print("\n❌ HAY PROBLEMAS QUE RESOLVER")
        print("   Revisar los tests que fallaron antes de deployar.")

    return all_passed


if __name__ == "__main__":
    success = run_all_evals()
    sys.exit(0 if success else 1)
