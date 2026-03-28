"""
API endpoints para gestión de pedidos (demandas capturadas de grupos WhatsApp).
"""

from flask import Blueprint, request, jsonify
from src.db.database import DatabaseManager

pedidos_bp = Blueprint('pedidos', __name__, url_prefix='/api')


@pedidos_bp.route('/pedidos', methods=['GET'])
def list_pedidos():
    """
    Lista pedidos con paginación y filtros opcionales.

    Query params:
        - page: Página (default 1)
        - per_page: Resultados por página (default 20, max 100)
        - grupo_id: Filtrar por grupo WhatsApp
        - q: Búsqueda en texto del pedido
    """
    try:
        page = max(1, request.args.get('page', 1, type=int))
        per_page = min(100, max(1, request.args.get('per_page', 20, type=int)))
        grupo_id = request.args.get('grupo_id', '')
        search_q = request.args.get('q', '').strip()

        offset = (page - 1) * per_page

        with DatabaseManager() as db:
            # Construir WHERE dinámico
            conditions = []
            params = []

            if grupo_id:
                conditions.append("p.grupo_id = %s")
                params.append(grupo_id)

            if search_q:
                conditions.append("p.texto_pedido ILIKE %s")
                params.append(f"%{search_q}%")

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            # Total count
            db.cursor.execute(f"""
                SELECT COUNT(*) as total
                FROM pedidos p
                {where_clause}
            """, params)
            total = db.cursor.fetchone()['total']

            # Pedidos con nombre del grupo
            db.cursor.execute(f"""
                SELECT
                    p.id, p.grupo_id, p.agente_telefono, p.agente_nombre,
                    p.texto_pedido, p.fecha_captura,
                    g.nombre as grupo_nombre
                FROM pedidos p
                LEFT JOIN grupos_whatsapp g ON p.grupo_id = g.grupo_id
                {where_clause}
                ORDER BY p.fecha_captura DESC
                LIMIT %s OFFSET %s
            """, params + [per_page, offset])

            pedidos = [{
                'id': row['id'],
                'grupo_id': row['grupo_id'],
                'grupo_nombre': row['grupo_nombre'],
                'agente_telefono': row['agente_telefono'],
                'agente_nombre': row['agente_nombre'],
                'texto_pedido': row['texto_pedido'],
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


@pedidos_bp.route('/pedidos/stats', methods=['GET'])
def pedidos_stats():
    """
    Estadísticas agregadas de pedidos.
    """
    try:
        with DatabaseManager() as db:
            # Total y esta semana
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE fecha_captura >= CURRENT_DATE - INTERVAL '7 days') as esta_semana,
                    COUNT(*) FILTER (WHERE fecha_captura >= CURRENT_DATE - INTERVAL '1 day') as hoy
                FROM pedidos
            """)
            counts = db.cursor.fetchone()

            # Top grupos por pedidos
            db.cursor.execute("""
                SELECT
                    p.grupo_id,
                    g.nombre as grupo_nombre,
                    COUNT(*) as total_pedidos
                FROM pedidos p
                LEFT JOIN grupos_whatsapp g ON p.grupo_id = g.grupo_id
                GROUP BY p.grupo_id, g.nombre
                ORDER BY total_pedidos DESC
                LIMIT 5
            """)
            top_grupos = [{
                'grupo_id': row['grupo_id'],
                'grupo_nombre': row['grupo_nombre'],
                'total_pedidos': row['total_pedidos']
            } for row in db.cursor.fetchall()]

            # Top agentes por pedidos
            db.cursor.execute("""
                SELECT
                    agente_telefono,
                    agente_nombre,
                    COUNT(*) as total_pedidos
                FROM pedidos
                WHERE agente_telefono IS NOT NULL
                GROUP BY agente_telefono, agente_nombre
                ORDER BY total_pedidos DESC
                LIMIT 10
            """)
            top_agentes = [{
                'telefono': row['agente_telefono'],
                'nombre': row['agente_nombre'],
                'total_pedidos': row['total_pedidos']
            } for row in db.cursor.fetchall()]

            return jsonify({
                'success': True,
                'data': {
                    'total': counts['total'] or 0,
                    'esta_semana': counts['esta_semana'] or 0,
                    'hoy': counts['hoy'] or 0,
                    'top_grupos': top_grupos,
                    'top_agentes': top_agentes
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@pedidos_bp.route('/pedidos/<int:pedido_id>', methods=['DELETE'])
def delete_pedido(pedido_id):
    """
    Elimina un pedido (hard delete para limpiar spam).
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute(
                "DELETE FROM pedidos WHERE id = %s RETURNING id, grupo_id",
                (pedido_id,)
            )
            result = db.cursor.fetchone()

            if not result:
                return jsonify({'success': False, 'error': 'Pedido no encontrado'}), 404

            # Decrementar contador del grupo
            db.cursor.execute("""
                UPDATE grupos_whatsapp
                SET total_pedidos = GREATEST(total_pedidos - 1, 0)
                WHERE grupo_id = %s
            """, (result['grupo_id'],))

            db.conn.commit()

            return jsonify({
                'success': True,
                'message': 'Pedido eliminado exitosamente'
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
