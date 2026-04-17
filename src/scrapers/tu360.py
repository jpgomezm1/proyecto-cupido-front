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

            listing = property_data.get('listing') or {}
            address = property_data.get('address') or {}
            features = property_data.get('features') or {}
            attributes = property_data.get('attributes') or {}
            pictures = property_data.get('pictures') or []
            services = property_data.get('services') or []
            contact = property_data.get('contact') or {}

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

            # Precisión de la ubicación: Tu360/Pulppo redondea coordenadas
            # cuando el vendedor oculta la direccion exacta (addressIsRounded).
            # manuallySet=false indica que vino de geocoding, no del mapa real.
            address_location = address.get('location') or {}
            is_rounded = bool(listing.get('addressIsRounded'))
            manually_set = bool(address_location.get('manuallySet'))
            ubicacion_aproximada = is_rounded or not manually_set

            # Ubicación (con normalización)
            ciudad_raw = (address.get('city') or {}).get('name', '')
            departamento_raw = (address.get('state') or {}).get('name', '')
            barrio_raw = (address.get('neighborhood') or {}).get('name', '')
            direccion = (
                address.get('streetAddress')
                or address.get('publicStreet')
                or address.get('street')
                or address.get('name')
                or ''
            )

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
            # Pulppo/Tu360 usa 'suites' como habitaciones; algunas propiedades
            # aun exponen 'bedrooms'/'rooms', así que probamos varios aliases.
            habitaciones = (
                attributes.get('suites')
                or attributes.get('bedrooms')
                or attributes.get('rooms')
                or features.get('bedrooms')
                or 0
            )
            banos = attributes.get('bathrooms') or features.get('bathrooms') or 0
            area_construida = attributes.get('roofedSurface') or attributes.get('totalSurface') or 0
            area_total = attributes.get('totalSurface') or area_construida or 0
            parqueaderos = attributes.get('parkings') or features.get('parkingSpaces') or 0
            piso = attributes.get('floor') or features.get('floor') or 0
            ano_construccion = attributes.get('yearBuild') or None
            antiguedad = features.get('age') or 0
            administracion = attributes.get('expenses') or None

            # Código
            codigo_interno = property_data.get('internalId', '')
            codigo_mongo = property_data.get('_id', '')

            # Imágenes — incluir todas las publicas y omitir planos/AI
            imagenes = []
            for pic in pictures:
                if not isinstance(pic, dict):
                    continue
                if pic.get('is_blueprint'):
                    continue
                if pic.get('public') is False:
                    continue
                img_url = pic.get('url', '')
                if img_url:
                    imagenes.append({
                        'url': img_url,
                        'descripcion': pic.get('description', ''),
                        'es_portada': len(imagenes) == 0
                    })

            # Amenidades/Servicios
            amenidades = [s.get('name', s) if isinstance(s, dict) else s for s in services]

            # Contacto (con validación de teléfono)
            agent_obj = contact.get('agent') or {}
            agente_nombre = (
                agent_obj.get('name')
                or ' '.join(filter(None, [agent_obj.get('firstName'), agent_obj.get('lastName')])).strip()
                or 'Tu360Inmobiliario'
            )
            agente_telefono_raw = agent_obj.get('phone', '')
            agente_telefono = PropertyNormalizer.validar_telefono(agente_telefono_raw) or agente_telefono_raw
            agente_email = agent_obj.get('email', '')

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
                'latitud': ((address.get('location') or {}).get('coordinates') or [None, None])[1],
                'longitud': ((address.get('location') or {}).get('coordinates') or [None, None])[0],

                # Características
                'habitaciones': habitaciones,
                'banos': banos,
                'area_construida': int(area_construida) if area_construida else (int(area_total) if area_total else None),
                'parqueaderos': parqueaderos,
                'piso': piso,
                'ano_construccion': ano_construccion or ((datetime.now().year - antiguedad) if antiguedad else None),
                'administracion': administracion,
                'ubicacion_aproximada': ubicacion_aproximada,

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
