#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dependencies Health API - Estado de dependencias externas
"""

from flask import Blueprint, jsonify
from src.db.database import DatabaseManager
from datetime import datetime, timedelta
import redis
import time
import os
import pytz

dependencies_bp = Blueprint('dependencies', __name__, url_prefix='/api/health')

# Zona horaria de Bogotá
BOGOTA_TZ = pytz.timezone('America/Bogota')


def get_bogota_now():
    """Get current time in Bogota timezone."""
    return datetime.now(BOGOTA_TZ)


def get_status_color(status: str) -> str:
    """Map status to color for frontend."""
    return {
        'healthy': 'green',
        'warning': 'yellow',
        'critical': 'red',
        'unknown': 'gray'
    }.get(status, 'gray')


def check_postgres() -> dict:
    """
    Ping a PostgreSQL y mide latencia.
    """
    start = time.time()
    try:
        db = DatabaseManager()
        db.connect()
        db.cursor.execute("SELECT 1 as ping")
        db.disconnect()
        latency_ms = int((time.time() - start) * 1000)

        if latency_ms <= 100:
            status = 'healthy'
        elif latency_ms <= 500:
            status = 'warning'
        else:
            status = 'critical'

        return {
            'name': 'PostgreSQL',
            'status': status,
            'latency_ms': latency_ms,
            'message': 'Connected',
            'last_check': get_bogota_now().isoformat()
        }
    except Exception as e:
        return {
            'name': 'PostgreSQL',
            'status': 'critical',
            'latency_ms': None,
            'message': str(e)[:100],
            'last_check': get_bogota_now().isoformat()
        }


def check_redis() -> dict:
    """
    Ping a Redis y mide latencia.
    """
    redis_url = os.getenv('REDIS_URL')
    if not redis_url:
        return {
            'name': 'Redis',
            'status': 'unknown',
            'latency_ms': None,
            'message': 'Not configured (REDIS_URL not set)',
            'last_check': get_bogota_now().isoformat()
        }

    start = time.time()
    try:
        # Heroku Redis usa certificados auto-firmados
        if redis_url.startswith('rediss://'):
            conn = redis.from_url(redis_url, ssl_cert_reqs=None)
        else:
            conn = redis.from_url(redis_url)

        conn.ping()
        latency_ms = int((time.time() - start) * 1000)

        if latency_ms <= 50:
            status = 'healthy'
        elif latency_ms <= 200:
            status = 'warning'
        else:
            status = 'critical'

        return {
            'name': 'Redis',
            'status': status,
            'latency_ms': latency_ms,
            'message': 'Connected',
            'last_check': get_bogota_now().isoformat()
        }
    except Exception as e:
        return {
            'name': 'Redis',
            'status': 'critical',
            'latency_ms': None,
            'message': str(e)[:100],
            'last_check': get_bogota_now().isoformat()
        }


def check_ai_provider(provider: str) -> dict:
    """
    Obtiene estadísticas del provider de IA desde ai_usage_log.
    Calcula latencia promedio y tasa de éxito de las últimas 24h.
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total_calls,
                    COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as successful,
                    COALESCE(AVG(response_time_ms), 0) as avg_latency_ms,
                    MAX(created_at) as last_call
                FROM ai_usage_log
                WHERE provider = %s
                AND created_at >= NOW() - INTERVAL '24 hours'
            """, (provider,))

            row = db.cursor.fetchone()
            total_calls = row['total_calls'] or 0
            successful = row['successful'] or 0
            avg_latency = int(row['avg_latency_ms']) if row['avg_latency_ms'] else 0

            if total_calls == 0:
                return {
                    'name': f'{provider.title()} API',
                    'status': 'unknown',
                    'latency_ms': None,
                    'avg_latency_24h_ms': None,
                    'success_rate': None,
                    'total_calls_24h': 0,
                    'message': 'No calls in last 24h',
                    'last_check': get_bogota_now().isoformat()
                }

            success_rate = round((successful / total_calls) * 100, 1)

            # Determinar status basado en success rate y latencia
            if success_rate >= 95 and avg_latency <= 5000:
                status = 'healthy'
            elif success_rate >= 85 and avg_latency <= 10000:
                status = 'warning'
            else:
                status = 'critical'

            return {
                'name': f'{provider.title()} API',
                'status': status,
                'latency_ms': avg_latency,  # Usando promedio como "latencia actual"
                'avg_latency_24h_ms': avg_latency,
                'success_rate': success_rate,
                'total_calls_24h': total_calls,
                'message': f'{success_rate}% success rate',
                'last_check': get_bogota_now().isoformat()
            }

    except Exception as e:
        return {
            'name': f'{provider.title()} API',
            'status': 'critical',
            'latency_ms': None,
            'message': str(e)[:100],
            'last_check': get_bogota_now().isoformat()
        }


def check_ultramsg() -> dict:
    """
    Verifica estado de UltraMSG basado en webhooks recibidos.
    """
    try:
        with DatabaseManager() as db:
            # Contar webhooks recibidos en las últimas 24h
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total_webhooks,
                    COALESCE(SUM(CASE WHEN resultado = 'Exitoso' THEN 1 ELSE 0 END), 0) as successful,
                    MAX(fecha_evento) as last_webhook
                FROM eventos_log
                WHERE tipo_evento = 'Webhook_Received'
                AND fecha_evento >= NOW() - INTERVAL '24 hours'
            """)

            row = db.cursor.fetchone()
            total = row['total_webhooks'] or 0
            successful = row['successful'] or 0
            last_webhook = row['last_webhook']

            if total == 0:
                return {
                    'name': 'UltraMSG',
                    'status': 'unknown',
                    'latency_ms': None,
                    'success_rate': None,
                    'total_webhooks_24h': 0,
                    'message': 'No webhooks in last 24h',
                    'last_check': get_bogota_now().isoformat()
                }

            success_rate = round((successful / total) * 100, 1)

            # Verificar qué tan reciente fue el último webhook
            if last_webhook:
                time_since_last = (get_bogota_now().replace(tzinfo=None) - last_webhook.replace(tzinfo=None)).total_seconds()
                minutes_since_last = int(time_since_last / 60)
            else:
                minutes_since_last = None

            # Determinar status
            if success_rate >= 95:
                status = 'healthy'
            elif success_rate >= 85:
                status = 'warning'
            else:
                status = 'critical'

            return {
                'name': 'UltraMSG',
                'status': status,
                'latency_ms': None,  # No tenemos latencia directa
                'success_rate': success_rate,
                'total_webhooks_24h': total,
                'minutes_since_last_webhook': minutes_since_last,
                'message': f'{total} webhooks, {success_rate}% success',
                'last_check': get_bogota_now().isoformat()
            }

    except Exception as e:
        return {
            'name': 'UltraMSG',
            'status': 'critical',
            'latency_ms': None,
            'message': str(e)[:100],
            'last_check': get_bogota_now().isoformat()
        }


def calculate_overall_status(dependencies: list) -> str:
    """
    Calcula el estado general basado en todas las dependencias.
    El peor estado gana.
    """
    statuses = [d['status'] for d in dependencies if d['status'] != 'unknown']

    if not statuses:
        return 'unknown'
    if 'critical' in statuses:
        return 'critical'
    if 'warning' in statuses:
        return 'warning'
    return 'healthy'


@dependencies_bp.route('/dependencies', methods=['GET'])
def get_dependencies_status():
    """
    Get status of all external dependencies:
    - PostgreSQL (database)
    - Redis (caching/queues)
    - Claude/Anthropic API
    - OpenAI API (if used)
    - UltraMSG (WhatsApp)
    """
    dependencies = []

    # 1. PostgreSQL
    db_status = check_postgres()
    dependencies.append(db_status)

    # 2. Redis
    redis_status = check_redis()
    dependencies.append(redis_status)

    # 3. Anthropic (Claude) API
    anthropic_status = check_ai_provider('anthropic')
    dependencies.append(anthropic_status)

    # 4. OpenAI API (solo si hay llamadas registradas)
    openai_status = check_ai_provider('openai')
    if openai_status.get('total_calls_24h', 0) > 0 or openai_status.get('status') == 'critical':
        dependencies.append(openai_status)

    # 5. UltraMSG (WhatsApp)
    ultramsg_status = check_ultramsg()
    dependencies.append(ultramsg_status)

    overall_status = calculate_overall_status(dependencies)

    return jsonify({
        'success': True,
        'data': {
            'overall_status': overall_status,
            'dependencies': dependencies,
            'last_check': get_bogota_now().isoformat()
        }
    })
