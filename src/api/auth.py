#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Autenticación - Proyecto Cupido
Login con JWT tokens para el panel de administración
"""

import os
import jwt
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, request, jsonify, g
from dotenv import load_dotenv

load_dotenv()

# Blueprint para autenticación
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# Clave secreta para JWT (DEBE configurarse en .env)
JWT_SECRET = os.getenv('JWT_SECRET')
if not JWT_SECRET:
    raise ValueError("❌ JWT_SECRET no configurada en .env - REQUERIDO para seguridad")

JWT_EXPIRATION_HOURS = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))


def _load_users_from_env():
    """
    Carga usuarios desde variables de entorno.
    Formato en .env:
        AUTH_USER_1_EMAIL=user@example.com
        AUTH_USER_1_PASSWORD_HASH=<sha256_hash>
        AUTH_USER_1_NAME=Nombre Usuario
        AUTH_USER_1_ROLE=admin
    """
    users = {}

    # Buscar usuarios configurados (hasta 10)
    for i in range(1, 11):
        email = os.getenv(f'AUTH_USER_{i}_EMAIL')
        if not email:
            continue

        password_hash = os.getenv(f'AUTH_USER_{i}_PASSWORD_HASH')
        name = os.getenv(f'AUTH_USER_{i}_NAME', email.split('@')[0])
        role = os.getenv(f'AUTH_USER_{i}_ROLE', 'user')

        if password_hash:
            users[email.lower().strip()] = {
                'password_hash': password_hash,
                'name': name,
                'role': role
            }

    return users


# Cargar usuarios autorizados desde variables de entorno
AUTHORIZED_USERS = _load_users_from_env()

if not AUTHORIZED_USERS:
    print("⚠️  ADVERTENCIA: No hay usuarios configurados en .env")
    print("   Configura AUTH_USER_1_EMAIL, AUTH_USER_1_PASSWORD_HASH, etc.")


def hash_password(password: str) -> str:
    """Hashea una contraseña con SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica si una contraseña coincide con su hash"""
    return hash_password(password) == password_hash


def generate_token(email: str, user_data: dict) -> str:
    """
    Genera un token JWT para el usuario

    Args:
        email: Email del usuario
        user_data: Datos del usuario (name, role)

    Returns:
        Token JWT como string
    """
    payload = {
        'email': email,
        'name': user_data['name'],
        'role': user_data['role'],
        'iat': datetime.utcnow(),
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    }

    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')


def decode_token(token: str) -> dict:
    """
    Decodifica y valida un token JWT

    Args:
        token: Token JWT

    Returns:
        Payload del token o None si es inválido

    Raises:
        jwt.ExpiredSignatureError: Si el token expiró
        jwt.InvalidTokenError: Si el token es inválido
    """
    return jwt.decode(token, JWT_SECRET, algorithms=['HS256'])


def token_required(f):
    """
    Decorador para proteger endpoints que requieren autenticación

    Uso:
        @app.route('/api/protected')
        @token_required
        def protected_route():
            user = g.current_user  # Usuario autenticado
            return jsonify({'message': f'Hola {user["name"]}'})
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        # Buscar token en header Authorization
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            # Formato esperado: "Bearer <token>"
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]

        if not token:
            return jsonify({
                'success': False,
                'error': 'Token de autenticación requerido',
                'code': 'AUTH_TOKEN_MISSING'
            }), 401

        try:
            # Decodificar token
            payload = decode_token(token)

            # Verificar que el usuario sigue existiendo
            if payload['email'] not in AUTHORIZED_USERS:
                return jsonify({
                    'success': False,
                    'error': 'Usuario no autorizado',
                    'code': 'AUTH_USER_NOT_FOUND'
                }), 401

            # Guardar usuario en contexto de Flask
            g.current_user = {
                'email': payload['email'],
                'name': payload['name'],
                'role': payload['role']
            }

        except jwt.ExpiredSignatureError:
            return jsonify({
                'success': False,
                'error': 'Token expirado. Por favor inicia sesión nuevamente.',
                'code': 'AUTH_TOKEN_EXPIRED'
            }), 401
        except jwt.InvalidTokenError:
            return jsonify({
                'success': False,
                'error': 'Token inválido',
                'code': 'AUTH_TOKEN_INVALID'
            }), 401

        return f(*args, **kwargs)

    return decorated


# ============================================================================
# ENDPOINTS DE AUTENTICACIÓN
# ============================================================================

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Endpoint de login

    Body JSON:
    {
        "email": "usuario@ejemplo.com",
        "password": "tu_contraseña"
    }

    Returns:
        {
            "success": true,
            "token": "eyJ...",
            "user": {
                "email": "...",
                "name": "...",
                "role": "..."
            },
            "expires_in": 86400
        }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'error': 'Se requieren credenciales',
                'code': 'AUTH_CREDENTIALS_MISSING'
            }), 400

        email = data.get('email', '').lower().strip()
        password = data.get('password', '')

        # Validar campos
        if not email or not password:
            return jsonify({
                'success': False,
                'error': 'Email y contraseña son requeridos',
                'code': 'AUTH_FIELDS_MISSING'
            }), 400

        # Buscar usuario
        if email not in AUTHORIZED_USERS:
            return jsonify({
                'success': False,
                'error': 'Credenciales inválidas',
                'code': 'AUTH_INVALID_CREDENTIALS'
            }), 401

        user = AUTHORIZED_USERS[email]

        # Verificar contraseña
        if not verify_password(password, user['password_hash']):
            return jsonify({
                'success': False,
                'error': 'Credenciales inválidas',
                'code': 'AUTH_INVALID_CREDENTIALS'
            }), 401

        # Generar token
        token = generate_token(email, user)

        print(f"✅ Login exitoso: {email}")

        return jsonify({
            'success': True,
            'token': token,
            'user': {
                'email': email,
                'name': user['name'],
                'role': user['role']
            },
            'expires_in': JWT_EXPIRATION_HOURS * 3600  # segundos
        }), 200

    except Exception as e:
        print(f"❌ Error en login: {e}")
        return jsonify({
            'success': False,
            'error': 'Error interno del servidor',
            'code': 'AUTH_SERVER_ERROR'
        }), 500


@auth_bp.route('/verify', methods=['GET'])
@token_required
def verify():
    """
    Verifica si el token actual es válido

    Headers:
        Authorization: Bearer <token>

    Returns:
        {
            "success": true,
            "user": {
                "email": "...",
                "name": "...",
                "role": "..."
            }
        }
    """
    return jsonify({
        'success': True,
        'user': g.current_user
    }), 200


@auth_bp.route('/me', methods=['GET'])
@token_required
def get_current_user():
    """
    Obtiene información del usuario actual

    Headers:
        Authorization: Bearer <token>

    Returns:
        {
            "success": true,
            "user": {
                "email": "...",
                "name": "...",
                "role": "..."
            }
        }
    """
    return jsonify({
        'success': True,
        'user': g.current_user
    }), 200
