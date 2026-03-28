#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API de Favoritos - Proyecto Cupido
Permite a los usuarios del chat guardar propiedades como favoritas
"""

from flask import Blueprint, jsonify, request
from flask_cors import CORS
from src.db.database import DatabaseManager
from src.api.chat_auth import require_chat_auth
import traceback

favorites_bp = Blueprint('favorites', __name__, url_prefix='/api/favorites')

# Habilitar CORS para este blueprint
CORS(favorites_bp, supports_credentials=True)


def get_db():
    """Helper para obtener conexión a la base de datos"""
    db = DatabaseManager()
    if not db.connect():
        raise ConnectionError("No se pudo conectar a la base de datos")
    return db


@favorites_bp.route('', methods=['GET'])
@require_chat_auth
def get_favorites():
    """
    GET /api/favorites

    Obtiene todas las propiedades favoritas del usuario autenticado

    Returns:
    {
        "success": true,
        "data": [
            {
                "id": 1,
                "propiedad_id": 123,
                "fecha_agregada": "2024-01-15T10:30:00",
                "notas": "...",
                "propiedad": { ... datos completos de la propiedad ... }
            }
        ],
        "count": 5
    }
    """
    db = None
    try:
        db = get_db()
        user_id = request.chat_user['id']

        # Query con JOIN para obtener datos completos de las propiedades
        query = """
            SELECT
                f.id as favorite_id,
                f.propiedad_id,
                f.fecha_agregada,
                f.notas,
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
                p.estrato as stratum,
                p.imagen_principal as cover_image_url,
                p.fecha_creacion as created_at
            FROM chat_user_favorites f
            JOIN propiedades p ON p.id = f.propiedad_id
            WHERE f.user_id = %s AND p.activa = true
            ORDER BY f.fecha_agregada DESC
        """

        db.cursor.execute(query, (user_id,))
        results = db.cursor.fetchall()

        favorites = []
        for row in results:
            favorites.append({
                'favorite_id': row['favorite_id'],
                'propiedad_id': row['propiedad_id'],
                'fecha_agregada': str(row['fecha_agregada']) if row['fecha_agregada'] else None,
                'notas': row['notas'],
                'propiedad': {
                    'id': row['id'],
                    'slug': row['slug'],
                    'title': row['title'],
                    'type': row['type'],
                    'price_cop': row['price_cop'],
                    'city': row['city'],
                    'barrio': row['barrio'],
                    'area_m2': float(row['area_m2']) if row['area_m2'] else None,
                    'bedrooms': row['bedrooms'],
                    'bathrooms': row['bathrooms'],
                    'parking': row['parking'],
                    'stratum': row['stratum'],
                    'cover_image_url': row['cover_image_url'],
                    'created_at': str(row['created_at']) if row['created_at'] else None,
                }
            })

        return jsonify({
            'success': True,
            'data': favorites,
            'count': len(favorites)
        }), 200

    except Exception as e:
        print(f"Error en get_favorites: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@favorites_bp.route('', methods=['POST'])
@require_chat_auth
def add_favorite():
    """
    POST /api/favorites

    Agrega una propiedad a los favoritos del usuario

    Body:
    {
        "propiedad_id": 123,
        "notas": "Me interesa por la ubicación" (opcional)
    }

    Returns:
    {
        "success": true,
        "data": {
            "id": 1,
            "propiedad_id": 123,
            "fecha_agregada": "2024-01-15T10:30:00"
        }
    }
    """
    db = None
    try:
        db = get_db()
        user_id = request.chat_user['id']
        data = request.get_json()

        if not data or 'propiedad_id' not in data:
            return jsonify({
                'success': False,
                'error': 'propiedad_id es requerido'
            }), 400

        propiedad_id = int(data['propiedad_id'])
        notas = data.get('notas', None)

        # Verificar que la propiedad existe y está activa
        db.cursor.execute("""
            SELECT id, titulo FROM propiedades
            WHERE id = %s AND activa = true
        """, (propiedad_id,))

        propiedad = db.cursor.fetchone()
        if not propiedad:
            return jsonify({
                'success': False,
                'error': 'Propiedad no encontrada o no está activa'
            }), 404

        # Insertar favorito (ON CONFLICT para manejar duplicados)
        db.cursor.execute("""
            INSERT INTO chat_user_favorites (user_id, propiedad_id, notas)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, propiedad_id)
            DO UPDATE SET notas = EXCLUDED.notas, fecha_agregada = CURRENT_TIMESTAMP
            RETURNING id, propiedad_id, fecha_agregada, notas
        """, (user_id, propiedad_id, notas))

        result = db.cursor.fetchone()
        db.conn.commit()

        return jsonify({
            'success': True,
            'data': {
                'id': result['id'],
                'propiedad_id': result['propiedad_id'],
                'fecha_agregada': str(result['fecha_agregada']),
                'notas': result['notas']
            },
            'message': f'Propiedad "{propiedad["titulo"]}" agregada a favoritos'
        }), 201

    except Exception as e:
        if db and db.conn:
            db.conn.rollback()
        print(f"Error en add_favorite: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@favorites_bp.route('/<int:propiedad_id>', methods=['DELETE'])
@require_chat_auth
def remove_favorite(propiedad_id: int):
    """
    DELETE /api/favorites/:propiedad_id

    Remueve una propiedad de los favoritos del usuario

    Returns:
    {
        "success": true,
        "message": "Propiedad removida de favoritos"
    }
    """
    db = None
    try:
        db = get_db()
        user_id = request.chat_user['id']

        db.cursor.execute("""
            DELETE FROM chat_user_favorites
            WHERE user_id = %s AND propiedad_id = %s
            RETURNING id
        """, (user_id, propiedad_id))

        result = db.cursor.fetchone()
        db.conn.commit()

        if not result:
            return jsonify({
                'success': False,
                'error': 'Favorito no encontrado'
            }), 404

        return jsonify({
            'success': True,
            'message': 'Propiedad removida de favoritos'
        }), 200

    except Exception as e:
        if db and db.conn:
            db.conn.rollback()
        print(f"Error en remove_favorite: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@favorites_bp.route('/check', methods=['GET'])
@require_chat_auth
def check_favorites():
    """
    GET /api/favorites/check?ids=1,2,3,4,5

    Verifica cuáles propiedades de una lista son favoritas del usuario
    Útil para cargar el estado de favoritos de múltiples propiedades a la vez

    Query params:
    - ids: lista de IDs de propiedades separados por coma

    Returns:
    {
        "success": true,
        "data": {
            "favorited_ids": [1, 3, 5]
        }
    }
    """
    db = None
    try:
        db = get_db()
        user_id = request.chat_user['id']

        ids_str = request.args.get('ids', '')
        if not ids_str:
            return jsonify({
                'success': True,
                'data': {'favorited_ids': []}
            }), 200

        # Parsear IDs
        try:
            ids = [int(id.strip()) for id in ids_str.split(',') if id.strip()]
        except ValueError:
            return jsonify({
                'success': False,
                'error': 'IDs inválidos'
            }), 400

        if not ids:
            return jsonify({
                'success': True,
                'data': {'favorited_ids': []}
            }), 200

        # Query para obtener IDs que son favoritos
        placeholders = ','.join(['%s'] * len(ids))
        query = f"""
            SELECT propiedad_id
            FROM chat_user_favorites
            WHERE user_id = %s AND propiedad_id IN ({placeholders})
        """

        db.cursor.execute(query, (user_id, *ids))
        results = db.cursor.fetchall()

        favorited_ids = [row['propiedad_id'] for row in results]

        return jsonify({
            'success': True,
            'data': {'favorited_ids': favorited_ids}
        }), 200

    except Exception as e:
        print(f"Error en check_favorites: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()


@favorites_bp.route('/ids', methods=['GET'])
@require_chat_auth
def get_favorite_ids():
    """
    GET /api/favorites/ids

    Obtiene solo los IDs de las propiedades favoritas del usuario
    Útil para cargar el estado inicial de favoritos sin toda la info

    Returns:
    {
        "success": true,
        "data": {
            "favorited_ids": [1, 3, 5, 8, 12]
        }
    }
    """
    db = None
    try:
        db = get_db()
        user_id = request.chat_user['id']

        db.cursor.execute("""
            SELECT propiedad_id
            FROM chat_user_favorites
            WHERE user_id = %s
            ORDER BY fecha_agregada DESC
        """, (user_id,))

        results = db.cursor.fetchall()
        favorited_ids = [row['propiedad_id'] for row in results]

        return jsonify({
            'success': True,
            'data': {'favorited_ids': favorited_ids}
        }), 200

    except Exception as e:
        print(f"Error en get_favorite_ids: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    finally:
        if db:
            db.disconnect()
