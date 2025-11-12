#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API REST para propiedades - Proyecto Cupido
Expone endpoints para que el frontend consuma la base de datos de Neon
"""

from flask import Blueprint, jsonify, request
from database import DatabaseManager
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
    - limit: int (default: 100)
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
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        city = request.args.get('city')
        prop_type = request.args.get('type')
        min_price = request.args.get('min_price')
        max_price = request.args.get('max_price')
        bedrooms = request.args.get('bedrooms')

        # Construir query SQL
        query = """
            SELECT
                id,
                codigo_propiedad as slug,
                titulo as title,
                tipo_propiedad as type,
                precio as price_cop,
                ciudad as city,
                zona as barrio,
                zona as zone,
                area_construida as area_m2,
                habitaciones as bedrooms,
                banos as bathrooms,
                parqueaderos as parking,
                estrato as stratum,
                ano_construccion as age_years,
                administracion as admin_fee_cop,
                descripcion as description,
                direccion_completa as address,
                latitud as lat,
                longitud as lng,
                estado as condition,
                caracteristicas_adicionales as features,
                activa as published,
                CASE WHEN fuente = 'Pulppo' THEN true ELSE false END as exclusive,
                false as featured,
                fuente as source,
                fecha_creacion as created_at,
                fecha_actualizacion as updated_at
            FROM propiedades
            WHERE activa = TRUE
        """
        params = []

        # Solo filtrar por published si es necesario
        if not published:
            query = query.replace("WHERE activa = TRUE", "WHERE activa = FALSE")

        # Agregar filtros
        if city:
            query += " AND LOWER(ciudad) = LOWER(%s)"
            params.append(city)

        if prop_type:
            query += " AND LOWER(tipo_propiedad) = LOWER(%s)"
            params.append(prop_type)

        if min_price:
            query += " AND precio >= %s"
            params.append(int(min_price))

        if max_price:
            query += " AND precio <= %s"
            params.append(int(max_price))

        if bedrooms:
            query += " AND habitaciones = %s"
            params.append(int(bedrooms))

        # Ordenar y paginar
        query += " ORDER BY fecha_creacion DESC LIMIT %s OFFSET %s"
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

    Obtiene una propiedad específica por su slug (código)
    """
    db = None
    try:
        db = get_db()

        query = """
            SELECT
                id,
                codigo_propiedad as slug,
                titulo as title,
                tipo_propiedad as type,
                precio as price_cop,
                ciudad as city,
                zona as barrio,
                zona as zone,
                area_construida as area_m2,
                habitaciones as bedrooms,
                banos as bathrooms,
                parqueaderos as parking,
                estrato as stratum,
                ano_construccion as age_years,
                administracion as admin_fee_cop,
                descripcion as description,
                direccion_completa as address,
                latitud as lat,
                longitud as lng,
                estado as condition,
                caracteristicas_adicionales as features,
                activa as published,
                CASE WHEN fuente = 'Pulppo' THEN true ELSE false END as exclusive,
                false as featured,
                fuente as source,
                fecha_creacion as created_at,
                fecha_actualizacion as updated_at
            FROM propiedades
            WHERE codigo_propiedad = %s AND activa = true
        """

        db.cursor.execute(query, (slug,))
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
            'created_at': str(prop.get('created_at')) if prop.get('created_at') else None,
            'updated_at': str(prop.get('updated_at')) if prop.get('updated_at') else None,
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
