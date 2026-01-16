"""
Activity API Blueprint - Módulo de Actividad del Sistema

Endpoints para métricas de:
- Captación de propiedades (WhatsApp)
- Actividad del Chat (búsquedas)
- Rendimiento de Agentes (AccesoChat)
"""

from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
from src.db.database import DatabaseManager
import pytz

activity_bp = Blueprint('activity', __name__, url_prefix='/api/activity')

# Zona horaria de Bogotá
BOGOTA_TZ = pytz.timezone('America/Bogota')


def get_bogota_now():
    """Get current time in Bogota timezone."""
    return datetime.now(BOGOTA_TZ)


def get_days_param():
    """Obtener parámetro days de query string, default 30"""
    try:
        return int(request.args.get('days', 30))
    except ValueError:
        return 30


@activity_bp.route('/overview', methods=['GET'])
def get_activity_overview():
    """
    GET /api/activity/overview?days=30

    KPIs principales del sistema:
    - Total capturas
    - Total búsquedas
    - Agentes activos
    - Conversaciones
    - Tendencias vs período anterior
    """
    try:
        days = get_days_param()
        start_date = get_bogota_now() - timedelta(days=days)
        prev_start_date = start_date - timedelta(days=days)

        with DatabaseManager() as db:
            # KPIs actuales - Capturas
            db.cursor.execute("""
                SELECT COUNT(*) as count FROM propiedades
                WHERE origen IN ('Wasi_Captado', 'Tu360_Captado', 'Lobbie_Captado')
                AND fecha_creacion >= %s
            """, (start_date,))
            total_captures = db.cursor.fetchone()['count']

            # Búsquedas en chat
            db.cursor.execute("""
                SELECT COUNT(*) as count FROM chat_usage_log
                WHERE accion = 'search' AND fecha >= %s
            """, (start_date,))
            total_searches = db.cursor.fetchone()['count']

            # Usuarios activos
            db.cursor.execute("""
                SELECT COUNT(DISTINCT user_id) as count FROM chat_usage_log
                WHERE fecha >= %s
            """, (start_date,))
            active_users = db.cursor.fetchone()['count']

            # Conversaciones
            db.cursor.execute("""
                SELECT COUNT(*) as count FROM conversaciones_busqueda
                WHERE fecha_creacion >= %s
            """, (start_date,))
            total_conversations = db.cursor.fetchone()['count']

            # KPIs período anterior - Capturas
            db.cursor.execute("""
                SELECT COUNT(*) as count FROM propiedades
                WHERE origen IN ('Wasi_Captado', 'Tu360_Captado', 'Lobbie_Captado')
                AND fecha_creacion >= %s AND fecha_creacion < %s
            """, (prev_start_date, start_date))
            prev_captures = db.cursor.fetchone()['count']

            # KPIs período anterior - Búsquedas
            db.cursor.execute("""
                SELECT COUNT(*) as count FROM chat_usage_log
                WHERE accion = 'search' AND fecha >= %s AND fecha < %s
            """, (prev_start_date, start_date))
            prev_searches = db.cursor.fetchone()['count']

            # Capturas hoy
            today_start = get_bogota_now().replace(hour=0, minute=0, second=0, microsecond=0)
            db.cursor.execute("""
                SELECT COUNT(*) as count FROM propiedades
                WHERE origen IN ('Wasi_Captado', 'Tu360_Captado', 'Lobbie_Captado')
                AND fecha_creacion >= %s
            """, (today_start,))
            today_captures = db.cursor.fetchone()['count']

            # Búsquedas hoy
            db.cursor.execute("""
                SELECT COUNT(*) as count FROM chat_usage_log
                WHERE accion = 'search' AND fecha >= %s
            """, (today_start,))
            today_searches = db.cursor.fetchone()['count']

            # Calcular tendencias
            def calc_trend(current_val, prev_val):
                if not prev_val or prev_val == 0:
                    return 0.0
                return round(((current_val - prev_val) / prev_val) * 100, 1)

            captures_trend = calc_trend(total_captures, prev_captures)
            searches_trend = calc_trend(total_searches, prev_searches)

            return jsonify({
                'success': True,
                'data': {
                    'total_captures': total_captures,
                    'total_searches': total_searches,
                    'active_users': active_users,
                    'total_conversations': total_conversations,
                    'captures_trend': captures_trend,
                    'searches_trend': searches_trend,
                    'today_captures': today_captures,
                    'today_searches': today_searches,
                    'period_days': days
                }
            })

    except Exception as e:
        print(f"Error en activity overview: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@activity_bp.route('/captures', methods=['GET'])
def get_capture_activity():
    """
    GET /api/activity/captures?days=30

    Métricas de captación de propiedades:
    - Por día (timezone Bogotá)
    - Por fuente (Wasi, Tu360, Lobbie)
    - Top agentes captadores
    """
    try:
        days = get_days_param()
        start_date = get_bogota_now() - timedelta(days=days)

        with DatabaseManager() as db:
            # Capturas por día y fuente (convertir a zona horaria Bogotá)
            db.cursor.execute("""
                SELECT
                    DATE(fecha_creacion AT TIME ZONE 'America/Bogota') as date,
                    origen,
                    COUNT(*) as count
                FROM propiedades
                WHERE origen IN ('Wasi_Captado', 'Tu360_Captado', 'Lobbie_Captado')
                AND fecha_creacion >= %s
                GROUP BY DATE(fecha_creacion AT TIME ZONE 'America/Bogota'), origen
                ORDER BY date
            """, (start_date,))
            by_day_raw = db.cursor.fetchall()

            # Procesar datos por día - incluir Lobbie
            days_data = {}
            for row in by_day_raw:
                date_str = row['date'].isoformat() if row['date'] else None
                if date_str not in days_data:
                    days_data[date_str] = {'date': date_str, 'wasi': 0, 'tu360': 0, 'lobbie': 0, 'total': 0}

                if row['origen'] == 'Wasi_Captado':
                    days_data[date_str]['wasi'] = row['count']
                elif row['origen'] == 'Tu360_Captado':
                    days_data[date_str]['tu360'] = row['count']
                elif row['origen'] == 'Lobbie_Captado':
                    days_data[date_str]['lobbie'] = row['count']
                days_data[date_str]['total'] += row['count']

            # Totales por fuente - incluir Lobbie
            db.cursor.execute("""
                SELECT
                    origen,
                    COUNT(*) as count
                FROM propiedades
                WHERE origen IN ('Wasi_Captado', 'Tu360_Captado', 'Lobbie_Captado')
                AND fecha_creacion >= %s
                GROUP BY origen
            """, (start_date,))
            by_source_raw = db.cursor.fetchall()

            source_totals = {'wasi': 0, 'tu360': 0, 'lobbie': 0}
            for row in by_source_raw:
                if row['origen'] == 'Wasi_Captado':
                    source_totals['wasi'] = row['count']
                elif row['origen'] == 'Tu360_Captado':
                    source_totals['tu360'] = row['count']
                elif row['origen'] == 'Lobbie_Captado':
                    source_totals['lobbie'] = row['count']

            # Top agentes captadores
            db.cursor.execute("""
                SELECT
                    p.agente_captador_telefono as phone,
                    a.nombre as name,
                    COUNT(*) as captures,
                    MAX(p.fecha_creacion) as last_capture
                FROM propiedades p
                LEFT JOIN agentes a ON p.agente_captador_telefono = a.telefono
                WHERE p.origen IN ('Wasi_Captado', 'Tu360_Captado', 'Lobbie_Captado')
                AND p.fecha_creacion >= %s
                AND p.agente_captador_telefono IS NOT NULL
                GROUP BY p.agente_captador_telefono, a.nombre
                ORDER BY captures DESC
                LIMIT 10
            """, (start_date,))
            top_capturers_raw = db.cursor.fetchall()

            # Capturas hoy (zona horaria Bogotá)
            today_start = get_bogota_now().replace(hour=0, minute=0, second=0, microsecond=0)
            db.cursor.execute("""
                SELECT COUNT(*) as count FROM propiedades
                WHERE origen IN ('Wasi_Captado', 'Tu360_Captado', 'Lobbie_Captado')
                AND fecha_creacion >= %s
            """, (today_start,))
            today_count = db.cursor.fetchone()['count']

            return jsonify({
                'success': True,
                'data': {
                    'by_day': list(days_data.values()),
                    'by_source': source_totals,
                    'top_capturers': [
                        {
                            'phone': row['phone'],
                            'name': row['name'],
                            'captures': row['captures'],
                            'last_capture': row['last_capture'].isoformat() if row['last_capture'] else None
                        }
                        for row in top_capturers_raw
                    ],
                    'today_count': today_count,
                    'total': source_totals['wasi'] + source_totals['tu360'] + source_totals['lobbie'],
                    'period_days': days
                }
            })

    except Exception as e:
        print(f"Error en capture activity: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@activity_bp.route('/chat', methods=['GET'])
def get_chat_activity():
    """
    GET /api/activity/chat?days=30

    Métricas de actividad del chat:
    - Búsquedas por día (timezone Bogotá)
    - Horas pico (timezone Bogotá)
    - Tipos de búsqueda (criterios populares)
    - Ciudades/ubicaciones buscadas
    - Tiempos de respuesta promedio
    """
    try:
        days = get_days_param()
        start_date = get_bogota_now() - timedelta(days=days)

        with DatabaseManager() as db:
            # Actividad por día (timezone Bogotá)
            db.cursor.execute("""
                SELECT
                    DATE(fecha AT TIME ZONE 'America/Bogota') as date,
                    COUNT(*) as total_actions,
                    COUNT(CASE WHEN accion = 'search' THEN 1 END) as searches,
                    COUNT(CASE WHEN accion = 'login' THEN 1 END) as logins
                FROM chat_usage_log
                WHERE fecha >= %s
                GROUP BY DATE(fecha AT TIME ZONE 'America/Bogota')
                ORDER BY date
            """, (start_date,))
            by_day_raw = db.cursor.fetchall()

            # Horas pico de búsqueda (timezone Bogotá)
            db.cursor.execute("""
                SELECT
                    EXTRACT(HOUR FROM fecha AT TIME ZONE 'America/Bogota')::integer as hour,
                    COUNT(*) as count
                FROM chat_usage_log
                WHERE accion = 'search' AND fecha >= %s
                GROUP BY EXTRACT(HOUR FROM fecha AT TIME ZONE 'America/Bogota')
                ORDER BY hour
            """, (start_date,))
            peak_hours_raw = db.cursor.fetchall()

            # Tipos de propiedad buscados
            db.cursor.execute("""
                SELECT
                    criterios_mensaje->>'tipo_propiedad' as tipo,
                    COUNT(*) as count
                FROM mensajes_conversacion
                WHERE criterios_mensaje IS NOT NULL
                AND criterios_mensaje->>'tipo_propiedad' IS NOT NULL
                AND fecha_creacion >= %s
                GROUP BY criterios_mensaje->>'tipo_propiedad'
                ORDER BY count DESC
                LIMIT 10
            """, (start_date,))
            tipos_raw = db.cursor.fetchall()

            # Ciudades/Ubicaciones buscadas (usando array de ubicaciones)
            db.cursor.execute("""
                SELECT
                    elem as ciudad,
                    COUNT(*) as count
                FROM mensajes_conversacion
                CROSS JOIN LATERAL jsonb_array_elements_text(criterios_mensaje->'ubicaciones') as elem
                WHERE fecha_creacion >= %s
                AND criterios_mensaje ? 'ubicaciones'
                GROUP BY elem
                ORDER BY count DESC
                LIMIT 10
            """, (start_date,))
            ciudades_raw = db.cursor.fetchall()

            # Combinar criterios para compatibilidad con frontend
            search_criteria = []
            for row in tipos_raw:
                search_criteria.append({
                    'tipo': row['tipo'],
                    'ciudad': None,
                    'count': row['count']
                })
            for row in ciudades_raw:
                search_criteria.append({
                    'tipo': None,
                    'ciudad': row['ciudad'],
                    'count': row['count']
                })

            # Tiempos de respuesta promedio
            db.cursor.execute("""
                SELECT
                    AVG(tiempo_respuesta_ms) as avg_response_time,
                    AVG(total_resultados) as avg_results
                FROM mensajes_conversacion
                WHERE fecha_creacion >= %s
                AND tiempo_respuesta_ms IS NOT NULL
            """, (start_date,))
            response_times = db.cursor.fetchone()

            # Totales
            db.cursor.execute("""
                SELECT
                    COUNT(CASE WHEN accion = 'search' THEN 1 END) as total_searches,
                    COUNT(DISTINCT user_id) as unique_users,
                    COUNT(DISTINCT DATE(fecha AT TIME ZONE 'America/Bogota')) as active_days
                FROM chat_usage_log
                WHERE fecha >= %s
            """, (start_date,))
            totals = db.cursor.fetchone()

            return jsonify({
                'success': True,
                'data': {
                    'by_day': [
                        {
                            'date': row['date'].isoformat() if row['date'] else None,
                            'searches': row['searches'],
                            'logins': row['logins'],
                            'total_actions': row['total_actions']
                        }
                        for row in by_day_raw
                    ],
                    'peak_hours': [
                        {'hour': row['hour'], 'count': row['count']}
                        for row in peak_hours_raw
                    ],
                    'search_criteria': search_criteria,
                    'avg_response_time_ms': float(response_times['avg_response_time'] or 0),
                    'avg_results_per_search': float(response_times['avg_results'] or 0),
                    'total_searches': totals['total_searches'] or 0,
                    'unique_users': totals['unique_users'] or 0,
                    'period_days': days
                }
            })

    except Exception as e:
        print(f"Error en chat activity: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@activity_bp.route('/agents', methods=['GET'])
def get_agent_activity():
    """
    GET /api/activity/agents?days=30

    Métricas de agentes (usuarios AccesoChat):
    - Ranking por búsquedas
    - Estadísticas generales
    """
    try:
        days = get_days_param()
        start_date = get_bogota_now() - timedelta(days=days)

        with DatabaseManager() as db:
            # Ranking de agentes
            db.cursor.execute("""
                SELECT
                    cu.id,
                    cu.nombre,
                    cu.email,
                    cu.total_busquedas,
                    cu.total_sesiones,
                    COUNT(cul.id) as searches_period,
                    MAX(cul.fecha) as last_activity
                FROM chat_users cu
                LEFT JOIN chat_usage_log cul ON cu.id = cul.user_id
                    AND cul.accion = 'search'
                    AND cul.fecha >= %s
                WHERE cu.activo = true
                GROUP BY cu.id, cu.nombre, cu.email, cu.total_busquedas, cu.total_sesiones
                ORDER BY searches_period DESC, cu.total_busquedas DESC
            """, (start_date,))
            agents_raw = db.cursor.fetchall()

            # Estadísticas generales
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total_agents,
                    COUNT(CASE WHEN activo = true THEN 1 END) as active_agents,
                    COALESCE(SUM(total_busquedas), 0) as total_searches_all_time,
                    COALESCE(AVG(total_busquedas), 0) as avg_searches_per_agent
                FROM chat_users
            """)
            stats = db.cursor.fetchone()

            # Top agent
            top_agent = agents_raw[0] if agents_raw else None

            return jsonify({
                'success': True,
                'data': {
                    'agents': [
                        {
                            'id': row['id'],
                            'nombre': row['nombre'],
                            'email': row['email'],
                            'total_busquedas': row['total_busquedas'] or 0,
                            'total_sesiones': row['total_sesiones'] or 0,
                            'searches_period': row['searches_period'] or 0,
                            'last_activity': row['last_activity'].isoformat() if row['last_activity'] else None
                        }
                        for row in agents_raw
                    ],
                    'total_agents': stats['total_agents'] or 0,
                    'active_agents': stats['active_agents'] or 0,
                    'avg_searches_per_agent': float(stats['avg_searches_per_agent'] or 0),
                    'top_agent': {
                        'nombre': top_agent['nombre'],
                        'searches_period': top_agent['searches_period'] or 0
                    } if top_agent else None,
                    'period_days': days
                }
            })

    except Exception as e:
        print(f"Error en agent activity: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@activity_bp.route('/hourly', methods=['GET'])
def get_hourly_activity():
    """
    GET /api/activity/hourly?days=7

    Distribución por hora para heatmap (timezone Bogotá):
    - Capturas por hora y día de semana
    - Búsquedas por hora y día de semana
    """
    try:
        days = get_days_param()
        if days > 30:
            days = 30  # Limitar para heatmap
        start_date = get_bogota_now() - timedelta(days=days)

        with DatabaseManager() as db:
            # Capturas por hora y día de semana (timezone Bogotá)
            db.cursor.execute("""
                SELECT
                    EXTRACT(HOUR FROM fecha_creacion AT TIME ZONE 'America/Bogota')::integer as hour,
                    EXTRACT(DOW FROM fecha_creacion AT TIME ZONE 'America/Bogota')::integer as day_of_week,
                    COUNT(*) as count
                FROM propiedades
                WHERE origen IN ('Wasi_Captado', 'Tu360_Captado', 'Lobbie_Captado')
                AND fecha_creacion >= %s
                GROUP BY EXTRACT(HOUR FROM fecha_creacion AT TIME ZONE 'America/Bogota'),
                         EXTRACT(DOW FROM fecha_creacion AT TIME ZONE 'America/Bogota')
            """, (start_date,))
            capture_hourly_raw = db.cursor.fetchall()

            # Búsquedas por hora y día de semana (timezone Bogotá)
            db.cursor.execute("""
                SELECT
                    EXTRACT(HOUR FROM fecha AT TIME ZONE 'America/Bogota')::integer as hour,
                    EXTRACT(DOW FROM fecha AT TIME ZONE 'America/Bogota')::integer as day_of_week,
                    COUNT(*) as count
                FROM chat_usage_log
                WHERE accion = 'search' AND fecha >= %s
                GROUP BY EXTRACT(HOUR FROM fecha AT TIME ZONE 'America/Bogota'),
                         EXTRACT(DOW FROM fecha AT TIME ZONE 'America/Bogota')
            """, (start_date,))
            search_hourly_raw = db.cursor.fetchall()

            # Crear matriz de datos
            # day_of_week: 0=Domingo, 1=Lunes, ..., 6=Sábado
            hourly_data = []

            # Mapear capturas
            capture_map = {}
            for row in capture_hourly_raw:
                key = (row['hour'], row['day_of_week'])
                capture_map[key] = row['count']

            # Mapear búsquedas
            search_map = {}
            for row in search_hourly_raw:
                key = (row['hour'], row['day_of_week'])
                search_map[key] = row['count']

            # Construir datos completos
            for day in range(7):  # 0-6 (Dom-Sab)
                for hour in range(24):  # 0-23
                    key = (hour, day)
                    hourly_data.append({
                        'hour': hour,
                        'day_of_week': day,
                        'captures': capture_map.get(key, 0),
                        'searches': search_map.get(key, 0)
                    })

            # Horas pico combinadas
            combined_by_hour = {}
            for item in hourly_data:
                h = item['hour']
                if h not in combined_by_hour:
                    combined_by_hour[h] = {'captures': 0, 'searches': 0}
                combined_by_hour[h]['captures'] += item['captures']
                combined_by_hour[h]['searches'] += item['searches']

            peak_hours = sorted(
                [{'hour': h, **v} for h, v in combined_by_hour.items()],
                key=lambda x: x['captures'] + x['searches'],
                reverse=True
            )[:5]

            return jsonify({
                'success': True,
                'data': {
                    'hourly_matrix': hourly_data,
                    'peak_hours': peak_hours,
                    'period_days': days
                }
            })

    except Exception as e:
        print(f"Error en hourly activity: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
