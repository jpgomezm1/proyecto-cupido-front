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
