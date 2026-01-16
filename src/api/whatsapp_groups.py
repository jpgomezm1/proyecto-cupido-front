#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhatsApp Groups API - Gestión de grupos de WhatsApp para captación
"""

from flask import Blueprint, request, jsonify
from src.db.database import DatabaseManager
from datetime import datetime
import os
import requests

whatsapp_groups_bp = Blueprint('whatsapp_groups', __name__, url_prefix='/api')

# Configuración de UltraMSG
ULTRAMSG_INSTANCE_ID = os.getenv('ULTRAMSG_INSTANCE_ID')
ULTRAMSG_TOKEN = os.getenv('ULTRAMSG_TOKEN')


def get_ultramsg_groups():
    """Obtiene todos los grupos de WhatsApp desde UltraMSG API."""
    if not ULTRAMSG_INSTANCE_ID or not ULTRAMSG_TOKEN:
        return None, "Credenciales de UltraMSG no configuradas"

    url = f"https://api.ultramsg.com/{ULTRAMSG_INSTANCE_ID}/groups?token={ULTRAMSG_TOKEN}"

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json(), None
    except Exception as e:
        return None, str(e)


def init_grupos_table():
    """Inicializa la tabla de grupos si no existe."""
    with DatabaseManager() as db:
        db.cursor.execute("""
            CREATE TABLE IF NOT EXISTS grupos_whatsapp (
                id SERIAL PRIMARY KEY,
                grupo_id VARCHAR(100) UNIQUE NOT NULL,
                nombre VARCHAR(255) NOT NULL,
                descripcion TEXT,
                activo BOOLEAN DEFAULT true,
                fecha_agregado TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                agregado_por VARCHAR(100),
                total_capturas INTEGER DEFAULT 0,
                ultima_captura TIMESTAMP
            )
        """)
        db.conn.commit()


# Inicializar tabla al cargar el módulo
try:
    init_grupos_table()
    print("[OK] Tabla grupos_whatsapp inicializada")
except Exception as e:
    print(f"[WARN] No se pudo inicializar tabla grupos_whatsapp: {e}")


@whatsapp_groups_bp.route('/whatsapp-groups/search', methods=['GET'])
def search_groups():
    """
    Busca grupos de WhatsApp disponibles en UltraMSG.

    Query params:
        - q: Término de búsqueda (opcional)

    Returns:
        Lista de grupos que coinciden con la búsqueda
    """
    try:
        search_term = request.args.get('q', '').lower().strip()

        groups, error = get_ultramsg_groups()

        if error:
            return jsonify({
                'success': False,
                'error': error
            }), 500

        # Filtrar por término de búsqueda si se proporciona
        if search_term:
            groups = [g for g in groups if search_term in g.get('name', '').lower()]

        # Obtener grupos ya agregados para marcarlos
        with DatabaseManager() as db:
            db.cursor.execute("SELECT grupo_id FROM grupos_whatsapp WHERE activo = true")
            active_ids = {row['grupo_id'] for row in db.cursor.fetchall()}

        # Formatear respuesta
        result = []
        for group in groups:
            result.append({
                'id': group.get('id'),
                'name': group.get('name'),
                'participants_count': group.get('participants', 0),
                'already_added': group.get('id') in active_ids
            })

        # Ordenar: primero los no agregados, luego por nombre
        result.sort(key=lambda x: (x['already_added'], x['name'].lower()))

        return jsonify({
            'success': True,
            'data': result,
            'total': len(result)
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@whatsapp_groups_bp.route('/whatsapp-groups', methods=['GET'])
def list_groups():
    """
    Lista todos los grupos de WhatsApp activos en el sistema.
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    id, grupo_id, nombre, descripcion, activo,
                    fecha_agregado, agregado_por, total_capturas, ultima_captura
                FROM grupos_whatsapp
                ORDER BY activo DESC, nombre ASC
            """)
            rows = db.cursor.fetchall()

            groups = [{
                'id': row['id'],
                'grupo_id': row['grupo_id'],
                'nombre': row['nombre'],
                'descripcion': row['descripcion'],
                'activo': row['activo'],
                'fecha_agregado': row['fecha_agregado'].isoformat() if row['fecha_agregado'] else None,
                'agregado_por': row['agregado_por'],
                'total_capturas': row['total_capturas'],
                'ultima_captura': row['ultima_captura'].isoformat() if row['ultima_captura'] else None
            } for row in rows]

            return jsonify({
                'success': True,
                'data': groups,
                'total': len(groups),
                'activos': sum(1 for g in groups if g['activo'])
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@whatsapp_groups_bp.route('/whatsapp-groups', methods=['POST'])
def add_group():
    """
    Agrega un grupo de WhatsApp al sistema.

    Body JSON:
        - grupo_id: ID del grupo (@g.us)
        - nombre: Nombre del grupo
        - descripcion: Descripción opcional
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400

        grupo_id = data.get('grupo_id')
        nombre = data.get('nombre')
        descripcion = data.get('descripcion', '')
        agregado_por = data.get('agregado_por', 'admin')

        if not grupo_id or not nombre:
            return jsonify({
                'success': False,
                'error': 'grupo_id y nombre son requeridos'
            }), 400

        with DatabaseManager() as db:
            # Verificar si ya existe
            db.cursor.execute(
                "SELECT id, activo FROM grupos_whatsapp WHERE grupo_id = %s",
                (grupo_id,)
            )
            existing = db.cursor.fetchone()

            if existing:
                if existing['activo']:
                    return jsonify({
                        'success': False,
                        'error': 'Este grupo ya está agregado y activo'
                    }), 400
                else:
                    # Reactivar grupo existente
                    db.cursor.execute("""
                        UPDATE grupos_whatsapp
                        SET activo = true, nombre = %s, descripcion = %s, fecha_agregado = CURRENT_TIMESTAMP
                        WHERE grupo_id = %s
                        RETURNING id
                    """, (nombre, descripcion, grupo_id))
                    db.conn.commit()

                    return jsonify({
                        'success': True,
                        'message': 'Grupo reactivado exitosamente',
                        'id': existing['id']
                    })

            # Insertar nuevo grupo
            db.cursor.execute("""
                INSERT INTO grupos_whatsapp (grupo_id, nombre, descripcion, agregado_por)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (grupo_id, nombre, descripcion, agregado_por))

            new_id = db.cursor.fetchone()['id']
            db.conn.commit()

            return jsonify({
                'success': True,
                'message': 'Grupo agregado exitosamente',
                'id': new_id
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@whatsapp_groups_bp.route('/whatsapp-groups/<int:group_id>', methods=['PUT'])
def update_group(group_id):
    """
    Actualiza un grupo de WhatsApp.
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400

        with DatabaseManager() as db:
            # Verificar que existe
            db.cursor.execute("SELECT id FROM grupos_whatsapp WHERE id = %s", (group_id,))
            if not db.cursor.fetchone():
                return jsonify({'success': False, 'error': 'Grupo no encontrado'}), 404

            # Construir query de actualización
            updates = []
            values = []

            if 'nombre' in data:
                updates.append("nombre = %s")
                values.append(data['nombre'])

            if 'descripcion' in data:
                updates.append("descripcion = %s")
                values.append(data['descripcion'])

            if 'activo' in data:
                updates.append("activo = %s")
                values.append(data['activo'])

            if not updates:
                return jsonify({'success': False, 'error': 'No hay campos para actualizar'}), 400

            values.append(group_id)

            db.cursor.execute(
                f"UPDATE grupos_whatsapp SET {', '.join(updates)} WHERE id = %s",
                values
            )
            db.conn.commit()

            return jsonify({
                'success': True,
                'message': 'Grupo actualizado exitosamente'
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@whatsapp_groups_bp.route('/whatsapp-groups/<int:group_id>', methods=['DELETE'])
def delete_group(group_id):
    """
    Desactiva (soft delete) un grupo de WhatsApp.
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute(
                "UPDATE grupos_whatsapp SET activo = false WHERE id = %s RETURNING id",
                (group_id,)
            )
            result = db.cursor.fetchone()

            if not result:
                return jsonify({'success': False, 'error': 'Grupo no encontrado'}), 404

            db.conn.commit()

            return jsonify({
                'success': True,
                'message': 'Grupo desactivado exitosamente'
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@whatsapp_groups_bp.route('/whatsapp-groups/active-ids', methods=['GET'])
def get_active_group_ids():
    """
    Obtiene solo los IDs de grupos activos (para uso interno del bot).
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute(
                "SELECT grupo_id FROM grupos_whatsapp WHERE activo = true"
            )
            rows = db.cursor.fetchall()

            return jsonify({
                'success': True,
                'data': [row['grupo_id'] for row in rows]
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@whatsapp_groups_bp.route('/whatsapp-groups/<int:group_id>/stats', methods=['GET'])
def get_group_stats(group_id):
    """
    Obtiene estadísticas de un grupo específico.
    """
    try:
        with DatabaseManager() as db:
            # Info del grupo
            db.cursor.execute("""
                SELECT grupo_id, nombre, total_capturas, ultima_captura, fecha_agregado
                FROM grupos_whatsapp WHERE id = %s
            """, (group_id,))

            group = db.cursor.fetchone()
            if not group:
                return jsonify({'success': False, 'error': 'Grupo no encontrado'}), 404

            # Capturas por día (últimos 30 días)
            db.cursor.execute("""
                SELECT DATE(fecha_creacion) as fecha, COUNT(*) as count
                FROM propiedades
                WHERE grupo_origen = %s
                AND fecha_creacion >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY DATE(fecha_creacion)
                ORDER BY fecha
            """, (group['grupo_id'],))

            capturas_por_dia = [{
                'fecha': row['fecha'].isoformat(),
                'count': row['count']
            } for row in db.cursor.fetchall()]

            # Top agentes captadores en este grupo
            db.cursor.execute("""
                SELECT
                    p.agente_captador_telefono as telefono,
                    a.nombre,
                    COUNT(*) as capturas
                FROM propiedades p
                LEFT JOIN agentes a ON p.agente_captador_telefono = a.telefono
                WHERE p.grupo_origen = %s
                GROUP BY p.agente_captador_telefono, a.nombre
                ORDER BY capturas DESC
                LIMIT 5
            """, (group['grupo_id'],))

            top_agentes = [{
                'telefono': row['telefono'],
                'nombre': row['nombre'],
                'capturas': row['capturas']
            } for row in db.cursor.fetchall()]

            return jsonify({
                'success': True,
                'data': {
                    'grupo': {
                        'nombre': group['nombre'],
                        'total_capturas': group['total_capturas'],
                        'ultima_captura': group['ultima_captura'].isoformat() if group['ultima_captura'] else None,
                        'fecha_agregado': group['fecha_agregado'].isoformat() if group['fecha_agregado'] else None
                    },
                    'capturas_por_dia': capturas_por_dia,
                    'top_agentes': top_agentes
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
