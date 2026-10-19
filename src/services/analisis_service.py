"""
Cupo del modo Análisis de Findy en la web (migración 062).

Un análisis es una pregunta que Findy responde con herramientas de mercado y componentes
(OpenUI). Le cuesta a Fynder ~USD 0,08–0,12, así que tiene cupo propio, aparte del uso
justo de la Búsqueda:
  - plan: `planes.analisis_ia` análisis por periodo pagado (el del plan vigente);
  - prueba: sin plan, el cupo del plan 'prueba', una sola vez;
  - extra: análisis canjeados con Fyns o regalados (`analisis_ia_movimientos`), no vencen.
Se gasta primero el del plan (o la prueba) y luego el extra. El análisis se reserva antes
de llamar a la IA (dos preguntas a la vez no se saltan el cupo) y, si falla, no se
descuenta. Tope diario anti-abuso: FYNDER_ANALISIS_DIA (30).
"""

import json
import os
from typing import Any, Dict, Optional

from src.services import suscripcion_service
from src.services.db import get_db, scalar

LIMITE_DIA = int(os.getenv("FYNDER_ANALISIS_DIA", "30"))
_LOCK_ANALISIS = 7105

# Un análisis cuenta si salió bien o si está en curso (reservado hace menos de 10 min).
_CUENTA = "(estado = 'ok' OR (estado = 'en_curso' AND created_at > NOW() - INTERVAL '10 minutes'))"


class AnalisisError(Exception):
    def __init__(self, codigo: str, mensaje: str, status: int = 400):
        super().__init__(mensaje)
        self.codigo, self.mensaje, self.status = codigo, mensaje, status


def _cupo(cur, user_id: int) -> Dict[str, Any]:
    periodo = suscripcion_service._periodo_vigente(cur, user_id)
    if periodo:
        incluidos = scalar(cur, "SELECT analisis_ia FROM planes WHERE codigo = %s", (periodo["plan_codigo"],))
        usados = scalar(cur, f"""
            SELECT COUNT(*) FROM analisis_ia
            WHERE user_id = %s AND fuente = 'plan' AND created_at >= %s AND {_CUENTA}
        """, (user_id, periodo["inicio"]))
        fuente, renueva = "plan", periodo["fin"]
    else:
        incluidos = scalar(cur, "SELECT analisis_ia FROM planes WHERE codigo = 'prueba'")
        usados = scalar(cur, f"SELECT COUNT(*) FROM analisis_ia WHERE user_id = %s AND fuente = 'prueba' AND {_CUENTA}",
                        (user_id,))
        fuente, renueva = "prueba", None
    abonados = scalar(cur, "SELECT COALESCE(SUM(cantidad), 0) FROM analisis_ia_movimientos WHERE user_id = %s",
                      (user_id,)) or 0
    gastados = scalar(cur, f"SELECT COUNT(*) FROM analisis_ia WHERE user_id = %s AND fuente = 'extra' AND {_CUENTA}",
                      (user_id,)) or 0
    hoy = scalar(cur, f"""
        SELECT COUNT(*) FROM analisis_ia
        WHERE user_id = %s AND {_CUENTA}
          AND created_at >= date_trunc('day', NOW() AT TIME ZONE 'America/Bogota') AT TIME ZONE 'America/Bogota'
    """, (user_id,)) or 0
    incluidos, usados = int(incluidos or 0), int(usados or 0)
    del_plan = max(0, incluidos - usados)
    extra = max(0, int(abonados) - int(gastados))
    return {
        "fuente": fuente,                 # 'plan' o 'prueba': de dónde sale el próximo antes del extra
        "con_plan": fuente == "plan",
        "total": incluidos,               # del plan este periodo (o de la prueba)
        "usados": usados,
        "del_plan": del_plan,
        "extra": extra,                   # canjeados o regalados, sin vencimiento
        "restantes": del_plan + extra,
        "renueva": renueva.isoformat() if renueva else None,
        "hoy": int(hoy),
        "limite_dia": LIMITE_DIA,
    }


def cupo(user_id: int) -> Dict[str, Any]:
    with get_db() as db:
        return _cupo(db.cursor, user_id)


def _sin_cupo(c: Dict[str, Any]) -> AnalisisError:
    if c["con_plan"]:
        msg = (f"Ya usaste los {c['total']} análisis de tu plan en este periodo. "
               "Canjea Fyns por más análisis; tu cupo se renueva con el plan.")
    else:
        msg = (f"Ya usaste tus {c['total']} análisis de prueba. "
               "Activa un plan (trae análisis cada mes) o canjea Fyns por más.")
    return AnalisisError("sin_cupo", msg, 402)


def reservar(user_id: int, conversacion_id: Optional[int], pregunta: str, modelo: str) -> Dict[str, Any]:
    """Toma un análisis del cupo (bajo lock por agente) y deja la fila 'en curso'."""
    with get_db() as db:
        cur = db.cursor
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK_ANALISIS, user_id))
        c = _cupo(cur, user_id)
        if c["hoy"] >= LIMITE_DIA:
            db.conn.rollback()
            raise AnalisisError("limite_dia", f"Llegaste al máximo de {LIMITE_DIA} análisis por día. "
                                "Sigue mañana; tu cupo no se pierde.", 429)
        fuente = c["fuente"] if c["del_plan"] > 0 else "extra" if c["extra"] > 0 else None
        if not fuente:
            db.conn.rollback()
            raise _sin_cupo(c)
        aid = scalar(cur, """
            INSERT INTO analisis_ia (user_id, conversacion_id, fuente, pregunta, modelo)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (user_id, conversacion_id, fuente, (pregunta or "")[:2000], modelo))
        db.conn.commit()
    return {"id": aid, "fuente": fuente}


def terminar(aid: int, herramientas: list, tokens_entrada: int, tokens_salida: int,
             tokens_cache: int, costo_usd: float) -> None:
    """El análisis salió: queda contado y con su costo."""
    with get_db() as db:
        db.cursor.execute("""
            UPDATE analisis_ia SET estado = 'ok', herramientas = %s, tokens_entrada = %s, tokens_salida = %s,
                   tokens_cache = %s, costo_usd = %s, terminado_at = NOW()
            WHERE id = %s
        """, (json.dumps(herramientas), tokens_entrada, tokens_salida, tokens_cache, costo_usd, aid))
        db.conn.commit()


def fallo(aid: int, error: str, costo_usd: Optional[float] = None) -> None:
    """El análisis no salió: se libera del cupo (el costo, si lo hubo, queda registrado)."""
    with get_db() as db:
        db.cursor.execute("""
            UPDATE analisis_ia SET estado = 'error', error = %s, costo_usd = %s, terminado_at = NOW() WHERE id = %s
        """, ((error or "")[:500], costo_usd, aid))
        db.conn.commit()


def abonar_en(cur, user_id: int, cantidad: int, referencia: str, creado_por: Optional[str] = None) -> int:
    """Suma análisis extra (canje de Fyns, regalo). Dentro de la transacción del caller."""
    return scalar(cur, """
        INSERT INTO analisis_ia_movimientos (user_id, cantidad, referencia, creado_por)
        VALUES (%s, %s, %s, %s) RETURNING id
    """, (user_id, cantidad, referencia, creado_por))
