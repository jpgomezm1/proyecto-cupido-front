#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuración del Sistema de Búsqueda Inteligente v2.1
Parámetros específicos para el mercado inmobiliario colombiano

MEJORAS v2.1:
- Normalización de nombres de zona a forma canónica
- Landmarks con coordenadas para búsqueda geoespacial
- Mapeo de landmarks a zonas
"""

import unicodedata
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class SegmentoPrecio(Enum):
    """Segmentos de precio del mercado inmobiliario colombiano"""
    VIS = "vis"
    ACCESIBLE = "accesible"
    MEDIO = "medio"
    MEDIO_ALTO = "medio_alto"
    PREMIUM = "premium"
    LUJO = "lujo"


class PerfilComprador(Enum):
    """Perfiles de comprador detectables"""
    FAMILIA = "familia"
    INVERSIONISTA = "inversionista"
    SENIOR = "senior"
    JOVEN_PROFESIONAL = "joven_profesional"
    GENERAL = "general"


# =============================================================================
# SEGMENTOS DE PRECIO - MERCADO COLOMBIANO 2024-2025
# =============================================================================

SEGMENTOS_PRECIO_COLOMBIA: Dict[str, Tuple[int, int]] = {
    'vis': (0, 200_000_000),                    # Hasta $200M
    'accesible': (200_000_000, 400_000_000),    # $200M - $400M
    'medio': (400_000_000, 700_000_000),        # $400M - $700M
    'medio_alto': (700_000_000, 1_200_000_000), # $700M - $1.200M
    'premium': (1_200_000_000, 2_500_000_000),  # $1.200M - $2.500M
    'lujo': (2_500_000_000, float('inf'))       # $2.500M+
}

# Tolerancia de precio por segmento (qué tanto puede variar del presupuesto)
# v2.2: Tolerancia uniforme del 10% para todos los segmentos
TOLERANCIA_PRECIO_POR_SEGMENTO: Dict[str, float] = {
    'vis': 0.10,        # ±10%
    'accesible': 0.10,  # ±10%
    'medio': 0.10,      # ±10%
    'medio_alto': 0.10, # ±10%
    'premium': 0.10,    # ±10%
    'lujo': 0.10        # ±10%
}

# Tolerancia por defecto si no se puede determinar segmento
TOLERANCIA_PRECIO_DEFAULT = 0.10  # ±10%


# =============================================================================
# PERFILES DE COMPRADOR Y SUS CARACTERÍSTICAS
# =============================================================================

PERFILES_COMPRADOR: Dict[str, Dict] = {
    'familia': {
        'keywords': [
            'familia', 'familias', 'niños', 'niño', 'hijos', 'hijo',
            'colegios', 'colegio', 'parque infantil', 'zona infantil',
            'espacioso', 'amplio para familia'
        ],
        'weights': {
            'seguridad': 2.0,
            'amenidades_familia': 2.0,
            'zona_residencial': 1.5,
            'parqueaderos': 1.3,
            'habitaciones': 1.5,
            'area': 1.3
        },
        'amenidades_preferidas': [
            'parque infantil', 'zona de niños', 'salón social',
            'zona verde', 'portería', 'vigilancia', 'circuito cerrado'
        ]
    },
    'inversionista': {
        'keywords': [
            'inversión', 'inversion', 'invertir', 'rentabilidad', 'renta',
            'arriendo', 'arrendar', 'valorización', 'valorizacion',
            'airbnb', 'temporal', 'retorno'
        ],
        'weights': {
            'rentabilidad': 3.0,
            'precio_competitivo': 2.5,
            'ubicacion_comercial': 2.0,
            'demanda_zona': 1.8,
            'estado_nuevo': 1.5
        },
        'amenidades_preferidas': [
            'amoblado', 'cerca a metro', 'zona comercial',
            'turístico', 'centros comerciales'
        ]
    },
    'senior': {
        'keywords': [
            'mayor', 'mayores', 'tercera edad', 'adulto mayor',
            'primer piso', 'sin escaleras', 'accesible', 'accesibilidad',
            'tranquilo', 'tranquila', 'retirado', 'jubilado'
        ],
        'weights': {
            'primer_piso': 3.0,
            'ascensor': 2.5,
            'accesibilidad': 2.0,
            'zona_tranquila': 1.8,
            'porteria': 1.5,
            'cerca_hospitales': 1.3
        },
        'amenidades_preferidas': [
            'ascensor', 'portería 24h', 'zona tranquila',
            'cerca a hospitales', 'parques', 'sin escaleras'
        ]
    },
    'joven_profesional': {
        'keywords': [
            'joven', 'soltero', 'soltera', 'profesional', 'moderno',
            'contemporáneo', 'contemporaneo', 'cerca al trabajo',
            'vida nocturna', 'gimnasio', 'coworking'
        ],
        'weights': {
            'ubicacion_central': 2.5,
            'modernidad': 2.0,
            'gimnasio': 1.8,
            'coworking': 1.5,
            'transporte': 1.5
        },
        'amenidades_preferidas': [
            'gimnasio', 'coworking', 'terraza', 'rooftop',
            'cerca a metro', 'zona gastronómica'
        ]
    },
    'general': {
        'keywords': [],
        'weights': {
            'ubicacion': 1.0,
            'precio': 1.0,
            'habitaciones': 1.0,
            'amenidades': 1.0
        },
        'amenidades_preferidas': []
    }
}


# =============================================================================
# ZONAS Y EXPANSIONES - MEDELLÍN Y ÁREA METROPOLITANA
# =============================================================================

# Mapeo de zonas a ciudad para búsquedas flexibles
ZONA_A_CIUDAD: Dict[str, str] = {
    # Medellín - Zona Sur (El Poblado)
    'poblado': 'Medellín', 'el poblado': 'Medellín',
    'castropol': 'Medellín', 'manila': 'Medellín',
    'lalinde': 'Medellín', 'astorga': 'Medellín',
    'san lucas': 'Medellín', 'el tesoro': 'Medellín',
    'los balsos': 'Medellín', 'el diamante': 'Medellín',
    'ciudad del rio': 'Medellín', 'ciudad del río': 'Medellín',

    # Medellín - Zona Centro-Occidental (Laureles/Estadio)
    'laureles': 'Medellín', 'estadio': 'Medellín',
    'conquistadores': 'Medellín', 'bolivariana': 'Medellín',
    'floresta': 'Medellín', 'la floresta': 'Medellín',
    'san joaquin': 'Medellín', 'san joaquín': 'Medellín',
    'calasanz': 'Medellín', 'santa monica': 'Medellín',
    'santa mónica': 'Medellín', 'suramericana': 'Medellín',
    'carlos e restrepo': 'Medellín',

    # Medellín - Zona Occidental (Belén)
    'belen': 'Medellín', 'belén': 'Medellín',
    'la mota': 'Medellín', 'rodeo alto': 'Medellín',
    'fatima': 'Medellín', 'fátima': 'Medellín',
    'los alpes': 'Medellín', 'la palma': 'Medellín',
    'guayabal': 'Medellín', 'trinidad': 'Medellín',

    # Medellín - Otras zonas
    'robledo': 'Medellín', 'aranjuez': 'Medellín',
    'manrique': 'Medellín', 'boston': 'Medellín',
    'buenos aires': 'Medellín', 'prado': 'Medellín',
    'centro': 'Medellín', 'la candelaria': 'Medellín',
    'castilla': 'Medellín', 'doce de octubre': 'Medellín',
    '12 de octubre': 'Medellín', 'pedregal': 'Medellín',
    'la america': 'Medellín', 'la américa': 'Medellín',
    'simon bolivar': 'Medellín', 'simón bolívar': 'Medellín',

    # Envigado
    'envigado': 'Envigado', 'zuñiga': 'Envigado', 'zúñiga': 'Envigado',
    'la paz': 'Envigado', 'el portal': 'Envigado',
    'la frontera': 'Envigado', 'el esmeraldal': 'Envigado',
    'loma del escobero': 'Envigado', 'las antillas': 'Envigado',
    'el dorado': 'Envigado', 'alcala': 'Envigado', 'alcalá': 'Envigado',
    'la cuenca': 'Envigado', 'el trianon': 'Envigado', 'el trianón': 'Envigado',

    # Sabaneta
    'sabaneta': 'Sabaneta', 'aves maria': 'Sabaneta', 'aves maría': 'Sabaneta',
    'mayorca': 'Sabaneta', 'la doctora': 'Sabaneta',
    'pan de azucar': 'Sabaneta', 'pan de azúcar': 'Sabaneta',
    'calle larga': 'Sabaneta', 'las lomitas': 'Sabaneta',

    # Itagüí
    'itagui': 'Itagüí', 'itagüí': 'Itagüí',
    'ditaires': 'Itagüí', 'santa maria': 'Itagüí',
    'santa maría': 'Itagüí', 'los naranjos': 'Itagüí',

    # Bello
    'bello': 'Bello', 'niquia': 'Bello', 'niquía': 'Bello',
    'paris': 'Bello', 'zamora': 'Bello',
    'cabañas': 'Bello', 'cabanas': 'Bello',

    # La Estrella
    'la estrella': 'La Estrella', 'pueblo viejo': 'La Estrella',

    # Caldas
    'caldas': 'Caldas', 'la clara': 'Caldas',

    # Copacabana
    'copacabana': 'Copacabana',

    # Girardota
    'girardota': 'Girardota',

    # Rionegro y Oriente
    'rionegro': 'Rionegro', 'llanogrande': 'Rionegro',
    'el retiro': 'El Retiro', 'la ceja': 'La Ceja',
    'guarne': 'Guarne', 'marinilla': 'Marinilla',
}

# Zonas similares/vecinas para expansión de búsqueda
ZONAS_SIMILARES: Dict[str, List[str]] = {
    # El Poblado y similares (estrato alto, sur)
    'poblado': ['ciudad del rio', 'lalinde', 'castropol', 'manila', 'envigado'],
    'ciudad del rio': ['poblado', 'lalinde', 'guayabal'],
    'castropol': ['poblado', 'lalinde', 'manila'],
    'lalinde': ['poblado', 'castropol', 'ciudad del rio'],

    # Laureles y similares (estrato medio-alto, occidental)
    'laureles': ['estadio', 'conquistadores', 'floresta', 'belen', 'bolivariana'],
    'estadio': ['laureles', 'conquistadores', 'floresta', 'suramericana'],
    'conquistadores': ['laureles', 'estadio', 'suramericana'],
    'floresta': ['laureles', 'estadio', 'belen', 'calasanz'],
    'belen': ['laureles', 'floresta', 'la mota', 'guayabal'],

    # Envigado - zonas DENTRO de Envigado (NO incluir otras ciudades)
    'envigado': ['zuñiga', 'la paz', 'el dorado', 'las antillas', 'alcala', 'la cuenca', 'el trianon', 'loma del escobero'],
    'loma del escobero': ['envigado', 'las palmas'],
    'zuñiga': ['envigado', 'la paz'],
    'las antillas': ['envigado', 'alcala', 'el dorado'],

    # Sabaneta - zonas DENTRO de Sabaneta (NO incluir otras ciudades)
    'sabaneta': ['aves maria', 'mayorca', 'la doctora', 'calle larga'],
    'aves maria': ['sabaneta', 'mayorca'],
    'mayorca': ['sabaneta', 'aves maria'],

    # Calasanz y occidental
    'calasanz': ['floresta', 'santa monica', 'san joaquin', 'robledo'],
    'robledo': ['calasanz', 'castilla', 'bello'],
}


# =============================================================================
# NORMALIZACIÓN DE ZONAS - v2.1
# =============================================================================

# Mapeo de variaciones → nombre canónico
ZONA_CANONICA: Dict[str, str] = {
    # El Poblado y variaciones
    'poblado': 'El Poblado',
    'el poblado': 'El Poblado',
    'santa maria poblado': 'El Poblado',
    'santa maría poblado': 'El Poblado',
    'santa maria, poblado': 'El Poblado',
    'santa maría, poblado': 'El Poblado',
    'poblado castropol': 'Castropol',
    'poblado lalinde': 'Lalinde',
    'poblado, lalinde': 'Lalinde',
    'poblado, la concha': 'El Poblado',
    'poblado, los balsos': 'Los Balsos',
    'altos del poblado': 'El Poblado',
    'el poblado ciudad del rio': 'Ciudad del Río',
    'provenza el poblado': 'El Poblado',
    'provenza, el poblado': 'El Poblado',
    'el poblado, provenza': 'El Poblado',
    'poblado san lucas': 'San Lucas',
    'san lucas (poblado)': 'San Lucas',
    'poblado i el campestre': 'El Poblado',

    # Laureles y variaciones
    'laureles': 'Laureles',
    'comuna 11 laureles': 'Laureles',
    'comuna 11- laureles': 'Laureles',
    'laureles segundo parque': 'Laureles',
    'laureles, segundo parque': 'Laureles',

    # Belén y variaciones (con y sin acento)
    'belen': 'Belén',
    'belén': 'Belén',
    'belen loma de los bernal': 'Loma de los Bernal',
    'belén loma de los bernal': 'Loma de los Bernal',
    'loma de los bernal': 'Loma de los Bernal',
    'belen fatima': 'Belén',
    'belén fatima': 'Belén',
    'belen fátima': 'Belén',
    'belén fátima': 'Belén',
    'belen san bernardo': 'Belén',
    'belén san bernardo': 'Belén',
    'belen alameda': 'Belén',
    'belén alameda': 'Belén',

    # Envigado zonas
    'loma del escobero': 'Loma del Escobero',
    'el escobero': 'Loma del Escobero',
    'escobero': 'Loma del Escobero',
    'abadia,envigado': 'Envigado',
    'abadia, envigado': 'Envigado',
    'variante las palmas': 'Las Palmas',
    'variante las palmas, vereda perico': 'Las Palmas',
    'alto de las palmas': 'Las Palmas',
    'las orquideas': 'Las Orquídeas',
    'las orquídeas': 'Las Orquídeas',
    'la orquidea': 'Las Orquídeas',
    'la orquídea': 'Las Orquídeas',
    'uribe angel': 'Uribe Ángel',
    'uribe ángel': 'Uribe Ángel',
    'camino verde': 'Camino Verde',
    'cumbres': 'Cumbres',
    'loma de las brujas': 'Loma de las Brujas',

    # Suramericana
    'suramerica': 'Suramericana',
    'suramérica': 'Suramericana',
    'suramericana': 'Suramericana',
    'suramérica, portal ditaires': 'Suramericana',
    'suramerica, portal ditaires': 'Suramericana',

    # Sabaneta
    'aves maria': 'Aves María',
    'aves maría': 'Aves María',
    'la doctora': 'La Doctora',
    'san jose': 'San José',
    'san josé': 'San José',
    'asdesillas': 'Asdesillas',

    # Itagüí
    'itagui': 'Itagüí',
    'itagüí': 'Itagüí',
    'itagui, pilsen': 'Pilsen',
    'pilsen': 'Pilsen',

    # Rionegro
    'rionegro': 'Rionegro',
    'llanogrande': 'Llanogrande',
    'rionegro, llanogrande': 'Llanogrande',
    'san antonio de pereira': 'San Antonio de Pereira',
    'pontezuela': 'Pontezuela',

    # Bello
    'cabanas': 'Cabañas',
    'cabañas': 'Cabañas',
    'niquia': 'Niquía',
    'niquía': 'Niquía',

    # Otros
    'la estrella': 'La Estrella',
    'el retiro': 'El Retiro',
    'estadio': 'Estadio',
    'conquistadores': 'Conquistadores',
    'floresta': 'Floresta',
    'la floresta': 'Floresta',
    'castropol': 'Castropol',
    'lalinde': 'Lalinde',
    'manila': 'Manila',
    'ciudad del rio': 'Ciudad del Río',
    'ciudad del río': 'Ciudad del Río',
    'guayabal': 'Guayabal',
    'san diego': 'San Diego',
    'las palmas': 'Las Palmas',
}

# Landmarks conocidos → zonas correspondientes
LANDMARKS_A_ZONAS: Dict[str, List[str]] = {
    # Universidades
    'universidad de medellin': ['Laureles', 'Estadio', 'Belén'],
    'universidad de medellín': ['Laureles', 'Estadio', 'Belén'],
    'eafit': ['El Poblado', 'Manila'],
    'universidad eafit': ['El Poblado', 'Manila'],
    'universidad pontificia bolivariana': ['Laureles'],
    'upb': ['Laureles'],
    'universidad nacional': ['Robledo', 'Aranjuez'],
    'universidad de antioquia': ['Centro', 'Prado'],
    'udea': ['Centro', 'Prado'],

    # Centros comerciales
    'santafe': ['El Poblado'],
    'santa fe': ['El Poblado'],
    'centro comercial santafe': ['El Poblado'],
    'oviedo': ['El Poblado'],
    'centro comercial oviedo': ['El Poblado'],
    'el tesoro': ['El Poblado'],
    'centro comercial el tesoro': ['El Poblado'],
    'mayorca': ['Sabaneta'],
    'centro comercial mayorca': ['Sabaneta'],
    'viva envigado': ['Envigado'],
    'centro comercial viva': ['Envigado'],
    'unicentro': ['Laureles'],
    'centro comercial unicentro': ['Laureles'],
    'premium plaza': ['El Poblado'],
    'arkadia': ['Belén'],
    'los molinos': ['El Poblado'],
    'san fernando plaza': ['El Poblado'],
    'monterrey': ['El Poblado'],

    # Estaciones metro
    'metro poblado': ['El Poblado'],
    'estacion poblado': ['El Poblado'],
    'metro aguacatala': ['El Poblado', 'Envigado'],
    'estacion aguacatala': ['El Poblado', 'Envigado'],
    'metro envigado': ['Envigado'],
    'estacion envigado': ['Envigado'],
    'metro itagui': ['Itagüí'],
    'metro itagüí': ['Itagüí'],
    'estacion itagui': ['Itagüí'],
    'metro sabaneta': ['Sabaneta'],
    'estacion sabaneta': ['Sabaneta'],
    'metro estadio': ['Estadio', 'Laureles'],
    'estacion estadio': ['Estadio', 'Laureles'],
    'metro suramericana': ['Suramericana', 'Laureles'],
    'estacion suramericana': ['Suramericana', 'Laureles'],
    'metro floresta': ['Floresta'],
    'estacion floresta': ['Floresta'],
    'metro industriales': ['El Poblado', 'Ciudad del Río'],
    'estacion industriales': ['El Poblado', 'Ciudad del Río'],
    'metro ayura': ['Envigado'],
    'estacion ayura': ['Envigado'],

    # Parques y lugares
    'segundo parque de laureles': ['Laureles'],
    'primer parque de laureles': ['Laureles'],
    'parque de laureles': ['Laureles'],
    'parque lleras': ['El Poblado'],
    'parque del poblado': ['El Poblado'],
    'ciudad del rio': ['Ciudad del Río'],
    'milla de oro': ['El Poblado'],
    'parque lineal': ['Ciudad del Río'],

    # Clínicas y hospitales
    'clinica las vegas': ['El Poblado'],
    'clinica medellin': ['El Poblado'],
    'clinica el rosario': ['El Poblado'],
    'hospital pablo tobon uribe': ['Robledo'],
    'hospital general': ['Centro'],
}

# Coordenadas de landmarks (lat, lon) para búsqueda geoespacial
LANDMARKS_COORDENADAS: Dict[str, Tuple[float, float]] = {
    # Universidades
    'universidad de medellin': (6.2314, -75.6092),
    'universidad de medellín': (6.2314, -75.6092),
    'eafit': (6.2006, -75.5783),
    'universidad eafit': (6.2006, -75.5783),
    'universidad pontificia bolivariana': (6.2555, -75.5906),
    'upb': (6.2555, -75.5906),
    'universidad nacional': (6.2660, -75.5760),
    'universidad de antioquia': (6.2676, -75.5687),

    # Centros comerciales
    'santafe': (6.2008, -75.5725),
    'santa fe': (6.2008, -75.5725),
    'oviedo': (6.1954, -75.5633),
    'el tesoro': (6.1897, -75.5582),
    'mayorca': (6.1517, -75.6148),
    'viva envigado': (6.1715, -75.5893),
    'unicentro': (6.2490, -75.5920),
    'premium plaza': (6.2008, -75.5695),
    'arkadia': (6.2340, -75.6130),
    'monterrey': (6.2050, -75.5690),

    # Estaciones metro
    'metro poblado': (6.2102, -75.5749),
    'metro aguacatala': (6.1890, -75.5820),
    'metro envigado': (6.1715, -75.5976),
    'metro itagui': (6.1620, -75.6080),
    'metro sabaneta': (6.1510, -75.6160),
    'metro estadio': (6.2566, -75.5877),
    'metro suramericana': (6.2484, -75.5865),
    'metro floresta': (6.2580, -75.5980),
    'metro industriales': (6.2220, -75.5750),
    'metro ayura': (6.1780, -75.5910),

    # Parques y lugares
    'parque lleras': (6.2082, -75.5670),
    'segundo parque de laureles': (6.2470, -75.5961),
    'primer parque de laureles': (6.2490, -75.5940),
    'parque del poblado': (6.2100, -75.5680),
    'ciudad del rio': (6.2230, -75.5740),
    'milla de oro': (6.2050, -75.5680),

    # Clínicas y hospitales
    'clinica las vegas': (6.2020, -75.5650),
    'clinica medellin': (6.2100, -75.5720),
    'hospital pablo tobon uribe': (6.2730, -75.5900),
}


# =============================================================================
# FUNCIONES DE NORMALIZACIÓN - v2.1
# =============================================================================

def quitar_acentos(texto: str) -> str:
    """Elimina acentos de un texto para comparación"""
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )


def normalizar_zona(zona: str) -> str:
    """
    Normaliza nombre de zona a forma canónica

    Args:
        zona: Nombre de zona (puede tener variaciones, acentos, etc.)

    Returns:
        Nombre canónico de la zona

    Ejemplos:
        normalizar_zona('poblado') → 'El Poblado'
        normalizar_zona('Belen') → 'Belén'
        normalizar_zona('Santa María, Poblado') → 'El Poblado'
    """
    if not zona:
        return zona

    # 1. Lowercase y strip
    zona_lower = zona.lower().strip()

    # 2. Buscar en mapeo canónico directo
    if zona_lower in ZONA_CANONICA:
        return ZONA_CANONICA[zona_lower]

    # 3. Quitar acentos y buscar de nuevo
    zona_sin_acentos = quitar_acentos(zona_lower)
    if zona_sin_acentos in ZONA_CANONICA:
        return ZONA_CANONICA[zona_sin_acentos]

    # 4. Manejar zonas compuestas (separadas por coma)
    if ',' in zona:
        partes = [p.strip() for p in zona.split(',')]
        # Intentar normalizar la primera parte
        primera_normalizada = normalizar_zona(partes[0])
        if primera_normalizada != partes[0]:
            return primera_normalizada
        # Si la primera no matcheó, intentar con la segunda
        if len(partes) > 1:
            segunda_normalizada = normalizar_zona(partes[1])
            if segunda_normalizada != partes[1]:
                return segunda_normalizada

    # 5. Buscar si alguna zona canónica está contenida en el texto
    for key, canonical in ZONA_CANONICA.items():
        if key in zona_lower or zona_lower in key:
            return canonical

    # 6. Si no hay match, retornar con capitalización correcta
    return zona.title()


def procesar_ubicacion_relativa(ubicacion: str) -> Dict:
    """
    Procesa ubicaciones relativas como 'cerca a X'

    Args:
        ubicacion: Texto de ubicación (puede ser zona o "cerca a landmark")

    Returns:
        Dict con tipo de ubicación y datos:
        - {'tipo': 'zona', 'valor': 'Laureles'}
        - {'tipo': 'coordenadas', 'lat': 6.23, 'lon': -75.60, 'radio_km': 2.0, 'landmark': 'eafit'}
        - {'tipo': 'zonas', 'valor': ['Laureles', 'Estadio']}
    """
    import re

    ubicacion_lower = ubicacion.lower().strip()

    # Detectar patrón "cerca a/de/al X"
    match = re.search(r'cerca\s+(?:a|de|al?)\s+(.+)', ubicacion_lower)
    if not match:
        # No es ubicación relativa, normalizar y retornar como zona
        return {'tipo': 'zona', 'valor': normalizar_zona(ubicacion)}

    landmark = match.group(1).strip()

    # Limpiar artículos del landmark
    landmark = re.sub(r'^(el|la|los|las)\s+', '', landmark)

    # Buscar en coordenadas conocidas (prioridad para búsqueda geoespacial)
    if landmark in LANDMARKS_COORDENADAS:
        lat, lon = LANDMARKS_COORDENADAS[landmark]
        return {
            'tipo': 'coordenadas',
            'lat': lat,
            'lon': lon,
            'radio_km': 2.0,
            'landmark': landmark
        }

    # Buscar con variaciones (sin acentos)
    landmark_sin_acentos = quitar_acentos(landmark)
    for key, coords in LANDMARKS_COORDENADAS.items():
        if quitar_acentos(key) == landmark_sin_acentos:
            return {
                'tipo': 'coordenadas',
                'lat': coords[0],
                'lon': coords[1],
                'radio_km': 2.0,
                'landmark': key
            }

    # Buscar en mapeo de landmarks a zonas
    if landmark in LANDMARKS_A_ZONAS:
        return {
            'tipo': 'zonas',
            'valor': LANDMARKS_A_ZONAS[landmark]
        }

    # Buscar con variaciones
    for key, zonas in LANDMARKS_A_ZONAS.items():
        if quitar_acentos(key) == landmark_sin_acentos:
            return {
                'tipo': 'zonas',
                'valor': zonas
            }

    # No se encontró el landmark, retornar como desconocido
    return {'tipo': 'desconocido', 'valor': ubicacion}


def inferir_zona_de_direccion(direccion: str, ciudad: str = None) -> Optional[str]:
    """
    Intenta inferir la zona desde la dirección completa

    Args:
        direccion: Dirección completa de la propiedad
        ciudad: Ciudad (opcional, para contexto)

    Returns:
        Zona inferida o None si no se puede determinar
    """
    if not direccion:
        return None

    direccion_lower = direccion.lower()

    # Buscar zonas conocidas en la dirección
    for zona_key, zona_canonica in ZONA_CANONICA.items():
        if zona_key in direccion_lower:
            return zona_canonica

    # Buscar landmarks en la dirección
    for landmark, zonas in LANDMARKS_A_ZONAS.items():
        if landmark in direccion_lower:
            return zonas[0]  # Retornar la primera zona del landmark

    return None


# =============================================================================
# CONFIGURACIÓN DE BÚSQUEDA
# =============================================================================

@dataclass
class SearchConfig:
    """Configuración para una búsqueda específica"""
    # Límites
    max_results: int = 10
    max_candidates: int = 50  # Candidatos antes de ranking

    # Tolerancias
    precio_tolerancia: float = 0.15
    habitaciones_tolerancia: int = 1
    area_tolerancia: float = 0.20

    # Pesos de scoring base
    peso_similitud_vectorial: float = 0.40
    peso_filtros_exactos: float = 0.30
    peso_perfil_comprador: float = 0.20
    peso_calidad_propiedad: float = 0.10

    # Umbrales
    min_similarity_threshold: float = 0.3
    min_total_score: float = 30.0


# Configuración por defecto
DEFAULT_SEARCH_CONFIG = SearchConfig()


# =============================================================================
# FUNCIONES HELPER
# =============================================================================

def get_segmento_precio(precio: int) -> str:
    """
    Determina el segmento de precio para un valor dado

    Args:
        precio: Precio en COP

    Returns:
        Nombre del segmento
    """
    for segmento, (min_val, max_val) in SEGMENTOS_PRECIO_COLOMBIA.items():
        if min_val <= precio < max_val:
            return segmento
    return 'lujo'  # Default para precios muy altos


def get_tolerancia_precio(precio: int) -> float:
    """
    Obtiene la tolerancia de precio según el segmento

    Args:
        precio: Precio en COP

    Returns:
        Tolerancia como decimal (ej: 0.15 = ±15%)
    """
    segmento = get_segmento_precio(precio)
    return TOLERANCIA_PRECIO_POR_SEGMENTO.get(segmento, TOLERANCIA_PRECIO_DEFAULT)


def calcular_rango_precio(precio_max: int, tolerancia: float = None, flexibilidad: str = 'normal') -> Tuple[int, int]:
    """
    Calcula el rango de precio aceptable dado un presupuesto máximo

    v2.2: Rango estricto de ±10% del presupuesto
    Si el usuario dice "$500M", mostrar propiedades entre $450M y $550M

    Args:
        precio_max: Presupuesto máximo del cliente
        tolerancia: Tolerancia override (si no se especifica, usa 10%)
        flexibilidad: 'estricto' o 'normal' (ambos usan ±10% ahora)

    Returns:
        Tupla (precio_min, precio_max_ajustado)
    """
    if tolerancia is None:
        tolerancia = get_tolerancia_precio(precio_max)  # Ahora siempre 0.10

    # v2.2: Rango estricto de ±10% para todos los casos
    # $500M → $450M a $550M
    precio_min = int(precio_max * (1 - tolerancia))      # -10% = 90%
    precio_max_ajustado = int(precio_max * (1 + tolerancia))  # +10% = 110%

    return precio_min, precio_max_ajustado


# =============================================================================
# TOLERANCIA DE ÁREA - v2.2
# =============================================================================

TOLERANCIA_AREA_INFERIOR = 0.05  # -5% hacia abajo
TOLERANCIA_AREA_SUPERIOR = 0.20  # +20% hacia arriba


def calcular_rango_area(area_min: int = None, area_max: int = None) -> Tuple[Optional[int], Optional[int]]:
    """
    Calcula el rango de área aceptable con tolerancia -5% / +20%

    v2.2: Si el usuario dice "80m²", mostrar propiedades entre 76m² y 96m²

    Args:
        area_min: Área mínima especificada por el usuario
        area_max: Área máxima especificada por el usuario

    Returns:
        Tupla (area_min_ajustado, area_max_ajustado)
    """
    area_min_ajustado = None
    area_max_ajustado = None

    if area_min:
        # -5% del área mínima (ej: 80m² → 76m²)
        area_min_ajustado = int(area_min * (1 - TOLERANCIA_AREA_INFERIOR))

    if area_max:
        # +20% del área máxima (ej: 100m² → 120m²)
        area_max_ajustado = int(area_max * (1 + TOLERANCIA_AREA_SUPERIOR))
    elif area_min:
        # Si solo especificó área mínima, usar +20% de esa como máximo implícito
        area_max_ajustado = int(area_min * (1 + TOLERANCIA_AREA_SUPERIOR))

    return area_min_ajustado, area_max_ajustado


# =============================================================================
# TOLERANCIA DE HABITACIONES - v2.3
# =============================================================================

TOLERANCIA_HABITACIONES = 1  # ±1 habitación de tolerancia en filtro SQL


def calcular_rango_habitaciones(
    hab_min: int = None,
    hab_max: int = None,
    flexibilidad: str = 'normal'
) -> Tuple[Optional[int], Optional[int]]:
    """
    Calcula el rango de habitaciones con tolerancia para el filtro SQL.

    v2.3: Soporta flexibilidad 'estricto' para casos donde el usuario
    dice "hasta X habitaciones" o "máximo X habitaciones".

    Cuando flexibilidad='estricto':
    - NO aplicar tolerancia hacia arriba en hab_max
    - Solo mostrar propiedades con ≤X habitaciones

    Cuando flexibilidad='normal':
    - Permite que propiedades "cercanas" pasen el filtro y sean evaluadas
      por el scoring, donde se penalizarán o bonificarán según qué tan cerca
      estén del valor ideal.

    Args:
        hab_min: Habitaciones mínimas especificadas
        hab_max: Habitaciones máximas especificadas
        flexibilidad: 'estricto' o 'normal' (default)

    Returns:
        Tupla (hab_min_filtro, hab_max_filtro) para usar en SQL
    """
    hab_min_filtro = None
    hab_max_filtro = None

    if hab_min:
        if flexibilidad == 'estricto':
            # Sin tolerancia hacia abajo
            hab_min_filtro = hab_min
        else:
            # -1 del mínimo (pero nunca menos de 1)
            hab_min_filtro = max(1, hab_min - TOLERANCIA_HABITACIONES)

    if hab_max:
        if flexibilidad == 'estricto':
            # Sin tolerancia hacia arriba - respeta el máximo exacto
            hab_max_filtro = hab_max
        else:
            # +1 del máximo
            hab_max_filtro = hab_max + TOLERANCIA_HABITACIONES
    elif hab_min and flexibilidad != 'estricto':
        # Si solo especificó mínimo y no es estricto, poner un máximo razonable (+2)
        hab_max_filtro = hab_min + TOLERANCIA_HABITACIONES + 1

    return hab_min_filtro, hab_max_filtro


def detectar_perfil_comprador(query: str, criterios: Dict = None) -> str:
    """
    Detecta el perfil del comprador basado en la query y criterios

    Args:
        query: Query original del usuario
        criterios: Criterios extraídos

    Returns:
        Nombre del perfil detectado
    """
    query_lower = query.lower()

    # Buscar keywords de cada perfil
    scores = {}
    for perfil, config in PERFILES_COMPRADOR.items():
        if perfil == 'general':
            continue
        score = sum(1 for kw in config['keywords'] if kw in query_lower)
        if score > 0:
            scores[perfil] = score

    # Si hay criterios específicos, agregar peso
    if criterios:
        # Primer piso indica senior
        if criterios.get('piso') == 1:
            scores['senior'] = scores.get('senior', 0) + 2

        # Muchas habitaciones indica familia
        if (criterios.get('habitaciones_min') or 0) >= 3:
            scores['familia'] = scores.get('familia', 0) + 1

        # Inversión explícita
        if criterios.get('es_inversionista'):
            scores['inversionista'] = scores.get('inversionista', 0) + 3

    if scores:
        return max(scores, key=scores.get)

    return 'general'


def get_zonas_expandidas(zona: str) -> List[str]:
    """
    Obtiene zonas similares para expandir la búsqueda

    Args:
        zona: Zona original buscada

    Returns:
        Lista de zonas similares (incluyendo la original)
    """
    zona_lower = zona.lower().strip()

    # Buscar en el diccionario de zonas similares
    similares = ZONAS_SIMILARES.get(zona_lower, [])

    # Siempre incluir la zona original primero
    resultado = [zona]
    resultado.extend([z for z in similares if z.lower() != zona_lower])

    return resultado


def get_ciudad_de_zona(zona: str) -> Optional[str]:
    """
    Obtiene la ciudad a la que pertenece una zona.

    Args:
        zona: Nombre de la zona

    Returns:
        Nombre de la ciudad o None si no se encuentra
    """
    zona_lower = zona.lower().strip()

    # Buscar en ZONA_A_CIUDAD
    ciudad = ZONA_A_CIUDAD.get(zona_lower)
    if ciudad:
        return ciudad

    # Si la zona es una ciudad conocida, retornarla
    ciudades_conocidas = ['Medellín', 'Envigado', 'Sabaneta', 'Itagüí', 'Bello', 'Rionegro', 'La Estrella', 'El Retiro', 'La Ceja']
    for c in ciudades_conocidas:
        if zona_lower == c.lower():
            return c

    return None


def get_ciudades_de_zonas(zonas: List[str]) -> List[str]:
    """
    Obtiene las ciudades únicas de una lista de zonas.

    Args:
        zonas: Lista de nombres de zonas

    Returns:
        Lista de ciudades únicas
    """
    ciudades = set()
    for zona in zonas:
        ciudad = get_ciudad_de_zona(zona)
        if ciudad:
            ciudades.add(ciudad)
    return list(ciudades)


def get_pesos_perfil(perfil: str) -> Dict[str, float]:
    """
    Obtiene los pesos de scoring para un perfil de comprador

    Args:
        perfil: Nombre del perfil

    Returns:
        Diccionario de pesos
    """
    config = PERFILES_COMPRADOR.get(perfil, PERFILES_COMPRADOR['general'])
    return config.get('weights', {})


def get_amenidades_preferidas(perfil: str) -> List[str]:
    """
    Obtiene las amenidades preferidas para un perfil

    Args:
        perfil: Nombre del perfil

    Returns:
        Lista de amenidades preferidas
    """
    config = PERFILES_COMPRADOR.get(perfil, PERFILES_COMPRADOR['general'])
    return config.get('amenidades_preferidas', [])


# =============================================================================
# CONSTANTES ADICIONALES
# =============================================================================

# Palabras clave colombianas para normalización
SINONIMOS_COLOMBIANOS = {
    'alcoba': 'habitacion',
    'alcobas': 'habitaciones',
    'cuarto': 'habitacion',
    'cuartos': 'habitaciones',
    'parqueadero': 'garaje',
    'parqueaderos': 'garajes',
    'cuarto util': 'deposito',
    'cuarto útil': 'deposito',
    'balcon': 'balcon',
    'terraza': 'terraza',
    'estudio': 'estudio',
}

# =============================================================================
# UMBRAL DE CALIDAD MÍNIMA - v2.3
# =============================================================================

# Umbral mínimo de score para mostrar resultados
# Resultados con score < MIN_SCORE_PARA_MOSTRAR se consideran "no encontrados"
# porque están muy alejados de los criterios del usuario
MIN_SCORE_PARA_MOSTRAR = 25


# Amenidades de alto valor por categoría
AMENIDADES_SEGURIDAD = [
    'porteria', 'portería', 'vigilancia', 'circuito cerrado', 'cctv',
    'citofono', 'citófono', 'control acceso', 'seguridad 24'
]

AMENIDADES_FAMILIA = [
    'parque infantil', 'zona infantil', 'zona niños', 'juegos infantiles',
    'salon social', 'salón social', 'bbq', 'zona verde', 'cancha'
]

AMENIDADES_LUJO = [
    'piscina', 'gimnasio', 'spa', 'sauna', 'turco', 'jacuzzi',
    'squash', 'tenis', 'golf', 'club house', 'rooftop'
]

AMENIDADES_ACCESIBILIDAD = [
    'ascensor', 'rampa', 'primer piso', 'acceso discapacitados'
]


# =============================================================================
# VARIACIONES DE ZONA - v2.4
# =============================================================================
# Diccionario inverso: zona canónica → todas sus variaciones
# Esto permite buscar "El Poblado" y encontrar propiedades guardadas como
# "Santa María Poblado", "Altos del Poblado", etc.

def build_variaciones_zona() -> Dict[str, List[str]]:
    """
    Construye diccionario inverso de ZONA_CANONICA.
    Para cada zona canónica, lista todas las variaciones que mapean a ella.

    También incluye variaciones manuales adicionales que pueden aparecer
    en la base de datos pero no están en ZONA_CANONICA.

    Returns:
        Dict con zona canónica como clave y lista de variaciones como valor
    """
    variaciones = {}

    # Paso 1: Invertir ZONA_CANONICA
    for variacion, canonica in ZONA_CANONICA.items():
        if canonica not in variaciones:
            variaciones[canonica] = []
        if variacion not in variaciones[canonica]:
            variaciones[canonica].append(variacion)

    # Paso 2: Agregar variaciones manuales adicionales
    # Estas son variaciones que pueden aparecer en la BD pero no están en el mapeo
    VARIACIONES_MANUALES = {
        'El Poblado': [
            'santa maria', 'santa maría', 'provenza', 'altos del poblado',
            'la concha', 'los gonzalez', 'los gonzález', 'las lomas',
            'el diamante', 'el tesoro', 'san lucas', 'los balsos',
            'santa maria de los angeles', 'santa maría de los ángeles',
            'poblado i', 'poblado ii', 'el campestre', 'patio bonito',
            'alejandria', 'alejandría', 'la aguacatala', 'aguacatala',
            'villa carlota', 'los naranjos poblado'
        ],
        'Laureles': [
            'segundo parque', 'primer parque', 'tercer parque',
            'comuna 11', 'laureles - estadio', 'san joaquin laureles',
            'lorena', 'la castellana laureles', 'bolivariana laureles'
        ],
        'Estadio': [
            'estadio - laureles', 'cerca al estadio', 'suramericana estadio'
        ],
        'Belén': [
            'belen', 'loma de los bernal', 'fatima', 'fátima',
            'san bernardo', 'alameda belen', 'rodeo alto', 'la mota',
            'rincon de belen', 'rincón de belén', 'los alpes',
            'altavista belen', 'nueva villa de aburra', 'nueva villa de aburrá'
        ],
        'Envigado': [
            'zuñiga', 'zúñiga', 'la paz', 'el portal', 'otro lado',
            'señorial', 'alcala', 'alcalá', 'el dorado', 'las antillas',
            'la cuenca', 'el trianon', 'el trianón', 'uribe angel',
            'uribe ángel', 'jardines envigado', 'la frontera',
            'el esmeraldal', 'zona centro envigado', 'las vegas envigado'
        ],
        'Loma del Escobero': [
            'escobero', 'el escobero', 'alto del escobero',
            'loma escobero', 'vereda el escobero'
        ],
        'Las Palmas': [
            'alto de las palmas', 'variante las palmas',
            'palmas', 'sector las palmas', 'via las palmas', 'vía las palmas'
        ],
        'Ciudad del Río': [
            'ciudad del rio', 'barrio colombia', 'cd del rio',
            'parque lineal', 'villa carlota ciudad del rio'
        ],
        'Sabaneta': [
            'aves maria', 'aves maría', 'mayorca', 'la doctora',
            'calle larga', 'san jose sabaneta', 'san josé sabaneta',
            'asdesillas', 'las lomitas', 'pan de azucar', 'pan de azúcar',
            'centro sabaneta', 'sector la doctora'
        ],
        'Itagüí': [
            'itagui', 'ditaires', 'santa maria itagui', 'santa maría itagüí',
            'pilsen', 'los naranjos itagui', 'los naranjos itagüí',
            'centro itagui', 'centro itagüí', 'la gloria itagui'
        ],
        'Bello': [
            'niquia', 'niquía', 'cabanas', 'cabañas', 'paris bello',
            'zamora', 'centro bello', 'la cumbre bello',
            'guasimalito', 'tierra buena'
        ],
        'Rionegro': [
            'llanogrande', 'llano grande', 'san antonio de pereira',
            'pontezuela', 'barro blanco', 'el porvenir rionegro',
            'centro rionegro', 'galicia rionegro'
        ],
        'La Estrella': [
            'pueblo viejo', 'centro la estrella', 'la tablaza',
            'la raya', 'ancón'
        ],
        'Conquistadores': [
            'conquistadores laureles', 'sector conquistadores'
        ],
        'Floresta': [
            'la floresta', 'floresta laureles', 'sector floresta'
        ],
        'Calasanz': [
            'santa monica', 'santa mónica', 'calasanz parte alta',
            'calasanz parte baja'
        ],
        'Castropol': [
            'castropol poblado', 'sector castropol'
        ],
        'Lalinde': [
            'lalinde poblado', 'sector lalinde'
        ],
        'Manila': [
            'manila poblado', 'sector manila'
        ],
        'Guayabal': [
            'trinidad', 'guayabal sur', 'campo amor'
        ],
        'Suramericana': [
            'suramérica', 'suramerica', 'portal ditaires'
        ],
    }

    for canonica, vars_manuales in VARIACIONES_MANUALES.items():
        if canonica not in variaciones:
            variaciones[canonica] = []
        for v in vars_manuales:
            v_lower = v.lower()
            if v_lower not in [x.lower() for x in variaciones[canonica]]:
                variaciones[canonica].append(v)

    return variaciones


# Construir el diccionario al cargar el módulo
VARIACIONES_ZONA = build_variaciones_zona()


def get_variaciones_zona(zona: str) -> List[str]:
    """
    Obtiene todas las variaciones de una zona para búsqueda SQL.

    Incluye:
    - La zona original
    - La zona normalizada (canónica)
    - Todas las variaciones conocidas

    Args:
        zona: Nombre de zona (puede ser canónica o variación)

    Returns:
        Lista de todas las variaciones para buscar en SQL
    """
    if not zona:
        return []

    # Primero normalizar la zona
    zona_canonica = normalizar_zona(zona)

    # Obtener variaciones del diccionario
    variaciones = set()

    # Agregar variaciones de la zona canónica
    if zona_canonica in VARIACIONES_ZONA:
        variaciones.update(VARIACIONES_ZONA[zona_canonica])

    # También buscar si la zona original es clave en VARIACIONES_ZONA
    zona_title = zona.title()
    if zona_title in VARIACIONES_ZONA:
        variaciones.update(VARIACIONES_ZONA[zona_title])

    # Siempre incluir la zona original y la canónica
    variaciones.add(zona)
    variaciones.add(zona.lower())
    variaciones.add(zona_canonica)
    variaciones.add(zona_canonica.lower())

    return list(variaciones)
