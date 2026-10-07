"""
API de pagos en línea de los planes (Wompi).

- Chat (`require_chat_auth`):
    POST /api/chat/pagos {plan}            → crea el pago y devuelve el link al checkout
    GET  /api/chat/pagos/<ref>?id=<tx>     → estado del pago (consulta a Wompi si sigue pendiente)
    GET  /api/chat/pagos                   → historial de pagos del agente
- Wompi:
    POST /api/pagos/wompi/eventos          → webhook `transaction.updated` (checksum verificado)

La lógica vive en `src/services/pagos_service.py`.
"""

import os
import traceback

from flask import Blueprint, jsonify, request

from src.api.chat_auth import require_chat_auth
from src.services import pagos_service as svc

pagos_bp = Blueprint('pagos', __name__, url_prefix='/api')

_STATUS = {"no_disponible": 503, "invalido": 400, "no_encontrado": 404}


def _frontend_de_la_peticion():
    """Origen al que Wompi devuelve al agente: el de la web que pidió el pago
    (producción o localhost en desarrollo); nunca uno arbitrario."""
    origen = (request.headers.get('Origin') or '').rstrip('/')
    publico = os.getenv("FYNDER_FRONTEND_URL", "").rstrip('/')
    permitidos = {publico, publico.replace("://", "://www."), "https://fyndercol.netlify.app"}
    if origen in permitidos or origen.startswith(("http://localhost:", "http://127.0.0.1:")):
        return origen
    return None


def _error(e: svc.PagoError):
    return jsonify({"success": False, "code": e.codigo, "error": e.mensaje}), _STATUS.get(e.codigo, 400)


@pagos_bp.route('/chat/pagos', methods=['POST'])
@require_chat_auth
def crear():
    plan = ((request.get_json(silent=True) or {}).get('plan') or '').strip().lower()
    try:
        data = svc.crear_pago(request.chat_user['id'], plan, _frontend_de_la_peticion())
        return jsonify({"success": True, "data": data})
    except svc.PagoError as e:
        return _error(e)
    except Exception as e:
        print(f"❌ Error creando pago: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


@pagos_bp.route('/chat/pagos/<referencia>', methods=['GET'])
@require_chat_auth
def estado(referencia: str):
    try:
        data = svc.verificar(request.chat_user['id'], referencia, request.args.get('id'))
        return jsonify({"success": True, "data": data})
    except svc.PagoError as e:
        return _error(e)
    except Exception as e:
        print(f"❌ Error verificando pago {referencia}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


@pagos_bp.route('/chat/pagos', methods=['GET'])
@require_chat_auth
def historial():
    try:
        return jsonify({"success": True, "data": {"pagos": svc.historial(request.chat_user['id'])}})
    except Exception as e:
        print(f"❌ Error en historial de pagos: {e}")
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


@pagos_bp.route('/pagos/wompi/eventos', methods=['POST'])
def evento_wompi():
    evento = request.get_json(silent=True) or {}
    try:
        res = svc.procesar_evento(evento, request.headers.get('X-Event-Checksum'))
    except Exception as e:
        # 500 → Wompi reintenta (30 min, 3 h, 24 h).
        print(f"❌ Error procesando evento de Wompi: {e}")
        traceback.print_exc()
        return jsonify({"ok": False}), 500
    if res.get("error") == "firma_invalida":
        print("⚠️ Evento de Wompi con firma inválida")
        return jsonify({"ok": False}), 401
    return jsonify({"ok": True}), 200
