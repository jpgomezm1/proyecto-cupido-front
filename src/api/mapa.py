"""
API del mapa de mercado (agente autenticado).

    GET    /api/chat/mapa/capas                 → zonas (con forma), hexágonos y puntos del inventario
    GET    /api/chat/mapa/zonas                 → solo zonas
    GET    /api/chat/mapa/zonas/<id>            → detalle de una zona
    POST   /api/chat/mapa/area {poligono, nombre?} → análisis de un área dibujada
    GET    /api/chat/mapa/areas                 → áreas guardadas del agente
    POST   /api/chat/mapa/areas {nombre, poligono, color?}
    DELETE /api/chat/mapa/areas/<id>
    POST   /api/chat/mapa/preguntar {pregunta, zona_id?, area?}   → IA: "Pregúntale al mapa"
    POST   /api/chat/mapa/lectura {zona_id? | area?}              → IA: lectura de Findy
    GET    /api/chat/mapa/buscar?q=

Sin contactos ni links de portal. La lógica vive en `mapa_service.py` y `mapa_ia.py`.
"""

import gzip
import json
import traceback

from flask import Blueprint, Response, jsonify, request

from src.api.chat_auth import require_chat_auth
from src.services import mapa_ia, mapa_service as svc

mapa_bp = Blueprint('mapa', __name__, url_prefix='/api/chat/mapa')

_STATUS = {"invalido": 400, "no_encontrado": 404, "limite": 429, "ia": 503}


def _ok(data, status=200):
    return jsonify({"success": True, "data": data}), status


def _manejar(fn, contexto: str):
    try:
        return fn()
    except svc.MapaError as e:
        return jsonify({"success": False, "code": e.codigo, "error": e.mensaje}), _STATUS.get(e.codigo, 400)
    except Exception as e:
        print(f"❌ Error en mapa/{contexto}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


def _uid() -> int:
    return request.chat_user['id']


def _json() -> dict:
    return request.get_json(silent=True) or {}


_capas_gz = {"generado": None, "cuerpo": b""}


@mapa_bp.route('/capas', methods=['GET'])
@require_chat_auth
def capas():
    """~850 KB en JSON → ~120 KB con gzip (se comprime una vez por cada versión del caché)."""
    def f():
        d = svc.capas()
        cuerpo = json.dumps({"success": True, "data": d}, default=str, separators=(",", ":")).encode()
        if "gzip" not in (request.headers.get("Accept-Encoding") or ""):
            return Response(cuerpo, mimetype="application/json")
        if _capas_gz["generado"] != d["generado"]:
            _capas_gz.update(generado=d["generado"], cuerpo=gzip.compress(cuerpo, 6))
        r = Response(_capas_gz["cuerpo"], mimetype="application/json")
        r.headers["Content-Encoding"] = "gzip"
        r.headers["Vary"] = "Accept-Encoding"
        return r
    return _manejar(f, 'capas')


@mapa_bp.route('/zonas', methods=['GET'])
@require_chat_auth
def zonas():
    return _manejar(lambda: _ok(svc.zonas()), 'zonas')


@mapa_bp.route('/zonas/<path:zona_id>', methods=['GET'])
@require_chat_auth
def zona(zona_id: str):
    def f():
        d = svc.zona_detalle(zona_id, _uid())
        if not d:
            raise svc.MapaError("no_encontrado", "Zona no encontrada.")
        return _ok(d)
    return _manejar(f, 'zona')


@mapa_bp.route('/area', methods=['POST'])
@require_chat_auth
def area():
    d = _json()
    return _manejar(lambda: _ok(svc.area_detalle(d.get('poligono'), _uid(), d.get('nombre'))), 'area')


@mapa_bp.route('/areas', methods=['GET'])
@require_chat_auth
def areas():
    return _manejar(lambda: _ok({"areas": svc.listar_areas(_uid())}), 'areas')


@mapa_bp.route('/areas', methods=['POST'])
@require_chat_auth
def guardar_area():
    d = _json()
    return _manejar(lambda: _ok(svc.guardar_area(_uid(), d.get('nombre'), d.get('poligono'), d.get('color')), 201), 'guardar_area')


@mapa_bp.route('/areas/<int:area_id>', methods=['DELETE'])
@require_chat_auth
def borrar_area(area_id: int):
    def f():
        if not svc.borrar_area(_uid(), area_id):
            raise svc.MapaError("no_encontrado", "Área no encontrada.")
        return _ok({"ok": True})
    return _manejar(f, 'borrar_area')


@mapa_bp.route('/preguntar', methods=['POST'])
@require_chat_auth
def preguntar():
    d = _json()
    return _manejar(lambda: _ok(mapa_ia.preguntar(_uid(), d.get('pregunta'), d.get('zona_id'), d.get('area'))), 'preguntar')


@mapa_bp.route('/lectura', methods=['POST'])
@require_chat_auth
def lectura():
    d = _json()
    return _manejar(lambda: _ok(mapa_ia.lectura(_uid(), d.get('zona_id'), d.get('area'))), 'lectura')


@mapa_bp.route('/buscar', methods=['GET'])
@require_chat_auth
def buscar():
    return _manejar(lambda: _ok(svc.buscar_zona(request.args.get('q') or '')), 'buscar')
