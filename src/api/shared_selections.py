#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API REST para Shared Property Selections
Permite guardar y recuperar selecciones de propiedades compartidas
"""

from flask import Blueprint, jsonify, request
from src.db.database import DatabaseManager
import traceback
import uuid
from datetime import datetime

# Crear blueprint
shared_selections_bp = Blueprint('shared_selections', __name__, url_prefix='/api/shared-selections')


def get_db():
    """Helper para obtener conexión a la base de datos"""
    db = DatabaseManager()
    db.connect()
    return db


@shared_selections_bp.route('', methods=['POST'])
def create_selection():
    """
    POST /api/shared-selections

    Crea una nueva selección de propiedades para compartir

    Body:
    {
        "conversation_id": 123,  // opcional
        "property_ids": [1, 2, 3]
    }

    Returns:
    {
        "success": true,
        "data": {
            "id": 1,
            "share_id": "abc123..."
        }
    }
    """
    db = None
    try:
        db = get_db()
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        property_ids = data.get('property_ids', [])
        conversation_id = data.get('conversation_id')

        if not property_ids or len(property_ids) == 0:
            return jsonify({'success': False, 'error': 'Se requiere al menos una propiedad'}), 400

        # Generar ID único para compartir
        share_id = str(uuid.uuid4())[:12]

        # Verificar que existe la tabla, si no, crearla
        db.cursor.execute("""
            CREATE TABLE IF NOT EXISTS shared_property_selections (
                id SERIAL PRIMARY KEY,
                share_id VARCHAR(50) UNIQUE NOT NULL,
                conversation_id INTEGER,
                property_ids INTEGER[] NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '30 days'),
                view_count INTEGER DEFAULT 0
            )
        """)
        db.conn.commit()

        # Insertar la selección
        db.cursor.execute("""
            INSERT INTO shared_property_selections (share_id, conversation_id, property_ids)
            VALUES (%s, %s, %s)
            RETURNING id, share_id
        """, (share_id, conversation_id, property_ids))

        result = db.cursor.fetchone()
        db.conn.commit()

        return jsonify({
            'success': True,
            'data': {
                'id': result['id'],
                'share_id': result['share_id']
            }
        }), 201

    except Exception as e:
        print(f"❌ Error en create_selection: {e}")
        traceback.print_exc()
        if db:
            db.conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@shared_selections_bp.route('/<share_id>', methods=['GET'])
def get_selection(share_id: str):
    """
    GET /api/shared-selections/:share_id

    Obtiene una selección de propiedades por su share_id

    Returns:
    {
        "success": true,
        "data": {
            "id": 1,
            "share_id": "abc123...",
            "properties": [...]
        }
    }
    """
    db = None
    try:
        db = get_db()

        # Obtener la selección
        db.cursor.execute("""
            SELECT id, share_id, conversation_id, property_ids, created_at
            FROM shared_property_selections
            WHERE share_id = %s
            AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
        """, (share_id,))

        selection = db.cursor.fetchone()

        if not selection:
            return jsonify({'success': False, 'error': 'Selección no encontrada o expirada'}), 404

        # Incrementar contador de vistas
        db.cursor.execute("""
            UPDATE shared_property_selections
            SET view_count = view_count + 1
            WHERE id = %s
        """, (selection['id'],))
        db.conn.commit()

        # Obtener las propiedades
        property_ids = selection['property_ids']

        if not property_ids:
            return jsonify({
                'success': True,
                'data': {
                    'id': selection['id'],
                    'share_id': selection['share_id'],
                    'properties': [],
                    'created_at': selection['created_at'].isoformat() if selection['created_at'] else None
                }
            }), 200

        # Consultar las propiedades
        db.cursor.execute("""
            SELECT
                p.id,
                p.codigo_propiedad as slug,
                p.titulo,
                p.precio,
                COALESCE('$' || TO_CHAR(p.precio, 'FM999,999,999,999'), '') as precio_texto,
                p.tipo_propiedad,
                p.ciudad,
                p.zona,
                p.area_construida,
                p.habitaciones,
                p.banos,
                p.parqueaderos,
                p.imagen_principal,
                p.imagen_principal as cover_image_url
            FROM propiedades p
            WHERE p.id = ANY(%s)
            ORDER BY array_position(%s, p.id)
        """, (property_ids, property_ids))

        properties = [dict(row) for row in db.cursor.fetchall()]

        return jsonify({
            'success': True,
            'data': {
                'id': selection['id'],
                'share_id': selection['share_id'],
                'properties': properties,
                'created_at': selection['created_at'].isoformat() if selection['created_at'] else None
            }
        }), 200

    except Exception as e:
        print(f"❌ Error en get_selection: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()
