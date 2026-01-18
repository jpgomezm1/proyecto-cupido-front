#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Costs API - Endpoints para visualización de costos de IA
"""

from flask import Blueprint, request, jsonify
from src.db.database import DatabaseManager
from datetime import datetime, timedelta
import pytz

ai_costs_bp = Blueprint('ai_costs', __name__, url_prefix='/api')

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


@ai_costs_bp.route('/ai-costs/summary', methods=['GET'])
def get_summary():
    """Get summary metrics for AI usage."""
    try:
        days = int(request.args.get('days', 30))
        start_date, _ = get_date_range(days)

        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total_calls,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0) as total_cost_usd,
                    COALESCE(AVG(estimated_cost_usd), 0) as avg_cost_per_call,
                    COALESCE(AVG(response_time_ms), 0) as avg_response_time_ms,
                    COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) * 100, 100) as success_rate
                FROM ai_usage_log
                WHERE created_at >= %s
            """, (start_date,))

            row = db.cursor.fetchone()

            return jsonify({
                'success': True,
                'data': {
                    'total_calls': row['total_calls'],
                    'total_tokens': int(row['total_tokens']),
                    'total_cost_usd': float(row['total_cost_usd']),
                    'avg_cost_per_call': float(row['avg_cost_per_call']),
                    'avg_response_time_ms': int(row['avg_response_time_ms']),
                    'success_rate': float(row['success_rate']),
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@ai_costs_bp.route('/ai-costs/by-model', methods=['GET'])
def get_by_model():
    """Get costs grouped by model."""
    try:
        days = int(request.args.get('days', 30))
        start_date, _ = get_date_range(days)

        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    model,
                    provider,
                    COUNT(*) as calls,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0) as total_cost_usd
                FROM ai_usage_log
                WHERE created_at >= %s
                GROUP BY model, provider
                ORDER BY total_cost_usd DESC
            """, (start_date,))

            rows = db.cursor.fetchall()

            # Calculate percentages
            total_cost = sum(float(r['total_cost_usd']) for r in rows)
            data = []
            for row in rows:
                cost = float(row['total_cost_usd'])
                data.append({
                    'model': row['model'],
                    'provider': row['provider'],
                    'calls': row['calls'],
                    'total_tokens': int(row['total_tokens']),
                    'total_cost_usd': cost,
                    'percentage': round((cost / total_cost * 100), 1) if total_cost > 0 else 0,
                })

            return jsonify({'success': True, 'data': data})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@ai_costs_bp.route('/ai-costs/by-day', methods=['GET'])
def get_by_day():
    """Get costs grouped by day."""
    try:
        days = int(request.args.get('days', 30))
        start_date, _ = get_date_range(days)

        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    DATE(created_at) as date,
                    COALESCE(SUM(estimated_cost_usd), 0) as total_cost_usd,
                    COUNT(*) as total_calls,
                    COALESCE(SUM(total_tokens), 0) as total_tokens
                FROM ai_usage_log
                WHERE created_at >= %s
                GROUP BY DATE(created_at)
                ORDER BY date
            """, (start_date,))

            rows = db.cursor.fetchall()
            data = [{
                'date': row['date'].isoformat(),
                'total_cost_usd': float(row['total_cost_usd']),
                'total_calls': row['total_calls'],
                'total_tokens': int(row['total_tokens']),
            } for row in rows]

            return jsonify({'success': True, 'data': data})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@ai_costs_bp.route('/ai-costs/by-type', methods=['GET'])
def get_by_type():
    """Get costs grouped by usage type."""
    try:
        days = int(request.args.get('days', 30))
        start_date, _ = get_date_range(days)

        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    usage_type,
                    COUNT(*) as calls,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(estimated_cost_usd), 0) as total_cost_usd
                FROM ai_usage_log
                WHERE created_at >= %s
                GROUP BY usage_type
                ORDER BY total_cost_usd DESC
            """, (start_date,))

            rows = db.cursor.fetchall()
            data = [{
                'usage_type': row['usage_type'],
                'calls': row['calls'],
                'total_tokens': int(row['total_tokens']),
                'total_cost_usd': float(row['total_cost_usd']),
            } for row in rows]

            return jsonify({'success': True, 'data': data})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@ai_costs_bp.route('/ai-costs/detail', methods=['GET'])
def get_detail():
    """Get detailed usage records with pagination."""
    try:
        days = int(request.args.get('days', 30))
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        start_date, _ = get_date_range(days)

        with DatabaseManager() as db:
            # Get total count
            db.cursor.execute("""
                SELECT COUNT(*) as count
                FROM ai_usage_log
                WHERE created_at >= %s
            """, (start_date,))
            total = db.cursor.fetchone()['count']

            # Get paginated data
            db.cursor.execute("""
                SELECT
                    id, created_at, provider, model, usage_type, function_name,
                    input_tokens, output_tokens, total_tokens,
                    estimated_cost_usd, response_time_ms, success, error_message
                FROM ai_usage_log
                WHERE created_at >= %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (start_date, limit, offset))

            rows = db.cursor.fetchall()
            data = [{
                'id': row['id'],
                'created_at': row['created_at'].isoformat(),
                'provider': row['provider'],
                'model': row['model'],
                'usage_type': row['usage_type'],
                'function_name': row['function_name'],
                'input_tokens': row['input_tokens'],
                'output_tokens': row['output_tokens'],
                'total_tokens': row['total_tokens'],
                'estimated_cost_usd': float(row['estimated_cost_usd']) if row['estimated_cost_usd'] else 0,
                'response_time_ms': row['response_time_ms'],
                'success': row['success'],
                'error_message': row['error_message'],
            } for row in rows]

            return jsonify({
                'success': True,
                'data': {
                    'data': data,
                    'total': total,
                    'limit': limit,
                    'offset': offset,
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@ai_costs_bp.route('/ai-costs/comparison', methods=['GET'])
def get_comparison():
    """Get month-over-month comparison."""
    try:
        now = get_bogota_now()
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        if now.month == 1:
            previous_month_start = current_month_start.replace(year=now.year - 1, month=12)
        else:
            previous_month_start = current_month_start.replace(month=now.month - 1)

        previous_month_end = current_month_start - timedelta(seconds=1)

        with DatabaseManager() as db:
            # Current month
            db.cursor.execute("""
                SELECT
                    COALESCE(SUM(estimated_cost_usd), 0) as cost,
                    COALESCE(SUM(total_tokens), 0) as tokens,
                    COUNT(*) as calls
                FROM ai_usage_log
                WHERE created_at >= %s
            """, (current_month_start,))
            current = db.cursor.fetchone()

            # Previous month
            db.cursor.execute("""
                SELECT
                    COALESCE(SUM(estimated_cost_usd), 0) as cost,
                    COALESCE(SUM(total_tokens), 0) as tokens,
                    COUNT(*) as calls
                FROM ai_usage_log
                WHERE created_at >= %s AND created_at <= %s
            """, (previous_month_start, previous_month_end))
            previous = db.cursor.fetchone()

            # Calculate changes
            prev_cost = float(previous['cost'])
            prev_tokens = int(previous['tokens'])
            prev_calls = previous['calls']

            curr_cost = float(current['cost'])
            curr_tokens = int(current['tokens'])
            curr_calls = current['calls']

            cost_change = ((curr_cost - prev_cost) / prev_cost * 100) if prev_cost > 0 else 0
            tokens_change = ((curr_tokens - prev_tokens) / prev_tokens * 100) if prev_tokens > 0 else 0
            calls_change = ((curr_calls - prev_calls) / prev_calls * 100) if prev_calls > 0 else 0

            return jsonify({
                'success': True,
                'data': {
                    'current': {
                        'cost': curr_cost,
                        'tokens': curr_tokens,
                        'calls': curr_calls,
                        'month': current_month_start.strftime('%Y-%m'),
                    },
                    'previous': {
                        'cost': prev_cost,
                        'tokens': prev_tokens,
                        'calls': prev_calls,
                        'month': previous_month_start.strftime('%Y-%m'),
                    },
                    'change': {
                        'cost': round(cost_change, 1),
                        'tokens': round(tokens_change, 1),
                        'calls': round(calls_change, 1),
                    }
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def calculate_change(current: float, previous: float) -> dict:
    """
    Calcula el cambio porcentual entre dos valores.
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
        "current": round(current, 4),
        "previous": round(previous, 4),
        "change_percent": round(abs(change), 1),
        "direction": direction
    }


@ai_costs_bp.route('/ai-costs/roi', methods=['GET'])
def get_roi_metrics():
    """
    Get ROI metrics: cost per search, monthly projection, breakdown by operation.
    """
    try:
        days = int(request.args.get('days', 30))
        start_date, _ = get_date_range(days)
        now = get_bogota_now()

        with DatabaseManager() as db:
            # ============================================
            # COSTO TOTAL DEL PERÍODO
            # ============================================
            db.cursor.execute("""
                SELECT
                    COALESCE(SUM(estimated_cost_usd), 0) as total_cost,
                    COUNT(*) as total_calls
                FROM ai_usage_log
                WHERE created_at >= %s
                  AND success = true
            """, (start_date,))
            totals = db.cursor.fetchone()
            total_cost = float(totals['total_cost'])
            total_calls = totals['total_calls']

            # ============================================
            # COSTO POR OPERACIÓN (DESGLOSE)
            # ============================================
            db.cursor.execute("""
                SELECT
                    usage_type,
                    COUNT(*) as calls,
                    COALESCE(SUM(estimated_cost_usd), 0) as total_cost,
                    COALESCE(AVG(estimated_cost_usd), 0) as avg_cost_per_call
                FROM ai_usage_log
                WHERE created_at >= %s
                  AND success = true
                GROUP BY usage_type
                ORDER BY total_cost DESC
            """, (start_date,))

            # Return as array for frontend compatibility
            cost_by_operation = []
            for row in db.cursor.fetchall():
                cost_by_operation.append({
                    'usage_type': row['usage_type'],
                    'total_calls': row['calls'],
                    'total_cost': round(float(row['total_cost']), 4),
                    'avg_cost_per_call': round(float(row['avg_cost_per_call']), 6)
                })

            # ============================================
            # BÚSQUEDAS EXITOSAS (para calcular costo por búsqueda)
            # ============================================
            db.cursor.execute("""
                SELECT COUNT(*) as total_searches
                FROM solicitudes_mercado
                WHERE fecha_solicitud >= %s
            """, (start_date,))
            total_searches = db.cursor.fetchone()['total_searches'] or 0

            # Costo por búsqueda
            cost_per_search = (total_cost / total_searches) if total_searches > 0 else 0

            # ============================================
            # PROYECCIÓN MENSUAL
            # ============================================

            # Costo diario promedio
            db.cursor.execute("""
                SELECT
                    DATE(created_at) as date,
                    COALESCE(SUM(estimated_cost_usd), 0) as daily_cost
                FROM ai_usage_log
                WHERE created_at >= %s
                GROUP BY DATE(created_at)
            """, (start_date,))

            daily_costs = [float(row['daily_cost']) for row in db.cursor.fetchall()]
            avg_daily_cost = sum(daily_costs) / len(daily_costs) if daily_costs else 0

            # Días restantes del mes
            days_in_month = 30  # Simplificación
            current_day = now.day
            days_remaining = days_in_month - current_day
            days_elapsed = current_day

            # Costo acumulado del mes actual
            current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            db.cursor.execute("""
                SELECT COALESCE(SUM(estimated_cost_usd), 0) as month_cost
                FROM ai_usage_log
                WHERE created_at >= %s
            """, (current_month_start,))
            month_cost_so_far = float(db.cursor.fetchone()['month_cost'])

            # Proyecciones
            projected_total = month_cost_so_far + (avg_daily_cost * days_remaining)
            projected_pessimistic = month_cost_so_far + (avg_daily_cost * 1.2 * days_remaining)  # +20%
            projected_optimistic = month_cost_so_far + (avg_daily_cost * 0.8 * days_remaining)   # -20%

            # ============================================
            # COMPARATIVA: Este mes vs mes anterior
            # ============================================

            # Mes anterior
            if now.month == 1:
                prev_month_start = current_month_start.replace(year=now.year - 1, month=12)
            else:
                prev_month_start = current_month_start.replace(month=now.month - 1)

            prev_month_end = current_month_start - timedelta(seconds=1)

            db.cursor.execute("""
                SELECT COALESCE(SUM(estimated_cost_usd), 0) as cost
                FROM ai_usage_log
                WHERE created_at >= %s AND created_at <= %s
            """, (prev_month_start, prev_month_end))
            prev_month_cost = float(db.cursor.fetchone()['cost'])

            return jsonify({
                'success': True,
                'data': {
                    'period_days': days,
                    'total_cost_usd': round(total_cost, 4),
                    'total_calls': total_calls,
                    'total_searches': total_searches,
                    'cost_per_search': round(cost_per_search, 4) if total_searches > 0 else None,
                    'cost_by_operation': cost_by_operation,
                    'daily_average_usd': round(avg_daily_cost, 4),
                    'monthly_projection': {
                        'estimated_usd': round(projected_total, 2),
                        'pessimistic_usd': round(projected_pessimistic, 2),
                        'optimistic_usd': round(projected_optimistic, 2),
                        'days_remaining': days_remaining,
                    },
                    'comparison_vs_last_period': calculate_change(month_cost_so_far, prev_month_cost)
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500