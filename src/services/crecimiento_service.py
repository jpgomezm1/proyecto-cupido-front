"""
Trazabilidad del negocio para el admin (Admin › Crecimiento): de dónde vienen los
agentes, si se quedan y cómo se mueven los ingresos. Solo lectura, sin IA.

- `embudo(dias)`: por canal, de la cuenta al pago.
- `cohortes(semanas)`: por la semana en que el agente entró por primera vez (no la de
  creación: las cuentas precargadas cuentan cuando de verdad entran).
- `ingresos(meses)`: movimientos del MRR por mes, lo cobrado por tipo, lo que vence,
  fundadores y el doble de llaves del lanzamiento.

El canal de cada agente sale de lo que ya se sabe, en este orden: fundador (tuvo ese
plan), ventas (la línea de ventas le escribió), red (cuenta precargada), lo que dijo el
registro (`eventos_uso` cuenta_creada → desde: compartido, instagram, landing…) y si no,
directo.
"""
from typing import Any, Dict, List

from src.services.db import fetch_all, get_db

CANALES = {
    "fundador": "Fundadores",
    "ventas": "WhatsApp de ventas",
    "red": "Red (precargadas)",
    "compartido": "Páginas compartidas",
    "instagram": "Instagram",
    "landing": "Landing",
    "pagina_agente": "Página de un agente",
    "informe": "Informe de captación",
    "directo": "Directo",
}

# Cuentas internas y de pruebas: no cuentan.
_EXCLUIR = "COALESCE(u.origen, '') <> 'prueba_ui' AND u.email NOT ILIKE '%%@fynder.test' AND u.eliminada_at IS NULL"
_TEL10 = "RIGHT(REGEXP_REPLACE(COALESCE({c},''),'[^0-9]','','g'),10)"

# Una fila por agente con su canal, cuándo entró y qué hizo. La comparten embudo y cohortes.
_AGENTES = f"""
WITH actividad AS (
    SELECT user_id, fecha AS t FROM chat_usage_log
    UNION ALL SELECT user_id, created_at FROM eventos_uso
    UNION ALL SELECT user_id, created_at FROM mcp_tool_calls
),
registro AS (
    SELECT DISTINCT ON (user_id) user_id, props->>'desde' AS desde
    FROM eventos_uso WHERE evento = 'cuenta_creada' ORDER BY user_id, created_at
),
pagado AS (
    SELECT user_id, MIN(created_at) AS primero, SUM(monto_cop) AS total
    FROM pagos WHERE estado = 'aprobado' GROUP BY user_id
)
SELECT u.id, u.fecha_creacion,
       (SELECT MIN(a.t) FROM actividad a WHERE a.user_id = u.id) AS entro,
       u.telefono_verificado AS verificado,
       EXISTS (SELECT 1 FROM conversaciones_busqueda c WHERE c.user_id = u.id)
         OR EXISTS (SELECT 1 FROM mcp_tool_calls m WHERE m.user_id = u.id AND m.ok AND m.tool = 'search_properties') AS busco,
       EXISTS (SELECT 1 FROM desbloqueos d WHERE d.user_id = u.id) AS contacto,
       p.primero IS NOT NULL
         OR EXISTS (SELECT 1 FROM suscripciones s WHERE s.user_id = u.id AND s.plan_codigo NOT IN ('prueba', 'fundador')
                    AND s.precio_cop > 0) AS pago,
       COALESCE(p.total, 0) AS ingresos,
       CASE
         WHEN EXISTS (SELECT 1 FROM suscripciones s WHERE s.user_id = u.id AND s.plan_codigo = 'fundador') THEN 'fundador'
         WHEN EXISTS (SELECT 1 FROM ventas_agentes v WHERE v.enviado_at IS NOT NULL
                        AND (v.user_id = u.id OR (v.telefono_10 <> '' AND v.telefono_10 = {_TEL10.format(c='u.telefono')}))) THEN 'ventas'
         WHEN u.origen = 'provision' THEN 'red'
         WHEN r.desde IN ('compartido', 'instagram', 'landing', 'pagina_agente', 'informe') THEN r.desde
         ELSE 'directo'
       END AS canal
FROM chat_users u
LEFT JOIN registro r ON r.user_id = u.id
LEFT JOIN pagado p ON p.user_id = u.id
WHERE {_EXCLUIR}
"""


def embudo(dias: int = 90) -> Dict[str, Any]:
    """Por canal: cuentas creadas (o que entraron) en la ventana y cuántas llegaron a cada paso."""
    d = int(dias)
    with get_db() as db:
        filas = fetch_all(db.cursor, f"""
            WITH ag AS ({_AGENTES})
            SELECT canal,
                   COUNT(*)                                   AS cuentas,
                   COUNT(*) FILTER (WHERE entro IS NOT NULL)  AS entraron,
                   COUNT(*) FILTER (WHERE verificado)         AS verificaron,
                   COUNT(*) FILTER (WHERE busco)              AS buscaron,
                   COUNT(*) FILTER (WHERE contacto)           AS contacto,
                   COUNT(*) FILTER (WHERE pago)               AS pagaron,
                   COALESCE(SUM(ingresos), 0)                 AS ingresos
            FROM ag
            WHERE fecha_creacion > NOW() - (%s * INTERVAL '1 day')
               OR entro > NOW() - (%s * INTERVAL '1 day')
            GROUP BY canal
        """, (d, d))
        # Arriba del embudo de «compartido»: las vistas y el clic en «¿Eres agente?».
        share = fetch_all(db.cursor, """
            SELECT event_type, COUNT(*) AS n, COUNT(DISTINCT visitor_id) AS personas
            FROM share_events
            WHERE created_at > NOW() - (%s * INTERVAL '1 day') AND event_type IN ('share_viewed', 'signup_clicked')
            GROUP BY event_type
        """, (d,))
    por_canal = {f["canal"]: f for f in filas}
    canales = [{"canal": c, "nombre": n, **{k: int(v) for k, v in por_canal[c].items() if k != "canal"}}
               for c, n in CANALES.items() if c in por_canal]
    canales.sort(key=lambda f: (-f["pagaron"], -f["cuentas"]))
    s = {f["event_type"]: f for f in share}
    return {
        "dias": d,
        "canales": canales,
        "total": {k: sum(c[k] for c in canales) for k in
                  ("cuentas", "entraron", "verificaron", "buscaron", "contacto", "pagaron", "ingresos")},
        "compartido_arriba": {
            "vistas": int((s.get("share_viewed") or {}).get("n") or 0),
            "personas": int((s.get("share_viewed") or {}).get("personas") or 0),
            "clic_registro": int((s.get("signup_clicked") or {}).get("n") or 0),
        },
    }


def cohortes(semanas: int = 10) -> Dict[str, Any]:
    """Por semana del primer ingreso: cuántos volvieron 1, 2 y 4 semanas después, abrieron contacto y pagaron."""
    k = int(semanas)
    with get_db() as db:
        filas = fetch_all(db.cursor, f"""
            WITH ag AS ({_AGENTES}),
            act AS (
                SELECT user_id, date_trunc('week', fecha) AS semana FROM chat_usage_log
                UNION SELECT user_id, date_trunc('week', created_at) FROM eventos_uso
                UNION SELECT user_id, date_trunc('week', created_at) FROM mcp_tool_calls
            ),
            c AS (SELECT id, date_trunc('week', entro) AS cohorte, contacto, pago FROM ag WHERE entro IS NOT NULL)
            SELECT c.cohorte,
                   COUNT(*) AS agentes,
                   COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM act a WHERE a.user_id = c.id AND a.semana = c.cohorte + INTERVAL '1 week')) AS s1,
                   COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM act a WHERE a.user_id = c.id AND a.semana = c.cohorte + INTERVAL '2 week')) AS s2,
                   COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM act a WHERE a.user_id = c.id AND a.semana = c.cohorte + INTERVAL '4 week')) AS s4,
                   COUNT(*) FILTER (WHERE contacto) AS contacto,
                   COUNT(*) FILTER (WHERE pago) AS pago,
                   (c.cohorte + INTERVAL '1 week' <= date_trunc('week', NOW())) AS cerrada_s1,
                   (c.cohorte + INTERVAL '2 week' <= date_trunc('week', NOW())) AS cerrada_s2,
                   (c.cohorte + INTERVAL '4 week' <= date_trunc('week', NOW())) AS cerrada_s4
            FROM c
            WHERE c.cohorte >= date_trunc('week', NOW()) - (%s * INTERVAL '1 week')
            GROUP BY c.cohorte ORDER BY c.cohorte DESC
        """, (k,))
    salida = []
    for f in filas:
        n = int(f["agentes"])
        fila = {"semana": f["cohorte"].date().isoformat(), "agentes": n,
                "contacto": int(f["contacto"]), "pago": int(f["pago"])}
        # Una semana que todavía no termina no es «0 % volvieron»: va vacía.
        for s in ("s1", "s2", "s4"):
            fila[s] = int(f[s]) if f[f"cerrada_{s}"] else None
        salida.append(fila)
    return {"semanas": k, "cohortes": salida}


def ingresos(meses: int = 6) -> Dict[str, Any]:
    """Movimientos del MRR por mes, lo cobrado por tipo y lo que hay que vigilar."""
    m = int(meses)
    with get_db() as db:
        cur = db.cursor
        movimientos = fetch_all(cur, """
            WITH pagas AS (
                SELECT s.*, LAG(s.fin) OVER (PARTITION BY s.user_id ORDER BY s.inicio) AS fin_anterior,
                       LEAD(s.inicio) OVER (PARTITION BY s.user_id ORDER BY s.inicio) AS inicio_siguiente
                FROM suscripciones s
                WHERE s.plan_codigo NOT IN ('prueba') AND s.precio_cop > 0
            ),
            meses AS (
                SELECT generate_series(date_trunc('month', NOW()) - ((%s - 1) * INTERVAL '1 month'),
                                       date_trunc('month', NOW()), INTERVAL '1 month') AS mes
            )
            SELECT to_char(mes, 'YYYY-MM') AS mes,
              COALESCE((SELECT SUM(precio_cop) FROM pagas WHERE date_trunc('month', inicio) = mes AND fin_anterior IS NULL), 0) AS nuevo,
              COALESCE((SELECT SUM(precio_cop) FROM pagas WHERE date_trunc('month', inicio) = mes AND fin_anterior IS NOT NULL), 0) AS renovado,
              COALESCE((SELECT SUM(precio_cop) FROM pagas
                        WHERE date_trunc('month', COALESCE(gracia_hasta, fin)) = mes AND COALESCE(gracia_hasta, fin) < NOW()
                          AND inicio_siguiente IS NULL), 0) AS perdido,
              (SELECT COUNT(*) FROM pagas WHERE date_trunc('month', inicio) = mes AND fin_anterior IS NULL) AS nuevos,
              (SELECT COUNT(*) FROM pagas WHERE date_trunc('month', COALESCE(gracia_hasta, fin)) = mes
                 AND COALESCE(gracia_hasta, fin) < NOW() AND inicio_siguiente IS NULL) AS perdidos
            FROM meses ORDER BY mes
        """, (m,))
        cobrado = fetch_all(cur, """
            SELECT to_char(date_trunc('month', p.created_at), 'YYYY-MM') AS mes, COALESCE(pl.tipo, 'otro') AS tipo,
                   SUM(p.monto_cop) AS total, COUNT(*) AS pagos
            FROM pagos p LEFT JOIN planes pl ON pl.codigo = p.plan_codigo
            WHERE p.estado = 'aprobado' AND p.created_at >= date_trunc('month', NOW()) - ((%s - 1) * INTERVAL '1 month')
            GROUP BY 1, 2 ORDER BY 1, 2
        """, (m,))
        vigilar = fetch_all(cur, """
            SELECT s.user_id, u.nombre, u.telefono, s.plan_codigo, pl.nombre AS plan, s.precio_cop, s.fin, s.gracia_hasta,
                   CASE WHEN s.fin <= NOW() THEN 'en_gracia' ELSE 'vence' END AS estado
            FROM suscripciones s
            JOIN chat_users u ON u.id = s.user_id
            LEFT JOIN planes pl ON pl.codigo = s.plan_codigo
            WHERE s.estado = 'activa' AND s.plan_codigo <> 'prueba'
              AND ((s.fin BETWEEN NOW() AND NOW() + INTERVAL '7 days')
                   OR (s.fin <= NOW() AND COALESCE(s.gracia_hasta, s.fin) > NOW()))
              AND NOT EXISTS (SELECT 1 FROM suscripciones s2 WHERE s2.user_id = s.user_id AND s2.inicio > s.inicio)
            ORDER BY s.fin
        """)
        resumen = fetch_all(cur, """
            SELECT
              (SELECT COUNT(DISTINCT user_id) FROM suscripciones WHERE plan_codigo = 'fundador') AS fundadores,
              (SELECT COUNT(DISTINCT user_id) FROM suscripciones WHERE plan_codigo = 'fundador' AND estado = 'activa'
                 AND COALESCE(gracia_hasta, fin) > NOW()) AS fundadores_activos,
              (SELECT COUNT(*) FROM suscripciones WHERE COALESCE(bono_lanzamiento, 0) > 0) AS con_doble,
              (SELECT COALESCE(SUM(precio_cop), 0) FROM suscripciones WHERE estado = 'activa' AND plan_codigo <> 'prueba'
                 AND COALESCE(gracia_hasta, fin) > NOW()) AS mrr
        """)[0]
    from src.services.fundador_service import CUPOS
    return {
        "meses": m,
        "movimientos": [{k: (int(v) if k != "mes" else v) for k, v in f.items()} for f in movimientos],
        "cobrado": [{"mes": f["mes"], "tipo": f["tipo"], "total": int(f["total"]), "pagos": int(f["pagos"])} for f in cobrado],
        "vigilar": [{**f, "fin": f["fin"].isoformat() if f["fin"] else None,
                     "gracia_hasta": f["gracia_hasta"].isoformat() if f["gracia_hasta"] else None,
                     "precio_cop": int(f["precio_cop"] or 0)} for f in vigilar],
        "mrr": int(resumen["mrr"] or 0),
        "fundadores": {"cupos": CUPOS, "usados": int(resumen["fundadores"] or 0),
                       "activos": int(resumen["fundadores_activos"] or 0)},
        "doble_llaves": int(resumen["con_doble"] or 0),
    }


def canales() -> List[Dict[str, str]]:
    return [{"canal": c, "nombre": n} for c, n in CANALES.items()]
