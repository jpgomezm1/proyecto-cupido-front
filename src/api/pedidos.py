"""
API endpoints para gestión de pedidos (demandas capturadas de grupos WhatsApp).
Estados: pendiente → en_proceso → procesado
"""

from flask import Blueprint, request, jsonify
from src.db.database import DatabaseManager

pedidos_bp = Blueprint('pedidos', __name__, url_prefix='/api')

ESTADOS_VALIDOS = ('pendiente', 'en_proceso', 'procesado')
NEXT_ESTADO = {'pendiente': 'en_proceso', 'en_proceso': 'procesado', 'procesado': 'pendiente'}


@pedidos_bp.route('/pedidos', methods=['GET'])
def list_pedidos():
    """
    Lista pedidos con paginación y filtros.

    Query params:
        - page, per_page: paginación
        - grupo_id: filtrar por grupo
        - q: búsqueda en texto
        - estado: pendiente | en_proceso | procesado
        - fecha: today | week (filtros rápidos de fecha)
    """
    try:
        page = max(1, request.args.get('page', 1, type=int))
        per_page = min(100, max(1, request.args.get('per_page', 20, type=int)))
        grupo_id = request.args.get('grupo_id', '')
        search_q = request.args.get('q', '').strip()
        estado_filter = request.args.get('estado', '')
        fecha_filter = request.args.get('fecha', '')

        offset = (page - 1) * per_page

        with DatabaseManager() as db:
            conditions = []
            params = []

            if grupo_id:
                conditions.append("p.grupo_id = %s")
                params.append(grupo_id)

            if search_q:
                conditions.append("(p.texto_pedido ILIKE %s OR p.texto_formateado ILIKE %s)")
                params.append(f"%{search_q}%")
                params.append(f"%{search_q}%")

            if estado_filter in ESTADOS_VALIDOS:
                conditions.append("p.estado = %s")
                params.append(estado_filter)

            if fecha_filter == 'today':
                conditions.append("p.fecha_captura >= CURRENT_DATE")
            elif fecha_filter == 'week':
                conditions.append("p.fecha_captura >= CURRENT_DATE - INTERVAL '7 days'")

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            db.cursor.execute(f"SELECT COUNT(*) as total FROM pedidos p {where_clause}", params)
            total = db.cursor.fetchone()['total']

            # Score = presupuesto normalizado - penalizacion por dias de antigüedad
            # Un pedido de $2B de hace 10 dias: 2.0 - (10*0.15) = 0.5
            # Un pedido de $800M de hoy: 0.8 - (0*0.15) = 0.8 → gana el reciente
            # Un pedido sin presupuesto se ordena solo por fecha
            db.cursor.execute(f"""
                SELECT
                    p.id, p.grupo_id, p.agente_telefono, p.agente_nombre,
                    p.texto_pedido, p.texto_formateado, p.estado,
                    p.fecha_captura, p.presupuesto_estimado,
                    g.nombre as grupo_nombre
                FROM pedidos p
                LEFT JOIN grupos_whatsapp g ON p.grupo_id = g.grupo_id
                {where_clause}
                ORDER BY
                    (COALESCE(p.presupuesto_estimado, 0) / 1000000000.0)
                    - (EXTRACT(EPOCH FROM (NOW() - p.fecha_captura)) / 86400.0 * 0.15)
                    DESC
                LIMIT %s OFFSET %s
            """, params + [per_page, offset])

            pedidos = [{
                'id': row['id'],
                'grupo_id': row['grupo_id'],
                'grupo_nombre': row['grupo_nombre'],
                'agente_telefono': row['agente_telefono'],
                'agente_nombre': row['agente_nombre'],
                'texto_pedido': row['texto_pedido'],
                'texto_formateado': row['texto_formateado'],
                'estado': row['estado'] or 'pendiente',
                'presupuesto_estimado': row['presupuesto_estimado'] if 'presupuesto_estimado' in row else None,
                'fecha_captura': row['fecha_captura'].isoformat() if row['fecha_captura'] else None
            } for row in db.cursor.fetchall()]

            return jsonify({
                'success': True,
                'data': pedidos,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page if total > 0 else 1
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@pedidos_bp.route('/pedidos/<int:pedido_id>/avanzar', methods=['PATCH'])
def avanzar_estado(pedido_id):
    """Avanza el estado: pendiente → en_proceso → procesado → pendiente."""
    try:
        with DatabaseManager() as db:
            db.cursor.execute("SELECT id, estado FROM pedidos WHERE id = %s", (pedido_id,))
            pedido = db.cursor.fetchone()
            if not pedido:
                return jsonify({'success': False, 'error': 'Pedido no encontrado'}), 404

            current = pedido['estado'] or 'pendiente'
            new_estado = NEXT_ESTADO.get(current, 'pendiente')

            db.cursor.execute(
                "UPDATE pedidos SET estado = %s WHERE id = %s RETURNING id, estado",
                (new_estado, pedido_id)
            )
            result = db.cursor.fetchone()
            db.conn.commit()

            return jsonify({
                'success': True,
                'data': {'id': result['id'], 'estado': result['estado']}
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@pedidos_bp.route('/pedidos/<int:pedido_id>/estado', methods=['PATCH'])
def set_estado(pedido_id):
    """Establece un estado específico."""
    try:
        data = request.get_json()
        nuevo_estado = data.get('estado', '') if data else ''
        if nuevo_estado not in ESTADOS_VALIDOS:
            return jsonify({'success': False, 'error': f'Estado invalido. Usar: {ESTADOS_VALIDOS}'}), 400

        with DatabaseManager() as db:
            db.cursor.execute(
                "UPDATE pedidos SET estado = %s WHERE id = %s RETURNING id, estado",
                (nuevo_estado, pedido_id)
            )
            result = db.cursor.fetchone()
            if not result:
                return jsonify({'success': False, 'error': 'Pedido no encontrado'}), 404
            db.conn.commit()

            return jsonify({
                'success': True,
                'data': {'id': result['id'], 'estado': result['estado']}
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# Backwards compat
@pedidos_bp.route('/pedidos/<int:pedido_id>/toggle-procesado', methods=['PATCH'])
def toggle_procesado(pedido_id):
    """Backwards compat: avanza el estado."""
    return avanzar_estado(pedido_id)


@pedidos_bp.route('/pedidos/stats', methods=['GET'])
def pedidos_stats():
    """Métricas de pedidos con desglose por estado."""
    try:
        days = max(1, request.args.get('days', 30, type=int))

        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE estado = 'procesado') as procesados,
                    COUNT(*) FILTER (WHERE estado = 'en_proceso') as en_proceso,
                    COUNT(*) FILTER (WHERE estado = 'pendiente' OR estado IS NULL) as pendientes,
                    COUNT(*) FILTER (WHERE fecha_captura >= CURRENT_DATE - INTERVAL '7 days') as esta_semana,
                    COUNT(*) FILTER (WHERE fecha_captura >= CURRENT_DATE - INTERVAL '1 day') as hoy
                FROM pedidos
            """)
            c = db.cursor.fetchone()
            total = c['total'] or 0
            procesados = c['procesados'] or 0
            en_proceso = c['en_proceso'] or 0
            pendientes = c['pendientes'] or 0
            tasa_respuesta = round((procesados / total * 100), 1) if total > 0 else 0
            tasa_en_gestion = round(((procesados + en_proceso) / total * 100), 1) if total > 0 else 0

            db.cursor.execute("""
                SELECT
                    DATE(fecha_captura) as fecha,
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE estado = 'procesado') as procesados,
                    COUNT(*) FILTER (WHERE estado = 'en_proceso') as en_proceso,
                    COUNT(*) FILTER (WHERE estado = 'pendiente' OR estado IS NULL) as pendientes
                FROM pedidos
                WHERE fecha_captura >= CURRENT_DATE - INTERVAL '%s days'
                GROUP BY DATE(fecha_captura)
                ORDER BY fecha
            """.replace('%s', str(int(days))))
            pedidos_por_dia = [{
                'fecha': row['fecha'].isoformat(),
                'total': row['total'],
                'procesados': row['procesados'],
                'en_proceso': row['en_proceso'],
                'pendientes': row['pendientes']
            } for row in db.cursor.fetchall()]

            db.cursor.execute("""
                SELECT
                    agente_telefono, agente_nombre,
                    COUNT(*) as total_pedidos,
                    COUNT(*) FILTER (WHERE estado = 'procesado') as procesados,
                    COUNT(*) FILTER (WHERE estado = 'en_proceso') as en_proceso
                FROM pedidos
                WHERE agente_telefono IS NOT NULL
                AND fecha_captura >= CURRENT_DATE - INTERVAL '%s days'
                GROUP BY agente_telefono, agente_nombre
                ORDER BY total_pedidos DESC
                LIMIT 10
            """.replace('%s', str(int(days))))
            top_agentes = [{
                'telefono': row['agente_telefono'],
                'nombre': row['agente_nombre'],
                'total_pedidos': row['total_pedidos'],
                'procesados': row['procesados'],
                'en_proceso': row['en_proceso']
            } for row in db.cursor.fetchall()]

            db.cursor.execute("""
                SELECT
                    p.grupo_id, g.nombre as grupo_nombre,
                    COUNT(*) as total_pedidos,
                    COUNT(*) FILTER (WHERE p.estado = 'procesado') as procesados,
                    COUNT(*) FILTER (WHERE p.estado = 'en_proceso') as en_proceso
                FROM pedidos p
                LEFT JOIN grupos_whatsapp g ON p.grupo_id = g.grupo_id
                WHERE p.fecha_captura >= CURRENT_DATE - INTERVAL '%s days'
                GROUP BY p.grupo_id, g.nombre
                ORDER BY total_pedidos DESC
                LIMIT 10
            """.replace('%s', str(int(days))))
            por_grupo = [{
                'grupo_id': row['grupo_id'],
                'grupo_nombre': row['grupo_nombre'],
                'total_pedidos': row['total_pedidos'],
                'procesados': row['procesados'],
                'en_proceso': row['en_proceso']
            } for row in db.cursor.fetchall()]

            db.cursor.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE fecha_captura >= CURRENT_DATE - INTERVAL '7 days') as esta_semana,
                    COUNT(*) FILTER (WHERE fecha_captura >= CURRENT_DATE - INTERVAL '14 days'
                                     AND fecha_captura < CURRENT_DATE - INTERVAL '7 days') as semana_pasada
                FROM pedidos
            """)
            weekly = db.cursor.fetchone()

            return jsonify({
                'success': True,
                'data': {
                    'total': total,
                    'procesados': procesados,
                    'en_proceso': en_proceso,
                    'pendientes': pendientes,
                    'tasa_respuesta': tasa_respuesta,
                    'tasa_en_gestion': tasa_en_gestion,
                    'esta_semana': c['esta_semana'] or 0,
                    'semana_pasada': weekly['semana_pasada'] or 0,
                    'hoy': c['hoy'] or 0,
                    'pedidos_por_dia': pedidos_por_dia,
                    'top_agentes': top_agentes,
                    'por_grupo': por_grupo
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@pedidos_bp.route('/pedidos/<int:pedido_id>', methods=['DELETE'])
def delete_pedido(pedido_id):
    """Elimina un pedido."""
    try:
        with DatabaseManager() as db:
            db.cursor.execute(
                "DELETE FROM pedidos WHERE id = %s RETURNING id, grupo_id",
                (pedido_id,)
            )
            result = db.cursor.fetchone()
            if not result:
                return jsonify({'success': False, 'error': 'Pedido no encontrado'}), 404

            db.cursor.execute("""
                UPDATE grupos_whatsapp
                SET total_pedidos = GREATEST(total_pedidos - 1, 0)
                WHERE grupo_id = %s
            """, (result['grupo_id'],))
            db.conn.commit()

            return jsonify({'success': True, 'message': 'Pedido eliminado exitosamente'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
