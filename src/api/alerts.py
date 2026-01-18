#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alerts API - Gestión de umbrales de alertas y historial
"""

from flask import Blueprint, request, jsonify
from src.db.database import DatabaseManager
from datetime import datetime, timedelta
import pytz

alerts_bp = Blueprint('alerts', __name__, url_prefix='/api/alerts')

# Zona horaria de Bogotá
BOGOTA_TZ = pytz.timezone('America/Bogota')


def get_bogota_now():
    """Get current time in Bogota timezone."""
    return datetime.now(BOGOTA_TZ)


@alerts_bp.route('/config', methods=['GET'])
def get_alert_config():
    """
    Get all configured alert thresholds.
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    id,
                    metric_name,
                    display_name,
                    description,
                    warning_threshold,
                    critical_threshold,
                    comparison_operator,
                    unit,
                    enabled,
                    created_at,
                    updated_at
                FROM alert_thresholds
                ORDER BY metric_name
            """)

            thresholds = []
            for row in db.cursor.fetchall():
                thresholds.append({
                    'id': row['id'],
                    'metric_name': row['metric_name'],
                    'display_name': row['display_name'],
                    'description': row['description'],
                    'warning_threshold': float(row['warning_threshold']) if row['warning_threshold'] else None,
                    'critical_threshold': float(row['critical_threshold']) if row['critical_threshold'] else None,
                    'comparison_operator': row['comparison_operator'],
                    'unit': row['unit'],
                    'enabled': row['enabled'],
                    'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                    'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None
                })

            return jsonify({
                'success': True,
                'data': thresholds
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@alerts_bp.route('/config/<int:threshold_id>', methods=['PUT'])
def update_threshold(threshold_id):
    """
    Update a specific alert threshold.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        # Campos actualizables
        allowed_fields = ['warning_threshold', 'critical_threshold', 'enabled', 'display_name', 'description']
        updates = {k: v for k, v in data.items() if k in allowed_fields}

        if not updates:
            return jsonify({'success': False, 'error': 'No valid fields to update'}), 400

        with DatabaseManager() as db:
            # Construir query dinámico
            set_clauses = []
            values = []
            for field, value in updates.items():
                set_clauses.append(f"{field} = %s")
                values.append(value)

            values.append(threshold_id)

            query = f"""
                UPDATE alert_thresholds
                SET {', '.join(set_clauses)}
                WHERE id = %s
                RETURNING id, metric_name, display_name, warning_threshold, critical_threshold, enabled
            """

            db.cursor.execute(query, values)
            updated = db.cursor.fetchone()

            if not updated:
                return jsonify({'success': False, 'error': 'Threshold not found'}), 404

            db.conn.commit()

            return jsonify({
                'success': True,
                'data': {
                    'id': updated['id'],
                    'metric_name': updated['metric_name'],
                    'display_name': updated['display_name'],
                    'warning_threshold': float(updated['warning_threshold']) if updated['warning_threshold'] else None,
                    'critical_threshold': float(updated['critical_threshold']) if updated['critical_threshold'] else None,
                    'enabled': updated['enabled']
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@alerts_bp.route('/config/<int:threshold_id>/toggle', methods=['POST'])
def toggle_threshold(threshold_id):
    """
    Toggle enabled/disabled status of a threshold.
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute("""
                UPDATE alert_thresholds
                SET enabled = NOT enabled
                WHERE id = %s
                RETURNING id, metric_name, enabled
            """, (threshold_id,))

            updated = db.cursor.fetchone()

            if not updated:
                return jsonify({'success': False, 'error': 'Threshold not found'}), 404

            db.conn.commit()

            return jsonify({
                'success': True,
                'data': {
                    'id': updated['id'],
                    'metric_name': updated['metric_name'],
                    'enabled': updated['enabled']
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@alerts_bp.route('/history', methods=['GET'])
def get_alert_history():
    """
    Get alert history with optional filters.
    """
    try:
        days = int(request.args.get('days', 7))
        limit = int(request.args.get('limit', 50))
        severity = request.args.get('severity')  # 'warning', 'critical', or None for all
        metric = request.args.get('metric')  # Filter by specific metric

        start_date = get_bogota_now() - timedelta(days=days)

        with DatabaseManager() as db:
            # Build query with optional filters
            query = """
                SELECT
                    id,
                    metric_name,
                    metric_value,
                    threshold_value,
                    severity,
                    triggered_at,
                    resolved_at,
                    context,
                    acknowledged,
                    acknowledged_by,
                    acknowledged_at
                FROM alert_history
                WHERE triggered_at >= %s
            """
            params = [start_date]

            if severity:
                query += " AND severity = %s"
                params.append(severity)

            if metric:
                query += " AND metric_name = %s"
                params.append(metric)

            query += " ORDER BY triggered_at DESC LIMIT %s"
            params.append(limit)

            db.cursor.execute(query, params)

            alerts = []
            for row in db.cursor.fetchall():
                alerts.append({
                    'id': row['id'],
                    'metric_name': row['metric_name'],
                    'metric_value': float(row['metric_value']) if row['metric_value'] else None,
                    'threshold_value': float(row['threshold_value']) if row['threshold_value'] else None,
                    'severity': row['severity'],
                    'triggered_at': row['triggered_at'].isoformat() if row['triggered_at'] else None,
                    'resolved_at': row['resolved_at'].isoformat() if row['resolved_at'] else None,
                    'context': row['context'] or {},
                    'acknowledged': row['acknowledged'],
                    'acknowledged_by': row['acknowledged_by'],
                    'acknowledged_at': row['acknowledged_at'].isoformat() if row['acknowledged_at'] else None
                })

            # Get summary stats
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total_alerts,
                    SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) as critical_count,
                    SUM(CASE WHEN severity = 'warning' THEN 1 ELSE 0 END) as warning_count,
                    SUM(CASE WHEN resolved_at IS NULL THEN 1 ELSE 0 END) as unresolved_count
                FROM alert_history
                WHERE triggered_at >= %s
            """, (start_date,))

            summary = db.cursor.fetchone()

            return jsonify({
                'success': True,
                'data': {
                    'alerts': alerts,
                    'summary': {
                        'total_alerts': summary['total_alerts'] or 0,
                        'critical_count': summary['critical_count'] or 0,
                        'warning_count': summary['warning_count'] or 0,
                        'unresolved_count': summary['unresolved_count'] or 0
                    },
                    'period_days': days
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@alerts_bp.route('/history/<int:alert_id>/acknowledge', methods=['POST'])
def acknowledge_alert(alert_id):
    """
    Acknowledge an alert.
    """
    try:
        data = request.get_json() or {}
        acknowledged_by = data.get('acknowledged_by', 'system')

        with DatabaseManager() as db:
            db.cursor.execute("""
                UPDATE alert_history
                SET
                    acknowledged = TRUE,
                    acknowledged_by = %s,
                    acknowledged_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, metric_name, acknowledged
            """, (acknowledged_by, alert_id))

            updated = db.cursor.fetchone()

            if not updated:
                return jsonify({'success': False, 'error': 'Alert not found'}), 404

            db.conn.commit()

            return jsonify({
                'success': True,
                'data': {
                    'id': updated['id'],
                    'metric_name': updated['metric_name'],
                    'acknowledged': updated['acknowledged']
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@alerts_bp.route('/active', methods=['GET'])
def get_active_alerts():
    """
    Get currently active (unresolved) alerts.
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    ah.id,
                    ah.metric_name,
                    at.display_name,
                    ah.metric_value,
                    ah.threshold_value,
                    ah.severity,
                    ah.triggered_at,
                    ah.context,
                    ah.acknowledged
                FROM alert_history ah
                LEFT JOIN alert_thresholds at ON ah.metric_name = at.metric_name
                WHERE ah.resolved_at IS NULL
                ORDER BY
                    CASE ah.severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
                    ah.triggered_at DESC
            """)

            alerts = []
            for row in db.cursor.fetchall():
                alerts.append({
                    'id': row['id'],
                    'metric_name': row['metric_name'],
                    'display_name': row['display_name'],
                    'metric_value': float(row['metric_value']) if row['metric_value'] else None,
                    'threshold_value': float(row['threshold_value']) if row['threshold_value'] else None,
                    'severity': row['severity'],
                    'triggered_at': row['triggered_at'].isoformat() if row['triggered_at'] else None,
                    'context': row['context'] or {},
                    'acknowledged': row['acknowledged']
                })

            return jsonify({
                'success': True,
                'data': {
                    'active_alerts': alerts,
                    'count': len(alerts),
                    'has_critical': any(a['severity'] == 'critical' for a in alerts)
                }
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
