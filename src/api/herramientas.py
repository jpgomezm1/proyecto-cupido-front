"""
Herramientas del agente: radar de oportunidades, calidad del aviso y su página.

    GET  /api/chat/radar                                 → oportunidades del día (sin IA)
    GET  /api/chat/mis-propiedades/<id>/calidad          → puntaje del aviso y qué mejorar
    GET  /api/chat/mi-pagina                             → su página pública (config)
    PUT  /api/chat/mi-pagina                             {slug?, bio?, zonas?, logo_url?, foto_url?, marca_nombre?, activa?}
    GET  /api/public/agente/<slug>                       → la página pública (sin login)
    GET  /api/chat/fotos-ia/cupo                         → fotos mejoradas que le quedan este mes
    POST /api/chat/mis-propiedades/<id>/fotos/mejorar    {url} → versión mejorada (no reemplaza)
    POST /api/chat/mis-propiedades/<id>/fotos/mejoradas/<mid>/aplicar → reemplaza la original

La lógica vive en `radar_service.py` y `pagina_agente_service.py`.
"""

import traceback

from flask import Blueprint, jsonify, request

from src.api.chat_auth import require_chat_auth
from src.api.listings import _tel10_verificado
from src.services import fotos_ia_service as fotos_ia, pagina_agente_service as pagina, radar_service

herramientas_bp = Blueprint('herramientas', __name__, url_prefix='/api')


def _ok(data):
    return jsonify({"success": True, "data": data})


def _manejar(fn, contexto: str):
    from src.services.mis_propiedades_service import EdicionError
    try:
        return fn()
    except fotos_ia.FotoError as e:
        return jsonify({"success": False, "error": e.mensaje, "code": e.codigo}), e.status
    except pagina.PaginaError as e:
        return jsonify({"success": False, "error": e.mensaje, "code": e.codigo}), 404 if e.codigo == "no_encontrado" else 400
    except EdicionError as e:
        return jsonify({"success": False, "error": str(e)}), getattr(e, "status", 400)
    except Exception as e:
        print(f"❌ Error en herramientas/{contexto}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500




@herramientas_bp.route('/chat/radar', methods=['GET'])
@require_chat_auth
def radar():
    return _manejar(lambda: _ok(radar_service.radar(request.args.get('limite', 8, type=int))), 'radar')


@herramientas_bp.route('/chat/mis-propiedades/<int:property_id>/calidad', methods=['GET'])
@require_chat_auth
def calidad(property_id):
    return _manejar(lambda: _ok(radar_service.calidad(property_id, _tel10_verificado(request.chat_user))), 'calidad')


@herramientas_bp.route('/chat/mi-pagina', methods=['GET'])
@require_chat_auth
def mi_pagina():
    return _manejar(lambda: _ok(pagina.mi_pagina(request.chat_user['id'])), 'mi_pagina')


@herramientas_bp.route('/chat/mi-pagina', methods=['PUT'])
@require_chat_auth
def guardar_pagina():
    return _manejar(lambda: _ok(pagina.guardar(request.chat_user['id'], request.get_json(silent=True) or {})),
                    'guardar_pagina')


@herramientas_bp.route('/public/agente/<slug>', methods=['GET'])
def pagina_publica(slug):
    return _manejar(lambda: _ok(pagina.publica(slug)), 'pagina_publica')


@herramientas_bp.route('/chat/fotos-ia/cupo', methods=['GET'])
@require_chat_auth
def fotos_cupo():
    return _manejar(lambda: _ok(fotos_ia.cupo(request.chat_user['id'])), 'fotos_cupo')


@herramientas_bp.route('/chat/mis-propiedades/<int:property_id>/fotos/mejorar', methods=['POST'])
@require_chat_auth
def fotos_mejorar(property_id):
    url = (request.get_json(silent=True) or {}).get('url')
    if not url:
        return jsonify({"success": False, "error": "Falta la foto (url)"}), 400
    user = request.chat_user
    return _manejar(lambda: _ok(fotos_ia.mejorar(user['id'], _tel10_verificado(user), property_id, url)), 'fotos_mejorar')


@herramientas_bp.route('/chat/mis-propiedades/<int:property_id>/fotos/mejoradas/<int:mejora_id>/aplicar', methods=['POST'])
@require_chat_auth
def fotos_aplicar(property_id, mejora_id):
    user = request.chat_user
    return _manejar(lambda: _ok(fotos_ia.aplicar(user['id'], _tel10_verificado(user), property_id, mejora_id)),
                    'fotos_aplicar')
