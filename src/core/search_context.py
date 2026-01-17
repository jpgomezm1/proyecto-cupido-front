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

    Args:
        previous: Criterios acumulados anteriores
        new: Criterios extraídos del mensaje actual por Claude
        message: Mensaje original del usuario

    Returns:
        Dict con criterios fusionados
    """
    # Empezar con copia de criterios anteriores
    merged = {**previous} if previous else {}

    # Detectar intenciones de refinamiento
    intents = detect_refinement_intent(message)

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
    # 7. APLICAR CRITERIOS DE CLAUDE (sobrescriben si están explícitos)
    # ============================================================
    for key, value in new.items():
        if value is not None:
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
    tipo = criteria.get('tipo_propiedad', '')
    if tipo:
        tipo_lower = tipo.lower()
        if 'apartamento' in tipo_lower:
            parts.append('Apto')
        elif 'casa' in tipo_lower:
            parts.append('Casa')
        elif 'penthouse' in tipo_lower:
            parts.append('PH')
        elif 'local' in tipo_lower:
            parts.append('Local')
        elif 'oficina' in tipo_lower:
            parts.append('Oficina')
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
