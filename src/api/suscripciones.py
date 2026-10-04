"""
API de suscripciones y desbloqueo de contactos.

- Chat (usuario agente, `require_chat_auth`), prefijo /api/chat:
    GET  /plan                          → estado del plan y saldo
    POST /desbloquear {tipo, ref, confirmar}
    GET  /desbloqueos                   → contactos ya desbloqueados
    POST /desbloqueos/<id>/reportar {motivo, detalle}
    POST /terminos/aceptar {version?}
    GET  /mis-propiedades/resumen       → cuántos inmuebles propios (teléfono verificado)
    GET  /mcp-estado                    → ¿conectó su IA? y último uso

- Admin (`token_required`), prefijo /api/admin/suscripciones:
    GET  /planes · PUT /planes/<codigo>
    GET  /?filtro=&q= · GET /usuarios/<id>
    POST /usuarios/<id>/activar · /usuarios/<id>/creditos · /usuarios/<id>/verificar-telefono
    POST /<sus_id>/cancelar
    GET  /reportes · POST /reportes/<id>/resolver

La lógica vive en `src/services/suscripcion_service.py`.
"""

import traceback

from flask import Blueprint, g, jsonify, request

from src.api.auth import token_required
from src.api.chat_auth import require_chat_auth
from src.services import suscripcion_service as svc

suscripciones_chat_bp = Blueprint('suscripciones_chat', __name__, url_prefix='/api/chat')
suscripciones_admin_bp = Blueprint('suscripciones_admin', __name__,
                                   url_prefix='/api/admin/suscripciones')

# Códigos de negocio que tienen un status HTTP propio.
_STATUS = {"sin_creditos": 402, "terminos_pendientes": 409, "no_encontrado": 404}


def _ok(data, status=200):
    return jsonify({"success": True, "data": data}), status


def _desde_servicio(res: dict):
    """Traduce la respuesta del servicio ({ok, error, mensaje, ...}) a HTTP."""
    if res.get("ok") is False or res.get("error"):
        return jsonify({"success": False, "code": res.get("error"),
                        "error": res.get("mensaje") or res.get("error"), "data": res}), \
            _STATUS.get(res.get("error"), 200)
    return _ok(res)


def _fallo(e: Exception, contexto: str):
    print(f"❌ Error en {contexto}: {e}")
    traceback.print_exc()
    return jsonify({"success": False, "error": "Error en el servidor"}), 500


# =========================================================================
# Chat
# =========================================================================

@suscripciones_chat_bp.route('/plan', methods=['GET'])
@require_chat_auth
def mi_plan():
    try:
        return _desde_servicio(svc.estado(request.chat_user['id']))
    except Exception as e:
        return _fallo(e, 'mi_plan')


@suscripciones_chat_bp.route('/desbloquear', methods=['POST'])
@require_chat_auth
def desbloquear():
    data = request.get_json(silent=True) or {}
    tipo = data.get('tipo', 'propiedad')
    ref = data.get('ref')
    if ref in (None, ''):
        return jsonify({"success": False, "error": "ref requerido"}), 400
    try:
        user_id = request.chat_user['id']
        if not data.get('confirmar'):
            return _desde_servicio(svc.preview_desbloqueo(user_id, tipo, ref))
        return _desde_servicio(svc.desbloquear(user_id, tipo, ref, canal='web'))
    except Exception as e:
        return _fallo(e, 'desbloquear')


@suscripciones_chat_bp.route('/desbloqueos', methods=['GET'])
@require_chat_auth
def mis_desbloqueos():
    try:
        return _ok(svc.listar_desbloqueos(request.chat_user['id'],
                                          request.args.get('limit', 50, type=int),
                                          request.args.get('offset', 0, type=int)))
    except Exception as e:
        return _fallo(e, 'mis_desbloqueos')


@suscripciones_chat_bp.route('/desbloqueos/<int:desbloqueo_id>/reportar', methods=['POST'])
@require_chat_auth
def reportar(desbloqueo_id: int):
    data = request.get_json(silent=True) or {}
    try:
        return _desde_servicio(svc.reportar_invalido(
            request.chat_user['id'], desbloqueo_id, data.get('motivo', ''), data.get('detalle')))
    except Exception as e:
        return _fallo(e, 'reportar')


@suscripciones_chat_bp.route('/terminos/aceptar', methods=['POST'])
@require_chat_auth
def aceptar_terminos():
    data = request.get_json(silent=True) or {}
    try:
        return _desde_servicio(svc.aceptar_terminos(
            request.chat_user['id'], data.get('version') or svc.TERMINOS_VERSION))
    except Exception as e:
        return _fallo(e, 'aceptar_terminos')


@suscripciones_chat_bp.route('/mis-propiedades/resumen', methods=['GET'])
@require_chat_auth
def resumen_mis_propiedades():
    """Cuántos inmuebles tiene el usuario (por su teléfono verificado)."""
    from src.services.db import get_db, fetch_one
    user = request.chat_user
    tel = ''.join(ch for ch in (user.get('telefono') or '') if ch.isdigit())[-10:]
    if not user.get('telefono_verificado') or len(tel) != 10:
        return _ok({"total": 0, "activas": 0, "telefono_verificado": False})
    try:
        with get_db() as db:
            row = fetch_one(db.cursor, """
                SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE activa) AS activas
                FROM propiedades
                WHERE RIGHT(REGEXP_REPLACE(COALESCE(agente_captador_telefono,''),'[^0-9]','','g'),10) = %s
            """, (tel,))
        return _ok({"total": row["total"], "activas": row["activas"], "telefono_verificado": True})
    except Exception as e:
        return _fallo(e, 'resumen_mis_propiedades')


@suscripciones_chat_bp.route('/mcp-estado', methods=['GET'])
@require_chat_auth
def mcp_estado():
    """
    ¿El agente ya conectó su IA (Claude/ChatGPT) a Fynder? Conectado = tiene una
    sesión MCP vigente. `ultimo_uso` = última tool que usó desde su IA.
    """
    from src.services.db import get_db, fetch_one
    user_id = request.chat_user['id']
    try:
        with get_db() as db:
            sesion = fetch_one(db.cursor, """
                SELECT COUNT(*) AS n, MAX(COALESCE(ultimo_uso, fecha_creacion)) AS ultima
                FROM chat_user_sessions
                WHERE user_id = %s AND tipo = 'mcp' AND activa
                  AND (fecha_expiracion IS NULL OR fecha_expiracion > NOW())
            """, (user_id,))
            try:
                uso = fetch_one(db.cursor, """
                    SELECT MAX(created_at) AS ultimo, COUNT(*) AS llamadas_30d
                    FROM mcp_tool_calls
                    WHERE user_id = %s AND created_at > NOW() - INTERVAL '30 days'
                """, (user_id,))
            except Exception:
                db.conn.rollback()  # la tabla de uso aún no existe (migración 039)
                uso = {}
        ultimo = (uso or {}).get('ultimo') or sesion.get('ultima')
        return _ok({
            "conectado": bool(sesion and sesion['n']),
            "ultimo_uso": ultimo.isoformat() if ultimo else None,
            "llamadas_30d": int((uso or {}).get('llamadas_30d') or 0),
        })
    except Exception as e:
        return _fallo(e, 'mcp_estado')


# =========================================================================
# Admin
# =========================================================================

def _admin() -> str:
    user = getattr(g, 'current_user', None) or {}
    return user.get('email') or 'admin'


def _admin_op(fn, contexto: str):
    try:
        return _ok(fn())
    except svc.SuscripcionError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return _fallo(e, contexto)


@suscripciones_admin_bp.route('/planes', methods=['GET'])
@token_required
def admin_planes():
    return _admin_op(svc.listar_planes, 'admin_planes')


@suscripciones_admin_bp.route('/planes/<codigo>', methods=['PUT'])
@token_required
def admin_actualizar_plan(codigo: str):
    data = request.get_json(silent=True) or {}
    return _admin_op(lambda: svc.actualizar_plan(
        codigo, nombre=data.get('nombre'), precio_cop=data.get('precio_cop'),
        desbloqueos_mes=data.get('desbloqueos_mes'), activo=data.get('activo')),
        'admin_actualizar_plan')


@suscripciones_admin_bp.route('', methods=['GET'])
@token_required
def admin_listar():
    return _admin_op(lambda: svc.listar_suscripciones(
        request.args.get('filtro', 'todas'), request.args.get('q') or None), 'admin_listar')


@suscripciones_admin_bp.route('/usuarios/<int:user_id>', methods=['GET'])
@token_required
def admin_detalle(user_id: int):
    return _admin_op(lambda: svc.detalle_usuario(user_id), 'admin_detalle')


@suscripciones_admin_bp.route('/usuarios/<int:user_id>/activar', methods=['POST'])
@token_required
def admin_activar(user_id: int):
    data = request.get_json(silent=True) or {}
    return _admin_op(lambda: svc.activar_plan(
        user_id, data.get('plan_codigo', ''), data.get('referencia_pago'),
        data.get('notas'), _admin()), 'admin_activar')


@suscripciones_admin_bp.route('/usuarios/<int:user_id>/creditos', methods=['POST'])
@token_required
def admin_creditos(user_id: int):
    data = request.get_json(silent=True) or {}
    return _admin_op(lambda: svc.agregar_creditos(
        user_id, data.get('cantidad', 0), data.get('tipo', 'extra'),
        data.get('referencia'), _admin()), 'admin_creditos')


@suscripciones_admin_bp.route('/usuarios/<int:user_id>/verificar-telefono', methods=['POST'])
@token_required
def admin_verificar_telefono(user_id: int):
    data = request.get_json(silent=True) or {}
    return _admin_op(lambda: svc.verificar_telefono(user_id, bool(data.get('verificado', True))),
                     'admin_verificar_telefono')


@suscripciones_admin_bp.route('/<int:suscripcion_id>/cancelar', methods=['POST'])
@token_required
def admin_cancelar(suscripcion_id: int):
    return _admin_op(lambda: svc.cancelar_suscripcion(suscripcion_id), 'admin_cancelar')


@suscripciones_admin_bp.route('/reportes', methods=['GET'])
@token_required
def admin_reportes():
    pendientes = request.args.get('pendientes', '1') != '0'
    return _admin_op(lambda: svc.listar_reportes(pendientes), 'admin_reportes')


@suscripciones_admin_bp.route('/reportes/<int:reporte_id>/resolver', methods=['POST'])
@token_required
def admin_resolver_reporte(reporte_id: int):
    data = request.get_json(silent=True) or {}
    return _admin_op(lambda: svc.resolver_reporte(
        reporte_id, bool(data.get('reembolsar')), data.get('resolucion')), 'admin_resolver_reporte')
