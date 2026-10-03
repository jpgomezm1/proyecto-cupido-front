"""
Auto-registro (self-service) para el MCP de Fynder.

Permite que un agente que NO tiene acceso al chat obtenga por sí mismo un
"código de acceso" (bearer token MCP) para conectar Fynder a su proveedor de IA
(Claude, etc.). Crea un `chat_user` de tipo MCP (con un password placeholder
inutilizable — el usuario nunca inicia sesión con contraseña, solo usa el token)
y emite el token sobre `chat_user_sessions` (tipo='mcp').

Gate opcional por código de invitación vía `MCP_SIGNUP_CODE`. Si la variable
`MCP_SIGNUP_ENABLED` está en 'false', el alta se desactiva.

Seguridad: un correo que ya existe NUNCA recibe un token por aquí (se conecta con
OAuth, con su clave). El celular declarado queda SIN verificar: no da acceso al
inventario de nadie ni créditos de prueba hasta que Fynder lo verifique.
"""

import hashlib
import os
import re
import secrets
from typing import Any, Dict, Optional

from src.services.db import get_db, fetch_one
from src.services.textutils import normalize_phone
from src.services.suscripcion_service import TERMINOS_VERSION

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupError(Exception):
    """Error de negocio en el auto-registro (validación, gate, duplicado)."""


def _signup_enabled() -> bool:
    return os.getenv("MCP_SIGNUP_ENABLED", "true").strip().lower() != "false"


def _placeholder_password_hash() -> str:
    # Hash aleatorio: no corresponde a ninguna contraseña conocida, así que el
    # login por contraseña es imposible. El acceso es solo por token MCP.
    return "mcp$" + hashlib.sha256(secrets.token_bytes(32)).hexdigest()


def self_register(nombre: str, email: str, telefono: Optional[str] = None,
                  invite_code: Optional[str] = None,
                  acepta_terminos: bool = False,
                  label: str = "Auto-registro MCP") -> Dict[str, Any]:
    """
    Crea un usuario NUEVO y emite un token MCP. Si el correo ya existe, falla:
    emitir un token sin contraseña permitiría que cualquiera que conozca un
    correo gaste los desbloqueos de otro.
    """
    if not _signup_enabled():
        raise SignupError("El auto-registro está temporalmente deshabilitado.")

    required_code = os.getenv("MCP_SIGNUP_CODE")
    if required_code and (invite_code or "").strip() != required_code:
        raise SignupError("Código de invitación inválido.")

    nombre = (nombre or "").strip()
    email = (email or "").strip().lower()
    if len(nombre) < 2:
        raise SignupError("Ingresa tu nombre completo.")
    if not _EMAIL_RE.match(email):
        raise SignupError("Ingresa un correo electrónico válido.")

    if not acepta_terminos:
        raise SignupError("Debes aceptar los términos de Fynder para continuar.")

    tel_norm = None
    if telefono:
        tel_norm = normalize_phone(telefono)
        if not tel_norm or len(tel_norm) != 10:
            raise SignupError("El celular no es válido (10 dígitos).")
        telefono = "+57" + tel_norm  # formato canónico de chat_users

    token = secrets.token_urlsafe(64)

    with get_db() as db:
        existing = fetch_one(db.cursor,
            "SELECT id, nombre, telefono, activo FROM chat_users WHERE email = %s", (email,))

        if existing:
            raise SignupError(
                "Ya tienes una cuenta con este correo. Conecta Fynder desde tu IA con "
                "\"Iniciar sesión\" (tu correo y tu clave de Fynder). Si no recuerdas tu "
                "clave, escríbenos y te ayudamos.")

        db.cursor.execute("""
            INSERT INTO chat_users (email, password_hash, nombre, telefono, activo,
                                    telefono_verificado, terminos_aceptados_at, terminos_version)
            VALUES (%s, %s, %s, %s, TRUE, FALSE, NOW(), %s)
            RETURNING id
        """, (email, _placeholder_password_hash(), nombre, telefono, TERMINOS_VERSION))
        user_id = db.cursor.fetchone()["id"]
        is_new = True

        db.cursor.execute("""
            INSERT INTO chat_user_sessions (token, user_id, tipo, label, activa, fecha_expiracion)
            VALUES (%s, %s, 'mcp', %s, TRUE, NULL)
        """, (token, user_id, label))
        db.conn.commit()

    return {
        "ok": True,
        "token": token,
        "user_id": user_id,
        "nombre": nombre,
        "email": email,
        # El celular queda pendiente de verificación por Fynder.
        "tiene_scope_inventario": False,
        "telefono_pendiente_verificacion": bool(tel_norm),
        "is_new": is_new,
    }


def issue_token_for_user(user_id: int, label: str = "Portal Fynder") -> str:
    """
    Emite un token MCP para un usuario YA autenticado (ej. un agente logueado en
    el portal de chat). No crea usuario ni pide datos: solo genera la sesión MCP.
    Devuelve el bearer token.
    """
    token = secrets.token_urlsafe(64)
    with get_db() as db:
        db.cursor.execute("""
            INSERT INTO chat_user_sessions (token, user_id, tipo, label, activa, fecha_expiracion)
            VALUES (%s, %s, 'mcp', %s, TRUE, NULL)
        """, (token, user_id, label))
        db.conn.commit()
    return token
