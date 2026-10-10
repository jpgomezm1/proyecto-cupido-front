"""
Misiones, rachas y llaves de premio (migración 049).

Incentiva el uso diario de Fynder, y sobre todo el uso desde la IA del agente
(Claude/ChatGPT vía MCP), con llaves que se abonan al saldo que no vence:

  Misiones (una vez):
    conectar_ia   Conectar Fynder a su IA (sesión MCP o primera tool OK)  +2 llaves
    consulta_ia   Primera consulta desde su IA (una tool de datos)         +1 llave
    perfil        Perfil completo (nombre, correo, celular verificado)     insignia
    mapa          Explorar el mapa de mercado                               insignia
  Racha (días seguidos con uso real, hora de Bogotá):
    3 días +1 · 7 días +2 · 14 días +3; el doble si esos días también fueron
    días con IA (racha del MCP al menos igual de larga).

"Uso real" = una búsqueda con IA (uso justo), una tool del MCP o un desbloqueo.
Las llaves solo se abonan con el celular verificado (igual que la prueba) y hay
un tope de llaves de premio por mes; lo que pase del tope queda como logro sin
llaves. Todo es idempotente: `evaluar` se puede llamar cuantas veces se quiera.
"""

import logging
import time
from datetime import date, timedelta
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional, Set

from src.services.db import get_db, fetch_all, fetch_one, scalar

logger = logging.getLogger(__name__)

TZ = "America/Bogota"
TOPE_MES = 8
HITOS = ((3, 1), (7, 2), (14, 3))   # (días, llaves); con IA, el doble
VENTANA_DIAS = 60
_LOCK_LOGROS = 7102

# Tools que no cuentan como "consulta" (solo administran la cuenta).
_TOOLS_CUENTA = ("mi_plan", "mis_desbloqueos")

MISIONES = {
    "conectar_ia": {"titulo": "Conecta Fynder a tu IA", "llaves": 2,
                    "detalle": "Agrega Fynder en Claude o ChatGPT y entra con tu cuenta.",
                    "url": "/chat/conectar-ia"},
    "consulta_ia": {"titulo": "Haz tu primera consulta desde tu IA", "llaves": 1,
                    "detalle": "Pregúntale a Claude o ChatGPT, p. ej. «¿cuánto vale el m² en Laureles?».",
                    "url": "/chat/conectar-ia"},
    "perfil": {"titulo": "Completa tu perfil", "llaves": 0,
               "detalle": "Tu nombre y tu celular verificado: así firmas lo que compartes.",
               "url": "/chat/cuenta"},
    "mapa": {"titulo": "Explora el mapa de mercado", "llaves": 0,
             "detalle": "Mira qué zonas tienen más compradores que oferta.",
             "url": "/chat/mercado/mapa"},
}


class LogrosError(Exception):
    pass


# --------------------------------------------------------------------------
# Rachas (lógica pura, probada en tests/test_logros_unit.py)
# --------------------------------------------------------------------------

def racha_hasta(dias: Set[date], hoy: date) -> Dict[str, Any]:
    """
    Racha vigente: días seguidos con actividad que terminan hoy, o ayer si hoy
    todavía no hay actividad (la racha sigue viva hasta que termine el día).
    """
    fin = hoy if hoy in dias else hoy - timedelta(days=1)
    n = 0
    while fin - timedelta(days=n) in dias:
        n += 1
    inicio = fin - timedelta(days=n - 1) if n else None
    return {"dias": n, "inicio": inicio, "hoy": hoy in dias}


def record(dias: Set[date]) -> int:
    mejor = 0
    for d in dias:
        if d - timedelta(days=1) in dias:
            continue
        n = 1
        while d + timedelta(days=n) in dias:
            n += 1
        mejor = max(mejor, n)
    return mejor


def hitos_ganados(racha: int, racha_ia: int) -> List[Dict[str, Any]]:
    """Hitos que la racha actual ya alcanzó, con su premio (doble si fue con IA)."""
    return [{"hito": h, "con_ia": racha_ia >= h, "llaves": ll * (2 if racha_ia >= h else 1)}
            for h, ll in HITOS if racha >= h]


def siguiente_hito(racha: int) -> Optional[Dict[str, int]]:
    for h, ll in HITOS:
        if racha < h:
            return {"dias": h, "faltan": h - racha, "llaves": ll, "llaves_ia": ll * 2}
    return None


# --------------------------------------------------------------------------
# Datos
# --------------------------------------------------------------------------

def _hoy(cur) -> date:
    return scalar(cur, f"SELECT (NOW() AT TIME ZONE '{TZ}')::date")


def _dias(cur, user_id: int) -> Dict[str, Set[date]]:
    filas = fetch_all(cur, f"""
        SELECT fecha, BOOL_OR(ia) AS ia FROM (
            SELECT fecha, FALSE AS ia FROM uso_diario
             WHERE user_id = %(u)s AND busquedas > 0 AND fecha > CURRENT_DATE - %(v)s
            UNION ALL
            -- mcp_tool_calls.created_at es TIMESTAMP sin zona, guardado en UTC
            SELECT (created_at AT TIME ZONE 'UTC' AT TIME ZONE '{TZ}')::date, TRUE FROM mcp_tool_calls
             WHERE user_id = %(u)s AND ok AND created_at > (NOW() AT TIME ZONE 'UTC') - make_interval(days => %(v)s)
            UNION ALL
            SELECT (created_at AT TIME ZONE '{TZ}')::date, FALSE FROM desbloqueos
             WHERE user_id = %(u)s AND created_at > NOW() - make_interval(days => %(v)s)
        ) t GROUP BY fecha
    """, {"u": user_id, "v": VENTANA_DIAS})
    return {"todos": {f["fecha"] for f in filas}, "ia": {f["fecha"] for f in filas if f["ia"]}}


def _usuario(cur, user_id: int) -> Optional[Dict[str, Any]]:
    return fetch_one(cur, """
        SELECT id, nombre, email, telefono_verificado, onboarding_at
        FROM chat_users WHERE id = %s AND activo
    """, (user_id,))


def _misiones_cumplidas(cur, u: Dict[str, Any]) -> Set[str]:
    hechas: Set[str] = set()
    uid = u["id"]
    sesion = scalar(cur, """
        SELECT 1 FROM chat_user_sessions WHERE user_id = %s AND tipo = 'mcp' LIMIT 1
    """, (uid,))
    consulta = scalar(cur, """
        SELECT 1 FROM mcp_tool_calls WHERE user_id = %s AND ok AND tool <> ALL(%s) LIMIT 1
    """, (uid, list(_TOOLS_CUENTA)))
    alguna = consulta or scalar(cur, "SELECT 1 FROM mcp_tool_calls WHERE user_id = %s AND ok LIMIT 1", (uid,))
    if sesion or alguna:
        hechas.add("conectar_ia")
    if consulta:
        hechas.add("consulta_ia")
    if (u.get("nombre") or "").strip() and u.get("email") and u.get("telefono_verificado"):
        hechas.add("perfil")
    return hechas


def _llaves_mes(cur, user_id: int) -> int:
    return int(scalar(cur, f"""
        SELECT COALESCE(SUM(llaves), 0) FROM logros
        WHERE user_id = %s
          AND created_at >= date_trunc('month', NOW() AT TIME ZONE '{TZ}') AT TIME ZONE '{TZ}'
    """, (user_id,)) or 0)


def _otorgar(cur, user_id: int, codigo: str, referencia: str, llaves: int,
             con_ia: bool, verificado: bool) -> Optional[int]:
    """Registra el logro (si no existía) y abona sus llaves respetando el tope. Devuelve id o None."""
    if llaves > 0 and not verificado:
        return None  # se cobra cuando verifique el celular (la condición se re-evalúa)
    pagar = min(llaves, max(0, TOPE_MES - _llaves_mes(cur, user_id))) if llaves > 0 else 0
    cur.execute("""
        INSERT INTO logros (user_id, codigo, referencia, llaves, con_ia, avisado_mcp)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, codigo, referencia) DO NOTHING
        RETURNING id
    """, (user_id, codigo, referencia, pagar, con_ia, pagar == 0))
    fila = cur.fetchone()
    if not fila:
        return None
    if pagar:
        cur.execute("""
            INSERT INTO creditos_movimientos (user_id, tipo, cantidad, referencia, creado_por)
            VALUES (%s, 'premio', %s, %s, 'sistema')
        """, (user_id, pagar, f"logro:{fila['id']}"))
    return fila["id"]


# --------------------------------------------------------------------------
# API del servicio
# --------------------------------------------------------------------------

def evaluar(user_id: int) -> List[int]:
    """Otorga lo que el agente ya se ganó. Idempotente. Devuelve ids de logros nuevos."""
    nuevos: List[int] = []
    with get_db() as db:
        cur = db.cursor
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK_LOGROS, user_id))
        u = _usuario(cur, user_id)
        if not u:
            return []
        verificado = bool(u.get("telefono_verificado"))
        for codigo in _misiones_cumplidas(cur, u):
            i = _otorgar(cur, user_id, codigo, "", MISIONES[codigo]["llaves"], codigo != "perfil", verificado)
            if i:
                nuevos.append(i)
        dias = _dias(cur, user_id)
        hoy = _hoy(cur)
        r, ria = racha_hasta(dias["todos"], hoy), racha_hasta(dias["ia"], hoy)
        for h in hitos_ganados(r["dias"], ria["dias"]):
            i = _otorgar(cur, user_id, "racha", f"{r['inicio'].isoformat()}:{h['hito']}",
                         h["llaves"], h["con_ia"], verificado)
            if i:
                nuevos.append(i)
        db.conn.commit()
    return nuevos


def registrar_evento(user_id: int, evento: str) -> List[int]:
    """Insignias que dispara la web (hoy: abrir el mapa)."""
    if evento != "mapa":
        raise LogrosError("Evento desconocido")
    with get_db() as db:
        i = _otorgar(db.cursor, user_id, "mapa", "", 0, False, True)
        db.conn.commit()
    return [i] if i else []


def _titulo(l: Dict[str, Any]) -> str:
    if l["codigo"] == "racha":
        dias = l["referencia"].split(":")[-1]
        return f"Racha de {dias} días" + (" con tu IA" if l["con_ia"] else "")
    return MISIONES.get(l["codigo"], {}).get("titulo", l["codigo"])


def _logro_salida(l: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": l["id"], "codigo": l["codigo"], "titulo": _titulo(l), "llaves": l["llaves"],
            "con_ia": l["con_ia"], "fecha": l["created_at"].isoformat()}


def resumen(user_id: int) -> Dict[str, Any]:
    """Todo lo que la web muestra: racha, semana, misiones, premios del mes y logros por celebrar."""
    evaluar(user_id)
    with get_db() as db:
        cur = db.cursor
        u = _usuario(cur, user_id)
        if not u:
            raise LogrosError("Usuario no encontrado")
        dias = _dias(cur, user_id)
        hoy = _hoy(cur)
        logros = fetch_all(cur, """
            SELECT id, codigo, referencia, llaves, con_ia, visto, created_at
            FROM logros WHERE user_id = %s ORDER BY created_at DESC LIMIT 60
        """, (user_id,))
        cumplidas = _misiones_cumplidas(cur, u)
        mes = _llaves_mes(cur, user_id)
    r, ria = racha_hasta(dias["todos"], hoy), racha_hasta(dias["ia"], hoy)
    cobradas = {l["codigo"] for l in logros if l["codigo"] in MISIONES}
    verificado = bool(u.get("telefono_verificado"))
    return {
        "racha": {
            "dias": r["dias"], "hoy": r["hoy"], "en_riesgo": r["dias"] > 0 and not r["hoy"],
            "dias_ia": ria["dias"], "hoy_ia": ria["hoy"],
            "record": record(dias["todos"]),
            "siguiente": siguiente_hito(r["dias"]),
            "semana": [{"fecha": (hoy - timedelta(days=k)).isoformat(),
                        "activo": hoy - timedelta(days=k) in dias["todos"],
                        "ia": hoy - timedelta(days=k) in dias["ia"]} for k in range(6, -1, -1)],
            "hitos": [{"dias": h, "llaves": ll, "llaves_ia": ll * 2} for h, ll in HITOS],
        },
        "misiones": [{
            "codigo": c, "titulo": m["titulo"], "detalle": m["detalle"], "url": m["url"],
            "llaves": m["llaves"], "hecha": c in cumplidas or c in cobradas, "cobrada": c in cobradas,
        } for c, m in MISIONES.items()],
        "premios_mes": {"ganadas": mes, "tope": TOPE_MES},
        "verificado": verificado,
        "onboarding": {"completado": bool(u.get("onboarding_at"))},
        "nuevos": [_logro_salida(l) for l in logros if not l["visto"]],
        "recientes": [_logro_salida(l) for l in logros[:8]],
    }


def marcar_vistos(user_id: int, ids: Iterable[int]) -> int:
    ids = [int(i) for i in ids][:100]
    if not ids:
        return 0
    with get_db() as db:
        db.cursor.execute("UPDATE logros SET visto = TRUE WHERE user_id = %s AND id = ANY(%s)", (user_id, ids))
        n = db.cursor.rowcount
        db.conn.commit()
    return n


def completar_onboarding(user_id: int) -> None:
    with get_db() as db:
        db.cursor.execute("UPDATE chat_users SET onboarding_at = COALESCE(onboarding_at, NOW()) WHERE id = %s",
                          (user_id,))
        db.conn.commit()


# --------------------------------------------------------------------------
# MCP: evaluar tras cada tool (con freno) y contarle al agente lo que ganó
# --------------------------------------------------------------------------

_ultima_eval: Dict[int, float] = {}
_eval_lock = Lock()
_FRENO_S = 90


def evaluar_tras_mcp(user_id: Optional[int]) -> None:
    """Desde el hilo de registro del MCP. Como mucho una evaluación por agente cada 90 s. Nunca lanza."""
    if not user_id:
        return
    with _eval_lock:
        if time.monotonic() - _ultima_eval.get(user_id, 0) < _FRENO_S:
            return
        _ultima_eval[user_id] = time.monotonic()
    try:
        evaluar(user_id)
    except Exception as e:  # la tabla puede no existir aún (migración 049)
        logger.warning("No se pudieron evaluar logros de %s: %s", user_id, e)


def aviso_mcp(user_id: int) -> Optional[Dict[str, Any]]:
    """Premios con llaves que el agente aún no conoce por su IA (y los marca como avisados)."""
    try:
        with get_db() as db:
            filas = fetch_all(db.cursor, """
                UPDATE logros SET avisado_mcp = TRUE
                WHERE user_id = %s AND NOT avisado_mcp AND llaves > 0
                RETURNING id, codigo, referencia, llaves, con_ia, created_at
            """, (user_id,))
            if not filas:
                return None
            saldo_premio = TOPE_MES - _llaves_mes(db.cursor, user_id)
            db.conn.commit()
    except Exception:
        return None
    total = sum(f["llaves"] for f in filas)
    return {
        "llaves_ganadas": total,
        "logros": [_titulo(f) for f in filas],
        "mensaje": (f"🎉 El agente ganó {total} {'llave' if total == 1 else 'llaves'} de Fynder por: "
                    + ", ".join(_titulo(f) for f in filas)
                    + ". Felicítalo brevemente al final de tu respuesta. Usar Fynder desde su IA "
                      "paga el doble en las rachas (3, 7 y 14 días seguidos)."),
        "premios_restantes_mes": max(0, saldo_premio),
    }
