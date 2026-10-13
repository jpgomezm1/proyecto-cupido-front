"""
API de misiones, rachas y onboarding (agente autenticado).

    GET  /api/chat/logros                    → racha, semana, misiones, premios del mes, logros por celebrar
    POST /api/chat/logros/vistos {ids}       → marca logros como celebrados
    POST /api/chat/logros/evento {evento}    → insignias que dispara la web ('mapa')
    POST /api/chat/onboarding/completar      → el agente terminó (o saltó) el onboarding
    GET  /api/chat/fyns                      → saldo, ganados del mes, catálogo y movimientos
    POST /api/chat/fyns/canjear {producto}   → canjea Fyns por un producto del catálogo

La lógica vive en `logros_service.py`.
"""

import traceback

from flask import Blueprint, jsonify, request

from src.api.chat_auth import require_chat_auth
from src.services import fyns_service, logros_service as svc

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


@logros_bp.route('/beneficios', methods=['GET'])
@require_chat_auth
def beneficios():
    """Lo que el agente tiene por su plan y sus complementos (completo o borroso, y cuántos usos)."""
    from src.services import beneficios_service
    return _manejar(lambda: _ok(beneficios_service.beneficios(_uid())), 'beneficios')


@logros_bp.route('/fyns', methods=['GET'])
@require_chat_auth
def fyns_estado():
    def f():
        svc.evaluar(_uid())
        return _ok(fyns_service.estado(_uid()))
    return _manejar(f, 'fyns')


@logros_bp.route('/fyns/canjear', methods=['POST'])
@require_chat_auth
def fyns_canjear():
    try:
        return _ok(fyns_service.canjear(_uid(), str(_json().get("producto") or "")))
    except fyns_service.FynsError as e:
        return jsonify({"success": False, "code": e.codigo, "error": e.mensaje}), 400
    except Exception as e:
        print(f"❌ Error en logros/fyns_canjear: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


@logros_bp.route('/onboarding/completar', methods=['POST'])
@require_chat_auth
def completar_onboarding():
    def f():
        svc.completar_onboarding(_uid())
        return _ok({"ok": True})
    return _manejar(f, 'onboarding')
