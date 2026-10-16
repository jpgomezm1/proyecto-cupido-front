"""
Plan Fundador (lanzamiento, nov-2026; migración 060).

Los primeros 20 agentes (la red de Hernán): todo lo de Cierre, gratis hasta el
15 de enero de 2027 y después $50.000 fijos cada 30 días mientras sigan
suscritos sin cortes. El plan no está a la venta (planes.activo = false): solo
lo activa el admin desde Ventas.

  activar(user_id)   la primera vez: ocupa un cupo y crea los periodos gratis
                     (de 30 días, el último recortado al 15-ene); después: renueva
                     30 días a $50.000 si no perdió la continuidad.

Los periodos son filas normales de `suscripciones` (plan_codigo = 'fundador'),
así que llaves, fotos, Fyns y beneficios salen de los mismos lugares que para
cualquier plan.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from src.services.db import fetch_one, get_db, scalar
from src.services import suscripcion_service as suscripciones

CODIGO = "fundador"
CUPOS = int(os.getenv("FYNDER_FUNDADORES_CUPOS", "20"))
# 15-ene-2027, fin del día en Bogotá (UTC-5)
GRATIS_HASTA = datetime(2027, 1, 16, 5, 0, tzinfo=timezone.utc)
_LOCK = 7106


class FundadorError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def _fundadores(cur) -> int:
    return scalar(cur, "SELECT COUNT(DISTINCT user_id) FROM suscripciones WHERE plan_codigo = %s", (CODIGO,)) or 0


def cupos() -> Dict[str, int]:
    with get_db() as db:
        usados = _fundadores(db.cursor)
    return {"total": CUPOS, "usados": usados, "libres": max(0, CUPOS - usados)}


def estado_de(cur, user_id: int) -> Optional[Dict[str, Any]]:
    """None si nunca fue fundador; si lo es: hasta cuándo tiene periodos y si sigue vigente."""
    f = fetch_one(cur, """
        SELECT MIN(inicio) AS desde, MAX(fin) AS hasta, MAX(gracia_hasta) AS gracia_hasta
        FROM suscripciones WHERE user_id = %s AND plan_codigo = %s AND estado = 'activa'
    """, (user_id, CODIGO))
    if not f or not f["desde"]:
        return None
    ahora = suscripciones._ahora()
    return {"desde": f["desde"].isoformat(), "hasta": f["hasta"].isoformat(),
            "vigente": f["gracia_hasta"] > ahora, "gratis_hasta": GRATIS_HASTA.isoformat()}


def _insertar(cur, user_id, plan, inicio, fin, precio, referencia, notas, admin) -> int:
    return scalar(cur, """
        INSERT INTO suscripciones (user_id, plan_codigo, desbloqueos_incluidos, fotos_ia_incluidas, precio_cop,
                                   inicio, fin, gracia_hasta, referencia_pago, notas, activada_por)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    """, (user_id, CODIGO, plan["desbloqueos_mes"], plan.get("fotos_ia") or 0, precio, inicio, fin,
          fin + timedelta(days=suscripciones.DIAS_GRACIA), referencia, notas, admin))


def activar(user_id: int, admin: Optional[str] = None, referencia_pago: Optional[str] = None,
            forzar: bool = False) -> Dict[str, Any]:
    """Primera vez: cupo + periodos gratis hasta el 15-ene. Después: renovación paga de 30 días.
    `forzar` permite renovar aunque haya perdido la continuidad (decisión del admin)."""
    with get_db() as db:
        cur = db.cursor
        plan = fetch_one(cur, "SELECT * FROM planes WHERE codigo = %s", (CODIGO,))
        if not plan:
            raise FundadorError("sin_plan", "Falta el plan Fundador (migración 060).")
        if not fetch_one(cur, "SELECT id FROM chat_users WHERE id = %s", (user_id,)):
            raise FundadorError("no_encontrado", "Ese agente no existe.")
        # Un lock global: el cupo se cuenta y se ocupa sin carreras.
        cur.execute("SELECT pg_advisory_xact_lock(%s, 0)", (_LOCK,))
        ahora = suscripciones._ahora()
        previo = estado_de(cur, user_id)

        if previo is None:
            if _fundadores(cur) >= CUPOS:
                raise FundadorError("sin_cupos", f"Ya se ocuparon los {CUPOS} cupos de fundador.")
            # Si tiene otro plan vigente, los periodos de fundador arrancan cuando ese termina.
            otro_fin = scalar(cur, """
                SELECT MAX(fin) FROM suscripciones WHERE user_id = %s AND estado = 'activa' AND fin > NOW()
            """, (user_id,))
            inicio = max(ahora, otro_fin) if otro_fin else ahora
            tramos = []
            while inicio < GRATIS_HASTA:
                fin = min(inicio + timedelta(days=suscripciones.DIAS_PERIODO), GRATIS_HASTA)
                if (GRATIS_HASTA - fin) < timedelta(days=3):    # no dejar un periodo de 1-2 días: se alarga este
                    fin = GRATIS_HASTA
                tramos.append((inicio, fin))
                inicio = fin
            ids = [_insertar(cur, user_id, plan, a, b, 0, "fundador-gratis", "Fundador: gratis hasta el 15 de enero", admin)
                   for a, b in tramos if (b - a) >= timedelta(days=3)]
            if not ids:
                raise FundadorError("fuera_de_fecha", "El periodo gratis de fundador ya terminó.")
            db.conn.commit()
            return {"ok": True, "primera_vez": True, "periodos": len(ids), "hasta": inicio.isoformat(),
                    "cupos_libres": max(0, CUPOS - _fundadores(cur))}

        if not previo["vigente"] and not forzar:
            raise FundadorError("perdio_continuidad",
                                "Su plan de fundador se venció y perdió el precio fijo. Actívalo con `forzar` si quieres mantenérselo.")
        ultimo_fin = datetime.fromisoformat(previo["hasta"])
        inicio = max(ahora, ultimo_fin)
        fin = inicio + timedelta(days=suscripciones.DIAS_PERIODO)
        sid = _insertar(cur, user_id, plan, inicio, fin, int(plan["precio_cop"]), referencia_pago,
                        "Fundador: renovación a precio fijo", admin)
        db.conn.commit()
        return {"ok": True, "primera_vez": False, "suscripcion_id": sid,
                "inicio": inicio.isoformat(), "fin": fin.isoformat(), "precio_cop": int(plan["precio_cop"])}
