"""
Dashboard API Blueprint - Overview del sistema
"""

from flask import Blueprint, jsonify
from datetime import datetime, timedelta
from src.db.database import DatabaseManager
import pytz

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api/dashboard')

BOGOTA_TZ = pytz.timezone('America/Bogota')


def get_bogota_now():
    return datetime.now(BOGOTA_TZ)


@dashboard_bp.route('/overview', methods=['GET'])
def get_overview():
    """
    GET /api/dashboard/overview

    Resumen ejecutivo del sistema para el Dashboard principal
    """
    try:
        now = get_bogota_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        with DatabaseManager() as db:
            # ============================================
            # PROPIEDADES
            # ============================================
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN activa THEN 1 END) as activas
                FROM propiedades
            """)
            props = db.cursor.fetchone()

            # Capturas esta semana
            db.cursor.execute("""
                SELECT COUNT(*) as count FROM propiedades
                WHERE origen IN ('Wasi_Captado', 'Tu360_Captado', 'Lobbie_Captado')
                AND fecha_creacion >= %s
            """, (week_ago,))
            captures_week = db.cursor.fetchone()['count']

            # Capturas hoy
            db.cursor.execute("""
                SELECT COUNT(*) as count FROM propiedades
                WHERE origen IN ('Wasi_Captado', 'Tu360_Captado', 'Lobbie_Captado')
                AND fecha_creacion >= %s
            """, (today_start,))
            captures_today = db.cursor.fetchone()['count']

            # ============================================
            # DEALS / SOLICITUDES
            # ============================================
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN estado = 'Pendiente_Seleccion' THEN 1 END) as pendientes,
                    COUNT(CASE WHEN estado = 'Seleccionado' THEN 1 END) as seleccionados,
                    COUNT(CASE WHEN estado = 'Cerrado_Exitoso' THEN 1 END) as exitosos,
                    COUNT(CASE WHEN estado = 'Cerrado_Fallido' THEN 1 END) as fallidos
                FROM solicitudes_mercado
            """)
            deals = db.cursor.fetchone()

            # Deals creados esta semana
            db.cursor.execute("""
                SELECT COUNT(*) as count FROM solicitudes_mercado
                WHERE fecha_solicitud >= %s
            """, (week_ago,))
            deals_week = db.cursor.fetchone()['count']

            # ============================================
            # USUARIOS CHAT
            # ============================================
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN activo THEN 1 END) as activos,
                    COALESCE(SUM(total_busquedas), 0) as total_busquedas
                FROM chat_users
            """)
            chat_users = db.cursor.fetchone()

            # Busquedas esta semana
            db.cursor.execute("""
                SELECT COUNT(*) as count FROM chat_usage_log
                WHERE accion = 'search' AND fecha >= %s
            """, (week_ago,))
            searches_week = db.cursor.fetchone()['count']

            # ============================================
            # GRUPOS WHATSAPP
            # ============================================
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN activo THEN 1 END) as activos,
                    COALESCE(SUM(total_capturas), 0) as total_capturas
                FROM grupos_whatsapp
            """)
            grupos = db.cursor.fetchone()

            # ============================================
            # AGENTES
            # ============================================
            db.cursor.execute("""
                SELECT COUNT(*) as total FROM agentes
            """)
            agentes_total = db.cursor.fetchone()['total']

            # ============================================
            # COSTOS IA (mes actual)
            # ============================================
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            db.cursor.execute("""
                SELECT
                    COUNT(*) as total_calls,
                    COALESCE(SUM(estimated_cost_usd), 0) as total_cost_usd,
                    COALESCE(SUM(total_tokens), 0) as total_tokens
                FROM ai_usage_log
                WHERE created_at >= %s
            """, (month_start,))
            ai_costs = db.cursor.fetchone()

            # ============================================
            # ACTIVIDAD RECIENTE (últimas 24h)
            # ============================================
            yesterday = now - timedelta(hours=24)

            # Últimas capturas
            db.cursor.execute("""
                SELECT
                    id, titulo, zona, ciudad, origen,
                    agente_captador_telefono, fecha_creacion
                FROM propiedades
                WHERE origen IN ('Wasi_Captado', 'Tu360_Captado', 'Lobbie_Captado')
                ORDER BY fecha_creacion DESC
                LIMIT 5
            """)
            recent_captures = [{
                'id': row['id'],
                'titulo': row['titulo'],
                'zona': row['zona'],
                'ciudad': row['ciudad'],
                'origen': row['origen'],
                'agente': row['agente_captador_telefono'],
                'fecha': row['fecha_creacion'].isoformat() if row['fecha_creacion'] else None
            } for row in db.cursor.fetchall()]

            # Últimos deals CERRADOS (solo los que generan comisión)
            db.cursor.execute("""
                SELECT
                    id, agente_telefono, query_original, estado, fecha_solicitud, fecha_cambio_estado
                FROM solicitudes_mercado
                WHERE estado = 'Cerrado_Exitoso'
                ORDER BY fecha_cambio_estado DESC
                LIMIT 5
            """)
            recent_deals = [{
                'id': row['id'],
                'contacto': row['agente_telefono'],
                'criterios': row['query_original'],
                'estado': row['estado'],
                'fecha': row['fecha_cambio_estado'].isoformat() if row['fecha_cambio_estado'] else (row['fecha_solicitud'].isoformat() if row['fecha_solicitud'] else None)
            } for row in db.cursor.fetchall()]

            # Últimas búsquedas del chat
            db.cursor.execute("""
                SELECT
                    cul.id, cu.nombre, cul.accion, cul.fecha,
                    cul.detalles
                FROM chat_usage_log cul
                JOIN chat_users cu ON cul.user_id = cu.id
                WHERE cul.accion = 'search'
                ORDER BY cul.fecha DESC
                LIMIT 5
            """)
            recent_searches = [{
                'id': row['id'],
                'usuario': row['nombre'],
                'accion': row['accion'],
                'detalles': row['detalles'],
                'fecha': row['fecha'].isoformat() if row['fecha'] else None
            } for row in db.cursor.fetchall()]

            return jsonify({
                'success': True,
                'data': {
                    # KPIs principales
                    'propiedades': {
                        'total': props['total'],
                        'activas': props['activas'],
                        'capturas_semana': captures_week,
                        'capturas_hoy': captures_today
                    },
                    'deals': {
                        'total': deals['total'],
                        'pendientes': deals['pendientes'],
                        'seleccionados': deals['seleccionados'],
                        'exitosos': deals['exitosos'],
                        'fallidos': deals['fallidos'],
                        'nuevos_semana': deals_week
                    },
                    'chat': {
                        'usuarios_total': chat_users['total'],
                        'usuarios_activos': chat_users['activos'],
                        'busquedas_total': int(chat_users['total_busquedas']),
                        'busquedas_semana': searches_week
                    },
                    'whatsapp': {
                        'grupos_total': grupos['total'],
                        'grupos_activos': grupos['activos'],
                        'capturas_total': int(grupos['total_capturas'])
                    },
                    'agentes': {
                        'total': agentes_total
                    },
                    'ai_costs': {
                        'total_calls': ai_costs['total_calls'],
                        'total_cost_usd': float(ai_costs['total_cost_usd']),
                        'total_tokens': int(ai_costs['total_tokens'])
                    },
                    # Actividad reciente
                    'actividad': {
                        'capturas': recent_captures,
                        'deals': recent_deals,
                        'busquedas': recent_searches
                    },
                    # Metadata
                    'generado_at': now.isoformat()
                }
            })

    except Exception as e:
        print(f"Error en dashboard overview: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
