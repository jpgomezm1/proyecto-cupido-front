"""
Índice Fynder mensual (indice_service, migración 064).

Público (solo ediciones publicadas):
    GET /api/indice              → la última edición + la lista de ediciones
    GET /api/indice/<AAAA-MM>    → una edición
    GET /api/cifras              → las cifras de la página de inicio (redondeadas hacia abajo)

El admin (calcular, revisar, publicar y la nota de prensa) vive en admin_negocio:
/api/admin/negocio/indice...
"""

import traceback

from flask import Blueprint, jsonify

from src.services import indice_service as svc

indice_bp = Blueprint('indice', __name__, url_prefix='/api')


def _manejar(fn, contexto: str):
    try:
        return jsonify({"success": True, "data": fn()})
    except svc.IndiceError as e:
        return jsonify({"success": False, "code": e.codigo, "error": e.mensaje}), 404 if e.codigo == "no_encontrado" else 400
    except Exception as e:  # noqa: BLE001
        print(f"❌ Error en indice/{contexto}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


@indice_bp.route('/indice', methods=['GET'])
def ultima():
    return _manejar(svc.ultima_publicada, 'ultima')


@indice_bp.route('/cifras', methods=['GET'])
def cifras():
    """Las cifras de la página de inicio («+8.000 inmuebles activos»…), en caché 10 min."""
    from src.services import market_service
    try:
        return jsonify({"success": True, "data": market_service.cifras_publicas_public()})
    except Exception as e:  # noqa: BLE001
        print(f"❌ Error en cifras: {e}")
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


@indice_bp.route('/indice/<mes>', methods=['GET'])
def edicion(mes):
    return _manejar(lambda: {**svc.edicion(mes), "ediciones": svc.publicadas()}, 'edicion')
