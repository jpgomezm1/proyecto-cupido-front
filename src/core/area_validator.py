#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validación de Área vs Tipo de Propiedad v1.0

Detecta inconsistencias entre el área solicitada y el tipo de propiedad.
Por ejemplo: "apartaestudio de 150m²" no tiene sentido porque un apartaestudio
normalmente tiene 20-55m².

Cuando hay inconsistencia, genera opciones para que el usuario elija cómo proceder.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict


# =============================================================================
# RANGOS DE ÁREA POR TIPO DE PROPIEDAD
# =============================================================================

# Rangos típicos de área en m² para cada tipo de propiedad en Colombia
AREA_RANGES = {
    'apartaestudio': {'min': 20, 'max': 55, 'label': 'Apartaestudio'},
    'apartamento': {'min': 45, 'max': 250, 'label': 'Apartamento'},
    'casa': {'min': 70, 'max': 500, 'label': 'Casa'},
    'penthouse': {'min': 100, 'max': 400, 'label': 'Penthouse'},
    'duplex': {'min': 80, 'max': 300, 'label': 'Dúplex'},
    'loft': {'min': 40, 'max': 120, 'label': 'Loft'},
    'local': {'min': 15, 'max': 1000, 'label': 'Local'},
    'oficina': {'min': 20, 'max': 500, 'label': 'Oficina'},
    'bodega': {'min': 50, 'max': 5000, 'label': 'Bodega'},
    'finca': {'min': 100, 'max': 10000, 'label': 'Finca'},
    'lote': {'min': 50, 'max': 50000, 'label': 'Lote'},
}

# Alias de tipos de propiedad
TIPO_ALIASES = {
    'apto': 'apartamento',
    'apt': 'apartamento',
    'apartamento': 'apartamento',
    'apartaestudio': 'apartaestudio',
    'estudio': 'apartaestudio',
    'casa': 'casa',
    'penthouse': 'penthouse',
    'ph': 'penthouse',
    'duplex': 'duplex',
    'dúplex': 'duplex',
    'loft': 'loft',
    'local': 'local',
    'local comercial': 'local',
    'oficina': 'oficina',
    'bodega': 'bodega',
    'finca': 'finca',
    'lote': 'lote',
    'terreno': 'lote',
}


@dataclass
class AreaValidationOption:
    """Representa una opción de corrección para inconsistencia de área"""
    id: str
    label: str
    action: str  # adjust_area | change_type | keep_original
    new_values: Dict[str, Any]
    emoji: str

    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para JSON"""
        return asdict(self)


# =============================================================================
# FUNCIONES DE NORMALIZACIÓN
# =============================================================================

def normalize_property_type(tipo: str) -> Optional[str]:
    """
    Normaliza el tipo de propiedad a una clave estándar.

    Args:
        tipo: Tipo de propiedad como lo escribió el usuario

    Returns:
        Clave normalizada o None si no se reconoce
    """
    if not tipo:
        return None

    tipo_lower = tipo.lower().strip()

    # Buscar en aliases
    if tipo_lower in TIPO_ALIASES:
        return TIPO_ALIASES[tipo_lower]

    # Buscar coincidencia parcial
    for alias, normalized in TIPO_ALIASES.items():
        if alias in tipo_lower or tipo_lower in alias:
            return normalized

    # Buscar directamente en AREA_RANGES
    for tipo_key in AREA_RANGES.keys():
        if tipo_key in tipo_lower:
            return tipo_key

    return None


# =============================================================================
# FUNCIONES DE VALIDACIÓN
# =============================================================================

def validate_area_vs_type(criteria: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Valida si el área solicitada es coherente con el tipo de propiedad.

    Args:
        criteria: Criterios de búsqueda con tipo_propiedad y area_min/area_max

    Returns:
        None si es válido, o dict con opciones de corrección si hay inconsistencia:
        {
            'validation_needed': True,
            'message': 'Un apartaestudio normalmente tiene 20-55m²',
            'options': [...]
        }
    """
    tipo_raw = criteria.get('tipo_propiedad', '')

    # Si tipo_propiedad es una lista, usar el primero
    if isinstance(tipo_raw, list):
        if not tipo_raw:
            return None
        tipo_raw = tipo_raw[0]

    tipo = normalize_property_type(tipo_raw)
    area_min = criteria.get('area_min')
    area_max = criteria.get('area_max')

    # Si no hay tipo o área, no hay nada que validar
    if not tipo or not (area_min or area_max):
        return None

    # Obtener rango esperado para este tipo
    rango = AREA_RANGES.get(tipo)
    if not rango:
        return None

    # Determinar el área que está fuera de rango
    area_problema = None
    problema_tipo = None

    if area_min and area_min > rango['max']:
        area_problema = area_min
        problema_tipo = 'excede_maximo'
    elif area_max and area_max > rango['max'] * 1.5:  # Tolerancia de 50% para max
        area_problema = area_max
        problema_tipo = 'excede_maximo'
    elif area_min and area_min < rango['min'] * 0.5:  # Tolerancia de 50% para min
        area_problema = area_min
        problema_tipo = 'bajo_minimo'

    if not problema_tipo:
        return None

    # Hay inconsistencia - construir opciones
    return build_area_correction_options(
        tipo_actual=tipo,
        tipo_label=rango['label'],
        area_solicitada=area_problema,
        rango=rango,
        problema=problema_tipo
    )


def build_area_correction_options(
    tipo_actual: str,
    tipo_label: str,
    area_solicitada: int,
    rango: Dict[str, int],
    problema: str
) -> Dict[str, Any]:
    """
    Construye las opciones de corrección para una inconsistencia de área.

    Args:
        tipo_actual: Tipo normalizado (ej: 'apartaestudio')
        tipo_label: Label para mostrar (ej: 'Apartaestudio')
        area_solicitada: Área que el usuario pidió
        rango: Dict con 'min' y 'max'
        problema: 'excede_maximo' o 'bajo_minimo'

    Returns:
        Dict con mensaje y opciones para el usuario
    """
    options = []
    option_number = 1

    # Opción 1: Ajustar área al tipo seleccionado
    if problema == 'excede_maximo':
        options.append(AreaValidationOption(
            id=str(option_number),
            label=f"{tipo_label} (ajustar área a máximo {rango['max']}m²)",
            action="adjust_area",
            new_values={
                'area_max': rango['max'],
                'area_min': None  # Quitar mínimo para dar flexibilidad
            },
            emoji=f"{option_number}️⃣"
        ))
        option_number += 1

    # Opción 2: Sugerir tipo alternativo que sí encaje con el área
    tipo_sugerido = suggest_type_for_area(area_solicitada, exclude=tipo_actual)
    if tipo_sugerido:
        tipo_sugerido_label = AREA_RANGES[tipo_sugerido]['label']
        options.append(AreaValidationOption(
            id=str(option_number),
            label=f"{tipo_sugerido_label} de {area_solicitada}m²",
            action="change_type",
            new_values={
                'tipo_propiedad': tipo_sugerido_label
            },
            emoji=f"{option_number}️⃣"
        ))
        option_number += 1

    # Opción 3: Mantener original (buscar como dijiste)
    options.append(AreaValidationOption(
        id=str(option_number),
        label="Buscar como dijiste",
        action="keep_original",
        new_values={},
        emoji=f"{option_number}️⃣"
    ))

    # Construir mensaje
    message = f"Un {tipo_label.lower()} normalmente tiene {rango['min']}-{rango['max']}m². ¿Quisiste decir:"

    return {
        'validation_needed': True,
        'message': message,
        'options': [opt.to_dict() for opt in options],
        'tipo_detectado': tipo_actual,
        'area_solicitada': area_solicitada,
        'rango_esperado': rango
    }


def suggest_type_for_area(area: int, exclude: str = None) -> Optional[str]:
    """
    Sugiere el tipo de propiedad más adecuado para un área dada.

    Busca el tipo donde el área esté más centrada en el rango.

    Args:
        area: Área en m²
        exclude: Tipo a excluir de las sugerencias

    Returns:
        Tipo de propiedad sugerido o None
    """
    # Tipos residenciales a considerar (excluir comerciales/industriales)
    tipos_residenciales = ['apartaestudio', 'apartamento', 'casa', 'penthouse', 'duplex', 'loft']

    best_match = None
    best_score = float('inf')

    for tipo in tipos_residenciales:
        if tipo == exclude:
            continue

        rango = AREA_RANGES.get(tipo)
        if not rango:
            continue

        # Verificar si el área está dentro del rango
        if rango['min'] <= area <= rango['max']:
            # Calcular qué tan "centrado" está el área en el rango
            center = (rango['min'] + rango['max']) / 2
            score = abs(area - center) / (rango['max'] - rango['min'])

            if score < best_score:
                best_score = score
                best_match = tipo

    return best_match


def format_area_validation_question(validation: Dict[str, Any]) -> str:
    """
    Formatea el mensaje de validación de área para el usuario.

    Args:
        validation: Resultado de validate_area_vs_type()

    Returns:
        Mensaje formateado
    """
    lines = [validation['message'], ""]

    for option in validation['options']:
        lines.append(f"{option['emoji']} {option['label']}")

    return "\n".join(lines)


# =============================================================================
# FUNCIONES DE APLICACIÓN DE CORRECCIÓN
# =============================================================================

def apply_area_correction(
    criteria: Dict[str, Any],
    selected_option: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Aplica la corrección de área seleccionada por el usuario.

    Args:
        criteria: Criterios de búsqueda actuales
        selected_option: Opción seleccionada por el usuario

    Returns:
        Criterios actualizados
    """
    action = selected_option.get('action', 'keep_original')
    new_values = selected_option.get('new_values', {})

    if action == 'adjust_area':
        # Actualizar área según los nuevos valores
        for key, value in new_values.items():
            if value is None and key in criteria:
                del criteria[key]
            elif value is not None:
                criteria[key] = value

    elif action == 'change_type':
        # Cambiar tipo de propiedad
        if 'tipo_propiedad' in new_values:
            criteria['tipo_propiedad'] = new_values['tipo_propiedad']

    # keep_original: no hacer nada

    # Limpiar estado de validación
    if 'search_state' in criteria:
        criteria['search_state']['phase'] = 'ready_to_search'

    return criteria


def parse_area_validation_response(
    response: str,
    options: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Parsea la respuesta del usuario a la validación de área.

    Args:
        response: Texto de respuesta del usuario
        options: Opciones disponibles

    Returns:
        Opción seleccionada o None
    """
    response = response.strip().lower()

    # Buscar por ID numérico
    for option in options:
        option_id = str(option.get('id', ''))
        if response == option_id:
            return option

    # Buscar por palabras clave
    keyword_map = {
        'adjust_area': ['ajustar', 'ajusta', 'maximo', 'máximo'],
        'change_type': ['apartamento', 'casa', 'cambiar', 'otro tipo'],
        'keep_original': ['como dijiste', 'original', 'mantener', 'así', 'asi']
    }

    for action, keywords in keyword_map.items():
        if any(kw in response for kw in keywords):
            for option in options:
                if option.get('action') == action:
                    return option

    # Si es un número, mapearlo a opción
    try:
        num = int(response.replace('️⃣', '').replace('⃣', ''))
        for option in options:
            if int(option.get('id', 0)) == num:
                return option
    except (ValueError, TypeError):
        pass

    # Default: última opción (keep_original)
    return options[-1] if options else None
