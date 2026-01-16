#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper para propiedades de Lobbie App
Extrae datos de propiedades desde URLs del portal app.lobbieapp.com
"""

import sys
import io
import time

# Configurar UTF-8 para evitar errores de encoding en Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import requests
from bs4 import BeautifulSoup
import re
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


class LobbieScraper:
    """
    Scraper para extraer datos de propiedades de Lobbie App
    URL pattern: https://app.lobbieapp.com/sp/{code}/{id}/...
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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'es-CO,es;q=0.9,en;q=0.8',
        })

    def _log(self, message: str):
        """Imprime mensaje si verbose está activado"""
        if self.verbose:
            print(message)

    def _validar_url(self, url: str) -> bool:
        """
        Valida que la URL sea de Lobbie App

        Args:
            url: URL a validar

        Returns:
            True si es válida
        """
        patrones = [
            r'app\.lobbieapp\.com/sp/',
            r'lobbieapp\.com/sp/',
        ]
        return any(re.search(patron, url) for patron in patrones)

    def _extraer_codigo_propiedad(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        """
        Extrae el código de la propiedad

        Args:
            soup: BeautifulSoup object
            url: URL de la propiedad

        Returns:
            Código de la propiedad o None
        """
        # Buscar en h4 con patrón "Código #XXXXXX"
        for h4 in soup.find_all('h4'):
            text = h4.get_text(strip=True)
            match = re.search(r'C[oó]digo\s*#?\s*(\d+)', text, re.IGNORECASE)
            if match:
                return match.group(1)

        # Fallback: extraer de URL de imágenes
        img_tags = soup.find_all('img', src=re.compile(r'lobbie.*properties/(\d+)'))
        if img_tags:
            match = re.search(r'properties/(\d+)/', img_tags[0].get('src', ''))
            if match:
                return match.group(1)

        return None

    def _extraer_precio(self, soup: BeautifulSoup) -> Dict:
        """
        Extrae información de precio

        Args:
            soup: BeautifulSoup object

        Returns:
            Dict con precio y precio_texto
        """
        data = {'precio': None, 'precio_texto': None}

        # Buscar en h4 con patrón "Precio Venta: $XXX.XXX.XXX"
        for h4 in soup.find_all('h4'):
            text = h4.get_text(strip=True)
            if 'precio' in text.lower():
                data['precio_texto'] = text

                # Extraer valor numérico
                match = re.search(r'\$\s*([\d.,]+)', text)
                if match:
                    precio_str = match.group(1).replace('.', '').replace(',', '')
                    try:
                        data['precio'] = int(precio_str)
                    except ValueError:
                        pass
                break

        return data

    def _extraer_ubicacion(self, soup: BeautifulSoup) -> Dict:
        """
        Extrae información de ubicación

        Args:
            soup: BeautifulSoup object

        Returns:
            Dict con ciudad, zona, departamento
        """
        data = {
            'ciudad': None,
            'zona': None,
            'departamento': None,
            'direccion_completa': None,
            'pais': 'Colombia'
        }

        # Buscar en todos los h4 para encontrar ubicación
        # Patrón típico: "El Poblado" o "Medellin, Antioquia"
        for h4 in soup.find_all('h4'):
            text = h4.get_text(strip=True)

            # Detectar ciudad y departamento (patrón: "Ciudad, Departamento")
            if ',' in text and not '$' in text and not 'Código' in text:
                parts = text.split(',')
                if len(parts) >= 2:
                    # Verificar si parece ubicación (no es precio ni código)
                    possible_city = parts[0].strip()
                    possible_dept = parts[1].strip()

                    # Validar contra ciudades conocidas
                    if possible_city.lower() in ['medellin', 'medellín', 'envigado', 'sabaneta', 'itagui', 'itagüí', 'bello', 'bogota', 'bogotá', 'cali', 'barranquilla']:
                        data['ciudad'] = PropertyNormalizer.normalizar_ciudad(possible_city)
                        data['departamento'] = PropertyNormalizer.normalizar_departamento(possible_dept)
                        continue

            # Detectar zona/barrio (nombres típicos de zonas)
            zonas_conocidas = ['poblado', 'laureles', 'envigado', 'belén', 'belen', 'estadio',
                              'conquistadores', 'floresta', 'sabaneta', 'itagüí', 'itagui',
                              'la estrella', 'robledo', 'castropol', 'manila', 'ciudad del río']
            text_lower = text.lower()
            for zona in zonas_conocidas:
                if zona in text_lower and not data['zona']:
                    data['zona'] = text
                    break

        # Si no encontramos ciudad pero sí zona, inferir ciudad
        if not data['ciudad'] and data['zona']:
            zona_lower = data['zona'].lower() if data['zona'] else ''
            if any(z in zona_lower for z in ['poblado', 'laureles', 'belén', 'estadio', 'conquistadores']):
                data['ciudad'] = 'Medellín'
                data['departamento'] = 'Antioquia'
            elif 'envigado' in zona_lower:
                data['ciudad'] = 'Envigado'
                data['departamento'] = 'Antioquia'
            elif 'sabaneta' in zona_lower:
                data['ciudad'] = 'Sabaneta'
                data['departamento'] = 'Antioquia'

        return data

    def _extraer_caracteristicas(self, soup: BeautifulSoup) -> Dict:
        """
        Extrae características físicas de la propiedad

        Args:
            soup: BeautifulSoup object

        Returns:
            Dict con habitaciones, baños, área, parqueaderos, etc.
        """
        data = {
            'habitaciones': None,
            'banos': None,
            'area_construida': None,
            'parqueaderos': None,
            'estrato': None,
            'ano_construccion': None,
            'piso': None,
            'tipo_propiedad': None,
        }

        # Buscar en todos los h4 para características
        for h4 in soup.find_all('h4'):
            text = h4.get_text(strip=True).lower()

            # Habitaciones
            if 'habitacion' in text or 'alcoba' in text:
                match = re.search(r'(\d+)', text)
                if match:
                    data['habitaciones'] = int(match.group(1))

            # Baños
            elif 'baño' in text or 'bano' in text:
                match = re.search(r'(\d+)', text)
                if match:
                    data['banos'] = int(match.group(1))

            # Área
            elif 'm2' in text or 'm²' in text or 'metros' in text:
                match = re.search(r'(\d+(?:[.,]\d+)?)', text)
                if match:
                    data['area_construida'] = float(match.group(1).replace(',', '.'))

            # Parqueaderos
            elif 'parqueadero' in text or 'garaje' in text or 'parking' in text:
                match = re.search(r'(\d+)', text)
                if match:
                    data['parqueaderos'] = int(match.group(1))

            # Estrato
            elif 'estrato' in text:
                match = re.search(r'(\d+)', text)
                if match:
                    data['estrato'] = int(match.group(1))

            # Año de construcción
            elif 'año' in text or 'construido' in text or 'antigüedad' in text:
                match = re.search(r'(19\d{2}|20\d{2})', text)
                if match:
                    data['ano_construccion'] = int(match.group(1))

            # Piso/Nivel
            elif 'piso' in text or 'nivel' in text:
                match = re.search(r'(\d+)', text)
                if match:
                    data['piso'] = int(match.group(1))

        # Detectar tipo de propiedad del título o contenido
        full_text = soup.get_text().lower()
        if 'apartamento' in full_text or 'apto' in full_text:
            data['tipo_propiedad'] = 'Apartamento'
        elif 'casa' in full_text:
            data['tipo_propiedad'] = 'Casa'
        elif 'local' in full_text:
            data['tipo_propiedad'] = 'Local Comercial'
        elif 'oficina' in full_text:
            data['tipo_propiedad'] = 'Oficina'
        elif 'lote' in full_text or 'terreno' in full_text:
            data['tipo_propiedad'] = 'Lote'

        return data

    def _extraer_costos(self, soup: BeautifulSoup) -> Dict:
        """
        Extrae costos adicionales (administración, predial)

        Args:
            soup: BeautifulSoup object

        Returns:
            Dict con administracion y predial
        """
        data = {
            'administracion': None,
            'predial': None
        }

        for h4 in soup.find_all('h4'):
            text = h4.get_text(strip=True).lower()

            # Administración
            if 'administraci' in text or 'admon' in text:
                match = re.search(r'\$?\s*([\d.,]+)', text)
                if match:
                    admin_str = match.group(1).replace('.', '').replace(',', '')
                    try:
                        data['administracion'] = int(admin_str)
                    except ValueError:
                        pass

            # Predial
            elif 'predial' in text:
                match = re.search(r'\$?\s*([\d.,]+)', text)
                if match:
                    predial_str = match.group(1).replace('.', '').replace(',', '')
                    try:
                        data['predial'] = int(predial_str)
                    except ValueError:
                        pass

        return data

    def _extraer_amenidades(self, soup: BeautifulSoup) -> Dict:
        """
        Extrae amenidades de la propiedad

        Args:
            soup: BeautifulSoup object

        Returns:
            Dict con amenidades internas, externas y total
        """
        data = {
            'amenidades_internas': None,
            'amenidades_externas': None,
            'total_amenidades': 0
        }

        amenidades = []

        # Buscar imágenes de check/ok seguidas de texto
        for img in soup.find_all('img', src=re.compile(r'ok|check|tick', re.IGNORECASE)):
            # El texto de amenidad suele estar después del img
            next_text = img.next_sibling
            if next_text and isinstance(next_text, str):
                amenidad = next_text.strip()
                if amenidad and len(amenidad) > 2 and len(amenidad) < 50:
                    amenidades.append(amenidad)

        # También buscar en listas
        for li in soup.find_all('li'):
            text = li.get_text(strip=True)
            # Filtrar amenidades típicas
            keywords = ['piscina', 'gimnasio', 'ascensor', 'portería', 'vigilancia',
                       'parqueadero', 'balcón', 'terraza', 'cocina', 'jardín',
                       'bbq', 'salón', 'zona social', 'cuarto útil', 'depósito']
            if any(kw in text.lower() for kw in keywords):
                if text not in amenidades:
                    amenidades.append(text)

        # Clasificar amenidades
        internas = []
        externas = []

        amenidades_externas_keywords = ['piscina', 'gimnasio', 'ascensor', 'portería',
                                        'vigilancia', 'zona social', 'salón comunal',
                                        'parque', 'cancha', 'bbq', 'turco', 'sauna']

        for amenidad in amenidades:
            amenidad_lower = amenidad.lower()
            if any(kw in amenidad_lower for kw in amenidades_externas_keywords):
                externas.append(amenidad)
            else:
                internas.append(amenidad)

        data['amenidades_internas'] = ' | '.join(internas) if internas else None
        data['amenidades_externas'] = ' | '.join(externas) if externas else None
        data['total_amenidades'] = len(amenidades)

        return data

    def _extraer_imagenes(self, soup: BeautifulSoup) -> Dict:
        """
        Extrae URLs de imágenes

        Args:
            soup: BeautifulSoup object

        Returns:
            Dict con URLs de imágenes
        """
        data = {
            'imagenes_urls': None,
            'imagen_principal': None,
            'total_imagenes': 0
        }

        images = []

        # Buscar imágenes de Lobbie S3
        for img in soup.find_all('img', src=re.compile(r'lobbie.*s3.*amazonaws')):
            src = img.get('src', '')
            if src and src not in images:
                # Filtrar iconos pequeños
                if 'properties' in src and ('photos' in src or 'images' in src):
                    images.append(src)

        # También buscar en data-src (lazy loading)
        for img in soup.find_all('img', attrs={'data-src': re.compile(r'lobbie.*s3')}):
            src = img.get('data-src', '')
            if src and src not in images:
                images.append(src)

        # Buscar en enlaces también
        for a in soup.find_all('a', href=re.compile(r'lobbie.*s3.*amazonaws')):
            href = a.get('href', '')
            if href and href not in images and ('photos' in href or 'images' in href):
                images.append(href)

        data['imagenes_urls'] = ' | '.join(images) if images else None
        data['imagen_principal'] = images[0] if images else None
        data['total_imagenes'] = len(images)

        return data

    def _extraer_descripcion(self, soup: BeautifulSoup) -> Dict:
        """
        Extrae la descripción de la propiedad

        Args:
            soup: BeautifulSoup object

        Returns:
            Dict con descripción
        """
        data = {
            'descripcion': None,
            'titulo': None
        }

        # Buscar descripción en párrafos largos
        paragraphs = soup.find_all('p')
        longest_text = ''

        for p in paragraphs:
            text = p.get_text(strip=True)
            # Ignorar textos muy cortos o que son claramente no descripción
            if len(text) > 50 and len(text) > len(longest_text):
                # Verificar que no sea un texto de marketing de Lobbie
                if 'lobbie' not in text.lower() and 'app' not in text.lower():
                    longest_text = text

        if longest_text:
            data['descripcion'] = longest_text

        # Extraer título (primer h1 o h2)
        title_tag = soup.find('h1') or soup.find('h2')
        if title_tag:
            titulo_raw = title_tag.get_text(strip=True)
            data['titulo'] = PropertyNormalizer.limpiar_titulo_propiedad(titulo_raw)

        return data

    def extract_property_data(self, url: str) -> Optional[Dict]:
        """
        Extrae todos los datos de una propiedad de Lobbie

        Args:
            url: URL de la propiedad

        Returns:
            Dict con los datos de la propiedad o None si falla
        """
        total_start = time.time()

        # Iniciar tracking del scrape
        if scraper_log:
            scraper_log.start_scrape(url, 'Lobbie')

        self._log(f"\n{'='*80}")
        self._log(f"SCRAPEANDO LOBBIE: {url}")
        self._log(f"{'='*80}\n")

        # Validar URL
        if not self._validar_url(url):
            self._log("[ERROR] URL no válida. Debe ser de app.lobbieapp.com")
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

            # Parsear HTML
            self._log("[2/3] Parseando HTML...")
            soup = BeautifulSoup(html, 'lxml')

            # Extraer datos
            self._log("[3/3] Extrayendo información...")

            # Datos base
            data = {
                'url': url,
                'fuente': 'Lobbie',
                'fecha_extraccion': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'estado': 'Disponible'
            }

            # Código de propiedad
            codigo = self._extraer_codigo_propiedad(soup, url)
            data['codigo_propiedad'] = codigo
            if scraper_log:
                scraper_log.log_data_extraction('codigo_propiedad', codigo, bool(codigo))

            # Precio
            precio_data = self._extraer_precio(soup)
            data.update(precio_data)
            if scraper_log:
                scraper_log.log_data_extraction('precio', precio_data.get('precio'), bool(precio_data.get('precio')))

            # Ubicación
            ubicacion_data = self._extraer_ubicacion(soup)
            data.update(ubicacion_data)
            if scraper_log:
                scraper_log.log_data_extraction('ciudad', ubicacion_data.get('ciudad'), bool(ubicacion_data.get('ciudad')))
                scraper_log.log_data_extraction('zona', ubicacion_data.get('zona'), bool(ubicacion_data.get('zona')))

            # Características físicas
            caracteristicas_data = self._extraer_caracteristicas(soup)
            data.update(caracteristicas_data)
            if scraper_log:
                scraper_log.log_data_extraction('habitaciones', caracteristicas_data.get('habitaciones'),
                                                caracteristicas_data.get('habitaciones') is not None)
                scraper_log.log_data_extraction('area_construida', caracteristicas_data.get('area_construida'),
                                                caracteristicas_data.get('area_construida') is not None)

            # Costos adicionales
            costos_data = self._extraer_costos(soup)
            data.update(costos_data)
            if scraper_log:
                scraper_log.log_data_extraction('administracion', costos_data.get('administracion'),
                                                costos_data.get('administracion') is not None)

            # Amenidades
            amenidades_data = self._extraer_amenidades(soup)
            data.update(amenidades_data)
            if scraper_log:
                scraper_log.log_data_extraction('amenidades', amenidades_data.get('total_amenidades'),
                                                amenidades_data.get('total_amenidades', 0) > 0)

            # Imágenes
            imagenes_data = self._extraer_imagenes(soup)
            data.update(imagenes_data)
            if scraper_log:
                scraper_log.log_images_extracted(imagenes_data.get('total_imagenes', 0),
                                                 imagenes_data.get('total_imagenes', 0))

            # Descripción y título
            descripcion_data = self._extraer_descripcion(soup)
            data.update(descripcion_data)

            # Generar título si no existe
            if not data.get('titulo'):
                tipo = data.get('tipo_propiedad', 'Propiedad')
                zona = data.get('zona', data.get('ciudad', ''))
                data['titulo'] = f"{tipo} en {zona}" if zona else tipo

            total_elapsed = (time.time() - total_start) * 1000

            # Log de éxito
            self._log(f"\n[OK] Propiedad extraída exitosamente")
            self._log(f"  Código: {data.get('codigo_propiedad')}")
            self._log(f"  Precio: {data.get('precio_texto')}")
            self._log(f"  Ubicación: {data.get('zona')}, {data.get('ciudad')}")
            self._log(f"  Tipo: {data.get('tipo_propiedad')}")
            self._log(f"  Características: {data.get('habitaciones')} hab, {data.get('banos')} baños, {data.get('area_construida')} m²")
            self._log(f"  Imágenes: {data.get('total_imagenes')}")
            self._log(f"  Tiempo: {total_elapsed:.0f}ms\n")

            if scraper_log:
                try:
                    scraper_log.log_complete(data.get('codigo_propiedad', 'unknown'), total_elapsed)
                except Exception:
                    pass

            # === FASE 3: New Relic metrics ===
            newrelic.agent.record_custom_metric('Custom/Scraper/Lobbie/Duration', total_elapsed)
            newrelic.agent.record_custom_metric('Custom/Scraper/Lobbie/Success', 1)

            return data

        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP Error {e.response.status_code}: {url}"
            self._log(f"[ERROR] {error_msg}")
            if scraper_log:
                scraper_log.log_error(str(e), 'http_error')
            return None

        except requests.exceptions.Timeout as e:
            error_msg = f"Timeout: {url}"
            self._log(f"[TIMEOUT] {error_msg}")
            if scraper_log:
                scraper_log.log_error(str(e), 'timeout')
            return None

        except Exception as e:
            error_msg = f"Error procesando {url}: {str(e)}"
            self._log(f"[ERROR] {error_msg}")
            if scraper_log:
                scraper_log.log_error(str(e), 'extraction')
            return None


def main():
    """Función principal para testing"""
    print("""
╔════════════════════════════════════════════════════════════╗
║                   LOBBIE PROPERTY SCRAPER                   ║
║                    Proyecto Cupido Tu360                    ║
╚════════════════════════════════════════════════════════════╝
    """)

    # URL de prueba
    test_url = "https://app.lobbieapp.com/sp/1gv6/GQ/1/1"

    # Crear scraper
    scraper = LobbieScraper(verbose=True)

    # Extraer datos
    data = scraper.extract_property_data(test_url)

    if data:
        print("\n" + "="*60)
        print("DATOS EXTRAÍDOS:")
        print("="*60)
        for key, value in data.items():
            if value is not None:
                # Truncar valores largos
                if isinstance(value, str) and len(value) > 100:
                    value = value[:100] + "..."
                print(f"  {key}: {value}")
    else:
        print("\n[ERROR] No se pudieron extraer los datos")


if __name__ == "__main__":
    main()
