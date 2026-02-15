#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Blueprint para Sistema de Feedback
Permite a usuarios de chat enviar feedback y a admins gestionarlo
"""

from flask import Blueprint, request, jsonify
from flask_cors import CORS
import traceback

from src.db.database import DatabaseManager
from src.api.chat_auth import require_chat_auth
from src.api.auth import token_required

feedback_bp = Blueprint('feedback', __name__, url_prefix='/api/feedback')

CORS(feedback_bp, supports_credentials=True)

CATEGORIAS_VALIDAS = ['administrador', 'busqueda_propiedades', 'ai_search', 'general', 'otro']
ESTADOS_VALIDOS = ['nuevo', 'en_revision', 'resuelto', 'descartado']
PRIORIDADES_VALIDAS = ['baja', 'media', 'alta', 'urgente']
MAX_IMAGENES = 5


# ============================================================================
# ENDPOINTS PARA USUARIOS DE CHAT
# ============================================================================

@feedback_bp.route('', methods=['POST'])
@require_chat_auth
def create_feedback():
    """
    POST /api/feedback
    Envia feedback desde un usuario de chat

    Body JSON:
    {
        "categoria": "administrador",
        "contenido": "Texto del feedback...",
        "imagenes": [{"data": "base64...", "nombre": "foto.jpg", "tipo": "image/jpeg"}]
    }
    """
    db = None
    try:
        db = DatabaseManager()
        db.connect()
        user_id = request.chat_user['id']
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No se enviaron datos'}), 400

        categoria = data.get('categoria', '').strip()
        contenido = data.get('contenido', '').strip()
        imagenes = data.get('imagenes', [])

        if not categoria or categoria not in CATEGORIAS_VALIDAS:
            return jsonify({
                'success': False,
                'error': f'Categoria invalida. Opciones: {", ".join(CATEGORIAS_VALIDAS)}'
            }), 400

        if not contenido:
            return jsonify({'success': False, 'error': 'El contenido es requerido'}), 400

        if len(imagenes) > MAX_IMAGENES:
            return jsonify({
                'success': False,
                'error': f'Maximo {MAX_IMAGENES} imagenes permitidas'
            }), 400

        # Validar estructura de imagenes
        import json
        for img in imagenes:
            if not isinstance(img, dict) or 'data' not in img:
                return jsonify({
                    'success': False,
                    'error': 'Formato de imagen invalido'
                }), 400

        db.cursor.execute("""
            INSERT INTO feedback (user_id, categoria, contenido, imagenes)
            VALUES (%s, %s, %s, %s::jsonb)
            RETURNING id, categoria, estado, prioridad, fecha_creacion
        """, (user_id, categoria, contenido, json.dumps(imagenes)))

        result = db.cursor.fetchone()
        feedback_id = result['id']
        db.conn.commit()

        # Generate AI summary in background (non-blocking for user)
        try:
            from src.core.feedback_analyzer import analyze_feedback
            ai_resumen = analyze_feedback(contenido, categoria, imagenes)
            if ai_resumen:
                db.cursor.execute(
                    "UPDATE feedback SET ai_resumen = %s WHERE id = %s",
                    (ai_resumen, feedback_id)
                )
                db.conn.commit()
                print(f"[Feedback] AI resumen saved for feedback #{feedback_id}")
        except Exception as ai_err:
            print(f"[Feedback] AI analysis failed (non-critical): {ai_err}")

        return jsonify({
            'success': True,
            'data': {
                'id': feedback_id,
                'categoria': result['categoria'],
                'estado': result['estado'],
                'prioridad': result['prioridad'],
                'fecha_creacion': str(result['fecha_creacion'])
            },
            'message': 'Feedback enviado exitosamente'
        }), 201

    except Exception as e:
        if db and db.conn:
            db.conn.rollback()
        print(f"Error en create_feedback: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@feedback_bp.route('/my', methods=['GET'])
@require_chat_auth
def get_my_feedback():
    """
    GET /api/feedback/my
    Obtiene el historial de feedback del usuario autenticado
    """
    db = None
    try:
        db = DatabaseManager()
        db.connect()
        user_id = request.chat_user['id']

        db.cursor.execute("""
            SELECT id, categoria, contenido, estado, prioridad,
                   notas_admin, fecha_creacion, fecha_actualizacion,
                   jsonb_array_length(COALESCE(imagenes, '[]'::jsonb)) as num_imagenes
            FROM feedback
            WHERE user_id = %s
            ORDER BY fecha_creacion DESC
            LIMIT 50
        """, (user_id,))

        results = db.cursor.fetchall()

        items = []
        for r in results:
            items.append({
                'id': r['id'],
                'categoria': r['categoria'],
                'contenido': r['contenido'][:200],
                'estado': r['estado'],
                'prioridad': r['prioridad'],
                'notas_admin': r['notas_admin'],
                'num_imagenes': r['num_imagenes'],
                'fecha_creacion': str(r['fecha_creacion']) if r['fecha_creacion'] else None,
                'fecha_actualizacion': str(r['fecha_actualizacion']) if r['fecha_actualizacion'] else None
            })

        return jsonify({
            'success': True,
            'data': items,
            'count': len(items)
        }), 200

    except Exception as e:
        print(f"Error en get_my_feedback: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


# ============================================================================
# ENDPOINTS PARA ADMIN
# ============================================================================

@feedback_bp.route('', methods=['GET'])
@token_required
def list_feedback():
    """
    GET /api/feedback
    Lista todo el feedback con filtros (admin)

    Query params:
        - estado: filtrar por estado
        - categoria: filtrar por categoria
        - limit: max resultados (default 50)
        - offset: paginacion
    """
    try:
        estado = request.args.get('estado')
        categoria = request.args.get('categoria')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        with DatabaseManager() as db:
            query = """
                SELECT
                    f.id, f.user_id, f.categoria, f.contenido, f.estado,
                    f.prioridad, f.notas_admin, f.ai_resumen,
                    f.fecha_creacion, f.fecha_actualizacion,
                    jsonb_array_length(COALESCE(f.imagenes, '[]'::jsonb)) as num_imagenes,
                    u.nombre as user_nombre,
                    u.email as user_email
                FROM feedback f
                JOIN chat_users u ON u.id = f.user_id
                WHERE 1=1
            """
            params = []

            if estado:
                query += " AND f.estado = %s"
                params.append(estado)

            if categoria:
                query += " AND f.categoria = %s"
                params.append(categoria)

            query += " ORDER BY f.fecha_creacion DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            db.cursor.execute(query, params)
            results = db.cursor.fetchall()

            # Total count with same filters
            count_query = "SELECT COUNT(*) as total FROM feedback f WHERE 1=1"
            count_params = []
            if estado:
                count_query += " AND f.estado = %s"
                count_params.append(estado)
            if categoria:
                count_query += " AND f.categoria = %s"
                count_params.append(categoria)

            db.cursor.execute(count_query, count_params)
            total = db.cursor.fetchone()['total']

            items = []
            for r in results:
                items.append({
                    'id': r['id'],
                    'user_id': r['user_id'],
                    'categoria': r['categoria'],
                    'contenido': r['contenido'][:200],
                    'estado': r['estado'],
                    'prioridad': r['prioridad'],
                    'notas_admin': r['notas_admin'],
                    'ai_resumen': r['ai_resumen'],
                    'num_imagenes': r['num_imagenes'],
                    'user_nombre': r['user_nombre'],
                    'user_email': r['user_email'],
                    'fecha_creacion': r['fecha_creacion'].isoformat() if r['fecha_creacion'] else None,
                    'fecha_actualizacion': r['fecha_actualizacion'].isoformat() if r['fecha_actualizacion'] else None
                })

            return jsonify({
                'success': True,
                'data': items,
                'total': total
            })

    except Exception as e:
        print(f"Error en list_feedback: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@feedback_bp.route('/<int:feedback_id>', methods=['GET'])
@token_required
def get_feedback_detail(feedback_id):
    """
    GET /api/feedback/<id>
    Detalle de un feedback con imagenes completas (admin)
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    f.id, f.user_id, f.categoria, f.contenido, f.imagenes,
                    f.estado, f.prioridad, f.notas_admin, f.ai_resumen,
                    f.fecha_creacion, f.fecha_actualizacion,
                    u.nombre as user_nombre,
                    u.email as user_email
                FROM feedback f
                JOIN chat_users u ON u.id = f.user_id
                WHERE f.id = %s
            """, (feedback_id,))

            r = db.cursor.fetchone()

            if not r:
                return jsonify({'success': False, 'error': 'Feedback no encontrado'}), 404

            return jsonify({
                'success': True,
                'data': {
                    'id': r['id'],
                    'user_id': r['user_id'],
                    'categoria': r['categoria'],
                    'contenido': r['contenido'],
                    'imagenes': r['imagenes'] or [],
                    'estado': r['estado'],
                    'prioridad': r['prioridad'],
                    'notas_admin': r['notas_admin'],
                    'ai_resumen': r['ai_resumen'],
                    'user_nombre': r['user_nombre'],
                    'user_email': r['user_email'],
                    'fecha_creacion': r['fecha_creacion'].isoformat() if r['fecha_creacion'] else None,
                    'fecha_actualizacion': r['fecha_actualizacion'].isoformat() if r['fecha_actualizacion'] else None
                }
            })

    except Exception as e:
        print(f"Error en get_feedback_detail: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@feedback_bp.route('/<int:feedback_id>', methods=['DELETE'])
@token_required
def delete_feedback(feedback_id):
    """
    DELETE /api/feedback/<id>
    Elimina un feedback (admin)
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute("DELETE FROM feedback WHERE id = %s RETURNING id", (feedback_id,))
            result = db.cursor.fetchone()

            if not result:
                return jsonify({'success': False, 'error': 'Feedback no encontrado'}), 404

            db.conn.commit()
            return jsonify({'success': True, 'message': 'Feedback eliminado'})

    except Exception as e:
        print(f"Error en delete_feedback: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@feedback_bp.route('/<int:feedback_id>/status', methods=['PUT'])
@token_required
def update_feedback_status(feedback_id):
    """
    PUT /api/feedback/<id>/status
    Actualiza estado, prioridad y notas_admin (admin)

    Body JSON:
    {
        "estado": "en_revision",
        "prioridad": "alta",
        "notas_admin": "Revisando el tema..."
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No se enviaron datos'}), 400

        with DatabaseManager() as db:
            # Verify exists
            db.cursor.execute("SELECT id FROM feedback WHERE id = %s", (feedback_id,))
            if not db.cursor.fetchone():
                return jsonify({'success': False, 'error': 'Feedback no encontrado'}), 404

            updates = []
            params = []

            if 'estado' in data:
                if data['estado'] not in ESTADOS_VALIDOS:
                    return jsonify({
                        'success': False,
                        'error': f'Estado invalido. Opciones: {", ".join(ESTADOS_VALIDOS)}'
                    }), 400
                updates.append("estado = %s")
                params.append(data['estado'])

            if 'prioridad' in data:
                if data['prioridad'] not in PRIORIDADES_VALIDAS:
                    return jsonify({
                        'success': False,
                        'error': f'Prioridad invalida. Opciones: {", ".join(PRIORIDADES_VALIDAS)}'
                    }), 400
                updates.append("prioridad = %s")
                params.append(data['prioridad'])

            if 'notas_admin' in data:
                updates.append("notas_admin = %s")
                params.append(data['notas_admin'])

            if not updates:
                return jsonify({'success': False, 'error': 'No hay campos para actualizar'}), 400

            updates.append("fecha_actualizacion = CURRENT_TIMESTAMP")
            params.append(feedback_id)

            query = f"""
                UPDATE feedback SET {', '.join(updates)}
                WHERE id = %s
                RETURNING id, estado, prioridad, notas_admin, fecha_actualizacion
            """

            db.cursor.execute(query, params)
            result = db.cursor.fetchone()
            db.conn.commit()

            return jsonify({
                'success': True,
                'data': {
                    'id': result['id'],
                    'estado': result['estado'],
                    'prioridad': result['prioridad'],
                    'notas_admin': result['notas_admin'],
                    'fecha_actualizacion': result['fecha_actualizacion'].isoformat() if result['fecha_actualizacion'] else None
                }
            })

    except Exception as e:
        print(f"Error en update_feedback_status: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@feedback_bp.route('/stats', methods=['GET'])
@token_required
def get_feedback_stats():
    """
    GET /api/feedback/stats
    Estadisticas de feedback (admin)
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE estado = 'nuevo') as nuevos,
                    COUNT(*) FILTER (WHERE estado = 'en_revision') as en_revision,
                    COUNT(*) FILTER (WHERE estado = 'resuelto') as resueltos,
                    COUNT(*) FILTER (WHERE estado = 'descartado') as descartados
                FROM feedback
            """)
            stats = db.cursor.fetchone()

            db.cursor.execute("""
                SELECT categoria, COUNT(*) as total
                FROM feedback
                GROUP BY categoria
                ORDER BY total DESC
            """)
            por_categoria = {r['categoria']: r['total'] for r in db.cursor.fetchall()}

            return jsonify({
                'success': True,
                'data': {
                    'total': stats['total'],
                    'nuevos': stats['nuevos'],
                    'en_revision': stats['en_revision'],
                    'resueltos': stats['resueltos'],
                    'descartados': stats['descartados'],
                    'por_categoria': por_categoria
                }
            })

    except Exception as e:
        print(f"Error en get_feedback_stats: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
