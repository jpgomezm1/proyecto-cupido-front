"""
Cuenta del agente: soporte desde la app y cierre de la cuenta.

- `crear_soporte`: guarda el mensaje (soporte_solicitudes), lo manda al buzón
  del equipo y le confirma al agente con su número de caso.
- `eliminar`: el agente cierra su cuenta (derecho de supresión, Ley 1581).
  Pide la clave actual y la palabra ELIMINAR. Desactiva la cuenta, cierra todas
  sus sesiones (web y MCP), revoca los refresh tokens de OAuth y borra los datos
  personales (nombre, correo, celular). Se conservan los registros contables
  (pagos, suscripciones, desbloqueos) sin datos que identifiquen a la persona.
  El correo de confirmación sale ANTES de borrar el correo.
"""

import secrets
from typing import Any, Dict, Optional

from src.services import correo_service
from src.services.db import get_db, fetch_one, scalar

MAX_SOPORTE_DIA = 10


class CuentaError(Exception):
    def __init__(self, codigo: str, mensaje: str, campo: Optional[str] = None):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.campo = campo


def crear_soporte(user_id: int, categoria: str, asunto: str, mensaje: str) -> Dict[str, Any]:
    categoria = (categoria or "otro").strip().lower()
    if categoria not in correo_service.CATEGORIAS_SOPORTE:
        categoria = "otro"
    asunto = " ".join((asunto or "").split())[:160]
    mensaje = (mensaje or "").strip()[:5000]
    if len(asunto) < 4:
        raise CuentaError("invalido", "Escribe un asunto corto.", "asunto")
    if len(mensaje) < 10:
        raise CuentaError("invalido", "Cuéntanos un poco más (mínimo 10 caracteres).", "mensaje")
    with get_db() as db:
        cur = db.cursor
        usuario = fetch_one(cur, "SELECT id, nombre, email, telefono, telefono_verificado FROM chat_users WHERE id = %s AND activo",
                            (user_id,))
        if not usuario:
            raise CuentaError("no_encontrado", "Usuario no encontrado.")
        hoy = scalar(cur, "SELECT COUNT(*) FROM soporte_solicitudes WHERE user_id = %s AND created_at > NOW() - INTERVAL '1 day'",
                     (user_id,)) or 0
        if hoy >= MAX_SOPORTE_DIA:
            raise CuentaError("limite", "Ya nos escribiste varias veces hoy. Te respondemos pronto.")
        cur.execute("""
            INSERT INTO soporte_solicitudes (user_id, categoria, asunto, mensaje)
            VALUES (%s, %s, %s, %s) RETURNING id
        """, (user_id, categoria, asunto, mensaje))
        ticket = cur.fetchone()["id"]
        db.conn.commit()
    correo_service.soporte_nuevo(ticket, usuario, categoria, asunto, mensaje)
    correo_service.soporte_recibido(usuario["nombre"], usuario["email"], ticket, categoria, asunto, mensaje)
    return {"ok": True, "caso": ticket}


def eliminar(user_id: int, clave: str, confirmacion: str, motivo: Optional[str] = None) -> Dict[str, Any]:
    if (confirmacion or "").strip().upper() != "ELIMINAR":
        raise CuentaError("invalido", "Escribe ELIMINAR para confirmar.", "confirmacion")
    with get_db() as db:
        cur = db.cursor
        usuario = fetch_one(cur, """
            SELECT id, nombre, email FROM chat_users
            WHERE id = %s AND activo AND password_hash = crypt(%s, password_hash)
        """, (user_id, clave or ""))
        if not usuario:
            raise CuentaError("clave", "La clave no es correcta.", "clave")
        nombre, email = usuario["nombre"], usuario["email"]
        cur.execute("UPDATE chat_user_sessions SET activa = FALSE WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM oauth_refresh_tokens WHERE user_id = %s", (user_id,))
        cur.execute("UPDATE codigos_telefono SET usado_at = COALESCE(usado_at, NOW()) WHERE user_id = %s", (user_id,))
        cur.execute("""
            UPDATE chat_users
            SET activo = FALSE, eliminada_at = NOW(),
                nombre = 'Cuenta eliminada', email = %s, correo_personal = NULL,
                telefono = NULL, telefono_verificado = FALSE, telefono_verificado_at = NULL,
                password_hash = %s
            WHERE id = %s
        """, (f"eliminada-{user_id}-{secrets.token_hex(4)}@fynder.invalid", "x$" + secrets.token_hex(32), user_id))
        if motivo:
            cur.execute("INSERT INTO chat_usage_log (user_id, accion, detalles) VALUES (%s, 'cuenta_eliminada', %s)",
                        (user_id, '{"motivo": ' + _json_str(motivo[:500]) + "}"))
        db.conn.commit()
    print(f"🗑️ Cuenta {user_id} cerrada por el agente")
    correo_service.cuenta_eliminada(nombre, email)
    return {"ok": True}


def _json_str(s: str) -> str:
    import json
    return json.dumps(s, ensure_ascii=False)
