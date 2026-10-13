"""
Misiones, rachas y premios en Fyns (migraciones 049 y 057).

Incentiva el uso diario de Fynder, y sobre todo el uso desde la IA del agente
(Claude/ChatGPT vía MCP), con Fyns (la divisa de Fynder, `fyns_service`) que se
canjean por llaves, fotos con IA y complementos. Desde su IA paga ~5 veces más:

  Día con uso real ................ IA +15 · web +3   (desde FYNS_DESDE)
  Cada 7 días seguidos ............ IA +75 · web +15  (con IA si la racha del MCP es igual de larga)
  Subir un inmueble a la red ...... IA +40 · web +10  (cuando queda publicado)
  Misiones (una vez): conectar su IA +300 · primera consulta desde su IA +100 ·
  perfil completo +50 · explorar el mapa +20.

"Uso real" = una búsqueda con IA (uso justo), una tool del MCP que no sea de la
cuenta (mi_plan, mis_desbloqueos, mis_fyns) o un desbloqueo. Un día se paga
cuando termina (si fue con IA, se paga en el momento: ya vale lo máximo).
Los Fyns solo se abonan con el celular verificado y hasta el tope mensual del
plan; lo que pase del tope queda como logro sin Fyns. Los logros anteriores a
Fyns conservan sus llaves. Todo es idempotente: `evaluar` se puede llamar
cuantas veces se quiera.
"""

import logging
import os
import time
from datetime import date, timedelta
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional, Set

from src.services import fyns_service as fyns
from src.services.db import get_db, fetch_all, fetch_one, scalar

logger = logging.getLogger(__name__)

TZ = "America/Bogota"
VENTANA_DIAS = 60
_LOCK_LOGROS = 7102

# Fyns por logro: (desde su IA, desde la web).
FYNS_DIA = (15, 3)
FYNS_RACHA = (75, 15)       # cada 7 días seguidos
FYNS_PUBLICAR = (40, 10)
CADA_RACHA = 7
# Los días y rachas se pagan desde que existen los Fyns (no hacia atrás).
FYNS_DESDE = date.fromisoformat(os.getenv("FYNS_DESDE", "2026-10-14"))
DIAS_ATRAS = 7              # un día sin evaluar se paga hasta una semana después

# Tools que no cuentan como "consulta" (solo administran la cuenta).
_TOOLS_CUENTA = ("mi_plan", "mis_desbloqueos", "mis_fyns", "canjear_fyns")

MISIONES = {
    "conectar_ia": {"titulo": "Conecta Fynder a tu IA", "fyns": 300,
                    "detalle": "Agrega Fynder en Claude o ChatGPT y entra con tu cuenta.",
                    "url": "/chat/conectar-ia"},
    "consulta_ia": {"titulo": "Haz tu primera consulta desde tu IA", "fyns": 100,
                    "detalle": "Pregúntale a Claude o ChatGPT, p. ej. «¿cuánto vale el m² en Laureles?».",
                    "url": "/chat/conectar-ia"},
    "perfil": {"titulo": "Completa tu perfil", "fyns": 50,
               "detalle": "Tu nombre y tu celular verificado: así firmas lo que compartes.",
               "url": "/chat/cuenta"},
    "mapa": {"titulo": "Explora el mapa de mercado", "fyns": 20,
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
    """Cada 7 días seguidos de la racha actual, con su premio (el de IA si la racha con IA llega)."""
    return [{"hito": h, "con_ia": racha_ia >= h, "fyns": FYNS_RACHA[0] if racha_ia >= h else FYNS_RACHA[1]}
            for h in range(CADA_RACHA, racha + 1, CADA_RACHA)]


def siguiente_hito(racha: int) -> Dict[str, int]:
    h = (racha // CADA_RACHA + 1) * CADA_RACHA
    return {"dias": h, "faltan": h - racha, "fyns": FYNS_RACHA[1], "fyns_ia": FYNS_RACHA[0]}


def dias_a_pagar(dias: Set[date], dias_ia: Set[date], hoy: date) -> List[Dict[str, Any]]:
    """Días con uso que ya se pueden pagar: los terminados de la última semana y hoy si fue con IA."""
    desde = max(FYNS_DESDE, hoy - timedelta(days=DIAS_ATRAS))
    out = []
    for d in sorted(dias):
        if d < desde or (d == hoy and d not in dias_ia):
            continue
        ia = d in dias_ia
        out.append({"fecha": d, "con_ia": ia, "fyns": FYNS_DIA[0] if ia else FYNS_DIA[1]})
    return out


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
               -- Consultar la cuenta (mi_plan, mis_desbloqueos) no es uso real.
               AND tool <> ALL(%(cuenta)s)
            UNION ALL
            SELECT (created_at AT TIME ZONE '{TZ}')::date, FALSE FROM desbloqueos
             WHERE user_id = %(u)s AND created_at > NOW() - make_interval(days => %(v)s)
        ) t GROUP BY fecha
    """, {"u": user_id, "v": VENTANA_DIAS, "cuenta": list(_TOOLS_CUENTA)})
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


def _publicados(cur, user_id: int) -> List[Dict[str, Any]]:
    """Inmuebles que el agente subió a la red (ya publicados) desde que existen los Fyns."""
    return fetch_all(cur, """
        SELECT e.propiedad_id, COALESCE(e.datos_evento->>'canal', 'web') = 'mcp' AS con_ia
        FROM eventos_log e JOIN propiedades p ON p.id = e.propiedad_id AND p.activa
        WHERE e.tipo_evento = 'listing_creado_fynder'
          AND e.datos_evento->>'user_id' = %s AND e.fecha_evento >= %s
    """, (str(user_id), FYNS_DESDE))


def _otorgar(cur, user_id: int, codigo: str, referencia: str, premio: int,
             con_ia: bool, verificado: bool) -> Optional[int]:
    """Registra el logro (si no existía) y abona sus Fyns respetando el tope del mes. Devuelve id o None."""
    if premio > 0 and not verificado:
        return None  # se cobra cuando verifique el celular (la condición se re-evalúa)
    pagar = 0
    if premio > 0:
        disponible = fyns.tope_mes_en(cur, user_id) - fyns.ganados_mes_en(cur, user_id)
        pagar = min(premio, max(0, disponible))
    cur.execute("""
        INSERT INTO logros (user_id, codigo, referencia, fyns, con_ia, avisado_mcp)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, codigo, referencia) DO NOTHING
        RETURNING id
    """, (user_id, codigo, referencia, pagar, con_ia, pagar == 0))
    fila = cur.fetchone()
    if not fila:
        return None
    if pagar:
        cur.execute("""
            INSERT INTO fyns_movimientos (user_id, cantidad, motivo, referencia)
            VALUES (%s, %s, 'logro', %s)
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
        premios = [(codigo, "", MISIONES[codigo]["fyns"], codigo in ("conectar_ia", "consulta_ia"))
                   for codigo in _misiones_cumplidas(cur, u)]
        dias = _dias(cur, user_id)
        hoy = _hoy(cur)
        premios += [("dia", d["fecha"].isoformat(), d["fyns"], d["con_ia"])
                    for d in dias_a_pagar(dias["todos"], dias["ia"], hoy)]
        r, ria = racha_hasta(dias["todos"], hoy), racha_hasta(dias["ia"], hoy)
        for h in hitos_ganados(r["dias"], ria["dias"]):
            # Solo rachas que se completan desde que existen los Fyns.
            if r["inicio"] + timedelta(days=h["hito"] - 1) >= FYNS_DESDE:
                premios.append(("racha", f"{r['inicio'].isoformat()}:{h['hito']}", h["fyns"], h["con_ia"]))
        premios += [("publicar", str(p["propiedad_id"]), FYNS_PUBLICAR[0] if p["con_ia"] else FYNS_PUBLICAR[1],
                     p["con_ia"]) for p in _publicados(cur, user_id)]
        for codigo, ref, premio, con_ia in premios:
            i = _otorgar(cur, user_id, codigo, ref, premio, con_ia, verificado)
            if i:
                nuevos.append(i)
        db.conn.commit()
    return nuevos


def registrar_evento(user_id: int, evento: str) -> List[int]:
    """Insignias que dispara la web (hoy: abrir el mapa)."""
    if evento != "mapa":
        raise LogrosError("Evento desconocido")
    with get_db() as db:
        u = _usuario(db.cursor, user_id)
        i = _otorgar(db.cursor, user_id, "mapa", "", MISIONES["mapa"]["fyns"], False,
                     bool(u and u.get("telefono_verificado")))
        db.conn.commit()
    return [i] if i else []


def _titulo(l: Dict[str, Any]) -> str:
    ia = " con tu IA" if l["con_ia"] else ""
    if l["codigo"] == "racha":
        dias = l["referencia"].split(":")[-1]
        return f"Racha de {dias} días{ia}"
    if l["codigo"] == "dia":
        return f"Un día usando Fynder{ia}"
    if l["codigo"] == "publicar":
        return "Subiste un inmueble a la red" + (" desde tu IA" if l["con_ia"] else "")
    return MISIONES.get(l["codigo"], {}).get("titulo", l["codigo"])


def _logro_salida(l: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": l["id"], "codigo": l["codigo"], "titulo": _titulo(l), "llaves": l["llaves"],
            "fyns": l.get("fyns") or 0, "con_ia": l["con_ia"], "fecha": l["created_at"].isoformat()}


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
            SELECT id, codigo, referencia, llaves, fyns, con_ia, visto, created_at
            FROM logros WHERE user_id = %s ORDER BY created_at DESC LIMIT 60
        """, (user_id,))
        cumplidas = _misiones_cumplidas(cur, u)
    billetera = fyns.estado(user_id)
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
            "cada": CADA_RACHA, "fyns_dia": FYNS_DIA[1], "fyns_dia_ia": FYNS_DIA[0],
        },
        "misiones": [{
            "codigo": c, "titulo": m["titulo"], "detalle": m["detalle"], "url": m["url"],
            "fyns": m["fyns"], "hecha": c in cumplidas or c in cobradas, "cobrada": c in cobradas,
        } for c, m in MISIONES.items()],
        "fyns": billetera,
        "verificado": verificado,
        "onboarding": {"completado": bool(u.get("onboarding_at"))},
        "nuevos": [_logro_salida(l) for l in logros if not l["visto"] and l["codigo"] != "dia"],
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
    """Fyns que el agente aún no conoce por su IA (y los marca como avisados).
    Los días sueltos se avisan solo junto con algo más, para no felicitar a diario."""
    try:
        with get_db() as db:
            cur = db.cursor
            filas = fetch_all(cur, """
                UPDATE logros SET avisado_mcp = TRUE
                WHERE user_id = %s AND NOT avisado_mcp AND fyns > 0
                  AND EXISTS (SELECT 1 FROM logros x WHERE x.user_id = %s AND NOT x.avisado_mcp
                              AND x.fyns > 0 AND x.codigo <> 'dia')
                RETURNING id, codigo, referencia, fyns, con_ia, created_at
            """, (user_id, user_id))
            if not filas:
                db.conn.rollback()
                return None
            saldo = fyns.saldo_en(cur, user_id)
            restante = fyns.tope_mes_en(cur, user_id) - fyns.ganados_mes_en(cur, user_id)
            db.conn.commit()
    except Exception:
        return None
    total = sum(f["fyns"] for f in filas)
    motivos = [_titulo(f) for f in filas if f["codigo"] != "dia"]
    return {
        "fyns_ganados": total,
        "saldo_fyns": saldo,
        "logros": motivos,
        "mensaje": (f"🎉 El agente ganó {total} Fyns (la divisa de Fynder) por: " + ", ".join(motivos)
                    + f". Ahora tiene {saldo} Fyns. Felicítalo en UNA línea al final de tu respuesta; "
                      "si le alcanza, recuérdale que puede canjearlos (100 Fyns = 1 llave) con 'canjear_fyns'."),
        "fyns_restantes_mes": max(0, restante),
    }
