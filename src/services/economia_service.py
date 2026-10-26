"""
La economía del negocio para el admin (Admin › Crecimiento): lo que Fynder debe en llaves
y Fyns, y cuánto deja cada agente. Solo lectura, sin IA.

- `llaves_y_fyns()`: llaves emitidas por origen y usadas, el saldo pendiente (un pasivo:
  contactos que Fynder ya prometió) y los Fyns en circulación con su equivalente en llaves.
- `rentabilidad(dias)`: por agente, lo que pagó contra lo que cuesta atenderlo. El costo
  directo es lo atribuible a cada uno (modo Análisis, fotos con IA y sus búsquedas a costo
  promedio); el de la plataforma (anonimizar avisos, fichas, embeddings) se muestra aparte
  porque no depende de cuántos agentes haya.
"""
import os
from typing import Any, Dict

from src.services.db import fetch_all, fetch_one, get_db

TRM = float(os.getenv("FYNDER_TRM_COP", "4000"))
COSTO_FOTO_USD = float(os.getenv("FYNDER_COSTO_FOTO_USD", "0.12"))  # fotos_ia_service: ~USD 0,10–0,13
# Tipos de uso de IA que salen de la búsqueda de un agente (el resto es procesar inventario).
_USOS_BUSQUEDA = ("search_extraction", "search_criteria_extraction", "description_improvement", "transcription")
_EXCLUIR = "COALESCE(u.origen, '') <> 'prueba_ui' AND u.email NOT ILIKE '%%@fynder.test' AND u.eliminada_at IS NULL"


def llaves_y_fyns() -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        # Origen de cada abono de llaves sueltas (no vencen): prueba, logro, canje de Fyns, regalo o compra.
        origenes = fetch_all(cur, """
            SELECT CASE
                     WHEN tipo = 'prueba' THEN 'prueba'
                     WHEN tipo = 'premio' AND referencia LIKE 'fyns:%%' THEN 'canje_fyns'
                     WHEN tipo = 'premio' THEN 'logro'
                     WHEN tipo = 'extra' AND creado_por IN ('admin') AND COALESCE(referencia, '') NOT ILIKE '%%pago%%' THEN 'regalo'
                     WHEN tipo = 'extra' THEN 'compra'
                     ELSE 'ajuste'
                   END AS origen,
                   SUM(cantidad) AS llaves, COUNT(DISTINCT user_id) AS agentes
            FROM creditos_movimientos GROUP BY 1
        """)
        usadas = fetch_one(cur, """
            SELECT COUNT(*) FILTER (WHERE fuente_credito = 'saldo' AND estado = 'vigente') AS de_saldo,
                   COUNT(*) FILTER (WHERE fuente_credito = 'plan' AND estado = 'vigente') AS de_plan,
                   COUNT(*) FILTER (WHERE estado = 'reembolsado') AS reembolsadas,
                   COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '30 days' AND estado = 'vigente') AS ultimos_30
            FROM desbloqueos
        """)
        # Pasivo: llaves sueltas sin usar (por agente, nunca negativo) + las del plan vigente sin usar.
        pasivo = fetch_one(cur, """
            WITH abonos AS (SELECT user_id, SUM(cantidad) AS n FROM creditos_movimientos GROUP BY user_id),
                 gastos AS (SELECT user_id, COUNT(*) AS n FROM desbloqueos
                            WHERE fuente_credito = 'saldo' AND estado = 'vigente' GROUP BY user_id),
                 vigentes AS (
                    SELECT DISTINCT ON (s.user_id) s.id, s.desbloqueos_incluidos
                    FROM suscripciones s
                    WHERE s.estado = 'activa' AND s.inicio <= NOW() AND NOW() < COALESCE(s.gracia_hasta, s.fin)
                    ORDER BY s.user_id, s.inicio DESC)
            SELECT
              (SELECT COALESCE(SUM(GREATEST(a.n - COALESCE(g.n, 0), 0)), 0)
                 FROM abonos a LEFT JOIN gastos g ON g.user_id = a.user_id) AS sueltas,
              (SELECT COALESCE(SUM(GREATEST(v.desbloqueos_incluidos - (
                    SELECT COUNT(*) FROM desbloqueos d
                    WHERE d.suscripcion_id = v.id AND d.fuente_credito = 'plan' AND d.estado = 'vigente'), 0)), 0)
                 FROM vigentes v) AS del_plan
        """)
        fyns = fetch_one(cur, """
            SELECT COALESCE(SUM(cantidad), 0) AS circulacion,
                   COALESCE(SUM(cantidad) FILTER (WHERE cantidad > 0 AND created_at > date_trunc('month', NOW())), 0) AS emitidos_mes,
                   COALESCE(-SUM(cantidad) FILTER (WHERE cantidad < 0 AND created_at > date_trunc('month', NOW())), 0) AS canjeados_mes,
                   COUNT(DISTINCT user_id) FILTER (WHERE cantidad > 0) AS agentes
            FROM fyns_movimientos
        """)
        llave = fetch_one(cur, "SELECT precio_cop FROM planes WHERE codigo = 'llave'") or {}
    precio_llave = int(llave.get("precio_cop") or 12000)
    sueltas, del_plan = int(pasivo["sueltas"] or 0), int(pasivo["del_plan"] or 0)
    circulacion = int(fyns["circulacion"] or 0)
    return {
        "emitidas": [{"origen": f["origen"], "llaves": int(f["llaves"] or 0), "agentes": int(f["agentes"] or 0)}
                     for f in origenes],
        "usadas": {k: int(v or 0) for k, v in usadas.items()},
        "pasivo": {"sueltas": sueltas, "del_plan": del_plan, "total": sueltas + del_plan,
                   "valor_cop": (sueltas + del_plan) * precio_llave, "precio_llave": precio_llave},
        "fyns": {"circulacion": circulacion, "en_llaves": circulacion // 100,
                 "emitidos_mes": int(fyns["emitidos_mes"] or 0), "canjeados_mes": int(fyns["canjeados_mes"] or 0),
                 "agentes": int(fyns["agentes"] or 0)},
    }


def rentabilidad(dias: int = 30) -> Dict[str, Any]:
    d = int(dias)
    with get_db() as db:
        cur = db.cursor
        # Costo promedio de una búsqueda: la IA de búsqueda del periodo entre las búsquedas hechas.
        base = fetch_one(cur, f"""
            SELECT
              (SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM ai_usage_log
                 WHERE created_at > NOW() - (%s * INTERVAL '1 day') AND usage_type = ANY(%s)) AS ia_busqueda,
              (SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM ai_usage_log
                 WHERE created_at > NOW() - (%s * INTERVAL '1 day') AND NOT (usage_type = ANY(%s))) AS ia_plataforma,
              (SELECT COALESCE(SUM(busquedas), 0) FROM uso_diario
                 WHERE fecha > (NOW() - (%s * INTERVAL '1 day'))::date) AS busquedas
        """, (d, list(_USOS_BUSQUEDA), d, list(_USOS_BUSQUEDA), d))
        busquedas_total = int(base["busquedas"] or 0)
        costo_busqueda_usd = float(base["ia_busqueda"] or 0) / busquedas_total if busquedas_total else 0.0
        filas = fetch_all(cur, f"""
            SELECT u.id, u.nombre,
              COALESCE((SELECT SUM(monto_cop) FROM pagos p WHERE p.user_id = u.id AND p.estado = 'aprobado'
                          AND p.created_at > NOW() - (%(d)s * INTERVAL '1 day')), 0) AS ingresos,
              COALESCE((SELECT SUM(costo_usd) FROM analisis_ia a WHERE a.user_id = u.id
                          AND a.created_at > NOW() - (%(d)s * INTERVAL '1 day')), 0) AS analisis_usd,
              (SELECT COUNT(*) FROM fotos_mejoradas f WHERE f.user_id = u.id AND f.url_mejorada IS NOT NULL
                 AND f.created_at > NOW() - (%(d)s * INTERVAL '1 day')) AS fotos,
              COALESCE((SELECT SUM(busquedas) FROM uso_diario ud WHERE ud.user_id = u.id
                          AND ud.fecha > (NOW() - (%(d)s * INTERVAL '1 day'))::date), 0) AS busquedas,
              (SELECT COUNT(*) FROM desbloqueos de WHERE de.user_id = u.id AND de.estado = 'vigente'
                 AND de.created_at > NOW() - (%(d)s * INTERVAL '1 day')) AS contactos,
              (SELECT pl.nombre FROM suscripciones s JOIN planes pl ON pl.codigo = s.plan_codigo
                 WHERE s.user_id = u.id AND s.estado = 'activa' AND NOW() < COALESCE(s.gracia_hasta, s.fin)
                 ORDER BY s.inicio DESC LIMIT 1) AS plan
            FROM chat_users u
            WHERE {_EXCLUIR}
        """, {"d": d})
    agentes = []
    for f in filas:
        costo_usd = float(f["analisis_usd"] or 0) + int(f["fotos"] or 0) * COSTO_FOTO_USD \
            + int(f["busquedas"] or 0) * costo_busqueda_usd
        if not (f["ingresos"] or costo_usd > 0 or f["contactos"]):
            continue
        costo = round(costo_usd * TRM)
        ingresos = int(f["ingresos"] or 0)
        agentes.append({
            "id": f["id"], "nombre": f["nombre"], "plan": f["plan"], "ingresos": ingresos, "costo": costo,
            "margen": ingresos - costo, "busquedas": int(f["busquedas"] or 0), "contactos": int(f["contactos"] or 0),
            "fotos": int(f["fotos"] or 0), "analisis_cop": round(float(f["analisis_usd"] or 0) * TRM),
        })
    agentes.sort(key=lambda a: (a["margen"], -a["costo"]))
    ingresos = sum(a["ingresos"] for a in agentes)
    directo = sum(a["costo"] for a in agentes)
    contactos = sum(a["contactos"] for a in agentes)
    plataforma = round(float(base["ia_plataforma"] or 0) * TRM)
    return {
        "dias": d, "trm": TRM,
        "resumen": {
            "ingresos": ingresos, "costo_directo": directo, "costo_plataforma": plataforma,
            "margen_directo": ingresos - directo, "margen_total": ingresos - directo - plataforma,
            "costo_por_contacto": round((directo + plataforma) / contactos) if contactos else None,
            "costo_por_busqueda": round(costo_busqueda_usd * TRM, 1),
        },
        "agentes": agentes,
    }
