#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API REST para Agentes - Proyecto Cupido
Gestiona los agentes inmobiliarios y su trazabilidad
"""

from flask import Blueprint, jsonify, request
from src.db.database import DatabaseManager
import traceback

# Crear blueprint para la API de agentes
agents_bp = Blueprint('agents', __name__, url_prefix='/api/agents')


def get_db():
    """Helper para obtener conexión a la base de datos"""
    db = DatabaseManager()
    db.connect()
    return db


@agents_bp.route('', methods=['GET'])
def get_agents():
    """
    GET /api/agents

    Obtiene lista de agentes con estadísticas

    Query params:
    - limit: int (default: 50)
    - offset: int (default: 0)
    - active: boolean (default: true)
    """
    db = None
    try:
        db = get_db()

        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        active = request.args.get('active', 'true').lower() == 'true'

        # Query optimizada: usar stats pre-computadas + subquery ligero para propiedades activas
        query = """
            SELECT
                a.id,
                a.telefono,
                a.nombre,
                a.activo,
                a.fecha_registro,
                a.fecha_actualizacion,
                a.total_propiedades_captadas,
                a.total_solicitudes_realizadas,
                a.total_matches_logrados,
                (SELECT COUNT(*) FROM propiedades p
                 WHERE p.agente_captador_telefono = a.telefono AND p.activa = TRUE
                ) as propiedades_activas
            FROM agentes a
            WHERE a.activo = %s
            ORDER BY a.fecha_registro DESC
            LIMIT %s OFFSET %s
        """

        db.cursor.execute(query, (active, limit, offset))
        agents = db.cursor.fetchall()

        # Obtener total de agentes
        db.cursor.execute("SELECT COUNT(*) as count FROM agentes WHERE activo = %s", (active,))
        total = db.cursor.fetchone()['count']

        agents_list = []
        for agent in agents:
            agents_list.append({
                'id': agent['id'],
                'telefono': agent['telefono'],
                'nombre': agent['nombre'],
                'activo': agent['activo'],
                'fecha_registro': str(agent['fecha_registro']) if agent['fecha_registro'] else None,
                'fecha_actualizacion': str(agent['fecha_actualizacion']) if agent['fecha_actualizacion'] else None,
                'stats': {
                    'propiedades_captadas': agent['propiedades_activas'] or 0,
                    'solicitudes_realizadas': agent['total_solicitudes_realizadas'] or 0,
                    'interacciones': agent['total_solicitudes_realizadas'] or 0,
                    'matches_logrados': agent['total_matches_logrados'] or 0,
                }
            })

        return jsonify({
            'success': True,
            'data': agents_list,
            'total': total,
            'limit': limit,
            'offset': offset
        }), 200

    except Exception as e:
        print(f"❌ Error en get_agents: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@agents_bp.route('/<telefono>', methods=['GET'])
def get_agent_detail(telefono: str):
    """
    GET /api/agents/:telefono

    Obtiene detalle de un agente específico
    """
    db = None
    try:
        db = get_db()

        # Normalizar teléfono
        if not telefono.startswith('+'):
            telefono = '+' + telefono

        # Query para obtener el agente
        query = """
            SELECT
                a.id,
                a.telefono,
                a.nombre,
                a.numero_whatsapp,
                a.activo,
                a.fecha_registro,
                a.fecha_actualizacion,
                a.total_propiedades_captadas,
                a.total_solicitudes_realizadas,
                a.total_matches_logrados
            FROM agentes a
            WHERE a.telefono = %s
        """

        db.cursor.execute(query, (telefono,))
        agent = db.cursor.fetchone()

        if not agent:
            return jsonify({
                'success': False,
                'error': 'Agente no encontrado'
            }), 404

        # Obtener estadísticas calculadas
        stats_query = """
            SELECT
                COUNT(DISTINCT p.id) as propiedades_activas,
                COUNT(DISTINCT s.id) as solicitudes_totales,
                COUNT(DISTINCT CASE WHEN i.agente_comprador_telefono = %s THEN i.id END) as interacciones_como_comprador,
                COUNT(DISTINCT CASE WHEN i.agente_vendedor_telefono = %s THEN i.id END) as interacciones_como_vendedor
            FROM agentes a
            LEFT JOIN propiedades p ON a.telefono = p.agente_captador_telefono AND p.activa = TRUE
            LEFT JOIN solicitudes_mercado s ON a.telefono = s.agente_telefono
            LEFT JOIN interacciones i ON a.telefono = i.agente_comprador_telefono OR a.telefono = i.agente_vendedor_telefono
            WHERE a.telefono = %s
        """

        db.cursor.execute(stats_query, (telefono, telefono, telefono))
        stats = db.cursor.fetchone()

        agent_data = {
            'id': agent['id'],
            'telefono': agent['telefono'],
            'nombre': agent['nombre'],
            'numero_whatsapp': agent['numero_whatsapp'],
            'activo': agent['activo'],
            'fecha_registro': str(agent['fecha_registro']) if agent['fecha_registro'] else None,
            'fecha_actualizacion': str(agent['fecha_actualizacion']) if agent['fecha_actualizacion'] else None,
            'stats': {
                'propiedades_captadas': stats['propiedades_activas'] or 0,
                'solicitudes_realizadas': stats['solicitudes_totales'] or 0,
                'interacciones_como_comprador': stats['interacciones_como_comprador'] or 0,
                'interacciones_como_vendedor': stats['interacciones_como_vendedor'] or 0,
                'matches_logrados': agent['total_matches_logrados'] or 0,
            }
        }

        return jsonify({
            'success': True,
            'data': agent_data
        }), 200

    except Exception as e:
        print(f"❌ Error en get_agent_detail: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@agents_bp.route('/<telefono>/properties', methods=['GET'])
def get_agent_properties(telefono: str):
    """
    GET /api/agents/:telefono/properties

    Obtiene propiedades captadas por un agente
    """
    db = None
    try:
        db = get_db()

        # Normalizar teléfono
        if not telefono.startswith('+'):
            telefono = '+' + telefono

        limit = int(request.args.get('limit', 20))
        offset = int(request.args.get('offset', 0))

        query = """
            SELECT
                p.id,
                p.codigo_propiedad as slug,
                p.titulo as title,
                p.tipo_propiedad as type,
                p.precio as price_cop,
                p.ciudad as city,
                p.zona as zone,
                p.habitaciones as bedrooms,
                p.banos as bathrooms,
                p.area_construida as area_m2,
                p.fuente as source,
                p.imagen_principal as cover_image,
                p.fecha_creacion as created_at,
                p.activa as active
            FROM propiedades p
            WHERE p.agente_captador_telefono = %s
            ORDER BY p.fecha_creacion DESC
            LIMIT %s OFFSET %s
        """

        db.cursor.execute(query, (telefono, limit, offset))
        properties = db.cursor.fetchall()

        # Obtener total
        db.cursor.execute(
            "SELECT COUNT(*) as count FROM propiedades WHERE agente_captador_telefono = %s",
            (telefono,)
        )
        total = db.cursor.fetchone()['count']

        properties_list = []
        for prop in properties:
            properties_list.append({
                'id': prop['id'],
                'slug': prop['slug'],
                'title': prop['title'],
                'type': prop['type'],
                'price_cop': prop['price_cop'],
                'city': prop['city'],
                'zone': prop['zone'],
                'bedrooms': prop['bedrooms'],
                'bathrooms': prop['bathrooms'],
                'area_m2': float(prop['area_m2']) if prop['area_m2'] else None,
                'source': prop['source'],
                'cover_image': prop['cover_image'],
                'created_at': str(prop['created_at']) if prop['created_at'] else None,
                'active': prop['active']
            })

        return jsonify({
            'success': True,
            'data': properties_list,
            'total': total
        }), 200

    except Exception as e:
        print(f"❌ Error en get_agent_properties: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@agents_bp.route('/<telefono>/searches', methods=['GET'])
def get_agent_searches(telefono: str):
    """
    GET /api/agents/:telefono/searches

    Obtiene solicitudes de búsqueda realizadas por un agente
    """
    db = None
    try:
        db = get_db()

        # Normalizar teléfono
        if not telefono.startswith('+'):
            telefono = '+' + telefono

        limit = int(request.args.get('limit', 20))
        offset = int(request.args.get('offset', 0))

        query = """
            SELECT
                s.id,
                s.query_original,
                s.fecha_solicitud,
                s.origen,
                s.estado,
                s.total_propiedades_encontradas,
                s.tiempo_respuesta_ms,
                s.criterios_extraidos,
                COUNT(i.id) as propiedades_seleccionadas
            FROM solicitudes_mercado s
            LEFT JOIN interacciones i ON s.id = i.solicitud_mercado_id
            WHERE s.agente_telefono = %s
            GROUP BY s.id, s.query_original, s.fecha_solicitud, s.origen,
                     s.estado, s.total_propiedades_encontradas, s.tiempo_respuesta_ms,
                     s.criterios_extraidos
            ORDER BY s.fecha_solicitud DESC
            LIMIT %s OFFSET %s
        """

        db.cursor.execute(query, (telefono, limit, offset))
        searches = db.cursor.fetchall()

        # Obtener total
        db.cursor.execute(
            "SELECT COUNT(*) as count FROM solicitudes_mercado WHERE agente_telefono = %s",
            (telefono,)
        )
        total = db.cursor.fetchone()['count']

        searches_list = []
        for search in searches:
            searches_list.append({
                'id': search['id'],
                'query': search['query_original'],
                'fecha': str(search['fecha_solicitud']) if search['fecha_solicitud'] else None,
                'origen': search['origen'],
                'estado': search['estado'],
                'resultados_encontrados': search['total_propiedades_encontradas'] or 0,
                'propiedades_seleccionadas': search['propiedades_seleccionadas'] or 0,
                'tiempo_respuesta_ms': search['tiempo_respuesta_ms'],
                'criterios': search['criterios_extraidos']
            })

        return jsonify({
            'success': True,
            'data': searches_list,
            'total': total
        }), 200

    except Exception as e:
        print(f"❌ Error en get_agent_searches: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@agents_bp.route('/<telefono>/interactions', methods=['GET'])
def get_agent_interactions(telefono: str):
    """
    GET /api/agents/:telefono/interactions

    Obtiene interacciones (matches) de un agente
    """
    db = None
    try:
        db = get_db()

        # Normalizar teléfono
        if not telefono.startswith('+'):
            telefono = '+' + telefono

        limit = int(request.args.get('limit', 20))
        offset = int(request.args.get('offset', 0))
        role = request.args.get('role', 'all')  # 'buyer', 'seller', 'all'

        # Construir query según el rol
        role_filter = ""
        if role == 'buyer':
            role_filter = "AND i.agente_comprador_telefono = %s"
        elif role == 'seller':
            role_filter = "AND i.agente_vendedor_telefono = %s"
        else:
            role_filter = "AND (i.agente_comprador_telefono = %s OR i.agente_vendedor_telefono = %s)"

        query = f"""
            SELECT
                i.id,
                i.fecha_seleccion,
                i.estado,
                i.tipo_propiedad_origen,
                i.agente_comprador_telefono,
                i.agente_vendedor_telefono,
                ac.nombre as comprador_nombre,
                av.nombre as vendedor_nombre,
                p.id as propiedad_id,
                p.codigo_propiedad as propiedad_slug,
                p.titulo as propiedad_titulo,
                p.precio as propiedad_precio,
                p.ciudad as propiedad_ciudad,
                p.imagen_principal as propiedad_imagen,
                s.query_original as solicitud_query
            FROM interacciones i
            LEFT JOIN agentes ac ON i.agente_comprador_telefono = ac.telefono
            LEFT JOIN agentes av ON i.agente_vendedor_telefono = av.telefono
            LEFT JOIN propiedades p ON i.propiedad_id = p.id
            LEFT JOIN solicitudes_mercado s ON i.solicitud_mercado_id = s.id
            WHERE i.activa = TRUE {role_filter}
            ORDER BY i.fecha_seleccion DESC
            LIMIT %s OFFSET %s
        """

        # Parámetros según el rol
        if role in ['buyer', 'seller']:
            params = (telefono, limit, offset)
        else:
            params = (telefono, telefono, limit, offset)

        db.cursor.execute(query, params)
        interactions = db.cursor.fetchall()

        # Obtener total
        if role == 'buyer':
            count_query = "SELECT COUNT(*) as count FROM interacciones WHERE agente_comprador_telefono = %s AND activa = TRUE"
            db.cursor.execute(count_query, (telefono,))
        elif role == 'seller':
            count_query = "SELECT COUNT(*) as count FROM interacciones WHERE agente_vendedor_telefono = %s AND activa = TRUE"
            db.cursor.execute(count_query, (telefono,))
        else:
            count_query = "SELECT COUNT(*) as count FROM interacciones WHERE (agente_comprador_telefono = %s OR agente_vendedor_telefono = %s) AND activa = TRUE"
            db.cursor.execute(count_query, (telefono, telefono))

        total = db.cursor.fetchone()['count']

        interactions_list = []
        for inter in interactions:
            # Determinar el rol del agente en esta interacción
            agent_role = 'buyer' if inter['agente_comprador_telefono'] == telefono else 'seller'

            interactions_list.append({
                'id': inter['id'],
                'fecha': str(inter['fecha_seleccion']) if inter['fecha_seleccion'] else None,
                'estado': inter['estado'],
                'rol': agent_role,
                'tipo_origen': inter['tipo_propiedad_origen'],
                'comprador': {
                    'telefono': inter['agente_comprador_telefono'],
                    'nombre': inter['comprador_nombre']
                },
                'vendedor': {
                    'telefono': inter['agente_vendedor_telefono'],
                    'nombre': inter['vendedor_nombre']
                },
                'propiedad': {
                    'id': inter['propiedad_id'],
                    'slug': inter['propiedad_slug'],
                    'titulo': inter['propiedad_titulo'],
                    'precio': inter['propiedad_precio'],
                    'ciudad': inter['propiedad_ciudad'],
                    'imagen': inter['propiedad_imagen']
                },
                'solicitud_query': inter['solicitud_query']
            })

        return jsonify({
            'success': True,
            'data': interactions_list,
            'total': total
        }), 200

    except Exception as e:
        print(f"❌ Error en get_agent_interactions: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@agents_bp.route('/<telefono>/activity', methods=['GET'])
def get_agent_activity(telefono: str):
    """
    GET /api/agents/:telefono/activity

    Obtiene la actividad/eventos recientes de un agente
    """
    db = None
    try:
        db = get_db()

        # Normalizar teléfono
        if not telefono.startswith('+'):
            telefono = '+' + telefono

        limit = int(request.args.get('limit', 30))

        query = """
            SELECT
                e.id,
                e.fecha_evento,
                e.tipo_evento,
                e.resultado,
                e.mensaje_error,
                e.propiedad_id,
                e.solicitud_id,
                e.interaccion_id,
                p.titulo as propiedad_titulo,
                p.codigo_propiedad as propiedad_slug
            FROM eventos_log e
            LEFT JOIN propiedades p ON e.propiedad_id = p.id
            WHERE e.agente_telefono = %s
            ORDER BY e.fecha_evento DESC
            LIMIT %s
        """

        db.cursor.execute(query, (telefono, limit))
        events = db.cursor.fetchall()

        events_list = []
        for event in events:
            events_list.append({
                'id': event['id'],
                'fecha': str(event['fecha_evento']) if event['fecha_evento'] else None,
                'tipo': event['tipo_evento'],
                'resultado': event['resultado'],
                'error': event['mensaje_error'],
                'propiedad': {
                    'id': event['propiedad_id'],
                    'titulo': event['propiedad_titulo'],
                    'slug': event['propiedad_slug']
                } if event['propiedad_id'] else None
            })

        return jsonify({
            'success': True,
            'data': events_list
        }), 200

    except Exception as e:
        print(f"❌ Error en get_agent_activity: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()
