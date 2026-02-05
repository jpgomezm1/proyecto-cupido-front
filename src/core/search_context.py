#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lógica de Contexto para Búsquedas Conversacionales
Maneja el merge de criterios entre mensajes de una conversación
"""

import re
from typing import Dict, Any, Optional

# Patrones de refinamiento en español
REFINEMENT_PATTERNS = {
    # Precio - patrones relativos y explícitos
    'cheaper': [
        r'más\s+barato', r'más\s+económico', r'menos\s+caro',
        r'menor\s+precio', r'más\s+accesible', r'rebajado',
        # Patrones con números explícitos (precio máximo)
        r'hasta\s+\d+', r'máximo\s+\d+', r'maximo\s+\d+',
        r'no\s+supere?\s+\d+', r'no\s+pase\s+de\s+\d+',
        r'menos\s+de\s+\d+\s*(?:millones|mm|m(?!\s*2))',
        r'tope\s+(?:de\s+)?\d+'
    ],
    'more_expensive': [
        r'más\s+caro', r'mayor\s+presupuesto', r'más\s+costoso',
        r'subir\s+el\s+precio', r'aumentar\s+presupuesto',
        # Patrones con números explícitos (precio mínimo)
        r'desde\s+\d+\s*(?:millones|mm|m(?!\s*2))',
        r'mínimo\s+\d+\s*(?:millones|mm|m(?!\s*2))',
        r'por\s+encima\s+de\s+\d+'
    ],
    # Tamaño - patrones relativos y explícitos
    'bigger': [
        r'más\s+grande', r'más\s+amplio', r'más\s+espacio',
        r'más\s+metros', r'mayor\s+área',
        # Patrones con números explícitos
        r'más\s+de\s+\d+\s*m', r'mínimo\s+\d+\s*m', r'minimo\s+\d+\s*m',
        r'desde\s+\d+\s*m', r'al\s+menos\s+\d+\s*m',
        r'mayor\s+a\s+\d+', r'mayor\s+de\s+\d+',
        r'quiero\s+\d+\s*m', r'que\s+tenga\s+\d+\s*m'
    ],
    'smaller': [
        r'más\s+pequeño', r'más\s+compacto', r'menos\s+metros',
        r'menor\s+área',
        # Patrones con números explícitos
        r'menos\s+de\s+\d+\s*m', r'máximo\s+\d+\s*m', r'maximo\s+\d+\s*m',
        r'hasta\s+\d+\s*m', r'no\s+más\s+de\s+\d+\s*m'
    ],
    # Habitaciones - patrones relativos y explícitos
    'more_rooms': [
        r'más\s+habitaciones', r'más\s+cuartos', r'más\s+alcobas',
        r'otra\s+habitación', r'habitación\s+extra',
        # Patrones con números explícitos
        r'\d+\s*(?:habitaciones|alcobas|cuartos|habs?)',
        r'(?:mínimo|minimo|al\s+menos)\s+\d+\s*(?:habitaciones|alcobas|cuartos|habs?)',
        r'(?:quiero|necesito|busco)\s+\d+\s*(?:habitaciones|alcobas|cuartos|habs?)'
    ],
    'less_rooms': [
        r'menos\s+habitaciones', r'menos\s+cuartos',
        r'una\s+habitación\s+menos',
        # Patrones con números explícitos (máximo)
        r'máximo\s+\d+\s*(?:habitaciones|alcobas|cuartos|habs?)'
    ],
    # Baños - patrones relativos y explícitos
    'specific_bathrooms': [
        r'\d+\s*(?:baños?|banos?)',
        r'(?:mínimo|minimo|al\s+menos)\s+\d+\s*(?:baños?|banos?)',
        r'(?:con|que\s+tenga)\s+\d+\s*(?:baños?|banos?)'
    ],
    # Ubicación
    'different_location': [
        r'otra\s+zona', r'otro\s+barrio', r'diferente\s+ubicación',
        r'cambiar\s+de\s+zona', r'en\s+otro\s+lado'
    ],
    # Agregar amenidad
    'add_amenity': [
        r'con\s+piscina', r'que\s+tenga\s+', r'con\s+gimnasio',
        r'con\s+parqueadero', r'con\s+ascensor', r'con\s+balcón',
        r'con\s+terraza', r'con\s+portería', r'con\s+seguridad'
    ],
    # Quitar amenidad
    'remove_amenity': [
        r'sin\s+piscina', r'que\s+no\s+tenga', r'sin\s+gimnasio',
        r'sin\s+parqueadero', r'no\s+necesito'
    ]
}

# Mapeo de palabras a amenidades
AMENITY_KEYWORDS = {
    'piscina': 'piscina',
    'gimnasio': 'gimnasio',
    'parqueadero': 'parqueadero',
    'ascensor': 'ascensor',
    'balcón': 'balcón',
    'balcon': 'balcón',
    'terraza': 'terraza',
    'portería': 'portería',
    'porteria': 'portería',
    'seguridad': 'seguridad 24h',
    'zona verde': 'zonas verdes',
    'zonas verdes': 'zonas verdes',
    'bbq': 'bbq',
    'sauna': 'sauna',
    'turco': 'turco',
    'jacuzzi': 'jacuzzi',
    'cancha': 'canchas deportivas',
    'salon social': 'salón social',
    'salón social': 'salón social'
}

# =============================================================================
# v2.7: TIPOS DE REFINAMIENTO
# =============================================================================
# 1. FILTER (restringir): Reduce el scope de búsqueda
# 2. EXPAND (ampliar): Agrega criterios sin eliminar los anteriores
# 3. RESET (reiniciar): Empieza una búsqueda nueva

REFINEMENT_TYPE_PATTERNS = {
    'filter': [
        # Exactitud
        r'\bexactamente\b', r'\bexacto\b', r'\bprecisamente\b',
        # Restricción
        r'\bsolamente\b', r'\bsolo\s+(?:en|de|con)\b', r'\búnicamente\b',
        r'\bnada\s+más\b', r'\bque\s+valgan?\b', r'\bque\s+cuesten?\b',
        r'\bque\s+sean?\s+de\b', r'\bnecesito\s+(?:que\s+)?sea\b',
        # Filtros específicos
        r'\bfiltrar\b', r'\brestringir\b',
    ],
    'expand': [
        # Adición
        r'\btambién\b', r'\btambien\b', r'\bademás\b', r'\bademas\b',
        r'\bagregar\b', r'\bincluir\b', r'\bañadir\b',
        # Mostrar más opciones
        r'\bmuéstrame\s+también\b', r'\bmuestrame\s+tambien\b',
        r'\by\s+también\b', r'\bo\s+también\b',
        r'\bque\s+(?:también|tambien)\s+(?:tenga|tengan|sea|sean)\b',
        # Ampliar
        r'\bampliar\b', r'\bexpandir\b',
    ],
    'reset': [
        # Negación + nueva dirección
        r'^no[,.]?\s+', r'\bno,\s+', r'\bmejor\b', r'\bmás\s+bien\b', r'\bmas\s+bien\b',
        r'\ben\s+cambio\b', r'\ben\s+vez\s+de\b',
        # Cancelación
        r'\bolvida(?:lo)?\b', r'\bignora\b', r'\bdescarta\b',
        r'\botra\s+cosa\b', r'\bempezar\s+de\s+nuevo\b', r'\bnueva\s+búsqueda\b',
        # Cambio completo
        r'\bcambiemos\b', r'\bcambia\s+(?:la|el|los|las)\b',
        r'\bquiero\s+(?:otra|otro|cambiar)\b',
    ]
}


def detect_refinement_type(message: str, previous_criteria: Dict = None) -> str:
    """
    Detecta el tipo de refinamiento basado en el mensaje.

    Args:
        message: Mensaje del usuario
        previous_criteria: Criterios anteriores (para contexto)

    Returns:
        'filter' - Restringir búsqueda actual
        'expand' - Ampliar criterios
        'reset' - Reiniciar búsqueda
        'modify' - Modificación normal (default)
    """
    message_lower = message.lower().strip()

    # Verificar patrones de RESET primero (tienen prioridad)
    for pattern in REFINEMENT_TYPE_PATTERNS['reset']:
        if re.search(pattern, message_lower):
            print(f"[DEBUG] v2.7: Detectado RESET por patrón: {pattern}")
            return 'reset'

    # Verificar patrones de EXPAND
    for pattern in REFINEMENT_TYPE_PATTERNS['expand']:
        if re.search(pattern, message_lower):
            print(f"[DEBUG] v2.7: Detectado EXPAND por patrón: {pattern}")
            return 'expand'

    # Verificar patrones de FILTER
    for pattern in REFINEMENT_TYPE_PATTERNS['filter']:
        if re.search(pattern, message_lower):
            print(f"[DEBUG] v2.7: Detectado FILTER por patrón: {pattern}")
            return 'filter'

    # Default: modificación normal
    return 'modify'


def detect_refinement_intent(message: str) -> Dict[str, Any]:
    """
    Detecta la intención de refinamiento en el mensaje

    Returns:
        Dict con intenciones detectadas y modificadores
    """
    message_lower = message.lower()
    intents = {}

    for intent_type, patterns in REFINEMENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, message_lower):
                intents[intent_type] = True
                break

    # Detectar amenidades a agregar
    if 'add_amenity' in intents:
        amenities_to_add = []
        for keyword, amenity in AMENITY_KEYWORDS.items():
            if keyword in message_lower and f'sin {keyword}' not in message_lower:
                if f'con {keyword}' in message_lower or f'que tenga {keyword}' in message_lower:
                    amenities_to_add.append(amenity)
        if amenities_to_add:
            intents['amenities_to_add'] = amenities_to_add

    # Detectar amenidades a quitar
    if 'remove_amenity' in intents:
        amenities_to_remove = []
        for keyword, amenity in AMENITY_KEYWORDS.items():
            if f'sin {keyword}' in message_lower or f'no necesito {keyword}' in message_lower:
                amenities_to_remove.append(amenity)
        if amenities_to_remove:
            intents['amenities_to_remove'] = amenities_to_remove

    return intents


def extract_explicit_area(message: str) -> Dict[str, int]:
    """
    Extrae área explícita del mensaje si se menciona un número de metros.

    Ejemplos:
        "quiero más de 100 m2" -> {'area_min': 100}
        "máximo 150 metros" -> {'area_max': 150}
        "entre 80 y 120 m2" -> {'area_min': 80, 'area_max': 120}

    Args:
        message: Mensaje del usuario

    Returns:
        Dict con area_min y/o area_max si se encuentran
    """
    message_lower = message.lower()
    result = {}

    # Patrón para rango de área: "entre X y Y m2"
    range_pattern = r'entre\s+(\d+)\s*(?:y|a)\s*(\d+)\s*(?:m2?|metros?)'
    range_match = re.search(range_pattern, message_lower)
    if range_match:
        result['area_min'] = int(range_match.group(1))
        result['area_max'] = int(range_match.group(2))
        return result

    # Patrones para área mínima: "más de X", "mínimo X", "desde X", "al menos X", "quiero X"
    min_patterns = [
        r'(?:más|mayor)\s+de\s+(\d+)\s*(?:m2?|metros?)',
        r'(?:mínimo|minimo|desde|al\s+menos)\s+(\d+)\s*(?:m2?|metros?)',
        r'(?:quiero|necesito|busco)\s+(?:más\s+de\s+)?(\d+)\s*(?:m2?|metros?)',
        r'(\d+)\s*(?:m2?|metros?)\s+(?:o\s+más|para\s+arriba|mínimo)',
    ]

    for pattern in min_patterns:
        match = re.search(pattern, message_lower)
        if match:
            result['area_min'] = int(match.group(1))
            break

    # Patrones para área máxima: "menos de X", "máximo X", "hasta X"
    max_patterns = [
        r'(?:menos|menor)\s+de\s+(\d+)\s*(?:m2?|metros?)',
        r'(?:máximo|maximo|hasta|no\s+más\s+de)\s+(\d+)\s*(?:m2?|metros?)',
        r'(\d+)\s*(?:m2?|metros?)\s+(?:máximo|o\s+menos|para\s+abajo)',
    ]

    for pattern in max_patterns:
        match = re.search(pattern, message_lower)
        if match:
            result['area_max'] = int(match.group(1))
            break

    return result


def extract_explicit_price(message: str) -> Dict[str, int]:
    """
    Extrae precio explícito del mensaje en formato colombiano.

    Ejemplos:
        "hasta 800 millones" -> {'precio_max': 800000000}
        "menos de 1200 MM" -> {'precio_max': 1200000000}
        "entre 500 y 800 millones" -> {'precio_min': 500000000, 'precio_max': 800000000}
        "máximo $1.200" -> {'precio_max': 1200000000}

    Args:
        message: Mensaje del usuario

    Returns:
        Dict con precio_min y/o precio_max si se encuentran
    """
    message_lower = message.lower()
    result = {}

    # Función auxiliar para convertir número a COP
    def parse_price(value_str: str) -> int:
        # Limpiar el string
        value_str = value_str.replace('.', '').replace(',', '').replace('$', '').strip()
        try:
            value = int(value_str)
            # Si el valor es pequeño, asumir millones
            if value < 10000:
                return value * 1_000_000
            return value
        except ValueError:
            return 0

    # Patrón para rango de precio: "entre X y Y millones"
    range_patterns = [
        r'entre\s+(\d+(?:\.\d+)?)\s*(?:y|a)\s*(\d+(?:\.\d+)?)\s*(?:millones|mm|m(?!\s*2))',
        r'de\s+(\d+(?:\.\d+)?)\s*a\s*(\d+(?:\.\d+)?)\s*(?:millones|mm|m(?!\s*2))',
    ]
    for pattern in range_patterns:
        match = re.search(pattern, message_lower)
        if match:
            result['precio_min'] = parse_price(match.group(1))
            result['precio_max'] = parse_price(match.group(2))
            return result

    # Patrones para precio máximo: "hasta X", "máximo X", "menos de X", "no supere X"
    max_patterns = [
        r'(?:hasta|máximo|maximo|tope(?:\s+de)?)\s+(?:los\s+)?\$?\s*(\d+(?:\.\d+)?)\s*(?:millones|mm|m(?!\s*2))?',
        r'(?:menos|menor)\s+de\s+(?:los\s+)?\$?\s*(\d+(?:\.\d+)?)\s*(?:millones|mm|m(?!\s*2))?',
        r'no\s+(?:supere?|pase\s+de)\s+(?:los\s+)?\$?\s*(\d+(?:\.\d+)?)\s*(?:millones|mm|m(?!\s*2))?',
        r'(?:precio|valor|presupuesto)\s+(?:de\s+)?(?:hasta|máximo)?\s*\$?\s*(\d+(?:\.\d+)?)\s*(?:millones|mm|m(?!\s*2))?',
        r'\$?\s*(\d+(?:\.\d+)?)\s*(?:millones|mm)\s+(?:máximo|o\s+menos|para\s+abajo)',
    ]

    for pattern in max_patterns:
        match = re.search(pattern, message_lower)
        if match:
            price = parse_price(match.group(1))
            if price > 0:
                result['precio_max'] = price
                break

    # Patrones para precio mínimo: "desde X", "mínimo X", "por encima de X"
    min_patterns = [
        r'(?:desde|mínimo|minimo)\s+\$?\s*(\d+(?:\.\d+)?)\s*(?:millones|mm|m(?!\s*2))?',
        r'por\s+encima\s+de\s+\$?\s*(\d+(?:\.\d+)?)\s*(?:millones|mm|m(?!\s*2))?',
        r'(?:más|mayor)\s+de\s+\$?\s*(\d+(?:\.\d+)?)\s*(?:millones|mm|m(?!\s*2))?',
    ]

    for pattern in min_patterns:
        match = re.search(pattern, message_lower)
        if match:
            price = parse_price(match.group(1))
            if price > 0:
                result['precio_min'] = price
                break

    return result


def extract_explicit_rooms(message: str) -> Dict[str, int]:
    """
    Extrae número de habitaciones y baños explícito del mensaje.

    Ejemplos:
        "quiero 3 habitaciones" -> {'habitaciones_min': 3}
        "mínimo 2 alcobas" -> {'habitaciones_min': 2}
        "con 2 baños" -> {'banos_min': 2}
        "3 habitaciones y 2 baños" -> {'habitaciones_min': 3, 'banos_min': 2}
        "máximo 3 habitaciones" -> {'habitaciones_max': 3}

    Args:
        message: Mensaje del usuario

    Returns:
        Dict con habitaciones_min/max y/o banos_min/max si se encuentran
    """
    message_lower = message.lower()
    result = {}

    # IMPORTANTE: Verificar patrones de MÁXIMO primero antes de mínimo
    # para evitar que "máximo 3 habitaciones" capture como mínimo

    # Patrones para habitaciones máximo (verificar primero)
    hab_max_patterns = [
        r'(?:máximo|maximo|hasta|no\s+más\s+de)\s+(\d+)\s*(?:habitaciones|alcobas|cuartos|habs?)',
        r'(\d+)\s*(?:habitaciones|alcobas|cuartos|habs?)\s+(?:máximo|maximo|o\s+menos)',
    ]

    has_hab_max = False
    for pattern in hab_max_patterns:
        match = re.search(pattern, message_lower)
        if match:
            result['habitaciones_max'] = int(match.group(1))
            has_hab_max = True
            break

    # Patrones para habitaciones mínimo (solo si no es máximo)
    if not has_hab_max:
        hab_min_patterns = [
            r'(?:mínimo|minimo|al\s+menos|desde)\s+(\d+)\s*(?:habitaciones|alcobas|cuartos|habs?)',
            r'(?:quiero|necesito|busco|con)\s+(\d+)\s*(?:habitaciones|alcobas|cuartos|habs?)',
            r'(\d+)\s*(?:habitaciones|alcobas|cuartos|habs?)\s+(?:o\s+más|mínimo|para\s+arriba)',
            r'(\d+)\s*(?:habitaciones|alcobas|cuartos|habs?)(?:\s|,|$)',
        ]

        for pattern in hab_min_patterns:
            match = re.search(pattern, message_lower)
            if match:
                result['habitaciones_min'] = int(match.group(1))
                break

    # Patrones para baños máximo (verificar primero)
    bano_max_patterns = [
        r'(?:máximo|maximo|hasta|no\s+más\s+de)\s+(\d+)\s*(?:baños?|banos?)',
        r'(\d+)\s*(?:baños?|banos?)\s+(?:máximo|maximo|o\s+menos)',
    ]

    has_bano_max = False
    for pattern in bano_max_patterns:
        match = re.search(pattern, message_lower)
        if match:
            result['banos_max'] = int(match.group(1))
            has_bano_max = True
            break

    # Patrones para baños mínimo (solo si no es máximo)
    if not has_bano_max:
        bano_min_patterns = [
            r'(?:mínimo|minimo|al\s+menos|desde)\s+(\d+)\s*(?:baños?|banos?)',
            r'(?:quiero|necesito|busco|con)\s+(\d+)\s*(?:baños?|banos?)',
            r'(\d+)\s*(?:baños?|banos?)\s+(?:o\s+más|mínimo|para\s+arriba)',
            r'(\d+)\s*(?:baños?|banos?)(?:\s|,|$)',
        ]

        for pattern in bano_min_patterns:
            match = re.search(pattern, message_lower)
            if match:
                result['banos_min'] = int(match.group(1))
                break

    return result


def extract_all_explicit_criteria(message: str) -> Dict[str, Any]:
    """
    Extrae todos los criterios explícitos del mensaje.
    Combina área, precio, habitaciones y baños.

    Args:
        message: Mensaje del usuario

    Returns:
        Dict con todos los criterios explícitos encontrados
    """
    result = {}

    # Extraer área
    area = extract_explicit_area(message)
    if area:
        result.update(area)

    # Extraer precio
    price = extract_explicit_price(message)
    if price:
        result.update(price)

    # Extraer habitaciones y baños
    rooms = extract_explicit_rooms(message)
    if rooms:
        result.update(rooms)

    return result


def merge_criteria(previous: Dict, new: Dict, message: str) -> Dict:
    """
    Fusiona criterios anteriores con nuevos criterios extraídos.

    Reglas de fusión:
    1. Criterios explícitos en el mensaje SIEMPRE tienen prioridad
    2. Criterios de Claude (new) sobrescriben si están presentes
    3. Palabras clave de refinamiento ajustan valores relativamente
    4. Criterios anteriores se mantienen si no se mencionan
    5. v2.5: Campos de configuración del sistema (hard_filters, priority_weights,
       selected_priority, search_state) SIEMPRE se preservan del previous
    6. v2.7: Detección mejorada de mensajes de refinamiento cortos

    Args:
        previous: Criterios acumulados anteriores
        new: Criterios extraídos del mensaje actual por Claude
        message: Mensaje original del usuario

    Returns:
        Dict con criterios fusionados
    """
    # v2.7: Detectar si es un mensaje de refinamiento corto
    # Si el mensaje es muy corto y/o tiene pocos criterios nuevos,
    # probablemente es un refinamiento parcial
    word_count = len(message.split())
    new_criteria_count = sum(1 for k, v in new.items()
                              if v is not None and v != '' and v != []
                              and k not in ['original_query', 'notas', 'perfil_comprador'])

    is_short_refinement = (
        previous and  # Hay criterios anteriores
        word_count < 12 and  # Mensaje corto (ej: "más baratas", "3 habitaciones", "con piscina")
        new_criteria_count < 4  # Pocos criterios nuevos extraídos
    )

    if is_short_refinement:
        print(f"[DEBUG] v2.7: Detectado refinamiento corto (palabras={word_count}, criterios_nuevos={new_criteria_count})")

    # Empezar con copia de criterios anteriores
    merged = {**previous} if previous else {}

    # v2.5: PRESERVAR campos de configuración del sistema de búsqueda
    # Estos campos NO deben sobrescribirse con los nuevos criterios
    SYSTEM_CONFIG_FIELDS = [
        'hard_filters',
        'priority_weights',
        'selected_priority',
        'search_state',
        'flexibilidad_habitaciones',
        'flexibilidad_precio',
        # v2.6: Campos calculados de filtros SQL (CRÍTICOS)
        'precio_min_implicito',
        'precio_max_ajustado',
        'habitaciones_min_filtro',
        'habitaciones_max_filtro',
        'segmento_precio',
        'tolerancia_aplicada'
    ]

    preserved_config = {}
    if previous:
        for field in SYSTEM_CONFIG_FIELDS:
            # v2.6: Usar 'is not None' para preservar valores como 0
            if field in previous and previous[field] is not None:
                preserved_config[field] = previous[field]

    # Detectar intenciones de refinamiento
    intents = detect_refinement_intent(message)

    # v2.7: Detectar TIPO de refinamiento (filter, expand, reset, modify)
    refinement_type = detect_refinement_type(message, previous)
    print(f"[DEBUG] v2.7: Tipo de refinamiento detectado: {refinement_type}")

    # ==========================================================================
    # MANEJO DE RESET: Reiniciar búsqueda completamente
    # ==========================================================================
    if refinement_type == 'reset':
        print(f"[DEBUG] v2.7: RESET - Reiniciando búsqueda, descartando criterios anteriores")
        # Solo preservar la configuración del sistema, descartar criterios de búsqueda
        merged = {}
        # Aplicar los nuevos criterios directamente
        for key, value in new.items():
            if value is not None and value != '' and value != []:
                merged[key] = value
        # Restaurar configuración del sistema
        for field, value in preserved_config.items():
            merged[field] = value
        return merged

    # Extraer TODOS los criterios explícitos del mensaje
    explicit = extract_all_explicit_criteria(message)

    # ============================================================
    # 1. PRECIO - Manejar refinamiento de precio
    # ============================================================
    if intents.get('cheaper'):
        if explicit.get('precio_max'):
            # Si hay precio explícito, usar ese
            merged['precio_max'] = explicit['precio_max']
        elif merged.get('precio_max'):
            # Si no hay precio explícito, reducir 20%
            merged['precio_max'] = int(merged['precio_max'] * 0.8)
        if new.get('precio_max'):
            # Si Claude extrajo un precio, usar el menor
            merged['precio_max'] = min(merged.get('precio_max', float('inf')), new['precio_max'])

    if intents.get('more_expensive'):
        if explicit.get('precio_min'):
            merged['precio_min'] = explicit['precio_min']
        elif merged.get('precio_max'):
            merged['precio_max'] = int(merged['precio_max'] * 1.25)

    # ============================================================
    # 2. ÁREA - Manejar refinamiento de área
    # ============================================================
    if intents.get('bigger'):
        if explicit.get('area_min'):
            merged['area_min'] = explicit['area_min']
        elif merged.get('area_min'):
            merged['area_min'] = int(merged['area_min'] * 1.2)

    if intents.get('smaller'):
        if explicit.get('area_max'):
            merged['area_max'] = explicit['area_max']
        else:
            if merged.get('area_min'):
                merged['area_min'] = int(merged['area_min'] * 0.8)
            if merged.get('area_max'):
                merged['area_max'] = int(merged['area_max'] * 0.8)

    # ============================================================
    # 3. HABITACIONES - Manejar refinamiento de habitaciones
    # ============================================================
    if intents.get('more_rooms'):
        if explicit.get('habitaciones_min'):
            # Si hay número explícito, usar ese
            merged['habitaciones_min'] = explicit['habitaciones_min']
        elif merged.get('habitaciones_min'):
            # Si no, aumentar en 1
            merged['habitaciones_min'] = merged['habitaciones_min'] + 1

    if intents.get('less_rooms'):
        if explicit.get('habitaciones_max'):
            merged['habitaciones_max'] = explicit['habitaciones_max']
        else:
            if merged.get('habitaciones_min') and merged['habitaciones_min'] > 1:
                merged['habitaciones_min'] = merged['habitaciones_min'] - 1
            if merged.get('habitaciones_max'):
                merged['habitaciones_max'] = merged['habitaciones_max'] - 1

    # ============================================================
    # 4. BAÑOS - Manejar refinamiento de baños
    # ============================================================
    if intents.get('specific_bathrooms'):
        if explicit.get('banos_min'):
            merged['banos_min'] = explicit['banos_min']
        if explicit.get('banos_max'):
            merged['banos_max'] = explicit['banos_max']

    # ============================================================
    # 5. UBICACIÓN - Limpiar si pide otra zona
    # ============================================================
    if intents.get('different_location'):
        merged.pop('ubicaciones', None)

    # ============================================================
    # 6. AMENIDADES - Agregar/quitar amenidades
    # ============================================================
    current_amenities = set(merged.get('amenidades_requeridas', []))

    if intents.get('amenities_to_add'):
        current_amenities.update(intents['amenities_to_add'])

    if intents.get('amenities_to_remove'):
        for amenity in intents['amenities_to_remove']:
            current_amenities.discard(amenity)

    if current_amenities:
        merged['amenidades_requeridas'] = list(current_amenities)

    # ============================================================
    # 7. APLICAR CRITERIOS DE CLAUDE
    # v2.7: Manejo diferenciado según tipo de refinamiento:
    #       - FILTER: Restringe (reemplaza con valores más estrictos)
    #       - EXPAND: Amplía (agrega sin eliminar lo anterior)
    #       - MODIFY: Normal (comportamiento por defecto)
    # ============================================================

    # Campos clave que deben preservarse en refinamientos cortos
    CAMPOS_CLAVE_REFINAMIENTO = [
        'ubicaciones', 'tipo_propiedad', 'precio_max', 'precio_min',
        'habitaciones_min', 'habitaciones_max', 'banos_min', 'banos_max',
        'area_min', 'area_max'
    ]

    for key, value in new.items():
        if value is not None:
            # ==========================================================
            # EXPAND: Agregar criterios sin eliminar los anteriores
            # ==========================================================
            if refinement_type == 'expand':
                if key == 'ubicaciones' and value:
                    # Agregar nuevas ubicaciones a las existentes
                    existing = merged.get('ubicaciones', [])
                    if isinstance(existing, list):
                        for loc in value:
                            if loc not in existing:
                                existing.append(loc)
                        merged['ubicaciones'] = existing
                    else:
                        merged['ubicaciones'] = value
                elif key == 'habitaciones_max' and value:
                    # Expandir rango de habitaciones hacia arriba
                    if merged.get('habitaciones_max'):
                        merged['habitaciones_max'] = max(merged['habitaciones_max'], value)
                    else:
                        merged['habitaciones_max'] = value
                elif key == 'habitaciones_min' and value:
                    # Expandir rango de habitaciones hacia abajo
                    if merged.get('habitaciones_min'):
                        merged['habitaciones_min'] = min(merged['habitaciones_min'], value)
                    else:
                        merged['habitaciones_min'] = value
                elif key == 'precio_max' and value:
                    # Expandir presupuesto hacia arriba
                    if merged.get('precio_max'):
                        merged['precio_max'] = max(merged['precio_max'], value)
                    else:
                        merged['precio_max'] = value
                elif key == 'tipo_propiedad' and value:
                    # Agregar tipos de propiedad
                    existing = merged.get('tipo_propiedad', [])
                    if isinstance(existing, str):
                        existing = [existing]
                    if isinstance(value, str):
                        value = [value]
                    for t in value:
                        if t not in existing:
                            existing.append(t)
                    merged['tipo_propiedad'] = existing if len(existing) > 1 else existing[0]
                elif value:
                    merged[key] = value

            # ==========================================================
            # FILTER: Restringir (el nuevo valor reemplaza, es más estricto)
            # ==========================================================
            elif refinement_type == 'filter':
                if isinstance(value, list) and len(value) == 0:
                    continue
                if isinstance(value, str) and value.strip() == '':
                    continue
                # En modo filtro, los nuevos valores siempre reemplazan
                merged[key] = value

            # ==========================================================
            # MODIFY (normal) o refinamiento corto
            # ==========================================================
            elif is_short_refinement:
                # Para refinamientos cortos, solo aplicar si:
                # 1. El campo NO es un campo clave O
                # 2. El valor es significativo (no vacío, no lista vacía)
                if key in CAMPOS_CLAVE_REFINAMIENTO:
                    # Solo sobrescribir campos clave si tienen valor real
                    if isinstance(value, list) and len(value) == 0:
                        continue  # No sobrescribir con lista vacía
                    if isinstance(value, str) and value.strip() == '':
                        continue  # No sobrescribir con string vacío
                    # Para ubicaciones, solo aplicar si no hay intención "different_location"
                    # y el nuevo valor es diferente del anterior
                    if key == 'ubicaciones':
                        if not intents.get('different_location') and merged.get('ubicaciones'):
                            # Solo actualizar si hay nuevas zonas mencionadas explícitamente
                            if value == merged.get('ubicaciones'):
                                continue
                        merged[key] = value
                    elif key == 'precio_max' and value:
                        if not merged.get('precio_max') or value < merged['precio_max']:
                            merged[key] = value
                        elif intents.get('more_expensive'):
                            merged[key] = value
                    elif value:
                        merged[key] = value
                else:
                    # Campos no clave: aplicar normalmente
                    if value:
                        merged[key] = value
            else:
                # Flujo normal (no refinamiento corto)
                if key == 'ubicaciones' and value:
                    merged[key] = value
                elif key == 'precio_max' and value:
                    if not merged.get('precio_max') or value < merged['precio_max']:
                        merged[key] = value
                    elif intents.get('more_expensive'):
                        merged[key] = value
                elif value:
                    merged[key] = value

    # ============================================================
    # 8. FALLBACK - Aplicar criterios explícitos del mensaje
    # Esto asegura que si el usuario menciona un valor explícito,
    # se use aunque Claude no lo haya extraído
    # ============================================================
    if explicit:
        # Área
        if explicit.get('area_min') and not new.get('area_min'):
            merged['area_min'] = explicit['area_min']
        if explicit.get('area_max') and not new.get('area_max'):
            merged['area_max'] = explicit['area_max']

        # Precio
        if explicit.get('precio_max') and not new.get('precio_max'):
            merged['precio_max'] = explicit['precio_max']
        if explicit.get('precio_min') and not new.get('precio_min'):
            merged['precio_min'] = explicit['precio_min']

        # Habitaciones
        if explicit.get('habitaciones_min') and not new.get('habitaciones_min'):
            merged['habitaciones_min'] = explicit['habitaciones_min']
        if explicit.get('habitaciones_max') and not new.get('habitaciones_max'):
            merged['habitaciones_max'] = explicit['habitaciones_max']

        # Baños
        if explicit.get('banos_min') and not new.get('banos_min'):
            merged['banos_min'] = explicit['banos_min']
        if explicit.get('banos_max') and not new.get('banos_max'):
            merged['banos_max'] = explicit['banos_max']

    # ============================================================
    # 9. v2.5: RESTAURAR campos de configuración del sistema
    # Estos campos NUNCA deben perderse durante el merge
    # ============================================================
    for field, value in preserved_config.items():
        merged[field] = value

    return merged


def generate_conversation_name(criteria: Dict) -> Optional[str]:
    """
    Genera un nombre descriptivo para la conversación basado en los criterios.

    Ejemplos:
        - "Apartamento Laureles $500M"
        - "Casa El Poblado piscina"
        - "Apto 3 hab Envigado"

    Args:
        criteria: Criterios de búsqueda

    Returns:
        Nombre generado o None si no hay suficiente info
    """
    parts = []

    # Tipo de propiedad (abreviado)
    # v2.6: Manejar cuando tipo_propiedad es lista (ej: ["Casa", "Apartamento"])
    tipo = criteria.get('tipo_propiedad', '')
    if tipo:
        # Si es lista, unir con "/" o usar el primero
        if isinstance(tipo, list):
            tipo_str = ' '.join(tipo).lower()
        else:
            tipo_str = tipo.lower()

        if 'apartamento' in tipo_str:
            parts.append('Apto')
        elif 'casa' in tipo_str:
            parts.append('Casa')
        elif 'penthouse' in tipo_str:
            parts.append('PH')
        elif 'local' in tipo_str:
            parts.append('Local')
        elif 'oficina' in tipo_str:
            parts.append('Oficina')
        else:
            # Si es lista, usar el primer elemento
            if isinstance(tipo, list):
                parts.append(tipo[0][:6] if tipo else 'Prop')
            else:
                parts.append(tipo.capitalize()[:6])

    # Ubicación (primera)
    ubicaciones = criteria.get('ubicaciones', [])
    if ubicaciones and isinstance(ubicaciones, list) and len(ubicaciones) > 0:
        parts.append(ubicaciones[0])

    # Habitaciones
    hab_min = criteria.get('habitaciones_min')
    if hab_min:
        parts.append(f"{hab_min} hab")

    # Precio (en millones)
    precio_max = criteria.get('precio_max')
    if precio_max:
        millones = int(precio_max / 1_000_000)
        if millones >= 1000:
            parts.append(f"${millones/1000:.1f}B")
        else:
            parts.append(f"${millones}M")

    # Si no hay suficiente info, retornar None
    if len(parts) < 2:
        return None

    return ' '.join(parts)


def summarize_criteria(criteria: Dict) -> str:
    """
    Genera un resumen legible de los criterios para mostrar al usuario.

    Args:
        criteria: Criterios de búsqueda

    Returns:
        Resumen en texto
    """
    parts = []

    if criteria.get('tipo_propiedad'):
        parts.append(f"Tipo: {criteria['tipo_propiedad']}")

    if criteria.get('ubicaciones'):
        ubicaciones = criteria['ubicaciones']
        if isinstance(ubicaciones, list):
            parts.append(f"Ubicación: {', '.join(ubicaciones[:3])}")
        else:
            parts.append(f"Ubicación: {ubicaciones}")

    if criteria.get('precio_max'):
        millones = int(criteria['precio_max'] / 1_000_000)
        parts.append(f"Hasta: ${millones:,}M")

    if criteria.get('precio_min'):
        millones = int(criteria['precio_min'] / 1_000_000)
        parts.append(f"Desde: ${millones:,}M")

    if criteria.get('habitaciones_min'):
        parts.append(f"Habitaciones: {criteria['habitaciones_min']}+")

    if criteria.get('banos_min'):
        parts.append(f"Baños: {criteria['banos_min']}+")

    if criteria.get('area_min'):
        parts.append(f"Área mín: {criteria['area_min']}m²")

    if criteria.get('amenidades_requeridas'):
        amenidades = criteria['amenidades_requeridas']
        if isinstance(amenidades, list) and amenidades:
            parts.append(f"Con: {', '.join(amenidades[:3])}")

    return ' | '.join(parts) if parts else 'Sin criterios específicos'
