#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Blueprint para Autenticación de Usuarios de Chat
Sistema de login para la vista compartible de chat
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from functools import wraps
import secrets
import traceback

from src.db.database import DatabaseManager

chat_auth_bp = Blueprint('chat_auth', __name__, url_prefix='/api/chat')


def generate_token():
    """Genera un token seguro para la sesión"""
    return secrets.token_urlsafe(64)


def get_current_user():
    """Obtiene el usuario actual desde el token en el header"""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None

    token = auth_header.split(' ')[1]

    try:
        with DatabaseManager() as db:
            query = """
                SELECT u.id, u.email, u.nombre
                FROM chat_users u
                JOIN chat_user_sessions s ON s.user_id = u.id
                WHERE s.token = %s
                  AND s.activa = TRUE
                  AND (s.fecha_expiracion IS NULL OR s.fecha_expiracion > NOW())
                  AND u.activo = TRUE
            """
            db.cursor.execute(query, (token,))
            row = db.cursor.fetchone()

            if row:
                # Actualizar último uso
                db.cursor.execute(
                    "UPDATE chat_user_sessions SET ultimo_uso = NOW() WHERE token = %s",
                    (token,)
                )
                db.conn.commit()
                return row

            return None
    except Exception as e:
        print(f"Error verificando token: {e}")
        return None


def require_chat_auth(f):
    """Decorador para requerir autenticación en endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({
                'success': False,
                'error': 'No autorizado',
                'code': 'UNAUTHORIZED'
            }), 401
        # Agregar usuario al request context
        request.chat_user = user
        return f(*args, **kwargs)
    return decorated_function


@chat_auth_bp.route('/login', methods=['POST'])
def login():
    """
    Login de usuario de chat

    Body JSON:
    {
        "email": "user@example.com",
        "password": "password123"
    }

    Returns:
    {
        "success": true,
        "data": {
            "token": "...",
            "user": {
                "id": 1,
                "email": "user@example.com",
                "nombre": "Usuario"
            }
        }
    }
    """
    try:
        data = request.get_json()
        if not data or 'email' not in data or 'password' not in data:
            return jsonify({
                'success': False,
                'error': 'Se requieren email y password'
            }), 400

        email = data['email'].strip().lower()
        password = data['password']

        with DatabaseManager() as db:
            # Verificar credenciales
            query = """
                SELECT id, nombre, email
                FROM chat_users
                WHERE email = %s
                  AND password_hash = crypt(%s, password_hash)
                  AND activo = TRUE
            """
            db.cursor.execute(query, (email, password))
            user = db.cursor.fetchone()

            if not user:
                return jsonify({
                    'success': False,
                    'error': 'Credenciales inválidas'
                }), 401

            user_id = user['id']

            # Generar token
            token = generate_token()
            expiration = datetime.now() + timedelta(days=30)

            # Crear sesión
            db.cursor.execute(
                """INSERT INTO chat_user_sessions
                   (user_id, token, ip_address, user_agent, fecha_expiracion)
                   VALUES (%s, %s, %s, %s, %s)""",
                (user_id, token, request.remote_addr,
                 request.headers.get('User-Agent', '')[:500], expiration)
            )

            # Registrar login
            db.cursor.execute(
                """UPDATE chat_users
                   SET ultimo_login = NOW(), total_sesiones = total_sesiones + 1
                   WHERE id = %s""",
                (user_id,)
            )

            # Log de uso
            db.cursor.execute(
                """INSERT INTO chat_usage_log (user_id, accion, detalles)
                   VALUES (%s, 'login', %s)""",
                (user_id, '{"ip": "' + (request.remote_addr or '') + '"}')
            )

            db.conn.commit()

            return jsonify({
                'success': True,
                'data': {
                    'token': token,
                    'user': {
                        'id': user['id'],
                        'email': user['email'],
                        'nombre': user['nombre']
                    },
                    'expires_at': expiration.isoformat()
                }
            })

    except Exception as e:
        print(f"Error en login: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'Error en el servidor'
        }), 500


@chat_auth_bp.route('/verify', methods=['GET'])
def verify_token():
    """
    Verifica si el token actual es válido

    Headers:
    Authorization: Bearer <token>

    Returns:
    {
        "success": true,
        "data": {
            "user": {
                "id": 1,
                "email": "user@example.com",
                "nombre": "Usuario"
            }
        }
    }
    """
    user = get_current_user()

    if not user:
        return jsonify({
            'success': False,
            'error': 'Token inválido o expirado',
            'code': 'INVALID_TOKEN'
        }), 401

    return jsonify({
        'success': True,
        'data': {
            'user': {
                'id': user['id'],
                'email': user['email'],
                'nombre': user['nombre']
            }
        }
    })


@chat_auth_bp.route('/logout', methods=['POST'])
@require_chat_auth
def logout():
    """
    Cierra la sesión actual

    Headers:
    Authorization: Bearer <token>
    """
    try:
        auth_header = request.headers.get('Authorization')
        token = auth_header.split(' ')[1]

        with DatabaseManager() as db:
            db.cursor.execute(
                "UPDATE chat_user_sessions SET activa = FALSE WHERE token = %s",
                (token,)
            )
            db.conn.commit()

        return jsonify({
            'success': True,
            'message': 'Sesión cerrada'
        })

    except Exception as e:
        print(f"Error en logout: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@chat_auth_bp.route('/me', methods=['GET'])
@require_chat_auth
def get_me():
    """
    Obtiene información del usuario actual

    Headers:
    Authorization: Bearer <token>
    """
    user = request.chat_user

    try:
        with DatabaseManager() as db:
            # Obtener stats del usuario
            db.cursor.execute(
                """SELECT total_sesiones, total_busquedas, ultimo_login
                   FROM chat_users WHERE id = %s""",
                (user['id'],)
            )
            stats = db.cursor.fetchone()

            return jsonify({
                'success': True,
                'data': {
                    'id': user['id'],
                    'email': user['email'],
                    'nombre': user['nombre'],
                    'total_sesiones': stats['total_sesiones'] if stats else 0,
                    'total_busquedas': stats['total_busquedas'] if stats else 0,
                    'ultimo_login': stats['ultimo_login'].isoformat() if stats and stats['ultimo_login'] else None
                }
            })

    except Exception as e:
        print(f"Error obteniendo usuario: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def log_chat_usage(user_id: int, accion: str, detalles: dict = None):
    """Registra una acción de uso en el log"""
    try:
        with DatabaseManager() as db:
            db.cursor.execute(
                """INSERT INTO chat_usage_log (user_id, accion, detalles)
                   VALUES (%s, %s, %s)""",
                (user_id, accion, str(detalles) if detalles else '{}')
            )

            # Incrementar contador de búsquedas si aplica
            if accion == 'search':
                db.cursor.execute(
                    "UPDATE chat_users SET total_busquedas = total_busquedas + 1 WHERE id = %s",
                    (user_id,)
                )

            db.conn.commit()
    except Exception as e:
        print(f"Error registrando uso: {e}")
