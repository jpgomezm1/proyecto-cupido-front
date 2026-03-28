#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API REST para Share Analytics - Proyecto Cupido
Tracking de eventos y metricas de links compartidos
"""

from flask import Blueprint, jsonify, request
from src.db.database import DatabaseManager
import traceback
import hashlib
from datetime import datetime

# Crear blueprint para Share Analytics API
share_analytics_bp = Blueprint('share_analytics', __name__, url_prefix='/api/share-analytics')


def get_db():
    """Helper para obtener conexión a la base de datos"""
    db = DatabaseManager()
    if not db.connect():
        raise ConnectionError("No se pudo conectar a la base de datos")
    return db


def hash_visitor_id(fingerprint: str) -> str:
    """Genera un hash anonimo del fingerprint del visitante"""
    if not fingerprint:
        return None
    return hashlib.sha256(fingerprint.encode()).hexdigest()[:32]


@share_analytics_bp.route('/events', methods=['POST'])
def track_event():
    """
    POST /api/share-analytics/events

    Registra un evento de tracking desde el frontend.

    Body:
    {
        "share_id": "abc123",
        "event_type": "share_viewed" | "property_clicked" | "whatsapp_clicked" | "phone_clicked",
        "property_id": 123,  // opcional
        "visitor_fingerprint": "anonymous-fingerprint",  // se hashea en servidor
        "session_id": "session-uuid",
        "share_type": "agente" | "cliente",
        "property_count": 5,
        "device_info": {
            "device_type": "mobile" | "desktop" | "tablet",
            "browser": "Chrome",
            "os": "Windows"
        },
        "utm_params": {
            "source": "whatsapp",
            "medium": "share",
            "campaign": "agent_123"
        },
        "referrer_domain": "wa.me"
    }
    """
    db = None
    try:
        db = get_db()
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        share_id = data.get('share_id')
        event_type = data.get('event_type')

        if not share_id or not event_type:
            return jsonify({'success': False, 'error': 'share_id and event_type are required'}), 400

        valid_events = ['share_viewed', 'property_clicked', 'whatsapp_clicked', 'phone_clicked']
        if event_type not in valid_events:
            return jsonify({'success': False, 'error': f'Invalid event_type. Must be one of: {valid_events}'}), 400

        # Hash del fingerprint para anonimizar
        visitor_fingerprint = data.get('visitor_fingerprint', '')
        visitor_id = hash_visitor_id(visitor_fingerprint)
        session_id = data.get('session_id')

        # Deduplicar views por sesion
        if event_type == 'share_viewed' and session_id:
            db.cursor.execute("""
                SELECT id FROM share_events
                WHERE share_id = %s AND session_id = %s AND event_type = 'share_viewed'
                LIMIT 1
            """, (share_id, session_id))
            if db.cursor.fetchone():
                return jsonify({'success': True, 'data': {'deduplicated': True}}), 200

        # Obtener selection_id y creator_user_id del share
        db.cursor.execute("""
            SELECT id, user_id, array_length(property_ids, 1) as prop_count
            FROM shared_property_selections
            WHERE share_id = %s
        """, (share_id,))
        selection = db.cursor.fetchone()

        selection_id = selection['id'] if selection else None
        creator_user_id = selection['user_id'] if selection else None
        property_count = data.get('property_count') or (selection['prop_count'] if selection else None)

        # Extraer device info
        device_info = data.get('device_info', {})
        device_type = device_info.get('device_type')
        browser = device_info.get('browser')
        os = device_info.get('os')

        # Extraer UTM params
        utm_params = data.get('utm_params', {})
        utm_source = utm_params.get('source')
        utm_medium = utm_params.get('medium')
        utm_campaign = utm_params.get('campaign')

        # Insertar evento
        db.cursor.execute("""
            INSERT INTO share_events (
                share_id, selection_id, event_type, share_type, property_count,
                creator_user_id, visitor_id, session_id, property_id,
                device_type, browser, os, referrer_domain,
                utm_source, utm_medium, utm_campaign, event_data
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            share_id,
            selection_id,
            event_type,
            data.get('share_type'),
            property_count,
            creator_user_id,
            visitor_id,
            session_id,
            data.get('property_id'),
            device_type,
            browser,
            os,
            data.get('referrer_domain'),
            utm_source,
            utm_medium,
            utm_campaign,
            '{}'
        ))
        event_id = db.cursor.fetchone()['id']

        # Actualizar contadores en shared_property_selections
        if selection_id:
            if event_type == 'share_viewed':
                # Contar visitantes unicos
                db.cursor.execute("""
                    UPDATE shared_property_selections
                    SET view_count = view_count + 1,
                        unique_visitors = (
                            SELECT COUNT(DISTINCT visitor_id)
                            FROM share_events
                            WHERE selection_id = %s AND event_type = 'share_viewed'
                        )
                    WHERE id = %s
                """, (selection_id, selection_id))
            elif event_type == 'property_clicked':
                db.cursor.execute("""
                    UPDATE shared_property_selections
                    SET total_clicks = total_clicks + 1
                    WHERE id = %s
                """, (selection_id,))
            elif event_type == 'whatsapp_clicked':
                db.cursor.execute("""
                    UPDATE shared_property_selections
                    SET whatsapp_clicks = whatsapp_clicks + 1
                    WHERE id = %s
                """, (selection_id,))

        db.conn.commit()

        return jsonify({
            'success': True,
            'data': {'event_id': event_id}
        }), 201

    except Exception as e:
        print(f"[SHARE_ANALYTICS] Error tracking event: {e}")
        traceback.print_exc()
        if db:
            db.conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@share_analytics_bp.route('/overview', methods=['GET'])
def get_overview():
    """
    GET /api/share-analytics/overview?days=30

    Obtiene metricas generales de shares.

    Returns:
    {
        "success": true,
        "data": {
            "total_shares": 150,
            "total_views": 1200,
            "unique_visitors": 800,
            "property_clicks": 300,
            "whatsapp_clicks": 100,
            "conversion_rate": 8.33,
            "trend": [...],
            "by_type": { "agente": {...}, "cliente": {...} }
        }
    }
    """
    db = None
    try:
        db = get_db()
        days = int(request.args.get('days', 30))

        # Totales
        db.cursor.execute("""
            SELECT
                COUNT(DISTINCT sps.id) as total_shares,
                COALESCE(SUM(se.view_count), 0) as total_views,
                COALESCE(SUM(se.unique_visitors), 0) as unique_visitors_sum
            FROM shared_property_selections sps
            LEFT JOIN (
                SELECT selection_id,
                       COUNT(*) FILTER (WHERE event_type = 'share_viewed') as view_count,
                       COUNT(DISTINCT visitor_id) FILTER (WHERE event_type = 'share_viewed') as unique_visitors
                FROM share_events
                WHERE created_at >= CURRENT_DATE - INTERVAL '%s days'
                GROUP BY selection_id
            ) se ON sps.id = se.selection_id
            WHERE sps.created_at >= CURRENT_DATE - INTERVAL '%s days'
        """ % (days, days))
        totals = db.cursor.fetchone()

        # Eventos por tipo
        db.cursor.execute("""
            SELECT
                COUNT(*) FILTER (WHERE event_type = 'share_viewed') as total_views,
                COUNT(DISTINCT visitor_id) FILTER (WHERE event_type = 'share_viewed') as unique_visitors,
                COUNT(*) FILTER (WHERE event_type = 'property_clicked') as property_clicks,
                COUNT(*) FILTER (WHERE event_type = 'whatsapp_clicked') as whatsapp_clicks,
                COUNT(*) FILTER (WHERE event_type = 'phone_clicked') as phone_clicks
            FROM share_events
            WHERE created_at >= CURRENT_DATE - INTERVAL '%s days'
        """ % days)
        events = db.cursor.fetchone()

        total_views = events['total_views'] or 0
        whatsapp_clicks = events['whatsapp_clicks'] or 0
        conversion_rate = round((whatsapp_clicks / total_views * 100), 2) if total_views > 0 else 0

        # Tendencia diaria
        db.cursor.execute("""
            SELECT
                DATE(created_at) as date,
                COUNT(*) FILTER (WHERE event_type = 'share_viewed') as views,
                COUNT(DISTINCT share_id) FILTER (WHERE event_type = 'share_viewed') as shares_viewed,
                COUNT(*) FILTER (WHERE event_type = 'whatsapp_clicked') as whatsapp_clicks
            FROM share_events
            WHERE created_at >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY DATE(created_at)
            ORDER BY date ASC
        """ % days)
        trend = [
            {
                'date': str(row['date']),
                'views': row['views'] or 0,
                'shares_viewed': row['shares_viewed'] or 0,
                'whatsapp_clicks': row['whatsapp_clicks'] or 0
            }
            for row in db.cursor.fetchall()
        ]

        # Breakdown por tipo (agente/cliente)
        db.cursor.execute("""
            SELECT
                COALESCE(share_type, 'agente') as share_type,
                COUNT(*) FILTER (WHERE event_type = 'share_viewed') as views,
                COUNT(DISTINCT visitor_id) FILTER (WHERE event_type = 'share_viewed') as unique_visitors,
                COUNT(*) FILTER (WHERE event_type = 'whatsapp_clicked') as whatsapp_clicks
            FROM share_events
            WHERE created_at >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY COALESCE(share_type, 'agente')
        """ % days)
        by_type = {}
        for row in db.cursor.fetchall():
            by_type[row['share_type']] = {
                'views': row['views'] or 0,
                'unique_visitors': row['unique_visitors'] or 0,
                'whatsapp_clicks': row['whatsapp_clicks'] or 0
            }

        # Total de shares creados en el periodo
        db.cursor.execute("""
            SELECT COUNT(*) as total
            FROM shared_property_selections
            WHERE created_at >= CURRENT_DATE - INTERVAL '%s days'
        """ % days)
        total_shares = db.cursor.fetchone()['total'] or 0

        return jsonify({
            'success': True,
            'data': {
                'total_shares': total_shares,
                'total_views': total_views,
                'unique_visitors': events['unique_visitors'] or 0,
                'property_clicks': events['property_clicks'] or 0,
                'whatsapp_clicks': whatsapp_clicks,
                'phone_clicks': events['phone_clicks'] or 0,
                'conversion_rate': conversion_rate,
                'trend': trend,
                'by_type': by_type
            }
        }), 200

    except Exception as e:
        print(f"[SHARE_ANALYTICS] Error in overview: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@share_analytics_bp.route('/agent-performance', methods=['GET'])
def get_agent_performance():
    """
    GET /api/share-analytics/agent-performance?days=30

    Obtiene performance de shares por agente/usuario.

    Returns:
    {
        "success": true,
        "data": [
            {
                "user_id": 1,
                "name": "Agente Nombre",
                "phone": "+573001234567",
                "total_shares": 25,
                "total_views": 150,
                "unique_visitors": 100,
                "property_clicks": 30,
                "whatsapp_clicks": 12,
                "conversion_rate": 8.0,
                "avg_views_per_share": 6.0
            },
            ...
        ]
    }
    """
    db = None
    try:
        db = get_db()
        days = int(request.args.get('days', 30))

        db.cursor.execute("""
            SELECT
                sps.user_id,
                cu.nombre as name,
                cu.telefono as phone,
                COUNT(DISTINCT sps.id) as total_shares,
                COALESCE(SUM(CASE WHEN se.event_type = 'share_viewed' THEN 1 ELSE 0 END), 0) as total_views,
                COUNT(DISTINCT CASE WHEN se.event_type = 'share_viewed' THEN se.visitor_id END) as unique_visitors,
                COALESCE(SUM(CASE WHEN se.event_type = 'property_clicked' THEN 1 ELSE 0 END), 0) as property_clicks,
                COALESCE(SUM(CASE WHEN se.event_type = 'whatsapp_clicked' THEN 1 ELSE 0 END), 0) as whatsapp_clicks
            FROM shared_property_selections sps
            LEFT JOIN share_events se ON sps.share_id = se.share_id
                AND se.created_at >= CURRENT_DATE - INTERVAL '%s days'
            LEFT JOIN chat_users cu ON sps.user_id = cu.id
            WHERE sps.created_at >= CURRENT_DATE - INTERVAL '%s days'
            AND sps.user_id IS NOT NULL
            GROUP BY sps.user_id, cu.nombre, cu.telefono
            ORDER BY total_views DESC
        """ % (days, days))

        agents = []
        for row in db.cursor.fetchall():
            total_views = row['total_views'] or 0
            whatsapp_clicks = row['whatsapp_clicks'] or 0
            total_shares = row['total_shares'] or 0

            agents.append({
                'user_id': row['user_id'],
                'name': row['name'] or 'Sin nombre',
                'phone': row['phone'],
                'total_shares': total_shares,
                'total_views': total_views,
                'unique_visitors': row['unique_visitors'] or 0,
                'property_clicks': row['property_clicks'] or 0,
                'whatsapp_clicks': whatsapp_clicks,
                'conversion_rate': round((whatsapp_clicks / total_views * 100), 2) if total_views > 0 else 0,
                'avg_views_per_share': round(total_views / total_shares, 1) if total_shares > 0 else 0
            })

        return jsonify({
            'success': True,
            'data': agents
        }), 200

    except Exception as e:
        print(f"[SHARE_ANALYTICS] Error in agent-performance: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@share_analytics_bp.route('/share/<share_id>', methods=['GET'])
def get_share_detail(share_id: str):
    """
    GET /api/share-analytics/share/:share_id

    Obtiene detalle de analytics para un share especifico.

    Returns:
    {
        "success": true,
        "data": {
            "share_id": "abc123",
            "created_at": "2025-01-20T10:00:00",
            "property_count": 5,
            "total_views": 50,
            "unique_visitors": 30,
            "property_clicks": 10,
            "whatsapp_clicks": 5,
            "conversion_rate": 10.0,
            "events_timeline": [...],
            "devices": {...},
            "referrers": [...]
        }
    }
    """
    db = None
    try:
        db = get_db()

        # Info basica del share
        db.cursor.execute("""
            SELECT
                sps.id,
                sps.share_id,
                sps.created_at,
                array_length(sps.property_ids, 1) as property_count,
                sps.user_id,
                cu.nombre as creator_name
            FROM shared_property_selections sps
            LEFT JOIN chat_users cu ON sps.user_id = cu.id
            WHERE sps.share_id = %s
        """, (share_id,))
        share = db.cursor.fetchone()

        if not share:
            return jsonify({'success': False, 'error': 'Share not found'}), 404

        # Metricas del share
        db.cursor.execute("""
            SELECT
                COUNT(*) FILTER (WHERE event_type = 'share_viewed') as total_views,
                COUNT(DISTINCT visitor_id) FILTER (WHERE event_type = 'share_viewed') as unique_visitors,
                COUNT(*) FILTER (WHERE event_type = 'property_clicked') as property_clicks,
                COUNT(*) FILTER (WHERE event_type = 'whatsapp_clicked') as whatsapp_clicks,
                COUNT(*) FILTER (WHERE event_type = 'phone_clicked') as phone_clicks
            FROM share_events
            WHERE share_id = %s
        """, (share_id,))
        metrics = db.cursor.fetchone()

        total_views = metrics['total_views'] or 0
        whatsapp_clicks = metrics['whatsapp_clicks'] or 0

        # Timeline de eventos (ultimos 50)
        db.cursor.execute("""
            SELECT
                event_type,
                created_at,
                property_id,
                device_type,
                referrer_domain
            FROM share_events
            WHERE share_id = %s
            ORDER BY created_at DESC
            LIMIT 50
        """, (share_id,))
        timeline = [
            {
                'event_type': row['event_type'],
                'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                'property_id': row['property_id'],
                'device_type': row['device_type'],
                'referrer_domain': row['referrer_domain']
            }
            for row in db.cursor.fetchall()
        ]

        # Distribucion por dispositivo
        db.cursor.execute("""
            SELECT
                COALESCE(device_type, 'unknown') as device_type,
                COUNT(*) as count
            FROM share_events
            WHERE share_id = %s AND event_type = 'share_viewed'
            GROUP BY device_type
        """, (share_id,))
        devices = {row['device_type']: row['count'] for row in db.cursor.fetchall()}

        # Top referrers
        db.cursor.execute("""
            SELECT
                COALESCE(referrer_domain, 'direct') as referrer,
                COUNT(*) as count
            FROM share_events
            WHERE share_id = %s AND event_type = 'share_viewed'
            GROUP BY referrer_domain
            ORDER BY count DESC
            LIMIT 10
        """, (share_id,))
        referrers = [
            {'domain': row['referrer'], 'count': row['count']}
            for row in db.cursor.fetchall()
        ]

        return jsonify({
            'success': True,
            'data': {
                'share_id': share['share_id'],
                'created_at': share['created_at'].isoformat() if share['created_at'] else None,
                'property_count': share['property_count'] or 0,
                'creator_name': share['creator_name'],
                'total_views': total_views,
                'unique_visitors': metrics['unique_visitors'] or 0,
                'property_clicks': metrics['property_clicks'] or 0,
                'whatsapp_clicks': whatsapp_clicks,
                'phone_clicks': metrics['phone_clicks'] or 0,
                'conversion_rate': round((whatsapp_clicks / total_views * 100), 2) if total_views > 0 else 0,
                'events_timeline': timeline,
                'devices': devices,
                'referrers': referrers
            }
        }), 200

    except Exception as e:
        print(f"[SHARE_ANALYTICS] Error in share detail: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@share_analytics_bp.route('/top-shares', methods=['GET'])
def get_top_shares():
    """
    GET /api/share-analytics/top-shares?days=30&limit=10

    Obtiene los shares con mejor performance.

    Returns:
    {
        "success": true,
        "data": [
            {
                "share_id": "abc123",
                "created_at": "2025-01-20",
                "property_count": 5,
                "creator_name": "Agente",
                "total_views": 100,
                "unique_visitors": 60,
                "whatsapp_clicks": 15,
                "conversion_rate": 15.0
            },
            ...
        ]
    }
    """
    db = None
    try:
        db = get_db()
        days = int(request.args.get('days', 30))
        limit = int(request.args.get('limit', 10))

        db.cursor.execute("""
            SELECT
                sps.share_id,
                sps.created_at,
                array_length(sps.property_ids, 1) as property_count,
                cu.nombre as creator_name,
                COUNT(*) FILTER (WHERE se.event_type = 'share_viewed') as total_views,
                COUNT(DISTINCT se.visitor_id) FILTER (WHERE se.event_type = 'share_viewed') as unique_visitors,
                COUNT(*) FILTER (WHERE se.event_type = 'whatsapp_clicked') as whatsapp_clicks
            FROM shared_property_selections sps
            LEFT JOIN share_events se ON sps.share_id = se.share_id
            LEFT JOIN chat_users cu ON sps.user_id = cu.id
            WHERE sps.created_at >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY sps.share_id, sps.created_at, sps.property_ids, cu.nombre
            HAVING COUNT(*) FILTER (WHERE se.event_type = 'share_viewed') > 0
            ORDER BY total_views DESC
            LIMIT %s
        """ % (days, limit))

        shares = []
        for row in db.cursor.fetchall():
            total_views = row['total_views'] or 0
            whatsapp_clicks = row['whatsapp_clicks'] or 0
            shares.append({
                'share_id': row['share_id'],
                'created_at': row['created_at'].isoformat() if row['created_at'] else None,
                'property_count': row['property_count'] or 0,
                'creator_name': row['creator_name'] or 'Sin nombre',
                'total_views': total_views,
                'unique_visitors': row['unique_visitors'] or 0,
                'whatsapp_clicks': whatsapp_clicks,
                'conversion_rate': round((whatsapp_clicks / total_views * 100), 2) if total_views > 0 else 0
            })

        return jsonify({
            'success': True,
            'data': shares
        }), 200

    except Exception as e:
        print(f"[SHARE_ANALYTICS] Error in top-shares: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()
