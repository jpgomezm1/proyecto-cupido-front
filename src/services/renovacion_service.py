"""
Renovación automática con tarjeta: el débito automático de los planes (migración 067, R19).

La tarjeta la captura el widget de Wompi en modo tokenize (el agente la escribe dentro del widget;
Fynder nunca la ve) y devuelve un token. Con ese token y las aceptaciones de Wompi el backend crea una
fuente de pago (POST /v1/payment_sources, llave privada) y guarda solo su id, la marca y los últimos 4.

  activar(user_id, plan, token, acepta)   guarda la tarjeta; si no tiene plan vigente, cobra el primer mes ya
  cobrar(medio_id)                        un cobro con la fuente (POST /v1/transactions, recurrent = true);
                                          el resultado entra por pagos_service._aplicar como cualquier pago
  renovar()                               el worker: cobra un día antes de que venza el plan; si el banco
                                          rechaza, reintenta cada 24 h hasta 3 veces y luego pausa y avisa
  cancelar(user_id)                       sin permanencia: deja de cobrar (el plan vigente sigue hasta su fin)

Probado contra el sandbox de Wompi: fuente AVAILABLE y cobro recurrente APPROVED.
"""

import secrets
import time
from datetime import timedelta
from typing import Any, Dict, Optional

import requests

from src.services import correo_service, pagos_service as pagos, suscripcion_service
from src.services.db import fetch_all, fetch_one, get_db

ANTES_DE_VENCER = timedelta(hours=24)     # cuándo se cobra la renovación
ENTRE_INTENTOS = timedelta(hours=24)
INTENTOS = 3
_ACEPTACION: Dict[str, Any] = {}          # caché de los tokens de aceptación de Wompi (1 h)


class RenovacionError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def _privada() -> Dict[str, str]:
    return {"Authorization": f"Bearer {pagos._cfg('WOMPI_PRIVATE_KEY')}"}


def aceptacion() -> Dict[str, Any]:
    """Los dos tokens de aceptación de Wompi (reglamento y tratamiento de datos) con sus documentos."""
    if _ACEPTACION.get("en", 0) > time.time() - 3600:
        return _ACEPTACION["datos"]
    m = requests.get(f"{pagos._api()}/merchants/{pagos._cfg('WOMPI_PUBLIC_KEY')}", timeout=15).json()["data"]
    acc, pers = m["presigned_acceptance"], m.get("presigned_personal_data_auth") or {}
    datos = {"acceptance_token": acc["acceptance_token"], "permalink": acc.get("permalink"),
             "datos_token": pers.get("acceptance_token"), "datos_permalink": pers.get("permalink")}
    _ACEPTACION.update(en=time.time(), datos=datos)
    return datos


def _marca(bin_: Optional[str]) -> str:
    b = str(bin_ or "")
    return "Visa" if b.startswith("4") else "Mastercard" if b[:1] in ("2", "5") else "Tarjeta"


def _plan(cur, user_id: int, plan_codigo: str) -> Dict[str, Any]:
    plan = fetch_one(cur, "SELECT codigo, nombre, precio_cop, activo, tipo FROM planes WHERE codigo = %s",
                     (plan_codigo,))
    if not plan or plan["codigo"] == "prueba" or plan.get("tipo") in ("paquete", "fotos", "complemento"):
        raise RenovacionError("invalido", "Ese plan no se puede renovar automáticamente.")
    if plan["codigo"] == "fundador":
        from src.services import fundador_service
        if fundador_service.estado_de(cur, user_id) is None:
            raise RenovacionError("invalido", "El plan Fundador no está a la venta.")
    elif not plan["activo"] or not plan["precio_cop"]:
        raise RenovacionError("invalido", "Ese plan no está disponible.")
    return plan


def _vence(cur, user_id: int):
    """Fin del último periodo de plan activo (None si no tiene)."""
    f = fetch_one(cur, """SELECT MAX(fin) AS fin FROM suscripciones
                          WHERE user_id = %s AND estado = 'activa' AND gracia_hasta > NOW()""", (user_id,))
    return f["fin"] if f else None


def estado(user_id: int) -> Dict[str, Any]:
    with get_db() as db:
        m = fetch_one(db.cursor, """
            SELECT m.id, m.marca, m.ultimos4, m.estado, m.plan_codigo, p.nombre AS plan_nombre, p.precio_cop
            FROM medios_pago m JOIN planes p ON p.codigo = m.plan_codigo
            WHERE m.user_id = %s ORDER BY m.created_at DESC LIMIT 1
        """, (user_id,))
        vence = _vence(db.cursor, user_id)
    if not m or m["estado"] == "cancelada":
        return {"activa": False, "habilitada": pagos.habilitado()}
    proximo = (vence - ANTES_DE_VENCER) if vence else None
    return {"activa": m["estado"] == "activa", "pausada": m["estado"] == "fallida", "habilitada": pagos.habilitado(),
            "tarjeta": f"{m['marca']} ••{m['ultimos4']}", "plan": m["plan_codigo"], "plan_nombre": m["plan_nombre"],
            "monto_cop": m["precio_cop"], "proximo_cobro": proximo.isoformat() if proximo else None}


def activar(user_id: int, plan_codigo: str, token: str, acepta: bool) -> Dict[str, Any]:
    if not pagos.habilitado():
        raise RenovacionError("no_disponible", "Los pagos en línea no están disponibles en este momento.")
    if not acepta:
        raise RenovacionError("sin_autorizacion", "Para activarla debes autorizar el cobro mensual.")
    token = (token or "").strip()
    if not token.startswith("tok_"):
        raise RenovacionError("invalido", "No recibimos la tarjeta. Intenta de nuevo.")
    with get_db() as db:
        plan = _plan(db.cursor, user_id, (plan_codigo or "").strip().lower())
        u = fetch_one(db.cursor, "SELECT nombre, email FROM chat_users WHERE id = %s AND activo", (user_id,))
    if not u or not u.get("email"):
        raise RenovacionError("no_encontrado", "Usuario no encontrado.")

    acc = aceptacion()
    cuerpo = {"type": "CARD", "token": token, "customer_email": u["email"], "acceptance_token": acc["acceptance_token"]}
    if acc.get("datos_token"):
        cuerpo["accept_personal_auth"] = acc["datos_token"]
    r = requests.post(f"{pagos._api()}/payment_sources", headers=_privada(), json=cuerpo, timeout=20)
    fuente = (r.json() or {}).get("data") or {}
    if r.status_code >= 400 or fuente.get("status") != "AVAILABLE":
        pagos._avisar(f"Wompi no creó la fuente de pago del usuario {user_id}: {r.status_code} {str(r.text)[:200]}")
        raise RenovacionError("tarjeta", "Wompi no pudo guardar esa tarjeta. Revisa los datos o prueba con otra.")
    pub = fuente.get("public_data") or {}

    with get_db() as db:
        cur = db.cursor
        cur.execute("UPDATE medios_pago SET estado = 'cancelada', cancelada_at = NOW() WHERE user_id = %s AND estado <> 'cancelada'",
                    (user_id,))
        medio_id = fetch_one(cur, """
            INSERT INTO medios_pago (user_id, fuente_id, marca, ultimos4, plan_codigo)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (user_id, int(fuente["id"]), _marca(pub.get("bin")), pub.get("last_four"), plan["codigo"]))["id"]
        vence = _vence(cur, user_id)
        db.conn.commit()

    cobro = None if vence else cobrar(medio_id)     # sin plan vigente: el primer mes se cobra ya
    res = estado(user_id)
    try:
        correo_service.renovacion_activada(u["nombre"], u["email"], plan["nombre"], plan["precio_cop"],
                                           res.get("tarjeta") or "tu tarjeta", res.get("proximo_cobro"))
    except Exception as e:  # noqa: BLE001 — el correo no tumba la activación
        print(f"⚠️ correo renovacion_activada: {e}")
    return {**res, "cobro": cobro}


def cobrar(medio_id: int) -> Dict[str, Any]:
    """Un cobro con la tarjeta guardada. El pago queda en `pagos` (automatico) y se aplica como cualquiera."""
    with get_db() as db:
        cur = db.cursor
        m = fetch_one(cur, """
            SELECT m.*, u.email, p.precio_cop FROM medios_pago m
            JOIN chat_users u ON u.id = m.user_id JOIN planes p ON p.codigo = m.plan_codigo
            WHERE m.id = %s
        """, (medio_id,))
        if not m or m["estado"] != "activa" or not m["precio_cop"]:
            return {"ok": False, "error": "sin_medio"}
        referencia = f"FY{m['user_id']}-AUT-{secrets.token_hex(5).upper()}"
        cur.execute("""
            INSERT INTO pagos (referencia, user_id, plan_codigo, monto_cop, automatico, medio_pago_id)
            VALUES (%s, %s, %s, %s, TRUE, %s)
        """, (referencia, m["user_id"], m["plan_codigo"], m["precio_cop"], medio_id))
        db.conn.commit()

    centavos = int(m["precio_cop"]) * 100
    try:
        r = requests.post(f"{pagos._api()}/transactions", headers=_privada(), timeout=25, json={
            "amount_in_cents": centavos, "currency": "COP", "reference": referencia,
            "signature": pagos.firma_integridad(referencia, centavos), "customer_email": m["email"],
            "payment_method": {"installments": 1}, "payment_source_id": int(m["fuente_id"]), "recurrent": True})
        tx = (r.json() or {}).get("data")
    except Exception as e:  # noqa: BLE001
        tx, r = None, None
        print(f"⚠️ Cobro automático {referencia}: {e}")
    if not tx or not tx.get("id"):
        pagos._aplicar({"reference": referencia, "status": "ERROR", "amount_in_cents": centavos, "currency": "COP"},
                       "renovacion")
        return {"ok": False, "referencia": referencia, "estado": "error"}
    # Casi siempre se resuelve en segundos; si no, lo cierra el webhook o la conciliación.
    for _ in range(5):
        if str(tx.get("status")).upper() != "PENDING":
            break
        time.sleep(2)
        try:
            tx = requests.get(f"{pagos._api()}/transactions/{tx['id']}", timeout=15).json()["data"]
        except Exception:  # noqa: BLE001
            break
    res = pagos._aplicar(tx, "renovacion")
    return {"ok": res.get("ok", False), "referencia": referencia, "estado": res.get("estado") or "pendiente"}


def renovar() -> Dict[str, int]:
    """Worker: cobra las renovaciones que vencen en menos de 24 h, con reintentos."""
    hechos = {"cobrados": 0, "pausados": 0}
    with get_db() as db:
        medios = fetch_all(db.cursor, """
            SELECT m.id, m.user_id, m.marca, m.ultimos4, m.created_at, p.nombre AS plan_nombre, u.nombre, u.email,
                   (SELECT MAX(fin) FROM suscripciones s WHERE s.user_id = m.user_id AND s.estado = 'activa') AS fin
            FROM medios_pago m JOIN planes p ON p.codigo = m.plan_codigo JOIN chat_users u ON u.id = m.user_id
            WHERE m.estado = 'activa'
        """)
    ahora = suscripcion_service._ahora()
    for m in medios:
        if not m["fin"] or m["fin"] - ahora > ANTES_DE_VENCER:
            continue
        with get_db() as db:
            intentos = fetch_all(db.cursor, """
                SELECT estado, created_at FROM pagos
                WHERE medio_pago_id = %s AND automatico AND created_at > %s ORDER BY created_at DESC
            """, (m["id"], m["fin"] - ANTES_DE_VENCER - timedelta(hours=1)))
        if any(i["estado"] in ("aprobado", "pendiente") for i in intentos):
            continue
        fallidos = [i for i in intentos if i["estado"] in ("rechazado", "error", "anulado")]
        if len(fallidos) >= INTENTOS or m["fin"] < ahora - timedelta(days=suscripcion_service.DIAS_GRACIA):
            with get_db() as db:
                db.cursor.execute("UPDATE medios_pago SET estado = 'fallida' WHERE id = %s", (m["id"],))
                db.conn.commit()
            try:
                correo_service.renovacion_fallida(m["nombre"], m["email"], m["plan_nombre"], f"{m['marca']} ••{m['ultimos4']}")
            except Exception as e:  # noqa: BLE001
                print(f"⚠️ correo renovacion_fallida: {e}")
            hechos["pausados"] += 1
            continue
        if fallidos and ahora - fallidos[0]["created_at"] < ENTRE_INTENTOS:
            continue
        cobrar(m["id"])
        hechos["cobrados"] += 1
    return hechos


def cancelar(user_id: int) -> Dict[str, Any]:
    with get_db() as db:
        db.cursor.execute("UPDATE medios_pago SET estado = 'cancelada', cancelada_at = NOW() "
                          "WHERE user_id = %s AND estado <> 'cancelada'", (user_id,))
        db.conn.commit()
    return estado(user_id)
