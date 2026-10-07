"""
API de la cuenta del agente.

    POST /api/chat/soporte {categoria, asunto, mensaje}        → caso de soporte (correo al equipo y al agente)
    POST /api/chat/cuenta/eliminar {clave, confirmacion, motivo?} → cierra la cuenta y borra datos personales

La lógica vive en `src/services/cuenta_service.py`.
"""

import traceback

from flask import Blueprint, jsonify, request

from src.api.chat_auth import require_chat_auth
from src.services import cuenta_service as svc

cuenta_bp = Blueprint('cuenta', __name__, url_prefix='/api/chat')

_STATUS = {"invalido": 400, "clave": 403, "limite": 429, "no_encontrado": 404}


def _error(e: svc.CuentaError):
    return jsonify({"success": False, "code": e.codigo, "campo": e.campo, "error": e.mensaje}), \
        _STATUS.get(e.codigo, 400)


@cuenta_bp.route('/soporte', methods=['POST'])
@require_chat_auth
def soporte():
    d = request.get_json(silent=True) or {}
    try:
        return jsonify({"success": True, "data": svc.crear_soporte(
            request.chat_user['id'], d.get('categoria'), d.get('asunto'), d.get('mensaje'))}), 201
    except svc.CuentaError as e:
        return _error(e)
    except Exception as e:
        print(f"❌ Error en soporte: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


@cuenta_bp.route('/cuenta/eliminar', methods=['POST'])
@require_chat_auth
def eliminar():
    d = request.get_json(silent=True) or {}
    try:
        return jsonify({"success": True, "data": svc.eliminar(
            request.chat_user['id'], d.get('clave'), d.get('confirmacion'), d.get('motivo'))})
    except svc.CuentaError as e:
        return _error(e)
    except Exception as e:
        print(f"❌ Error cerrando cuenta: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500
