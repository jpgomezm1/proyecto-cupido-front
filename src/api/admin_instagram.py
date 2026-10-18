"""
Admin › Instagram: la parrilla de @fynder (copia del módulo de Órbita). Cero llamadas
a Buffer por carga: lee lo que deja el worker en instagram_posts.

    GET  /api/admin/instagram               → posts, última sincronización, seguidores, meta
    POST /api/admin/instagram/seguidores    {n, meta?}
    POST /api/admin/instagram/sincronizar   → corre la sincronización ya (máx. 1 cada 10 min)

Protegido con el JWT del admin (`proteger_admin` en main.py).
"""

import traceback
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from src.services import instagram_service as ig

admin_instagram_bp = Blueprint('admin_instagram', __name__, url_prefix='/api/admin/instagram')


def _ok(data):
    return jsonify({"success": True, "data": data})


def _fallo(e: Exception, contexto: str):
    print(f"❌ Error en admin_instagram/{contexto}: {e}")
    traceback.print_exc()
    return jsonify({"success": False, "error": "Error en el servidor"}), 500


def _admin() -> str:
    from src.api.access import admin_actual
    return (admin_actual() or {}).get('email') or 'admin'


@admin_instagram_bp.route('', methods=['GET'])
def estado():
    try:
        return _ok(ig.estado())
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'estado')


@admin_instagram_bp.route('/seguidores', methods=['POST'])
def seguidores():
    body = request.get_json(silent=True) or {}
    try:
        n = int(body.get('n'))
        meta = int(body['meta']) if body.get('meta') not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Escribe un número de seguidores válido."}), 400
    if not 0 <= n <= 10_000_000:
        return jsonify({"success": False, "error": "Escribe un número de seguidores válido."}), 400
    if meta is not None and meta <= 0:
        return jsonify({"success": False, "error": "La meta tiene que ser un número mayor que cero."}), 400
    try:
        return _ok(ig.anotar_seguidores(n, meta, admin=_admin()))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'seguidores')


@admin_instagram_bp.route('/sincronizar', methods=['POST'])
def sincronizar():
    """A mano, para no esperar al worker. Buffer limita las llamadas: máximo una cada 10 minutos."""
    try:
        ultima = ig.ultima_sincronizacion()
        if ultima and datetime.now(timezone.utc) - datetime.fromisoformat(ultima) < timedelta(minutes=10):
            return jsonify({"success": False, "error": "Se sincronizó hace menos de 10 minutos. Espera un poco."}), 429
        return _ok(ig.sincronizar())
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'sincronizar')
