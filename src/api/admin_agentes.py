"""
Gestión de agentes desde el admin (JWT del admin, `proteger_admin` en main.py).

    POST /api/admin/agentes                      crear cuenta {tipo, nombre, email?, telefono?, verificar_telefono?,
                                                 plan_codigo?, forma_pago?, referencia?, monto_cop?, llaves_regalo?}
    GET  /api/admin/agentes/<id>                 ficha completa
    POST /api/admin/agentes/<id>/plan            {plan_codigo, forma_pago, referencia?, monto_cop?, notas?}
    POST /api/admin/agentes/<id>/llaves          {cantidad, motivo: regalo|venta|ajuste, referencia?, monto_cop?}
    POST /api/admin/agentes/<id>/clave           clave nueva (se ve una vez; cierra sesiones)

Lógica en `services/admin_agentes_service.py`.
"""

import traceback

from flask import Blueprint, jsonify, request

from src.services import admin_agentes_service as svc

admin_agentes_bp = Blueprint('admin_agentes', __name__, url_prefix='/api/admin/agentes')


def _admin() -> str:
    from src.api.access import admin_actual
    return (admin_actual() or {}).get('email') or 'admin'


def _op(fn, contexto: str):
    try:
        return jsonify({"success": True, "data": fn()})
    except svc.AgenteError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        print(f"❌ Error en admin_agentes/{contexto}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


def _json() -> dict:
    return request.get_json(silent=True) or {}


@admin_agentes_bp.route('', methods=['POST'])
def crear():
    return _op(lambda: svc.crear_agente(_json(), _admin()), 'crear')


@admin_agentes_bp.route('/<int:user_id>', methods=['GET'])
def ficha(user_id: int):
    return _op(lambda: svc.ficha(user_id), 'ficha')


@admin_agentes_bp.route('/<int:user_id>/linea', methods=['GET'])
def linea(user_id: int):
    """La historia del agente en un solo hilo (linea_tiempo_service)."""
    from src.services import linea_tiempo_service
    return _op(lambda: linea_tiempo_service.de(user_id), 'linea')


@admin_agentes_bp.route('/<int:user_id>/plan', methods=['POST'])
def plan(user_id: int):
    d = _json()
    return _op(lambda: svc.activar_plan(user_id, d.get('plan_codigo', ''), d.get('forma_pago', ''),
                                        d.get('referencia'), d.get('monto_cop'), d.get('notas'), _admin()), 'plan')


@admin_agentes_bp.route('/<int:user_id>/llaves', methods=['POST'])
def llaves(user_id: int):
    d = _json()
    return _op(lambda: svc.dar_llaves(user_id, d.get('cantidad', 0), d.get('motivo', ''),
                                      d.get('referencia'), d.get('monto_cop'), _admin()), 'llaves')


@admin_agentes_bp.route('/<int:user_id>/clave', methods=['POST'])
def clave(user_id: int):
    return _op(lambda: svc.nueva_clave(user_id), 'clave')
