#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilidades compartidas para scrapers de propiedades
Funciones de normalización para tipos, ubicaciones, precios, etc.
"""

import re
import os
from typing import Optional, Dict, List
from dotenv import load_dotenv

load_dotenv()

# Cliente de Anthropic (lazy loading)
_anthropic_client = None

def _get_anthropic_client():
    """Obtiene o crea el cliente de Anthropic"""
    global _anthropic_client
    if _anthropic_client is None:
        try:
            import anthropic
            api_key = os.getenv('ANTHROPIC_API_KEY')
            if api_key:
                _anthropic_client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            pass
    return _anthropic_client


class PropertyNormalizer:
    """
    Clase para normalizar datos de propiedades de diferentes fuentes
    Asegura consistencia en tipos, ubicaciones, precios, etc.
    """

    # Mapeo de tipos de propiedad (lowercase -> normalizado)
    TIPO_PROPIEDAD_MAP = {
        # Apartamentos
        'apartamento': 'Apartamento',
        'apto': 'Apartamento',
        'apt': 'Apartamento',
        'apartaestudio': 'Apartaestudio',
        'loft': 'Loft',
        'penthouse': 'Penthouse',
        'duplex': 'Duplex',

        # Casas
        'casa': 'Casa',
        'casa campestre': 'Casa Campestre',
        'casa campestre': 'Casa Campestre',
        'finca': 'Finca',
        'villa': 'Villa',
        'cabaña': 'Cabaña',
        'chalet': 'Chalet',

        # Comercial
        'local': 'Local Comercial',
        'local comercial': 'Local Comercial',
        'oficina': 'Oficina',
        'consultorio': 'Consultorio',
        'bodega': 'Bodega',
        'edificio': 'Edificio',
        'edificio comercial': 'Edificio Comercial',
        'centro comercial': 'Centro Comercial',

        # Terrenos
        'lote': 'Lote',
        'terreno': 'Terreno',
        'lote de terreno': 'Lote',
        'parcela': 'Parcela',

        # Otros
        'garage': 'Garaje',
        'garaje': 'Garaje',
        'parqueadero': 'Parqueadero',
        'hotel': 'Hotel',
        'hostal': 'Hostal',
    }

    # Mapeo de ciudades (variaciones -> oficial)
    CIUDAD_MAP = {
        # Medellín y área metropolitana
        'medellin': 'Medellín',
        'medellín': 'Medellín',
        'envigado': 'Envigado',
        'itagui': 'Itagüí',
        'itagüí': 'Itagüí',
        'sabaneta': 'Sabaneta',
        'bello': 'Bello',
        'la estrella': 'La Estrella',
        'estrella': 'La Estrella',
        'copacabana': 'Copacabana',
        'caldas': 'Caldas',
        'barbosa': 'Barbosa',
        'girardota': 'Girardota',

        # Bogotá
        'bogota': 'Bogotá',
        'bogotá': 'Bogotá',
        'bogota d.c.': 'Bogotá',
        'bogotá d.c.': 'Bogotá',

        # Cali
        'cali': 'Cali',
        'santiago de cali': 'Cali',

        # Barranquilla
        'barranquilla': 'Barranquilla',

        # Cartagena
        'cartagena': 'Cartagena',
        'cartagena de indias': 'Cartagena',

        # Otras ciudades principales
        'bucaramanga': 'Bucaramanga',
        'pereira': 'Pereira',
        'manizales': 'Manizales',
        'santa marta': 'Santa Marta',
        'cucuta': 'Cúcuta',
        'cúcuta': 'Cúcuta',
        'ibague': 'Ibagué',
        'ibagué': 'Ibagué',
        'pasto': 'Pasto',
        'villavicencio': 'Villavicencio',
        'monteria': 'Montería',
        'montería': 'Montería',
        'neiva': 'Neiva',
        'armenia': 'Armenia',
    }

    # Mapeo de departamentos
    DEPARTAMENTO_MAP = {
        'antioquia': 'Antioquia',
        'cundinamarca': 'Cundinamarca',
        'valle del cauca': 'Valle del Cauca',
        'valle': 'Valle del Cauca',
        'atlantico': 'Atlántico',
        'atlántico': 'Atlántico',
        'bolivar': 'Bolívar',
        'bolívar': 'Bolívar',
        'santander': 'Santander',
        'risaralda': 'Risaralda',
        'caldas': 'Caldas',
        'magdalena': 'Magdalena',
        'norte de santander': 'Norte de Santander',
        'tolima': 'Tolima',
        'narino': 'Nariño',
        'nariño': 'Nariño',
        'meta': 'Meta',
        'cordoba': 'Córdoba',
        'córdoba': 'Córdoba',
        'huila': 'Huila',
        'quindio': 'Quindío',
        'quindío': 'Quindío',
    }

    # Mapeo de tipo de negocio
    TIPO_NEGOCIO_MAP = {
        'venta': 'Venta',
        'vender': 'Venta',
        'sale': 'Venta',
        'sell': 'Venta',
        'arriendo': 'Arriendo',
        'arrendar': 'Arriendo',
        'alquiler': 'Arriendo',
        'rent': 'Arriendo',
        'alquilar': 'Arriendo',
    }

    @staticmethod
    def normalizar_tipo_propiedad(tipo_raw: Optional[str]) -> str:
        """
        Normaliza el tipo de propiedad a valores estándar

        Args:
            tipo_raw: Tipo de propiedad sin normalizar

        Returns:
            Tipo normalizado (ej: 'Apartamento', 'Casa', 'Local Comercial')
        """
        if not tipo_raw:
            return 'Otro'

        tipo_lower = tipo_raw.lower().strip()

        # Buscar coincidencia exacta
        if tipo_lower in PropertyNormalizer.TIPO_PROPIEDAD_MAP:
            return PropertyNormalizer.TIPO_PROPIEDAD_MAP[tipo_lower]

        # Buscar coincidencia parcial
        for key, value in PropertyNormalizer.TIPO_PROPIEDAD_MAP.items():
            if key in tipo_lower or tipo_lower in key:
                return value

        # Si no se encuentra, capitalizar
        return tipo_raw.title()

    @staticmethod
    def normalizar_ciudad(ciudad_raw: Optional[str]) -> Optional[str]:
        """
        Normaliza el nombre de la ciudad

        Args:
            ciudad_raw: Ciudad sin normalizar

        Returns:
            Ciudad normalizada o None
        """
        if not ciudad_raw:
            return None

        ciudad_lower = ciudad_raw.lower().strip()

        # Remover puntos y caracteres especiales
        ciudad_lower = ciudad_lower.rstrip('.')

        # Buscar en mapa
        if ciudad_lower in PropertyNormalizer.CIUDAD_MAP:
            return PropertyNormalizer.CIUDAD_MAP[ciudad_lower]

        # Si no se encuentra, capitalizar cada palabra
        return ciudad_raw.title().strip()

    @staticmethod
    def normalizar_departamento(depto_raw: Optional[str]) -> Optional[str]:
        """
        Normaliza el nombre del departamento

        Args:
            depto_raw: Departamento sin normalizar

        Returns:
            Departamento normalizado o None
        """
        if not depto_raw:
            return None

        depto_lower = depto_raw.lower().strip()

        # Buscar en mapa
        if depto_lower in PropertyNormalizer.DEPARTAMENTO_MAP:
            return PropertyNormalizer.DEPARTAMENTO_MAP[depto_lower]

        # Si no se encuentra, capitalizar cada palabra
        return depto_raw.title().strip()

    @staticmethod
    def normalizar_tipo_negocio(tipo_raw: Optional[str]) -> str:
        """
        Normaliza el tipo de negocio (Venta/Arriendo)

        Args:
            tipo_raw: Tipo de negocio sin normalizar

        Returns:
            Tipo normalizado ('Venta' o 'Arriendo')
        """
        if not tipo_raw:
            return 'Venta'

        tipo_lower = tipo_raw.lower().strip()

        # Buscar en mapa
        if tipo_lower in PropertyNormalizer.TIPO_NEGOCIO_MAP:
            return PropertyNormalizer.TIPO_NEGOCIO_MAP[tipo_lower]

        # Default: Venta
        return 'Venta'

    @staticmethod
    def normalizar_barrio(barrio_raw: Optional[str]) -> Optional[str]:
        """
        Normaliza el nombre del barrio/zona

        Args:
            barrio_raw: Barrio sin normalizar

        Returns:
            Barrio normalizado o None
        """
        if not barrio_raw:
            return None

        # Remover puntos finales
        barrio = barrio_raw.strip().rstrip('.')

        # Capitalizar cada palabra
        return barrio.title()

    @staticmethod
    def formatear_precio(precio: int, moneda: str = 'COP') -> str:
        """
        Formatea el precio de forma legible
        IMPORTANTE: En Colombia los precios de propiedades son en COP, no USD

        Args:
            precio: Precio numérico
            moneda: Moneda (COP por defecto - Peso Colombiano)

        Returns:
            Precio formateado en COP (ej: '$1.5M COP', '$250M COP')
        """
        if not precio or precio == 0:
            return 'Precio no disponible'

        # SIEMPRE es COP en el mercado inmobiliario colombiano
        if moneda == 'COP' or moneda == 'COL' or not moneda:
            moneda = 'COP'  # Normalizar

            # Millones - rango típico de propiedades
            # Ej: 250,000,000 = $250M COP
            #     1,400,000,000 = $1,400M COP
            if precio >= 1_000_000:
                millones = precio / 1_000_000
                # Formatear con punto como separador de miles
                if millones >= 1000:
                    return f"${millones:,.0f}M COP".replace(',', '.')
                else:
                    return f"${millones:.0f}M COP"
            # Miles - arriendos y propiedades muy económicas
            elif precio >= 1_000:
                miles = precio / 1_000
                return f"${miles:.0f}K COP"
            else:
                return f"${precio:,} COP".replace(',', '.')

        # Solo para casos excepcionales en USD u otras monedas
        elif moneda == 'USD':
            if precio >= 1_000_000:
                millones = precio / 1_000_000
                return f"USD ${millones:.1f}M"
            else:
                return f"USD ${precio:,}".replace(',', '.')
        else:
            # Otras monedas
            return f"{moneda} ${precio:,}".replace(',', '.')

    @staticmethod
    def validar_telefono(telefono: Optional[str]) -> Optional[str]:
        """
        Valida y normaliza un número de teléfono colombiano

        Args:
            telefono: Teléfono sin validar

        Returns:
            Teléfono en formato +57XXXXXXXXXX o None
        """
        if not telefono:
            return None

        # Remover espacios, guiones, paréntesis
        telefono_clean = re.sub(r'[\s\-\(\)]', '', telefono)

        # Si empieza con +57, validar longitud
        if telefono_clean.startswith('+57'):
            if len(telefono_clean) == 13:  # +57 + 10 dígitos
                return telefono_clean
            return None

        # Si empieza con 57 (sin +)
        if telefono_clean.startswith('57') and len(telefono_clean) == 12:
            return '+' + telefono_clean

        # Si es un número de 10 dígitos (celular o fijo)
        if len(telefono_clean) == 10 and telefono_clean.isdigit():
            return '+57' + telefono_clean

        # Si es 7 dígitos (fijo sin código de ciudad)
        if len(telefono_clean) == 7 and telefono_clean.isdigit():
            # Asumir Medellín (604)
            return '+57604' + telefono_clean

        return None

    @staticmethod
    def limpiar_texto(texto: Optional[str]) -> Optional[str]:
        """
        Limpia un texto de caracteres especiales y espacios extra

        Args:
            texto: Texto a limpiar

        Returns:
            Texto limpio o None
        """
        if not texto:
            return None

        # Remover espacios múltiples
        texto_clean = re.sub(r'\s+', ' ', texto)

        # Remover espacios al inicio/final
        texto_clean = texto_clean.strip()

        return texto_clean if texto_clean else None

    @staticmethod
    def extraer_tipo_desde_titulo(titulo: str) -> Optional[str]:
        """
        Intenta extraer el tipo de propiedad desde el título

        Args:
            titulo: Título de la propiedad

        Returns:
            Tipo de propiedad normalizado o None
        """
        if not titulo:
            return None

        titulo_lower = titulo.lower()

        # Buscar palabras clave en el título
        for key in PropertyNormalizer.TIPO_PROPIEDAD_MAP.keys():
            if key in titulo_lower:
                return PropertyNormalizer.TIPO_PROPIEDAD_MAP[key]

        return None

    @staticmethod
    def limpiar_titulo_propiedad(titulo: str, use_ai: bool = True) -> str:
        """
        Limpia el título de una propiedad quitando palabras como "Venta", "Arriendo", etc.
        Usa AI (Claude) para un procesamiento más inteligente.

        Ejemplos:
            - "Venta Apartamento Rionegro - Porvenir" → "Apartamento Rionegro - Porvenir"
            - "Arriendo Casa en El Poblado" → "Casa en El Poblado"
            - "Se Vende Apartamento Laureles" → "Apartamento Laureles"

        Args:
            titulo: Título original de la propiedad
            use_ai: Si True, usa Claude AI para limpiar. Si False, usa regex simple.

        Returns:
            Título limpio sin palabras de tipo de negocio
        """
        if not titulo:
            return titulo

        # Primero intentar limpieza rápida con regex (para casos obvios)
        titulo_limpio = PropertyNormalizer._limpiar_titulo_regex(titulo)

        # Si el título cambió significativamente, usar el resultado del regex
        if titulo_limpio != titulo and len(titulo_limpio) > 10:
            return titulo_limpio

        # Si use_ai está habilitado y el regex no fue suficiente, usar Claude
        if use_ai:
            titulo_ai = PropertyNormalizer._limpiar_titulo_con_ai(titulo)
            if titulo_ai:
                return titulo_ai

        return titulo_limpio

    @staticmethod
    def _limpiar_titulo_regex(titulo: str) -> str:
        """
        Limpieza rápida del título usando expresiones regulares.
        Quita palabras comunes de tipo de negocio del inicio del título.
        """
        if not titulo:
            return titulo

        # Palabras a quitar del inicio del título
        palabras_inicio = [
            r'^venta\s+',
            r'^arriendo\s+',
            r'^alquiler\s+',
            r'^se\s+vende\s+',
            r'^se\s+arrienda\s+',
            r'^se\s+alquila\s+',
            r'^en\s+venta\s+',
            r'^en\s+arriendo\s+',
            r'^para\s+venta\s+',
            r'^para\s+arriendo\s+',
        ]

        titulo_limpio = titulo.strip()

        # Aplicar cada patrón
        for patron in palabras_inicio:
            titulo_limpio = re.sub(patron, '', titulo_limpio, flags=re.IGNORECASE)

        # Capitalizar primera letra
        if titulo_limpio:
            titulo_limpio = titulo_limpio[0].upper() + titulo_limpio[1:] if len(titulo_limpio) > 1 else titulo_limpio.upper()

        return titulo_limpio.strip()

    @staticmethod
    def _limpiar_titulo_con_ai(titulo: str) -> Optional[str]:
        """
        Usa Claude AI para limpiar el título de forma inteligente.
        """
        client = _get_anthropic_client()
        if not client:
            return None

        try:
            message = client.messages.create(
                model="claude-3-5-haiku-20241022",  # Modelo rápido y económico
                max_tokens=100,
                messages=[
                    {
                        "role": "user",
                        "content": f"""Limpia el siguiente título de propiedad inmobiliaria quitando SOLO las palabras que indican el tipo de negocio (como "Venta", "Arriendo", "Se Vende", "En Venta", "Alquiler", etc.) del inicio.

NO modifiques el resto del título. NO agregues ni quites otras palabras.

Título original: "{titulo}"

Responde SOLO con el título limpio, sin comillas ni explicaciones."""
                    }
                ]
            )

            titulo_limpio = message.content[0].text.strip()

            # Validar que el resultado tenga sentido
            if titulo_limpio and len(titulo_limpio) >= 5 and len(titulo_limpio) <= len(titulo):
                return titulo_limpio

            return None

        except Exception as e:
            print(f"⚠️  Error limpiando título con AI: {e}")
            return None
