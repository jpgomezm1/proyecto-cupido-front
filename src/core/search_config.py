#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuración del Sistema de Búsqueda Inteligente v2.0
Parámetros específicos para el mercado inmobiliario colombiano
"""

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
TOLERANCIA_PRECIO_POR_SEGMENTO: Dict[str, float] = {
    'vis': 0.10,        # ±10% - Poco margen en este segmento
    'accesible': 0.12,  # ±12%
    'medio': 0.15,      # ±15%
    'medio_alto': 0.15, # ±15%
    'premium': 0.18,    # ±18% - Más flexibilidad
    'lujo': 0.20        # ±20% - Alta flexibilidad
}

# Tolerancia por defecto si no se puede determinar segmento
TOLERANCIA_PRECIO_DEFAULT = 0.15  # ±15%


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

    # Envigado y sur
    'envigado': ['poblado', 'sabaneta', 'zuñiga', 'la paz'],
    'sabaneta': ['envigado', 'itagui', 'la estrella'],

    # Calasanz y occidental
    'calasanz': ['floresta', 'santa monica', 'san joaquin', 'robledo'],
    'robledo': ['calasanz', 'castilla', 'bello'],
}


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


def calcular_rango_precio(precio_max: int, tolerancia: float = None) -> Tuple[int, int]:
    """
    Calcula el rango de precio aceptable dado un presupuesto máximo

    Args:
        precio_max: Presupuesto máximo del cliente
        tolerancia: Tolerancia override (si no se especifica, usa la del segmento)

    Returns:
        Tupla (precio_min, precio_max_ajustado)
    """
    if tolerancia is None:
        tolerancia = get_tolerancia_precio(precio_max)

    # Precio mínimo: no mostrar propiedades demasiado baratas
    precio_min = int(precio_max * (1 - tolerancia))

    # Precio máximo: pequeño margen arriba para no perder oportunidades
    precio_max_ajustado = int(precio_max * (1 + tolerancia * 0.5))  # Solo mitad de tolerancia arriba

    return precio_min, precio_max_ajustado


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
        if criterios.get('habitaciones_min', 0) >= 3:
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
