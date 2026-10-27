"""
En qué etapa está el agente: cuánto ha usado Fynder, para que la app le muestre las
herramientas cuando le sirven y no todas el primer día (oct-2026: 51 agentes buscaron,
2 abrieron un contacto y 7 funciones nunca las había usado nadie).

Solo conteos, sin IA. Las reglas de qué se muestra viven en el frontend
(`useHerramientas`); aquí solo los hechos.
"""
from typing import Any, Dict

from src.services.db import get_db, fetch_one

_PHONE10 = "RIGHT(REGEXP_REPLACE(COALESCE(p.agente_captador_telefono,''),'[^0-9]','','g'),10)"


def resumen(user_id: int, tel10: str = "") -> Dict[str, Any]:
    """`tel10`: los 10 dígitos del celular verificado ('' si no lo está): define «mis inmuebles»."""
    with get_db() as db:
        f = fetch_one(db.cursor, f"""
            SELECT
              (SELECT COUNT(*) FROM conversaciones_busqueda WHERE user_id = %(u)s)
                + (SELECT COUNT(*) FROM mcp_tool_calls WHERE user_id = %(u)s AND ok AND tool = 'search_properties')
                                                                                   AS busquedas,
              (SELECT COUNT(*) FROM chat_user_favorites WHERE user_id = %(u)s)    AS guardados,
              (SELECT COUNT(*) FROM desbloqueos WHERE user_id = %(u)s)            AS contactos,
              (SELECT COUNT(*) FROM clientes_agente WHERE user_id = %(u)s)        AS clientes,
              (SELECT COUNT(*) FROM encargos WHERE user_id = %(u)s)               AS encargos,
              (SELECT COUNT(*) FROM propiedades p WHERE %(t)s <> '' AND {_PHONE10} = %(t)s) AS inmuebles,
              EXISTS (SELECT 1 FROM mcp_tool_calls WHERE user_id = %(u)s)         AS ia,
              EXISTS (SELECT 1 FROM suscripciones s WHERE s.user_id = %(u)s AND s.plan_codigo <> 'prueba'
                        AND s.estado = 'activa')                                    AS plan_pago
        """, {"u": user_id, "t": tel10 or ""}) or {}
        # Propietarios que quieren vender (valorador, migración 063): aparte, para que la
        # etapa no falle si la tabla todavía no existe.
        try:
            from src.services.valorador_service import hay_para
            f = {**f, "propietarios": 1 if hay_para(db.cursor, user_id) else 0}
        except Exception:  # noqa: BLE001
            db.conn.rollback()
            f = {**f, "propietarios": 0}
    return {k: (bool(v) if k in ("ia", "plan_pago") else int(v or 0)) for k, v in f.items()}
