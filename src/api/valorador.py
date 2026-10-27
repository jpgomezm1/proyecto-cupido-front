"""
Valorador para propietarios (valorador_service, migración 063).

Público (sin cuenta; límites por IP en main.py):
    GET  /api/valorar/barrios?q=            → barrios del catálogo
    GET  /api/valorar/agente/<slug>         → la marca del agente para /a/<slug>/valorar
    POST /api/valorar {tipo, barrio_id, area, habitaciones?, banos?, agente?, desde?}
                                            → {token, resultado, agente}
    POST /api/valorar/<token>/contacto {nombre, telefono, intencion, plazo, acepta}
                                            → envía el código por WhatsApp
    POST /api/valorar/<token>/verificar {codigo}
    POST /api/valorar/retirar/<token_retiro> → el propietario ya no quiere que lo contacten

Agente (require_chat_auth):
    GET  /api/chat/propietarios             → los propietarios que puede abrir (sin contacto)
    GET  /api/chat/mi-valorador             → su link y cuánto le ha servido
El contacto se abre con POST /api/chat/desbloquear {tipo: 'valoracion', ref}.
"""

import traceback

from flask import Blueprint, jsonify, request

from src.api.chat_auth import require_chat_auth
from src.services import valorador_service as svc

valorador_bp = Blueprint('valorador', __name__, url_prefix='/api')

_STATUS = {"invalido": 400, "incorrecto": 400, "vencido": 400, "ya": 409, "limite": 429, "envio": 502,
           "no_encontrada": 404, "agente": 404}


def _manejar(fn, contexto: str, status: int = 200):
    try:
        return jsonify({"success": True, "data": fn()}), status
    except svc.ValoradorError as e:
        return jsonify({"success": False, "code": e.codigo, "campo": e.campo, "error": e.mensaje}), \
            _STATUS.get(e.codigo, 400)
    except Exception as e:  # noqa: BLE001
        print(f"❌ Error en valorador/{contexto}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


def _json() -> dict:
    return request.get_json(silent=True) or {}


def _ip() -> str:
    return (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()


@valorador_bp.route('/valorar/barrios', methods=['GET'])
def barrios():
    return _manejar(lambda: svc.barrios(request.args.get('q', '')), 'barrios')


@valorador_bp.route('/valorar/agente/<slug>', methods=['GET'])
def agente(slug):
    return _manejar(lambda: svc.agente(slug), 'agente')


@valorador_bp.route('/valorar', methods=['POST'])
def valorar():
    return _manejar(lambda: svc.valorar(_json(), ip=_ip()), 'valorar', 201)


@valorador_bp.route('/valorar/<token>/contacto', methods=['POST'])
def contacto(token):
    return _manejar(lambda: svc.pedir_contacto(token, _json()), 'contacto')


@valorador_bp.route('/valorar/<token>/verificar', methods=['POST'])
def verificar(token):
    return _manejar(lambda: svc.verificar(token, str(_json().get('codigo') or '')), 'verificar')


@valorador_bp.route('/valorar/retirar/<token>', methods=['POST'])
def retirar(token):
    return _manejar(lambda: svc.retirar(token), 'retirar')


@valorador_bp.route('/chat/propietarios', methods=['GET'])
@require_chat_auth
def propietarios():
    return _manejar(lambda: svc.para_agente(request.chat_user['id']), 'propietarios')


@valorador_bp.route('/chat/mi-valorador', methods=['GET'])
@require_chat_auth
def mi_valorador():
    return _manejar(lambda: svc.mi_valorador(request.chat_user['id']), 'mi_valorador')
