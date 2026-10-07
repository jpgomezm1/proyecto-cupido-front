"""
API del mapa de mercado (agente autenticado).

    GET /api/chat/mapa/zonas                          → zonas con oferta, demanda, precios y temperatura
    GET /api/chat/mapa/zonas/<id>                     → detalle: oportunidades, recientes, histograma, pedidos
    GET /api/chat/mapa/inmuebles?bbox=s,w,n,e&tipo=&precio_min=&precio_max=&hab_min=
                                                      → inmuebles del área visible + resumen
    GET /api/chat/mapa/buscar?q=                       → zonas por nombre

Sin contactos ni links de portal. La lógica vive en `src/services/mapa_service.py`.
"""

import traceback

from flask import Blueprint, jsonify, request

from src.api.chat_auth import require_chat_auth
from src.services import mapa_service as svc

mapa_bp = Blueprint('mapa', __name__, url_prefix='/api/chat/mapa')


def _fallo(e: Exception, contexto: str):
    print(f"❌ Error en mapa/{contexto}: {e}")
    traceback.print_exc()
    return jsonify({"success": False, "error": "Error en el servidor"}), 500


def _num(nombre: str, tipo=float):
    v = request.args.get(nombre)
    try:
        return tipo(v) if v not in (None, "") else None
    except ValueError:
        return None


@mapa_bp.route('/zonas', methods=['GET'])
@require_chat_auth
def zonas():
    try:
        return jsonify({"success": True, "data": svc.zonas()})
    except Exception as e:
        return _fallo(e, 'zonas')


@mapa_bp.route('/zonas/<path:zona_id>', methods=['GET'])
@require_chat_auth
def zona(zona_id: str):
    try:
        d = svc.zona_detalle(zona_id, request.chat_user['id'])
        if not d:
            return jsonify({"success": False, "error": "Zona no encontrada"}), 404
        return jsonify({"success": True, "data": d})
    except Exception as e:
        return _fallo(e, 'zona')


@mapa_bp.route('/inmuebles', methods=['GET'])
@require_chat_auth
def inmuebles():
    try:
        partes = [float(x) for x in (request.args.get('bbox') or '').split(',')]
        if len(partes) != 4:
            raise ValueError
    except ValueError:
        return jsonify({"success": False, "error": "bbox=s,w,n,e requerido"}), 400
    s, w, n, e = partes
    if n - s > 1.5 or e - w > 1.5:  # nunca todo el país de una
        return jsonify({"success": False, "error": "Acerca un poco más el mapa"}), 400
    try:
        return jsonify({"success": True, "data": svc.inmuebles(
            (s, w, n, e), request.args.get('tipo') or None, _num('precio_min'), _num('precio_max'), _num('hab_min', int))})
    except Exception as e:
        return _fallo(e, 'inmuebles')


@mapa_bp.route('/buscar', methods=['GET'])
@require_chat_auth
def buscar():
    try:
        return jsonify({"success": True, "data": svc.buscar_zona(request.args.get('q') or '')})
    except Exception as e:
        return _fallo(e, 'buscar')
