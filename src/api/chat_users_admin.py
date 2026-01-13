#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Blueprint para Administración de Usuarios de Chat
CRUD completo para gestionar accesos al chat compartible
"""

from flask import Blueprint, request, jsonify
import secrets
import string
import traceback

from src.db.database import DatabaseManager
from src.api.auth import token_required

chat_users_admin_bp = Blueprint('chat_users_admin', __name__, url_prefix='/api/admin/chat-users')


def generate_password(length=12):
    """Genera una contraseña segura aleatoria"""
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# ============================================================================
# CRUD DE USUARIOS
# ============================================================================

@chat_users_admin_bp.route('', methods=['GET'])
@token_required
def list_users():
    """
    Lista todos los usuarios de chat con sus estadísticas

    Query params:
        - activo: true/false para filtrar por estado
        - limit: número máximo de resultados
        - offset: para paginación

    Returns:
        {
            "success": true,
            "data": {
                "users": [...],
                "total": 10,
                "stats": {
                    "total": 10,
                    "activos": 8,
                    "sesiones_activas": 5
                }
            }
        }
    """
    try:
        activo = request.args.get('activo')
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)

        with DatabaseManager() as db:
            # Query base con stats de conversaciones
            query = """
                SELECT
                    u.id,
                    u.email,
                    u.nombre,
                    u.activo,
                    u.fecha_creacion,
                    u.ultimo_login,
                    u.total_sesiones,
                    u.total_busquedas,
                    (SELECT COUNT(*) FROM chat_user_sessions s
                     WHERE s.user_id = u.id AND s.activa = TRUE
                     AND (s.fecha_expiracion IS NULL OR s.fecha_expiracion > NOW())) as sesiones_activas,
                    (SELECT COUNT(*) FROM conversaciones_busqueda c
                     WHERE c.user_id = u.id AND c.activa = TRUE) as total_conversaciones,
                    (SELECT COALESCE(SUM(c.total_mensajes), 0) FROM conversaciones_busqueda c
                     WHERE c.user_id = u.id) as total_mensajes,
                    (SELECT MAX(l.fecha) FROM chat_usage_log l
                     WHERE l.user_id = u.id) as ultima_actividad
                FROM chat_users u
            """

            params = []
            if activo is not None:
                query += " WHERE u.activo = %s"
                params.append(activo.lower() == 'true')

            query += " ORDER BY u.fecha_creacion DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            db.cursor.execute(query, params)
            users = db.cursor.fetchall()

            # Contar total
            count_query = "SELECT COUNT(*) as total FROM chat_users"
            if activo is not None:
                count_query += " WHERE activo = %s"
                db.cursor.execute(count_query, [activo.lower() == 'true'])
            else:
                db.cursor.execute(count_query)
            total = db.cursor.fetchone()['total']

            # Stats generales
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE activo = TRUE) as activos,
                    (SELECT COUNT(*) FROM chat_user_sessions
                     WHERE activa = TRUE
                     AND (fecha_expiracion IS NULL OR fecha_expiracion > NOW())) as sesiones_activas
                FROM chat_users
            """)
            stats = db.cursor.fetchone()

            return jsonify({
                'success': True,
                'data': {
                    'users': [{
                        'id': u['id'],
                        'email': u['email'],
                        'nombre': u['nombre'],
                        'activo': u['activo'],
                        'fecha_creacion': u['fecha_creacion'].isoformat() if u['fecha_creacion'] else None,
                        'ultimo_login': u['ultimo_login'].isoformat() if u['ultimo_login'] else None,
                        'total_sesiones': u['total_sesiones'],
                        'total_busquedas': u['total_busquedas'],
                        'sesiones_activas': u['sesiones_activas'],
                        'total_conversaciones': u['total_conversaciones'],
                        'total_mensajes': u['total_mensajes'],
                        'ultima_actividad': u['ultima_actividad'].isoformat() if u['ultima_actividad'] else None
                    } for u in users],
                    'total': total,
                    'stats': {
                        'total': stats['total'],
                        'activos': stats['activos'],
                        'sesiones_activas': stats['sesiones_activas']
                    }
                }
            })

    except Exception as e:
        print(f"Error listando usuarios: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@chat_users_admin_bp.route('', methods=['POST'])
@token_required
def create_user():
    """
    Crea un nuevo usuario de chat

    Body JSON:
    {
        "email": "user@example.com",
        "nombre": "Nombre Usuario",
        "password": "password123" (opcional, se genera automáticamente si no se envía)
    }

    Returns:
        {
            "success": true,
            "data": {
                "user": {...},
                "password": "..." (solo se muestra una vez)
            }
        }
    """
    try:
        data = request.get_json()

        if not data or 'email' not in data or 'nombre' not in data:
            return jsonify({
                'success': False,
                'error': 'Se requieren email y nombre'
            }), 400

        email = data['email'].strip().lower()
        nombre = data['nombre'].strip()
        password = data.get('password', generate_password())

        # Validar email
        if '@' not in email:
            return jsonify({
                'success': False,
                'error': 'Email inválido'
            }), 400

        with DatabaseManager() as db:
            # Verificar si ya existe
            db.cursor.execute("SELECT id FROM chat_users WHERE email = %s", (email,))
            if db.cursor.fetchone():
                return jsonify({
                    'success': False,
                    'error': 'Ya existe un usuario con ese email'
                }), 409

            # Crear usuario con password hasheado usando pgcrypto
            db.cursor.execute("""
                INSERT INTO chat_users (email, nombre, password_hash)
                VALUES (%s, %s, crypt(%s, gen_salt('bf')))
                RETURNING id, email, nombre, activo, fecha_creacion
            """, (email, nombre, password))

            user = db.cursor.fetchone()
            db.conn.commit()

            print(f"✅ Usuario de chat creado: {email}")

            return jsonify({
                'success': True,
                'data': {
                    'user': {
                        'id': user['id'],
                        'email': user['email'],
                        'nombre': user['nombre'],
                        'activo': user['activo'],
                        'fecha_creacion': user['fecha_creacion'].isoformat() if user['fecha_creacion'] else None
                    },
                    'password': password  # Solo se muestra una vez
                }
            }), 201

    except Exception as e:
        print(f"Error creando usuario: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@chat_users_admin_bp.route('/<int:user_id>', methods=['GET'])
@token_required
def get_user(user_id):
    """
    Obtiene un usuario por ID con estadísticas detalladas
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    u.id,
                    u.email,
                    u.nombre,
                    u.activo,
                    u.fecha_creacion,
                    u.ultimo_login,
                    u.total_sesiones,
                    u.total_busquedas
                FROM chat_users u
                WHERE u.id = %s
            """, (user_id,))

            user = db.cursor.fetchone()

            if not user:
                return jsonify({
                    'success': False,
                    'error': 'Usuario no encontrado'
                }), 404

            # Contar sesiones activas
            db.cursor.execute("""
                SELECT COUNT(*) as count
                FROM chat_user_sessions
                WHERE user_id = %s AND activa = TRUE
                AND (fecha_expiracion IS NULL OR fecha_expiracion > NOW())
            """, (user_id,))
            sesiones = db.cursor.fetchone()['count']

            return jsonify({
                'success': True,
                'data': {
                    'id': user['id'],
                    'email': user['email'],
                    'nombre': user['nombre'],
                    'activo': user['activo'],
                    'fecha_creacion': user['fecha_creacion'].isoformat() if user['fecha_creacion'] else None,
                    'ultimo_login': user['ultimo_login'].isoformat() if user['ultimo_login'] else None,
                    'total_sesiones': user['total_sesiones'],
                    'total_busquedas': user['total_busquedas'],
                    'sesiones_activas': sesiones
                }
            })

    except Exception as e:
        print(f"Error obteniendo usuario: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@chat_users_admin_bp.route('/<int:user_id>', methods=['PUT'])
@token_required
def update_user(user_id):
    """
    Actualiza un usuario existente

    Body JSON:
    {
        "nombre": "Nuevo Nombre",
        "activo": true/false
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'error': 'No se enviaron datos para actualizar'
            }), 400

        with DatabaseManager() as db:
            # Verificar que existe
            db.cursor.execute("SELECT id FROM chat_users WHERE id = %s", (user_id,))
            if not db.cursor.fetchone():
                return jsonify({
                    'success': False,
                    'error': 'Usuario no encontrado'
                }), 404

            # Construir query de actualización
            updates = []
            params = []

            if 'nombre' in data:
                updates.append("nombre = %s")
                params.append(data['nombre'].strip())

            if 'activo' in data:
                updates.append("activo = %s")
                params.append(data['activo'])

                # Si se desactiva, cerrar todas las sesiones
                if not data['activo']:
                    db.cursor.execute(
                        "UPDATE chat_user_sessions SET activa = FALSE WHERE user_id = %s",
                        (user_id,)
                    )

            if not updates:
                return jsonify({
                    'success': False,
                    'error': 'No hay campos válidos para actualizar'
                }), 400

            params.append(user_id)
            query = f"UPDATE chat_users SET {', '.join(updates)} WHERE id = %s RETURNING id, email, nombre, activo"

            db.cursor.execute(query, params)
            user = db.cursor.fetchone()
            db.conn.commit()

            print(f"✅ Usuario actualizado: {user['email']}")

            return jsonify({
                'success': True,
                'data': {
                    'id': user['id'],
                    'email': user['email'],
                    'nombre': user['nombre'],
                    'activo': user['activo']
                }
            })

    except Exception as e:
        print(f"Error actualizando usuario: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@chat_users_admin_bp.route('/<int:user_id>', methods=['DELETE'])
@token_required
def delete_user(user_id):
    """
    Desactiva un usuario (soft delete)
    También cierra todas sus sesiones activas
    """
    try:
        with DatabaseManager() as db:
            # Verificar que existe
            db.cursor.execute("SELECT email FROM chat_users WHERE id = %s", (user_id,))
            user = db.cursor.fetchone()

            if not user:
                return jsonify({
                    'success': False,
                    'error': 'Usuario no encontrado'
                }), 404

            # Desactivar usuario
            db.cursor.execute(
                "UPDATE chat_users SET activo = FALSE WHERE id = %s",
                (user_id,)
            )

            # Cerrar todas las sesiones
            db.cursor.execute(
                "UPDATE chat_user_sessions SET activa = FALSE WHERE user_id = %s",
                (user_id,)
            )

            db.conn.commit()

            print(f"✅ Usuario desactivado: {user['email']}")

            return jsonify({
                'success': True,
                'message': 'Usuario desactivado correctamente'
            })

    except Exception as e:
        print(f"Error desactivando usuario: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# GESTIÓN DE CONTRASEÑAS
# ============================================================================

@chat_users_admin_bp.route('/<int:user_id>/reset-password', methods=['POST'])
@token_required
def reset_password(user_id):
    """
    Genera una nueva contraseña para el usuario

    Returns:
        {
            "success": true,
            "data": {
                "password": "nueva_password"  (solo se muestra una vez)
            }
        }
    """
    try:
        with DatabaseManager() as db:
            # Verificar que existe
            db.cursor.execute("SELECT email FROM chat_users WHERE id = %s", (user_id,))
            user = db.cursor.fetchone()

            if not user:
                return jsonify({
                    'success': False,
                    'error': 'Usuario no encontrado'
                }), 404

            # Generar nueva contraseña
            new_password = generate_password()

            # Actualizar contraseña
            db.cursor.execute("""
                UPDATE chat_users
                SET password_hash = crypt(%s, gen_salt('bf'))
                WHERE id = %s
            """, (new_password, user_id))

            # Cerrar todas las sesiones activas
            db.cursor.execute(
                "UPDATE chat_user_sessions SET activa = FALSE WHERE user_id = %s",
                (user_id,)
            )

            db.conn.commit()

            print(f"✅ Contraseña reseteada para: {user['email']}")

            return jsonify({
                'success': True,
                'data': {
                    'password': new_password,
                    'message': 'Contraseña actualizada. Todas las sesiones han sido cerradas.'
                }
            })

    except Exception as e:
        print(f"Error reseteando contraseña: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# GESTIÓN DE SESIONES
# ============================================================================

@chat_users_admin_bp.route('/<int:user_id>/sessions', methods=['GET'])
@token_required
def get_sessions(user_id):
    """
    Lista las sesiones de un usuario

    Query params:
        - activas: true/false para filtrar solo activas
    """
    try:
        activas = request.args.get('activas', 'true').lower() == 'true'

        with DatabaseManager() as db:
            # Verificar que existe
            db.cursor.execute("SELECT id FROM chat_users WHERE id = %s", (user_id,))
            if not db.cursor.fetchone():
                return jsonify({
                    'success': False,
                    'error': 'Usuario no encontrado'
                }), 404

            query = """
                SELECT
                    id,
                    ip_address,
                    user_agent,
                    activa,
                    fecha_creacion,
                    fecha_expiracion,
                    ultimo_uso
                FROM chat_user_sessions
                WHERE user_id = %s
            """

            if activas:
                query += " AND activa = TRUE AND (fecha_expiracion IS NULL OR fecha_expiracion > NOW())"

            query += " ORDER BY fecha_creacion DESC LIMIT 50"

            db.cursor.execute(query, (user_id,))
            sessions = db.cursor.fetchall()

            return jsonify({
                'success': True,
                'data': [{
                    'id': s['id'],
                    'ip_address': s['ip_address'],
                    'user_agent': s['user_agent'][:100] if s['user_agent'] else None,
                    'activa': s['activa'],
                    'fecha_creacion': s['fecha_creacion'].isoformat() if s['fecha_creacion'] else None,
                    'fecha_expiracion': s['fecha_expiracion'].isoformat() if s['fecha_expiracion'] else None,
                    'ultimo_uso': s['ultimo_uso'].isoformat() if s['ultimo_uso'] else None
                } for s in sessions]
            })

    except Exception as e:
        print(f"Error obteniendo sesiones: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@chat_users_admin_bp.route('/<int:user_id>/sessions', methods=['DELETE'])
@token_required
def close_all_sessions(user_id):
    """
    Cierra todas las sesiones activas de un usuario
    """
    try:
        with DatabaseManager() as db:
            # Verificar que existe
            db.cursor.execute("SELECT email FROM chat_users WHERE id = %s", (user_id,))
            user = db.cursor.fetchone()

            if not user:
                return jsonify({
                    'success': False,
                    'error': 'Usuario no encontrado'
                }), 404

            # Cerrar todas las sesiones
            db.cursor.execute("""
                UPDATE chat_user_sessions
                SET activa = FALSE
                WHERE user_id = %s AND activa = TRUE
                RETURNING id
            """, (user_id,))

            closed = db.cursor.rowcount
            db.conn.commit()

            print(f"✅ {closed} sesiones cerradas para: {user['email']}")

            return jsonify({
                'success': True,
                'data': {
                    'sessions_closed': closed,
                    'message': f'{closed} sesiones cerradas correctamente'
                }
            })

    except Exception as e:
        print(f"Error cerrando sesiones: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# ACTIVIDAD Y CONVERSACIONES
# ============================================================================

@chat_users_admin_bp.route('/<int:user_id>/activity', methods=['GET'])
@token_required
def get_user_activity(user_id):
    """
    Obtiene el historial de actividad de un usuario

    Query params:
        - limit: número máximo de resultados (default 50)

    Returns:
        {
            "success": true,
            "data": {
                "activity": [
                    {
                        "accion": "search",
                        "fecha": "2024-01-15T10:30:00",
                        "detalles": {...}
                    }
                ],
                "conversations": [
                    {
                        "id": 1,
                        "nombre": "Apto Laureles",
                        "total_mensajes": 5,
                        "fecha_creacion": "...",
                        "fecha_actualizacion": "..."
                    }
                ]
            }
        }
    """
    try:
        limit = request.args.get('limit', 50, type=int)

        with DatabaseManager() as db:
            # Verificar que existe
            db.cursor.execute("SELECT id, nombre, email FROM chat_users WHERE id = %s", (user_id,))
            user = db.cursor.fetchone()

            if not user:
                return jsonify({
                    'success': False,
                    'error': 'Usuario no encontrado'
                }), 404

            # Obtener historial de actividad
            db.cursor.execute("""
                SELECT
                    accion,
                    detalles,
                    fecha,
                    conversacion_id
                FROM chat_usage_log
                WHERE user_id = %s
                ORDER BY fecha DESC
                LIMIT %s
            """, (user_id, limit))
            activity = db.cursor.fetchall()

            # Obtener conversaciones del usuario
            db.cursor.execute("""
                SELECT
                    id,
                    nombre,
                    total_mensajes,
                    total_propiedades_mostradas,
                    criterios_acumulados,
                    fecha_creacion,
                    fecha_actualizacion
                FROM conversaciones_busqueda
                WHERE user_id = %s AND activa = TRUE
                ORDER BY fecha_actualizacion DESC
                LIMIT 20
            """, (user_id,))
            conversations = db.cursor.fetchall()

            return jsonify({
                'success': True,
                'data': {
                    'user': {
                        'id': user['id'],
                        'nombre': user['nombre'],
                        'email': user['email']
                    },
                    'activity': [{
                        'accion': a['accion'],
                        'detalles': a['detalles'],
                        'fecha': a['fecha'].isoformat() if a['fecha'] else None,
                        'conversacion_id': a['conversacion_id']
                    } for a in activity],
                    'conversations': [{
                        'id': c['id'],
                        'nombre': c['nombre'],
                        'total_mensajes': c['total_mensajes'],
                        'total_propiedades_mostradas': c['total_propiedades_mostradas'],
                        'criterios': c['criterios_acumulados'],
                        'fecha_creacion': c['fecha_creacion'].isoformat() if c['fecha_creacion'] else None,
                        'fecha_actualizacion': c['fecha_actualizacion'].isoformat() if c['fecha_actualizacion'] else None
                    } for c in conversations]
                }
            })

    except Exception as e:
        print(f"Error obteniendo actividad: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
