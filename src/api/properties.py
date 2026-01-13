#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API REST para propiedades - Proyecto Cupido
Expone endpoints para que el frontend consuma la base de datos de Neon
"""

from flask import Blueprint, jsonify, request
from src.db.database import DatabaseManager
import traceback
from typing import Dict, List, Optional

# Crear blueprint para la API
api_bp = Blueprint('api', __name__, url_prefix='/api')


def get_db():
    """Helper para obtener conexión a la base de datos"""
    db = DatabaseManager()
    db.connect()
    return db


@api_bp.route('/properties', methods=['GET'])
def get_properties():
    """
    GET /api/properties

    Obtiene lista de propiedades con filtros opcionales

    Query params:
    - published: boolean (default: true)
    - limit: int (default: 500)
    - offset: int (default: 0)
    - city: string
    - type: string
    - min_price: number
    - max_price: number
    - bedrooms: number
    """
    db = None
    try:
        db = get_db()

        # Parámetros de query
        published = request.args.get('published', 'true').lower() == 'true'
        limit = int(request.args.get('limit', 500))
        offset = int(request.args.get('offset', 0))
        city = request.args.get('city')
        prop_type = request.args.get('type')
        min_price = request.args.get('min_price')
        max_price = request.args.get('max_price')
        bedrooms = request.args.get('bedrooms')

        # Construir query SQL
        query = """
            SELECT
                p.id,
                p.codigo_propiedad as slug,
                p.titulo as title,
                p.tipo_propiedad as type,
                p.precio as price_cop,
                p.ciudad as city,
                p.zona as barrio,
                p.zona as zone,
                p.area_construida as area_m2,
                p.habitaciones as bedrooms,
                p.banos as bathrooms,
                p.parqueaderos as parking,
                p.estrato as stratum,
                p.ano_construccion as age_years,
                p.administracion as admin_fee_cop,
                p.descripcion as description,
                p.direccion_completa as address,
                p.latitud as lat,
                p.longitud as lng,
                p.estado as condition,
                p.caracteristicas_adicionales as features,
                p.activa as published,
                CASE WHEN p.fuente = 'Pulppo' THEN true ELSE false END as exclusive,
                false as featured,
                p.fuente as source,
                p.fecha_creacion as created_at,
                p.fecha_actualizacion as updated_at,
                p.agente_captador_telefono as owner_phone,
                p.grupo_origen as source_group,
                a.nombre as owner_name
            FROM propiedades p
            LEFT JOIN agentes a ON a.telefono = p.agente_captador_telefono
            WHERE p.activa = TRUE
        """
        params = []

        # Solo filtrar por published si es necesario
        if not published:
            query = query.replace("WHERE p.activa = TRUE", "WHERE p.activa = FALSE")

        # Agregar filtros
        if city:
            query += " AND LOWER(p.ciudad) = LOWER(%s)"
            params.append(city)

        if prop_type:
            query += " AND LOWER(p.tipo_propiedad) = LOWER(%s)"
            params.append(prop_type)

        if min_price:
            query += " AND p.precio >= %s"
            params.append(int(min_price))

        if max_price:
            query += " AND p.precio <= %s"
            params.append(int(max_price))

        if bedrooms:
            query += " AND p.habitaciones = %s"
            params.append(int(bedrooms))

        # Ordenar y paginar
        query += " ORDER BY p.fecha_creacion DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        # Ejecutar query
        db.cursor.execute(query, tuple(params))
        properties = db.cursor.fetchall()

        # Convertir a formato JSON compatible
        properties_list = []
        for prop in properties:
            # prop ya es un diccionario (RealDictCursor)
            prop_dict = {
                'id': prop.get('id'),
                'slug': prop.get('slug'),
                'title': prop.get('title'),
                'type': prop.get('type'),
                'price_cop': prop.get('price_cop'),
                'city': prop.get('city'),
                'barrio': prop.get('barrio'),
                'zone': prop.get('zone'),
                'area_m2': prop.get('area_m2'),
                'bedrooms': prop.get('bedrooms'),
                'bathrooms': prop.get('bathrooms'),
                'parking': prop.get('parking'),
                'stratum': prop.get('stratum'),
                'age_years': prop.get('age_years'),
                'admin_fee_cop': prop.get('admin_fee_cop'),
                'description': prop.get('description'),
                'address': prop.get('address'),
                'lat': prop.get('lat'),
                'lng': prop.get('lng'),
                'condition': prop.get('condition'),
                'features': prop.get('features'),
                'published': prop.get('published'),
                'exclusive': prop.get('exclusive'),
                'featured': prop.get('featured'),
                'source': prop.get('source'),
                'created_at': str(prop.get('created_at')) if prop.get('created_at') else None,
                'updated_at': str(prop.get('updated_at')) if prop.get('updated_at') else None,
                'owner_phone': prop.get('owner_phone'),
                'owner_name': prop.get('owner_name'),
                'source_group': prop.get('source_group'),
            }

            # Convertir features de texto a JSON
            if prop_dict.get('features'):
                try:
                    # Si ya es una lista, la dejamos como está
                    if isinstance(prop_dict['features'], str):
                        # Dividir por comas o punto y coma
                        features_text = prop_dict['features']
                        prop_dict['features'] = [f.strip() for f in features_text.replace(';', ',').split(',') if f.strip()]
                except:
                    prop_dict['features'] = []
            else:
                prop_dict['features'] = []

            # Asegurar tipos correctos
            if prop_dict.get('lat'):
                prop_dict['lat'] = float(prop_dict['lat'])
            if prop_dict.get('lng'):
                prop_dict['lng'] = float(prop_dict['lng'])
            if prop_dict.get('area_m2'):
                prop_dict['area_m2'] = float(prop_dict['area_m2'])

            properties_list.append(prop_dict)

        return jsonify({
            'success': True,
            'data': properties_list,
            'count': len(properties_list)
        }), 200

    except Exception as e:
        print(f"❌ Error en get_properties: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@api_bp.route('/properties/<slug>', methods=['GET'])
def get_property_by_slug(slug: str):
    """
    GET /api/properties/:slug

    Obtiene una propiedad específica por su slug (código) o ID
    Acepta tanto el codigo_propiedad como el ID numérico
    """
    db = None
    try:
        db = get_db()

        # Intentar buscar por codigo_propiedad primero, luego por ID
        # Esto permite usar tanto "WASI-12345" como "26"
        query = """
            SELECT
                p.id,
                p.codigo_propiedad as slug,
                p.titulo as title,
                p.tipo_propiedad as type,
                p.precio as price_cop,
                p.ciudad as city,
                p.zona as barrio,
                p.zona as zone,
                p.area_construida as area_m2,
                p.habitaciones as bedrooms,
                p.banos as bathrooms,
                p.parqueaderos as parking,
                p.estrato as stratum,
                p.ano_construccion as age_years,
                p.administracion as admin_fee_cop,
                p.descripcion as description,
                p.direccion_completa as address,
                p.latitud as lat,
                p.longitud as lng,
                p.estado as condition,
                p.caracteristicas_adicionales as features,
                p.activa as published,
                CASE WHEN p.fuente = 'Pulppo' THEN true ELSE false END as exclusive,
                false as featured,
                p.fuente as source,
                p.url as source_url,
                p.fecha_creacion as created_at,
                p.fecha_actualizacion as updated_at,
                p.agente_captador_telefono as owner_phone,
                p.grupo_origen as source_group,
                a.nombre as owner_name
            FROM propiedades p
            LEFT JOIN agentes a ON a.telefono = p.agente_captador_telefono
            WHERE (p.codigo_propiedad = %s OR p.id::text = %s) AND p.activa = true
        """

        db.cursor.execute(query, (slug, slug))
        result = db.cursor.fetchall()

        if not result or len(result) == 0:
            return jsonify({
                'success': False,
                'error': 'Property not found'
            }), 404

        prop = result[0]
        # prop ya es un diccionario (RealDictCursor)
        prop_dict = {
            'id': prop.get('id'),
            'slug': prop.get('slug'),
            'title': prop.get('title'),
            'type': prop.get('type'),
            'price_cop': prop.get('price_cop'),
            'city': prop.get('city'),
            'barrio': prop.get('barrio'),
            'zone': prop.get('zone'),
            'area_m2': prop.get('area_m2'),
            'bedrooms': prop.get('bedrooms'),
            'bathrooms': prop.get('bathrooms'),
            'parking': prop.get('parking'),
            'stratum': prop.get('stratum'),
            'age_years': prop.get('age_years'),
            'admin_fee_cop': prop.get('admin_fee_cop'),
            'description': prop.get('description'),
            'address': prop.get('address'),
            'lat': prop.get('lat'),
            'lng': prop.get('lng'),
            'condition': prop.get('condition'),
            'features': prop.get('features'),
            'published': prop.get('published'),
            'exclusive': prop.get('exclusive'),
            'featured': prop.get('featured'),
            'source': prop.get('source'),
            'source_url': prop.get('source_url'),
            'created_at': str(prop.get('created_at')) if prop.get('created_at') else None,
            'updated_at': str(prop.get('updated_at')) if prop.get('updated_at') else None,
            'owner_phone': prop.get('owner_phone'),
            'owner_name': prop.get('owner_name'),
            'source_group': prop.get('source_group'),
        }

        # Convertir features
        if prop_dict.get('features'):
            try:
                if isinstance(prop_dict['features'], str):
                    features_text = prop_dict['features']
                    prop_dict['features'] = [f.strip() for f in features_text.replace(';', ',').split(',') if f.strip()]
            except:
                prop_dict['features'] = []
        else:
            prop_dict['features'] = []

        # Asegurar tipos correctos
        if prop_dict.get('lat'):
            prop_dict['lat'] = float(prop_dict['lat'])
        if prop_dict.get('lng'):
            prop_dict['lng'] = float(prop_dict['lng'])
        if prop_dict.get('area_m2'):
            prop_dict['area_m2'] = float(prop_dict['area_m2'])

        return jsonify({
            'success': True,
            'data': prop_dict
        }), 200

    except Exception as e:
        print(f"❌ Error en get_property_by_slug: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@api_bp.route('/property-images', methods=['GET'])
def get_property_images():
    """
    GET /api/property-images

    Obtiene imágenes de propiedades

    Query params:
    - property_id: int (opcional, filtra por propiedad)
    - is_cover: boolean (opcional, solo imágenes de portada)
    """
    db = None
    try:
        db = get_db()

        property_id = request.args.get('property_id')
        is_cover = request.args.get('is_cover')

        # Obtener URLs de imágenes desde la tabla propiedades
        query = """
            SELECT
                id as property_id,
                imagen_principal as url,
                1 as position,
                true as is_cover,
                codigo_propiedad
            FROM propiedades
            WHERE activa = true AND imagen_principal IS NOT NULL
        """
        params = []

        if property_id:
            query += " AND id = %s"
            params.append(int(property_id))

        if is_cover and is_cover.lower() == 'true':
            # Ya está filtrado por imagen principal
            pass

        if params:
            db.cursor.execute(query, tuple(params))
        else:
            db.cursor.execute(query)
        results = db.cursor.fetchall()

        images = []
        for row in results:
            # row es un diccionario (RealDictCursor)
            img_dict = {
                'id': f"{row.get('property_id')}-1",  # ID único combinando property_id y position
                'property_id': row.get('property_id'),
                'url': row.get('url'),
                'position': row.get('position'),
                'is_cover': row.get('is_cover'),
                'created_at': None
            }
            images.append(img_dict)

            # Si la propiedad tiene múltiples imágenes en imagenes_urls
            # Podemos expandir aquí si es necesario

        return jsonify({
            'success': True,
            'data': images,
            'count': len(images)
        }), 200

    except Exception as e:
        print(f"❌ Error en get_property_images: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@api_bp.route('/property-images/<int:property_id>', methods=['GET'])
def get_property_images_by_id(property_id: int):
    """
    GET /api/property-images/:property_id

    Obtiene todas las imágenes de una propiedad específica
    """
    db = None
    try:
        db = get_db()

        query = """
            SELECT
                id,
                imagen_principal,
                imagenes_urls
            FROM propiedades
            WHERE id = %s AND activa = true
        """

        db.cursor.execute(query, (property_id,))
        result = db.cursor.fetchall()

        if not result or len(result) == 0:
            return jsonify({
                'success': False,
                'error': 'Property not found'
            }), 404

        # result[0] es un diccionario (RealDictCursor)
        row = result[0]
        prop_id = row.get('id')
        imagen_principal = row.get('imagen_principal')
        imagenes_urls = row.get('imagenes_urls')

        images = []

        # Agregar imagen principal como primera imagen
        if imagen_principal:
            images.append({
                'id': f"{prop_id}-1",
                'property_id': prop_id,
                'url': imagen_principal,
                'position': 1,
                'is_cover': True,
                'created_at': None
            })

        # Agregar resto de imágenes si existen
        if imagenes_urls:
            urls = imagenes_urls.split('|')
            for idx, url in enumerate(urls, start=2):
                if url.strip() and url != imagen_principal:
                    images.append({
                        'id': f"{prop_id}-{idx}",
                        'property_id': prop_id,
                        'url': url.strip(),
                        'position': idx,
                        'is_cover': False,
                        'created_at': None
                    })

        return jsonify({
            'success': True,
            'data': images,
            'count': len(images)
        }), 200

    except Exception as e:
        print(f"❌ Error en get_property_images_by_id: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@api_bp.route('/filter-options', methods=['GET'])
def get_filter_options():
    """
    GET /api/filter-options

    Obtiene las opciones disponibles para los filtros con sus contadores
    """
    db = None
    try:
        db = get_db()

        filter_options = {}

        # 1. CIUDADES
        db.cursor.execute("""
            SELECT ciudad, COUNT(*) as count
            FROM propiedades
            WHERE activa = true AND ciudad IS NOT NULL
            GROUP BY ciudad
            ORDER BY count DESC
        """)
        filter_options['cities'] = [
            {'value': row['ciudad'], 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        # 2. ZONAS/BARRIOS (top 10)
        db.cursor.execute("""
            SELECT zona, COUNT(*) as count
            FROM propiedades
            WHERE activa = true AND zona IS NOT NULL AND zona != ''
            GROUP BY zona
            ORDER BY count DESC
            LIMIT 10
        """)
        filter_options['zones'] = [
            {'value': row['zona'], 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        # 3. TIPOS DE PROPIEDAD
        db.cursor.execute("""
            SELECT tipo_propiedad, COUNT(*) as count
            FROM propiedades
            WHERE activa = true AND tipo_propiedad IS NOT NULL
            GROUP BY tipo_propiedad
            ORDER BY count DESC
        """)
        filter_options['property_types'] = [
            {'value': row['tipo_propiedad'], 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        # 4. RANGO DE HABITACIONES
        db.cursor.execute("""
            SELECT habitaciones, COUNT(*) as count
            FROM propiedades
            WHERE activa = true AND habitaciones IS NOT NULL
            GROUP BY habitaciones
            ORDER BY habitaciones
        """)
        filter_options['bedrooms'] = [
            {'value': row['habitaciones'], 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        # 5. FUENTES
        db.cursor.execute("""
            SELECT fuente, COUNT(*) as count
            FROM propiedades
            WHERE activa = true AND fuente IS NOT NULL
            GROUP BY fuente
            ORDER BY count DESC
        """)
        filter_options['sources'] = [
            {'value': row['fuente'], 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        # 6. RANGOS DE PRECIOS (estadísticas)
        db.cursor.execute("""
            SELECT
                MIN(precio) as min_price,
                MAX(precio) as max_price,
                AVG(precio) as avg_price,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY precio) as q1,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY precio) as median,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY precio) as q3
            FROM propiedades
            WHERE activa = true AND precio IS NOT NULL
        """)
        price_stats = db.cursor.fetchone()
        filter_options['price_stats'] = {
            'min': price_stats['min_price'],
            'max': price_stats['max_price'],
            'avg': price_stats['avg_price'],
            'q1': price_stats['q1'],
            'median': price_stats['median'],
            'q3': price_stats['q3']
        }

        # 7. RANGOS DE ÁREA (estadísticas)
        db.cursor.execute("""
            SELECT
                MIN(area_construida) as min_area,
                MAX(area_construida) as max_area,
                AVG(area_construida) as avg_area
            FROM propiedades
            WHERE activa = true AND area_construida IS NOT NULL
        """)
        area_stats = db.cursor.fetchone()
        filter_options['area_stats'] = {
            'min': area_stats['min_area'],
            'max': area_stats['max_area'],
            'avg': area_stats['avg_area']
        }

        # 8. TOTAL DE PROPIEDADES
        db.cursor.execute("SELECT COUNT(*) as count FROM propiedades WHERE activa = true")
        total = db.cursor.fetchone()
        filter_options['total_properties'] = total['count']

        return jsonify({
            'success': True,
            'data': filter_options
        }), 200

    except Exception as e:
        print(f"❌ Error en get_filter_options: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@api_bp.route('/health', methods=['GET'])
def health_check():
    """
    GET /api/health

    Verificar estado de la API y conexión a base de datos
    """
    db = None
    try:
        db = get_db()

        # Verificar conexión con query simple
        db.cursor.execute("SELECT COUNT(*) FROM propiedades")
        result = db.cursor.fetchone()
        count = result['count'] if result else 0

        return jsonify({
            'success': True,
            'status': 'healthy',
            'database': 'connected',
            'properties_count': count
        }), 200

    except Exception as e:
        print(f"❌ Error en health_check: {str(e)}")
        return jsonify({
            'success': False,
            'status': 'unhealthy',
            'database': 'disconnected',
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@api_bp.route('/scrape-wasi', methods=['POST'])
def scrape_wasi():
    """
    POST /api/scrape-wasi

    Scrapea una propiedad de Wasi y la guarda en la base de datos

    Body:
    {
        "url": "https://info.wasi.co/..."
    }

    Returns:
    {
        "success": true,
        "data": {
            "id": 123,
            "slug": "9560011",
            "title": "...",
            ...
        }
    }
    """
    db = None
    try:
        # Obtener URL del body
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({
                'success': False,
                'error': 'URL is required'
            }), 400

        url = data['url']

        # Validar que sea una URL de Wasi
        if 'wasi.co' not in url:
            return jsonify({
                'success': False,
                'error': 'La URL debe ser de Wasi.co'
            }), 400

        print(f"[API] Scrapeando URL: {url}")

        # Importar scraper
        from src.scrapers.wasi import WasiScraper

        # Crear scraper (sin AI enrichment para ser más rápido)
        scraper = WasiScraper(
            delay=1,
            verbose=True,
            enable_ai_enrichment=False
        )

        # Extraer datos de la propiedad
        property_data = scraper.extract_property_data(url)

        if not property_data:
            return jsonify({
                'success': False,
                'error': 'No se pudo extraer información de la URL'
            }), 400

        print(f"[API] Datos extraídos: {property_data.get('titulo', 'Sin título')}")

        # Verificar si es propiedad propia
        if data.get('es_propia', False):
            property_data['fuente'] = 'Propia'
            print(f"[API] Marcada como propiedad propia")

        # Guardar en base de datos
        db = get_db()
        property_id = db.insert_property(property_data)

        if not property_id:
            return jsonify({
                'success': False,
                'error': 'Error al guardar la propiedad en la base de datos'
            }), 500

        print(f"[API] Propiedad guardada con ID: {property_id}")

        # Procesar vectores automáticamente (en background)
        try:
            from src.core.property_processor import process_new_property
            process_new_property(property_id, property_data)
        except Exception as ve:
            print(f"[API] ⚠️  Procesamiento vectorial no disponible: {ve}")

        # Obtener la propiedad completa guardada
        db.cursor.execute("""
            SELECT
                id,
                codigo_propiedad as slug,
                titulo as title,
                tipo_propiedad as type,
                precio as price_cop,
                ciudad as city,
                zona as barrio,
                area_construida as area_m2,
                habitaciones as bedrooms,
                banos as bathrooms,
                parqueaderos as parking,
                estrato as stratum,
                descripcion as description,
                imagen_principal as cover_image,
                imagenes_urls,
                activa as published
            FROM propiedades
            WHERE id = %s
        """, (property_id,))

        saved_property = db.cursor.fetchone()

        if not saved_property:
            return jsonify({
                'success': False,
                'error': 'Propiedad guardada pero no se pudo recuperar'
            }), 500

        # Convertir a dict y procesar imágenes
        result = dict(saved_property)

        # Procesar imágenes
        images = []
        if result.get('cover_image'):
            images.append(result['cover_image'])

        if result.get('imagenes_urls'):
            # Split por | y agregar a la lista
            extra_images = result['imagenes_urls'].split('|')
            for img in extra_images:
                img = img.strip()
                if img and img not in images:
                    images.append(img)

        result['images'] = images
        del result['imagenes_urls']

        return jsonify({
            'success': True,
            'data': result,
            'message': 'Propiedad capturada y guardada exitosamente'
        }), 200

    except Exception as e:
        print(f"[API] Error en scrape_wasi: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@api_bp.route('/scrape-tu360', methods=['POST'])
def scrape_tu360():
    """
    POST /api/scrape-tu360

    Scrapea una propiedad de Tu360Inmobiliario y la guarda en la base de datos

    Body:
    {
        "url": "https://asesor.tu360inmobiliario-pulppo.com/property/..."
    }

    Returns:
    {
        "success": true,
        "data": {
            "id": 123,
            "slug": "...",
            "title": "...",
            ...
        }
    }
    """
    db = None
    try:
        # Obtener URL del body
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({
                'success': False,
                'error': 'URL is required'
            }), 400

        url = data['url']

        # Validar que sea una URL de Tu360
        if 'tu360inmobiliario-pulppo.com' not in url:
            return jsonify({
                'success': False,
                'error': 'La URL debe ser de tu360inmobiliario-pulppo.com'
            }), 400

        print(f"[API] Scrapeando URL Tu360: {url}")

        # Importar scraper
        from src.scrapers.tu360 import Tu360Scraper

        # Crear scraper
        scraper = Tu360Scraper(verbose=True)

        # Extraer datos de la propiedad
        property_data = scraper.extract_property_data(url)

        if not property_data:
            return jsonify({
                'success': False,
                'error': 'No se pudo extraer información de la URL'
            }), 400

        print(f"[API] Datos extraídos: {property_data.get('titulo', 'Sin título')}")

        # Guardar en base de datos
        db = get_db()
        property_id = db.insert_property(property_data)

        if not property_id:
            return jsonify({
                'success': False,
                'error': 'Error al guardar la propiedad en la base de datos'
            }), 500

        print(f"[API] Propiedad guardada con ID: {property_id}")

        # Procesar vectores automáticamente (en background)
        try:
            from src.core.property_processor import process_new_property
            process_new_property(property_id, property_data)
        except Exception as ve:
            print(f"[API] ⚠️  Procesamiento vectorial no disponible: {ve}")

        # Obtener la propiedad completa guardada
        db.cursor.execute("""
            SELECT
                id,
                codigo_propiedad as slug,
                titulo as title,
                tipo_propiedad as type,
                precio as price_cop,
                ciudad as city,
                zona as barrio,
                area_construida as area_m2,
                habitaciones as bedrooms,
                banos as bathrooms,
                parqueaderos as parking,
                estrato as stratum,
                descripcion as description,
                imagen_principal as cover_image,
                imagenes_urls,
                activa as published
            FROM propiedades
            WHERE id = %s
        """, (property_id,))

        saved_property = db.cursor.fetchone()

        if not saved_property:
            return jsonify({
                'success': False,
                'error': 'Propiedad guardada pero no se pudo recuperar'
            }), 500

        # Convertir a dict y procesar imágenes
        result = dict(saved_property)

        # Procesar imágenes
        images = []
        if result.get('cover_image'):
            images.append(result['cover_image'])

        if result.get('imagenes_urls'):
            # Split por | y agregar a la lista
            extra_images = result['imagenes_urls'].split('|')
            for img in extra_images:
                img = img.strip()
                if img and img not in images:
                    images.append(img)

        result['images'] = images
        del result['imagenes_urls']

        return jsonify({
            'success': True,
            'data': result,
            'message': 'Propiedad capturada y guardada exitosamente'
        }), 200

    except Exception as e:
        print(f"[API] Error en scrape_tu360: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@api_bp.route('/scrape-lobbie', methods=['POST'])
def scrape_lobbie():
    """
    POST /api/scrape-lobbie

    Scrapea una propiedad de Lobbie App y la guarda en la base de datos

    Body:
    {
        "url": "https://app.lobbieapp.com/sp/..."
    }

    Returns:
    {
        "success": true,
        "data": {
            "id": 123,
            "slug": "...",
            "title": "...",
            ...
        }
    }
    """
    db = None
    try:
        # Obtener URL del body
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({
                'success': False,
                'error': 'URL is required'
            }), 400

        url = data['url']

        # Validar que sea una URL de Lobbie
        if 'lobbieapp.com' not in url:
            return jsonify({
                'success': False,
                'error': 'La URL debe ser de lobbieapp.com'
            }), 400

        print(f"[API] Scrapeando URL Lobbie: {url}")

        # Importar scraper
        from src.scrapers.lobbie import LobbieScraper

        # Crear scraper
        scraper = LobbieScraper(verbose=True)

        # Extraer datos de la propiedad
        property_data = scraper.extract_property_data(url)

        if not property_data:
            return jsonify({
                'success': False,
                'error': 'No se pudo extraer información de la URL'
            }), 400

        print(f"[API] Datos extraídos: {property_data.get('titulo', 'Sin título')}")

        # Guardar en base de datos
        db = get_db()
        property_id = db.insert_property(property_data)

        if not property_id:
            return jsonify({
                'success': False,
                'error': 'Error al guardar la propiedad en la base de datos'
            }), 500

        print(f"[API] Propiedad guardada con ID: {property_id}")

        # Procesar vectores automáticamente (en background)
        try:
            from src.core.property_processor import process_new_property
            process_new_property(property_id, property_data)
        except Exception as ve:
            print(f"[API] ⚠️  Procesamiento vectorial no disponible: {ve}")

        # Obtener la propiedad completa guardada
        db.cursor.execute("""
            SELECT
                id,
                codigo_propiedad as slug,
                titulo as title,
                tipo_propiedad as type,
                precio as price_cop,
                ciudad as city,
                zona as barrio,
                area_construida as area_m2,
                habitaciones as bedrooms,
                banos as bathrooms,
                parqueaderos as parking,
                estrato as stratum,
                descripcion as description,
                imagen_principal as cover_image,
                imagenes_urls,
                activa as published
            FROM propiedades
            WHERE id = %s
        """, (property_id,))

        saved_property = db.cursor.fetchone()

        if not saved_property:
            return jsonify({
                'success': False,
                'error': 'Propiedad guardada pero no se pudo recuperar'
            }), 500

        # Convertir a dict y procesar imágenes
        result = dict(saved_property)

        # Procesar imágenes
        images = []
        if result.get('cover_image'):
            images.append(result['cover_image'])

        if result.get('imagenes_urls'):
            # Split por | y agregar a la lista
            extra_images = result['imagenes_urls'].split('|')
            for img in extra_images:
                img = img.strip()
                if img and img not in images:
                    images.append(img)

        result['images'] = images
        del result['imagenes_urls']

        return jsonify({
            'success': True,
            'data': result,
            'message': 'Propiedad capturada y guardada exitosamente desde Lobbie'
        }), 200

    except Exception as e:
        print(f"[API] Error en scrape_lobbie: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@api_bp.route('/properties/<slug>/similar', methods=['GET'])
def get_similar_properties(slug: str):
    """
    GET /api/properties/:slug/similar

    Obtiene propiedades similares a la propiedad especificada
    Criterios de similitud:
    - Misma ciudad
    - Rango de precio similar (+/- 30%)
    - Mismo tipo de propiedad
    - Numero similar de habitaciones (+/- 1)

    Query params:
    - limit: int (default: 6)
    """
    db = None
    try:
        db = get_db()
        limit = int(request.args.get('limit', 6))

        # Primero obtener la propiedad de referencia (buscar por codigo_propiedad o por ID)
        db.cursor.execute("""
            SELECT id, ciudad, precio, tipo_propiedad, habitaciones, zona
            FROM propiedades
            WHERE (codigo_propiedad = %s OR id::text = %s) AND activa = true
        """, (slug, slug))

        ref_prop = db.cursor.fetchone()

        if not ref_prop:
            return jsonify({
                'success': False,
                'error': 'Property not found'
            }), 404

        ref_id = ref_prop['id']
        ref_city = ref_prop['ciudad']
        ref_price = ref_prop['precio'] or 0
        ref_type = ref_prop['tipo_propiedad']
        ref_bedrooms = ref_prop['habitaciones'] or 0
        ref_zone = ref_prop['zona']

        # Calcular rango de precio (+/- 30%)
        price_min = ref_price * 0.7
        price_max = ref_price * 1.3

        # Buscar propiedades similares
        query = """
            SELECT
                p.id,
                p.codigo_propiedad as slug,
                p.titulo as title,
                p.tipo_propiedad as type,
                p.precio as price_cop,
                p.ciudad as city,
                p.zona as barrio,
                p.area_construida as area_m2,
                p.habitaciones as bedrooms,
                p.banos as bathrooms,
                p.parqueaderos as parking,
                p.imagen_principal as cover_image,
                p.fuente as source
            FROM propiedades p
            WHERE p.activa = true
            AND p.id != %s
            AND (
                -- Priorizar misma ciudad y tipo
                (p.ciudad = %s AND p.tipo_propiedad = %s)
                OR
                -- O misma zona
                (p.zona = %s AND p.zona IS NOT NULL AND p.zona != '')
                OR
                -- O precio similar en misma ciudad
                (p.ciudad = %s AND p.precio BETWEEN %s AND %s)
            )
            ORDER BY
                -- Ordenar por relevancia
                CASE
                    WHEN p.ciudad = %s AND p.tipo_propiedad = %s AND p.precio BETWEEN %s AND %s THEN 1
                    WHEN p.zona = %s THEN 2
                    WHEN p.ciudad = %s AND p.tipo_propiedad = %s THEN 3
                    WHEN p.ciudad = %s AND p.precio BETWEEN %s AND %s THEN 4
                    ELSE 5
                END,
                ABS(p.precio - %s) ASC
            LIMIT %s
        """

        params = [
            ref_id,
            ref_city, ref_type,  # Misma ciudad y tipo
            ref_zone,  # Misma zona
            ref_city, price_min, price_max,  # Precio similar
            # ORDER BY params
            ref_city, ref_type, price_min, price_max,  # Caso 1
            ref_zone,  # Caso 2
            ref_city, ref_type,  # Caso 3
            ref_city, price_min, price_max,  # Caso 4
            ref_price,  # ABS
            limit
        ]

        db.cursor.execute(query, tuple(params))
        similar_props = db.cursor.fetchall()

        properties_list = []
        for prop in similar_props:
            prop_dict = {
                'id': prop.get('id'),
                'slug': prop.get('slug'),
                'title': prop.get('title'),
                'type': prop.get('type'),
                'price_cop': prop.get('price_cop'),
                'city': prop.get('city'),
                'barrio': prop.get('barrio'),
                'area_m2': float(prop.get('area_m2')) if prop.get('area_m2') else None,
                'bedrooms': prop.get('bedrooms'),
                'bathrooms': prop.get('bathrooms'),
                'parking': prop.get('parking'),
                'cover_image': prop.get('cover_image'),
                'source': prop.get('source'),
            }
            properties_list.append(prop_dict)

        return jsonify({
            'success': True,
            'data': properties_list,
            'count': len(properties_list)
        }), 200

    except Exception as e:
        print(f"Error en get_similar_properties: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@api_bp.route('/improve-description', methods=['POST'])
def improve_description():
    """
    POST /api/improve-description

    Usa Claude AI para mejorar la descripción de una propiedad
    haciéndola más clara, organizada y profesional.

    Body:
    {
        "description": "texto de descripción original...",
        "property_info": {  // opcional, para contexto
            "title": "...",
            "type": "Apartamento",
            "city": "Medellín",
            "bedrooms": 3,
            "bathrooms": 2,
            "area_m2": 81.73,
            "price_cop": 650000000
        }
    }

    Returns:
    {
        "success": true,
        "data": {
            "improved_description": "texto mejorado...",
            "highlights": ["highlight1", "highlight2", ...]
        }
    }
    """
    try:
        import anthropic
        import os

        data = request.get_json()
        if not data or 'description' not in data:
            return jsonify({
                'success': False,
                'error': 'description is required'
            }), 400

        original_description = data['description']
        property_info = data.get('property_info', {})

        # Si la descripción es muy corta, no vale la pena procesarla
        if len(original_description) < 50:
            return jsonify({
                'success': True,
                'data': {
                    'improved_description': original_description,
                    'highlights': []
                }
            }), 200

        # Construir contexto de la propiedad
        context_parts = []
        if property_info.get('type'):
            context_parts.append(f"Tipo: {property_info['type']}")
        if property_info.get('city'):
            context_parts.append(f"Ciudad: {property_info['city']}")
        if property_info.get('bedrooms'):
            context_parts.append(f"Habitaciones: {property_info['bedrooms']}")
        if property_info.get('bathrooms'):
            context_parts.append(f"Baños: {property_info['bathrooms']}")
        if property_info.get('area_m2'):
            context_parts.append(f"Área: {property_info['area_m2']} m²")

        context = ", ".join(context_parts) if context_parts else "Sin contexto adicional"

        # Crear cliente de Anthropic
        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

        prompt = f"""Eres un experto en marketing inmobiliario. Tu tarea es tomar una descripción de propiedad que viene de un portal inmobiliario (usualmente desordenada, con información repetida y mal estructurada) y convertirla en una descripción profesional, clara y atractiva.

INFORMACIÓN DE LA PROPIEDAD:
{context}

DESCRIPCIÓN ORIGINAL:
{original_description}

INSTRUCCIONES:
1. Elimina información redundante o repetida
2. NO incluyas información que ya está en otros campos (precio, área, habitaciones, baños, etc.) - eso ya se muestra por separado
3. Organiza la información de forma lógica y fluida
4. Usa un tono profesional pero cálido
5. Destaca los puntos más atractivos de la propiedad
6. Mantén la descripción concisa (máximo 3-4 párrafos)
7. NO inventes información que no esté en la descripción original
8. Si hay amenidades del conjunto/edificio, menciónalas de forma organizada
9. Escribe en español

Responde SOLO con un JSON válido en este formato exacto (sin markdown, sin ```):
{{"improved_description": "La descripción mejorada aquí...", "highlights": ["punto destacado 1", "punto destacado 2", "punto destacado 3"]}}

Los highlights deben ser 3-5 características únicas y atractivas de la propiedad (no información genérica como "tiene baños")."""

        message = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        response_text = message.content[0].text.strip()

        # Intentar parsear JSON
        import json
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError:
            # Si falla el parsing, usar la descripción original
            print(f"[API] Error parsing AI response: {response_text[:200]}")
            result = {
                'improved_description': original_description,
                'highlights': []
            }

        return jsonify({
            'success': True,
            'data': result
        }), 200

    except Exception as e:
        print(f"Error en improve_description: {str(e)}")
        traceback.print_exc()
        # En caso de error, devolver descripción original
        return jsonify({
            'success': True,
            'data': {
                'improved_description': data.get('description', ''),
                'highlights': []
            }
        }), 200
