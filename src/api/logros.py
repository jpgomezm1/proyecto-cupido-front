"""
API de misiones, rachas y onboarding (agente autenticado).

    GET  /api/chat/logros                    → racha, semana, misiones, premios del mes, logros por celebrar
    POST /api/chat/logros/vistos {ids}       → marca logros como celebrados
    POST /api/chat/logros/evento {evento}    → insignias que dispara la web ('mapa')
    POST /api/chat/onboarding/completar      → el agente terminó (o saltó) el onboarding

La lógica vive en `logros_service.py`.
"""

import traceback

from flask import Blueprint, jsonify, request

from src.api.chat_auth import require_chat_auth
from src.services import logros_service as svc

logros_bp = Blueprint('logros', __name__, url_prefix='/api/chat')


def _ok(data):
    return jsonify({"success": True, "data": data})


def _manejar(fn, contexto: str):
    try:
        return fn()
    except svc.LogrosError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        print(f"❌ Error en logros/{contexto}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


def _uid() -> int:
    return request.chat_user['id']


def _json() -> dict:
    return request.get_json(silent=True) or {}


@logros_bp.route('/logros', methods=['GET'])
@require_chat_auth
def resumen():
    return _manejar(lambda: _ok(svc.resumen(_uid())), 'resumen')


@logros_bp.route('/logros/vistos', methods=['POST'])
@require_chat_auth
def vistos():
    ids = _json().get("ids") or []
    if not isinstance(ids, list):
        return jsonify({"success": False, "error": "ids debe ser una lista"}), 400
    return _manejar(lambda: _ok({"marcados": svc.marcar_vistos(_uid(), ids)}), 'vistos')


@logros_bp.route('/logros/evento', methods=['POST'])
@require_chat_auth
def evento():
    return _manejar(lambda: _ok({"nuevos": svc.registrar_evento(_uid(), str(_json().get("evento") or ""))}), 'evento')


@logros_bp.route('/onboarding/completar', methods=['POST'])
@require_chat_auth
def completar_onboarding():
    def f():
        svc.completar_onboarding(_uid())
        return _ok({"ok": True})
    return _manejar(f, 'onboarding')
