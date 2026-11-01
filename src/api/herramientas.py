"""
Herramientas del agente: radar de oportunidades, calidad del aviso y su página.

    GET  /api/chat/radar                                 → oportunidades del día (sin IA)
    GET  /api/chat/oportunidades/marcas?ids=…            → badges del inventario (bajó de precio, Vitrina)
    GET  /api/chat/mis-propiedades/<id>/calidad          → puntaje del aviso y qué mejorar
    GET  /api/chat/mi-pagina                             → su página pública (config)
    PUT  /api/chat/mi-pagina                             {slug?, bio?, zonas?, logo_url?, foto_url?, marca_nombre?, config?, activa?}
    POST /api/chat/mi-pagina/ia/armar                    {indicaciones?} → propuesta de la IA (no guarda)
    POST /api/chat/mi-pagina/ia/mejorar                  {campo, texto, pedido?, contexto?} → texto reescrito
    GET  /api/chat/mi-pagina/imagenes                    → biblioteca de imágenes y cupo de imágenes con IA
    POST /api/chat/mi-pagina/imagenes                    {descripcion, estilo?, formato?} → imagen con IA (gasta cupo)
    POST /api/chat/mi-pagina/imagenes/subida             {url} → guarda en la biblioteca una imagen que subió
    POST /api/chat/mi-pagina/imagenes/sugerir            {para?, pista?} → 3 descripciones para generar
    GET  /api/public/agente/<slug>                       → la página pública (sin login)
    POST /api/public/agente/<slug>/evento                {tipo: visita|whatsapp|inmueble|valorar}
    GET  /api/chat/fotos-ia/cupo                         → fotos mejoradas que le quedan este mes
    POST /api/chat/mis-propiedades/<id>/fotos/mejorar    {url} → versión mejorada (no reemplaza)
    POST /api/chat/mis-propiedades/<id>/fotos/mejoradas/<mid>/aplicar → reemplaza la original

La lógica vive en `radar_service.py`, `pagina_agente_service.py` y `pagina_ia_service.py`.
"""

import traceback

from flask import Blueprint, jsonify, request

from src.api.chat_auth import require_chat_auth
from src.api.listings import _tel10_verificado
from src.services import fotos_ia_service as fotos_ia, pagina_agente_service as pagina, pagina_ia_service as pagina_ia, radar_service
from src.services import pagina_imagenes_service as pagina_img

herramientas_bp = Blueprint('herramientas', __name__, url_prefix='/api')


def _ok(data):
    return jsonify({"success": True, "data": data})


def _manejar(fn, contexto: str):
    from src.services.mis_propiedades_service import EdicionError
    try:
        return fn()
    except fotos_ia.FotoError as e:
        return jsonify({"success": False, "error": e.mensaje, "code": e.codigo}), e.status
    except pagina_img.ImagenError as e:
        return jsonify({"success": False, "error": e.mensaje, "code": e.codigo}), e.status
    except pagina.PaginaError as e:
        return jsonify({"success": False, "error": e.mensaje, "code": e.codigo}), 404 if e.codigo == "no_encontrado" else 400
    except pagina_ia.PaginaIAError as e:
        return jsonify({"success": False, "error": e.mensaje, "code": e.codigo}), {"limite": 429, "ia": 503}.get(e.codigo, 400)
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


@herramientas_bp.route('/chat/oportunidades/marcas', methods=['GET'])
@require_chat_auth
def oportunidades_marcas():
    """?ids=1,2,3 → badges de oportunidad para las tarjetas del inventario."""
    ids = [x for x in (request.args.get('ids') or '').split(',') if x.strip().isdigit()]
    return _manejar(lambda: _ok(radar_service.marcas(request.chat_user['id'], ids)), 'oportunidades_marcas')


@herramientas_bp.route('/chat/mis-propiedades/<int:property_id>/calidad', methods=['GET'])
@require_chat_auth
def calidad(property_id):
    return _manejar(lambda: _ok(radar_service.calidad(property_id, _tel10_verificado(request.chat_user))), 'calidad')


@herramientas_bp.route('/chat/mi-pagina', methods=['GET'])
@require_chat_auth
def mi_pagina():
    uid = request.chat_user['id']
    return _manejar(lambda: _ok({**pagina.mi_pagina(uid), "ia": pagina_ia.cupo(uid)}), 'mi_pagina')


@herramientas_bp.route('/chat/mi-pagina', methods=['PUT'])
@require_chat_auth
def guardar_pagina():
    uid = request.chat_user['id']
    return _manejar(lambda: _ok({**pagina.guardar(uid, request.get_json(silent=True) or {}), "ia": pagina_ia.cupo(uid)}),
                    'guardar_pagina')


@herramientas_bp.route('/chat/mi-pagina/ia/armar', methods=['POST'])
@require_chat_auth
def pagina_ia_armar():
    d = request.get_json(silent=True) or {}
    return _manejar(lambda: _ok(pagina_ia.armar(request.chat_user['id'], d.get('indicaciones'))), 'pagina_ia_armar')


@herramientas_bp.route('/chat/mi-pagina/ia/mejorar', methods=['POST'])
@require_chat_auth
def pagina_ia_mejorar():
    d = request.get_json(silent=True) or {}
    return _manejar(lambda: _ok(pagina_ia.mejorar(request.chat_user['id'], d.get('campo'), d.get('texto') or '',
                                                  d.get('pedido'), d.get('contexto'))), 'pagina_ia_mejorar')


@herramientas_bp.route('/chat/mi-pagina/imagenes', methods=['GET'])
@require_chat_auth
def pagina_imagenes():
    return _manejar(lambda: _ok(pagina_img.biblioteca(request.chat_user['id'])), 'pagina_imagenes')


@herramientas_bp.route('/chat/mi-pagina/imagenes', methods=['POST'])
@require_chat_auth
def pagina_imagen_generar():
    d = request.get_json(silent=True) or {}
    return _manejar(lambda: _ok(pagina_img.generar(request.chat_user['id'], d.get('descripcion') or '',
                                                   d.get('estilo'), d.get('formato'))), 'pagina_imagen_generar')


@herramientas_bp.route('/chat/mi-pagina/imagenes/subida', methods=['POST'])
@require_chat_auth
def pagina_imagen_subida():
    d = request.get_json(silent=True) or {}
    return _manejar(lambda: _ok(pagina_img.registrar_subida(request.chat_user['id'], d.get('url') or '')),
                    'pagina_imagen_subida')


@herramientas_bp.route('/chat/mi-pagina/imagenes/sugerir', methods=['POST'])
@require_chat_auth
def pagina_imagen_sugerir():
    d = request.get_json(silent=True) or {}
    return _manejar(lambda: _ok(pagina_img.sugerir(request.chat_user['id'], d.get('para'), d.get('pista'))),
                    'pagina_imagen_sugerir')


@herramientas_bp.route('/public/agente/<slug>', methods=['GET'])
def pagina_publica(slug):
    return _manejar(lambda: _ok(pagina.publica(slug)), 'pagina_publica')


@herramientas_bp.route('/public/agente/<slug>/evento', methods=['POST'])
def pagina_evento(slug):
    tipo = (request.get_json(silent=True) or {}).get('tipo')
    return _manejar(lambda: (pagina.registrar_evento(slug, tipo), _ok({"ok": True}))[1], 'pagina_evento')


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


@herramientas_bp.route('/chat/eventos', methods=['POST'])
@require_chat_auth
def registrar_eventos():
    """Lote de eventos de uso de la interfaz {eventos: [{evento, ruta?, props?}]} (máx. 30)."""
    from src.services.eventos_uso_service import registrar
    datos = request.get_json(silent=True) or {}
    return jsonify({"success": True, "data": {"guardados": registrar(request.chat_user['id'], datos.get('eventos') or [])}})


@herramientas_bp.route('/chat/etapa', methods=['GET'])
@require_chat_auth
def etapa():
    """Cuánto ha usado Fynder el agente: la app decide con esto qué herramientas mostrarle."""
    from src.services import etapa_service
    user = request.chat_user
    try:
        return jsonify({"success": True, "data": etapa_service.resumen(user['id'], _tel10_verificado(user))})
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)[:200]}), 500
