"""
API endpoints para gestión de pedidos (demandas capturadas de grupos WhatsApp).
Estados: pendiente → en_proceso → procesado
"""

from flask import Blueprint, request, jsonify, Response
from src.db.database import DatabaseManager
import csv
import io

pedidos_bp = Blueprint('pedidos', __name__, url_prefix='/api')

ESTADOS_VALIDOS = ('pendiente', 'en_proceso', 'procesado', 'no_match')
NEXT_ESTADO = {'pendiente': 'en_proceso', 'en_proceso': 'procesado', 'procesado': 'pendiente', 'no_match': 'pendiente'}


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
        presupuesto_filter = request.args.get('presupuesto', '')

        offset = (page - 1) * per_page

        RANGOS_PRESUPUESTO = {
            '<300M': (0, 300000000),
            '300-500M': (300000000, 500000000),
            '500-800M': (500000001, 800000000),
            '800M-1.2B': (800000001, 1200000000),
            '>1.2B': (1200000001, None),  # >1.200 millones
        }

        with DatabaseManager() as db:
            conditions = []
            params = []

            if grupo_id:
                conditions.append("p.grupo_id = %s")
                params.append(grupo_id)

            if search_q:
                conditions.append("(p.texto_pedido ILIKE %s OR p.agente_nombre ILIKE %s OR p.agente_telefono ILIKE %s)")
                params.append(f"%{search_q}%")
                params.append(f"%{search_q}%")
                params.append(f"%{search_q}%")

            if estado_filter in ESTADOS_VALIDOS:
                conditions.append("p.estado = %s")
                params.append(estado_filter)

            if fecha_filter == 'today':
                conditions.append("p.fecha_captura >= CURRENT_DATE")
            elif fecha_filter == 'week':
                conditions.append("p.fecha_captura >= CURRENT_DATE - INTERVAL '7 days'")

            if presupuesto_filter in RANGOS_PRESUPUESTO:
                rango = RANGOS_PRESUPUESTO[presupuesto_filter]
                conditions.append("p.presupuesto_estimado >= %s")
                params.append(rango[0])
                if rango[1] is not None:
                    conditions.append("p.presupuesto_estimado <= %s")
                    params.append(rango[1])

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
                    p.texto_pedido, p.estado,
                    p.fecha_captura, p.presupuesto_estimado,
                    p.share_id, p.share_count, p.canal,
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
                'estado': row['estado'] or 'pendiente',
                'presupuesto_estimado': row['presupuesto_estimado'] if 'presupuesto_estimado' in row else None,
                'share_id': row['share_id'] if 'share_id' in row else None,
                'share_count': row['share_count'] if 'share_count' in row else None,
                'canal': row['canal'] if 'canal' in row else 'manual',
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


@pedidos_bp.route('/pedidos/<int:pedido_id>/share', methods=['PATCH'])
def set_share(pedido_id):
    """Asocia un share_id (link compartible) a un pedido."""
    try:
        data = request.get_json()
        share_id = data.get('share_id', '') if data else ''
        share_count = data.get('share_count', 0) if data else 0
        if not share_id:
            return jsonify({'success': False, 'error': 'share_id requerido'}), 400

        with DatabaseManager() as db:
            db.cursor.execute(
                "UPDATE pedidos SET share_id = %s, share_count = %s WHERE id = %s RETURNING id, share_id, share_count",
                (share_id, share_count, pedido_id)
            )
            result = db.cursor.fetchone()
            if not result:
                return jsonify({'success': False, 'error': 'Pedido no encontrado'}), 404
            db.conn.commit()

            return jsonify({
                'success': True,
                'data': {'id': result['id'], 'share_id': result['share_id'], 'share_count': result['share_count']}
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@pedidos_bp.route('/pedidos/<int:pedido_id>/enviar', methods=['POST'])
def enviar_pedido(pedido_id):
    """
    Ejecuta el flujo completo manualmente: buscar con AI, generar link, enviar WhatsApp.
    Usa la segunda linea de UltraMSG. Envia al numero personal del agente, NUNCA al grupo.
    """
    import os
    import uuid
    import requests as req

    try:
        with DatabaseManager() as db:
            db.cursor.execute("SELECT id, texto_pedido, agente_telefono, share_id FROM pedidos WHERE id = %s", (pedido_id,))
            pedido = db.cursor.fetchone()
            if not pedido:
                return jsonify({'success': False, 'error': 'Pedido no encontrado'}), 404

            texto_pedido = pedido['texto_pedido']
            agente_telefono = pedido['agente_telefono']

            if not agente_telefono or '@g.us' in agente_telefono:
                return jsonify({'success': False, 'error': 'No se puede enviar: sin telefono personal'}), 400

            # Verificar credenciales segunda linea
            instance_id = os.getenv('ULTRAMSG_RESPONDER_INSTANCE_ID')
            token = os.getenv('ULTRAMSG_RESPONDER_TOKEN')
            if not instance_id or not token:
                return jsonify({'success': False, 'error': 'Credenciales ULTRAMSG_RESPONDER no configuradas'}), 500

            # Usar share_id existente si ya tiene, o generar uno nuevo
            share_id = pedido['share_id'] if pedido['share_id'] else None
            count = 0

            if not share_id:
                # Buscar propiedades con AI
                from src.core.search_agent import PropertySearchAgent
                agent = PropertySearchAgent()
                search_response = agent.search(texto_pedido, limit=20, sender='manual_send')

                results = search_response.get('results', [])
                good_results = [r for r in results if r.get('match_score', 0) >= 40][:5]

                if not good_results:
                    db.cursor.execute(
                        "UPDATE pedidos SET estado = 'no_match', share_count = 0 WHERE id = %s",
                        (pedido_id,)
                    )
                    db.conn.commit()
                    return jsonify({'success': False, 'error': f'Sin match: {len(results)} resultados pero ninguno con score >= 40'}), 200

                property_ids = [r['id'] for r in good_results]
                count = len(property_ids)
                share_id = str(uuid.uuid4())[:12]
                db.cursor.execute("""
                    INSERT INTO shared_property_selections (share_id, property_ids, created_at, expires_at, view_count)
                    VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '30 days', 0)
                """, (share_id, property_ids))
                db.conn.commit()
            else:
                # Ya tiene link, obtener count
                db.cursor.execute("SELECT share_count FROM pedidos WHERE id = %s", (pedido_id,))
                row = db.cursor.fetchone()
                count = row['share_count'] or 0

            # Construir mensajes (2 separados)
            link = f"https://fyndercol.netlify.app/compartir/propiedades/{share_id}"
            message_text = (
                f"Hola, soy *Hernan Rios* de *Fynder* 🏡\n\n"
                f"Te comparto *{count} propiedades* para el pedido de tu cliente: _{texto_pedido}_\n\n"
                f"Antes de que las veas, asi trabajamos en Fynder — para que no haya sorpresas despues:\n\n"
                f"Comision total del *3%*:\n"
                f"• *1.25%* para ti como agente del comprador\n"
                f"• *1.25%* para el captador\n"
                f"• *0.5%* para Fynder, que te conectamos con la propiedad\n\n"
                f"Mira las opciones en el link 👇 y me confirmas si te sirve trabajar asi"
            )

            # Enviar 2 WhatsApps (SEGUNDA LINEA, al numero PERSONAL)
            import time
            api_url = f"https://api.ultramsg.com/{instance_id}/messages/chat"

            # Mensaje 1: texto
            resp = req.post(api_url, data={'token': token, 'to': agente_telefono, 'body': message_text}, timeout=30)
            if resp.status_code != 200:
                return jsonify({'success': False, 'error': f'Error UltraMSG mensaje 1: {resp.status_code}'}), 500

            # Mensaje 2: link solo (clickeable)
            time.sleep(1)
            resp2 = req.post(api_url, data={'token': token, 'to': agente_telefono, 'body': link}, timeout=30)
            if resp2.status_code != 200:
                return jsonify({'success': False, 'error': f'Error UltraMSG mensaje 2: {resp2.status_code}'}), 500

            # Actualizar pedido
            db.cursor.execute("""
                UPDATE pedidos SET share_id = %s, share_count = %s, estado = 'procesado', canal = 'auto'
                WHERE id = %s
            """, (share_id, count, pedido_id))
            db.conn.commit()

            return jsonify({
                'success': True,
                'data': {'id': pedido_id, 'share_id': share_id, 'share_count': count, 'enviado_a': agente_telefono}
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@pedidos_bp.route('/pedidos/auto-responder', methods=['GET'])
def get_auto_responder():
    """Retorna si el auto-responder esta habilitado."""
    try:
        with DatabaseManager() as db:
            db.cursor.execute("SELECT value FROM system_config WHERE key = 'auto_responder_enabled'")
            row = db.cursor.fetchone()
            enabled = row['value'] == 'true' if row else False
            return jsonify({'success': True, 'data': {'enabled': enabled}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@pedidos_bp.route('/pedidos/auto-responder', methods=['PATCH'])
def toggle_auto_responder():
    """Activa o desactiva el auto-responder."""
    try:
        data = request.get_json()
        enabled = data.get('enabled', False) if data else False
        value = 'true' if enabled else 'false'

        with DatabaseManager() as db:
            db.cursor.execute("""
                INSERT INTO system_config (key, value, updated_at)
                VALUES ('auto_responder_enabled', %s, CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = CURRENT_TIMESTAMP
            """, (value, value))
            db.conn.commit()
            return jsonify({'success': True, 'data': {'enabled': enabled}})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@pedidos_bp.route('/pedidos/export', methods=['GET'])
def export_pedidos():
    """Exporta pedidos como CSV para descargar en Excel."""
    try:
        estado_filter = request.args.get('estado', '')

        with DatabaseManager() as db:
            conditions = []
            params = []

            if estado_filter in ESTADOS_VALIDOS:
                conditions.append("p.estado = %s")
                params.append(estado_filter)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            db.cursor.execute(f"""
                SELECT
                    p.id,
                    p.fecha_captura,
                    p.agente_nombre,
                    p.agente_telefono,
                    p.texto_pedido,
                    p.presupuesto_estimado,
                    p.estado,
                    p.canal,
                    p.share_id,
                    p.share_count,
                    g.nombre as grupo_nombre
                FROM pedidos p
                LEFT JOIN grupos_whatsapp g ON p.grupo_id = g.grupo_id
                {where_clause}
                ORDER BY p.fecha_captura DESC
            """, params)

            rows = db.cursor.fetchall()

            output = io.StringIO()
            output.write('\ufeff')  # BOM for Excel UTF-8
            writer = csv.writer(output)

            writer.writerow([
                'ID', 'Fecha', 'Agente', 'Telefono', 'Pedido',
                'Presupuesto', 'Estado', 'Canal', 'Link Fynder', 'Propiedades', 'Grupo'
            ])

            for row in rows:
                presupuesto = row['presupuesto_estimado']
                pres_fmt = f"${presupuesto:,.0f}" if presupuesto else ''
                fecha = row['fecha_captura'].strftime('%Y-%m-%d %H:%M') if row['fecha_captura'] else ''
                share_link = f"https://fyndercol.netlify.app/compartir/propiedades/{row['share_id']}" if row['share_id'] else ''

                writer.writerow([
                    row['id'],
                    fecha,
                    row['agente_nombre'] or '',
                    row['agente_telefono'] or '',
                    row['texto_pedido'] or '',
                    pres_fmt,
                    row['estado'] or '',
                    row['canal'] or 'manual',
                    share_link,
                    row['share_count'] or '',
                    row['grupo_nombre'] or '',
                ])

            response = Response(
                output.getvalue(),
                mimetype='text/csv; charset=utf-8',
                headers={
                    'Content-Disposition': 'attachment; filename=pedidos_fynder.csv',
                    'Content-Type': 'text/csv; charset=utf-8',
                }
            )
            return response

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
                    COUNT(*) FILTER (WHERE estado = 'no_match') as no_match,
                    COUNT(*) FILTER (WHERE fecha_captura >= CURRENT_DATE - INTERVAL '7 days') as esta_semana,
                    COUNT(*) FILTER (WHERE fecha_captura >= CURRENT_DATE - INTERVAL '1 day') as hoy
                FROM pedidos
            """)
            c = db.cursor.fetchone()
            total = c['total'] or 0
            procesados = c['procesados'] or 0
            en_proceso = c['en_proceso'] or 0
            pendientes = c['pendientes'] or 0
            no_match = c['no_match'] or 0
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

            # Distribucion por rango de presupuesto
            db.cursor.execute("""
                SELECT
                    CASE
                        WHEN presupuesto_estimado < 300000000 THEN '<$300M'
                        WHEN presupuesto_estimado BETWEEN 300000000 AND 500000000 THEN '$300-500M'
                        WHEN presupuesto_estimado BETWEEN 500000001 AND 800000000 THEN '$500-800M'
                        WHEN presupuesto_estimado BETWEEN 800000001 AND 1200000000 THEN '$800-1.200M'
                        WHEN presupuesto_estimado > 1200000000 THEN '>$1.200M'
                    END as rango,
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE estado = 'procesado') as procesados,
                    COUNT(*) FILTER (WHERE estado = 'no_match') as no_match,
                    COUNT(*) FILTER (WHERE estado IN ('pendiente', 'en_proceso')) as sin_gestionar
                FROM pedidos
                WHERE presupuesto_estimado IS NOT NULL AND presupuesto_estimado > 0
                GROUP BY rango
                ORDER BY MIN(presupuesto_estimado)
            """)
            por_presupuesto = [{
                'rango': row['rango'],
                'total': row['total'],
                'procesados': row['procesados'],
                'no_match': row['no_match'],
                'sin_gestionar': row['sin_gestionar']
            } for row in db.cursor.fetchall()]

            # Canal de procesamiento (auto vs manual)
            db.cursor.execute("""
                SELECT
                    COALESCE(canal, 'manual') as canal,
                    COUNT(*) as total
                FROM pedidos
                WHERE estado = 'procesado'
                GROUP BY COALESCE(canal, 'manual')
            """)
            por_canal = [{
                'canal': row['canal'],
                'total': row['total']
            } for row in db.cursor.fetchall()]

            return jsonify({
                'success': True,
                'data': {
                    'total': total,
                    'procesados': procesados,
                    'en_proceso': en_proceso,
                    'pendientes': pendientes,
                    'no_match': no_match,
                    'tasa_respuesta': tasa_respuesta,
                    'tasa_en_gestion': tasa_en_gestion,
                    'esta_semana': c['esta_semana'] or 0,
                    'semana_pasada': weekly['semana_pasada'] or 0,
                    'hoy': c['hoy'] or 0,
                    'pedidos_por_dia': pedidos_por_dia,
                    'top_agentes': top_agentes,
                    'por_grupo': por_grupo,
                    'por_presupuesto': por_presupuesto,
                    'por_canal': por_canal
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
