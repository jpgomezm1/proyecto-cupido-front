"""
API de registro autogestionado y verificación del celular.

    POST /api/chat/registro {nombre, email, clave, telefono, acepta_terminos}
         → crea la cuenta (luego el front inicia sesión con /api/chat/login)
    POST /api/chat/telefono/codigo {telefono?}      (require_chat_auth)
         → envía un código de 6 dígitos por WhatsApp
    POST /api/chat/telefono/verificar {codigo}      (require_chat_auth)
         → verifica el celular y otorga los créditos de prueba

La lógica vive en `src/services/registro_service.py`.
"""

import traceback

from flask import Blueprint, jsonify, request

from src.api.chat_auth import require_chat_auth
from src.services import registro_service as svc

registro_bp = Blueprint('registro', __name__, url_prefix='/api/chat')

_STATUS = {"invalido": 400, "incorrecto": 400, "vencido": 400, "duplicado": 409, "ya_verificado": 409,
           "limite": 429, "envio": 502, "no_encontrado": 404}


def _error(e: svc.RegistroError):
    return jsonify({"success": False, "code": e.codigo, "campo": e.campo, "error": e.mensaje}), \
        _STATUS.get(e.codigo, 400)


def _fallo(e: Exception, contexto: str):
    print(f"❌ Error en {contexto}: {e}")
    traceback.print_exc()
    return jsonify({"success": False, "error": "Error en el servidor"}), 500


@registro_bp.route('/registro', methods=['POST'])
def registro():
    d = request.get_json(silent=True) or {}
    try:
        res = svc.registrar(d.get('nombre'), d.get('email'), d.get('clave'), d.get('telefono'),
                            bool(d.get('acepta_terminos')))
        return jsonify({"success": True, "data": res}), 201
    except svc.RegistroError as e:
        return _error(e)
    except Exception as e:
        return _fallo(e, 'registro')


@registro_bp.route('/telefono/codigo', methods=['POST'])
@require_chat_auth
def enviar_codigo():
    d = request.get_json(silent=True) or {}
    try:
        return jsonify({"success": True, "data": svc.enviar_codigo(request.chat_user['id'], d.get('telefono'))})
    except svc.RegistroError as e:
        return _error(e)
    except Exception as e:
        return _fallo(e, 'enviar_codigo')


@registro_bp.route('/telefono/verificar', methods=['POST'])
@require_chat_auth
def verificar():
    d = request.get_json(silent=True) or {}
    try:
        return jsonify({"success": True, "data": svc.verificar_codigo(request.chat_user['id'], str(d.get('codigo') or ''))})
    except svc.RegistroError as e:
        return _error(e)
    except Exception as e:
        return _fallo(e, 'verificar_codigo')
