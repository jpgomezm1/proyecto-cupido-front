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
            r'app\.lobbieapp\.com/sp/',       # formato antiguo
            r'app\.lobbieapp\.com/inmueble/',  # formato nuevo (Next.js) 2026+
            r'lobbieapp\.com/sp/',
            r'lobbieapp\.com/inmueble/',
        ]
        return any(re.search(patron, url) for patron in patrones)

    def _extraer_meta_tags(self, soup: BeautifulSoup) -> Dict:
        """
        Extrae datos desde OpenGraph meta tags (fuente más confiable)

        Args:
            soup: BeautifulSoup object

        Returns:
            Dict con og:title, og:description, og:image
        """
        data = {
            'og_title': None,
            'og_description': None,
            'og_image': None
        }

        # og:title
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            data['og_title'] = og_title.get('content').strip()

        # og:description
        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            data['og_description'] = og_desc.get('content').strip()

        # og:image
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            data['og_image'] = og_image.get('content').strip()

        return data

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
        data = {'precio': None, 'precio_texto': None, 'tipo_negocio': 'Venta'}

        # Buscar en h4 con patrón "Precio Venta: $XXX.XXX.XXX" o "Precio Arriendo: ..."
        for h4 in soup.find_all('h4'):
            text = h4.get_text(strip=True)
            if 'precio' in text.lower():
                data['precio_texto'] = text

                # Detectar tipo de negocio desde el texto del h4
                text_lower = text.lower()
                if 'arriendo' in text_lower or 'arrendamiento' in text_lower or 'renta' in text_lower:
                    data['tipo_negocio'] = 'Arriendo'

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
        PRIORIDAD: orbit-holder carousel > og:image > S3 images

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

        # Método 1: Carrusel orbit-holder (galería principal de Lobbie)
        orbit = soup.find('ul', class_='orbit-holder')
        if orbit:
            for img in orbit.find_all('img', src=True):
                src = img.get('src', '')
                if src and src not in images:
                    images.append(src)

        # Método 2: og:image como respaldo para imagen principal
        meta_tags = self._extraer_meta_tags(soup)
        if meta_tags.get('og_image') and meta_tags['og_image'] not in images:
            images.insert(0, meta_tags['og_image'])

        # Método 3: Buscar imágenes de S3 de Lobbie (fallback)
        if not images:
            for img in soup.find_all('img', src=re.compile(r'lobbie.*s3.*amazonaws')):
                src = img.get('src', '')
                if src and src not in images:
                    if 'properties' in src and ('photos' in src or 'images' in src):
                        images.append(src)

        # Método 4: data-src para lazy loading
        if not images:
            for img in soup.find_all('img', attrs={'data-src': re.compile(r'lobbie.*s3')}):
                src = img.get('data-src', '')
                if src and src not in images:
                    images.append(src)

        # Método 5: Buscar en enlaces (último recurso)
        if not images:
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
        Extrae la descripción y título de la propiedad
        PRIORIDAD: OpenGraph > elementos específicos > fallbacks

        Args:
            soup: BeautifulSoup object

        Returns:
            Dict con descripción y titulo
        """
        data = {
            'descripcion': None,
            'titulo': None
        }

        # Extraer meta tags primero
        meta_tags = self._extraer_meta_tags(soup)

        # === TÍTULO ===
        # Prioridad 1: og:title (más confiable)
        if meta_tags.get('og_title'):
            titulo_raw = meta_tags['og_title']
            # Limpiar prefijos comunes de Lobbie
            titulo_raw = re.sub(r'^(Lobbie\s*[-|:]\s*)', '', titulo_raw, flags=re.IGNORECASE)
            data['titulo'] = PropertyNormalizer.limpiar_titulo_propiedad(titulo_raw)

        # Prioridad 2: h4 dentro de .card (título de propiedad)
        if not data['titulo']:
            card = soup.find('div', class_='card')
            if card:
                h4_title = card.find('h4')
                if h4_title:
                    titulo_raw = h4_title.get_text(strip=True)
                    # Verificar que no sea precio o código
                    if not re.search(r'(precio|código|\$)', titulo_raw, re.IGNORECASE):
                        data['titulo'] = PropertyNormalizer.limpiar_titulo_propiedad(titulo_raw)

        # Prioridad 3: <title> del documento
        if not data['titulo']:
            title_tag = soup.find('title')
            if title_tag:
                titulo_raw = title_tag.get_text(strip=True)
                # Remover "Lobbie" del título
                titulo_raw = re.sub(r'\s*[-|]\s*Lobbie.*$', '', titulo_raw, flags=re.IGNORECASE)
                titulo_raw = re.sub(r'^Lobbie\s*[-|:]\s*', '', titulo_raw, flags=re.IGNORECASE)
                if titulo_raw and len(titulo_raw) > 5:
                    data['titulo'] = PropertyNormalizer.limpiar_titulo_propiedad(titulo_raw)

        # === DESCRIPCIÓN ===
        # Prioridad 1: og:description
        if meta_tags.get('og_description'):
            data['descripcion'] = meta_tags['og_description']

        # Prioridad 2: elemento <pre> (usado por Lobbie para descripciones largas)
        if not data['descripcion']:
            pre_tag = soup.find('pre')
            if pre_tag:
                desc_text = pre_tag.get_text(strip=True)
                if len(desc_text) > 30:
                    data['descripcion'] = desc_text

        # Prioridad 3: párrafos largos (sin filtro restrictivo de "lobbie")
        if not data['descripcion']:
            paragraphs = soup.find_all('p')
            longest_text = ''
            for p in paragraphs:
                text = p.get_text(strip=True)
                if len(text) > 50 and len(text) > len(longest_text):
                    # Solo excluir textos que sean claramente marketing del sitio
                    if not re.search(r'(descarga\s+la\s+app|registrate|crear\s+cuenta)', text, re.IGNORECASE):
                        longest_text = text
            if longest_text:
                data['descripcion'] = longest_text

        return data

    def _extraer_datos_ssr(self, soup: BeautifulSoup, html: str) -> Dict:
        """
        Extrae datos del formato NUEVO de Lobbie (app Next.js / server-side render,
        rutas /inmueble/...). El contenido ya NO usa <h4>/<pre>/orbit-holder; los
        datos vienen renderizados como texto etiquetado en una tabla
        "Datos principales" y las imágenes como URLs de CloudFront en <link preload>.

        Args:
            soup: BeautifulSoup del HTML
            html: HTML crudo (para extraer URLs de imágenes)

        Returns:
            Dict con los campos de la propiedad
        """
        data: Dict = {}

        # Texto visible normalizado (todo el DOM renderizado)
        txt = re.sub(r'\s+', ' ', soup.get_text(' ', strip=True))

        # Acotar los campos numéricos a la tabla "Datos principales" para evitar
        # colisiones con el encabezado (que usa "N baños" en vez de "Baños N").
        m_tabla = re.search(r'Datos principales(.+?)(?:Descripci[oó]n|Esta p[aá]gina)', txt, re.I)
        tabla = m_tabla.group(1) if m_tabla else txt

        def _buscar(patron: str, fuente: str, cast=None):
            m = re.search(patron, fuente, re.I)
            if not m:
                return None
            valor = m.group(1).strip()
            if cast is None:
                return valor
            try:
                return cast(valor)
            except (ValueError, TypeError):
                return None

        def _int_puntos(v: str) -> int:
            return int(v.replace('.', '').replace(',', ''))

        # --- Código de propiedad ---
        data['codigo_propiedad'] = _buscar(r'C[oó]digo\s*(\d+)', tabla) \
            or _buscar(r'C[oó]digo:?\s*(\d+)', txt)

        # --- Precio y tipo de negocio ---
        precio = _buscar(r'Precio\s*COP\s*([\d.]+)', tabla, _int_puntos) \
            or _buscar(r'COP\s*([\d.]+)', txt, _int_puntos)
        data['precio'] = precio
        es_arriendo = bool(re.search(r'\ben\s+arriendo\b|arrendamiento|renta\b|canon', txt, re.I))
        data['tipo_negocio'] = 'Arriendo' if es_arriendo else 'Venta'
        if precio:
            etiqueta = 'Arriendo' if es_arriendo else 'Venta'
            data['precio_texto'] = f"Precio {etiqueta}: COP {precio:,.0f}".replace(',', '.')

        # --- Características físicas (desde la tabla) ---
        data['area_construida'] = _buscar(r'[ÁA]rea\s*(\d+(?:[.,]\d+)?)', tabla,
                                           lambda v: float(v.replace(',', '.')))
        data['habitaciones'] = _buscar(r'Habitaciones\s*(\d+)', tabla, int)
        data['banos'] = _buscar(r'Ba[ñn]os\s*(\d+)', tabla, int)
        data['parqueaderos'] = _buscar(r'Parqueaderos\s*(\d+)', tabla, int)
        estrato = _buscar(r'Estrato\s*(\d+)', tabla, int)
        data['estrato'] = estrato if estrato else None  # 0 = no especificado
        data['ano_construccion'] = _buscar(r'A[ñn]o construido\s*(\d{4})', tabla, int)
        data['piso'] = None

        admin = _buscar(r'Administraci[oó]n\s*([\d.]+)', tabla)
        data['administracion'] = _int_puntos(admin) if admin else None
        predial = _buscar(r'Predial\s*([\d.]+)', tabla)
        data['predial'] = _int_puntos(predial) if predial else None

        # --- Tipo de propiedad y ubicación (desde el encabezado) ---
        m_header = re.search(r'compartido\s+(.+?)\s+C[oó]digo:', txt, re.I)
        header = m_header.group(1).strip() if m_header else ''

        m_tipo = re.search(
            r'\b(Apartaestudio|Apartamento|Casa|Penthouse|Duplex|Local|Oficina|Bodega|Finca|Lote)\b',
            header, re.I)
        data['tipo_propiedad'] = PropertyNormalizer.normalizar_tipo_propiedad(
            m_tipo.group(1)) if m_tipo else None

        # Quitar el prefijo "{Tipo} en {arriendo|venta}" para dejar "ZONA, Ciudad, Depto"
        loc = re.sub(r'^.*?\ben\s+(?:arriendo|arrendamiento|renta|venta)\s+', '',
                     header, flags=re.I).strip()
        partes = [p.strip() for p in loc.split(',') if p.strip()]
        data['pais'] = 'Colombia'
        data['zona'] = PropertyNormalizer.normalizar_barrio(partes[0]) if len(partes) >= 1 else None
        data['ciudad'] = PropertyNormalizer.normalizar_ciudad(partes[1]) if len(partes) >= 2 else None
        data['departamento'] = PropertyNormalizer.normalizar_departamento(partes[2]) if len(partes) >= 3 else None
        data['direccion_completa'] = loc or None

        # --- Descripción ---
        m_desc = re.search(r'Descripci[oó]n\s+(.+?)\s+Esta p[aá]gina fue creada', txt, re.I)
        data['descripcion'] = m_desc.group(1).strip() if m_desc else None

        # --- Título ---
        if data.get('tipo_propiedad') and data.get('zona'):
            data['titulo'] = PropertyNormalizer.limpiar_titulo_propiedad(
                f"{data['tipo_propiedad']} en {data['zona']}")

        # --- Imágenes (CloudFront, en <link rel=preload> y <img>) ---
        imgs = sorted(set(re.findall(
            r'https://[a-z0-9.]*cloudfront\.net/properties/\d+/photos/\d+/[^"&\\ ]+\.(?:jpg|jpeg|png|webp)',
            html, re.I)))
        # Respaldo: og:image (proxy de Lobbie) si no hubo CloudFront
        if not imgs:
            meta = self._extraer_meta_tags(soup)
            if meta.get('og_image'):
                imgs = [meta['og_image']]
        data['imagenes_urls'] = ' | '.join(imgs) if imgs else None
        data['imagen_principal'] = imgs[0] if imgs else None
        data['total_imagenes'] = len(imgs)

        # --- Amenidades: el formato nuevo no las lista en el HTML renderizado ---
        data['amenidades_internas'] = None
        data['amenidades_externas'] = None
        data['total_amenidades'] = 0

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

            # Detectar formato: el formato nuevo (Next.js, rutas /inmueble/) NO
            # tiene <h4>; los datos van en una tabla "Datos principales".
            usa_formato_legacy = bool(soup.find_all('h4'))

            if not usa_formato_legacy:
                # ===== FORMATO NUEVO (SSR /inmueble/) =====
                self._log("   Formato detectado: nuevo (Next.js SSR)")
                data.update(self._extraer_datos_ssr(soup, html))
                if scraper_log:
                    scraper_log.log_data_extraction('codigo_propiedad', data.get('codigo_propiedad'), bool(data.get('codigo_propiedad')))
                    scraper_log.log_data_extraction('precio', data.get('precio'), bool(data.get('precio')))
                    scraper_log.log_data_extraction('ciudad', data.get('ciudad'), bool(data.get('ciudad')))
                    scraper_log.log_data_extraction('zona', data.get('zona'), bool(data.get('zona')))
                    scraper_log.log_data_extraction('habitaciones', data.get('habitaciones'), data.get('habitaciones') is not None)
                    scraper_log.log_images_extracted(data.get('total_imagenes', 0), data.get('total_imagenes', 0))
            else:
                # ===== FORMATO LEGACY (/sp/) =====
                self._log("   Formato detectado: legacy (/sp/)")
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
            self._log(f"  Título: {data.get('titulo')}")
            self._log(f"  Código: {data.get('codigo_propiedad')}")
            self._log(f"  Precio: {data.get('precio_texto')}")
            self._log(f"  Ubicación: {data.get('zona')}, {data.get('ciudad')}")
            self._log(f"  Tipo: {data.get('tipo_propiedad')}")
            self._log(f"  Características: {data.get('habitaciones')} hab, {data.get('banos')} baños, {data.get('area_construida')} m²")
            self._log(f"  Imágenes: {data.get('total_imagenes')}")
            self._log(f"  Descripción: {data.get('descripcion')[:80] + '...' if data.get('descripcion') else 'N/A'}")
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

    # URL de prueba (formato nuevo /inmueble/)
    test_url = "https://app.lobbieapp.com/inmueble/1i4W?a=1&s=0&u=e944f387-e9ac-4ac0-b121-39eae55030cb"

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
