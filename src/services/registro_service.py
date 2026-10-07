"""
Registro autogestionado de agentes en la web y verificación del celular.

- `registrar`: crea la cuenta (origen='web') con clave, celular SIN verificar y
  términos aceptados. El celular declarado no da nada hasta verificarlo.
- `enviar_codigo` / `verificar_codigo`: código de 6 dígitos por WhatsApp
  (UltraMSG). Al verificar, el celular queda `telefono_verificado` y se otorgan
  los créditos de prueba (uno por teléfono, ver `asegurar_prueba`).

Reglas:
  - Un celular verificado pertenece a UNA cuenta activa: "propio" y "mis
    propiedades" se deciden por él, así que nunca se verifica un número que ya
    está verificado en otra cuenta.
  - El código se guarda como hash, vence en 10 min y admite 5 intentos.
  - Límites de envío: 3 por cuenta por hora y 5 por número por día.
"""

import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from typing import Any, Dict, Optional

from src.services import suscripcion_service
from src.services.db import get_db, fetch_one, scalar
from src.services.textutils import normalize_phone
from src.services.whatsapp_sender import WhatsAppSendError, enviar_whatsapp

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_CLAVE = 8
VIGENCIA_CODIGO = timedelta(minutes=10)
MAX_INTENTOS = 5
MAX_ENVIOS_HORA_USUARIO = 3
MAX_ENVIOS_DIA_TELEFONO = 5
DIAS_SESION = 30


class RegistroError(Exception):
    def __init__(self, codigo: str, mensaje: str, campo: Optional[str] = None):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.campo = campo


def _celular(telefono: Optional[str]) -> str:
    """+57XXXXXXXXXX de un celular colombiano o RegistroError."""
    tel10 = normalize_phone(telefono or "")
    if not tel10 or len(tel10) != 10 or not tel10.startswith("3"):
        raise RegistroError("invalido", "Escribe un celular colombiano de 10 dígitos (empieza por 3).", "telefono")
    return "+57" + tel10


def _hash(user_id: int, codigo: str) -> str:
    return hashlib.sha256(f"{user_id}:{codigo}".encode()).hexdigest()


def _telefono_en_otra_cuenta(cur, telefono: str, user_id: Optional[int]) -> bool:
    tel10 = telefono[-10:]
    return bool(scalar(cur, """
        SELECT 1 FROM chat_users
        WHERE activo AND telefono_verificado AND id <> %s
          AND RIGHT(REGEXP_REPLACE(COALESCE(telefono, ''), '[^0-9]', '', 'g'), 10) = %s
        LIMIT 1
    """, (user_id or 0, tel10)))


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

def registrar(nombre: str, email: str, clave: str, telefono: str, acepta_terminos: bool) -> Dict[str, Any]:
    nombre = " ".join((nombre or "").split())
    email = (email or "").strip().lower()
    if len(nombre) < 3:
        raise RegistroError("invalido", "Escribe tu nombre completo.", "nombre")
    if not _EMAIL_RE.match(email) or len(email) > 120:
        raise RegistroError("invalido", "Escribe un correo válido.", "email")
    if len(clave or "") < MIN_CLAVE:
        raise RegistroError("invalido", f"La clave debe tener al menos {MIN_CLAVE} caracteres.", "clave")
    tel = _celular(telefono)
    if not acepta_terminos:
        raise RegistroError("invalido", "Para crear tu cuenta debes aceptar los términos y el tratamiento de datos.", "terminos")

    with get_db() as db:
        cur = db.cursor
        if scalar(cur, "SELECT 1 FROM chat_users WHERE lower(email) = %s", (email,)):
            raise RegistroError("duplicado", "Ya hay una cuenta con este correo. Entra con tu clave o recupérala.", "email")
        if _telefono_en_otra_cuenta(cur, tel, None):
            raise RegistroError("duplicado", "Este celular ya está en una cuenta de Fynder. Entra con ella o escríbenos.", "telefono")
        cur.execute("""
            INSERT INTO chat_users (email, nombre, password_hash, telefono, activo, origen,
                                    telefono_verificado, terminos_aceptados_at, terminos_version)
            VALUES (%s, %s, crypt(%s, gen_salt('bf')), %s, TRUE, 'web', FALSE, NOW(), %s)
            RETURNING id
        """, (email, nombre, clave, tel, suscripcion_service.TERMINOS_VERSION))
        user_id = cur.fetchone()["id"]
        db.conn.commit()
    print(f"🆕 Registro web: usuario {user_id}")
    return {"ok": True, "user_id": user_id, "email": email}


# ---------------------------------------------------------------------------
# Verificación del celular
# ---------------------------------------------------------------------------

def enviar_codigo(user_id: int, telefono: Optional[str] = None) -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        usuario = fetch_one(cur, "SELECT id, telefono, telefono_verificado, activo FROM chat_users WHERE id = %s",
                            (user_id,))
        if not usuario or not usuario["activo"]:
            raise RegistroError("no_encontrado", "Usuario no encontrado.")
        if usuario["telefono_verificado"]:
            raise RegistroError("ya_verificado", "Tu celular ya está verificado.")
        tel = _celular(telefono or usuario.get("telefono"))
        if _telefono_en_otra_cuenta(cur, tel, user_id):
            raise RegistroError("duplicado", "Este celular ya está verificado en otra cuenta de Fynder. Escríbenos si es tuyo.", "telefono")

        envios_hora = scalar(cur, """
            SELECT COUNT(*) FROM codigos_telefono WHERE user_id = %s AND created_at > NOW() - INTERVAL '1 hour'
        """, (user_id,)) or 0
        envios_tel = scalar(cur, """
            SELECT COUNT(*) FROM codigos_telefono WHERE telefono = %s AND created_at > NOW() - INTERVAL '1 day'
        """, (tel,)) or 0
        if envios_hora >= MAX_ENVIOS_HORA_USUARIO or envios_tel >= MAX_ENVIOS_DIA_TELEFONO:
            raise RegistroError("limite", "Ya pediste varios códigos. Espera un rato e inténtalo de nuevo.")

        codigo = f"{secrets.randbelow(1_000_000):06d}"
        # Un código nuevo invalida los anteriores.
        cur.execute("UPDATE codigos_telefono SET usado_at = NOW() WHERE user_id = %s AND usado_at IS NULL", (user_id,))
        cur.execute("""
            INSERT INTO codigos_telefono (user_id, telefono, codigo_hash, expira_at)
            VALUES (%s, %s, %s, NOW() + %s)
        """, (user_id, tel, _hash(user_id, codigo), VIGENCIA_CODIGO))
        if tel != usuario.get("telefono"):
            cur.execute("UPDATE chat_users SET telefono = %s WHERE id = %s", (tel, user_id))
        db.conn.commit()

    try:
        enviar_whatsapp(tel, f"Tu código de Fynder es *{codigo}*.\n\nVence en 10 minutos. "
                             "Si no lo pediste, ignora este mensaje.")
    except WhatsAppSendError as e:
        print(f"⚠️ No se pudo enviar el código a usuario {user_id}: {e}")
        raise RegistroError("envio", "No pudimos enviar el WhatsApp. Revisa el número o intenta en un momento.")
    return {"ok": True, "telefono": tel, "vence_minutos": int(VIGENCIA_CODIGO.total_seconds() // 60)}


def verificar_codigo(user_id: int, codigo: str) -> Dict[str, Any]:
    codigo = re.sub(r"\D", "", codigo or "")
    if len(codigo) != 6:
        raise RegistroError("invalido", "El código tiene 6 dígitos.", "codigo")
    with get_db() as db:
        cur = db.cursor
        fila = fetch_one(cur, """
            SELECT * FROM codigos_telefono
            WHERE user_id = %s AND usado_at IS NULL AND expira_at > NOW()
            ORDER BY created_at DESC LIMIT 1 FOR UPDATE
        """, (user_id,))
        if not fila:
            raise RegistroError("vencido", "El código venció. Pide uno nuevo.")
        if fila["intentos"] >= MAX_INTENTOS:
            raise RegistroError("limite", "Demasiados intentos. Pide un código nuevo.")
        if not hmac.compare_digest(fila["codigo_hash"], _hash(user_id, codigo)):
            cur.execute("UPDATE codigos_telefono SET intentos = intentos + 1 WHERE id = %s", (fila["id"],))
            db.conn.commit()
            quedan = MAX_INTENTOS - fila["intentos"] - 1
            raise RegistroError("incorrecto", "El código no coincide." + (f" Te quedan {quedan} intentos." if quedan else ""), "codigo")
        if _telefono_en_otra_cuenta(cur, fila["telefono"], user_id):
            raise RegistroError("duplicado", "Este celular ya está verificado en otra cuenta de Fynder. Escríbenos si es tuyo.")

        cur.execute("UPDATE codigos_telefono SET usado_at = NOW() WHERE id = %s", (fila["id"],))
        cur.execute("""
            UPDATE chat_users SET telefono = %s, telefono_verificado = TRUE, telefono_verificado_at = NOW()
            WHERE id = %s
        """, (fila["telefono"], user_id))
        usuario = fetch_one(cur, """
            SELECT id, telefono, telefono_verificado, origen, acceso_entregado FROM chat_users WHERE id = %s
        """, (user_id,))
        suscripcion_service.asegurar_prueba(cur, usuario)
        db.conn.commit()
    estado = suscripcion_service.estado(user_id)
    print(f"✅ Celular verificado: usuario {user_id}")
    return {"ok": True, "telefono": fila["telefono"], "disponibles": estado.get("disponibles", 0)}
