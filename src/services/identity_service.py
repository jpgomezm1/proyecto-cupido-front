"""
Servicio de identidad para el MCP de Fynder.

Resuelve un bearer token -> agente (chat_user). Reusa la infraestructura que YA
existe para los usuarios de chat: `chat_users` + `chat_user_sessions` (tokens
opacos `secrets.token_urlsafe(64)`). No toca el JWT de administrador: el MCP es
exclusivamente para usuarios con acceso al chat (agentes), nunca para el admin.

El scoping de "mis propiedades" y de las escrituras se hace por los últimos 10
dígitos del teléfono del agente (== `agente_captador_telefono` normalizado).
"""

from dataclasses import dataclass
from typing import Optional

from src.services.db import get_db, fetch_one
from src.services.textutils import normalize_phone


@dataclass(frozen=True)
class AgentIdentity:
    """Identidad resuelta de un agente que consume el MCP."""
    user_id: int
    email: Optional[str]
    nombre: Optional[str]
    telefono: Optional[str]
    telefono_10: Optional[str]  # últimos 10 dígitos (llave de scoping)

    @property
    def has_inventory_scope(self) -> bool:
        """True si el agente tiene un teléfono con el que scoping de inventario
        propio es posible."""
        return bool(self.telefono_10)


# Consulta idéntica en espíritu a chat_auth.get_current_user, pero desacoplada
# del request de Flask: recibe el token directamente (el MCP no usa Flask).
_RESOLVE_SQL = """
    SELECT u.id, u.email, u.nombre, u.telefono
    FROM chat_users u
    JOIN chat_user_sessions s ON s.user_id = u.id
    WHERE s.token = %s
      AND s.activa = TRUE
      AND (s.fecha_expiracion IS NULL OR s.fecha_expiracion > NOW())
      AND u.activo = TRUE
    LIMIT 1
"""

_TOUCH_SQL = "UPDATE chat_user_sessions SET ultimo_uso = NOW() WHERE token = %s"


def resolve_agent(token: Optional[str], touch: bool = True) -> Optional[AgentIdentity]:
    """
    Resuelve un bearer token a una `AgentIdentity`, o None si el token es
    inválido / expirado / de un usuario inactivo.

    Args:
        token: el bearer token opaco enviado por el cliente MCP.
        touch: si True, actualiza `ultimo_uso` de la sesión (best-effort).
    """
    if not token or not token.strip():
        return None

    token = token.strip()
    with get_db() as db:
        row = fetch_one(db.cursor, _RESOLVE_SQL, (token,))
        if not row:
            return None
        if touch:
            try:
                db.cursor.execute(_TOUCH_SQL, (token,))
                db.conn.commit()
            except Exception:
                # El touch es cosmético; no debe tumbar la resolución.
                try:
                    db.conn.rollback()
                except Exception:
                    pass

    return AgentIdentity(
        user_id=row["id"],
        email=row.get("email"),
        nombre=row.get("nombre"),
        telefono=row.get("telefono"),
        telefono_10=normalize_phone(row.get("telefono")),
    )


_RESOLVE_BY_ID_SQL = """
    SELECT id, email, nombre, telefono
    FROM chat_users
    WHERE id = %s AND activo = TRUE
    LIMIT 1
"""


def resolve_agent_by_id(user_id) -> Optional[AgentIdentity]:
    """
    Resuelve un agente por su id de chat_user (usado con OAuth: el `subject` del
    access token es el user_id).
    """
    if user_id is None:
        return None
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    with get_db() as db:
        row = fetch_one(db.cursor, _RESOLVE_BY_ID_SQL, (user_id,))
    if not row:
        return None
    return AgentIdentity(
        user_id=row["id"],
        email=row.get("email"),
        nombre=row.get("nombre"),
        telefono=row.get("telefono"),
        telefono_10=normalize_phone(row.get("telefono")),
    )
