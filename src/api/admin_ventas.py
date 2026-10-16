"""
Admin › Ventas: la lista de agentes para la línea de WhatsApp de ventas (solo
outbound, para conseguir reuniones) y el plan Fundador. Lógica en
services/ventas_service.py y services/fundador_service.py.

    GET  /api/admin/ventas/agentes?estado=&fuente=&q=&limite=&offset=&remitente=
    GET  /api/admin/ventas/hoy                      → a quién llamar hoy
    GET  /api/admin/ventas/agentes/<tel>/historial
    POST /api/admin/ventas/agentes                  {fuente, filas: [{nombre, telefono}]}
    POST /api/admin/ventas/agentes/<tel>            {estado?, notas?, reunion_at?}
    POST /api/admin/ventas/agentes/<tel>/enviado    {texto?}
    POST /api/admin/ventas/agentes/<tel>/gancho     → recalcula el gancho
    POST /api/admin/ventas/agentes/<tel>/fundador   {referencia?, forzar?}
    POST /api/admin/ventas/sembrar                  → agrega celulares nuevos y sincroniza estados

Protegido con el JWT del admin (`proteger_admin` en main.py): trae celulares de agentes.
"""

import traceback

from flask import Blueprint, jsonify, request

from src.services import ventas_service as ventas
from src.services.fundador_service import FundadorError

admin_ventas_bp = Blueprint('admin_ventas', __name__, url_prefix='/api/admin/ventas')


def _ok(data):
    return jsonify({"success": True, "data": data})


def _admin() -> str:
    from src.api.access import admin_actual
    return (admin_actual() or {}).get('email') or 'admin'


def _fallo(e: Exception, contexto: str):
    if isinstance(e, (ventas.VentasError, FundadorError)):
        return jsonify({"success": False, "error": e.mensaje, "codigo": e.codigo}), 400
    print(f"❌ Error en admin_ventas/{contexto}: {e}")
    traceback.print_exc()
    return jsonify({"success": False, "error": "Error en el servidor"}), 500


def _int(nombre: str, defecto: int, maximo: int = 200) -> int:
    try:
        return max(0, min(maximo, int(request.args.get(nombre, defecto))))
    except (TypeError, ValueError):
        return defecto


@admin_ventas_bp.route('/agentes', methods=['GET'])
def listar():
    try:
        return _ok(ventas.listar(
            estado=request.args.get('estado') or None, fuente=request.args.get('fuente') or None,
            q=(request.args.get('q') or '').strip() or None, limite=_int('limite', 50) or 50,
            offset=_int('offset', 0, 100_000), remitente=(request.args.get('remitente') or '').strip()[:40]))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'listar')


@admin_ventas_bp.route('/hoy', methods=['GET'])
def hoy():
    try:
        return _ok(ventas.hoy())
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'hoy')


@admin_ventas_bp.route('/agentes/<tel>/historial', methods=['GET'])
def historial(tel: str):
    try:
        return _ok(ventas.historial(tel))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'historial')


@admin_ventas_bp.route('/agentes', methods=['POST'])
def agregar():
    body = request.get_json(silent=True) or {}
    filas = body.get('filas') or []
    if not isinstance(filas, list) or not filas or len(filas) > 500:
        return jsonify({"success": False, "error": "Manda entre 1 y 500 filas."}), 400
    try:
        return _ok(ventas.agregar(filas, body.get('fuente') or 'otro', admin=_admin()))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'agregar')


@admin_ventas_bp.route('/agentes/<tel>', methods=['POST'])
def actualizar(tel: str):
    body = request.get_json(silent=True) or {}
    cambios = {k: body[k] for k in ('estado', 'notas', 'reunion_at') if k in body}
    try:
        return _ok(ventas.actualizar(tel, cambios, admin=_admin()))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'actualizar')


@admin_ventas_bp.route('/agentes/<tel>/enviado', methods=['POST'])
def enviado(tel: str):
    body = request.get_json(silent=True) or {}
    try:
        return _ok(ventas.marcar_enviado(tel, body.get('texto'), admin=_admin()))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'enviado')


@admin_ventas_bp.route('/agentes/<tel>/gancho', methods=['POST'])
def gancho(tel: str):
    try:
        return _ok(ventas.recalcular(tel))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'gancho')


@admin_ventas_bp.route('/agentes/<tel>/fundador', methods=['POST'])
def fundador(tel: str):
    body = request.get_json(silent=True) or {}
    try:
        return _ok(ventas.activar_fundador(tel, admin=_admin(), referencia=(body.get('referencia') or None),
                                           forzar=bool(body.get('forzar'))))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'fundador')


@admin_ventas_bp.route('/sembrar', methods=['POST'])
def sembrar():
    try:
        return _ok(ventas.sembrar())
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'sembrar')
