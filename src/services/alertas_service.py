"""
Alertas de cruce: Fynder le avisa al agente cuando pasa algo que le sirve.

  - nuevo_inmueble: entró a la red un inmueble que encaja con el perfil de uno de
    sus clientes (mismo puntaje del buscador v3; umbral FYNDER_ALERTA_UMBRAL).
  - baja_precio / sube_precio: cambió el precio de algo que el agente guardó para
    un cliente o en favoritos, o que ahora encaja con un cliente por precio.

Las genera `generar()` (el worker, cada 30 min) a partir de dos cursores: los
inmuebles creados y los cambios de precio aplicados desde la última corrida.
Se ven en la campana de la app y llegan en un resumen por correo (como máximo
cada FYNDER_ALERTA_CORREO_HORAS horas, si el agente no lo apagó).
No hay IA aquí: solo SQL y el puntaje del buscador, así que no tiene costo.
"""

import os
from typing import Any, Dict, List, Optional

from src.services import busqueda
from src.services.db import fetch_all, fetch_one, get_db, scalar

UMBRAL = float(os.getenv("FYNDER_ALERTA_UMBRAL", "72"))
HORAS_CORREO = float(os.getenv("FYNDER_ALERTA_CORREO_HORAS", "12"))
MAX_POR_CLIENTE = 5          # alertas nuevas por cliente en una corrida (lo mejor primero)
_LOCK = 7103


def _m(v) -> str:
    return f"${v / 1e6:,.0f} M".replace(",", ".") if v else ""


# ── lectura ────────────────────────────────────────────────────────────────

def _salida(a: Dict[str, Any], mini: Dict[str, Any]) -> Dict[str, Any]:
    p = mini or {}
    nombre_c = a.get("cliente_nombre")
    lugar = ", ".join(x for x in (p.get("zona"), p.get("ciudad")) if x)
    if a["tipo"] == "nuevo_inmueble":
        titulo = f"Nuevo para {nombre_c}: {p.get('titulo') or 'un inmueble'}"
        detalle = ("Cumple: " + ", ".join(a["razones"][:4])) if a["razones"] else lugar
    else:
        verbo = "Bajó" if a["tipo"] == "baja_precio" else "Subió"
        dif = abs((a["precio_nuevo"] or 0) - (a["precio_anterior"] or 0))
        para = f" · para {nombre_c}" if nombre_c else ""
        titulo = f"{verbo} {_m(dif)}: {p.get('titulo') or 'un inmueble que guardaste'}"
        detalle = f"De {_m(a['precio_anterior'])} a {_m(a['precio_nuevo'])}{para}"
    return {
        "id": a["id"], "tipo": a["tipo"],
        "cliente": {"id": a["cliente_id"], "nombre": nombre_c} if a["cliente_id"] else None,
        "propiedad": mini, "titulo": titulo, "detalle": detalle, "razones": list(a["razones"] or []),
        "score": round(a["score"], 1) if a["score"] is not None else None,
        "precio_anterior": int(a["precio_anterior"]) if a["precio_anterior"] else None,
        "precio_nuevo": int(a["precio_nuevo"]) if a["precio_nuevo"] else None,
        "leida": a["leida_at"] is not None, "created_at": a["created_at"].isoformat(),
    }


def listar(user_id: int, no_leidas: bool = False, limite: int = 30,
           cliente_id: Optional[int] = None) -> List[Dict[str, Any]]:
    from src.services.clientes_service import propiedades_mini
    cond, params = ["a.user_id = %s"], [user_id]
    if no_leidas:
        cond.append("a.leida_at IS NULL")
    if cliente_id:
        cond.append("a.cliente_id = %s"); params.append(cliente_id)
    params.append(max(1, min(int(limite or 30), 100)))
    with get_db() as db:
        filas = fetch_all(db.cursor, f"""
            SELECT a.*, c.nombre AS cliente_nombre FROM alertas a
            LEFT JOIN clientes_agente c ON c.id = a.cliente_id
            WHERE {' AND '.join(cond)} ORDER BY a.created_at DESC LIMIT %s
        """, params)
    minis = propiedades_mini([f["propiedad_id"] for f in filas])
    return [_salida(f, minis.get(f["propiedad_id"])) for f in filas if f["propiedad_id"] in minis]


def resumen(user_id: int) -> Dict[str, Any]:
    with get_db() as db:
        n = scalar(db.cursor, "SELECT COUNT(*) FROM alertas WHERE user_id = %s AND leida_at IS NULL", (user_id,)) or 0
    return {"no_leidas": int(n)}


def marcar_leidas(user_id: int, ids: Optional[List[int]] = None, todas: bool = False) -> Dict[str, Any]:
    with get_db() as db:
        if todas:
            db.cursor.execute("UPDATE alertas SET leida_at = NOW() WHERE user_id = %s AND leida_at IS NULL", (user_id,))
        elif ids:
            db.cursor.execute("UPDATE alertas SET leida_at = NOW() WHERE user_id = %s AND id = ANY(%s) AND leida_at IS NULL",
                              (user_id, [int(i) for i in ids]))
        db.conn.commit()
    return {"ok": True}


def preferencias(user_id: int, correo: Optional[bool] = None) -> Dict[str, Any]:
    with get_db() as db:
        if correo is not None:
            db.cursor.execute("UPDATE chat_users SET alertas_correo = %s WHERE id = %s", (bool(correo), user_id))
            db.conn.commit()
        v = scalar(db.cursor, "SELECT alertas_correo FROM chat_users WHERE id = %s", (user_id,))
    return {"correo": bool(v)}


# ── generación (worker) ────────────────────────────────────────────────────

def _cursor(cur, clave: str):
    return scalar(cur, "SELECT valor FROM alertas_cursor WHERE clave = %s", (clave,))


def _clientes_activos(cur) -> List[Dict[str, Any]]:
    return fetch_all(cur, """
        SELECT c.id, c.user_id, c.nombre, c.perfil FROM clientes_agente c
        JOIN chat_users u ON u.id = c.user_id AND u.activo
        WHERE c.estado = 'activo' AND c.alertas AND c.perfil <> '{}'::jsonb
    """)


def _puntuar(cliente: Dict[str, Any], ids: List[int]) -> List[Dict[str, Any]]:
    """Inmuebles de `ids` que encajan con el perfil del cliente, mejor primero."""
    ped = dict(cliente["perfil"] or {})
    if not busqueda.chips(ped) or not ids:
        return []
    cands = busqueda._candidatos(ped, None, ids=ids)
    if not cands:
        return []
    ub = busqueda._ubicaciones(ped)
    out = []
    for p in cands:
        r = busqueda._puntuar(p, ped, ub)
        if r and r["score"] >= UMBRAL:
            r.pop("_p", None)
            out.append(r)
    return sorted(out, key=lambda r: r["score"], reverse=True)


def _insertar(cur, user_id, cliente_id, tipo, propiedad_id, score=None, razones=None,
              anterior=None, nuevo=None) -> bool:
    cur.execute("""
        INSERT INTO alertas (user_id, cliente_id, tipo, propiedad_id, score, razones, precio_anterior, precio_nuevo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING RETURNING id
    """, (user_id, cliente_id, tipo, propiedad_id, score, list(razones or []), anterior, nuevo))
    return cur.fetchone() is not None


def generar(max_inmuebles: int = 400) -> Dict[str, int]:
    """Alertas por inmuebles nuevos y cambios de precio desde la última corrida."""
    creadas = {"nuevo_inmueble": 0, "baja_precio": 0, "sube_precio": 0}
    with get_db() as db:
        cur = db.cursor
        if not scalar(cur, "SELECT pg_try_advisory_lock(%s)", (_LOCK,)):
            return {"omitido": 1}
        try:
            desde_i, desde_p = _cursor(cur, "inmuebles"), _cursor(cur, "precios")
            nuevos = fetch_all(cur, """
                SELECT id, fecha_creacion FROM propiedades
                WHERE activa AND fecha_creacion > %s ORDER BY fecha_creacion LIMIT %s
            """, (desde_i, max_inmuebles))
            cambios = fetch_all(cur, """
                SELECT DISTINCT ON (propiedad_id) propiedad_id, precio_anterior, precio_nuevo, created_at
                FROM cambios_precio WHERE aplicado AND created_at > %s
                ORDER BY propiedad_id, created_at DESC
            """, (desde_p,))
            clientes = _clientes_activos(cur)

            # 1) Inmuebles nuevos que encajan con un cliente.
            ids_nuevos = [n["id"] for n in nuevos]
            for c in clientes:
                for r in _puntuar(c, ids_nuevos)[:MAX_POR_CLIENTE]:
                    if _insertar(cur, c["user_id"], c["id"], "nuevo_inmueble", r["id"], r["score"], r["cumple"]):
                        creadas["nuevo_inmueble"] += 1
                        cur.execute("""
                            INSERT INTO cliente_inmuebles (cliente_id, propiedad_id, estado, origen, score, razones)
                            VALUES (%s, %s, 'sugerido', 'alerta', %s, %s) ON CONFLICT DO NOTHING
                        """, (c["id"], r["id"], r["score"], r["cumple"]))

            # 2) Cambios de precio.
            for ch in cambios:
                pid, ant, nue = ch["propiedad_id"], ch["precio_anterior"], ch["precio_nuevo"]
                if not ant or not nue or ant == nue:
                    continue
                tipo = "baja_precio" if nue < ant else "sube_precio"
                avisados = set()
                # a) Lo guardó para un cliente (y no lo descartó).
                for f in fetch_all(cur, """
                    SELECT c.user_id, c.id AS cliente_id FROM cliente_inmuebles i
                    JOIN clientes_agente c ON c.id = i.cliente_id
                    WHERE i.propiedad_id = %s AND i.estado <> 'descartado' AND c.estado = 'activo'
                """, (pid,)):
                    if _insertar(cur, f["user_id"], f["cliente_id"], tipo, pid, anterior=ant, nuevo=nue):
                        creadas[tipo] += 1
                    avisados.add(f["user_id"])
                # b) Lo tiene en favoritos (solo bajas: una subida en favoritos no es noticia accionable).
                if tipo == "baja_precio":
                    for f in fetch_all(cur, "SELECT DISTINCT user_id FROM chat_user_favorites WHERE propiedad_id = %s", (pid,)):
                        if f["user_id"] not in avisados and _insertar(cur, f["user_id"], None, tipo, pid, anterior=ant, nuevo=nue):
                            creadas[tipo] += 1
                            avisados.add(f["user_id"])
                    # c) Con el precio nuevo ahora encaja con un cliente.
                    for c in clientes:
                        if c["user_id"] in avisados:
                            continue
                        r = _puntuar(c, [pid])
                        if r and _insertar(cur, c["user_id"], c["id"], tipo, pid, r[0]["score"], r[0]["cumple"], ant, nue):
                            creadas[tipo] += 1

            if nuevos:
                cur.execute("UPDATE alertas_cursor SET valor = %s WHERE clave = 'inmuebles'", (nuevos[-1]["fecha_creacion"],))
            if cambios:
                cur.execute("UPDATE alertas_cursor SET valor = %s WHERE clave = 'precios'",
                            (max(ch["created_at"] for ch in cambios),))
            db.conn.commit()
        finally:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_LOCK,))
            db.conn.commit()
    return creadas


# ── resumen por correo ─────────────────────────────────────────────────────

def enviar_resumenes() -> Dict[str, int]:
    """Un correo por agente con las alertas nuevas que no ha visto, como máximo cada HORAS_CORREO."""
    from src.services import correo_service
    enviados = 0
    with get_db() as db:
        cur = db.cursor
        usuarios = fetch_all(cur, f"""
            SELECT u.id, u.nombre, u.email FROM chat_users u
            WHERE u.activo AND u.alertas_correo AND u.email IS NOT NULL
              AND (u.alertas_correo_at IS NULL OR u.alertas_correo_at < NOW() - INTERVAL '{float(HORAS_CORREO)} hours')
              AND EXISTS (SELECT 1 FROM alertas a WHERE a.user_id = u.id AND a.correo_at IS NULL AND a.leida_at IS NULL
                          AND a.created_at > NOW() - INTERVAL '3 days')
        """)
    for u in usuarios:
        alertas = [a for a in listar(u["id"], no_leidas=True, limite=40)]
        with get_db() as db:
            pendientes = {f["id"] for f in fetch_all(db.cursor, """
                SELECT id FROM alertas WHERE user_id = %s AND correo_at IS NULL AND leida_at IS NULL
            """, (u["id"],))}
        alertas = [a for a in alertas if a["id"] in pendientes]
        if not alertas:
            continue
        try:
            correo_service.resumen_alertas(u["nombre"], u["email"], alertas)
        except Exception as e:  # noqa: BLE001 — un correo fallido no frena a los demás
            print(f"[ALERTAS] correo a {u['id']} falló: {e}")
            continue
        with get_db() as db:
            db.cursor.execute("UPDATE alertas SET correo_at = NOW() WHERE id = ANY(%s)", ([a["id"] for a in alertas],))
            db.cursor.execute("UPDATE chat_users SET alertas_correo_at = NOW() WHERE id = %s", (u["id"],))
            db.conn.commit()
        enviados += 1
    return {"correos": enviados}
