#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Platform Costs API - CRUD de costos recurrentes + vista consolidada
"""

from flask import Blueprint, request, jsonify
from src.db.database import DatabaseManager
from datetime import datetime, date, timedelta
from calendar import monthrange
import csv
import io
import pytz

platform_costs_bp = Blueprint('platform_costs', __name__, url_prefix='/api')

BOGOTA_TZ = pytz.timezone('America/Bogota')

VALID_CATEGORIES = ('messaging', 'infrastructure', 'database', 'monitoring', 'ai_api', 'other')
VALID_BILLING_CYCLES = ('monthly', 'annual')


def get_bogota_now():
    return datetime.now(BOGOTA_TZ)


def get_month_range(year: int, month: int):
    """Return (first_day, last_day) as date objects for a given year/month."""
    first_day = date(year, month, 1)
    _, last_day_num = monthrange(year, month)
    last_day = date(year, month, last_day_num)
    return first_day, last_day


# ============================================================
# CRUD - Platform Cost Definitions
# ============================================================

@platform_costs_bp.route('/platform-costs', methods=['GET'])
def list_platform_costs():
    """List platform cost definitions. ?active_only=true to filter active ones."""
    try:
        active_only = request.args.get('active_only', 'false').lower() == 'true'

        with DatabaseManager() as db:
            if active_only:
                db.cursor.execute("""
                    SELECT * FROM platform_cost_definitions
                    WHERE active_until IS NULL OR active_until >= CURRENT_DATE
                    ORDER BY category, service_name
                """)
            else:
                db.cursor.execute("""
                    SELECT * FROM platform_cost_definitions
                    ORDER BY category, service_name, active_from DESC
                """)

            rows = db.cursor.fetchall()
            data = []
            for row in rows:
                data.append({
                    'id': row['id'],
                    'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                    'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
                    'service_name': row['service_name'],
                    'category': row['category'],
                    'description': row['description'],
                    'monthly_cost_usd': float(row['monthly_cost_usd']),
                    'billing_cycle': row['billing_cycle'],
                    'active_from': row['active_from'].isoformat() if row['active_from'] else None,
                    'active_until': row['active_until'].isoformat() if row['active_until'] else None,
                    'url': row['url'],
                    'notes': row['notes'],
                })

            return jsonify({'success': True, 'data': data})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@platform_costs_bp.route('/platform-costs', methods=['POST'])
def create_platform_cost():
    """Create a new platform cost definition."""
    try:
        body = request.get_json()
        if not body:
            return jsonify({'success': False, 'error': 'Request body required'}), 400

        service_name = body.get('service_name', '').strip()
        if not service_name:
            return jsonify({'success': False, 'error': 'service_name is required'}), 400

        category = body.get('category', 'infrastructure')
        if category not in VALID_CATEGORIES:
            return jsonify({'success': False, 'error': f'Invalid category. Must be one of: {VALID_CATEGORIES}'}), 400

        monthly_cost_usd = body.get('monthly_cost_usd')
        if monthly_cost_usd is None:
            return jsonify({'success': False, 'error': 'monthly_cost_usd is required'}), 400

        try:
            monthly_cost_usd = float(monthly_cost_usd)
            if monthly_cost_usd < 0:
                raise ValueError()
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'monthly_cost_usd must be a non-negative number'}), 400

        billing_cycle = body.get('billing_cycle', 'monthly')
        if billing_cycle not in VALID_BILLING_CYCLES:
            return jsonify({'success': False, 'error': f'Invalid billing_cycle. Must be one of: {VALID_BILLING_CYCLES}'}), 400

        active_from = body.get('active_from')
        if active_from:
            active_from = date.fromisoformat(active_from)
        else:
            # Default: first day of current month
            today = get_bogota_now().date()
            active_from = today.replace(day=1)

        description = body.get('description', '').strip() or None
        url = body.get('url', '').strip() or None
        notes = body.get('notes', '').strip() or None

        with DatabaseManager() as db:
            db.cursor.execute("""
                INSERT INTO platform_cost_definitions
                    (service_name, category, description, monthly_cost_usd, billing_cycle, active_from, url, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (service_name, category, description, monthly_cost_usd, billing_cycle, active_from, url, notes))

            new_id = db.cursor.fetchone()['id']
            db.conn.commit()

            return jsonify({'success': True, 'data': {'id': new_id}}), 201

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@platform_costs_bp.route('/platform-costs/<int:cost_id>', methods=['PUT'])
def update_platform_cost(cost_id):
    """Update an existing platform cost definition."""
    try:
        body = request.get_json()
        if not body:
            return jsonify({'success': False, 'error': 'Request body required'}), 400

        with DatabaseManager() as db:
            # Verify exists
            db.cursor.execute("SELECT id FROM platform_cost_definitions WHERE id = %s", (cost_id,))
            if not db.cursor.fetchone():
                return jsonify({'success': False, 'error': 'Cost definition not found'}), 404

            # Build SET clause dynamically
            updates = []
            params = []

            if 'service_name' in body:
                val = body['service_name'].strip()
                if not val:
                    return jsonify({'success': False, 'error': 'service_name cannot be empty'}), 400
                updates.append("service_name = %s")
                params.append(val)

            if 'category' in body:
                if body['category'] not in VALID_CATEGORIES:
                    return jsonify({'success': False, 'error': f'Invalid category'}), 400
                updates.append("category = %s")
                params.append(body['category'])

            if 'monthly_cost_usd' in body:
                try:
                    cost = float(body['monthly_cost_usd'])
                    if cost < 0:
                        raise ValueError()
                except (ValueError, TypeError):
                    return jsonify({'success': False, 'error': 'monthly_cost_usd must be non-negative'}), 400
                updates.append("monthly_cost_usd = %s")
                params.append(cost)

            if 'billing_cycle' in body:
                if body['billing_cycle'] not in VALID_BILLING_CYCLES:
                    return jsonify({'success': False, 'error': 'Invalid billing_cycle'}), 400
                updates.append("billing_cycle = %s")
                params.append(body['billing_cycle'])

            if 'active_from' in body:
                updates.append("active_from = %s")
                params.append(date.fromisoformat(body['active_from']))

            if 'active_until' in body:
                if body['active_until'] is None:
                    updates.append("active_until = NULL")
                else:
                    updates.append("active_until = %s")
                    params.append(date.fromisoformat(body['active_until']))

            if 'description' in body:
                updates.append("description = %s")
                params.append(body['description'].strip() if body['description'] else None)

            if 'url' in body:
                updates.append("url = %s")
                params.append(body['url'].strip() if body['url'] else None)

            if 'notes' in body:
                updates.append("notes = %s")
                params.append(body['notes'].strip() if body['notes'] else None)

            if not updates:
                return jsonify({'success': False, 'error': 'No fields to update'}), 400

            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(cost_id)

            query = f"UPDATE platform_cost_definitions SET {', '.join(updates)} WHERE id = %s"
            db.cursor.execute(query, params)
            db.conn.commit()

            return jsonify({'success': True, 'data': {'id': cost_id}})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@platform_costs_bp.route('/platform-costs/<int:cost_id>', methods=['DELETE'])
def deactivate_platform_cost(cost_id):
    """Soft-delete: set active_until = today."""
    try:
        with DatabaseManager() as db:
            db.cursor.execute("SELECT id FROM platform_cost_definitions WHERE id = %s", (cost_id,))
            if not db.cursor.fetchone():
                return jsonify({'success': False, 'error': 'Cost definition not found'}), 404

            today = get_bogota_now().date()
            db.cursor.execute("""
                UPDATE platform_cost_definitions
                SET active_until = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (today, cost_id))
            db.conn.commit()

            return jsonify({'success': True, 'data': {'id': cost_id, 'active_until': today.isoformat()}})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# Consolidated View — AI + Platform costs combined
# ============================================================

def _get_platform_costs_for_month(db, first_day, last_day):
    """Get platform costs active during a given month."""
    db.cursor.execute("""
        SELECT service_name, category, monthly_cost_usd
        FROM platform_cost_definitions
        WHERE active_from <= %s
          AND (active_until IS NULL OR active_until >= %s)
        ORDER BY category, service_name
    """, (last_day, first_day))

    rows = db.cursor.fetchall()
    total = sum(float(r['monthly_cost_usd']) for r in rows)
    breakdown = [{
        'service_name': r['service_name'],
        'category': r['category'],
        'cost_usd': float(r['monthly_cost_usd']),
    } for r in rows]

    return total, breakdown


def _get_ai_costs_for_month(db, first_day, last_day):
    """Get AI costs for a given month from ai_usage_log."""
    next_month_first = last_day + timedelta(days=1)
    db.cursor.execute("""
        SELECT COALESCE(SUM(estimated_cost_usd), 0) as total
        FROM ai_usage_log
        WHERE created_at >= %s AND created_at < %s
    """, (first_day, next_month_first))

    row = db.cursor.fetchone()
    return float(row['total'])


def _get_ai_breakdown_for_month(db, first_day, last_day):
    """Get AI costs broken down by model for a given month."""
    next_month_first = last_day + timedelta(days=1)
    db.cursor.execute("""
        SELECT model,
               COALESCE(SUM(estimated_cost_usd), 0) as cost_usd,
               COUNT(*) as calls
        FROM ai_usage_log
        WHERE created_at >= %s AND created_at < %s
        GROUP BY model
        ORDER BY cost_usd DESC
    """, (first_day, next_month_first))

    rows = db.cursor.fetchall()
    total_cost = sum(float(r['cost_usd']) for r in rows)
    breakdown = []
    for r in rows:
        cost = float(r['cost_usd'])
        breakdown.append({
            'model': r['model'],
            'cost_usd': round(cost, 6),
            'calls': r['calls'],
            'percentage': round((cost / total_cost * 100), 1) if total_cost > 0 else 0,
        })
    return breakdown


@platform_costs_bp.route('/costs/consolidated', methods=['GET'])
def get_consolidated_costs():
    """Get combined AI + platform costs per month."""
    try:
        num_months = int(request.args.get('months', 6))
        num_months = max(1, min(num_months, 24))

        now = get_bogota_now()
        months_data = []

        with DatabaseManager() as db:
            for i in range(num_months):
                # Walk backwards from current month
                month_offset = num_months - 1 - i
                year = now.year
                month = now.month - month_offset

                while month <= 0:
                    month += 12
                    year -= 1

                first_day, last_day = get_month_range(year, month)
                month_label = first_day.strftime('%Y-%m')

                ai_cost = _get_ai_costs_for_month(db, first_day, last_day)
                platform_cost, platform_breakdown = _get_platform_costs_for_month(db, first_day, last_day)
                total = ai_cost + platform_cost

                ai_pct = round((ai_cost / total * 100), 1) if total > 0 else 0
                platform_pct = round((platform_cost / total * 100), 1) if total > 0 else 0

                ai_breakdown = _get_ai_breakdown_for_month(db, first_day, last_day)

                months_data.append({
                    'month': month_label,
                    'ai_cost_usd': round(ai_cost, 2),
                    'platform_cost_usd': round(platform_cost, 2),
                    'total_cost_usd': round(total, 2),
                    'ai_percentage': ai_pct,
                    'platform_percentage': platform_pct,
                    'platform_breakdown': platform_breakdown,
                    'ai_breakdown': ai_breakdown,
                })

        total_ai = sum(m['ai_cost_usd'] for m in months_data)
        total_platform = sum(m['platform_cost_usd'] for m in months_data)
        grand_total = total_ai + total_platform

        # Current month detail (last entry)
        current = months_data[-1] if months_data else None
        current_month = None
        if current:
            current_month = {
                'month': current['month'],
                'ai_cost_usd': current['ai_cost_usd'],
                'platform_cost_usd': current['platform_cost_usd'],
                'total_cost_usd': current['total_cost_usd'],
                'platform_breakdown': current['platform_breakdown'],
                'ai_breakdown': current['ai_breakdown'],
            }

        # Monthly average
        num = len(months_data) if months_data else 1
        monthly_average_usd = round(grand_total / num, 2)

        # Month-over-month change (compare last 2 months)
        mom_change = {'total_pct': 0.0, 'ai_pct': 0.0, 'platform_pct': 0.0}
        if len(months_data) >= 2:
            prev = months_data[-2]
            curr = months_data[-1]
            if prev['total_cost_usd'] > 0:
                mom_change['total_pct'] = round(
                    (curr['total_cost_usd'] - prev['total_cost_usd']) / prev['total_cost_usd'] * 100, 1)
            if prev['ai_cost_usd'] > 0:
                mom_change['ai_pct'] = round(
                    (curr['ai_cost_usd'] - prev['ai_cost_usd']) / prev['ai_cost_usd'] * 100, 1)
            if prev['platform_cost_usd'] > 0:
                mom_change['platform_pct'] = round(
                    (curr['platform_cost_usd'] - prev['platform_cost_usd']) / prev['platform_cost_usd'] * 100, 1)

        return jsonify({
            'success': True,
            'data': {
                'months': months_data,
                'totals': {
                    'total_ai_usd': round(total_ai, 2),
                    'total_platform_usd': round(total_platform, 2),
                    'grand_total_usd': round(grand_total, 2),
                },
                'current_month': current_month,
                'monthly_average_usd': monthly_average_usd,
                'month_over_month_change': mom_change,
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@platform_costs_bp.route('/costs/consolidated/export', methods=['GET'])
def export_consolidated_costs():
    """Export consolidated costs as CSV."""
    try:
        num_months = int(request.args.get('months', 12))
        num_months = max(1, min(num_months, 24))

        now = get_bogota_now()

        # Collect all unique service names for dynamic columns
        all_services = set()
        months_data = []

        with DatabaseManager() as db:
            for i in range(num_months):
                month_offset = num_months - 1 - i
                year = now.year
                month = now.month - month_offset

                while month <= 0:
                    month += 12
                    year -= 1

                first_day, last_day = get_month_range(year, month)
                month_label = first_day.strftime('%Y-%m')

                ai_cost = _get_ai_costs_for_month(db, first_day, last_day)
                platform_cost, platform_breakdown = _get_platform_costs_for_month(db, first_day, last_day)
                total = ai_cost + platform_cost
                ai_pct = round((ai_cost / total * 100), 1) if total > 0 else 0

                service_costs = {}
                for item in platform_breakdown:
                    name = item['service_name']
                    all_services.add(name)
                    service_costs[name] = item['cost_usd']

                months_data.append({
                    'month': month_label,
                    'ai_cost': ai_cost,
                    'platform_cost': platform_cost,
                    'total': total,
                    'ai_pct': ai_pct,
                    'service_costs': service_costs,
                })

        # Build CSV
        service_list = sorted(all_services)
        output = io.StringIO()
        writer = csv.writer(output)

        headers = ['Mes', 'Costo IA (USD)', 'Costo Plataforma (USD)', 'Total (USD)', '% IA'] + service_list
        writer.writerow(headers)

        for m in months_data:
            row = [
                m['month'],
                f"{m['ai_cost']:.2f}",
                f"{m['platform_cost']:.2f}",
                f"{m['total']:.2f}",
                f"{m['ai_pct']:.1f}%",
            ]
            for svc in service_list:
                row.append(f"{m['service_costs'].get(svc, 0):.2f}")
            writer.writerow(row)

        csv_content = output.getvalue()
        output.close()

        from flask import Response
        return Response(
            csv_content,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=costos_consolidados_{now.strftime("%Y%m%d")}.csv'
            }
        )

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
