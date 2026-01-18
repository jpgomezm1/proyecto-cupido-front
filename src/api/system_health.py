#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System Health API - Endpoints para monitoreo de salud del sistema
"""

from flask import Blueprint, request, jsonify
from src.db.database import DatabaseManager
from datetime import datetime, timedelta
import time
import pytz

system_health_bp = Blueprint('system_health', __name__, url_prefix='/api/health')

# Zona horaria de Bogotá
BOGOTA_TZ = pytz.timezone('America/Bogota')


def get_bogota_now():
    """Get current time in Bogota timezone."""
    return datetime.now(BOGOTA_TZ)


def get_date_range(days: int):
    """Get start date for the given number of days ago in Bogota timezone."""
    end = get_bogota_now()
    start = end - timedelta(days=days)
    return start, end


def get_status_from_success_rate(rate: float) -> str:
    """Determine status based on success rate."""
    if rate >= 95:
        return 'healthy'
    elif rate >= 85:
        return 'warning'
    return 'critical'


def get_status_from_response_time(ms: float) -> str:
    """Determine status based on response time in ms."""
    if ms <= 2000:
        return 'healthy'
    elif ms <= 5000:
        return 'warning'
    return 'critical'


def get_status_from_error_count(count: int) -> str:
    """Determine status based on error count."""
    if count <= 5:
        return 'healthy'
    elif count <= 15:
        return 'warning'
    return 'critical'


def get_status_from_connection_time(ms: float) -> str:
    """Determine status based on connection time."""
    if ms <= 100:
        return 'healthy'
    elif ms <= 500:
        return 'warning'
    return 'critical'


def calculate_change(current: float, previous: float) -> dict:
    """
    Calcula el cambio porcentual entre dos valores.
    Retorna dirección (up/down/stable) y porcentaje de cambio.
    """
    if previous == 0:
        if current == 0:
            return {"current": current, "previous": previous, "change_percent": 0, "direction": "stable"}
        return {"current": current, "previous": previous, "change_percent": 100, "direction": "up"}

    change = ((current - previous) / previous) * 100
    if change > 1:
        direction = "up"
    elif change < -1:
        direction = "down"
    else:
        direction = "stable"

    return {
        "current": current,
        "previous": previous,
        "change_percent": round(abs(change), 1),
        "direction": direction
    }


@system_health_bp.route('/overview', methods=['GET'])
def get_overview():
    """Get system-wide health summary with temporal comparisons."""
    try:
        with DatabaseManager() as db:
            # ============================================
            # MÉTRICAS ACTUALES (últimas 24h)
            # ============================================

            # Errors in last 24h
            db.cursor.execute("""
                SELECT COUNT(*) as error_count
                FROM eventos_log
                WHERE resultado = 'Error'
                AND fecha_evento >= NOW() - INTERVAL '24 hours'
            """)
            errors_24h = db.cursor.fetchone()['error_count']

            # AI success rate (last 24h)
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total_calls,
                    COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as successful_calls,
                    COALESCE(AVG(response_time_ms), 0) as avg_response_time
                FROM ai_usage_log
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            """)
            ai_stats = db.cursor.fetchone()
            ai_total = ai_stats['total_calls'] or 0
            ai_successful = ai_stats['successful_calls'] or 0
            ai_success_rate = (ai_successful / ai_total * 100) if ai_total > 0 else 100
            avg_response_time = float(ai_stats['avg_response_time'] or 0)

            # Search stats (last 24h)
            db.cursor.execute("""
                SELECT COUNT(*) as total_searches
                FROM solicitudes_mercado
                WHERE fecha_solicitud >= NOW() - INTERVAL '24 hours'
            """)
            searches_24h = db.cursor.fetchone()['total_searches']

            # Bot activity (last 24h)
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total_messages,
                    COALESCE(SUM(CASE WHEN resultado = 'Exitoso' THEN 1 ELSE 0 END), 0) as successful
                FROM eventos_log
                WHERE tipo_evento IN ('Mensaje_Grupo', 'Mensaje_Privado', 'Webhook_Received',
                                      'Solicitud_Mercado', 'Propiedad_Captada')
                AND fecha_evento >= NOW() - INTERVAL '24 hours'
            """)
            bot_stats = db.cursor.fetchone()
            bot_total = bot_stats['total_messages'] or 0
            bot_successful = bot_stats['successful'] or 0
            bot_success_rate = (bot_successful / bot_total * 100) if bot_total > 0 else 100

            # Active properties
            db.cursor.execute("""
                SELECT COUNT(*) as count FROM propiedades WHERE activa = true
            """)
            active_properties = db.cursor.fetchone()['count']

            # ============================================
            # MÉTRICAS DE AYER (24-48h) para comparativas
            # ============================================

            # Errors yesterday (24-48h ago)
            db.cursor.execute("""
                SELECT COUNT(*) as error_count
                FROM eventos_log
                WHERE resultado = 'Error'
                AND fecha_evento >= NOW() - INTERVAL '48 hours'
                AND fecha_evento < NOW() - INTERVAL '24 hours'
            """)
            errors_yesterday = db.cursor.fetchone()['error_count']

            # AI stats yesterday (24-48h ago)
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total_calls,
                    COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as successful_calls,
                    COALESCE(AVG(response_time_ms), 0) as avg_response_time
                FROM ai_usage_log
                WHERE created_at >= NOW() - INTERVAL '48 hours'
                AND created_at < NOW() - INTERVAL '24 hours'
            """)
            ai_stats_yesterday = db.cursor.fetchone()
            ai_total_yesterday = ai_stats_yesterday['total_calls'] or 0
            ai_successful_yesterday = ai_stats_yesterday['successful_calls'] or 0
            ai_success_rate_yesterday = (ai_successful_yesterday / ai_total_yesterday * 100) if ai_total_yesterday > 0 else 100
            avg_response_time_yesterday = float(ai_stats_yesterday['avg_response_time'] or 0)

            # Search stats yesterday (24-48h ago)
            db.cursor.execute("""
                SELECT COUNT(*) as total_searches
                FROM solicitudes_mercado
                WHERE fecha_solicitud >= NOW() - INTERVAL '48 hours'
                AND fecha_solicitud < NOW() - INTERVAL '24 hours'
            """)
            searches_yesterday = db.cursor.fetchone()['total_searches']

            # Bot activity yesterday (24-48h ago)
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total_messages,
                    COALESCE(SUM(CASE WHEN resultado = 'Exitoso' THEN 1 ELSE 0 END), 0) as successful
                FROM eventos_log
                WHERE tipo_evento IN ('Mensaje_Grupo', 'Mensaje_Privado', 'Webhook_Received',
                                      'Solicitud_Mercado', 'Propiedad_Captada')
                AND fecha_evento >= NOW() - INTERVAL '48 hours'
                AND fecha_evento < NOW() - INTERVAL '24 hours'
            """)
            bot_stats_yesterday = db.cursor.fetchone()
            bot_total_yesterday = bot_stats_yesterday['total_messages'] or 0
            bot_successful_yesterday = bot_stats_yesterday['successful'] or 0
            bot_success_rate_yesterday = (bot_successful_yesterday / bot_total_yesterday * 100) if bot_total_yesterday > 0 else 100

            # ============================================
            # DETERMINAR STATUS
            # ============================================
            db_status = 'healthy'  # If we got here, DB is connected
            ai_status = get_status_from_success_rate(ai_success_rate)
            bot_status = get_status_from_success_rate(bot_success_rate)
            endpoint_status = get_status_from_error_count(errors_24h)

            # Overall is the worst of all
            statuses = [db_status, ai_status, bot_status, endpoint_status]
            if 'critical' in statuses:
                overall_status = 'critical'
            elif 'warning' in statuses:
                overall_status = 'warning'
            else:
                overall_status = 'healthy'

            return jsonify({
                'success': True,
                'data': {
                    'overall_status': overall_status,
                    'timestamp': get_bogota_now().isoformat(),
                    'summary': {
                        'errors_24h': errors_24h,
                        'ai_success_rate': round(ai_success_rate, 1),
                        'avg_response_time_ms': int(avg_response_time),
                        'bot_messages_24h': bot_total,
                        'bot_success_rate': round(bot_success_rate, 1),
                        'active_properties': active_properties,
                        'searches_24h': searches_24h,
                    },
                    'status_by_area': {
                        'database': db_status,
                        'ai_service': ai_status,
                        'whatsapp_bot': bot_status,
                        'api_endpoints': endpoint_status,
                    },
                    # NUEVO: Comparativas temporales (hoy vs ayer)
                    'comparisons': {
                        'errors_24h': calculate_change(errors_24h, errors_yesterday),
                        'ai_success_rate': calculate_change(ai_success_rate, ai_success_rate_yesterday),
                        'avg_response_time_ms': calculate_change(avg_response_time, avg_response_time_yesterday),
                        'bot_messages_24h': calculate_change(bot_total, bot_total_yesterday),
                        'bot_success_rate': calculate_change(bot_success_rate, bot_success_rate_yesterday),
                        'searches_24h': calculate_change(searches_24h, searches_yesterday),
                    }
                }
            })

    except Exception as e:
        return jsonify({
            'success': True,
            'data': {
                'overall_status': 'critical',
                'timestamp': get_bogota_now().isoformat(),
                'summary': {
                    'errors_24h': 0,
                    'ai_success_rate': 0,
                    'avg_response_time_ms': 0,
                    'bot_messages_24h': 0,
                    'bot_success_rate': 0,
                    'active_properties': 0,
                    'searches_24h': 0,
                },
                'status_by_area': {
                    'database': 'critical',
                    'ai_service': 'critical',
                    'whatsapp_bot': 'critical',
                    'api_endpoints': 'critical',
                },
                'comparisons': {},
                'error': str(e)
            }
        })


@system_health_bp.route('/database', methods=['GET'])
def get_database_health():
    """Get database health metrics."""
    try:
        start_time = time.time()

        with DatabaseManager() as db:
            # Connection test
            db.cursor.execute("SELECT 1 as ping")
            connection_time_ms = int((time.time() - start_time) * 1000)

            # Table sizes
            db.cursor.execute("""
                SELECT
                    relname as table_name,
                    n_live_tup as row_count
                FROM pg_stat_user_tables
                WHERE schemaname = 'public'
                ORDER BY n_live_tup DESC
            """)
            tables_raw = db.cursor.fetchall()
            tables = []
            for t in tables_raw:
                row_count = t['row_count'] or 0
                tables.append({
                    'name': t['table_name'],
                    'row_count': row_count,
                    'status': 'healthy'
                })

            # Last activity timestamps
            db.cursor.execute("""
                SELECT
                    (SELECT MAX(fecha_creacion) FROM propiedades) as last_property,
                    (SELECT MAX(fecha_solicitud) FROM solicitudes_mercado) as last_search,
                    (SELECT MAX(fecha_evento) FROM eventos_log) as last_event,
                    (SELECT MAX(created_at) FROM ai_usage_log) as last_ai_call
            """)
            activity = db.cursor.fetchone()

            # Query performance (from solicitudes_mercado)
            db.cursor.execute("""
                SELECT
                    COALESCE(AVG(tiempo_respuesta_ms), 0) as avg_query_time,
                    COALESCE(MIN(tiempo_respuesta_ms), 0) as min_query_time,
                    COALESCE(MAX(tiempo_respuesta_ms), 0) as max_query_time,
                    COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY tiempo_respuesta_ms), 0) as p95_query_time
                FROM solicitudes_mercado
                WHERE fecha_solicitud >= NOW() - INTERVAL '24 hours'
                AND tiempo_respuesta_ms IS NOT NULL
            """)
            perf = db.cursor.fetchone()

            status = get_status_from_connection_time(connection_time_ms)

            return jsonify({
                'success': True,
                'data': {
                    'status': status,
                    'connection_time_ms': connection_time_ms,
                    'tables': tables,
                    'last_activity': {
                        'last_property': activity['last_property'].isoformat() if activity['last_property'] else None,
                        'last_search': activity['last_search'].isoformat() if activity['last_search'] else None,
                        'last_event': activity['last_event'].isoformat() if activity['last_event'] else None,
                        'last_ai_call': activity['last_ai_call'].isoformat() if activity['last_ai_call'] else None,
                    },
                    'query_performance': {
                        'avg_ms': int(perf['avg_query_time']),
                        'min_ms': int(perf['min_query_time']),
                        'max_ms': int(perf['max_query_time']),
                        'p95_ms': int(perf['p95_query_time']),
                    }
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_health_bp.route('/endpoints', methods=['GET'])
def get_endpoints_health():
    """Get per-endpoint health metrics."""
    try:
        days = int(request.args.get('days', 7))
        start_date, _ = get_date_range(days)

        with DatabaseManager() as db:
            # Metrics by tipo_evento
            db.cursor.execute("""
                SELECT
                    tipo_evento as endpoint,
                    COUNT(*) as total_calls,
                    COALESCE(SUM(CASE WHEN resultado = 'Exitoso' THEN 1 ELSE 0 END), 0) as successful,
                    COALESCE(SUM(CASE WHEN resultado = 'Error' THEN 1 ELSE 0 END), 0) as errors,
                    COALESCE(SUM(CASE WHEN resultado = 'Ignorado' THEN 1 ELSE 0 END), 0) as ignored
                FROM eventos_log
                WHERE fecha_evento >= %s
                GROUP BY tipo_evento
                ORDER BY total_calls DESC
            """, (start_date,))

            endpoints_raw = db.cursor.fetchall()
            endpoints = []
            for e in endpoints_raw:
                total = e['total_calls'] or 1
                successful = e['successful'] or 0
                success_rate = round((successful / total) * 100, 2) if total > 0 else 100
                endpoints.append({
                    'endpoint': e['endpoint'],
                    'total_calls': total,
                    'successful': successful,
                    'errors': e['errors'] or 0,
                    'ignored': e['ignored'] or 0,
                    'success_rate': success_rate,
                    'status': get_status_from_success_rate(success_rate)
                })

            # Error details
            db.cursor.execute("""
                SELECT
                    tipo_evento as endpoint,
                    mensaje_error,
                    COUNT(*) as error_count,
                    MAX(fecha_evento) as last_occurrence
                FROM eventos_log
                WHERE resultado = 'Error'
                AND fecha_evento >= %s
                AND mensaje_error IS NOT NULL
                GROUP BY tipo_evento, mensaje_error
                ORDER BY error_count DESC
                LIMIT 20
            """, (start_date,))

            error_details = []
            for err in db.cursor.fetchall():
                error_details.append({
                    'endpoint': err['endpoint'],
                    'error_message': err['mensaje_error'],
                    'count': err['error_count'],
                    'last_occurrence': err['last_occurrence'].isoformat() if err['last_occurrence'] else None
                })

            return jsonify({
                'success': True,
                'data': {
                    'endpoints': endpoints,
                    'error_details': error_details
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_health_bp.route('/ai', methods=['GET'])
def get_ai_health():
    """Get AI service health metrics."""
    try:
        days = int(request.args.get('days', 7))
        start_date, _ = get_date_range(days)

        with DatabaseManager() as db:
            # Stats by provider
            db.cursor.execute("""
                SELECT
                    provider,
                    COUNT(*) as total_calls,
                    COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as successful,
                    COALESCE(SUM(CASE WHEN NOT success THEN 1 ELSE 0 END), 0) as failed,
                    COALESCE(AVG(response_time_ms), 0) as avg_response_time_ms,
                    COALESCE(AVG(total_tokens), 0) as avg_tokens
                FROM ai_usage_log
                WHERE created_at >= %s
                GROUP BY provider
            """, (start_date,))

            by_provider = []
            for p in db.cursor.fetchall():
                total = p['total_calls'] or 1
                successful = p['successful'] or 0
                success_rate = round((successful / total) * 100, 2) if total > 0 else 100
                by_provider.append({
                    'provider': p['provider'],
                    'total_calls': total,
                    'successful': successful,
                    'failed': p['failed'] or 0,
                    'success_rate': success_rate,
                    'avg_response_time_ms': int(p['avg_response_time_ms']),
                    'avg_tokens': int(p['avg_tokens']),
                    'status': get_status_from_success_rate(success_rate)
                })

            # Stats by model
            db.cursor.execute("""
                SELECT
                    model,
                    provider,
                    COUNT(*) as total_calls,
                    COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as successful,
                    COALESCE(AVG(response_time_ms), 0) as avg_response_time_ms
                FROM ai_usage_log
                WHERE created_at >= %s
                GROUP BY model, provider
                ORDER BY total_calls DESC
            """, (start_date,))

            by_model = []
            for m in db.cursor.fetchall():
                total = m['total_calls'] or 1
                successful = m['successful'] or 0
                success_rate = round((successful / total) * 100, 2) if total > 0 else 100
                by_model.append({
                    'model': m['model'],
                    'provider': m['provider'],
                    'total_calls': total,
                    'success_rate': success_rate,
                    'avg_response_time_ms': int(m['avg_response_time_ms']),
                    'status': get_status_from_success_rate(success_rate)
                })

            # Recent failures
            db.cursor.execute("""
                SELECT
                    id,
                    created_at,
                    provider,
                    model,
                    usage_type,
                    function_name,
                    error_message,
                    response_time_ms
                FROM ai_usage_log
                WHERE success = false
                AND created_at >= %s
                ORDER BY created_at DESC
                LIMIT 20
            """, (start_date,))

            recent_failures = []
            for f in db.cursor.fetchall():
                recent_failures.append({
                    'id': f['id'],
                    'created_at': f['created_at'].isoformat() if f['created_at'] else None,
                    'provider': f['provider'],
                    'model': f['model'],
                    'usage_type': f['usage_type'],
                    'function_name': f['function_name'],
                    'error_message': f['error_message'],
                    'response_time_ms': f['response_time_ms']
                })

            # Hourly trend (last 24h)
            db.cursor.execute("""
                SELECT
                    DATE_TRUNC('hour', created_at) as hour,
                    COALESCE(AVG(response_time_ms), 0) as avg_response_time,
                    COUNT(*) as call_count,
                    COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as successful
                FROM ai_usage_log
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY DATE_TRUNC('hour', created_at)
                ORDER BY hour
            """)

            hourly_trend = []
            for h in db.cursor.fetchall():
                total = h['call_count'] or 1
                successful = h['successful'] or 0
                hourly_trend.append({
                    'hour': h['hour'].isoformat() if h['hour'] else None,
                    'avg_response_time': int(h['avg_response_time']),
                    'calls': total,
                    'success_rate': round((successful / total) * 100, 1) if total > 0 else 100
                })

            # Determine overall AI status
            overall_success_rate = 100
            if by_provider:
                total_calls = sum(p['total_calls'] for p in by_provider)
                total_successful = sum(p['successful'] for p in by_provider)
                overall_success_rate = (total_successful / total_calls * 100) if total_calls > 0 else 100

            return jsonify({
                'success': True,
                'data': {
                    'status': get_status_from_success_rate(overall_success_rate),
                    'by_provider': by_provider,
                    'by_model': by_model,
                    'recent_failures': recent_failures,
                    'hourly_trend': hourly_trend
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_health_bp.route('/errors', methods=['GET'])
def get_errors():
    """Get error log and trends."""
    try:
        days = int(request.args.get('days', 7))
        limit = int(request.args.get('limit', 50))
        start_date, _ = get_date_range(days)

        with DatabaseManager() as db:
            # Error count by type
            db.cursor.execute("""
                SELECT
                    tipo_evento as type,
                    COUNT(*) as count,
                    MAX(fecha_evento) as last_occurrence
                FROM eventos_log
                WHERE resultado = 'Error'
                AND fecha_evento >= %s
                GROUP BY tipo_evento
                ORDER BY count DESC
            """, (start_date,))

            by_type = []
            total_errors = 0
            most_common_type = None
            for t in db.cursor.fetchall():
                count = t['count'] or 0
                total_errors += count
                if most_common_type is None:
                    most_common_type = t['type']
                by_type.append({
                    'type': t['type'],
                    'count': count,
                    'last_occurrence': t['last_occurrence'].isoformat() if t['last_occurrence'] else None
                })

            # Errors today
            db.cursor.execute("""
                SELECT COUNT(*) as count
                FROM eventos_log
                WHERE resultado = 'Error'
                AND fecha_evento >= CURRENT_DATE
            """)
            errors_today = db.cursor.fetchone()['count']

            # Error trend by day
            db.cursor.execute("""
                SELECT
                    DATE(fecha_evento) as date,
                    COUNT(*) as count
                FROM eventos_log
                WHERE resultado = 'Error'
                AND fecha_evento >= %s
                GROUP BY DATE(fecha_evento)
                ORDER BY date
            """, (start_date,))

            trend = []
            for d in db.cursor.fetchall():
                trend.append({
                    'date': d['date'].isoformat() if d['date'] else None,
                    'count': d['count'] or 0
                })

            # Recent errors with details
            db.cursor.execute("""
                SELECT
                    id,
                    fecha_evento,
                    tipo_evento,
                    agente_telefono,
                    mensaje_error,
                    grupo_origen
                FROM eventos_log
                WHERE resultado = 'Error'
                AND fecha_evento >= %s
                ORDER BY fecha_evento DESC
                LIMIT %s
            """, (start_date, limit))

            recent_errors = []
            for e in db.cursor.fetchall():
                recent_errors.append({
                    'id': e['id'],
                    'timestamp': e['fecha_evento'].isoformat() if e['fecha_evento'] else None,
                    'type': e['tipo_evento'],
                    'agent_phone': e['agente_telefono'],
                    'error_message': e['mensaje_error'],
                    'group_origin': e['grupo_origen']
                })

            return jsonify({
                'success': True,
                'data': {
                    'summary': {
                        'total_errors': total_errors,
                        'errors_today': errors_today,
                        'most_common_type': most_common_type
                    },
                    'by_type': by_type,
                    'trend': trend,
                    'recent_errors': recent_errors
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_health_bp.route('/bot', methods=['GET'])
def get_bot_health():
    """Get WhatsApp bot health metrics."""
    try:
        days = int(request.args.get('days', 7))
        start_date, _ = get_date_range(days)

        with DatabaseManager() as db:
            # Message processing stats
            db.cursor.execute("""
                SELECT
                    tipo_evento as operation,
                    COUNT(*) as total,
                    COALESCE(SUM(CASE WHEN resultado = 'Exitoso' THEN 1 ELSE 0 END), 0) as successful,
                    COALESCE(SUM(CASE WHEN resultado = 'Error' THEN 1 ELSE 0 END), 0) as failed
                FROM eventos_log
                WHERE tipo_evento IN ('Mensaje_Grupo', 'Mensaje_Privado', 'Webhook_Received',
                                      'Propiedad_Captada', 'Solicitud_Mercado', 'Propiedad_Seleccionada',
                                      'Contacto_Compartido', 'Notificacion_Enviada')
                AND fecha_evento >= %s
                GROUP BY tipo_evento
                ORDER BY total DESC
            """, (start_date,))

            by_operation = []
            total_messages = 0
            total_successful = 0
            total_failed = 0
            for op in db.cursor.fetchall():
                total_messages += op['total'] or 0
                total_successful += op['successful'] or 0
                total_failed += op['failed'] or 0
                by_operation.append({
                    'operation': op['operation'],
                    'total': op['total'] or 0,
                    'successful': op['successful'] or 0,
                    'failed': op['failed'] or 0
                })

            message_success_rate = (total_successful / total_messages * 100) if total_messages > 0 else 100

            # Hourly activity (last 24h)
            db.cursor.execute("""
                SELECT
                    DATE_TRUNC('hour', fecha_evento) as hour,
                    COUNT(*) as message_count,
                    COALESCE(SUM(CASE WHEN resultado = 'Exitoso' THEN 1 ELSE 0 END), 0) as successful
                FROM eventos_log
                WHERE tipo_evento IN ('Mensaje_Grupo', 'Mensaje_Privado')
                AND fecha_evento >= NOW() - INTERVAL '24 hours'
                GROUP BY DATE_TRUNC('hour', fecha_evento)
                ORDER BY hour
            """)

            hourly_activity = []
            for h in db.cursor.fetchall():
                total = h['message_count'] or 1
                successful = h['successful'] or 0
                hourly_activity.append({
                    'hour': h['hour'].isoformat() if h['hour'] else None,
                    'messages': total,
                    'success_rate': round((successful / total) * 100, 1) if total > 0 else 100
                })

            # Search response times
            db.cursor.execute("""
                SELECT
                    COALESCE(AVG(tiempo_respuesta_ms), 0) as avg_response_time,
                    COALESCE(MIN(tiempo_respuesta_ms), 0) as min_response_time,
                    COALESCE(MAX(tiempo_respuesta_ms), 0) as max_response_time,
                    COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY tiempo_respuesta_ms), 0) as median_response_time
                FROM solicitudes_mercado
                WHERE fecha_solicitud >= %s
                AND tiempo_respuesta_ms IS NOT NULL
            """, (start_date,))

            perf = db.cursor.fetchone()

            # Capture stats
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total_captures,
                    COALESCE(SUM(CASE WHEN activa = true THEN 1 ELSE 0 END), 0) as active_captures
                FROM propiedades
                WHERE fuente IN ('Wasi_Captado', 'Tu360_Captado')
                AND fecha_creacion >= %s
            """, (start_date,))

            capture_stats = db.cursor.fetchone()
            total_captures = capture_stats['total_captures'] or 0
            active_captures = capture_stats['active_captures'] or 0
            capture_success_rate = (active_captures / total_captures * 100) if total_captures > 0 else 100

            return jsonify({
                'success': True,
                'data': {
                    'status': get_status_from_success_rate(message_success_rate),
                    'message_stats': {
                        'total_messages': total_messages,
                        'successful': total_successful,
                        'failed': total_failed,
                        'success_rate': round(message_success_rate, 2)
                    },
                    'by_operation': by_operation,
                    'response_times': {
                        'avg_ms': int(perf['avg_response_time']),
                        'min_ms': int(perf['min_response_time']),
                        'max_ms': int(perf['max_response_time']),
                        'median_ms': int(perf['median_response_time'])
                    },
                    'hourly_activity': hourly_activity,
                    'capture_stats': {
                        'total_captures_period': total_captures,
                        'active_captures': active_captures,
                        'capture_success_rate': round(capture_success_rate, 2)
                    }
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@system_health_bp.route('/performance', methods=['GET'])
def get_performance_metrics():
    """
    Get detailed performance metrics with percentiles P50/P95/P99.
    Includes temporal comparisons and slowest endpoints identification.
    """
    try:
        days = int(request.args.get('days', 7))
        start_date, _ = get_date_range(days)

        with DatabaseManager() as db:
            # ============================================
            # PERCENTILES GLOBALES Y POR ENDPOINT
            # ============================================

            # Percentiles by usage_type (endpoint)
            db.cursor.execute("""
                SELECT
                    usage_type as endpoint,
                    COUNT(*) as total_calls,
                    ROUND(COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY response_time_ms), 0)::numeric, 0) as p50_ms,
                    ROUND(COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_time_ms), 0)::numeric, 0) as p95_ms,
                    ROUND(COALESCE(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY response_time_ms), 0)::numeric, 0) as p99_ms,
                    ROUND(COALESCE(AVG(response_time_ms), 0)::numeric, 0) as avg_ms,
                    COALESCE(MIN(response_time_ms), 0) as min_ms,
                    COALESCE(MAX(response_time_ms), 0) as max_ms,
                    COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as successful,
                    COALESCE(SUM(CASE WHEN NOT success THEN 1 ELSE 0 END), 0) as failed
                FROM ai_usage_log
                WHERE created_at >= %s
                  AND response_time_ms IS NOT NULL
                GROUP BY usage_type
                ORDER BY p95_ms DESC
            """, (start_date,))

            by_endpoint = []
            total_p50 = 0
            total_p95 = 0
            total_p99 = 0
            total_calls_with_time = 0

            for row in db.cursor.fetchall():
                total = row['total_calls'] or 1
                successful = row['successful'] or 0
                success_rate = round((successful / total) * 100, 2) if total > 0 else 100
                p95 = int(row['p95_ms'])

                by_endpoint.append({
                    'endpoint': row['endpoint'],
                    'total_calls': total,
                    'p50_ms': int(row['p50_ms']),
                    'p95_ms': p95,
                    'p99_ms': int(row['p99_ms']),
                    'avg_ms': int(row['avg_ms']),
                    'min_ms': int(row['min_ms']),
                    'max_ms': int(row['max_ms']),
                    'success_rate': success_rate,
                    'status': get_status_from_response_time(p95)
                })

                # Acumular para calcular globales ponderados
                total_p50 += int(row['p50_ms']) * total
                total_p95 += int(row['p95_ms']) * total
                total_p99 += int(row['p99_ms']) * total
                total_calls_with_time += total

            # Calcular percentiles globales (promedio ponderado)
            global_p50 = int(total_p50 / total_calls_with_time) if total_calls_with_time > 0 else 0
            global_p95 = int(total_p95 / total_calls_with_time) if total_calls_with_time > 0 else 0
            global_p99 = int(total_p99 / total_calls_with_time) if total_calls_with_time > 0 else 0

            # ============================================
            # ENDPOINTS MÁS LENTOS (P95 > 5000ms)
            # ============================================
            slowest_endpoints = [ep for ep in by_endpoint if ep['p95_ms'] > 5000]

            # ============================================
            # TENDENCIA HORARIA (últimas 24h)
            # ============================================
            db.cursor.execute("""
                SELECT
                    DATE_TRUNC('hour', created_at) as hour,
                    ROUND(COALESCE(AVG(response_time_ms), 0)::numeric, 0) as avg_ms,
                    ROUND(COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_time_ms), 0)::numeric, 0) as p95_ms,
                    COUNT(*) as call_count
                FROM ai_usage_log
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                  AND response_time_ms IS NOT NULL
                GROUP BY DATE_TRUNC('hour', created_at)
                ORDER BY hour
            """)

            hourly_trend = []
            for h in db.cursor.fetchall():
                hourly_trend.append({
                    'hour': h['hour'].isoformat() if h['hour'] else None,
                    'avg_ms': int(h['avg_ms']),
                    'p95_ms': int(h['p95_ms']),
                    'calls': h['call_count']
                })

            # ============================================
            # COMPARATIVAS: Hoy vs Ayer
            # ============================================

            # P95 de hoy (últimas 24h)
            db.cursor.execute("""
                SELECT
                    ROUND(COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_time_ms), 0)::numeric, 0) as p95_ms,
                    COUNT(*) as total_calls
                FROM ai_usage_log
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                  AND response_time_ms IS NOT NULL
            """)
            today_stats = db.cursor.fetchone()
            p95_today = int(today_stats['p95_ms']) if today_stats else 0

            # P95 de ayer (24-48h)
            db.cursor.execute("""
                SELECT
                    ROUND(COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_time_ms), 0)::numeric, 0) as p95_ms,
                    COUNT(*) as total_calls
                FROM ai_usage_log
                WHERE created_at >= NOW() - INTERVAL '48 hours'
                  AND created_at < NOW() - INTERVAL '24 hours'
                  AND response_time_ms IS NOT NULL
            """)
            yesterday_stats = db.cursor.fetchone()
            p95_yesterday = int(yesterday_stats['p95_ms']) if yesterday_stats else 0

            return jsonify({
                'success': True,
                'data': {
                    'period_days': days,
                    'global_percentiles': {
                        'p50_ms': global_p50,
                        'p95_ms': global_p95,
                        'p99_ms': global_p99,
                        'status': get_status_from_response_time(global_p95)
                    },
                    'by_endpoint': by_endpoint,
                    'slowest_endpoints': slowest_endpoints,
                    'hourly_trend': hourly_trend,
                    'comparisons': {
                        'p95_today_vs_yesterday': calculate_change(p95_today, p95_yesterday)
                    }
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500