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
