"""
Pagos en línea de los planes con Wompi (Web Checkout + eventos).

Flujo:
  1. `crear_pago(user_id, plan)`: fila 'pendiente' en `pagos` con referencia
     única y el link al checkout de Wompi (firma de integridad hecha aquí, el
     secreto nunca sale del backend).
  2. El agente paga (tarjeta, PSE, Nequi, Bancolombia) y Wompi lo devuelve a
     /chat/pago?ref=…&id=<transacción>.
  3. La confirmación llega por dos vías, ambas idempotentes:
     - `procesar_evento`: webhook `transaction.updated` con checksum verificado.
     - `verificar`: al volver, el front pregunta y consultamos la transacción
       a la API de Wompi (sirve en local y si el webhook se demora).
  4. `_aplicar`: con el pago bloqueado, valida monto/moneda/referencia y, si
     quedó APPROVED, activa el periodo del plan en la misma transacción.

Configuración (env): WOMPI_PUBLIC_KEY, WOMPI_PRIVATE_KEY, WOMPI_EVENTS_SECRET,
WOMPI_INTEGRITY_SECRET. El ambiente (sandbox/producción) sale del prefijo de las
llaves (pub_test_/pub_prod_…); si las cuatro no son del mismo ambiente, los pagos
quedan deshabilitados.
"""

import hashlib
import hmac
import json
import os
import secrets
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from src.services import suscripcion_service
from src.services.db import get_db, fetch_one, fetch_all

CHECKOUT_URL = "https://checkout.wompi.co/p/"
_API = {"sandbox": "https://sandbox.wompi.co/v1", "production": "https://production.wompi.co/v1"}

# Estado de Wompi → estado del pago. PENDING no cambia nada.
_ESTADOS = {"APPROVED": "aprobado", "DECLINED": "rechazado", "VOIDED": "anulado", "ERROR": "error"}
_FINALES = {"aprobado", "rechazado", "anulado", "error"}


class PagoError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


def _cfg(nombre: str) -> str:
    return (os.getenv(nombre) or "").strip()


_PREFIJOS = {
    "sandbox": ("pub_test_", "prv_test_", "test_events_", "test_integrity_"),
    "production": ("pub_prod_", "prv_prod_", "prod_events_", "prod_integrity_"),
}
_LLAVES = ("WOMPI_PUBLIC_KEY", "WOMPI_PRIVATE_KEY", "WOMPI_EVENTS_SECRET", "WOMPI_INTEGRITY_SECRET")


def ambiente() -> Optional[str]:
    """'sandbox' o 'production' según el prefijo de las 4 llaves; None si falta
    alguna o mezclan ambientes (nunca operar con llaves cruzadas)."""
    valores = [_cfg(n) for n in _LLAVES]
    for nombre, prefijos in _PREFIJOS.items():
        if all(v.startswith(pre) for v, pre in zip(valores, prefijos)):
            return nombre
    return None


def habilitado() -> bool:
    return ambiente() is not None


def _api() -> str:
    return _API[ambiente() or "sandbox"]


def _frontend() -> str:
    return os.getenv("FYNDER_FRONTEND_URL", "https://fyndercol.netlify.app").rstrip("/")


def firma_integridad(referencia: str, monto_centavos: int, moneda: str = "COP") -> str:
    texto = f"{referencia}{monto_centavos}{moneda}{_cfg('WOMPI_INTEGRITY_SECRET')}"
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _salida(pago: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "referencia": pago["referencia"],
        "plan": pago["plan_codigo"],
        "plan_nombre": pago.get("plan_nombre"),
        "monto_cop": pago["monto_cop"],
        "estado": pago["estado"],
        "metodo": pago.get("metodo"),
        "creado": pago["created_at"].isoformat() if pago.get("created_at") else None,
        "llaves": pago.get("llaves"),
        "vence": pago["vence"].isoformat() if pago.get("vence") else None,
    }


# ---------------------------------------------------------------------------
# 1. Crear el pago
# ---------------------------------------------------------------------------

def crear_pago(user_id: int, plan_codigo: str, frontend: Optional[str] = None) -> Dict[str, Any]:
    if not habilitado():
        raise PagoError("no_disponible", "Los pagos en línea no están disponibles en este momento.")
    with get_db() as db:
        cur = db.cursor
        plan = fetch_one(cur, """
            SELECT codigo, nombre, precio_cop FROM planes
            WHERE codigo = %s AND activo AND codigo <> 'prueba' AND precio_cop > 0
        """, (plan_codigo,))
        if not plan:
            raise PagoError("invalido", "Ese plan no existe o no está disponible.")
        usuario = fetch_one(cur, "SELECT id, nombre, email, telefono, activo FROM chat_users WHERE id = %s",
                            (user_id,))
        if not usuario or not usuario.get("activo"):
            raise PagoError("no_encontrado", "Usuario no encontrado.")
        referencia = f"FY{user_id}-{plan['codigo'][:3].upper()}-{secrets.token_hex(5).upper()}"
        cur.execute("""
            INSERT INTO pagos (referencia, user_id, plan_codigo, monto_cop)
            VALUES (%s, %s, %s, %s)
        """, (referencia, user_id, plan["codigo"], plan["precio_cop"]))
        db.conn.commit()

    centavos = int(plan["precio_cop"]) * 100
    base = (frontend or _frontend()).rstrip("/")
    params = {
        "public-key": _cfg("WOMPI_PUBLIC_KEY"),
        "currency": "COP",
        "amount-in-cents": centavos,
        "reference": referencia,
        "signature:integrity": firma_integridad(referencia, centavos),
    }
    # El firewall del checkout de Wompi rechaza (403) una redirect-url a
    # localhost: en desarrollo el checkout se abre en otra pestaña sin regreso
    # y la web espera el resultado en /chat/pago.
    local = base.startswith(("http://localhost", "http://127.0.0.1"))
    if not local:
        params["redirect-url"] = f"{base}/chat/pago?ref={referencia}"
    if usuario.get("email"):
        params["customer-data:email"] = usuario["email"]
    if usuario.get("nombre"):
        params["customer-data:full-name"] = usuario["nombre"]
    return {
        "ok": True,
        "referencia": referencia,
        "plan": plan["codigo"],
        "plan_nombre": plan["nombre"],
        "monto_cop": plan["precio_cop"],
        "checkout_url": f"{CHECKOUT_URL}?{urlencode(params)}",
        "sin_redireccion": local,
    }


# ---------------------------------------------------------------------------
# 2. Aplicar una transacción de Wompi a nuestro pago (idempotente)
# ---------------------------------------------------------------------------

def _aplicar(tx: Dict[str, Any], fuente: str) -> Dict[str, Any]:
    referencia = tx.get("reference")
    if not referencia:
        return {"ok": False, "error": "sin_referencia"}
    nuevo = _ESTADOS.get(str(tx.get("status") or "").upper())
    with get_db() as db:
        cur = db.cursor
        pago = fetch_one(cur, "SELECT * FROM pagos WHERE referencia = %s FOR UPDATE", (referencia,))
        if not pago:
            return {"ok": False, "error": "desconocido"}
        # Un aprobado es definitivo; un rechazo/error aún puede pasar a aprobado
        # si el agente reintenta en el mismo checkout.
        if nuevo is None or pago["estado"] == "aprobado" or (pago["estado"] in _FINALES and nuevo != "aprobado"):
            db.conn.rollback()
            return {"ok": True, "estado": pago["estado"], "sin_cambios": True}

        detalle = json.dumps({"fuente": fuente, "tx": tx}, default=str)
        esperado = int(pago["monto_cop"]) * 100
        if nuevo == "aprobado" and (int(tx.get("amount_in_cents") or 0) != esperado
                                    or (tx.get("currency") or "COP") != "COP"):
            # Nunca activar por un monto distinto al del plan: queda para revisión.
            cur.execute("""
                UPDATE pagos SET estado = 'error', transaccion_id = %s, metodo = %s,
                       detalle = %s, updated_at = NOW() WHERE id = %s
            """, (tx.get("id"), tx.get("payment_method_type"), detalle, pago["id"]))
            db.conn.commit()
            print(f"⚠️ Pago {referencia}: monto {tx.get('amount_in_cents')} ≠ esperado {esperado}")
            return {"ok": False, "error": "monto_no_coincide", "estado": "error"}

        suscripcion_id = None
        if nuevo == "aprobado":
            res = suscripcion_service.activar_plan_en(
                cur, pago["user_id"], pago["plan_codigo"], referencia_pago=referencia,
                notas=f"Wompi {tx.get('payment_method_type') or ''} {tx.get('id') or ''}".strip(),
                admin="wompi", precio_cop=pago["monto_cop"])
            suscripcion_id = res["suscripcion_id"]
        cur.execute("""
            UPDATE pagos SET estado = %s, transaccion_id = %s, metodo = %s,
                   suscripcion_id = %s, detalle = %s, updated_at = NOW()
            WHERE id = %s
        """, (nuevo, tx.get("id"), tx.get("payment_method_type"), suscripcion_id, detalle, pago["id"]))
        db.conn.commit()
    print(f"💳 Pago {referencia} → {nuevo} ({fuente})")
    return {"ok": True, "estado": nuevo, "suscripcion_id": suscripcion_id}


# ---------------------------------------------------------------------------
# 3a. Webhook de eventos
# ---------------------------------------------------------------------------

def _valor(data: Dict[str, Any], ruta: str) -> Any:
    actual: Any = data
    for parte in ruta.split("."):
        actual = actual.get(parte) if isinstance(actual, dict) else None
    return actual


def checksum_valido(evento: Dict[str, Any], header: Optional[str] = None) -> bool:
    secreto = _cfg("WOMPI_EVENTS_SECRET")
    firma = evento.get("signature") or {}
    props = firma.get("properties") or []
    recibido = (header or firma.get("checksum") or "").strip()
    if not secreto or not props or not recibido:
        return False
    data = evento.get("data") or {}
    texto = "".join(str(_valor(data, p)) for p in props) + str(evento.get("timestamp", "")) + secreto
    calculado = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    return hmac.compare_digest(calculado.upper(), recibido.upper())


def procesar_evento(evento: Dict[str, Any], header_checksum: Optional[str] = None) -> Dict[str, Any]:
    if not checksum_valido(evento, header_checksum):
        return {"ok": False, "error": "firma_invalida"}
    if evento.get("event") != "transaction.updated":
        return {"ok": True, "ignorado": evento.get("event")}
    tx = (evento.get("data") or {}).get("transaction") or {}
    return _aplicar(tx, "evento")


# ---------------------------------------------------------------------------
# 3b. Verificación al volver del checkout
# ---------------------------------------------------------------------------

def _consultar_transaccion(transaccion_id: str) -> Optional[Dict[str, Any]]:
    r = requests.get(f"{_api()}/transactions/{transaccion_id}",
                     headers={"Authorization": f"Bearer {_cfg('WOMPI_PRIVATE_KEY')}"}, timeout=15)
    if r.status_code != 200:
        return None
    return (r.json() or {}).get("data")


def _consultar_por_referencia(referencia: str) -> Optional[Dict[str, Any]]:
    r = requests.get(f"{_api()}/transactions", params={"reference": referencia},
                     headers={"Authorization": f"Bearer {_cfg('WOMPI_PRIVATE_KEY')}"}, timeout=15)
    if r.status_code != 200:
        return None
    datos = (r.json() or {}).get("data") or []
    # Si hubo varios intentos con la misma referencia, gana el aprobado.
    for tx in datos:
        if tx.get("status") == "APPROVED":
            return tx
    return datos[0] if datos else None


def verificar(user_id: int, referencia: str, transaccion_id: Optional[str] = None) -> Dict[str, Any]:
    """Estado de un pago del usuario; si sigue pendiente, se lo pregunta a Wompi."""
    with get_db() as db:
        pago = fetch_one(db.cursor, """
            SELECT pg.*, p.nombre AS plan_nombre, p.desbloqueos_mes AS llaves, s.fin AS vence
            FROM pagos pg JOIN planes p ON p.codigo = pg.plan_codigo
            LEFT JOIN suscripciones s ON s.id = pg.suscripcion_id
            WHERE pg.referencia = %s AND pg.user_id = %s
        """, (referencia, user_id))
    if not pago:
        raise PagoError("no_encontrado", "No encontramos ese pago.")

    if pago["estado"] == "pendiente" and habilitado():
        try:
            tx = _consultar_transaccion(transaccion_id) if transaccion_id else None
            if not tx or tx.get("reference") != referencia:
                tx = _consultar_por_referencia(referencia)
            if tx and tx.get("reference") == referencia:
                _aplicar(tx, "verificacion")
        except requests.RequestException as e:
            print(f"⚠️ No se pudo consultar Wompi para {referencia}: {e}")
        with get_db() as db:
            pago = fetch_one(db.cursor, """
                SELECT pg.*, p.nombre AS plan_nombre, p.desbloqueos_mes AS llaves, s.fin AS vence
            FROM pagos pg JOIN planes p ON p.codigo = pg.plan_codigo
            LEFT JOIN suscripciones s ON s.id = pg.suscripcion_id
                WHERE pg.referencia = %s
            """, (referencia,))
    return {"ok": True, **_salida(pago)}


def historial(user_id: int, limit: int = 12) -> list:
    with get_db() as db:
        filas = fetch_all(db.cursor, """
            SELECT pg.*, p.nombre AS plan_nombre, p.desbloqueos_mes AS llaves, s.fin AS vence
            FROM pagos pg JOIN planes p ON p.codigo = pg.plan_codigo
            LEFT JOIN suscripciones s ON s.id = pg.suscripcion_id
            WHERE pg.user_id = %s AND pg.estado <> 'pendiente'
            ORDER BY pg.created_at DESC LIMIT %s
        """, (user_id, limit))
    return [_salida(f) for f in filas]
