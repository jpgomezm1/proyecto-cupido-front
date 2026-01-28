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
from src.api.chat_auth import require_chat_auth, get_current_user

# v2.4: Nuevos módulos para sistema de fases
from src.core.search_state import (
    SearchPhase,
    build_priority_options,
    parse_priority_response,
    apply_priority_weights,
    create_search_state,
    should_ask_priority,
    format_priority_question
)
from src.core.area_validator import (
    validate_area_vs_type,
    apply_area_correction,
    parse_area_validation_response,
    format_area_validation_question
)

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
@require_chat_auth
def list_conversations():
    """
    Lista todas las conversaciones activas del usuario autenticado

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
        user_id = request.chat_user['id']

        with DatabaseManager() as db:
            # Obtener conversaciones activas del usuario
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
                WHERE activa = TRUE AND user_id = %s
                ORDER BY fecha_actualizacion DESC
                LIMIT %s OFFSET %s
            """
            db.cursor.execute(query, (user_id, limit, offset))
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

            # Obtener total del usuario
            db.cursor.execute(
                "SELECT COUNT(*) as count FROM conversaciones_busqueda WHERE activa = TRUE AND user_id = %s",
                (user_id,)
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
@require_chat_auth
def create_conversation():
    """
    Crea una nueva conversación para el usuario autenticado

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
        user_id = request.chat_user['id']

        with DatabaseManager() as db:
            query = """
                INSERT INTO conversaciones_busqueda (nombre, user_id)
                VALUES (%s, %s)
                RETURNING id, nombre, fecha_creacion
            """
            db.cursor.execute(query, (nombre, user_id))
            row = db.cursor.fetchone()

            # Registrar en log de uso
            db.cursor.execute(
                """INSERT INTO chat_usage_log (user_id, accion, conversacion_id, detalles)
                   VALUES (%s, 'conversation_create', %s, '{}')""",
                (user_id, row['id'] if isinstance(row, dict) else row[0])
            )

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
@require_chat_auth
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
        user_id = request.chat_user['id']

        with DatabaseManager() as db:
            # Obtener conversación (solo si pertenece al usuario)
            query_conv = """
                SELECT id, nombre, criterios_acumulados, total_mensajes,
                       fecha_creacion, fecha_actualizacion
                FROM conversaciones_busqueda
                WHERE id = %s AND activa = TRUE AND user_id = %s
            """
            db.cursor.execute(query_conv, (conversation_id, user_id))
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
                    # v2.4: Extract options from search_response for interactive messages
                    if msg.get('search_response'):
                        sr = msg['search_response']
                        if isinstance(sr, str):
                            sr = json.loads(sr)
                        if sr.get('options'):
                            msg['options'] = sr['options']
                        if sr.get('awaiting_response'):
                            msg['awaiting_response'] = sr['awaiting_response']
                        if sr.get('response_type'):
                            msg['response_type'] = sr['response_type']
                else:
                    search_response = row[8]
                    msg = {
                        'id': row[0],
                        'role': row[1],
                        'content': row[2],
                        'criterios_mensaje': row[3],
                        'criterios_acumulados': row[4],
                        'propiedades_ids': row[5],
                        'total_resultados': row[6],
                        'tiempo_respuesta_ms': row[7],
                        'search_response': search_response,
                        'fecha_creacion': row[9].isoformat() if row[9] else None
                    }
                    # v2.4: Extract options from search_response for interactive messages
                    if search_response:
                        sr = search_response
                        if isinstance(sr, str):
                            sr = json.loads(sr)
                        if sr.get('options'):
                            msg['options'] = sr['options']
                        if sr.get('awaiting_response'):
                            msg['awaiting_response'] = sr['awaiting_response']
                        if sr.get('response_type'):
                            msg['response_type'] = sr['response_type']
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


@conversations_bp.route('/public/<int:conversation_id>', methods=['GET'])
def get_public_conversation(conversation_id):
    """
    Obtiene una conversación para vista pública (sin autenticación)
    Solo lectura - para compartir links

    Returns:
    {
        "success": true,
        "data": {
            "id": 1,
            "nombre": "Apto Laureles $500M",
            "criterios_acumulados": {...},
            "total_mensajes": 5,
            "mensajes": [...]
        }
    }
    """
    try:
        with DatabaseManager() as db:
            # Obtener conversación (incluyendo inactivas para links compartidos)
            query_conv = """
                SELECT id, nombre, criterios_acumulados, total_mensajes,
                       fecha_creacion, fecha_actualizacion, user_id
                FROM conversaciones_busqueda
                WHERE id = %s
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
                    'fecha_actualizacion': conv_row[5].isoformat() if conv_row[5] else None,
                    'user_id': conv_row[6]
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
                    # v2.4: Extract options from search_response for interactive messages
                    if msg.get('search_response'):
                        sr = msg['search_response']
                        if isinstance(sr, str):
                            sr = json.loads(sr)
                        if sr.get('options'):
                            msg['options'] = sr['options']
                        if sr.get('awaiting_response'):
                            msg['awaiting_response'] = sr['awaiting_response']
                        if sr.get('response_type'):
                            msg['response_type'] = sr['response_type']
                else:
                    search_response = row[8]
                    msg = {
                        'id': row[0],
                        'role': row[1],
                        'content': row[2],
                        'criterios_mensaje': row[3],
                        'criterios_acumulados': row[4],
                        'propiedades_ids': row[5],
                        'total_resultados': row[6],
                        'tiempo_respuesta_ms': row[7],
                        'search_response': search_response,
                        'fecha_creacion': row[9].isoformat() if row[9] else None
                    }
                    # v2.4: Extract options from search_response for interactive messages
                    if search_response:
                        sr = search_response
                        if isinstance(sr, str):
                            sr = json.loads(sr)
                        if sr.get('options'):
                            msg['options'] = sr['options']
                        if sr.get('awaiting_response'):
                            msg['awaiting_response'] = sr['awaiting_response']
                        if sr.get('response_type'):
                            msg['response_type'] = sr['response_type']
                mensajes.append(msg)

            conversation['mensajes'] = mensajes

            return jsonify({
                'success': True,
                'data': conversation
            })

    except Exception as e:
        print(f"Error obteniendo conversación pública: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@conversations_bp.route('/<int:conversation_id>', methods=['PUT'])
@require_chat_auth
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

        user_id = request.chat_user['id']

        with DatabaseManager() as db:
            query = """
                UPDATE conversaciones_busqueda
                SET nombre = %s, fecha_actualizacion = NOW()
                WHERE id = %s AND activa = TRUE AND user_id = %s
                RETURNING id, nombre
            """
            db.cursor.execute(query, (nombre, conversation_id, user_id))
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
@require_chat_auth
def delete_conversation(conversation_id):
    """
    Elimina una conversación (soft delete)
    """
    try:
        user_id = request.chat_user['id']

        with DatabaseManager() as db:
            query = """
                UPDATE conversaciones_busqueda
                SET activa = FALSE, fecha_actualizacion = NOW()
                WHERE id = %s AND activa = TRUE AND user_id = %s
                RETURNING id
            """
            db.cursor.execute(query, (conversation_id, user_id))
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
@require_chat_auth
def send_message(conversation_id):
    """
    Envía un mensaje a la conversación y ejecuta búsqueda con contexto

    v2.4: Sistema de fases para preguntar prioridad y validar área

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

        user_id = request.chat_user['id']

        with DatabaseManager() as db:
            # Verificar que la conversación existe y pertenece al usuario
            db.cursor.execute(
                """SELECT id, nombre, criterios_acumulados, total_mensajes
                   FROM conversaciones_busqueda
                   WHERE id = %s AND activa = TRUE AND user_id = %s""",
                (conversation_id, user_id)
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

            # =================================================================
            # v2.4: SISTEMA DE FASES
            # =================================================================
            search_state = prev_criteria.get('search_state', {})
            phase = search_state.get('phase', 'initial')

            print(f"📊 Fase actual: {phase}")

            # -----------------------------------------------------------------
            # FASE: Esperando respuesta de prioridad
            # -----------------------------------------------------------------
            if phase == SearchPhase.AWAITING_PRIORITY.value:
                print(f"🎯 Procesando selección de prioridad: {content}")
                pending_options = search_state.get('pending_options', [])
                selected_priority = parse_priority_response(content, pending_options)

                if selected_priority:
                    # Aplicar pesos de prioridad
                    prev_criteria = apply_priority_weights(prev_criteria, selected_priority)
                    print(f"✅ Prioridad aplicada: {selected_priority}")

                    # Verificar validación de área
                    area_validation = validate_area_vs_type(prev_criteria)
                    if area_validation:
                        # Pedir validación de área
                        return _handle_area_validation_request(
                            db, conversation_id, user_id, user_message,
                            prev_criteria, area_validation, conv_nombre, total_mensajes
                        )

                    # Ejecutar búsqueda
                    return _execute_search_and_respond(
                        db, conversation_id, user_id, user_message,
                        prev_criteria, conv_nombre, total_mensajes, content
                    )
                else:
                    # No se entendió la respuesta, pedir de nuevo
                    return _handle_priority_retry(
                        db, conversation_id, user_message, pending_options
                    )

            # -----------------------------------------------------------------
            # FASE: Esperando respuesta de validación de área
            # -----------------------------------------------------------------
            elif phase == SearchPhase.AWAITING_AREA_VALIDATION.value:
                print(f"📐 Procesando selección de área: {content}")
                pending_options = search_state.get('pending_options', [])
                selected_option = parse_area_validation_response(content, pending_options)

                if selected_option:
                    # Aplicar corrección de área
                    prev_criteria = apply_area_correction(prev_criteria, selected_option)
                    print(f"✅ Corrección de área aplicada: {selected_option.get('action')}")

                    # Ejecutar búsqueda
                    return _execute_search_and_respond(
                        db, conversation_id, user_id, user_message,
                        prev_criteria, conv_nombre, total_mensajes, content
                    )
                else:
                    # No se entendió, usar opción por defecto (keep_original)
                    prev_criteria['search_state']['phase'] = SearchPhase.READY_TO_SEARCH.value
                    return _execute_search_and_respond(
                        db, conversation_id, user_id, user_message,
                        prev_criteria, conv_nombre, total_mensajes, content
                    )

            # -----------------------------------------------------------------
            # FASE: Mensaje inicial o listo para buscar
            # -----------------------------------------------------------------
            else:
                # Extraer criterios del mensaje actual
                agent = get_search_agent()
                start_time = datetime.now()

                # Extraer criterios SIN ejecutar búsqueda completa
                new_criteria = agent._extract_search_criteria(
                    content,
                    prev_criteria if total_mensajes > 0 else None
                )

                elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                # Merge de criterios
                accumulated_criteria = merge_criteria(prev_criteria, new_criteria, content)
                accumulated_criteria['original_query'] = content

                # Verificar si debemos preguntar por prioridad
                if should_ask_priority(accumulated_criteria):
                    priority_options = build_priority_options(accumulated_criteria)

                    if len(priority_options) > 1:  # Más que solo "Confío en Findy"
                        return _handle_priority_request(
                            db, conversation_id, user_id, user_message,
                            accumulated_criteria, priority_options, conv_nombre, total_mensajes
                        )

                # No hay suficientes criterios para preguntar prioridad
                # Verificar validación de área directamente
                area_validation = validate_area_vs_type(accumulated_criteria)
                if area_validation:
                    return _handle_area_validation_request(
                        db, conversation_id, user_id, user_message,
                        accumulated_criteria, area_validation, conv_nombre, total_mensajes
                    )

                # Ejecutar búsqueda directamente
                return _execute_search_and_respond(
                    db, conversation_id, user_id, user_message,
                    accumulated_criteria, conv_nombre, total_mensajes, content
                )

    except Exception as e:
        print(f"Error enviando mensaje: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def _handle_priority_request(db, conversation_id, user_id, user_message,
                              criteria, priority_options, conv_nombre, total_mensajes):
    """
    Maneja la solicitud de prioridad al usuario

    v2.4: Pregunta qué criterio es más importante antes de buscar
    """
    # Guardar estado de búsqueda en criterios
    criteria['search_state'] = create_search_state(
        phase=SearchPhase.AWAITING_PRIORITY,
        options=priority_options,
        original_query=criteria.get('original_query', '')
    )

    # Formatear pregunta
    assistant_content = format_priority_question(priority_options)

    # Guardar mensaje del asistente con opciones
    search_response_json = json.dumps({
        'criteria': criteria,
        'results': [],
        'total_found': 0,
        'awaiting_response': True,
        'response_type': 'priority_selection',
        'options': [opt.to_dict() for opt in priority_options]
    }, default=str)

    db.cursor.execute(
        """INSERT INTO mensajes_conversacion
           (conversacion_id, role, content, criterios_mensaje,
            criterios_acumulados, propiedades_ids, total_resultados,
            tiempo_respuesta_ms, search_response)
           VALUES (%s, 'assistant', %s, %s, %s, %s, %s, %s, %s)
           RETURNING id, fecha_creacion""",
        (conversation_id, assistant_content, json.dumps({}),
         json.dumps(criteria), [], 0, 0, search_response_json)
    )
    asst_msg_row = db.cursor.fetchone()

    # Actualizar criterios acumulados en la conversación
    db.cursor.execute(
        """UPDATE conversaciones_busqueda
           SET criterios_acumulados = %s, fecha_actualizacion = NOW()
           WHERE id = %s""",
        (json.dumps(criteria), conversation_id)
    )

    # Auto-nombrar conversación si es el primer mensaje
    if total_mensajes == 0 and conv_nombre == 'Nueva Conversación' and criteria:
        new_name = generate_conversation_name(criteria)
        if new_name:
            db.cursor.execute(
                "UPDATE conversaciones_busqueda SET nombre = %s WHERE id = %s",
                (new_name, conversation_id)
            )

    db.conn.commit()

    if isinstance(asst_msg_row, dict):
        assistant_message = {
            'id': asst_msg_row['id'],
            'role': 'assistant',
            'content': assistant_content,
            'criterios_acumulados': criteria,
            'total_resultados': 0,
            'tiempo_respuesta_ms': 0,
            'fecha_creacion': asst_msg_row['fecha_creacion'].isoformat(),
            'options': [opt.to_dict() for opt in priority_options],
            'awaiting_response': True,
            'response_type': 'priority_selection',
            'search_response': {
                'criteria': criteria,
                'results': [],
                'total_found': 0,
                'options': [opt.to_dict() for opt in priority_options],
                'awaiting_response': True,
                'response_type': 'priority_selection'
            }
        }
    else:
        assistant_message = {
            'id': asst_msg_row[0],
            'role': 'assistant',
            'content': assistant_content,
            'criterios_acumulados': criteria,
            'total_resultados': 0,
            'tiempo_respuesta_ms': 0,
            'fecha_creacion': asst_msg_row[1].isoformat() if asst_msg_row[1] else None,
            'options': [opt.to_dict() for opt in priority_options],
            'awaiting_response': True,
            'response_type': 'priority_selection',
            'search_response': {
                'criteria': criteria,
                'results': [],
                'total_found': 0,
                'options': [opt.to_dict() for opt in priority_options],
                'awaiting_response': True,
                'response_type': 'priority_selection'
            }
        }

    return jsonify({
        'success': True,
        'data': {
            'user_message': user_message,
            'assistant_message': assistant_message
        }
    })


def _handle_area_validation_request(db, conversation_id, user_id, user_message,
                                     criteria, area_validation, conv_nombre, total_mensajes):
    """
    Maneja la solicitud de validación de área al usuario

    v2.4: Pregunta si el área es correcta para el tipo de propiedad
    """
    # Guardar estado de búsqueda en criterios
    criteria['search_state'] = create_search_state(
        phase=SearchPhase.AWAITING_AREA_VALIDATION,
        options=area_validation['options'],
        original_query=criteria.get('original_query', ''),
        validation_message=area_validation['message']
    )

    # Formatear pregunta
    assistant_content = format_area_validation_question(area_validation)

    # Guardar mensaje del asistente con opciones
    search_response_json = json.dumps({
        'criteria': criteria,
        'results': [],
        'total_found': 0,
        'awaiting_response': True,
        'response_type': 'area_validation',
        'options': area_validation['options']
    }, default=str)

    db.cursor.execute(
        """INSERT INTO mensajes_conversacion
           (conversacion_id, role, content, criterios_mensaje,
            criterios_acumulados, propiedades_ids, total_resultados,
            tiempo_respuesta_ms, search_response)
           VALUES (%s, 'assistant', %s, %s, %s, %s, %s, %s, %s)
           RETURNING id, fecha_creacion""",
        (conversation_id, assistant_content, json.dumps({}),
         json.dumps(criteria), [], 0, 0, search_response_json)
    )
    asst_msg_row = db.cursor.fetchone()

    # Actualizar criterios acumulados en la conversación
    db.cursor.execute(
        """UPDATE conversaciones_busqueda
           SET criterios_acumulados = %s, fecha_actualizacion = NOW()
           WHERE id = %s""",
        (json.dumps(criteria), conversation_id)
    )

    db.conn.commit()

    if isinstance(asst_msg_row, dict):
        assistant_message = {
            'id': asst_msg_row['id'],
            'role': 'assistant',
            'content': assistant_content,
            'criterios_acumulados': criteria,
            'total_resultados': 0,
            'tiempo_respuesta_ms': 0,
            'fecha_creacion': asst_msg_row['fecha_creacion'].isoformat(),
            'options': area_validation['options'],
            'awaiting_response': True,
            'response_type': 'area_validation',
            'search_response': {
                'criteria': criteria,
                'results': [],
                'total_found': 0,
                'options': area_validation['options'],
                'awaiting_response': True,
                'response_type': 'area_validation'
            }
        }
    else:
        assistant_message = {
            'id': asst_msg_row[0],
            'role': 'assistant',
            'content': assistant_content,
            'criterios_acumulados': criteria,
            'total_resultados': 0,
            'tiempo_respuesta_ms': 0,
            'fecha_creacion': asst_msg_row[1].isoformat() if asst_msg_row[1] else None,
            'options': area_validation['options'],
            'awaiting_response': True,
            'response_type': 'area_validation',
            'search_response': {
                'criteria': criteria,
                'results': [],
                'total_found': 0,
                'options': area_validation['options'],
                'awaiting_response': True,
                'response_type': 'area_validation'
            }
        }

    return jsonify({
        'success': True,
        'data': {
            'user_message': user_message,
            'assistant_message': assistant_message
        }
    })


def _handle_priority_retry(db, conversation_id, user_message, pending_options):
    """
    Maneja el caso donde no se entendió la respuesta de prioridad
    """
    assistant_content = "No entendí tu respuesta. Por favor selecciona una opción:\n\n"
    for opt in pending_options:
        assistant_content += f"{opt.get('emoji', '')} {opt.get('label', '')}\n"

    # Guardar mensaje simple sin modificar el estado
    db.cursor.execute(
        """INSERT INTO mensajes_conversacion
           (conversacion_id, role, content)
           VALUES (%s, 'assistant', %s)
           RETURNING id, fecha_creacion""",
        (conversation_id, assistant_content)
    )
    asst_msg_row = db.cursor.fetchone()
    db.conn.commit()

    if isinstance(asst_msg_row, dict):
        assistant_message = {
            'id': asst_msg_row['id'],
            'role': 'assistant',
            'content': assistant_content,
            'fecha_creacion': asst_msg_row['fecha_creacion'].isoformat(),
            'options': pending_options,
            'awaiting_response': True,
            'response_type': 'priority_selection'
        }
    else:
        assistant_message = {
            'id': asst_msg_row[0],
            'role': 'assistant',
            'content': assistant_content,
            'fecha_creacion': asst_msg_row[1].isoformat() if asst_msg_row[1] else None,
            'options': pending_options,
            'awaiting_response': True,
            'response_type': 'priority_selection'
        }

    return jsonify({
        'success': True,
        'data': {
            'user_message': user_message,
            'assistant_message': assistant_message
        }
    })


def _execute_search_and_respond(db, conversation_id, user_id, user_message,
                                 criteria, conv_nombre, total_mensajes, original_content):
    """
    Ejecuta la búsqueda y devuelve los resultados

    v2.4: Función auxiliar para ejecutar búsqueda con criterios ya procesados
    """
    agent = get_search_agent()
    start_time = datetime.now()

    # Limpiar estado de búsqueda antes de ejecutar
    if 'search_state' in criteria:
        criteria['search_state']['phase'] = SearchPhase.READY_TO_SEARCH.value

    # Usar el query original guardado o el contenido actual
    query = criteria.get('original_query', original_content)

    # Ejecutar búsqueda con criterios ya procesados
    search_response = agent.search(
        query,
        limit=10,
        sender='web',
        previous_criteria=criteria  # Pasar criterios con prioridad aplicada
    )

    elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)

    # Obtener resultados
    results = search_response.get('results', [])
    total_found = search_response.get('total_found', 0)

    # Actualizar criterios con los de la búsqueda
    search_criteria = search_response.get('criteria', {})
    accumulated_criteria = merge_criteria(criteria, search_criteria, original_content)

    # Limpiar search_state del resultado final
    if 'search_state' in accumulated_criteria:
        accumulated_criteria['search_state']['phase'] = SearchPhase.READY_TO_SEARCH.value

    if total_found > 0:
        priority_msg = ""
        if criteria.get('selected_priority') and criteria['selected_priority'] != 'balanced':
            priority_labels = {
                'zona': 'zona',
                'precio': 'precio',
                'habitaciones': 'habitaciones'
            }
            priority_msg = f" (priorizando {priority_labels.get(criteria['selected_priority'], '')})"
        assistant_content = f"Encontré {total_found} propiedades que coinciden con tu búsqueda{priority_msg}."
    else:
        assistant_content = "No encontré propiedades que coincidan exactamente. Intenta con criterios más amplios."

    # Enriquecer resultados con imágenes
    try:
        results = enrich_results_with_images(results, db)
    except Exception as img_error:
        print(f"⚠️ Error enriqueciendo imágenes: {img_error}")
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
        (conversation_id, assistant_content, json.dumps(search_criteria),
         json.dumps(accumulated_criteria), propiedades_ids,
         total_found, elapsed_ms, search_response_json)
    )
    asst_msg_row = db.cursor.fetchone()

    # Actualizar criterios acumulados en la conversación
    db.cursor.execute(
        """UPDATE conversaciones_busqueda
           SET criterios_acumulados = %s, fecha_actualizacion = NOW()
           WHERE id = %s""",
        (json.dumps(accumulated_criteria), conversation_id)
    )

    # Auto-nombrar conversación si es el primer mensaje
    if total_mensajes == 0 and conv_nombre == 'Nueva Conversación' and accumulated_criteria:
        new_name = generate_conversation_name(accumulated_criteria)
        if new_name:
            db.cursor.execute(
                "UPDATE conversaciones_busqueda SET nombre = %s WHERE id = %s",
                (new_name, conversation_id)
            )

    # Registrar búsqueda en log de uso
    search_details = json.dumps({
        'query': original_content[:100],
        'results_count': total_found,
        'criteria': list(accumulated_criteria.keys()) if accumulated_criteria else [],
        'priority': criteria.get('selected_priority', 'none')
    })
    db.cursor.execute(
        """INSERT INTO chat_usage_log (user_id, accion, conversacion_id, detalles)
           VALUES (%s, 'search', %s, %s)""",
        (user_id, conversation_id, search_details)
    )

    # Actualizar total_busquedas del usuario
    db.cursor.execute(
        "UPDATE chat_users SET total_busquedas = total_busquedas + 1 WHERE id = %s",
        (user_id,)
    )

    db.conn.commit()

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

    return jsonify({
        'success': True,
        'data': {
            'user_message': user_message,
            'assistant_message': assistant_message
        }
    })


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
