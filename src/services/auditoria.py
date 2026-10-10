"""
Registro de acciones sensibles del admin (tabla `auditoria_admin`, migración 053):
verificar o cambiar el teléfono de un agente (da control sobre su inventario) y
regenerar claves de acceso. Nunca tumba la acción si el registro falla.
"""

import json
from typing import Any, Dict, Optional

from src.services.db import get_db


def _admin_email() -> Optional[str]:
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return None
        actual = getattr(g, "current_user", None) or {}
        if actual.get("email"):
            return actual["email"]
        from src.api.access import admin_actual
        return (admin_actual() or {}).get("email")
    except Exception:  # noqa: BLE001
        return None


def registrar(accion: str, user_id: Optional[int] = None, detalle: Optional[Dict[str, Any]] = None) -> None:
    try:
        with get_db() as db:
            db.cursor.execute(
                "INSERT INTO auditoria_admin (admin_email, accion, user_id, detalle) VALUES (%s, %s, %s, %s)",
                (_admin_email(), accion, user_id, json.dumps(detalle or {}, default=str)))
            db.conn.commit()
    except Exception as e:  # noqa: BLE001 — sin la tabla (053 sin aplicar) no se rompe nada
        print(f"[auditoria] no se pudo registrar {accion}: {e}")
