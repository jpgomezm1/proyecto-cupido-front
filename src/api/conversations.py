#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Blueprint para Conversaciones de Búsqueda
Sistema de conversaciones persistentes tipo ChatGPT
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
import traceback
import json

from src.db.database import DatabaseManager
from src.core.search_agent import PropertySearchAgent
from src.core.search_context import merge_criteria, generate_conversation_name

conversations_bp = Blueprint('conversations', __name__, url_prefix='/api/conversations')

# Instancia del agente de búsqueda (lazy init)
_search_agent = None


def get_search_agent():
    """Obtiene o crea la instancia del agente de búsqueda"""
    global _search_agent
    if _search_agent is None:
        _search_agent = PropertySearchAgent()
    return _search_agent


@conversations_bp.route('', methods=['GET'])
def list_conversations():
    """
    Lista todas las conversaciones activas

    Query params:
    - limit: int (default 50)
    - offset: int (default 0)

    Returns:
    {
        "success": true,
        "data": [
            {
                "id": 1,
                "nombre": "Apto Laureles $500M",
                "total_mensajes": 5,
                "fecha_creacion": "2024-12-20T10:30:00",
                "fecha_actualizacion": "2024-12-20T11:45:00",
                "tiempo_relativo": "Hace 30 min"
            }
        ],
        "total": 10
    }
    """
    try:
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        with DatabaseManager() as db:
            # Obtener conversaciones activas
            query = """
                SELECT
                    id,
                    nombre,
                    total_mensajes,
                    total_propiedades_mostradas,
                    fecha_creacion,
                    fecha_actualizacion,
                    CASE
                        WHEN fecha_actualizacion > NOW() - INTERVAL '1 hour'
                            THEN 'Hace ' || EXTRACT(MINUTE FROM NOW() - fecha_actualizacion)::INTEGER || ' min'
                        WHEN fecha_actualizacion > NOW() - INTERVAL '24 hours'
                            THEN 'Hace ' || EXTRACT(HOUR FROM NOW() - fecha_actualizacion)::INTEGER || ' horas'
                        ELSE TO_CHAR(fecha_actualizacion, 'DD Mon')
                    END as tiempo_relativo
                FROM conversaciones_busqueda
                WHERE activa = TRUE
                ORDER BY fecha_actualizacion DESC
                LIMIT %s OFFSET %s
            """
            db.cursor.execute(query, (limit, offset))
            rows = db.cursor.fetchall()

            conversations = []
            for row in rows:
                if isinstance(row, dict):
                    conv = dict(row)
                else:
                    conv = {
                        'id': row[0],
                        'nombre': row[1],
                        'total_mensajes': row[2],
                        'total_propiedades_mostradas': row[3],
                        'fecha_creacion': row[4].isoformat() if row[4] else None,
                        'fecha_actualizacion': row[5].isoformat() if row[5] else None,
                        'tiempo_relativo': row[6]
                    }
                conversations.append(conv)

            # Obtener total
            db.cursor.execute(
                "SELECT COUNT(*) as count FROM conversaciones_busqueda WHERE activa = TRUE"
            )
            total = db.cursor.fetchone()['count']

            return jsonify({
                'success': True,
                'data': conversations,
                'total': total
            })

    except Exception as e:
        print(f"Error listando conversaciones: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@conversations_bp.route('', methods=['POST'])
def create_conversation():
    """
    Crea una nueva conversación

    Body JSON (opcional):
    {
        "nombre": "Mi búsqueda"
    }

    Returns:
    {
        "success": true,
        "data": {
            "id": 1,
            "nombre": "Nueva Conversación",
            "fecha_creacion": "2024-12-20T10:30:00"
        }
    }
    """
    try:
        data = request.get_json() or {}
        nombre = data.get('nombre', 'Nueva Conversación')

        with DatabaseManager() as db:
            query = """
                INSERT INTO conversaciones_busqueda (nombre)
                VALUES (%s)
                RETURNING id, nombre, fecha_creacion
            """
            db.cursor.execute(query, (nombre,))
            row = db.cursor.fetchone()
            db.conn.commit()

            if isinstance(row, dict):
                conversation = dict(row)
                if 'fecha_creacion' in conversation and conversation['fecha_creacion']:
                    conversation['fecha_creacion'] = conversation['fecha_creacion'].isoformat()
            else:
                conversation = {
                    'id': row[0],
                    'nombre': row[1],
                    'fecha_creacion': row[2].isoformat() if row[2] else None
                }

            return jsonify({
                'success': True,
                'data': conversation
            }), 201

    except Exception as e:
        print(f"Error creando conversación: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@conversations_bp.route('/<int:conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    """
    Obtiene una conversación con todos sus mensajes

    Returns:
    {
        "success": true,
        "data": {
            "id": 1,
            "nombre": "Apto Laureles $500M",
            "criterios_acumulados": {...},
            "mensajes": [
                {
                    "id": 1,
                    "role": "user",
                    "content": "Busco apartamento...",
                    "fecha_creacion": "2024-12-20T10:30:00"
                },
                {
                    "id": 2,
                    "role": "assistant",
                    "content": "Encontré 5 propiedades...",
                    "search_response": {...},
                    "fecha_creacion": "2024-12-20T10:30:05"
                }
            ]
        }
    }
    """
    try:
        with DatabaseManager() as db:
            # Obtener conversación
            query_conv = """
                SELECT id, nombre, criterios_acumulados, total_mensajes,
                       fecha_creacion, fecha_actualizacion
                FROM conversaciones_busqueda
                WHERE id = %s AND activa = TRUE
            """
            db.cursor.execute(query_conv, (conversation_id,))
            conv_row = db.cursor.fetchone()

            if not conv_row:
                return jsonify({
                    'success': False,
                    'error': 'Conversación no encontrada'
                }), 404

            if isinstance(conv_row, dict):
                conversation = dict(conv_row)
                if 'fecha_creacion' in conversation and conversation['fecha_creacion']:
                    conversation['fecha_creacion'] = conversation['fecha_creacion'].isoformat()
                if 'fecha_actualizacion' in conversation and conversation['fecha_actualizacion']:
                    conversation['fecha_actualizacion'] = conversation['fecha_actualizacion'].isoformat()
            else:
                conversation = {
                    'id': conv_row[0],
                    'nombre': conv_row[1],
                    'criterios_acumulados': conv_row[2] or {},
                    'total_mensajes': conv_row[3],
                    'fecha_creacion': conv_row[4].isoformat() if conv_row[4] else None,
                    'fecha_actualizacion': conv_row[5].isoformat() if conv_row[5] else None
                }

            # Obtener mensajes
            query_msgs = """
                SELECT id, role, content, criterios_mensaje, criterios_acumulados,
                       propiedades_ids, total_resultados, tiempo_respuesta_ms,
                       search_response, fecha_creacion
                FROM mensajes_conversacion
                WHERE conversacion_id = %s
                ORDER BY fecha_creacion ASC
            """
            db.cursor.execute(query_msgs, (conversation_id,))
            msg_rows = db.cursor.fetchall()

            mensajes = []
            for row in msg_rows:
                if isinstance(row, dict):
                    msg = dict(row)
                    if 'fecha_creacion' in msg and msg['fecha_creacion']:
                        msg['fecha_creacion'] = msg['fecha_creacion'].isoformat()
                else:
                    msg = {
                        'id': row[0],
                        'role': row[1],
                        'content': row[2],
                        'criterios_mensaje': row[3],
                        'criterios_acumulados': row[4],
                        'propiedades_ids': row[5],
                        'total_resultados': row[6],
                        'tiempo_respuesta_ms': row[7],
                        'search_response': row[8],
                        'fecha_creacion': row[9].isoformat() if row[9] else None
                    }
                mensajes.append(msg)

            conversation['mensajes'] = mensajes

            return jsonify({
                'success': True,
                'data': conversation
            })

    except Exception as e:
        print(f"Error obteniendo conversación: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@conversations_bp.route('/<int:conversation_id>', methods=['PUT'])
def update_conversation(conversation_id):
    """
    Actualiza el nombre de una conversación

    Body JSON:
    {
        "nombre": "Nuevo nombre"
    }
    """
    try:
        data = request.get_json()
        if not data or 'nombre' not in data:
            return jsonify({
                'success': False,
                'error': 'Se requiere el campo "nombre"'
            }), 400

        nombre = data['nombre'].strip()
        if not nombre:
            return jsonify({
                'success': False,
                'error': 'El nombre no puede estar vacío'
            }), 400

        with DatabaseManager() as db:
            query = """
                UPDATE conversaciones_busqueda
                SET nombre = %s, fecha_actualizacion = NOW()
                WHERE id = %s AND activa = TRUE
                RETURNING id, nombre
            """
            db.cursor.execute(query, (nombre, conversation_id))
            row = db.cursor.fetchone()
            db.conn.commit()

            if not row:
                return jsonify({
                    'success': False,
                    'error': 'Conversación no encontrada'
                }), 404

            return jsonify({
                'success': True,
                'data': {
                    'id': row[0] if not isinstance(row, dict) else row['id'],
                    'nombre': row[1] if not isinstance(row, dict) else row['nombre']
                }
            })

    except Exception as e:
        print(f"Error actualizando conversación: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@conversations_bp.route('/<int:conversation_id>', methods=['DELETE'])
def delete_conversation(conversation_id):
    """
    Elimina una conversación (soft delete)
    """
    try:
        with DatabaseManager() as db:
            query = """
                UPDATE conversaciones_busqueda
                SET activa = FALSE, fecha_actualizacion = NOW()
                WHERE id = %s AND activa = TRUE
                RETURNING id
            """
            db.cursor.execute(query, (conversation_id,))
            row = db.cursor.fetchone()
            db.conn.commit()

            if not row:
                return jsonify({
                    'success': False,
                    'error': 'Conversación no encontrada'
                }), 404

            return jsonify({
                'success': True,
                'message': 'Conversación eliminada'
            })

    except Exception as e:
        print(f"Error eliminando conversación: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@conversations_bp.route('/<int:conversation_id>/messages', methods=['POST'])
def send_message(conversation_id):
    """
    Envía un mensaje a la conversación y ejecuta búsqueda con contexto

    Body JSON:
    {
        "content": "Busco apartamento en Laureles..."
    }

    Returns:
    {
        "success": true,
        "data": {
            "user_message": {...},
            "assistant_message": {...}
        }
    }
    """
    try:
        data = request.get_json()
        if not data or 'content' not in data:
            return jsonify({
                'success': False,
                'error': 'Se requiere el campo "content"'
            }), 400

        content = data['content'].strip()
        if not content:
            return jsonify({
                'success': False,
                'error': 'El mensaje no puede estar vacío'
            }), 400

        with DatabaseManager() as db:
            # Verificar que la conversación existe y obtener criterios acumulados
            db.cursor.execute(
                """SELECT id, nombre, criterios_acumulados, total_mensajes
                   FROM conversaciones_busqueda
                   WHERE id = %s AND activa = TRUE""",
                (conversation_id,)
            )
            conv_row = db.cursor.fetchone()

            if not conv_row:
                return jsonify({
                    'success': False,
                    'error': 'Conversación no encontrada'
                }), 404

            if isinstance(conv_row, dict):
                prev_criteria = conv_row.get('criterios_acumulados') or {}
                conv_nombre = conv_row.get('nombre', 'Nueva Conversación')
                total_mensajes = conv_row.get('total_mensajes', 0)
            else:
                prev_criteria = conv_row[2] or {}
                conv_nombre = conv_row[1]
                total_mensajes = conv_row[3] or 0

            # Guardar mensaje del usuario
            db.cursor.execute(
                """INSERT INTO mensajes_conversacion
                   (conversacion_id, role, content)
                   VALUES (%s, 'user', %s)
                   RETURNING id, fecha_creacion""",
                (conversation_id, content)
            )
            user_msg_row = db.cursor.fetchone()

            if isinstance(user_msg_row, dict):
                user_message = {
                    'id': user_msg_row['id'],
                    'role': 'user',
                    'content': content,
                    'fecha_creacion': user_msg_row['fecha_creacion'].isoformat()
                }
            else:
                user_message = {
                    'id': user_msg_row[0],
                    'role': 'user',
                    'content': content,
                    'fecha_creacion': user_msg_row[1].isoformat() if user_msg_row[1] else None
                }

            # Ejecutar búsqueda
            agent = get_search_agent()
            start_time = datetime.now()

            # Si hay criterios previos, enriquecer el query con contexto
            search_query = content
            if prev_criteria and total_mensajes > 0:
                # Añadir contexto de criterios anteriores al query
                context_parts = []
                if prev_criteria.get('ubicaciones'):
                    context_parts.append(f"zona: {', '.join(prev_criteria['ubicaciones'])}")
                if prev_criteria.get('tipo_propiedad'):
                    context_parts.append(f"tipo: {prev_criteria['tipo_propiedad']}")
                if prev_criteria.get('precio_max'):
                    context_parts.append(f"precio máximo: {prev_criteria['precio_max']}")
                if prev_criteria.get('habitaciones_min'):
                    context_parts.append(f"habitaciones: {prev_criteria['habitaciones_min']}+")

                if context_parts:
                    search_query = f"(Contexto anterior: {', '.join(context_parts)}) {content}"

            search_response = agent.search(
                search_query,
                limit=10,
                sender='web'
            )

            elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # Obtener nuevos criterios
            new_criteria = search_response.get('criteria', {})

            # Merge de criterios acumulados
            accumulated_criteria = merge_criteria(prev_criteria, new_criteria, content)

            # Preparar respuesta del asistente
            results = search_response.get('results', [])
            total_found = search_response.get('total_found', 0)

            if total_found > 0:
                assistant_content = f"Encontré {total_found} propiedades que coinciden con tu búsqueda."
            else:
                assistant_content = "No encontré propiedades que coincidan exactamente. Intenta con criterios más amplios."

            # Enriquecer resultados con imágenes (con manejo de errores)
            try:
                results = enrich_results_with_images(results, db)
            except Exception as img_error:
                print(f"⚠️ Error enriqueciendo imágenes: {img_error}")
                # Rollback para limpiar la transacción fallida
                try:
                    db.conn.rollback()
                except:
                    pass

            # Guardar mensaje del asistente
            search_response_json = json.dumps({
                'criteria': accumulated_criteria,
                'results': results,
                'total_found': total_found,
                'elapsed_ms': elapsed_ms
            }, default=str)

            propiedades_ids = [r.get('id') for r in results if r.get('id')]

            db.cursor.execute(
                """INSERT INTO mensajes_conversacion
                   (conversacion_id, role, content, criterios_mensaje,
                    criterios_acumulados, propiedades_ids, total_resultados,
                    tiempo_respuesta_ms, search_response)
                   VALUES (%s, 'assistant', %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, fecha_creacion""",
                (conversation_id, assistant_content, json.dumps(new_criteria),
                 json.dumps(accumulated_criteria), propiedades_ids,
                 total_found, elapsed_ms, search_response_json)
            )
            asst_msg_row = db.cursor.fetchone()

            if isinstance(asst_msg_row, dict):
                assistant_message = {
                    'id': asst_msg_row['id'],
                    'role': 'assistant',
                    'content': assistant_content,
                    'criterios_acumulados': accumulated_criteria,
                    'total_resultados': total_found,
                    'tiempo_respuesta_ms': elapsed_ms,
                    'fecha_creacion': asst_msg_row['fecha_creacion'].isoformat(),
                    'search_response': {
                        'criteria': accumulated_criteria,
                        'results': results,
                        'total_found': total_found,
                        'elapsed_ms': elapsed_ms
                    }
                }
            else:
                assistant_message = {
                    'id': asst_msg_row[0],
                    'role': 'assistant',
                    'content': assistant_content,
                    'criterios_acumulados': accumulated_criteria,
                    'total_resultados': total_found,
                    'tiempo_respuesta_ms': elapsed_ms,
                    'fecha_creacion': asst_msg_row[1].isoformat() if asst_msg_row[1] else None,
                    'search_response': {
                        'criteria': accumulated_criteria,
                        'results': results,
                        'total_found': total_found,
                        'elapsed_ms': elapsed_ms
                    }
                }

            # Auto-nombrar conversación si es el primer mensaje
            if total_mensajes == 0 and conv_nombre == 'Nueva Conversación' and accumulated_criteria:
                new_name = generate_conversation_name(accumulated_criteria)
                if new_name:
                    db.cursor.execute(
                        "UPDATE conversaciones_busqueda SET nombre = %s WHERE id = %s",
                        (new_name, conversation_id)
                    )

            db.conn.commit()

            return jsonify({
                'success': True,
                'data': {
                    'user_message': user_message,
                    'assistant_message': assistant_message
                }
            })

    except Exception as e:
        print(f"Error enviando mensaje: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def enrich_results_with_images(results, db):
    """Enriquece los resultados con imágenes de portada"""
    if not results:
        return results

    # Usar imagen_principal que ya viene del search
    for result in results:
        if not result.get('cover_image_url'):
            result['cover_image_url'] = result.get('imagen_principal')

    # Intentar obtener imágenes adicionales de property_images (si existe la tabla)
    try:
        property_ids = [r.get('id') for r in results if r.get('id')]
        if not property_ids:
            return results

        # Verificar si la tabla existe antes de consultar
        db.cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'property_images'
            )
        """)
        table_exists = db.cursor.fetchone()
        if isinstance(table_exists, dict):
            table_exists = table_exists.get('exists', False)
        else:
            table_exists = table_exists[0] if table_exists else False

        if not table_exists:
            return results

        placeholders = ','.join(['%s'] * len(property_ids))
        query = f"""
            SELECT property_id, url
            FROM property_images
            WHERE property_id IN ({placeholders})
            AND is_cover = TRUE
        """
        db.cursor.execute(query, property_ids)
        rows = db.cursor.fetchall()

        cover_map = {}
        for row in rows:
            if isinstance(row, dict):
                cover_map[row['property_id']] = row['url']
            else:
                cover_map[row[0]] = row[1]

        for result in results:
            prop_id = result.get('id')
            if prop_id in cover_map:
                result['cover_image_url'] = cover_map[prop_id]

    except Exception as e:
        print(f"Error obteniendo imágenes: {e}")
        for result in results:
            if not result.get('cover_image_url'):
                result['cover_image_url'] = result.get('imagen_principal')

    return results
