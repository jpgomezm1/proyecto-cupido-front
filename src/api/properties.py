#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API REST para propiedades - Proyecto Cupido
Expone endpoints para que el frontend consuma la base de datos de Neon
"""

from flask import Blueprint, jsonify, request
from src.db.database import DatabaseManager
from src.scrapers.utils import PropertyNormalizer
import traceback
from typing import Dict, List, Optional

# Crear blueprint para la API
api_bp = Blueprint('api', __name__, url_prefix='/api')


def get_db():
    """Helper para obtener conexión a la base de datos"""
    db = DatabaseManager()
    if not db.connect():
        raise ConnectionError("No se pudo conectar a la base de datos")
    return db


@api_bp.route('/properties', methods=['GET'])
def get_properties():
    """
    GET /api/properties

    Obtiene lista de propiedades con filtros opcionales

    Query params:
    - status: string ('all', 'active', 'inactive') - default: 'active'
    - limit: int (default: 50)
    - offset: int (default: 0)
    - city: string
    - type: string
    - min_price: number
    - max_price: number
    - bedrooms: number
    - source: string (Propia, Wasi, Tu360, Lobbie, Pulppo)
    - zone: string (barrio/zona)
    - stratum: int
    - search: string (text search across title, city, zone, slug)
    - min_area: number
    - max_area: number
    - sort_by: string (recent, price_asc, price_desc, area_desc, price_m2_asc, monthly_cost_asc)
    - max_admin: number (max admin fee)
    - min_year: number (min construction year)
    - max_year: number (max construction year)
    - opportunity: string ('true') - below zone avg price/m2 + recent 30 days
    - min_price_m2: number (min price per m2)
    - max_price_m2: number (max price per m2)
    - below_zone_avg: string ('true') - below zone avg price/m2 (no date restriction)
    """
    db = None
    try:
        db = get_db()

        # Parámetros de query
        status = request.args.get('status', 'active')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        city = request.args.get('city')
        prop_type = request.args.get('type')
        min_price = request.args.get('min_price')
        max_price = request.args.get('max_price')
        bedrooms = request.args.get('bedrooms')
        source = request.args.get('source')
        zone = request.args.get('zone')
        stratum = request.args.get('stratum')
        search = request.args.get('search')
        min_area = request.args.get('min_area')
        max_area = request.args.get('max_area')
        sort_by = request.args.get('sort_by', 'recent')
        max_admin = request.args.get('max_admin')
        min_year = request.args.get('min_year')
        max_year = request.args.get('max_year')
        opportunity = request.args.get('opportunity')
        min_price_m2 = request.args.get('min_price_m2')
        max_price_m2 = request.args.get('max_price_m2')
        below_zone_avg = request.args.get('below_zone_avg')

        # Construir condición de estado
        if status == 'all':
            status_condition = "TRUE"
        elif status == 'inactive':
            status_condition = "p.activa = FALSE"
        else:
            status_condition = "p.activa = TRUE"

        # Base WHERE clause
        where_clause = f"""
            WHERE {status_condition}
            AND (p.tipo_negocio = 'Venta' OR p.tipo_negocio IS NULL)
        """
        params = []

        # Agregar filtros
        if city:
            where_clause += " AND LOWER(p.ciudad) = LOWER(%s)"
            params.append(city)

        if prop_type:
            where_clause += " AND LOWER(p.tipo_propiedad) = LOWER(%s)"
            params.append(prop_type)

        if min_price:
            where_clause += " AND p.precio >= %s"
            params.append(int(min_price))

        if max_price:
            where_clause += " AND p.precio <= %s"
            params.append(int(max_price))

        if bedrooms:
            bedrooms_val = int(bedrooms)
            if bedrooms_val >= 5:
                where_clause += " AND p.habitaciones >= %s"
            else:
                where_clause += " AND p.habitaciones = %s"
            params.append(bedrooms_val)

        if source:
            if source == 'Wasi':
                where_clause += " AND p.fuente LIKE %s"
                params.append('%Wasi%')
            elif source == 'Tu360':
                where_clause += " AND p.fuente LIKE %s"
                params.append('%Tu360%')
            else:
                where_clause += " AND p.fuente = %s"
                params.append(source)

        if zone:
            where_clause += " AND LOWER(p.zona) = LOWER(%s)"
            params.append(zone)

        if stratum:
            where_clause += " AND p.estrato = %s"
            params.append(int(stratum))

        if min_area:
            where_clause += " AND p.area_construida >= %s"
            params.append(float(min_area))

        if max_area:
            where_clause += " AND p.area_construida <= %s"
            params.append(float(max_area))

        if max_admin:
            where_clause += " AND COALESCE(p.administracion, 0) <= %s"
            params.append(int(max_admin))

        if min_year:
            where_clause += " AND p.ano_construccion >= %s"
            params.append(int(min_year))

        if max_year:
            where_clause += " AND p.ano_construccion <= %s"
            params.append(int(max_year))

        if opportunity and opportunity.lower() == 'true':
            where_clause += """
                AND p.area_construida > 0 AND p.precio > 0
                AND p.fecha_creacion >= CURRENT_DATE - INTERVAL '30 days'
                AND p.precio / p.area_construida < (
                    SELECT AVG(p2.precio / p2.area_construida)
                    FROM propiedades p2
                    WHERE p2.activa = true AND p2.area_construida > 0
                    AND p2.precio > 0 AND LOWER(p2.zona) = LOWER(p.zona)
                )
            """

        if below_zone_avg and below_zone_avg.lower() == 'true':
            where_clause += """
                AND p.area_construida > 0 AND p.precio > 0
                AND p.precio / p.area_construida < (
                    SELECT AVG(p2.precio / p2.area_construida)
                    FROM propiedades p2
                    WHERE p2.activa = true AND p2.area_construida > 0
                    AND p2.precio > 0 AND LOWER(p2.zona) = LOWER(p.zona)
                )
            """

        if min_price_m2:
            where_clause += " AND p.area_construida > 0 AND (p.precio / p.area_construida) >= %s"
            params.append(float(min_price_m2))

        if max_price_m2:
            where_clause += " AND p.area_construida > 0 AND (p.precio / p.area_construida) <= %s"
            params.append(float(max_price_m2))

        if search:
            search_clean = search.strip()
            # Detectar búsqueda múltiple por códigos/IDs (ej: "9654920, 9481415")
            potential_codes = [s.strip() for s in search_clean.replace(',', ' ').split() if s.strip().isdigit()]

            if len(potential_codes) > 1:
                # Búsqueda múltiple: buscar por ID numérico O por codigo_propiedad
                placeholders = ','.join(['%s'] * len(potential_codes))
                where_clause += f" AND (p.id IN ({placeholders}) OR p.codigo_propiedad IN ({placeholders}))"
                params.extend([int(c) for c in potential_codes])
                params.extend(potential_codes)
            else:
                search_term = f"%{search_clean}%"
                where_clause += """ AND (
                    LOWER(p.titulo) LIKE LOWER(%s) OR
                    LOWER(p.zona) LIKE LOWER(%s) OR
                    LOWER(p.ciudad) LIKE LOWER(%s) OR
                    LOWER(p.codigo_propiedad) LIKE LOWER(%s) OR
                    CAST(p.id AS TEXT) = %s
                )"""
                params.extend([search_term, search_term, search_term, search_term, search_clean])

        # COUNT query (same filters, no limit/offset)
        count_query = f"""
            SELECT COUNT(*) as total
            FROM propiedades p
            LEFT JOIN agentes a ON a.telefono = p.agente_captador_telefono
            {where_clause}
        """
        db.cursor.execute(count_query, tuple(params))
        total_count = db.cursor.fetchone()['total']

        # Sort
        sort_map = {
            'price_asc': 'p.precio ASC NULLS LAST',
            'price_desc': 'p.precio DESC NULLS LAST',
            'area_desc': 'p.area_construida DESC NULLS LAST',
            'price_m2_asc': 'CASE WHEN p.area_construida > 0 THEN p.precio / p.area_construida ELSE NULL END ASC NULLS LAST',
            'monthly_cost_asc': '(COALESCE(p.administracion, 0) + COALESCE(p.predial, 0) / 12.0) ASC NULLS LAST',
        }
        order_clause = sort_map.get(sort_by, 'p.fecha_creacion DESC')

        # Main query with cover image subquery
        query = f"""
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
                p.predial as predial_cop,
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
                a.nombre as owner_name,
                p.imagen_principal as cover_image_url
            FROM propiedades p
            LEFT JOIN agentes a ON a.telefono = p.agente_captador_telefono
            {where_clause}
            ORDER BY {order_clause}
            LIMIT %s OFFSET %s
        """
        paginate_params = list(params) + [limit, offset]

        # Ejecutar query
        db.cursor.execute(query, tuple(paginate_params))
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
                'predial_cop': prop.get('predial_cop'),
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
                'cover_image_url': prop.get('cover_image_url'),
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

            # Generar shareable_slug con nombre legible
            title_slug = PropertyNormalizer.slugify_titulo(prop_dict.get('title', ''))
            prop_id = str(prop_dict.get('id', ''))
            prop_dict['shareable_slug'] = f"{prop_id}-{title_slug}" if title_slug else prop_id

            properties_list.append(prop_dict)

        page = (offset // limit) + 1 if limit > 0 else 1

        return jsonify({
            'success': True,
            'data': properties_list,
            'count': len(properties_list),
            'total_count': total_count,
            'page': page,
            'per_page': limit
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

        # Extraer ID numérico del inicio del slug para soportar
        # slugs legibles tipo "7859-apto-san-lucas"
        numeric_id = slug.split('-')[0] if '-' in slug else slug

        # Intentar buscar por codigo_propiedad primero, luego por ID
        # Esto permite usar tanto "WASI-12345" como "26" como "7859-apto-san-lucas"
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
                p.predial as predial_cop,
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

        db.cursor.execute(query, (slug, numeric_id))
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

        # Generar shareable_slug con nombre legible
        title_slug = PropertyNormalizer.slugify_titulo(prop_dict.get('title', ''))
        prop_id = str(prop_dict.get('id', ''))
        prop_dict['shareable_slug'] = f"{prop_id}-{title_slug}" if title_slug else prop_id

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

        # 2. ZONAS/BARRIOS (todas)
        db.cursor.execute("""
            SELECT zona, COUNT(*) as count
            FROM propiedades
            WHERE activa = true AND zona IS NOT NULL AND zona != ''
            GROUP BY zona
            ORDER BY count DESC
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


@api_bp.route('/properties/<int:property_id>/status', methods=['PUT'])
def update_property_status(property_id: int):
    """
    PUT /api/properties/:property_id/status

    Actualiza el estado activo/inactivo de una propiedad

    Body:
    {
        "activa": true/false
    }

    Returns:
    {
        "success": true,
        "data": {
            "id": 123,
            "codigo_propiedad": "WASI-123",
            "titulo": "...",
            "activa": false
        }
    }
    """
    db = None
    try:
        db = get_db()
        data = request.get_json()

        if data is None or 'activa' not in data:
            return jsonify({
                'success': False,
                'error': 'Campo activa requerido'
            }), 400

        activa = bool(data['activa'])

        db.cursor.execute("""
            UPDATE propiedades
            SET activa = %s, fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id, codigo_propiedad, titulo, activa
        """, (activa, property_id))

        result = db.cursor.fetchone()

        if not result:
            return jsonify({
                'success': False,
                'error': 'Propiedad no encontrada'
            }), 404

        db.conn.commit()

        return jsonify({
            'success': True,
            'data': dict(result),
            'message': f"Propiedad {'activada' if activa else 'desactivada'} exitosamente"
        }), 200

    except Exception as e:
        if db and db.conn:
            db.conn.rollback()
        print(f"❌ Error en update_property_status: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
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

        # Agregar información del agente captador si se proporciona
        agente_telefono = data.get('agente_telefono')
        agente_nombre = data.get('agente_nombre')

        if agente_telefono:
            # Normalizar teléfono a formato +57
            telefono_normalizado = agente_telefono.strip()
            if not telefono_normalizado.startswith('+'):
                telefono_normalizado = '+57' + telefono_normalizado.lstrip('0')
            property_data['agente_captador_telefono'] = telefono_normalizado
            print(f"[API] Agente captador: {telefono_normalizado}")

        # Guardar en base de datos
        db = get_db()

        # Si hay nombre de agente, crear o actualizar en tabla agentes
        if agente_telefono and agente_nombre:
            telefono_normalizado = property_data.get('agente_captador_telefono', agente_telefono)
            db.get_or_create_agente(telefono_normalizado, agente_nombre)
            print(f"[API] Agente registrado: {agente_nombre} ({telefono_normalizado})")

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

        # Agregar información del agente captador si se proporciona
        agente_telefono = data.get('agente_telefono')
        agente_nombre = data.get('agente_nombre')

        if agente_telefono:
            # Normalizar teléfono a formato +57
            telefono_normalizado = agente_telefono.strip()
            if not telefono_normalizado.startswith('+'):
                telefono_normalizado = '+57' + telefono_normalizado.lstrip('0')
            property_data['agente_captador_telefono'] = telefono_normalizado
            print(f"[API] Agente captador: {telefono_normalizado}")

        # Guardar en base de datos
        db = get_db()

        # Si hay nombre de agente, crear o actualizar en tabla agentes
        if agente_telefono and agente_nombre:
            telefono_normalizado = property_data.get('agente_captador_telefono', agente_telefono)
            db.get_or_create_agente(telefono_normalizado, agente_nombre)
            print(f"[API] Agente registrado: {agente_nombre} ({telefono_normalizado})")

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

        # Agregar información del agente captador si se proporciona
        agente_telefono = data.get('agente_telefono')
        agente_nombre = data.get('agente_nombre')

        if agente_telefono:
            # Normalizar teléfono a formato +57
            telefono_normalizado = agente_telefono.strip()
            if not telefono_normalizado.startswith('+'):
                telefono_normalizado = '+57' + telefono_normalizado.lstrip('0')
            property_data['agente_captador_telefono'] = telefono_normalizado
            print(f"[API] Agente captador: {telefono_normalizado}")

        # Guardar en base de datos
        db = get_db()

        # Si hay nombre de agente, crear o actualizar en tabla agentes
        if agente_telefono and agente_nombre:
            telefono_normalizado = property_data.get('agente_captador_telefono', agente_telefono)
            db.get_or_create_agente(telefono_normalizado, agente_nombre)
            print(f"[API] Agente registrado: {agente_nombre} ({telefono_normalizado})")

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


@api_bp.route('/properties/<int:property_id>/captador', methods=['PUT'])
def update_property_captador(property_id: int):
    """
    PUT /api/properties/:property_id/captador

    Actualiza la información del agente captador de una propiedad

    Body:
    {
        "agente_telefono": "+573001234567" o "3001234567",
        "agente_nombre": "Juan Pérez"  (opcional)
    }

    Returns:
    {
        "success": true,
        "data": {
            "id": 123,
            "agente_captador_telefono": "+573001234567",
            "owner_name": "Juan Pérez"
        }
    }
    """
    db = None
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body is required'
            }), 400

        agente_telefono = data.get('agente_telefono')
        agente_nombre = data.get('agente_nombre')

        # Validar que al menos uno de los campos esté presente
        if not agente_telefono and not agente_nombre:
            return jsonify({
                'success': False,
                'error': 'Se requiere al menos agente_telefono o agente_nombre'
            }), 400

        db = get_db()

        # Verificar que la propiedad existe
        db.cursor.execute("SELECT id FROM propiedades WHERE id = %s", (property_id,))
        if not db.cursor.fetchone():
            return jsonify({
                'success': False,
                'error': 'Propiedad no encontrada'
            }), 404

        # Normalizar teléfono si se proporciona
        telefono_normalizado = None
        if agente_telefono:
            telefono_normalizado = agente_telefono.strip()
            if not telefono_normalizado.startswith('+'):
                telefono_normalizado = '+57' + telefono_normalizado.lstrip('0')

            # Validar formato básico
            import re
            if not re.match(r'^\+57\d{10}$', telefono_normalizado):
                return jsonify({
                    'success': False,
                    'error': 'Formato de teléfono inválido. Use formato: 3001234567 o +573001234567'
                }), 400

        # Si hay nombre de agente y teléfono, crear o actualizar en tabla agentes
        if telefono_normalizado and agente_nombre:
            db.get_or_create_agente(telefono_normalizado, agente_nombre)
            print(f"[API] Agente actualizado/creado: {agente_nombre} ({telefono_normalizado})")
        elif telefono_normalizado and not agente_nombre:
            # Solo actualizar el nombre si se proporciona teléfono sin nombre
            # Verificar si ya existe el agente
            db.cursor.execute("SELECT nombre FROM agentes WHERE telefono = %s", (telefono_normalizado,))
            existing = db.cursor.fetchone()
            if not existing:
                # Crear agente sin nombre
                db.get_or_create_agente(telefono_normalizado, None)

        # Actualizar la propiedad
        if telefono_normalizado:
            db.cursor.execute("""
                UPDATE propiedades
                SET agente_captador_telefono = %s
                WHERE id = %s
            """, (telefono_normalizado, property_id))
            db.conn.commit()

        # Obtener la propiedad actualizada con info del agente
        db.cursor.execute("""
            SELECT
                p.id,
                p.codigo_propiedad as slug,
                p.titulo as title,
                p.agente_captador_telefono as owner_phone,
                a.nombre as owner_name
            FROM propiedades p
            LEFT JOIN agentes a ON a.telefono = p.agente_captador_telefono
            WHERE p.id = %s
        """, (property_id,))

        updated_property = db.cursor.fetchone()

        return jsonify({
            'success': True,
            'data': dict(updated_property) if updated_property else None,
            'message': 'Información del captador actualizada exitosamente'
        }), 200

    except Exception as e:
        if db and db.conn:
            db.conn.rollback()
        print(f"[API] Error en update_property_captador: {str(e)}")
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

    OPTIMIZADO: Si property_id se proporciona, cachea el resultado en DB
    para evitar llamadas repetidas a la API de AI.

    Body:
    {
        "description": "texto de descripción original...",
        "property_id": 123,  // opcional, para cachear en DB
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
            "highlights": ["highlight1", "highlight2", ...],
            "cached": true/false  // indica si vino de cache
        }
    }
    """
    try:
        import anthropic
        import os
        import json

        data = request.get_json()
        if not data or 'description' not in data:
            return jsonify({
                'success': False,
                'error': 'description is required'
            }), 400

        original_description = data['description']
        property_info = data.get('property_info', {})
        property_id = data.get('property_id')

        # === PASO 1: Verificar cache en DB si tenemos property_id ===
        if property_id:
            try:
                with DatabaseManager() as db:
                    db.cursor.execute("""
                        SELECT descripcion_ai, highlights_ai
                        FROM propiedades
                        WHERE id = %s AND descripcion_ai IS NOT NULL
                    """, (property_id,))
                    cached = db.cursor.fetchone()

                    if cached and cached.get('descripcion_ai'):
                        # Retornar descripción cacheada
                        highlights = []
                        if cached.get('highlights_ai'):
                            try:
                                highlights = json.loads(cached['highlights_ai'])
                            except json.JSONDecodeError:
                                highlights = []

                        print(f"[API] improve-description: usando cache para propiedad {property_id}")
                        return jsonify({
                            'success': True,
                            'data': {
                                'improved_description': cached['descripcion_ai'],
                                'highlights': highlights,
                                'cached': True
                            }
                        }), 200
            except Exception as e:
                # Si falla la lectura de cache, continuar con generación
                print(f"[API] Error al leer cache de descripción AI: {e}")

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

        prompt = f"""Eres un copywriter inmobiliario experto. Transforma esta descripción cruda de portal en texto profesional y atractivo.

PROPIEDAD: {context}

TEXTO ORIGINAL (crudo, desordenado, con metadatos mezclados):
{original_description}

REGLAS:
1. ELIMINA toda la metadata técnica (País, Provincia, Estado, Tipo Inmueble, Negocio, Galería, Detalle del Inmueble, etc.) — eso ya se muestra en la ficha
2. ELIMINA datos repetidos que ya están en campos separados: precio, área, habitaciones, baños, estrato, año, administración
3. ELIMINA listas de características sueltas tipo "Admite mascotas Agua Balcón..." — eso ya se muestra como amenidades
4. CONSERVA solo la narrativa descriptiva: qué hace especial esta propiedad, distribución, vistas, acabados, ubicación
5. Escribe 2-3 párrafos fluidos, profesionales y en español colombiano
6. NO inventes información que no esté en el original
7. Si queda poca narrativa real después de limpiar, escribe una descripción atractiva breve basada en lo que sí hay

FORMATO DE RESPUESTA — JSON puro sin markdown, sin ```:
{{"improved_description": "Párrafo 1.\\n\\nPárrafo 2.\\n\\nPárrafo 3.", "highlights": ["destacado 1", "destacado 2", "destacado 3", "destacado 4"]}}

Los highlights son 3-5 puntos únicos y atractivos (no genéricos como "tiene baños")."""

        import time
        start_time = time.time()

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        # Track AI usage
        from src.core.ai_usage_tracker import get_ai_tracker
        get_ai_tracker().track_anthropic_response(
            model='claude-haiku-4-5-20251001',
            usage_type='description_improvement',
            function_name='properties.improve_property_description',
            response=message,
            start_time=start_time,
            context={'description_length': len(original_description)}
        )

        response_text = message.content[0].text.strip()

        # Strip markdown code fences if present
        if response_text.startswith('```'):
            response_text = response_text.split('\n', 1)[-1] if '\n' in response_text else response_text[3:]
            if response_text.endswith('```'):
                response_text = response_text[:-3].strip()

        # Intentar parsear JSON
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError:
            # Si falla el parsing, usar la descripción original
            print(f"[API] Error parsing AI response: {response_text[:200]}")
            result = {
                'improved_description': original_description,
                'highlights': []
            }

        # === PASO 2: Guardar en DB si tenemos property_id y generación exitosa ===
        if property_id and result.get('improved_description') and result['improved_description'] != original_description:
            try:
                with DatabaseManager() as db:
                    highlights_json = json.dumps(result.get('highlights', []))
                    db.cursor.execute("""
                        UPDATE propiedades
                        SET descripcion_ai = %s,
                            highlights_ai = %s,
                            descripcion_ai_fecha = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (result['improved_description'], highlights_json, property_id))
                    db.conn.commit()
                    print(f"[API] improve-description: descripción AI guardada para propiedad {property_id}")
            except Exception as e:
                print(f"[API] Error al guardar descripción AI en cache: {e}")

        # Agregar flag de que no vino de cache
        result['cached'] = False

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


@api_bp.route('/properties/<int:property_id>/opportunity-insight', methods=['POST'])
def get_opportunity_insight(property_id):
    """
    POST /api/properties/<id>/opportunity-insight

    Genera un análisis con AI de por qué una propiedad es una oportunidad.
    Recibe datos de mercado del frontend para evitar queries extra.

    Body JSON:
    - price_cop: number
    - area_m2: number
    - price_m2: number
    - zone: string
    - zone_avg_m2: number
    - city: string
    - type: string
    - bedrooms: number
    - bathrooms: number
    - stratum: number
    - admin_fee: number | null
    - days_listed: number
    """
    db = None
    try:
        import anthropic
        import os
        import json

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Request body required'}), 400

        price_cop = data.get('price_cop', 0)
        area_m2 = data.get('area_m2', 0)
        price_m2 = data.get('price_m2', 0)
        zone = data.get('zone', '')
        zone_avg_m2 = data.get('zone_avg_m2', 0)
        city = data.get('city', '')
        prop_type = data.get('type', '')
        bedrooms = data.get('bedrooms', 0)
        bathrooms = data.get('bathrooms', 0)
        stratum = data.get('stratum', 0)
        admin_fee = data.get('admin_fee')
        days_listed = data.get('days_listed', 0)

        # Calcular % por debajo del promedio
        pct_below = round(((zone_avg_m2 - price_m2) / zone_avg_m2) * 100) if zone_avg_m2 > 0 else 0

        # Check cache in DB
        try:
            db = get_db()
            db.cursor.execute("""
                SELECT oportunidad_insight_ai
                FROM propiedades
                WHERE id = %s AND oportunidad_insight_ai IS NOT NULL
            """, (property_id,))
            cached = db.cursor.fetchone()
            if cached and cached.get('oportunidad_insight_ai'):
                print(f"[API] opportunity-insight: usando cache para propiedad {property_id}")
                return jsonify({
                    'success': True,
                    'data': {
                        'insight': cached['oportunidad_insight_ai'],
                        'cached': True
                    }
                }), 200
        except Exception:
            pass  # Column may not exist yet, continue to generate

        # Format price for prompt
        def fmt_cop(v):
            if v >= 1_000_000_000:
                return f"${v/1_000_000_000:.1f} mil millones"
            elif v >= 1_000_000:
                return f"${v/1_000_000:.1f}M"
            elif v >= 1_000:
                return f"${v/1_000:.0f}K"
            return f"${v:,.0f}"

        admin_text = f"Administración: {fmt_cop(admin_fee)}/mes" if admin_fee else "Sin admin reportada"

        prompt = f"""Eres un analista inmobiliario experto en el mercado colombiano. Analiza esta propiedad y explica por qué es una oportunidad.

PROPIEDAD: {prop_type} en {zone}, {city} (Estrato {stratum})
Precio: {fmt_cop(price_cop)} | Área: {area_m2} m² | Precio/m²: {fmt_cop(price_m2)}
{bedrooms} hab, {bathrooms} baños | {admin_text}
Publicada hace {days_listed} días

MERCADO: Promedio en {zone}: {fmt_cop(zone_avg_m2)}/m² → esta propiedad está {pct_below}% por debajo.

REGLAS ESTRICTAS DE FORMATO:
- Escribe EXACTAMENTE 3 párrafos cortos separados por línea en blanco
- Párrafo 1: Por qué el precio es atractivo vs la zona (usa los números)
- Párrafo 2: Qué hace especial esta propiedad (área, ubicación, estrato, admin)
- Párrafo 3: Para quién es ideal (tipo de comprador) y urgencia si es reciente
- PROHIBIDO usar títulos, headers (#), bullets, asteriscos o markdown
- PROHIBIDO empezar con "# Análisis" o cualquier encabezado
- Solo texto plano en español colombiano, tono profesional pero cercano
- Máximo 4 frases por párrafo, sé concreto con datos"""

        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

        import time
        start_time = time.time()

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        # Track AI usage
        try:
            from src.core.ai_usage_tracker import get_ai_tracker
            get_ai_tracker().track_anthropic_response(
                model='claude-haiku-4-5-20251001',
                usage_type='opportunity_insight',
                function_name='properties.get_opportunity_insight',
                response=message,
                start_time=start_time,
                context={'property_id': property_id, 'zone': zone}
            )
        except Exception:
            pass

        insight = message.content[0].text.strip()

        # Try to cache in DB
        try:
            if db:
                db.cursor.execute("""
                    UPDATE propiedades SET oportunidad_insight_ai = %s WHERE id = %s
                """, (insight, property_id))
                db.conn.commit()
                print(f"[API] opportunity-insight: guardado para propiedad {property_id}")
        except Exception as e:
            print(f"[API] Error al guardar insight en cache: {e}")
            # Column may not exist — that's fine, still return the result

        return jsonify({
            'success': True,
            'data': {
                'insight': insight,
                'cached': False
            }
        }), 200

    except Exception as e:
        print(f"Error en get_opportunity_insight: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
