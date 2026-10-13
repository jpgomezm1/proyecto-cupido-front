"""
Fyns: la divisa de Fynder (migración 057).

Se GANAN con los logros de `logros_service` (días de uso, rachas, publicar,
misiones), mucho más desde la IA del agente (MCP) que desde la web, con un tope
mensual según el plan (`planes.fyns_tope_mes`; el de 'prueba' si no tiene plan).
Se CANJEAN aquí por lo del catálogo. No vencen.

La llave sigue siendo lo que abre un contacto: los Fyns no se gastan en
contactos directamente, se cambian por llaves.
"""

from typing import Any, Dict, List

from src.services.db import fetch_all, fetch_one, get_db, scalar

_LOCK_FYNS = 7104
TZ = "America/Bogota"

# Producto → costo en Fyns y qué entrega. Encargos, Vitrina e informes se suman
# cuando existan.
CATALOGO: Dict[str, Dict[str, Any]] = {
    "llave": {"titulo": "1 llave", "costo": 100, "detalle": "Abre un contacto. Queda en tu saldo y no vence."},
    "fotos_5": {"titulo": "5 fotos con IA", "costo": 60, "detalle": "Mejora 5 fotos de tus inmuebles. No vencen."},
}

# Cómo se ganan (lo mismo que paga logros_service; aquí para mostrarlo).
COMO_GANAR: List[Dict[str, Any]] = [
    {"accion": "Un día usando Fynder", "ia": 15, "web": 3},
    {"accion": "7 días seguidos", "ia": 75, "web": 15},
    {"accion": "Subir un inmueble a la red", "ia": 40, "web": 10},
    {"accion": "Conectar tu IA (una vez)", "ia": 300, "web": None},
    {"accion": "Primera consulta desde tu IA (una vez)", "ia": 100, "web": None},
]


class FynsError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def saldo_en(cur, user_id: int) -> int:
    return int(scalar(cur, "SELECT COALESCE(SUM(cantidad), 0) FROM fyns_movimientos WHERE user_id = %s",
                      (user_id,)) or 0)


def tope_mes_en(cur, user_id: int) -> int:
    """Tope de Fyns ganados al mes: el del plan vigente (con gracia) o el de 'prueba'."""
    return int(scalar(cur, """
        SELECT COALESCE(
            (SELECT p.fyns_tope_mes FROM suscripciones s JOIN planes p ON p.codigo = s.plan_codigo
             WHERE s.user_id = %s AND s.estado = 'activa' AND s.inicio <= NOW() AND NOW() < s.gracia_hasta
             ORDER BY s.inicio DESC LIMIT 1),
            (SELECT fyns_tope_mes FROM planes WHERE codigo = 'prueba'), 0)
    """, (user_id,)) or 0)


def ganados_mes_en(cur, user_id: int) -> int:
    return int(scalar(cur, f"""
        SELECT COALESCE(SUM(fyns), 0) FROM logros
        WHERE user_id = %s
          AND created_at >= date_trunc('month', NOW() AT TIME ZONE '{TZ}') AT TIME ZONE '{TZ}'
    """, (user_id,)) or 0)


def _catalogo(saldo: int) -> List[Dict[str, Any]]:
    return [{"producto": k, **v, "alcanza": saldo >= v["costo"]} for k, v in CATALOGO.items()]


def estado(user_id: int) -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        saldo = saldo_en(cur, user_id)
        tope = tope_mes_en(cur, user_id)
        ganados = ganados_mes_en(cur, user_id)
        movs = fetch_all(cur, """
            SELECT m.cantidad, m.motivo, m.referencia, m.created_at, l.codigo, l.con_ia
            FROM fyns_movimientos m
            LEFT JOIN logros l ON m.motivo = 'logro' AND l.id::text = split_part(m.referencia, ':', 2)
            WHERE m.user_id = %s ORDER BY m.created_at DESC LIMIT 15
        """, (user_id,))
    return {
        "saldo": saldo,
        "ganados_mes": ganados,
        "tope_mes": tope,
        "restante_mes": max(0, tope - ganados),
        "catalogo": _catalogo(saldo),
        "como_ganar": COMO_GANAR,
        "movimientos": [{"cantidad": m["cantidad"], "motivo": m["motivo"], "codigo": m.get("codigo"),
                         "producto": m["referencia"] if m["motivo"] == "canje" else None,
                         "con_ia": m.get("con_ia"), "fecha": m["created_at"].isoformat()} for m in movs],
    }


def canjear(user_id: int, producto: str) -> Dict[str, Any]:
    """Cambia Fyns por un producto del catálogo, en una sola transacción."""
    item = CATALOGO.get((producto or "").strip())
    if not item:
        raise FynsError("invalido", "Ese producto no está en el catálogo de Fyns.")
    with get_db() as db:
        cur = db.cursor
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK_FYNS, user_id))
        u = fetch_one(cur, "SELECT id, telefono_verificado FROM chat_users WHERE id = %s AND activo", (user_id,))
        if not u:
            raise FynsError("no_encontrado", "Usuario no encontrado.")
        saldo = saldo_en(cur, user_id)
        if saldo < item["costo"]:
            db.conn.rollback()
            raise FynsError("sin_fyns", f"Te faltan {item['costo'] - saldo} Fyns para {item['titulo']} "
                                        f"(cuesta {item['costo']}; tienes {saldo}).")
        mov = scalar(cur, """
            INSERT INTO fyns_movimientos (user_id, cantidad, motivo, referencia)
            VALUES (%s, %s, 'canje', %s) RETURNING id
        """, (user_id, -item["costo"], producto))
        if producto == "llave":
            cur.execute("""
                INSERT INTO creditos_movimientos (user_id, tipo, cantidad, referencia, creado_por)
                VALUES (%s, 'premio', 1, %s, 'fyns')
            """, (user_id, f"fyns:{mov}"))
        elif producto == "fotos_5":
            cur.execute("""
                INSERT INTO fotos_ia_movimientos (user_id, cantidad, referencia, creado_por)
                VALUES (%s, 5, %s, 'fyns')
            """, (user_id, f"fyns:{mov}"))
        db.conn.commit()
        nuevo = saldo - item["costo"]
    return {"ok": True, "producto": producto, "titulo": item["titulo"], "costo": item["costo"],
            "saldo": nuevo, "catalogo": _catalogo(nuevo)}
