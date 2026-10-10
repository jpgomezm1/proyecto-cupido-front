"""
Tablero de uso del admin. Dos fuentes:

1. La base de Fynder (siempre disponible, con todo el historial): actividad por
   día, agentes activos, embudo del negocio y retención semanal. "Activo" = el
   agente buscó con Findy (uso_diario), usó el MCP o abrió un contacto ese día.
2. PostHog (lo que solo se ve en la interfaz): embudo de la web, páginas más
   usadas y web vs MCP. Requiere POSTHOG_PERSONAL_KEY (solo lectura, scope
   query:read) y POSTHOG_PROJECT_ID; sin ellos responde {configurado: False}.
   Las consultas a PostHog se cachean 10 minutos.
"""

import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.services.db import fetch_all, fetch_one, get_db

_ACTIVIDAD = """
    SELECT user_id, fecha::date AS dia FROM uso_diario WHERE busquedas > 0
    UNION SELECT user_id, created_at::date FROM mcp_tool_calls WHERE user_id IS NOT NULL
    UNION SELECT user_id, created_at::date FROM desbloqueos
"""


def _valor(v: Any) -> Any:
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if v.__class__.__name__ == "Decimal":
        return int(v) if v == int(v) else float(v)
    return v


def _iso(filas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{k: _valor(v) for k, v in dict(f).items()} for f in filas]


def sistema(dias: int = 30) -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        por_dia = fetch_all(cur, f"""
            WITH dias AS (SELECT generate_series((NOW() - (%s - 1) * INTERVAL '1 day')::date, NOW()::date, '1 day')::date AS dia),
                 act AS ({_ACTIVIDAD})
            SELECT d.dia,
                   (SELECT COUNT(DISTINCT user_id) FROM act WHERE act.dia = d.dia) AS agentes_activos,
                   (SELECT COALESCE(SUM(busquedas), 0) FROM uso_diario WHERE fecha = d.dia) AS busquedas,
                   (SELECT COUNT(*) FROM mcp_tool_calls WHERE created_at::date = d.dia) AS mcp,
                   (SELECT COUNT(*) FROM desbloqueos WHERE created_at::date = d.dia) AS contactos,
                   (SELECT COUNT(*) FROM chat_users WHERE fecha_creacion::date = d.dia) AS agentes_nuevos,
                   (SELECT COALESCE(SUM(monto_cop), 0) FROM pagos WHERE estado = 'aprobado' AND created_at::date = d.dia) AS ingresos
            FROM dias d ORDER BY d.dia
        """, (dias,))
        activos = fetch_one(cur, f"""
            WITH act AS ({_ACTIVIDAD})
            SELECT COUNT(DISTINCT user_id) FILTER (WHERE dia = NOW()::date) AS hoy,
                   COUNT(DISTINCT user_id) FILTER (WHERE dia > NOW()::date - 7) AS semana,
                   COUNT(DISTINCT user_id) FILTER (WHERE dia > NOW()::date - 30) AS mes
            FROM act
        """)
        embudo = fetch_one(cur, """
            SELECT COUNT(*) FILTER (WHERE activo) AS registrados,
                   COUNT(*) FILTER (WHERE activo AND telefono_verificado) AS verificados,
                   COUNT(*) FILTER (WHERE activo AND (EXISTS (SELECT 1 FROM uso_diario d WHERE d.user_id = u.id AND d.busquedas > 0)
                                       OR EXISTS (SELECT 1 FROM mcp_tool_calls m WHERE m.user_id = u.id))) AS buscaron,
                   COUNT(*) FILTER (WHERE activo AND EXISTS (SELECT 1 FROM desbloqueos x WHERE x.user_id = u.id)) AS abrieron_contacto,
                   COUNT(*) FILTER (WHERE activo AND EXISTS (SELECT 1 FROM pagos p WHERE p.user_id = u.id AND p.estado = 'aprobado')) AS pagaron
            FROM chat_users u
            -- Las cuentas pre-cargadas cuentan solo cuando ya se entregaron.
            WHERE COALESCE(u.origen, '') <> 'provision' OR u.acceso_entregado
        """)
        semanas = fetch_all(cur, f"""
            WITH act AS ({_ACTIVIDAD}),
                 sem AS (SELECT DISTINCT user_id, date_trunc('week', dia)::date AS semana FROM act)
            SELECT s.semana, COUNT(*) AS activos,
                   COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM sem p WHERE p.user_id = s.user_id
                                                  AND p.semana = s.semana - 7)) AS volvieron
            FROM sem s WHERE s.semana > date_trunc('week', NOW())::date - 7 * 8
            GROUP BY s.semana ORDER BY s.semana
        """)
        top = fetch_all(cur, f"""
            WITH act AS ({_ACTIVIDAD})
            SELECT u.id AS user_id, u.nombre AS agente, COUNT(DISTINCT a.dia) AS dias_activo,
                   MAX(a.dia) AS ultimo_dia
            FROM act a JOIN chat_users u ON u.id = a.user_id
            WHERE a.dia > NOW()::date - %s
            GROUP BY u.id, u.nombre ORDER BY dias_activo DESC, ultimo_dia DESC LIMIT 15
        """, (dias,))
    return {"dias": dias, "por_dia": _iso(por_dia), "activos": _iso([activos])[0], "embudo": _iso([embudo])[0],
            "semanas": _iso(semanas), "top_agentes": _iso(top)}


# ── PostHog ────────────────────────────────────────────────────────────────

_CACHE: Dict[Tuple[str, int], Tuple[float, Any]] = {}
_TTL = 600

PASOS_WEB = ["findy_busqueda", "inmueble_abierto", "contacto_vista_previa", "contacto_abierto"]


def _posthog_config() -> Optional[Tuple[str, str, str]]:
    key, proyecto = os.getenv("POSTHOG_PERSONAL_KEY"), os.getenv("POSTHOG_PROJECT_ID")
    if not key or not proyecto:
        return None
    return key, proyecto, os.getenv("POSTHOG_API_HOST", "https://us.posthog.com").rstrip("/")


def _hogql(q: str) -> List[list]:
    key, proyecto, host = _posthog_config()  # type: ignore[misc]
    r = requests.post(f"{host}/api/projects/{proyecto}/query/",
                      headers={"Authorization": f"Bearer {key}"},
                      json={"query": {"kind": "HogQLQuery", "query": q}}, timeout=25)
    r.raise_for_status()
    return r.json().get("results") or []


def interfaz(dias: int = 30) -> Dict[str, Any]:
    """Lo mismo que se pide a PostHog, calculado con `eventos_uso` (migración 054)."""
    d = int(dias)
    try:
        with get_db() as db:
            cur = db.cursor
            pasos = {f["evento"]: int(f["agentes"]) for f in fetch_all(cur, """
                SELECT evento, COUNT(DISTINCT user_id) AS agentes FROM eventos_uso
                WHERE created_at > NOW() - (%s * INTERVAL '1 day') AND evento = ANY(%s)
                GROUP BY evento
            """, (d, PASOS_WEB))}
            por_dia = fetch_all(cur, """
                WITH dias AS (SELECT generate_series((NOW() - (%s - 1) * INTERVAL '1 day')::date, NOW()::date, '1 day')::date AS dia)
                SELECT d.dia,
                       (SELECT COUNT(*) FROM eventos_uso e WHERE e.created_at::date = d.dia) AS web,
                       (SELECT COUNT(*) FROM mcp_tool_calls m WHERE m.created_at::date = d.dia) AS mcp,
                       (SELECT COUNT(DISTINCT u) FROM (
                            SELECT user_id AS u FROM eventos_uso WHERE created_at::date = d.dia
                            UNION SELECT user_id FROM mcp_tool_calls WHERE created_at::date = d.dia) x) AS agentes
                FROM dias d ORDER BY d.dia
            """, (d,))
            paginas = fetch_all(cur, """
                SELECT COALESCE(ruta, '/') AS pagina, COUNT(*) AS vistas, COUNT(DISTINCT user_id) AS agentes
                FROM eventos_uso WHERE evento = 'pagina_vista' AND created_at > NOW() - (%s * INTERVAL '1 day')
                GROUP BY 1 ORDER BY 2 DESC LIMIT 15
            """, (d,))
            eventos = fetch_all(cur, """
                SELECT evento, COUNT(*) AS total, COUNT(DISTINCT user_id) AS agentes
                FROM eventos_uso WHERE evento <> 'pagina_vista' AND created_at > NOW() - (%s * INTERVAL '1 day')
                GROUP BY 1 ORDER BY 2 DESC LIMIT 20
            """, (d,))
    except Exception as e:  # noqa: BLE001 — sin la migración 054
        return {"configurado": False, "error": f"Falta la tabla de eventos (migración 054): {str(e)[:120]}"}
    return {"configurado": True, "fuente": "fynder", "dias": d,
            "embudo": [{"paso": p, "agentes": pasos.get(p, 0)} for p in PASOS_WEB],
            "por_dia": _iso(por_dia), "paginas": _iso(paginas), "eventos": _iso(eventos)}


def posthog(dias: int = 30) -> Dict[str, Any]:
    if not _posthog_config():
        # Sin llave de lectura de PostHog: los mismos eventos, guardados en Fynder.
        return interfaz(dias)
    clave = ("posthog", dias)
    if clave in _CACHE and time.time() - _CACHE[clave][0] < _TTL:
        return _CACHE[clave][1]
    d = int(dias)
    agentes = "distinct_id LIKE 'agente-%'"
    try:
        pasos = dict((e, int(n)) for e, n in _hogql(f"""
            SELECT event, count(DISTINCT distinct_id) FROM events
            WHERE timestamp > now() - INTERVAL {d} DAY AND {agentes}
              AND event IN ({", ".join(repr(p) for p in PASOS_WEB)})
            GROUP BY event"""))
        por_dia = [{"dia": str(f[0]), "web": int(f[1]), "mcp": int(f[2]), "agentes": int(f[3])} for f in _hogql(f"""
            SELECT toDate(timestamp) AS dia, countIf(event != 'mcp_herramienta'), countIf(event = 'mcp_herramienta'),
                   count(DISTINCT distinct_id)
            FROM events WHERE timestamp > now() - INTERVAL {d} DAY AND {agentes}
            GROUP BY dia ORDER BY dia""")]
        paginas = [{"pagina": f[0] or "/", "vistas": int(f[1]), "agentes": int(f[2])} for f in _hogql(f"""
            SELECT properties.$pathname AS p, count(), count(DISTINCT distinct_id) FROM events
            WHERE event = '$pageview' AND timestamp > now() - INTERVAL {d} DAY AND {agentes}
            GROUP BY p ORDER BY count() DESC LIMIT 15""")]
        eventos = [{"evento": f[0], "total": int(f[1]), "agentes": int(f[2])} for f in _hogql(f"""
            SELECT event, count(), count(DISTINCT distinct_id) FROM events
            WHERE timestamp > now() - INTERVAL {d} DAY AND {agentes} AND event NOT LIKE '$%'
            GROUP BY event ORDER BY count() DESC LIMIT 20""")]
        res = {"configurado": True, "fuente": "posthog", "dias": d,
               "embudo": [{"paso": p, "agentes": pasos.get(p, 0)} for p in PASOS_WEB],
               "por_dia": por_dia, "paginas": paginas, "eventos": eventos}
    except Exception as e:  # noqa: BLE001
        return {"configurado": True, "error": f"PostHog no respondió: {str(e)[:160]}"}
    _CACHE[clave] = (time.time(), res)
    return res
