#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API REST para Deals/Solicitudes - Proyecto Cupido
Gestión de deals inmobiliarios y trazabilidad
"""

from flask import Blueprint, jsonify, request
from src.db.database import DatabaseManager
import traceback
from datetime import datetime
from typing import Dict, List, Optional

# Crear blueprint
deals_bp = Blueprint('deals', __name__, url_prefix='/api/deals')

# Estados válidos del pipeline
DEAL_STATES = [
    'lead',
    'contactado',
    'visita_agendada',
    'visita_realizada',
    'negociando',
    'documentacion',
    'cierre',
    'ganado',
    'perdido'
]

# Mapeo de estados a campos de fecha
STATE_DATE_FIELDS = {
    'lead': 'fecha_lead',
    'contactado': 'fecha_contactado',
    'visita_agendada': 'fecha_visita_agendada',
    'visita_realizada': 'fecha_visita_realizada',
    'negociando': 'fecha_negociando',
    'documentacion': 'fecha_documentacion',
    'cierre': 'fecha_cierre',
    'ganado': 'fecha_resultado',
    'perdido': 'fecha_resultado'
}


def get_db():
    """Helper para obtener conexión a la base de datos"""
    db = DatabaseManager()
    if not db.connect():
        raise Exception("No se pudo conectar a la base de datos")
    return db


@deals_bp.route('', methods=['GET'])
def get_deals():
    """
    GET /api/deals

    Obtiene lista de deals con filtros opcionales

    Query params:
    - estado: Filtrar por estado
    - propiedad_id: Filtrar por propiedad
    - limit: Límite de resultados (default: 50)
    - offset: Offset para paginación
    """
    db = None
    try:
        db = get_db()

        # Parámetros
        estado = request.args.get('estado')
        propiedad_id = request.args.get('propiedad_id')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        query = """
            SELECT
                d.id, d.codigo, d.estado, d.prioridad,
                d.propiedad_id, d.contacto_id,
                d.tipo_comision, d.porcentaje_comision, d.valor_comision,
                d.precio_negociado, d.origen,
                d.fecha_creacion, d.fecha_actualizacion,
                d.agente_vendedor_telefono,
                -- Propiedad
                p.titulo as propiedad_titulo,
                p.precio as propiedad_precio,
                p.tipo_propiedad,
                p.ciudad as propiedad_ciudad,
                p.zona as propiedad_zona,
                p.imagen_principal as propiedad_imagen,
                p.fuente as propiedad_fuente,
                p.codigo_propiedad as propiedad_slug,
                -- Contacto
                c.nombre as contacto_nombre,
                c.telefono as contacto_telefono,
                c.email as contacto_email,
                -- Agente Vendedor (de la propiedad)
                av.nombre as agente_vendedor_nombre,
                -- Días
                EXTRACT(DAY FROM NOW() - d.fecha_actualizacion)::INTEGER as dias_en_estado,
                EXTRACT(DAY FROM NOW() - d.fecha_creacion)::INTEGER as dias_totales,
                -- Propiedades activas
                (SELECT COUNT(*) FROM deal_propiedades dp2
                 WHERE dp2.deal_id = d.id AND dp2.estado != 'descartado'
                ) as propiedades_activas
            FROM deals d
            JOIN propiedades p ON p.id = d.propiedad_id
            JOIN contactos c ON c.id = d.contacto_id
            LEFT JOIN agentes av ON av.telefono = d.agente_vendedor_telefono
            WHERE 1=1
        """
        params = []

        if estado:
            query += " AND d.estado = %s"
            params.append(estado)

        if propiedad_id:
            query += " AND d.propiedad_id = %s"
            params.append(int(propiedad_id))

        query += " ORDER BY d.fecha_actualizacion DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        db.cursor.execute(query, params)
        deals = [dict(row) for row in db.cursor.fetchall()]

        # Convertir fechas
        for deal in deals:
            for key, value in deal.items():
                if hasattr(value, 'isoformat'):
                    deal[key] = value.isoformat()

        return jsonify({
            'success': True,
            'data': deals,
            'count': len(deals)
        }), 200

    except Exception as e:
        print(f"❌ Error en get_deals: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@deals_bp.route('/pipeline', methods=['GET'])
def get_pipeline():
    """
    GET /api/deals/pipeline

    Obtiene deals agrupados por estado para vista Kanban
    """
    db = None
    try:
        db = get_db()

        pipeline = {}

        for estado in DEAL_STATES:
            if estado in ['ganado', 'perdido']:
                continue  # Estos se muestran aparte

            db.cursor.execute("""
                SELECT
                    d.id, d.codigo, d.estado, d.prioridad,
                    d.propiedad_id,
                    d.valor_comision, d.precio_negociado,
                    d.fecha_creacion, d.fecha_actualizacion,
                    d.agente_vendedor_telefono,
                    p.titulo as propiedad_titulo,
                    p.precio as propiedad_precio,
                    p.imagen_principal as propiedad_imagen,
                    p.zona as propiedad_zona,
                    p.ciudad as propiedad_ciudad,
                    p.tipo_propiedad,
                    c.nombre as contacto_nombre,
                    c.telefono as contacto_telefono,
                    av.nombre as agente_vendedor_nombre,
                    EXTRACT(DAY FROM NOW() - d.fecha_actualizacion)::INTEGER as dias_en_estado
                FROM deals d
                JOIN propiedades p ON p.id = d.propiedad_id
                JOIN contactos c ON c.id = d.contacto_id
                LEFT JOIN agentes av ON av.telefono = d.agente_vendedor_telefono
                WHERE d.estado = %s
                ORDER BY d.prioridad DESC, d.fecha_actualizacion DESC
            """, (estado,))

            deals = [dict(row) for row in db.cursor.fetchall()]

            for deal in deals:
                for key, value in deal.items():
                    if hasattr(value, 'isoformat'):
                        deal[key] = value.isoformat()

            pipeline[estado] = {
                'deals': deals,
                'count': len(deals),
                'valor_total': sum(d.get('valor_comision') or 0 for d in deals)
            }

        return jsonify({
            'success': True,
            'data': pipeline
        }), 200

    except Exception as e:
        print(f"❌ Error en get_pipeline: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@deals_bp.route('/stats', methods=['GET'])
def get_stats():
    """
    GET /api/deals/stats

    Obtiene estadísticas del pipeline
    """
    db = None
    try:
        db = get_db()

        # Stats generales
        db.cursor.execute("""
            SELECT
                COUNT(*) as total_deals,
                COUNT(*) FILTER (WHERE estado NOT IN ('ganado', 'perdido')) as deals_activos,
                COUNT(*) FILTER (WHERE estado = 'ganado') as deals_ganados,
                COUNT(*) FILTER (WHERE estado = 'perdido') as deals_perdidos,
                SUM(valor_comision) FILTER (WHERE estado NOT IN ('ganado', 'perdido')) as comision_potencial,
                SUM(valor_comision) FILTER (WHERE estado = 'ganado') as comision_ganada,
                SUM(valor_comision) FILTER (WHERE estado = 'ganado' AND comision_pagada = true) as comision_cobrada
            FROM deals
        """)

        stats = dict(db.cursor.fetchone())

        # Stats por estado
        db.cursor.execute("""
            SELECT estado, COUNT(*) as total, SUM(valor_comision) as valor
            FROM deals
            GROUP BY estado
        """)

        por_estado = {row['estado']: {'total': row['total'], 'valor': float(row['valor'] or 0)}
                      for row in db.cursor.fetchall()}

        stats['por_estado'] = por_estado

        # Conversión de tipos
        for key in ['comision_potencial', 'comision_ganada', 'comision_cobrada']:
            if stats.get(key):
                stats[key] = float(stats[key])
            else:
                stats[key] = 0

        return jsonify({
            'success': True,
            'data': stats
        }), 200

    except Exception as e:
        print(f"❌ Error en get_stats: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@deals_bp.route('/<int:deal_id>', methods=['GET'])
def get_deal(deal_id: int):
    """
    GET /api/deals/:id

    Obtiene un deal específico con todo su historial
    """
    db = None
    try:
        db = get_db()

        # Deal principal
        db.cursor.execute("""
            SELECT
                d.*,
                p.titulo as propiedad_titulo,
                p.precio as propiedad_precio,
                p.tipo_propiedad,
                p.ciudad as propiedad_ciudad,
                p.zona as propiedad_zona,
                p.imagen_principal as propiedad_imagen,
                p.imagenes_urls as propiedad_imagenes,
                p.fuente as propiedad_fuente,
                p.habitaciones, p.banos, p.area_construida,
                p.descripcion as propiedad_descripcion,
                c.nombre as contacto_nombre,
                c.telefono as contacto_telefono,
                c.email as contacto_email,
                c.notas as contacto_notas,
                av.nombre as agente_vendedor_nombre,
                ac.nombre as agente_comprador_nombre
            FROM deals d
            JOIN propiedades p ON p.id = d.propiedad_id
            JOIN contactos c ON c.id = d.contacto_id
            LEFT JOIN agentes av ON av.telefono = d.agente_vendedor_telefono
            LEFT JOIN agentes ac ON ac.telefono = d.agente_comprador_telefono
            WHERE d.id = %s
        """, (deal_id,))

        deal = db.cursor.fetchone()

        if not deal:
            return jsonify({'success': False, 'error': 'Deal no encontrado'}), 404

        deal = dict(deal)

        # Historial de actividades
        db.cursor.execute("""
            SELECT * FROM deal_actividades
            WHERE deal_id = %s
            ORDER BY fecha DESC
        """, (deal_id,))

        actividades = [dict(row) for row in db.cursor.fetchall()]

        # Documentos
        db.cursor.execute("""
            SELECT * FROM deal_documentos
            WHERE deal_id = %s
            ORDER BY fecha_subida DESC
        """, (deal_id,))

        documentos = [dict(row) for row in db.cursor.fetchall()]

        # Propiedades asociadas (multi-propiedad) con captador
        db.cursor.execute("""
            SELECT
                dp.id, dp.propiedad_id, dp.estado as estado_en_deal,
                dp.notas as notas_propiedad, dp.fecha_agregado,
                p.titulo, p.precio, p.imagen_principal as imagen,
                p.codigo_propiedad as slug, p.ciudad, p.zona,
                p.tipo_propiedad, p.habitaciones, p.area_construida,
                p.agente_captador_telefono as captador_telefono,
                ag.nombre as captador_nombre
            FROM deal_propiedades dp
            JOIN propiedades p ON p.id = dp.propiedad_id
            LEFT JOIN agentes ag ON ag.telefono = p.agente_captador_telefono
            WHERE dp.deal_id = %s
            ORDER BY dp.fecha_agregado ASC
        """, (deal_id,))
        propiedades_asociadas = [dict(row) for row in db.cursor.fetchall()]

        # Convertir fechas
        for item in [deal] + actividades + documentos + propiedades_asociadas:
            for key, value in item.items():
                if hasattr(value, 'isoformat'):
                    item[key] = value.isoformat()

        deal['actividades'] = actividades
        deal['documentos'] = documentos
        deal['propiedades'] = propiedades_asociadas

        return jsonify({
            'success': True,
            'data': deal
        }), 200

    except Exception as e:
        print(f"❌ Error en get_deal: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@deals_bp.route('', methods=['POST'])
def create_deal():
    """
    POST /api/deals

    Crea un nuevo deal (juntar puntas manual)

    Body:
    {
        "propiedad_id": 123,
        "contacto": {
            "nombre": "Juan Pérez",
            "telefono": "+573001234567",
            "email": "juan@email.com"
        },
        "notas": "Interesado en comprar",
        "origen": "manual",
        "creado_por": "user@email.com"
    }
    """
    db = None
    try:
        db = get_db()
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        propiedad_id = data.get('propiedad_id')
        contacto_data = data.get('contacto', {})

        if not propiedad_id:
            return jsonify({'success': False, 'error': 'propiedad_id es requerido'}), 400

        if not contacto_data.get('nombre') or not contacto_data.get('telefono'):
            return jsonify({'success': False, 'error': 'Nombre y teléfono del contacto son requeridos'}), 400

        # Verificar que la propiedad existe
        db.cursor.execute("SELECT id, agente_captador_telefono, precio, titulo FROM propiedades WHERE id = %s", (propiedad_id,))
        propiedad = db.cursor.fetchone()

        if not propiedad:
            return jsonify({'success': False, 'error': 'Propiedad no encontrada'}), 404

        # Crear o actualizar contacto
        db.cursor.execute("""
            INSERT INTO contactos (nombre, telefono, email, origen, notas)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (telefono) DO UPDATE SET
                nombre = EXCLUDED.nombre,
                email = COALESCE(EXCLUDED.email, contactos.email),
                fecha_actualizacion = CURRENT_TIMESTAMP
            RETURNING id
        """, (
            contacto_data['nombre'],
            contacto_data['telefono'],
            contacto_data.get('email'),
            data.get('origen', 'manual'),
            contacto_data.get('notas')
        ))

        contacto_id = db.cursor.fetchone()['id']

        # Verificar si ya existe un deal para esta propiedad y contacto
        db.cursor.execute("""
            SELECT id, codigo FROM deals
            WHERE propiedad_id = %s AND contacto_id = %s
            AND estado NOT IN ('ganado', 'perdido')
        """, (propiedad_id, contacto_id))

        existing = db.cursor.fetchone()
        if existing:
            return jsonify({
                'success': False,
                'error': f'Ya existe un deal activo para esta propiedad y contacto: {existing["codigo"]}'
            }), 409

        # Tipo de negocio y comision
        tipo_negocio = data.get('tipo_negocio', 'tercero')  # tercero, cliente, propiedad
        if tipo_negocio in ('cliente', 'propiedad'):
            porcentaje = 1.50
            tipo_com = 'captacion'
        else:
            porcentaje = 0.50
            tipo_com = 'matching'

        precio_prop = propiedad.get('precio') or 0
        valor_com = float(precio_prop) * (porcentaje / 100) if precio_prop else 0

        # Crear deal
        db.cursor.execute("""
            INSERT INTO deals (
                propiedad_id, contacto_id,
                agente_vendedor_telefono,
                origen, notas, creado_por,
                tipo_comision, porcentaje_comision, valor_comision,
                codigo
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '')
            RETURNING id, codigo
        """, (
            propiedad_id,
            contacto_id,
            propiedad['agente_captador_telefono'],
            data.get('origen', 'manual'),
            data.get('notas'),
            data.get('creado_por'),
            tipo_com,
            porcentaje,
            valor_com,
        ))

        result = db.cursor.fetchone()
        deal_id = result['id']

        # Actualizar código (trigger lo genera pero necesitamos el id)
        db.cursor.execute("""
            UPDATE deals SET codigo = 'DEAL-' || TO_CHAR(NOW(), 'YYMM') || '-' || LPAD(%s::TEXT, 4, '0')
            WHERE id = %s
            RETURNING codigo
        """, (deal_id, deal_id))

        codigo = db.cursor.fetchone()['codigo']

        # Poner estado inicial en contactado
        db.cursor.execute("""
            UPDATE deals SET estado = 'contactado', fecha_contactado = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (deal_id,))

        # Insertar propiedad principal en deal_propiedades
        db.cursor.execute("""
            INSERT INTO deal_propiedades (deal_id, propiedad_id, estado)
            VALUES (%s, %s, 'interesado')
            ON CONFLICT (deal_id, propiedad_id) DO NOTHING
        """, (deal_id, propiedad_id))

        # Registrar actividad
        db.cursor.execute("""
            INSERT INTO deal_actividades (deal_id, tipo, descripcion, estado_nuevo, usuario)
            VALUES (%s, 'estado_cambio', 'Deal creado', 'contactado', %s)
        """, (deal_id, data.get('creado_por')))

        db.conn.commit()

        # Notificacion por correo
        try:
            print(f"[EMAIL] Intentando enviar notificacion para deal {codigo}...")
            from src.notifications.email import send_deal_created_email
            send_deal_created_email(
                deal_code=codigo,
                contact_name=contacto_data.get('nombre', ''),
                contact_phone=contacto_data.get('telefono', ''),
                property_title=str(propiedad.get('titulo', '') or ''),
                property_price=float(propiedad.get('precio', 0) or 0),
            )
        except Exception as email_err:
            import traceback
            print(f"[EMAIL ERROR] create_deal notification: {email_err}")
            traceback.print_exc()

        return jsonify({
            'success': True,
            'data': {
                'id': deal_id,
                'codigo': codigo
            },
            'message': f'Deal {codigo} creado exitosamente'
        }), 201

    except Exception as e:
        print(f"❌ Error en create_deal: {e}")
        traceback.print_exc()
        if db:
            db.conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@deals_bp.route('/<int:deal_id>/estado', methods=['PUT'])
def update_deal_state(deal_id: int):
    """
    PUT /api/deals/:id/estado

    Actualiza el estado de un deal (mover en el pipeline)

    Body:
    {
        "estado": "contactado",
        "notas": "Se contactó por teléfono",
        "usuario": "user@email.com",
        "precio_venta": 500000000,  // Solo para estado "ganado"
        "porcentaje_comision": 0.5  // Solo para estado "ganado"
    }
    """
    db = None
    try:
        db = get_db()
        data = request.get_json()

        nuevo_estado = data.get('estado')

        if nuevo_estado not in DEAL_STATES:
            return jsonify({
                'success': False,
                'error': f'Estado inválido. Válidos: {", ".join(DEAL_STATES)}'
            }), 400

        # Obtener estado actual
        db.cursor.execute("SELECT estado FROM deals WHERE id = %s", (deal_id,))
        current = db.cursor.fetchone()

        if not current:
            return jsonify({'success': False, 'error': 'Deal no encontrado'}), 404

        estado_anterior = current['estado']

        # Actualizar estado y fecha correspondiente
        date_field = STATE_DATE_FIELDS.get(nuevo_estado, 'fecha_actualizacion')

        update_query = f"""
            UPDATE deals
            SET estado = %s, {date_field} = CURRENT_TIMESTAMP
        """
        params = [nuevo_estado]

        # Si es perdido, guardar motivo
        if nuevo_estado == 'perdido' and data.get('motivo_perdida'):
            update_query += ", motivo_perdida = %s"
            params.append(data['motivo_perdida'])

        # Si es ganado, guardar precio y comisión
        if nuevo_estado == 'ganado':
            precio_venta = data.get('precio_venta')
            porcentaje_comision = data.get('porcentaje_comision')

            if precio_venta:
                update_query += ", precio_negociado = %s"
                params.append(precio_venta)

            if porcentaje_comision:
                update_query += ", porcentaje_comision = %s"
                params.append(porcentaje_comision)

                # Calcular valor de comisión
                if precio_venta:
                    valor_comision = float(precio_venta) * (float(porcentaje_comision) / 100)
                    update_query += ", valor_comision = %s"
                    params.append(valor_comision)

        update_query += " WHERE id = %s RETURNING codigo"
        params.append(deal_id)

        db.cursor.execute(update_query, params)
        result = db.cursor.fetchone()

        # Registrar actividad
        descripcion = f"Estado cambiado de '{estado_anterior}' a '{nuevo_estado}'"
        if data.get('notas'):
            descripcion += f". {data['notas']}"

        # Para ganados, agregar info de la venta
        if nuevo_estado == 'ganado' and data.get('precio_venta'):
            precio_venta = data.get('precio_venta')
            porcentaje = data.get('porcentaje_comision', 0)
            comision = float(precio_venta) * (float(porcentaje) / 100)
            descripcion += f" | Venta: ${precio_venta:,.0f} | Comisión {porcentaje}%: ${comision:,.0f}"

        db.cursor.execute("""
            INSERT INTO deal_actividades (
                deal_id, tipo, descripcion,
                estado_anterior, estado_nuevo, usuario
            ) VALUES (%s, 'estado_cambio', %s, %s, %s, %s)
        """, (deal_id, descripcion, estado_anterior, nuevo_estado, data.get('usuario')))

        db.conn.commit()

        # Notificacion por correo
        try:
            from src.notifications.email import send_deal_stage_changed_email, send_deal_won_email, send_deal_lost_email
            # Fetch deal info for email
            db.cursor.execute("""
                SELECT c.nombre as contacto_nombre, p.titulo as propiedad_titulo
                FROM deals d
                JOIN contactos c ON c.id = d.contacto_id
                JOIN propiedades p ON p.id = d.propiedad_id
                WHERE d.id = %s
            """, (deal_id,))
            deal_info = db.cursor.fetchone()
            c_name = deal_info['contacto_nombre'] if deal_info else ''
            p_title = deal_info['propiedad_titulo'] if deal_info else ''

            if nuevo_estado == 'ganado':
                send_deal_won_email(
                    deal_code=result['codigo'],
                    contact_name=c_name,
                    property_title=p_title,
                    sale_price=float(data.get('precio_venta', 0) or 0),
                    commission=float(data.get('precio_venta', 0) or 0) * float(data.get('porcentaje_comision', 0) or 0) / 100,
                    commission_pct=float(data.get('porcentaje_comision', 0) or 0),
                )
            elif nuevo_estado == 'perdido':
                send_deal_lost_email(
                    deal_code=result['codigo'],
                    contact_name=c_name,
                    property_title=p_title,
                    reason=data.get('motivo_perdida', ''),
                )
            else:
                send_deal_stage_changed_email(
                    deal_code=result['codigo'],
                    contact_name=c_name,
                    previous_stage=estado_anterior,
                    new_stage=nuevo_estado,
                    property_title=p_title,
                )
        except Exception as email_err:
            print(f"[EMAIL ERROR] update_deal_state notification: {email_err}")

        return jsonify({
            'success': True,
            'data': {
                'codigo': result['codigo'],
                'estado_anterior': estado_anterior,
                'estado_nuevo': nuevo_estado
            }
        }), 200

    except Exception as e:
        print(f"❌ Error en update_deal_state: {e}")
        traceback.print_exc()
        if db:
            db.conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@deals_bp.route('/<int:deal_id>/actividad', methods=['POST'])
def add_activity(deal_id: int):
    """
    POST /api/deals/:id/actividad

    Agrega una actividad/nota al deal

    Body:
    {
        "tipo": "nota",  // nota, llamada, mensaje, visita
        "descripcion": "Se llamó al cliente",
        "usuario": "user@email.com"
    }
    """
    db = None
    try:
        db = get_db()
        data = request.get_json()

        db.cursor.execute("""
            INSERT INTO deal_actividades (deal_id, tipo, descripcion, usuario, metadata)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (
            deal_id,
            data.get('tipo', 'nota'),
            data.get('descripcion'),
            data.get('usuario'),
            data.get('metadata')
        ))

        actividad_id = db.cursor.fetchone()['id']
        db.conn.commit()

        return jsonify({
            'success': True,
            'data': {'id': actividad_id}
        }), 201

    except Exception as e:
        print(f"❌ Error en add_activity: {e}")
        if db:
            db.conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@deals_bp.route('/contactos', methods=['GET'])
def get_contactos():
    """
    GET /api/deals/contactos

    Obtiene lista de contactos
    """
    db = None
    try:
        db = get_db()

        search = request.args.get('search', '')
        limit = int(request.args.get('limit', 50))

        query = """
            SELECT c.*,
                   COUNT(d.id) as total_deals,
                   COUNT(d.id) FILTER (WHERE d.estado = 'ganado') as deals_ganados
            FROM contactos c
            LEFT JOIN deals d ON d.contacto_id = c.id
            WHERE c.activo = true
        """
        params = []

        if search:
            query += " AND (c.nombre ILIKE %s OR c.telefono ILIKE %s OR c.email ILIKE %s)"
            search_param = f'%{search}%'
            params.extend([search_param, search_param, search_param])

        query += " GROUP BY c.id ORDER BY c.fecha_creacion DESC LIMIT %s"
        params.append(limit)

        db.cursor.execute(query, params)
        contactos = [dict(row) for row in db.cursor.fetchall()]

        for c in contactos:
            for key, value in c.items():
                if hasattr(value, 'isoformat'):
                    c[key] = value.isoformat()

        return jsonify({
            'success': True,
            'data': contactos
        }), 200

    except Exception as e:
        print(f"❌ Error en get_contactos: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


# ============================================================================
# ELIMINAR DEAL
# ============================================================================

@deals_bp.route('/<int:deal_id>', methods=['DELETE'])
def delete_deal(deal_id: int):
    """Elimina un deal permanentemente"""
    db = None
    try:
        db = get_db()

        db.cursor.execute("SELECT id, codigo FROM deals WHERE id = %s", (deal_id,))
        deal = db.cursor.fetchone()
        if not deal:
            return jsonify({'success': False, 'error': 'Deal no encontrado'}), 404

        # CASCADE borra deal_actividades, deal_propiedades, deal_documentos
        db.cursor.execute("DELETE FROM deals WHERE id = %s", (deal_id,))
        db.conn.commit()

        return jsonify({'success': True, 'data': {'codigo': deal['codigo']}}), 200

    except Exception as e:
        if db: db.conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db: db.disconnect()


# ============================================================================
# MULTI-PROPIEDAD: Gestión de propiedades por deal
# ============================================================================

@deals_bp.route('/<int:deal_id>/propiedades', methods=['POST'])
def add_deal_property(deal_id: int):
    """Agrega una propiedad a un deal"""
    db = None
    try:
        db = get_db()
        data = request.json
        propiedad_id = data.get('propiedad_id')

        if not propiedad_id:
            return jsonify({'success': False, 'error': 'propiedad_id requerido'}), 400

        db.cursor.execute("""
            INSERT INTO deal_propiedades (deal_id, propiedad_id, estado)
            VALUES (%s, %s, 'interesado')
            ON CONFLICT (deal_id, propiedad_id) DO NOTHING
            RETURNING id
        """, (deal_id, propiedad_id))

        result = db.cursor.fetchone()
        if not result:
            return jsonify({'success': False, 'error': 'La propiedad ya está asociada a este deal'}), 409

        # Registrar actividad
        db.cursor.execute("""
            SELECT titulo FROM propiedades WHERE id = %s
        """, (propiedad_id,))
        prop = db.cursor.fetchone()
        prop_name = prop['titulo'] if prop else f'ID {propiedad_id}'

        db.cursor.execute("""
            INSERT INTO deal_actividades (deal_id, tipo, descripcion)
            VALUES (%s, 'nota', %s)
        """, (deal_id, f'Propiedad agregada: {prop_name}'))

        db.conn.commit()

        return jsonify({'success': True, 'data': {'id': result['id']}}), 201

    except Exception as e:
        if db: db.conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db: db.disconnect()


@deals_bp.route('/<int:deal_id>/propiedades/<int:propiedad_id>', methods=['PUT'])
def update_deal_property(deal_id: int, propiedad_id: int):
    """Actualiza el estado de una propiedad dentro de un deal"""
    db = None
    try:
        db = get_db()
        data = request.json
        estado = data.get('estado', 'interesado')
        notas = data.get('notas')

        db.cursor.execute("""
            UPDATE deal_propiedades
            SET estado = %s, notas = %s
            WHERE deal_id = %s AND propiedad_id = %s
            RETURNING id
        """, (estado, notas, deal_id, propiedad_id))

        result = db.cursor.fetchone()
        if not result:
            return jsonify({'success': False, 'error': 'Propiedad no encontrada en este deal'}), 404

        # Registrar actividad
        db.cursor.execute("""
            SELECT titulo FROM propiedades WHERE id = %s
        """, (propiedad_id,))
        prop = db.cursor.fetchone()
        prop_name = prop['titulo'] if prop else f'ID {propiedad_id}'
        estado_labels = {'interesado': 'Interesado', 'descartado': 'Descartada', 'seleccionado': 'Seleccionada'}

        db.cursor.execute("""
            INSERT INTO deal_actividades (deal_id, tipo, descripcion)
            VALUES (%s, 'nota', %s)
        """, (deal_id, f'Propiedad {estado_labels.get(estado, estado)}: {prop_name}'))

        db.conn.commit()

        return jsonify({'success': True}), 200

    except Exception as e:
        if db: db.conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db: db.disconnect()


@deals_bp.route('/<int:deal_id>/propiedades/<int:propiedad_id>', methods=['DELETE'])
def remove_deal_property(deal_id: int, propiedad_id: int):
    """Quita una propiedad de un deal"""
    db = None
    try:
        db = get_db()

        db.cursor.execute("""
            DELETE FROM deal_propiedades
            WHERE deal_id = %s AND propiedad_id = %s
            RETURNING id
        """, (deal_id, propiedad_id))

        result = db.cursor.fetchone()
        if not result:
            return jsonify({'success': False, 'error': 'Propiedad no encontrada en este deal'}), 404

        db.conn.commit()

        return jsonify({'success': True}), 200

    except Exception as e:
        if db: db.conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db: db.disconnect()


# Función helper para crear deal desde WhatsApp (usada por cupido_manager)
def create_deal_from_whatsapp(
    propiedad_id: int,
    contacto_telefono: str,
    contacto_nombre: str,
    mensaje_origen: str,
    agente_comprador_telefono: str = None
) -> Optional[Dict]:
    """
    Crea un deal automáticamente desde una solicitud de WhatsApp

    Args:
        propiedad_id: ID de la propiedad solicitada
        contacto_telefono: Teléfono del interesado
        contacto_nombre: Nombre del interesado
        mensaje_origen: Mensaje original de WhatsApp
        agente_comprador_telefono: Teléfono del agente que trae al comprador

    Returns:
        Dict con info del deal creado o None si falla
    """
    db = None
    try:
        db = DatabaseManager()
        db.connect()

        # Obtener agente vendedor de la propiedad
        db.cursor.execute(
            "SELECT agente_captador_telefono FROM propiedades WHERE id = %s",
            (propiedad_id,)
        )
        propiedad = db.cursor.fetchone()

        if not propiedad:
            return None

        # Crear o actualizar contacto
        db.cursor.execute("""
            INSERT INTO contactos (nombre, telefono, origen)
            VALUES (%s, %s, 'whatsapp')
            ON CONFLICT (telefono) DO UPDATE SET
                nombre = COALESCE(EXCLUDED.nombre, contactos.nombre),
                fecha_actualizacion = CURRENT_TIMESTAMP
            RETURNING id
        """, (contacto_nombre, contacto_telefono))

        contacto_id = db.cursor.fetchone()['id']

        # Verificar si ya existe deal
        db.cursor.execute("""
            SELECT id, codigo FROM deals
            WHERE propiedad_id = %s AND contacto_id = %s
            AND estado NOT IN ('ganado', 'perdido')
        """, (propiedad_id, contacto_id))

        existing = db.cursor.fetchone()
        if existing:
            print(f"ℹ️  Ya existe deal {existing['codigo']} para esta propiedad y contacto")
            return {'id': existing['id'], 'codigo': existing['codigo'], 'existente': True}

        # Crear deal
        db.cursor.execute("""
            INSERT INTO deals (
                propiedad_id, contacto_id,
                agente_vendedor_telefono, agente_comprador_telefono,
                origen, mensaje_origen, codigo
            ) VALUES (%s, %s, %s, %s, 'whatsapp_auto', %s, '')
            RETURNING id
        """, (
            propiedad_id,
            contacto_id,
            propiedad['agente_captador_telefono'],
            agente_comprador_telefono,
            mensaje_origen[:500] if mensaje_origen else None
        ))

        deal_id = db.cursor.fetchone()['id']

        # Generar código
        db.cursor.execute("""
            UPDATE deals SET codigo = 'DEAL-' || TO_CHAR(NOW(), 'YYMM') || '-' || LPAD(%s::TEXT, 4, '0')
            WHERE id = %s
            RETURNING codigo
        """, (deal_id, deal_id))

        codigo = db.cursor.fetchone()['codigo']

        # Registrar actividad
        db.cursor.execute("""
            INSERT INTO deal_actividades (deal_id, tipo, descripcion, estado_nuevo)
            VALUES (%s, 'estado_cambio', 'Deal creado automáticamente desde WhatsApp', 'lead')
        """, (deal_id,))

        db.conn.commit()

        # Notificacion por correo
        try:
            from src.notifications.email import send_deal_created_email
            db.cursor.execute("SELECT titulo, precio FROM propiedades WHERE id = %s", (propiedad_id,))
            prop_row = db.cursor.fetchone()
            send_deal_created_email(
                deal_code=codigo,
                contact_name=contacto_nombre,
                contact_phone=contacto_telefono,
                property_title=prop_row['titulo'] if prop_row else '',
                property_price=prop_row['precio'] if prop_row else 0,
            )
        except Exception as email_err:
            print(f"[EMAIL ERROR] whatsapp deal notification: {email_err}")

        print(f"✅ Deal {codigo} creado automáticamente")
        return {'id': deal_id, 'codigo': codigo, 'existente': False}

    except Exception as e:
        print(f"❌ Error creando deal desde WhatsApp: {e}")
        if db:
            db.conn.rollback()
        return None
    finally:
        if db:
            db.disconnect()
