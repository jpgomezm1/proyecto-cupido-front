#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scraper de propiedades de Wasi
Extrae información completa de propiedades inmobiliarias desde info.wasi.co
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import time
import re
from datetime import datetime
from tqdm import tqdm
import os
from urllib.parse import unquote
import newrelic.agent

# Importar sistema de logging
try:
    from src.core.logger import get_scraper_logger
    scraper_log = get_scraper_logger()
except ImportError:
    scraper_log = None


class WasiScraper:
    """Clase para scrapear propiedades de Wasi con enriquecimiento AI"""

    def __init__(self, delay=2, verbose=False, enable_ai_enrichment=True):
        """
        Inicializa el scraper

        Args:
            delay (int): Segundos de espera entre requests
            verbose (bool): Modo detallado de logging
            enable_ai_enrichment (bool): Si True, enriquece con AI
        """
        self.delay = delay
        self.verbose = verbose
        self.enable_ai_enrichment = enable_ai_enrichment
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.properties_data = []
        self.errors = []

        # Inicializar AI enricher si está habilitado
        self.enricher = None
        if self.enable_ai_enrichment:
            try:
                from property_ai_enricher import PropertyAIEnricher
                self.enricher = PropertyAIEnricher(verbose=self.verbose)
                self.log("✅ AI Enrichment activado")
            except Exception as e:
                self.log(f"⚠️  No se pudo activar AI Enrichment: {e}")
                self.enable_ai_enrichment = False

    def log(self, message):
        """Imprime mensaje si verbose está activado"""
        if self.verbose:
            print(f"[LOG] {message}")

    def extract_property_data(self, url):
        """
        Extrae todos los datos de una propiedad

        Args:
            url (str): URL de la propiedad en Wasi

        Returns:
            dict: Diccionario con toda la información extraída
        """
        total_start = time.time()

        # Decodificar URL para evitar doble encoding (ej: %C3%AD -> í)
        # Esto es necesario porque requests re-codifica las URLs y Wasi rechaza la doble codificación
        url = unquote(url)

        # Iniciar tracking del scrape
        if scraper_log:
            scraper_log.start_scrape(url, 'Wasi')

        try:
            self.log(f"Obteniendo página: {url}")

            # Descargar página (usar request directo en lugar de session para evitar acumulación de cookies)
            download_start = time.time()
            response = requests.get(url, headers=self.session.headers, timeout=30)
            response.raise_for_status()
            download_elapsed = (time.time() - download_start) * 1000

            if scraper_log:
                scraper_log.log_page_download(url, response.status_code, download_elapsed)

            soup = BeautifulSoup(response.content, 'lxml')

            # Diccionario para almacenar todos los datos
            data = {
                'url': url,
                'fuente': 'Wasi',  # Identificador de la fuente
                'fecha_extraccion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            # === TIPO DE NEGOCIO ===
            # Detectar desde URL (/arriendo en path) y fallback desde título
            url_lower = url.lower()
            if '/arriendo' in url_lower or '/rent' in url_lower or '/alquiler' in url_lower:
                data['tipo_negocio'] = 'Arriendo'
            else:
                # Fallback: revisar título raw antes del cleaning
                title_tag = soup.find('h1', class_='title') or soup.find('h1')
                titulo_raw = title_tag.text.strip().lower() if title_tag else ''
                if 'arriendo' in titulo_raw or 'se arrienda' in titulo_raw or 'arrendamiento' in titulo_raw:
                    data['tipo_negocio'] = 'Arriendo'
                else:
                    data['tipo_negocio'] = 'Venta'

            # === INFORMACIÓN BÁSICA ===
            basic_info = self._extract_basic_info(soup)
            data.update(basic_info)
            if scraper_log:
                scraper_log.log_data_extraction('titulo', basic_info.get('titulo'), bool(basic_info.get('titulo')))
                scraper_log.log_data_extraction('precio', basic_info.get('precio'), bool(basic_info.get('precio')))
                scraper_log.log_data_extraction('codigo_propiedad', basic_info.get('codigo_propiedad'), bool(basic_info.get('codigo_propiedad')))

            # === UBICACIÓN ===
            location = self._extract_location(soup)
            data.update(location)
            if scraper_log:
                scraper_log.log_data_extraction('ciudad', location.get('ciudad'), bool(location.get('ciudad')))
                scraper_log.log_data_extraction('zona', location.get('zona'), bool(location.get('zona')))

            # === CARACTERÍSTICAS FÍSICAS ===
            features = self._extract_physical_features(soup)
            data.update(features)
            if scraper_log:
                scraper_log.log_data_extraction('habitaciones', features.get('habitaciones'), features.get('habitaciones') is not None)
                scraper_log.log_data_extraction('area_construida', features.get('area_construida'), features.get('area_construida') is not None)

            # === COSTOS ===
            costs = self._extract_costs(soup)
            data.update(costs)
            if scraper_log:
                scraper_log.log_data_extraction('administracion', costs.get('administracion'), costs.get('administracion') is not None)

            # === AMENIDADES ===
            amenities = self._extract_amenities(soup)
            data.update(amenities)
            if scraper_log:
                scraper_log.log_data_extraction('amenidades', amenities.get('total_amenidades'), amenities.get('total_amenidades', 0) > 0)

            # === CONTACTO ===
            contact = self._extract_contact(soup)
            data.update(contact)

            # === IMÁGENES ===
            images = self._extract_images(soup)
            data.update(images)
            if scraper_log:
                scraper_log.log_images_extracted(images.get('total_imagenes', 0), images.get('imagenes_hd_count', 0))

            # === DESCRIPCIÓN ===
            desc = self._extract_description(soup)
            data.update(desc)

            total_elapsed = (time.time() - total_start) * 1000
            self.log(f"[OK] Datos extraidos exitosamente de {url}")

            # === FASE 3: New Relic metrics ===
            newrelic.agent.record_custom_metric('Custom/Scraper/Wasi/Duration', total_elapsed)
            newrelic.agent.record_custom_metric('Custom/Scraper/Wasi/Success', 1)

            if scraper_log:
                try:
                    scraper_log.log_complete(data.get('codigo_propiedad', 'unknown'), total_elapsed)
                except Exception:
                    pass  # Ignorar errores de logging

            return data

        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP Error {e.response.status_code}: {url}"
            print(f"   [ERROR] {error_msg}")
            self.errors.append({'url': url, 'error': str(e), 'timestamp': datetime.now()})
            if scraper_log:
                try:
                    scraper_log.log_error(str(e), 'http_error')
                except Exception:
                    pass
            return None

        except requests.exceptions.Timeout as e:
            error_msg = f"Timeout: {url}"
            print(f"   [TIMEOUT] {error_msg}")
            self.errors.append({'url': url, 'error': 'Timeout', 'timestamp': datetime.now()})
            if scraper_log:
                try:
                    scraper_log.log_error(str(e), 'timeout')
                except Exception:
                    pass
            return None

        except Exception as e:
            error_msg = f"Error procesando {url}: {str(e)}"
            print(f"   [ERROR] {error_msg}")
            self.errors.append({'url': url, 'error': str(e), 'timestamp': datetime.now()})

            if scraper_log:
                try:
                    scraper_log.log_error(str(e), 'extraction')
                except Exception:
                    pass

            return None

    def _extract_basic_info(self, soup):
        """Extrae información básica de la propiedad"""
        from src.scrapers.utils import PropertyNormalizer

        data = {}

        # Título - limpiar con AI para quitar "Venta", "Arriendo", etc.
        title_tag = soup.find('h1', class_='title') or soup.find('h1')
        titulo_raw = title_tag.text.strip() if title_tag else None
        data['titulo'] = PropertyNormalizer.limpiar_titulo_propiedad(titulo_raw) if titulo_raw else None

        # Precio - usando selector correcto
        price_tag = soup.find('p', class_='pr1')
        if price_tag:
            price_text = price_tag.text.strip()
            # Extraer solo números
            price_clean = re.sub(r'[^\d]', '', price_text)
            data['precio'] = int(price_clean) if price_clean else None
            data['precio_texto'] = price_text
        else:
            data['precio'] = None
            data['precio_texto'] = None

        # Código de propiedad desde la URL
        code_match = re.search(r'/(\d+)(?:\?|$)', data.get('url', ''))
        if not code_match:
            # Intentar desde script con variable JavaScript
            script_tag = soup.find('script', string=re.compile(r'var id_bien\s*='))
            if script_tag:
                id_match = re.search(r'var id_bien\s*=\s*(\d+)', script_tag.string)
                data['codigo_propiedad'] = id_match.group(1) if id_match else None
            else:
                data['codigo_propiedad'] = None
        else:
            data['codigo_propiedad'] = code_match.group(1)

        # Tipo de propiedad - desde list-info-1a
        tipo_li = None
        for li in soup.find_all('li'):
            if 'Tipo Inmueble:' in li.text:
                tipo_li = li
                break
        if tipo_li:
            data['tipo_propiedad'] = tipo_li.text.replace('Tipo Inmueble:', '').strip()
        else:
            data['tipo_propiedad'] = None

        # Estado - buscar en estado del inmueble
        estado_li = None
        for li in soup.find_all('li'):
            if 'Estado:' in li.text:
                estado_li = li
                break
        if estado_li:
            data['estado'] = estado_li.text.replace('Estado:', '').strip()
        else:
            data['estado'] = 'Disponible'

        return data

    def _extract_location(self, soup):
        """Extrae información de ubicación"""
        data = {}

        # Buscar en list-info-1a con estructura específica
        list_info = soup.find('div', class_='list-info-1a')
        if list_info:
            for li in list_info.find_all('li'):
                text = li.text.strip()
                if 'País:' in text:
                    data['pais'] = text.replace('País:', '').strip()
                elif 'Provincia:' in text:
                    data['departamento'] = text.replace('Provincia:', '').strip()
                elif 'Ciudad:' in text:
                    data['ciudad'] = text.replace('Ciudad:', '').strip().rstrip('.')
                elif 'Zona:' in text:
                    data['zona'] = text.replace('Zona:', '').strip()
                elif 'Nivel:' in text:
                    nivel_text = text.replace('Nivel:', '').strip()
                    if nivel_text.isdigit():
                        data['piso'] = int(nivel_text)

        # Defaults si no se encontró
        if 'pais' not in data:
            data['pais'] = None
        if 'departamento' not in data:
            data['departamento'] = None
        if 'ciudad' not in data:
            data['ciudad'] = None
        if 'zona' not in data:
            # Fallback: intentar extraer zona del título si no se encontró en metadata
            # Muchas veces el título contiene "en [zona]"
            titulo = soup.find('h1', class_='title')
            if titulo:
                titulo_text = titulo.text.strip()
                # Buscar patrones como "en La Estrella", "en Laureles", etc.
                zona_match = re.search(r'\sen\s+([A-Z][a-záéíóúñ\s]+?)(?:\||$)', titulo_text)
                if zona_match:
                    data['zona'] = zona_match.group(1).strip()
                else:
                    data['zona'] = None
            else:
                data['zona'] = None

        # Coordenadas GPS (buscar en scripts o atributos data)
        # Wasi nunca publica la coordenada exacta de la propiedad: redondea
        # al centroide de barrio/ciudad. La marcamos como aproximada siempre.
        map_script = soup.find('script', string=re.compile(r'latitude|longitude|lat|lng'))
        lat_val = None
        lng_val = None
        if map_script:
            lat_match = re.search(
                r'(?:lat(?:itude)?)["\']?\s*[:=]\s*["\']?(-?\d+\.\d+)',
                map_script.string,
            )
            lng_match = re.search(
                r'(?:lng|lon(?:gitude)?)["\']?\s*[:=]\s*["\']?(-?\d+\.\d+)',
                map_script.string,
            )
            try:
                lat_val = float(lat_match.group(1)) if lat_match else None
                lng_val = float(lng_match.group(1)) if lng_match else None
            except (ValueError, IndexError):
                lat_val = None
                lng_val = None
        data['latitud'] = lat_val
        data['longitud'] = lng_val
        # Wasi siempre entrega ubicación de barrio/ciudad, no de la propiedad
        data['ubicacion_aproximada'] = True if (lat_val and lng_val) else None

        # Dirección completa
        address = soup.find('address') or soup.find(class_=re.compile(r'address|direccion'))
        data['direccion_completa'] = address.text.strip() if address else None

        return data

    def _extract_physical_features(self, soup):
        """Extrae características físicas de la propiedad"""
        data = {}

        # Buscar en list-info-1a con estructura específica
        list_info = soup.find('div', class_='list-info-1a')
        if list_info:
            for li in list_info.find_all('li'):
                text = li.text.strip()

                # Área construida
                if 'Área Construida:' in text or 'Área Privada:' in text:
                    area_match = re.search(r'(\d+(?:[.,]\d+)?)\s*m', text)
                    if area_match:
                        data['area_construida'] = float(area_match.group(1).replace(',', '.'))

                # Habitaciones
                elif 'Habitaciones:' in text:
                    hab_match = re.search(r'(\d+)', text)
                    if hab_match:
                        data['habitaciones'] = int(hab_match.group(1))

                # Baños
                elif 'Baños:' in text:
                    bano_match = re.search(r'(\d+)', text)
                    if bano_match:
                        data['banos'] = int(bano_match.group(1))

                # Garajes/Parqueaderos
                elif 'Garaje:' in text or 'Parqueadero:' in text:
                    garaje_match = re.search(r'(\d+)', text)
                    if garaje_match:
                        data['parqueaderos'] = int(garaje_match.group(1))

                # Estrato
                elif 'Estrato:' in text:
                    estrato_match = re.search(r'(\d+)', text)
                    if estrato_match:
                        data['estrato'] = int(estrato_match.group(1))

                # Año de construcción
                elif 'Año de construcción:' in text:
                    ano_match = re.search(r'(\d{4})', text)
                    if ano_match:
                        data['ano_construccion'] = int(ano_match.group(1))

        # Defaults si no se encontró
        if 'area_construida' not in data:
            data['area_construida'] = None
        if 'habitaciones' not in data:
            data['habitaciones'] = None
        if 'banos' not in data:
            data['banos'] = None
        if 'parqueaderos' not in data:
            data['parqueaderos'] = None
        if 'estrato' not in data:
            data['estrato'] = None
        if 'piso' not in data:
            data['piso'] = None
        if 'ano_construccion' not in data:
            data['ano_construccion'] = None

        # Extraer características adicionales
        feature_texts = []
        for li in soup.find_all('li'):
            text = li.text.strip()
            # Filtrar características relevantes
            if text and len(text) < 100 and len(text) > 3:
                # Evitar campos que ya extrajimos
                if not any(keyword in text for keyword in ['País:', 'Provincia:', 'Ciudad:', 'Zona:', 'Habitaciones:', 'Baños:', 'Garaje:']):
                    feature_texts.append(text)

        data['caracteristicas_adicionales'] = ' | '.join(list(set(feature_texts))[:20]) if feature_texts else None

        return data

    def _extract_costs(self, soup):
        """Extrae costos adicionales"""
        data = {}

        # Buscar en list-info-1a con estructura específica
        list_info = soup.find('div', class_='list-info-1a')
        if list_info:
            for li in list_info.find_all('li'):
                text = li.text.strip()

                # Administración
                if 'Administración:' in text:
                    admin_match = re.search(r'\$\s*([\d,.]+)', text)
                    if admin_match:
                        admin_value = admin_match.group(1).replace('.', '').replace(',', '')
                        data['administracion'] = int(admin_value) if admin_value.isdigit() else None

        # Buscar predial en la descripción adicional
        html_text = soup.get_text()
        predial_match = re.search(r'predial.*?\$\s*([\d,.]+)', html_text, re.IGNORECASE)
        if predial_match:
            predial_value = predial_match.group(1).replace('.', '').replace(',', '')
            data['predial'] = int(predial_value) if predial_value.isdigit() else None
        else:
            data['predial'] = None

        # Defaults si no se encontró
        if 'administracion' not in data:
            data['administracion'] = None

        return data

    def _extract_amenities(self, soup):
        """Extrae amenidades internas y externas"""
        data = {}

        # Buscar secciones de amenidades con clase list-info-2a
        amenity_sections = soup.find_all('div', class_='list-info-2a')

        internal_amenities = []
        external_amenities = []

        # Generalmente hay 2 secciones: internas y externas
        for idx, section in enumerate(amenity_sections):
            items = section.find_all('li')
            for item in items:
                text = item.text.strip()
                if text and len(text) < 50 and len(text) > 2:
                    # La primera sección suele ser interna, la segunda externa
                    if idx == 0:
                        # Clasificar basado en palabras clave
                        if any(word in text.lower() for word in ['ascensor', 'vigilancia', 'parque', 'zona social', 'gimnasio', 'piscina', 'portería', 'salón comunal', 'área social']):
                            external_amenities.append(text)
                        else:
                            internal_amenities.append(text)
                    else:
                        external_amenities.append(text)

        data['amenidades_internas'] = ' | '.join(sorted(set(internal_amenities))) if internal_amenities else None
        data['amenidades_externas'] = ' | '.join(sorted(set(external_amenities))) if external_amenities else None
        data['total_amenidades'] = len(set(internal_amenities + external_amenities))

        return data

    def _extract_contact(self, soup):
        """Extrae información de contacto"""
        data = {}

        # Asesor
        agent = soup.find(['span', 'div', 'p'], class_=re.compile(r'agent|asesor|realtor'))
        data['asesor'] = agent.text.strip() if agent else None

        # Teléfono
        phone = soup.find('a', href=re.compile(r'tel:')) or soup.find(string=re.compile(r'\+?\d{2,3}\s*\d{10}'))
        if phone:
            if hasattr(phone, 'get'):
                data['telefono'] = phone.get('href', '').replace('tel:', '')
            else:
                phone_match = re.search(r'(\+?\d{2,3}\s*\d{10})', str(phone))
                data['telefono'] = phone_match.group(1) if phone_match else None
        else:
            data['telefono'] = None

        # Inmobiliaria
        company = soup.find(['span', 'div'], class_=re.compile(r'company|inmobiliaria|agency'))
        data['inmobiliaria'] = company.text.strip() if company else None

        return data

    def _extract_images(self, soup):
        """Extrae URLs de imágenes en ALTA RESOLUCIÓN"""
        data = {}

        images_hd = []
        images_thumb = []

        # MÉTODO 1: Buscar en contenedor .fotorama (galería principal) - ALTA RESOLUCIÓN
        fotorama = soup.find('div', class_='fotorama')
        if fotorama:
            # Extraer URLs de alta resolución desde atributo 'href' de enlaces
            for link in fotorama.find_all('a', href=True):
                href = link.get('href')
                if href and 'image.wasi.co' in href:
                    images_hd.append(href)
                    self.log(f"Imagen HD encontrada: {href[:80]}...")

            # También extraer miniaturas si es necesario (desde img src)
            for img in fotorama.find_all('img', src=True):
                src = img.get('src')
                if src and 'image.wasi.co' in src:
                    images_thumb.append(src)

        # MÉTODO 2: Si no encuentra en fotorama, buscar en Gallery > layout
        if not images_hd:
            gallery = soup.find('div', class_='Gallery')
            if gallery:
                for link in gallery.find_all('a', href=True):
                    href = link.get('href')
                    if href and 'image.wasi.co' in href:
                        images_hd.append(href)

        # MÉTODO 3: Buscar todas las imágenes de Wasi como fallback
        if not images_hd:
            all_imgs = soup.find_all('img')
            for img in all_imgs:
                src = img.get('src') or img.get('data-src') or img.get('data-original')
                if src and 'image.wasi.co' in src:
                    # Intentar convertir miniatura a HD modificando parámetros
                    if 'width":156' in src or 'width":90' in src:
                        # Es miniatura, intentar obtener versión HD
                        # (esto es un aproximado, la URL HD real está en href)
                        images_thumb.append(src)
                    else:
                        images_hd.append(src)

        # Si no hay HD, usar miniaturas como último recurso
        final_images = images_hd if images_hd else images_thumb

        # Eliminar duplicados manteniendo el orden
        seen = set()
        unique_images = []
        for img in final_images:
            if img not in seen:
                seen.add(img)
                unique_images.append(img)

        data['imagenes_urls'] = ' | '.join(unique_images) if unique_images else None
        data['total_imagenes'] = len(unique_images)
        data['imagen_principal'] = unique_images[0] if unique_images else None

        # Campos adicionales para debugging
        data['imagenes_hd_count'] = len(images_hd)
        data['imagenes_thumb_count'] = len(images_thumb)

        return data

    def _extract_description(self, soup):
        """Extrae la descripción de la propiedad"""
        data = {}

        # Buscar descripción en diferentes elementos
        desc = (soup.find('div', class_=re.compile(r'description|descripcion')) or
                soup.find('p', class_=re.compile(r'description|descripcion')))

        if desc:
            # Limpiar texto
            desc_text = desc.get_text(separator=' ', strip=True)
            data['descripcion'] = desc_text
            data['descripcion_length'] = len(desc_text)
        else:
            data['descripcion'] = None
            data['descripcion_length'] = 0

        return data

    def scrape_from_file(self, file_path):
        """
        Lee URLs desde archivo y scrapea cada una

        Args:
            file_path (str): Ruta al archivo con URLs
        """
        print(f"\n🚀 Iniciando scraper de Wasi")
        if self.enable_ai_enrichment:
            print(f"🤖 AI Enrichment: ACTIVADO")
        print(f"📁 Leyendo URLs desde: {file_path}\n")

        # Leer URLs del archivo
        with open(file_path, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip() and line.strip().startswith('http')]

        print(f"✓ Se encontraron {len(urls)} URLs para procesar\n")

        # Procesar cada URL con barra de progreso
        for url in tqdm(urls, desc="Scrapeando propiedades", unit="propiedad"):
            data = self.extract_property_data(url)
            if data:
                self.properties_data.append(data)

            # Delay entre requests
            if url != urls[-1]:  # No esperar después del último
                time.sleep(self.delay)

        print(f"\n✓ Scraping completado!")
        print(f"  • Propiedades extraídas: {len(self.properties_data)}")
        print(f"  • Errores: {len(self.errors)}")

        # Enriquecer con AI si está habilitado
        if self.enable_ai_enrichment and self.enricher and self.properties_data:
            print(f"\n🤖 Iniciando enriquecimiento AI de {len(self.properties_data)} propiedades...")
            print(f"⏱️  Esto puede tomar varios minutos...\n")

            try:
                enriched_properties = self.enricher.enrich_batch(
                    self.properties_data,
                    delay=1.0  # Delay entre llamadas a Claude
                )
                self.properties_data = enriched_properties
                print(f"\n✅ Enriquecimiento AI completado!")
            except Exception as e:
                print(f"\n⚠️  Error en enriquecimiento AI: {e}")
                print(f"Las propiedades se guardarán sin enriquecimiento")

    def save_data(self, output_dir='data', save_to_db=True):
        """
        Guarda los datos en múltiples formatos y en base de datos

        Args:
            output_dir (str): Directorio de salida
            save_to_db (bool): Si True, guarda también en la base de datos
        """
        # Crear directorio si no existe
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        print(f"\n💾 Guardando datos...\n")

        if self.properties_data:
            # Convertir a DataFrame
            df = pd.DataFrame(self.properties_data)

            # Guardar CSV
            csv_path = os.path.join(output_dir, f'propiedades_wasi_{timestamp}.csv')
            df.to_csv(csv_path, index=False, encoding='utf-8-sig')
            print(f"✓ CSV guardado: {csv_path}")

            # Guardar JSON
            json_path = os.path.join(output_dir, f'propiedades_wasi_{timestamp}.json')
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(self.properties_data, f, ensure_ascii=False, indent=2)
            print(f"✓ JSON guardado: {json_path}")

            # Guardar Excel
            try:
                excel_path = os.path.join(output_dir, f'propiedades_wasi_{timestamp}.xlsx')
                df.to_excel(excel_path, index=False, engine='openpyxl')
                print(f"✓ Excel guardado: {excel_path}")
            except Exception as e:
                print(f"⚠ No se pudo guardar Excel: {e}")

            # Guardar en base de datos
            if save_to_db:
                print(f"\n🗄️  Guardando en base de datos Neon PostgreSQL...")
                try:
                    from database import save_properties_to_db
                    exitosas, fallidas = save_properties_to_db(self.properties_data)
                    print(f"✓ Base de datos actualizada:")
                    print(f"  • Propiedades guardadas: {exitosas}")
                    if fallidas > 0:
                        print(f"  • Propiedades fallidas: {fallidas}")
                except ImportError as e:
                    print(f"⚠️  Error al importar módulo de base de datos: {e}")
                    print(f"    Verifica que:")
                    print(f"    1. database.py esté en la misma carpeta")
                    print(f"    2. psycopg2-binary esté instalado: pip install psycopg2-binary")
                    print(f"    3. python-dotenv esté instalado: pip install python-dotenv")
                except Exception as e:
                    print(f"⚠️  Error al guardar en base de datos: {e}")
                    print(f"    Verifica que DATABASE_URL esté configurada en .env")
                    import traceback
                    print(f"\nDetalle del error:")
                    traceback.print_exc()

        # Guardar log de errores
        if self.errors:
            log_path = os.path.join(output_dir, f'scraper_errors_{timestamp}.log')
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(f"Log de errores - {datetime.now()}\n")
                f.write("=" * 50 + "\n\n")
                for error in self.errors:
                    f.write(f"URL: {error['url']}\n")
                    f.write(f"Error: {error['error']}\n")
                    f.write(f"Timestamp: {error['timestamp']}\n")
                    f.write("-" * 50 + "\n")
            print(f"✓ Log de errores guardado: {log_path}")

        print(f"\n✅ Todos los archivos guardados en: {output_dir}/")

    def get_summary(self):
        """Retorna un resumen de la extracción"""
        if not self.properties_data:
            return "No se extrajeron datos"

        df = pd.DataFrame(self.properties_data)

        summary = f"""
╔════════════════════════════════════════════════════════════╗
║           RESUMEN DE EXTRACCIÓN - WASI SCRAPER            ║
╚════════════════════════════════════════════════════════════╝

📊 Estadísticas Generales:
  • Total propiedades: {len(self.properties_data)}
  • Errores: {len(self.errors)}
  • Tasa de éxito: {len(self.properties_data)/(len(self.properties_data)+len(self.errors))*100:.1f}%

💰 Precios:
  • Precio promedio: ${df['precio'].mean():,.0f} COP
  • Precio mínimo: ${df['precio'].min():,.0f} COP
  • Precio máximo: ${df['precio'].max():,.0f} COP

🏠 Características:
  • Área promedio: {df['area_construida'].mean():.1f} m²
  • Habitaciones promedio: {df['habitaciones'].mean():.1f}
  • Baños promedio: {df['banos'].mean():.1f}

📸 Imágenes:
  • Total imágenes extraídas: {df['total_imagenes'].sum()}
  • Promedio por propiedad: {df['total_imagenes'].mean():.1f}

🏢 Tipos de Propiedad:
{df['tipo_propiedad'].value_counts().to_string() if 'tipo_propiedad' in df else '  No disponible'}
"""
        return summary


def main():
    """Función principal"""
    print("""
╔════════════════════════════════════════════════════════════╗
║                   WASI PROPERTY SCRAPER                    ║
║                    Proyecto Cupido Tu360                   ║
╚════════════════════════════════════════════════════════════╝
    """)

    # Configuración
    INPUT_FILE = 'links_wasi.txt'
    OUTPUT_DIR = 'data'
    DELAY = 2  # segundos entre requests
    VERBOSE = True  # Modo detallado

    # Crear scraper
    scraper = WasiScraper(delay=DELAY, verbose=VERBOSE)

    # Ejecutar scraping
    scraper.scrape_from_file(INPUT_FILE)

    # Guardar datos
    scraper.save_data(OUTPUT_DIR)

    # Mostrar resumen
    print(scraper.get_summary())

    print("\n🎉 ¡Proceso completado exitosamente!")


if __name__ == "__main__":
    main()
