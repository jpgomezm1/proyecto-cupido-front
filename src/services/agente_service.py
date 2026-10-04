"""
Datos PÚBLICOS del agente que comparte un link con su cliente.

El "agente" es el usuario de Fynder que ENVIÓ el link (no el captador/dueño de
la propiedad, cuyo contacto es un desbloqueo pago y nunca se expone aquí).

Regla de negocio: solo se devuelve el contacto si el usuario está activo y su
teléfono está VERIFICADO; de lo contrario `None` (la UI muestra "Pídele más
información a tu asesor" sin número).

Sin dependencias de Flask: se importa tanto desde la API como desde el MCP.
"""

from typing import Any, Dict, Optional

from src.services.db import get_db, fetch_one


def _to_int(user_id: Any) -> Optional[int]:
    try:
        n = int(user_id)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def agente_publico(user_id: Any) -> Optional[Dict[str, Any]]:
    """{id, name, phone, whatsapp} del agente verificado, o None."""
    uid = _to_int(user_id)
    if uid is None:
        return None
    try:
        with get_db() as db:
            user = fetch_one(db.cursor, """
                SELECT id, nombre, telefono
                FROM chat_users
                WHERE id = %s AND activo AND telefono_verificado
            """, (uid,))
    except Exception:
        return None
    if not user or not user.get("telefono"):
        return None
    phone = user["telefono"]
    return {
        "id": user["id"],
        "name": user.get("nombre") or "Tu asesor",
        "phone": phone,
        "whatsapp": phone.replace("+", "") if phone else None,
    }
