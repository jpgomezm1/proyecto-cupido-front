#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API REST para Analytics - Proyecto Cupido
Expone endpoints para estadísticas y métricas del sistema
"""

from flask import Blueprint, jsonify, request
from src.db.database import DatabaseManager
import traceback

# Crear blueprint para Analytics API
analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')


def get_db():
    """Helper para obtener conexión a la base de datos"""
    db = DatabaseManager()
    db.connect()
    return db


@analytics_bp.route('/overview', methods=['GET'])
def get_analytics_overview():
    """
    GET /api/analytics/overview

    Obtiene métricas generales del sistema
    """
    db = None
    try:
        db = get_db()

        # Total propiedades activas
        db.cursor.execute("SELECT COUNT(*) as count FROM propiedades WHERE activa = true")
        total_properties = db.cursor.fetchone()['count']

        # Total búsquedas (solicitudes de mercado)
        db.cursor.execute("SELECT COUNT(*) as count FROM solicitudes_mercado")
        total_searches = db.cursor.fetchone()['count']

        # Total propiedades captadas (Wasi_Captado + Tu360_Captado)
        db.cursor.execute("SELECT COUNT(*) as count FROM propiedades WHERE fuente IN ('Wasi_Captado', 'Tu360_Captado')")
        total_captures = db.cursor.fetchone()['count']

        # Total interacciones (selecciones)
        db.cursor.execute("SELECT COUNT(*) as count FROM interacciones WHERE estado = 'Seleccionado'")
        total_interactions = db.cursor.fetchone()['count']

        # Tiempo promedio de respuesta
        db.cursor.execute("""
            SELECT AVG(tiempo_respuesta_ms) as avg_time
            FROM solicitudes_mercado
            WHERE tiempo_respuesta_ms IS NOT NULL
        """)
        avg_response = db.cursor.fetchone()
        avg_response_time_ms = int(avg_response['avg_time']) if avg_response['avg_time'] else 0

        # Tasa de conversión (búsquedas que terminan en selección)
        conversion_rate = (total_interactions / total_searches * 100) if total_searches > 0 else 0

        return jsonify({
            'success': True,
            'data': {
                'total_properties': total_properties,
                'total_searches': total_searches,
                'total_captures': total_captures,
                'total_interactions': total_interactions,
                'avg_response_time_ms': avg_response_time_ms,
                'conversion_rate': round(conversion_rate, 2)
            }
        }), 200

    except Exception as e:
        print(f"[ANALYTICS] Error en overview: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@analytics_bp.route('/searches', methods=['GET'])
def get_analytics_searches():
    """
    GET /api/analytics/searches?days=30

    Obtiene estadísticas de búsquedas
    """
    db = None
    try:
        db = get_db()
        days = int(request.args.get('days', 30))

        # Búsquedas por día
        db.cursor.execute("""
            SELECT
                DATE(fecha_solicitud) as date,
                COUNT(*) as count
            FROM solicitudes_mercado
            WHERE fecha_solicitud >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY DATE(fecha_solicitud)
            ORDER BY date ASC
        """ % days)
        searches_by_day = [
            {'date': str(row['date']), 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        # Términos más buscados (tipo de propiedad)
        db.cursor.execute("""
            SELECT
                criterios_extraidos->>'tipo_propiedad' as property_type,
                COUNT(*) as count
            FROM solicitudes_mercado
            WHERE criterios_extraidos->>'tipo_propiedad' IS NOT NULL
            AND fecha_solicitud >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY criterios_extraidos->>'tipo_propiedad'
            ORDER BY count DESC
            LIMIT 10
        """ % days)
        popular_types = [
            {'type': row['property_type'], 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        # Ubicaciones más buscadas
        db.cursor.execute("""
            SELECT
                criterios_extraidos->>'ubicacion' as location,
                COUNT(*) as count
            FROM solicitudes_mercado
            WHERE criterios_extraidos->>'ubicacion' IS NOT NULL
            AND fecha_solicitud >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY criterios_extraidos->>'ubicacion'
            ORDER BY count DESC
            LIMIT 10
        """ % days)
        popular_locations = [
            {'location': row['location'], 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        return jsonify({
            'success': True,
            'data': {
                'searches_by_day': searches_by_day,
                'popular_types': popular_types,
                'popular_locations': popular_locations
            }
        }), 200

    except Exception as e:
        print(f"[ANALYTICS] Error en searches: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@analytics_bp.route('/captures', methods=['GET'])
def get_analytics_captures():
    """
    GET /api/analytics/captures?days=30

    Obtiene estadísticas de propiedades captadas
    """
    db = None
    try:
        db = get_db()
        days = int(request.args.get('days', 30))

        # Capturas por día
        db.cursor.execute("""
            SELECT
                DATE(fecha_creacion) as date,
                COUNT(*) as count
            FROM propiedades
            WHERE fuente IN ('Wasi_Captado', 'Tu360_Captado')
            AND fecha_creacion >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY DATE(fecha_creacion)
            ORDER BY date ASC
        """ % days)
        captures_by_day = [
            {'date': str(row['date']), 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        # Tipos de propiedades captadas
        db.cursor.execute("""
            SELECT
                tipo_propiedad as type,
                COUNT(*) as count
            FROM propiedades
            WHERE fuente IN ('Wasi_Captado', 'Tu360_Captado')
            AND fecha_creacion >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY tipo_propiedad
            ORDER BY count DESC
        """ % days)
        captures_by_type = [
            {'type': row['type'], 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        # Ciudades
        db.cursor.execute("""
            SELECT
                ciudad as city,
                COUNT(*) as count
            FROM propiedades
            WHERE fuente IN ('Wasi_Captado', 'Tu360_Captado')
            AND fecha_creacion >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY ciudad
            ORDER BY count DESC
            LIMIT 10
        """ % days)
        captures_by_city = [
            {'city': row['city'], 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        # Capturas por fuente
        db.cursor.execute("""
            SELECT
                fuente as source,
                COUNT(*) as count
            FROM propiedades
            WHERE fuente IN ('Wasi_Captado', 'Tu360_Captado')
            AND fecha_creacion >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY fuente
            ORDER BY count DESC
        """ % days)
        captures_by_source = [
            {'source': row['source'], 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        return jsonify({
            'success': True,
            'data': {
                'captures_by_day': captures_by_day,
                'captures_by_type': captures_by_type,
                'captures_by_city': captures_by_city,
                'captures_by_source': captures_by_source
            }
        }), 200

    except Exception as e:
        print(f"[ANALYTICS] Error en captures: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@analytics_bp.route('/captures/recent', methods=['GET'])
def get_recent_captures():
    """
    GET /api/analytics/captures/recent?limit=20

    Obtiene lista detallada de capturas recientes con timestamps y metadata
    """
    db = None
    try:
        db = get_db()
        limit = int(request.args.get('limit', 20))

        # Capturas recientes con detalles completos
        db.cursor.execute("""
            SELECT
                p.id,
                p.codigo_propiedad,
                p.titulo,
                p.tipo_propiedad,
                p.estado,
                p.precio,
                p.ciudad,
                p.zona,
                p.area_construida,
                p.habitaciones,
                p.banos,
                p.fuente,
                p.url,
                p.imagen_principal,
                p.agente_captador_telefono,
                p.grupo_origen,
                p.fecha_creacion,
                p.activa,
                a.nombre as agente_nombre,
                a.total_propiedades_captadas
            FROM propiedades p
            LEFT JOIN agentes a ON a.telefono = p.agente_captador_telefono
            WHERE p.fuente IN ('Wasi_Captado', 'Tu360_Captado')
            ORDER BY p.fecha_creacion DESC
            LIMIT %s
        """ % limit)

        captures = []
        for row in db.cursor.fetchall():
            # Formatear precio a string legible
            precio = row['precio']
            precio_formateado = f"${precio:,.0f}".replace(",", ".") if precio else "N/A"

            captures.append({
                'id': row['id'],
                'codigo': row['codigo_propiedad'],
                'titulo': row['titulo'],
                'tipo_propiedad': row['tipo_propiedad'],
                'estado': row['estado'],
                'precio': precio,
                'precio_formateado': precio_formateado,
                'ciudad': row['ciudad'],
                'barrio': row['zona'],
                'area_m2': row['area_construida'],
                'habitaciones': row['habitaciones'],
                'banos': row['banos'],
                'fuente': row['fuente'],
                'url_original': row['url'],
                'imagen_principal': row['imagen_principal'],
                'agente_captador_telefono': row['agente_captador_telefono'],
                'agente_nombre': row['agente_nombre'],
                'total_capturas_agente': row['total_propiedades_captadas'],
                'grupo_origen': row['grupo_origen'],
                'fecha_creacion': row['fecha_creacion'].isoformat() if row['fecha_creacion'] else None,
                'activa': row['activa']
            })

        return jsonify({
            'success': True,
            'data': {
                'captures': captures,
                'total': len(captures)
            }
        }), 200

    except Exception as e:
        print(f"[ANALYTICS] Error en recent captures: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@analytics_bp.route('/interactions', methods=['GET'])
def get_analytics_interactions():
    """
    GET /api/analytics/interactions?days=30

    Obtiene estadísticas de interacciones
    """
    db = None
    try:
        db = get_db()
        days = int(request.args.get('days', 30))

        # Interacciones por día
        db.cursor.execute("""
            SELECT
                DATE(fecha_seleccion) as date,
                COUNT(*) as count
            FROM interacciones
            WHERE fecha_seleccion >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY DATE(fecha_seleccion)
            ORDER BY date ASC
        """ % days)
        interactions_by_day = [
            {'date': str(row['date']), 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        # Estados
        db.cursor.execute("""
            SELECT
                estado as status,
                COUNT(*) as count
            FROM interacciones
            WHERE fecha_seleccion >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY estado
            ORDER BY count DESC
        """ % days)
        interactions_by_status = [
            {'status': row['status'], 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        return jsonify({
            'success': True,
            'data': {
                'interactions_by_day': interactions_by_day,
                'interactions_by_status': interactions_by_status
            }
        }), 200

    except Exception as e:
        print(f"[ANALYTICS] Error en interactions: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


# =============================================================================
# MARKET INTELLIGENCE ENDPOINTS
# =============================================================================

@analytics_bp.route('/market/zones', methods=['GET'])
def get_market_zones():
    """
    GET /api/analytics/market/zones

    Análisis de zonas: oferta vs demanda, precios, oportunidades
    """
    db = None
    try:
        db = get_db()
        days = int(request.args.get('days', 90))

        # OFERTA: Propiedades disponibles por zona
        db.cursor.execute("""
            SELECT
                COALESCE(zona, ciudad) as zone,
                ciudad as city,
                COUNT(*) as supply_count,
                AVG(precio) as avg_price,
                AVG(CASE WHEN area_construida > 0 THEN precio / area_construida END) as avg_price_m2,
                MIN(precio) as min_price,
                MAX(precio) as max_price,
                AVG(area_construida) as avg_area,
                AVG(habitaciones) as avg_bedrooms
            FROM propiedades
            WHERE activa = true
            GROUP BY COALESCE(zona, ciudad), ciudad
            HAVING COUNT(*) >= 1
            ORDER BY supply_count DESC
            LIMIT 20
        """)
        supply_by_zone = []
        for row in db.cursor.fetchall():
            supply_by_zone.append({
                'zone': row['zone'] or 'Sin zona',
                'city': row['city'] or 'Sin ciudad',
                'supply_count': row['supply_count'],
                'avg_price': int(row['avg_price']) if row['avg_price'] else 0,
                'avg_price_m2': int(row['avg_price_m2']) if row['avg_price_m2'] else 0,
                'min_price': int(row['min_price']) if row['min_price'] else 0,
                'max_price': int(row['max_price']) if row['max_price'] else 0,
                'avg_area': int(row['avg_area']) if row['avg_area'] else 0,
                'avg_bedrooms': round(row['avg_bedrooms'], 1) if row['avg_bedrooms'] else 0
            })

        # DEMANDA: Búsquedas por ubicación
        db.cursor.execute("""
            SELECT
                COALESCE(
                    criterios_extraidos->>'ubicacion',
                    criterios_extraidos->'ubicaciones'->>0
                ) as zone,
                COUNT(*) as demand_count,
                AVG((criterios_extraidos->>'precio_max')::numeric) as avg_budget
            FROM solicitudes_mercado
            WHERE fecha_solicitud >= CURRENT_DATE - INTERVAL '%s days'
            AND (
                criterios_extraidos->>'ubicacion' IS NOT NULL
                OR criterios_extraidos->'ubicaciones'->>0 IS NOT NULL
            )
            GROUP BY COALESCE(
                criterios_extraidos->>'ubicacion',
                criterios_extraidos->'ubicaciones'->>0
            )
            ORDER BY demand_count DESC
            LIMIT 20
        """ % days)
        demand_by_zone = []
        for row in db.cursor.fetchall():
            demand_by_zone.append({
                'zone': row['zone'] or 'Sin especificar',
                'demand_count': row['demand_count'],
                'avg_budget': int(row['avg_budget']) if row['avg_budget'] else 0
            })

        # Crear mapa combinado supply-demand
        zone_analysis = {}
        for s in supply_by_zone:
            zone_analysis[s['zone'].lower()] = {
                **s,
                'demand_count': 0,
                'avg_budget': 0,
                'gap_score': 0
            }

        for d in demand_by_zone:
            zone_key = d['zone'].lower()
            if zone_key in zone_analysis:
                zone_analysis[zone_key]['demand_count'] = d['demand_count']
                zone_analysis[zone_key]['avg_budget'] = d['avg_budget']
            else:
                zone_analysis[zone_key] = {
                    'zone': d['zone'],
                    'city': '',
                    'supply_count': 0,
                    'demand_count': d['demand_count'],
                    'avg_budget': d['avg_budget'],
                    'avg_price': 0,
                    'avg_price_m2': 0,
                    'min_price': 0,
                    'max_price': 0,
                    'avg_area': 0,
                    'avg_bedrooms': 0
                }

        # Calcular gap score (demanda/oferta ratio)
        for zone in zone_analysis.values():
            supply = zone['supply_count'] or 0.1
            demand = zone['demand_count'] or 0
            zone['gap_score'] = round(demand / supply, 2)

        # Ordenar por gap_score para identificar oportunidades
        opportunities = sorted(
            [z for z in zone_analysis.values() if z['demand_count'] > 0],
            key=lambda x: x['gap_score'],
            reverse=True
        )[:10]

        return jsonify({
            'success': True,
            'data': {
                'supply_by_zone': supply_by_zone,
                'demand_by_zone': demand_by_zone,
                'zone_analysis': list(zone_analysis.values()),
                'opportunities': opportunities
            }
        }), 200

    except Exception as e:
        print(f"[ANALYTICS] Error en market/zones: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@analytics_bp.route('/market/prices', methods=['GET'])
def get_market_prices():
    """
    GET /api/analytics/market/prices

    Análisis de precios: distribución, precio/m², tendencias
    """
    db = None
    try:
        db = get_db()

        # Distribución de precios por tipo de propiedad
        db.cursor.execute("""
            SELECT
                tipo_propiedad as type,
                COUNT(*) as count,
                AVG(precio) as avg_price,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY precio) as median_price,
                MIN(precio) as min_price,
                MAX(precio) as max_price,
                AVG(CASE WHEN area_construida > 0 THEN precio / area_construida END) as avg_price_m2,
                AVG(area_construida) as avg_area
            FROM propiedades
            WHERE activa = true AND precio > 0
            GROUP BY tipo_propiedad
            ORDER BY count DESC
        """)
        price_by_type = []
        for row in db.cursor.fetchall():
            price_by_type.append({
                'type': row['type'] or 'Otro',
                'count': row['count'],
                'avg_price': int(row['avg_price']) if row['avg_price'] else 0,
                'median_price': int(row['median_price']) if row['median_price'] else 0,
                'min_price': int(row['min_price']) if row['min_price'] else 0,
                'max_price': int(row['max_price']) if row['max_price'] else 0,
                'avg_price_m2': int(row['avg_price_m2']) if row['avg_price_m2'] else 0,
                'avg_area': int(row['avg_area']) if row['avg_area'] else 0
            })

        # Rangos de precio más comunes en inventario
        db.cursor.execute("""
            SELECT
                CASE
                    WHEN precio < 200000000 THEN '< 200M'
                    WHEN precio < 400000000 THEN '200M - 400M'
                    WHEN precio < 600000000 THEN '400M - 600M'
                    WHEN precio < 800000000 THEN '600M - 800M'
                    WHEN precio < 1000000000 THEN '800M - 1.000M'
                    ELSE '> 1.000M'
                END as price_range,
                COUNT(*) as count
            FROM propiedades
            WHERE activa = true AND precio > 0
            GROUP BY price_range
            ORDER BY MIN(precio)
        """)
        inventory_by_range = [
            {'range': row['price_range'], 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        # Precio/m² por zona (top zonas)
        db.cursor.execute("""
            SELECT
                COALESCE(zona, ciudad) as zone,
                COUNT(*) as count,
                AVG(CASE WHEN area_construida > 0 THEN precio / area_construida END) as avg_price_m2,
                MIN(CASE WHEN area_construida > 0 THEN precio / area_construida END) as min_price_m2,
                MAX(CASE WHEN area_construida > 0 THEN precio / area_construida END) as max_price_m2
            FROM propiedades
            WHERE activa = true AND precio > 0 AND area_construida > 0
            GROUP BY COALESCE(zona, ciudad)
            HAVING COUNT(*) >= 2
            ORDER BY avg_price_m2 DESC
            LIMIT 15
        """)
        price_m2_by_zone = []
        for row in db.cursor.fetchall():
            price_m2_by_zone.append({
                'zone': row['zone'] or 'Sin zona',
                'count': row['count'],
                'avg_price_m2': int(row['avg_price_m2']) if row['avg_price_m2'] else 0,
                'min_price_m2': int(row['min_price_m2']) if row['min_price_m2'] else 0,
                'max_price_m2': int(row['max_price_m2']) if row['max_price_m2'] else 0
            })

        # Estrato vs precio promedio
        db.cursor.execute("""
            SELECT
                estrato,
                COUNT(*) as count,
                AVG(precio) as avg_price,
                AVG(CASE WHEN area_construida > 0 THEN precio / area_construida END) as avg_price_m2
            FROM propiedades
            WHERE activa = true AND estrato IS NOT NULL AND precio > 0
            GROUP BY estrato
            ORDER BY estrato
        """)
        price_by_stratum = []
        for row in db.cursor.fetchall():
            price_by_stratum.append({
                'stratum': row['estrato'],
                'count': row['count'],
                'avg_price': int(row['avg_price']) if row['avg_price'] else 0,
                'avg_price_m2': int(row['avg_price_m2']) if row['avg_price_m2'] else 0
            })

        return jsonify({
            'success': True,
            'data': {
                'price_by_type': price_by_type,
                'inventory_by_range': inventory_by_range,
                'price_m2_by_zone': price_m2_by_zone,
                'price_by_stratum': price_by_stratum
            }
        }), 200

    except Exception as e:
        print(f"[ANALYTICS] Error en market/prices: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@analytics_bp.route('/market/demand', methods=['GET'])
def get_market_demand():
    """
    GET /api/analytics/market/demand

    Insights de demanda: qué buscan los clientes, preferencias, presupuestos
    Ideal para vender a constructoras
    """
    db = None
    try:
        db = get_db()
        days = int(request.args.get('days', 90))

        # Rangos de precio más buscados
        db.cursor.execute("""
            SELECT
                CASE
                    WHEN (criterios_extraidos->>'precio_max')::numeric < 200000000 THEN '< 200M'
                    WHEN (criterios_extraidos->>'precio_max')::numeric < 400000000 THEN '200M - 400M'
                    WHEN (criterios_extraidos->>'precio_max')::numeric < 600000000 THEN '400M - 600M'
                    WHEN (criterios_extraidos->>'precio_max')::numeric < 800000000 THEN '600M - 800M'
                    WHEN (criterios_extraidos->>'precio_max')::numeric < 1000000000 THEN '800M - 1.000M'
                    ELSE '> 1.000M'
                END as price_range,
                COUNT(*) as search_count,
                AVG((criterios_extraidos->>'precio_max')::numeric) as avg_max_budget
            FROM solicitudes_mercado
            WHERE fecha_solicitud >= CURRENT_DATE - INTERVAL '%s days'
            AND criterios_extraidos->>'precio_max' IS NOT NULL
            GROUP BY price_range
            ORDER BY search_count DESC
        """ % days)
        demand_by_price_range = []
        for row in db.cursor.fetchall():
            demand_by_price_range.append({
                'range': row['price_range'],
                'search_count': row['search_count'],
                'avg_budget': int(row['avg_max_budget']) if row['avg_max_budget'] else 0
            })

        # Tipo de propiedad más buscado
        db.cursor.execute("""
            SELECT
                criterios_extraidos->>'tipo_propiedad' as type,
                COUNT(*) as search_count
            FROM solicitudes_mercado
            WHERE fecha_solicitud >= CURRENT_DATE - INTERVAL '%s days'
            AND criterios_extraidos->>'tipo_propiedad' IS NOT NULL
            GROUP BY criterios_extraidos->>'tipo_propiedad'
            ORDER BY search_count DESC
        """ % days)
        demand_by_type = [
            {'type': row['type'], 'search_count': row['search_count']}
            for row in db.cursor.fetchall()
        ]

        # Habitaciones más buscadas
        db.cursor.execute("""
            SELECT
                COALESCE(
                    criterios_extraidos->>'habitaciones_min',
                    criterios_extraidos->>'habitaciones'
                ) as bedrooms,
                COUNT(*) as search_count
            FROM solicitudes_mercado
            WHERE fecha_solicitud >= CURRENT_DATE - INTERVAL '%s days'
            AND (
                criterios_extraidos->>'habitaciones_min' IS NOT NULL
                OR criterios_extraidos->>'habitaciones' IS NOT NULL
            )
            GROUP BY bedrooms
            ORDER BY search_count DESC
            LIMIT 10
        """ % days)
        demand_by_bedrooms = [
            {'bedrooms': row['bedrooms'], 'search_count': row['search_count']}
            for row in db.cursor.fetchall()
        ]

        # Presupuesto promedio por tipo
        db.cursor.execute("""
            SELECT
                criterios_extraidos->>'tipo_propiedad' as type,
                AVG((criterios_extraidos->>'precio_max')::numeric) as avg_budget,
                MIN((criterios_extraidos->>'precio_max')::numeric) as min_budget,
                MAX((criterios_extraidos->>'precio_max')::numeric) as max_budget,
                COUNT(*) as search_count
            FROM solicitudes_mercado
            WHERE fecha_solicitud >= CURRENT_DATE - INTERVAL '%s days'
            AND criterios_extraidos->>'tipo_propiedad' IS NOT NULL
            AND criterios_extraidos->>'precio_max' IS NOT NULL
            GROUP BY criterios_extraidos->>'tipo_propiedad'
            ORDER BY search_count DESC
        """ % days)
        budget_by_type = []
        for row in db.cursor.fetchall():
            budget_by_type.append({
                'type': row['type'],
                'avg_budget': int(row['avg_budget']) if row['avg_budget'] else 0,
                'min_budget': int(row['min_budget']) if row['min_budget'] else 0,
                'max_budget': int(row['max_budget']) if row['max_budget'] else 0,
                'search_count': row['search_count']
            })

        # Búsquedas recientes sin resultados (demanda no atendida)
        db.cursor.execute("""
            SELECT
                query_original,
                criterios_extraidos,
                fecha_solicitud
            FROM solicitudes_mercado
            WHERE fecha_solicitud >= CURRENT_DATE - INTERVAL '%s days'
            AND total_propiedades_encontradas = 0
            ORDER BY fecha_solicitud DESC
            LIMIT 20
        """ % days)
        unmet_demand = []
        for row in db.cursor.fetchall():
            unmet_demand.append({
                'query': row['query_original'][:100] if row['query_original'] else '',
                'criteria': row['criterios_extraidos'],
                'date': row['fecha_solicitud'].isoformat() if row['fecha_solicitud'] else None
            })

        return jsonify({
            'success': True,
            'data': {
                'demand_by_price_range': demand_by_price_range,
                'demand_by_type': demand_by_type,
                'demand_by_bedrooms': demand_by_bedrooms,
                'budget_by_type': budget_by_type,
                'unmet_demand': unmet_demand,
                'total_searches': sum(d['search_count'] for d in demand_by_type)
            }
        }), 200

    except Exception as e:
        print(f"[ANALYTICS] Error en market/demand: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@analytics_bp.route('/market/agents', methods=['GET'])
def get_market_agents():
    """
    GET /api/analytics/market/agents

    Performance de agentes: captaciones, búsquedas, rankings
    """
    db = None
    try:
        db = get_db()
        days = int(request.args.get('days', 90))

        # Top agentes por captaciones
        db.cursor.execute("""
            SELECT
                a.telefono,
                a.nombre,
                a.total_propiedades_captadas,
                a.total_busquedas,
                COUNT(DISTINCT p.id) as recent_captures,
                MAX(p.fecha_creacion) as last_capture
            FROM agentes a
            LEFT JOIN propiedades p ON p.agente_captador_telefono = a.telefono
                AND p.fecha_creacion >= CURRENT_DATE - INTERVAL '%s days'
            WHERE a.total_propiedades_captadas > 0
            GROUP BY a.id, a.telefono, a.nombre, a.total_propiedades_captadas, a.total_busquedas
            ORDER BY recent_captures DESC, a.total_propiedades_captadas DESC
            LIMIT 15
        """ % days)
        top_capturers = []
        for row in db.cursor.fetchall():
            top_capturers.append({
                'phone': row['telefono'],
                'name': row['nombre'] or 'Sin nombre',
                'total_captures': row['total_propiedades_captadas'],
                'total_searches': row['total_busquedas'],
                'recent_captures': row['recent_captures'],
                'last_capture': row['last_capture'].isoformat() if row['last_capture'] else None
            })

        # Top agentes por búsquedas
        db.cursor.execute("""
            SELECT
                a.telefono,
                a.nombre,
                a.total_busquedas,
                COUNT(DISTINCT s.id) as recent_searches
            FROM agentes a
            LEFT JOIN solicitudes_mercado s ON s.agente_telefono = a.telefono
                AND s.fecha_solicitud >= CURRENT_DATE - INTERVAL '%s days'
            WHERE a.total_busquedas > 0
            GROUP BY a.id, a.telefono, a.nombre, a.total_busquedas
            ORDER BY recent_searches DESC, a.total_busquedas DESC
            LIMIT 15
        """ % days)
        top_searchers = []
        for row in db.cursor.fetchall():
            top_searchers.append({
                'phone': row['telefono'],
                'name': row['nombre'] or 'Sin nombre',
                'total_searches': row['total_busquedas'],
                'recent_searches': row['recent_searches']
            })

        # Resumen general de agentes
        db.cursor.execute("""
            SELECT
                COUNT(*) as total_agents,
                SUM(total_propiedades_captadas) as total_captures,
                SUM(total_busquedas) as total_searches,
                AVG(total_propiedades_captadas) as avg_captures_per_agent
            FROM agentes
            WHERE total_propiedades_captadas > 0 OR total_busquedas > 0
        """)
        summary = db.cursor.fetchone()

        return jsonify({
            'success': True,
            'data': {
                'top_capturers': top_capturers,
                'top_searchers': top_searchers,
                'summary': {
                    'total_agents': summary['total_agents'] or 0,
                    'total_captures': summary['total_captures'] or 0,
                    'total_searches': summary['total_searches'] or 0,
                    'avg_captures_per_agent': round(summary['avg_captures_per_agent'] or 0, 1)
                }
            }
        }), 200

    except Exception as e:
        print(f"[ANALYTICS] Error en market/agents: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@analytics_bp.route('/market/inventory', methods=['GET'])
def get_market_inventory():
    """
    GET /api/analytics/market/inventory

    Estado del inventario: distribución, características, fuentes
    """
    db = None
    try:
        db = get_db()

        # Total inventario
        db.cursor.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE fuente = 'Pulppo') as pulppo,
                COUNT(*) FILTER (WHERE fuente = 'Wasi_Captado') as wasi,
                COUNT(*) FILTER (WHERE fuente = 'Tu360_Captado') as tu360,
                AVG(precio) as avg_price,
                AVG(area_construida) as avg_area
            FROM propiedades
            WHERE activa = true
        """)
        totals = db.cursor.fetchone()

        # Por ciudad
        db.cursor.execute("""
            SELECT
                ciudad as city,
                COUNT(*) as count,
                AVG(precio) as avg_price,
                AVG(CASE WHEN area_construida > 0 THEN precio / area_construida END) as avg_price_m2
            FROM propiedades
            WHERE activa = true
            GROUP BY ciudad
            ORDER BY count DESC
            LIMIT 10
        """)
        by_city = []
        for row in db.cursor.fetchall():
            by_city.append({
                'city': row['city'] or 'Sin ciudad',
                'count': row['count'],
                'avg_price': int(row['avg_price']) if row['avg_price'] else 0,
                'avg_price_m2': int(row['avg_price_m2']) if row['avg_price_m2'] else 0
            })

        # Por tipo
        db.cursor.execute("""
            SELECT
                tipo_propiedad as type,
                COUNT(*) as count,
                AVG(precio) as avg_price
            FROM propiedades
            WHERE activa = true
            GROUP BY tipo_propiedad
            ORDER BY count DESC
        """)
        by_type = [
            {
                'type': row['type'] or 'Otro',
                'count': row['count'],
                'avg_price': int(row['avg_price']) if row['avg_price'] else 0
            }
            for row in db.cursor.fetchall()
        ]

        # Por habitaciones
        db.cursor.execute("""
            SELECT
                habitaciones as bedrooms,
                COUNT(*) as count,
                AVG(precio) as avg_price
            FROM propiedades
            WHERE activa = true AND habitaciones IS NOT NULL
            GROUP BY habitaciones
            ORDER BY habitaciones
        """)
        by_bedrooms = [
            {
                'bedrooms': row['bedrooms'],
                'count': row['count'],
                'avg_price': int(row['avg_price']) if row['avg_price'] else 0
            }
            for row in db.cursor.fetchall()
        ]

        return jsonify({
            'success': True,
            'data': {
                'totals': {
                    'total': totals['total'],
                    'pulppo': totals['pulppo'],
                    'wasi': totals['wasi'],
                    'tu360': totals['tu360'],
                    'avg_price': int(totals['avg_price']) if totals['avg_price'] else 0,
                    'avg_area': int(totals['avg_area']) if totals['avg_area'] else 0
                },
                'by_city': by_city,
                'by_type': by_type,
                'by_bedrooms': by_bedrooms
            }
        }), 200

    except Exception as e:
        print(f"[ANALYTICS] Error en market/inventory: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@analytics_bp.route('/market/geo-zones', methods=['GET'])
def get_market_geo_zones():
    """
    GET /api/analytics/market/geo-zones

    Obtiene estadísticas por zona con coordenadas geográficas para visualización en mapa
    """
    db = None
    try:
        db = get_db()

        # Estadísticas por zona con coordenadas
        db.cursor.execute("""
            SELECT
                COALESCE(zona, 'Sin zona') as zone,
                ciudad as city,
                AVG(latitud) as lat,
                AVG(longitud) as lng,
                COUNT(*) as property_count,
                AVG(precio) as avg_price,
                MIN(precio) as min_price,
                MAX(precio) as max_price,
                AVG(precio / NULLIF(area_construida, 0)) as avg_price_m2,
                AVG(area_construida) as avg_area,
                AVG(habitaciones) as avg_bedrooms,
                STRING_AGG(DISTINCT tipo_propiedad, ', ') as property_types
            FROM propiedades
            WHERE activa = true
                AND latitud IS NOT NULL
                AND longitud IS NOT NULL
                AND latitud != 0
                AND longitud != 0
                AND longitud < -70
                AND longitud > -80
                AND latitud > 0
                AND latitud < 10
            GROUP BY zona, ciudad
            HAVING COUNT(*) >= 1
            ORDER BY COUNT(*) DESC
        """)

        zones = []
        for row in db.cursor.fetchall():
            zones.append({
                'zone': row['zone'],
                'city': row['city'],
                'lat': float(row['lat']) if row['lat'] else None,
                'lng': float(row['lng']) if row['lng'] else None,
                'property_count': row['property_count'],
                'avg_price': int(row['avg_price']) if row['avg_price'] else 0,
                'min_price': int(row['min_price']) if row['min_price'] else 0,
                'max_price': int(row['max_price']) if row['max_price'] else 0,
                'avg_price_m2': int(row['avg_price_m2']) if row['avg_price_m2'] else 0,
                'avg_area': int(row['avg_area']) if row['avg_area'] else 0,
                'avg_bedrooms': round(row['avg_bedrooms'], 1) if row['avg_bedrooms'] else 0,
                'property_types': row['property_types']
            })

        # Propiedades individuales para el mapa detallado
        db.cursor.execute("""
            SELECT
                id,
                titulo as title,
                tipo_propiedad as type,
                precio as price,
                COALESCE(zona, 'Sin zona') as zone,
                ciudad as city,
                latitud as lat,
                longitud as lng,
                area_construida as area,
                habitaciones as bedrooms,
                banos as bathrooms
            FROM propiedades
            WHERE activa = true
                AND latitud IS NOT NULL
                AND longitud IS NOT NULL
                AND latitud != 0
                AND longitud != 0
                AND longitud < -70
                AND longitud > -80
                AND latitud > 0
                AND latitud < 10
            ORDER BY precio DESC
            LIMIT 200
        """)

        properties = []
        for row in db.cursor.fetchall():
            properties.append({
                'id': row['id'],
                'title': row['title'],
                'type': row['type'],
                'price': int(row['price']) if row['price'] else 0,
                'zone': row['zone'],
                'city': row['city'],
                'lat': float(row['lat']),
                'lng': float(row['lng']),
                'area': int(row['area']) if row['area'] else 0,
                'bedrooms': row['bedrooms'],
                'bathrooms': row['bathrooms']
            })

        # Estadísticas globales para el mapa
        db.cursor.execute("""
            SELECT
                AVG(latitud) as center_lat,
                AVG(longitud) as center_lng,
                MIN(precio) as global_min_price,
                MAX(precio) as global_max_price,
                AVG(precio) as global_avg_price
            FROM propiedades
            WHERE activa = true
                AND latitud IS NOT NULL
                AND longitud IS NOT NULL
                AND latitud != 0
                AND longitud != 0
                AND longitud < -70
                AND longitud > -80
        """)
        stats_row = db.cursor.fetchone()

        stats = {
            'center_lat': float(stats_row['center_lat']) if stats_row['center_lat'] else 6.2442,
            'center_lng': float(stats_row['center_lng']) if stats_row['center_lng'] else -75.5812,
            'min_price': int(stats_row['global_min_price']) if stats_row['global_min_price'] else 0,
            'max_price': int(stats_row['global_max_price']) if stats_row['global_max_price'] else 0,
            'avg_price': int(stats_row['global_avg_price']) if stats_row['global_avg_price'] else 0
        }

        return jsonify({
            'success': True,
            'data': {
                'zones': zones,
                'properties': properties,
                'stats': stats
            }
        }), 200

    except Exception as e:
        print(f"[ANALYTICS] Error en market/geo-zones: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()
