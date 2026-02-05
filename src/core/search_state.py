#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Fases de Búsqueda y Prioridades v1.0

Maneja el flujo de búsqueda con estados:
- awaiting_priority: Esperando que el usuario seleccione qué criterio es más importante
- awaiting_area_validation: Esperando validación de área vs tipo de propiedad
- ready_to_search: Listo para ejecutar la búsqueda

También maneja los pesos de scoring según la prioridad seleccionada.
"""

from enum import Enum
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict

# v2.6: Import funciones de cálculo de rangos
from src.core.search_config import (
    calcular_rango_precio,
    calcular_rango_habitaciones
)


class SearchPhase(Enum):
    """Fases del flujo de búsqueda"""
    INITIAL = "initial"
    AWAITING_PRIORITY = "awaiting_priority"
    AWAITING_AREA_VALIDATION = "awaiting_area_validation"
    READY_TO_SEARCH = "ready_to_search"


@dataclass
class PriorityOption:
    """Representa una opción de prioridad para el usuario"""
    id: str
    type: str  # zona | precio | habitaciones | findy
    label: str
    value: str
    emoji: str

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para JSON"""
        return asdict(self)


# =============================================================================
# PESOS DE SCORING POR PRIORIDAD
# =============================================================================

# Cuando el usuario selecciona una prioridad, ese criterio recibe más peso en el scoring
# y se convierte en filtro "duro" (no se relaja en búsqueda progresiva)
PRIORITY_WEIGHTS = {
    'zona': {
        'zona': 40,
        'precio': 15,
        'habitaciones': 15
    },
    'precio': {
        'zona': 15,
        'precio': 40,
        'habitaciones': 15
    },
    'habitaciones': {
        'zona': 15,
        'precio': 15,
        'habitaciones': 40
    },
    'balanced': {
        'zona': 20,
        'precio': 20,
        'habitaciones': 20
    }
}


# =============================================================================
# FUNCIONES DE CONSTRUCCIÓN DE OPCIONES
# =============================================================================

def build_priority_options(criteria: Dict[str, Any]) -> List[PriorityOption]:
    """
    Construye la lista de opciones de prioridad basada en los criterios extraídos.

    Solo muestra opciones para criterios que el usuario realmente mencionó.
    "Confío en Findy" siempre se agrega al final.

    Args:
        criteria: Diccionario con criterios de búsqueda extraídos por Claude

    Returns:
        Lista de PriorityOption con las opciones disponibles
    """
    options = []
    option_number = 1

    # Opción de ZONA - solo si hay ubicaciones
    if criteria.get('ubicaciones'):
        zonas = criteria['ubicaciones']
        # Mostrar máximo 2 zonas en el label
        zonas_display = ', '.join(zonas[:2])
        if len(zonas) > 2:
            zonas_display += f' (+{len(zonas) - 2})'

        options.append(PriorityOption(
            id=str(option_number),
            type="zona",
            label=f"Zona exacta ({zonas_display})",
            value="zona",
            emoji=f"{option_number}️⃣"
        ))
        option_number += 1

    # Opción de PRECIO - solo si hay precio_max
    if criteria.get('precio_max'):
        precio_m = int(criteria['precio_max'] / 1_000_000)
        options.append(PriorityOption(
            id=str(option_number),
            type="precio",
            label=f"Precio (${precio_m}M)",
            value="precio",
            emoji=f"{option_number}️⃣"
        ))
        option_number += 1

    # Opción de HABITACIONES - solo si hay habitaciones especificadas
    if criteria.get('habitaciones_min') or criteria.get('habitaciones_max'):
        hab_min = criteria.get('habitaciones_min')
        hab_max = criteria.get('habitaciones_max')

        if hab_min and hab_max and hab_min != hab_max:
            hab_display = f"{hab_min}-{hab_max}"
        elif hab_min:
            hab_display = str(hab_min)
        else:
            hab_display = str(hab_max)

        options.append(PriorityOption(
            id=str(option_number),
            type="habitaciones",
            label=f"Habitaciones ({hab_display})",
            value="habitaciones",
            emoji=f"{option_number}️⃣"
        ))
        option_number += 1

    # "Confío en Findy" SIEMPRE al final
    options.append(PriorityOption(
        id=str(option_number),
        type="findy",
        label="Confío en Findy ✨",
        value="balanced",
        emoji=f"{option_number}️⃣"
    ))

    return options


def format_priority_question(options: List[PriorityOption]) -> str:
    """
    Formatea el mensaje de pregunta de prioridad para el usuario.

    Args:
        options: Lista de opciones de prioridad

    Returns:
        Mensaje formateado - solo la pregunta, las opciones se muestran en la UI
    """
    # v2.4: Solo la pregunta, las opciones se renderizan como botones en el frontend
    return "¿Qué es lo más importante para tu búsqueda?"


# =============================================================================
# FUNCIONES DE PARSEO DE RESPUESTAS
# =============================================================================

def parse_priority_response(response: str, options: List[Dict[str, Any]]) -> Optional[str]:
    """
    Parsea la respuesta del usuario para determinar qué prioridad seleccionó.

    Soporta:
    - Respuestas numéricas: "1", "2", "3", "4"
    - Palabras clave: "zona", "precio", "habitaciones", "findy", "confío"

    Args:
        response: Texto de respuesta del usuario
        options: Lista de opciones disponibles (como dicts)

    Returns:
        Valor de la prioridad seleccionada ('zona', 'precio', 'habitaciones', 'balanced')
        o None si no se pudo determinar
    """
    response = response.strip().lower()

    # Detectar respuestas numéricas
    for option in options:
        option_id = str(option.get('id', ''))
        if response == option_id:
            return option.get('value')
        # También aceptar emoji sin el sufijo
        if response == option_id + "️⃣" or response == option_id + "⃣":
            return option.get('value')

    # Detectar palabras clave
    keyword_map = {
        'zona': ['zona', 'ubicacion', 'ubicación', 'barrio', 'sector', 'lugar'],
        'precio': ['precio', 'presupuesto', 'plata', 'dinero', 'costo', 'valor'],
        'habitaciones': ['habitacion', 'habitaciones', 'cuarto', 'cuartos', 'alcoba', 'alcobas', 'hab'],
        'balanced': ['findy', 'confio', 'confío', 'cualquier', 'cualquiera', 'no importa', 'da igual', 'balanced']
    }

    for priority, keywords in keyword_map.items():
        if any(kw in response for kw in keywords):
            return priority

    # Si el usuario solo escribió un número, intentar mapearlo
    try:
        num = int(response.replace('️⃣', '').replace('⃣', ''))
        for option in options:
            if int(option.get('id', 0)) == num:
                return option.get('value')
    except (ValueError, TypeError):
        pass

    return None


# =============================================================================
# FUNCIONES DE APLICACIÓN DE PRIORIDAD
# =============================================================================

def apply_priority_weights(criteria: Dict[str, Any], priority: str) -> Dict[str, Any]:
    """
    Aplica los pesos de prioridad a los criterios de búsqueda.

    v2.5: "balanced" (Confío en Findy) ahora marca TODOS los criterios mencionados
    como filtros semi-duros. Esto significa que el sistema respetará todos los
    criterios por igual en lugar de relajarlos.

    Args:
        criteria: Criterios de búsqueda actuales
        priority: Prioridad seleccionada ('zona', 'precio', 'habitaciones', 'balanced')

    Returns:
        Criterios actualizados con pesos y filtros duros
    """
    # Aplicar pesos de scoring
    weights = PRIORITY_WEIGHTS.get(priority, PRIORITY_WEIGHTS['balanced'])
    criteria['priority_weights'] = weights
    criteria['selected_priority'] = priority

    # v2.5: Marcar criterios como filtros duros
    hard_filters = criteria.get('hard_filters', [])

    if priority == 'balanced':
        # "Confío en Findy" = respetar TODOS los criterios mencionados por igual
        # Esto evita que el sistema relaje criterios importantes como habitaciones
        if criteria.get('ubicaciones') and 'zona' not in hard_filters:
            hard_filters.append('zona')
        if criteria.get('precio_max') and 'precio' not in hard_filters:
            hard_filters.append('precio')
        if (criteria.get('habitaciones_min') or criteria.get('habitaciones_max')) and 'habitaciones' not in hard_filters:
            hard_filters.append('habitaciones')
    else:
        # Prioridad específica: solo ese criterio es duro
        if priority not in hard_filters:
            hard_filters.append(priority)

    criteria['hard_filters'] = hard_filters

    # v2.6: Calcular rangos de filtros SQL si faltan
    # Esto garantiza que los filtros de precio y habitaciones estén siempre disponibles
    print(f"[apply_priority_weights] Criterios recibidos:")
    print(f"   - precio_max: {criteria.get('precio_max')}")
    print(f"   - precio_min_implicito: {criteria.get('precio_min_implicito')}")
    print(f"   - habitaciones_min: {criteria.get('habitaciones_min')}")
    print(f"   - habitaciones_max: {criteria.get('habitaciones_max')}")

    # Calcular rango de precio
    if criteria.get('precio_max') and not criteria.get('precio_min_implicito'):
        precio_max = criteria['precio_max']
        flexibilidad = criteria.get('flexibilidad_precio', 'normal')
        precio_min, precio_max_ajustado = calcular_rango_precio(precio_max, flexibilidad=flexibilidad)
        criteria['precio_min_implicito'] = precio_min
        criteria['precio_max_ajustado'] = precio_max_ajustado
        print(f"[apply_priority_weights] Calculado rango precio: ${precio_min/1_000_000:.0f}M - ${precio_max_ajustado/1_000_000:.0f}M")

    # Calcular rango de habitaciones
    if (criteria.get('habitaciones_min') or criteria.get('habitaciones_max')) and not criteria.get('habitaciones_min_filtro'):
        hab_min_filtro, hab_max_filtro = calcular_rango_habitaciones(
            criteria.get('habitaciones_min'),
            criteria.get('habitaciones_max'),
            flexibilidad=criteria.get('flexibilidad_habitaciones', 'normal')
        )
        if hab_min_filtro:
            criteria['habitaciones_min_filtro'] = hab_min_filtro
        if hab_max_filtro:
            criteria['habitaciones_max_filtro'] = hab_max_filtro
        print(f"[apply_priority_weights] Calculado rango habitaciones: {hab_min_filtro}-{hab_max_filtro}")

    # Limpiar estado de búsqueda - ya no estamos esperando prioridad
    if 'search_state' in criteria:
        criteria['search_state']['phase'] = SearchPhase.READY_TO_SEARCH.value
        criteria['search_state']['selected_priority'] = priority

    return criteria


def create_search_state(
    phase: SearchPhase,
    options: List[PriorityOption] = None,
    original_query: str = None,
    validation_message: str = None
) -> Dict[str, Any]:
    """
    Crea un nuevo estado de búsqueda.

    Args:
        phase: Fase actual del flujo
        options: Opciones pendientes para el usuario
        original_query: Query original del usuario
        validation_message: Mensaje de validación (para area_validation)

    Returns:
        Diccionario con el estado de búsqueda
    """
    state = {
        'phase': phase.value,
        'selected_priority': None
    }

    if options:
        state['pending_options'] = [opt.to_dict() if isinstance(opt, PriorityOption) else opt for opt in options]

    if original_query:
        state['original_query'] = original_query

    if validation_message:
        state['validation_message'] = validation_message

    return state


def should_ask_priority(criteria: Dict[str, Any]) -> bool:
    """
    Determina si debemos preguntar al usuario por la prioridad.

    v2.7: DESHABILITADO - Siempre confiar en Findy (balanced)
    El sistema va directo a resultados sin preguntar por prioridad.

    Args:
        criteria: Criterios extraídos

    Returns:
        Siempre False - no preguntar por prioridad
    """
    # v2.7: DESHABILITADO - Ir directo a resultados con criterios balanceados
    return False


def get_priority_weight(criteria: Dict[str, Any], criterion: str) -> int:
    """
    Obtiene el peso de scoring para un criterio específico.

    Args:
        criteria: Criterios con priority_weights aplicados
        criterion: 'zona', 'precio', o 'habitaciones'

    Returns:
        Peso para el scoring (default 15 si no hay prioridad configurada)
    """
    weights = criteria.get('priority_weights', PRIORITY_WEIGHTS['balanced'])
    return weights.get(criterion, 15)


def is_hard_filter(criteria: Dict[str, Any], criterion: str) -> bool:
    """
    Verifica si un criterio es filtro duro (no se puede relajar).

    Args:
        criteria: Criterios de búsqueda
        criterion: 'zona', 'precio', o 'habitaciones'

    Returns:
        True si el criterio no debe relajarse
    """
    hard_filters = criteria.get('hard_filters', [])
    return criterion in hard_filters
