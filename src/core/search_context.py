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
    # Precio
    'cheaper': [
        r'más\s+barato', r'más\s+económico', r'menos\s+caro',
        r'menor\s+precio', r'más\s+accesible', r'rebajado'
    ],
    'more_expensive': [
        r'más\s+caro', r'mayor\s+presupuesto', r'más\s+costoso',
        r'subir\s+el\s+precio', r'aumentar\s+presupuesto'
    ],
    # Tamaño
    'bigger': [
        r'más\s+grande', r'más\s+amplio', r'más\s+espacio',
        r'más\s+metros', r'mayor\s+área'
    ],
    'smaller': [
        r'más\s+pequeño', r'más\s+compacto', r'menos\s+metros',
        r'menor\s+área'
    ],
    # Habitaciones
    'more_rooms': [
        r'más\s+habitaciones', r'más\s+cuartos', r'más\s+alcobas',
        r'otra\s+habitación', r'habitación\s+extra'
    ],
    'less_rooms': [
        r'menos\s+habitaciones', r'menos\s+cuartos',
        r'una\s+habitación\s+menos'
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


def merge_criteria(previous: Dict, new: Dict, message: str) -> Dict:
    """
    Fusiona criterios anteriores con nuevos criterios extraídos.

    Reglas de fusión:
    1. Campos explícitos en new SIEMPRE sobrescriben
    2. Campos no mencionados en new SE MANTIENEN de previous
    3. Palabras clave de refinamiento ajustan valores relativamente
    4. "otra zona" limpia ubicaciones

    Args:
        previous: Criterios acumulados anteriores
        new: Criterios extraídos del mensaje actual
        message: Mensaje original del usuario

    Returns:
        Dict con criterios fusionados
    """
    # Empezar con copia de criterios anteriores
    merged = {**previous} if previous else {}

    # Detectar intenciones de refinamiento
    intents = detect_refinement_intent(message)

    # Aplicar refinamientos relativos
    if intents.get('cheaper'):
        if merged.get('precio_max'):
            merged['precio_max'] = int(merged['precio_max'] * 0.8)
        if new.get('precio_max'):
            merged['precio_max'] = min(merged.get('precio_max', float('inf')), new['precio_max'])

    if intents.get('more_expensive'):
        if merged.get('precio_max'):
            merged['precio_max'] = int(merged['precio_max'] * 1.25)

    if intents.get('bigger'):
        if merged.get('area_min'):
            merged['area_min'] = int(merged['area_min'] * 1.2)

    if intents.get('smaller'):
        if merged.get('area_min'):
            merged['area_min'] = int(merged['area_min'] * 0.8)
        if merged.get('area_max'):
            merged['area_max'] = int(merged['area_max'] * 0.8)

    if intents.get('more_rooms'):
        if merged.get('habitaciones_min'):
            merged['habitaciones_min'] = merged['habitaciones_min'] + 1

    if intents.get('less_rooms'):
        if merged.get('habitaciones_min') and merged['habitaciones_min'] > 1:
            merged['habitaciones_min'] = merged['habitaciones_min'] - 1
        if merged.get('habitaciones_max'):
            merged['habitaciones_max'] = merged['habitaciones_max'] - 1

    # Limpiar ubicaciones si pide otra zona
    if intents.get('different_location'):
        merged.pop('ubicaciones', None)

    # Manejar amenidades
    current_amenities = set(merged.get('amenidades_requeridas', []))

    if intents.get('amenities_to_add'):
        current_amenities.update(intents['amenities_to_add'])

    if intents.get('amenities_to_remove'):
        for amenity in intents['amenities_to_remove']:
            current_amenities.discard(amenity)

    if current_amenities:
        merged['amenidades_requeridas'] = list(current_amenities)

    # Aplicar nuevos criterios (sobrescriben si están explícitos)
    for key, value in new.items():
        if value is not None:
            # Para ubicaciones, si new tiene ubicaciones, reemplazar (es explícito)
            if key == 'ubicaciones' and value:
                merged[key] = value
            # Para precio_max, si new tiene uno más bajo, usar ese
            elif key == 'precio_max' and value:
                if not merged.get('precio_max') or value < merged['precio_max']:
                    merged[key] = value
                elif intents.get('more_expensive'):
                    # Si pide más caro pero especifica un precio, usar ese
                    merged[key] = value
            # Para otros campos, sobrescribir si no es None
            elif value:
                merged[key] = value

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
