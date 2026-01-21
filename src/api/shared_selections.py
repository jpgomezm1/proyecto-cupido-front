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
        "property_ids": [1, 2, 3],
        "user_id": 5  // opcional - ID del chat_user que crea el share
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
        user_id = data.get('user_id')  # ID del chat_user que crea el share

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
                view_count INTEGER DEFAULT 0,
                user_id INTEGER REFERENCES chat_users(id) ON DELETE SET NULL
            )
        """)
        db.conn.commit()

        # Insertar la selección con user_id
        db.cursor.execute("""
            INSERT INTO shared_property_selections (share_id, conversation_id, property_ids, user_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id, share_id
        """, (share_id, conversation_id, property_ids, user_id))

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
            "properties": [...],
            "agent": {
                "name": "Nombre Agente",
                "phone": "+573001234567",
                "whatsapp": "573001234567"
            }
        }
    }
    """
    db = None
    try:
        db = get_db()

        # Obtener la selección con JOIN a chat_users para obtener teléfono del agente
        db.cursor.execute("""
            SELECT
                s.id,
                s.share_id,
                s.conversation_id,
                s.property_ids,
                s.created_at,
                s.user_id,
                cu.nombre as agent_name,
                cu.telefono as agent_phone
            FROM shared_property_selections s
            LEFT JOIN chat_users cu ON s.user_id = cu.id
            WHERE s.share_id = %s
            AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP)
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

        # Construir info del agente si existe
        agent_info = None
        if selection.get('user_id') and selection.get('agent_phone'):
            agent_phone = selection['agent_phone']
            agent_info = {
                'name': selection['agent_name'] or 'Fynder',
                'phone': agent_phone,
                'whatsapp': agent_phone.replace('+', '') if agent_phone else None
            }

        if not property_ids:
            return jsonify({
                'success': True,
                'data': {
                    'id': selection['id'],
                    'share_id': selection['share_id'],
                    'properties': [],
                    'created_at': selection['created_at'].isoformat() if selection['created_at'] else None,
                    'agent': agent_info
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
                'created_at': selection['created_at'].isoformat() if selection['created_at'] else None,
                'agent': agent_info
            }
        }), 200

    except Exception as e:
        print(f"❌ Error en get_selection: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()
