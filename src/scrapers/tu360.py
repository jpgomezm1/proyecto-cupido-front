#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper para propiedades de Tu360Inmobiliario
Extrae datos de propiedades desde URLs del portal tu360inmobiliario-pulppo.com
"""

import sys
import io
import time

# Configurar UTF-8 para evitar errores de encoding en Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import requests
import re
import json
from typing import Dict, List, Optional
from datetime import datetime
import newrelic.agent
from src.scrapers.utils import PropertyNormalizer

# Importar sistema de logging
try:
    from src.core.logger import get_scraper_logger
    scraper_log = get_scraper_logger()
except ImportError:
    scraper_log = None


class Tu360Scraper:
    """
    Scraper para extraer datos de propiedades de Tu360Inmobiliario
    """

    def __init__(self, verbose: bool = True):
        """
        Inicializa el scraper

        Args:
            verbose: Si True, muestra mensajes de progreso
        """
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

    def _log(self, message: str):
        """Imprime mensaje si verbose está activado"""
        if self.verbose:
            print(message)

    def _validar_url(self, url: str) -> bool:
        """
        Valida que la URL sea de Tu360Inmobiliario

        Args:
            url: URL a validar

        Returns:
            True si es válida
        """
        patrones = [
            r'tu360inmobiliario-pulppo\.com/property/',
            r'asesor\.tu360inmobiliario-pulppo\.com/property/',
        ]

        return any(re.search(patron, url) for patron in patrones)

    def _extraer_json_data(self, html: str) -> Optional[Dict]:
        """
        Extrae los datos JSON de la página Next.js

        Args:
            html: HTML de la página

        Returns:
            Dict con los datos de la propiedad o None
        """
        try:
            # Buscar el script con __NEXT_DATA__
            pattern = r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>'
            match = re.search(pattern, html, re.DOTALL)

            if not match:
                self._log("[ERROR] No se encontró __NEXT_DATA__ en la página")
                return None

            json_str = match.group(1)
            data = json.loads(json_str)

            # Navegar a pageProps.property
            property_data = data.get('props', {}).get('pageProps', {}).get('property')

            if not property_data:
                self._log("[ERROR] No se encontraron datos de propiedad en pageProps")
                return None

            return property_data

        except json.JSONDecodeError as e:
            self._log(f"[ERROR] Error al parsear JSON: {e}")
            return None
        except Exception as e:
            self._log(f"[ERROR] Error extrayendo JSON: {e}")
            return None


    def extract_property_data(self, url: str) -> Optional[Dict]:
        """
        Extrae todos los datos de una propiedad de Tu360

        Args:
            url: URL de la propiedad

        Returns:
            Dict con los datos de la propiedad o None si falla
        """
        total_start = time.time()

        # Iniciar tracking del scrape
        if scraper_log:
            scraper_log.start_scrape(url, 'Tu360')

        self._log(f"\n{'='*80}")
        self._log(f"SCRAPEANDO TU360: {url}")
        self._log(f"{'='*80}\n")

        # Validar URL
        if not self._validar_url(url):
            self._log("[ERROR] URL no válida. Debe ser de tu360inmobiliario-pulppo.com")
            if scraper_log:
                scraper_log.log_error("URL no válida", "validation")
            return None

        try:
            # Obtener HTML
            self._log("[1/3] Descargando página...")
            download_start = time.time()
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            html = response.text
            download_elapsed = (time.time() - download_start) * 1000

            if scraper_log:
                scraper_log.log_page_download(url, response.status_code, download_elapsed)

            # Extraer JSON
            self._log("[2/3] Extrayendo datos JSON...")
            property_data = self._extraer_json_data(html)

            if not property_data:
                if scraper_log:
                    scraper_log.log_error("No se encontró __NEXT_DATA__ en la página", "json_extraction")
                return None

            # Parsear datos
            self._log("[3/3] Procesando información...")

            listing = property_data.get('listing', {})
            address = property_data.get('address', {})
            features = property_data.get('features', {})
            attributes = property_data.get('attributes', {})
            pictures = property_data.get('pictures', [])
            services = property_data.get('services', [])
            contact = property_data.get('contact', {})

            # Extraer datos principales
            # Limpiar título con AI para quitar "Venta", "Arriendo", etc.
            titulo_raw = listing.get('title', 'Sin título')
            titulo = PropertyNormalizer.limpiar_titulo_propiedad(titulo_raw) if titulo_raw else 'Sin título'
            descripcion = listing.get('description', '')

            # Precio (con formateo mejorado)
            price_info = listing.get('price', {})
            precio = price_info.get('price', 0)
            moneda = price_info.get('currency', 'COP')
            precio_formateado = PropertyNormalizer.formatear_precio(precio, moneda)

            # Ubicación (con normalización)
            ciudad_raw = address.get('city', {}).get('name', '')
            departamento_raw = address.get('state', {}).get('name', '')
            barrio_raw = address.get('neighborhood', {}).get('name', '')
            direccion = address.get('streetAddress', '')

            ciudad = PropertyNormalizer.normalizar_ciudad(ciudad_raw)
            departamento = PropertyNormalizer.normalizar_departamento(departamento_raw)
            barrio = PropertyNormalizer.normalizar_barrio(barrio_raw)

            # Tipo y operación (con normalización mejorada)
            tipo_propiedad = PropertyNormalizer.normalizar_tipo_propiedad(property_data.get('type', ''))

            # Si el tipo no se detectó bien, intentar desde el título
            if tipo_propiedad == 'Otro' or not tipo_propiedad:
                tipo_desde_titulo = PropertyNormalizer.extraer_tipo_desde_titulo(titulo)
                if tipo_desde_titulo:
                    tipo_propiedad = tipo_desde_titulo

            tipo_negocio = PropertyNormalizer.normalizar_tipo_negocio(listing.get('operation', 'sale'))

            # Características
            habitaciones = attributes.get('bedrooms', 0) or features.get('bedrooms', 0) or 0
            banos = attributes.get('bathrooms', 0) or features.get('bathrooms', 0) or 0
            area_total = attributes.get('totalSurface') or attributes.get('surface') or attributes.get('roofedSurface') or 0
            area_construida = attributes.get('roofedSurface') or attributes.get('surface') or 0
            parqueaderos = attributes.get('parkings', 0) or features.get('parkingSpaces', 0) or 0
            piso = features.get('floor', 0) or 0
            antiguedad = features.get('age', 0) or 0

            # Código
            codigo_interno = property_data.get('internalId', '')
            codigo_mongo = property_data.get('_id', '')

            # Imágenes
            imagenes = []
            for pic in pictures[:20]:  # Máximo 20 imágenes
                img_url = pic.get('url', '')
                if img_url:
                    imagenes.append({
                        'url': img_url,
                        'descripcion': pic.get('description', ''),
                        'es_portada': len(imagenes) == 0  # Primera imagen es portada
                    })

            # Amenidades/Servicios
            amenidades = [s.get('name', s) if isinstance(s, dict) else s for s in services]

            # Contacto (con validación de teléfono)
            agente_nombre = contact.get('agent', {}).get('name', 'Tu360Inmobiliario')
            agente_telefono_raw = contact.get('agent', {}).get('phone', '')
            agente_telefono = PropertyNormalizer.validar_telefono(agente_telefono_raw) or agente_telefono_raw
            agente_email = contact.get('agent', {}).get('email', '')

            # Construir imágenes como string separado por |
            imagenes_urls_str = '|'.join([img['url'] for img in imagenes]) if imagenes else None

            # Amenidades como string
            amenidades_str = ', '.join(amenidades) if amenidades else None

            # Construir objeto de datos normalizados (compatible con esquema DB)
            datos_normalizados = {
                # Identificación
                'fuente': 'Tu360_Captado',
                'codigo_propiedad': codigo_interno or codigo_mongo,
                'url': url,  # Campo esperado por la DB

                # Información básica
                'titulo': titulo,
                'descripcion': descripcion,
                'descripcion_length': len(descripcion) if descripcion else 0,
                'tipo_propiedad': tipo_propiedad,
                'estado': 'Usado',  # Default

                # Precio
                'precio': precio,
                'precio_texto': precio_formateado,

                # Ubicación
                'pais': 'Colombia',
                'departamento': departamento,
                'ciudad': ciudad,
                'zona': barrio,  # zona es el campo esperado por la DB
                'direccion_completa': direccion,
                'latitud': address.get('coordinates', [None, None])[1],
                'longitud': address.get('coordinates', [None, None])[0],

                # Características
                'habitaciones': habitaciones,
                'banos': banos,
                'area_construida': int(area_construida) if area_construida else (int(area_total) if area_total else None),
                'parqueaderos': parqueaderos,
                'piso': piso,
                'ano_construccion': (datetime.now().year - antiguedad) if antiguedad else None,

                # Imágenes
                'imagenes_urls': imagenes_urls_str,
                'total_imagenes': len(imagenes),
                'imagen_principal': imagenes[0]['url'] if imagenes else None,
                'imagenes_hd_count': len(imagenes),
                'imagenes_thumb_count': 0,

                # Amenidades
                'caracteristicas_adicionales': amenidades_str,
                'total_amenidades': len(amenidades),

                # Contacto
                'asesor': agente_nombre,
                'telefono': agente_telefono,
                'inmobiliaria': 'Tu360Inmobiliario',

                # Tipo de negocio (Venta/Arriendo)
                'tipo_negocio': tipo_negocio,

                # Metadata
                'fecha_extraccion': datetime.now().isoformat(),
                'activa': True,
            }

            # Log de resumen
            total_elapsed = (time.time() - total_start) * 1000

            self._log(f"\n[OK] Propiedad extraída exitosamente:")
            self._log(f"   Título: {titulo[:60]}...")
            self._log(f"   Código: {codigo_interno or codigo_mongo}")
            self._log(f"   Tipo: {tipo_propiedad} - {tipo_negocio}")
            self._log(f"   Precio: {precio_formateado}")
            self._log(f"   Ubicación: {ciudad}, {barrio}")
            self._log(f"   Área: {area_total or area_construida} m²")
            self._log(f"   Habitaciones: {habitaciones} | Baños: {banos}")
            self._log(f"   Imágenes: {len(imagenes)}")
            self._log(f"   Amenidades: {len(amenidades)}")

            # Logs estructurados
            if scraper_log:
                scraper_log.log_data_extraction('titulo', titulo, bool(titulo))
                scraper_log.log_data_extraction('precio', precio, precio > 0)
                scraper_log.log_data_extraction('ciudad', ciudad, bool(ciudad))
                scraper_log.log_data_extraction('habitaciones', habitaciones, habitaciones > 0)
                scraper_log.log_images_extracted(len(imagenes), len(imagenes))
                scraper_log.log_complete(codigo_interno or codigo_mongo, total_elapsed)

            # === FASE 3: New Relic metrics ===
            newrelic.agent.record_custom_metric('Custom/Scraper/Tu360/Duration', total_elapsed)
            newrelic.agent.record_custom_metric('Custom/Scraper/Tu360/Success', 1)

            return datos_normalizados

        except requests.RequestException as e:
            self._log(f"[ERROR] Error de conexión: {e}")
            if scraper_log:
                scraper_log.log_error(str(e), 'connection')
            return None
        except Exception as e:
            self._log(f"[ERROR] Error inesperado: {e}")
            if scraper_log:
                scraper_log.log_error(str(e), 'extraction')
            import traceback
            traceback.print_exc()
            return None


def test_scraper():
    """Función de prueba del scraper"""
    print("="*80)
    print("  TEST SCRAPER TU360INMOBILIARIO")
    print("="*80)

    # URL de prueba
    url_test = "https://asesor.tu360inmobiliario-pulppo.com/property/6915e42712e1c67cd6945b92"

    scraper = Tu360Scraper(verbose=True)
    datos = scraper.extract_property_data(url_test)

    if datos:
        print("\n" + "="*80)
        print("  DATOS EXTRAÍDOS")
        print("="*80)
        print(json.dumps(datos, indent=2, ensure_ascii=False, default=str))
        print("\n[OK] Test completado exitosamente")
    else:
        print("\n[ERROR] No se pudieron extraer los datos")


if __name__ == '__main__':
    test_scraper()
