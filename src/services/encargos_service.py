"""
Encargos de Findy y Findy Conecta (migración 058, parte 4).

Un ENCARGO es Findy trabajando solo para el agente:
  - buscar_inmueble: "el mejor inmueble para este cliente" (su perfil).
  - buscar_comprador: "el mejor comprador para este inmueble mío".
El worker (`correr`) lo trabaja cada 30 min con el mismo puntaje del buscador
(sin IA, sin costo) y guarda las mejores contrapartes (`encargo_matches`).
Cuántos encargos activos puede tener sale de `beneficios_service` (+ los cupos
extra canjeados con Fyns).

FINDY CONECTA: sobre un match, el agente pide una PRESENTACIÓN. Si la otra parte
es agente de Fynder (activo, verificado y con términos), recibe la solicitud y
decide; si acepta, ambos reciben el contacto del otro (aceptación doble: cada
parte autoriza en ese momento, Ley 1581). Quien pidió gasta 1 llave (el
desbloqueo normal, con sus reglas: si el inmueble ya no está, no se cobra);
quien recibe el negocio no paga. Con "Findy trabaja por ti" sus solicitudes
llegan marcadas como prioritarias y van primero.
Si la contraparte no es agente de Fynder, se usa el contacto normal (una llave)
o `solicitar_visita`.
"""

from datetime import timedelta
from typing import Any, Dict, List, Optional

from src.services import beneficios_service
from src.services.db import fetch_all, fetch_one, get_db, scalar

MAX_MATCHES = 5            # por encargo y corrida
UMBRAL_INMUEBLE = 72       # puntaje del buscador v3 (0-100)
UMBRAL_COMPRADOR = 70      # puntaje de compradores_service (0-100)
DIAS_RESPUESTA = 7
_LOCK_ENCARGOS = 7106

_SQL_TEL10 = "RIGHT(REGEXP_REPLACE(COALESCE({col}, ''), '[^0-9]', '', 'g'), 10)"


class EncargoError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


# ── cupo ─────────────────────────────────────────────────────────────────────

def cupo_en(cur, user_id: int) -> Dict[str, int]:
    ben = beneficios_service.beneficios_en(cur, user_id)
    extra = int(scalar(cur, "SELECT COUNT(*) FROM encargos_extra WHERE user_id = %s AND hasta > NOW()", (user_id,)) or 0)
    activos = int(scalar(cur, "SELECT COUNT(*) FROM encargos WHERE user_id = %s AND estado = 'activo'", (user_id,)) or 0)
    total = min(beneficios_service.ILIMITADO, ben["encargos"] + extra)
    return {"total": total, "activos": activos, "disponibles": max(0, total - activos), "extra": extra}


def abonar_extra_en(cur, user_id: int, referencia: str, dias: int = 30) -> int:
    """Un cupo extra de encargo por `dias` (canje de Fyns)."""
    return scalar(cur, """
        INSERT INTO encargos_extra (user_id, hasta, referencia) VALUES (%s, NOW() + make_interval(days => %s), %s)
        RETURNING id
    """, (user_id, dias, referencia))


# ── crear / cerrar ───────────────────────────────────────────────────────────

def _es_propia(cur, user_id: int, propiedad_id: int) -> bool:
    return bool(scalar(cur, f"""
        SELECT 1 FROM propiedades p JOIN chat_users u ON u.id = %s AND u.telefono_verificado
        WHERE p.id = %s AND {_SQL_TEL10.format(col='u.telefono')}
            = {_SQL_TEL10.format(col="COALESCE(p.telefono, p.agente_captador_telefono)")}
    """, (user_id, propiedad_id)))


def crear(user_id: int, tipo: str, cliente_id: Optional[int] = None, propiedad_id: Optional[int] = None,
          canal: str = "web") -> Dict[str, Any]:
    if tipo not in ("buscar_inmueble", "buscar_comprador"):
        raise EncargoError("invalido", "El encargo es buscar un inmueble para un cliente o un comprador para un inmueble.")
    with get_db() as db:
        cur = db.cursor
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK_ENCARGOS, user_id))
        if tipo == "buscar_inmueble":
            c = fetch_one(cur, "SELECT id, perfil FROM clientes_agente WHERE id = %s AND user_id = %s", (cliente_id, user_id))
            if not c:
                raise EncargoError("no_encontrado", "Ese cliente no existe.")
            from src.services import busqueda
            if not busqueda.chips(c["perfil"] or {}):
                raise EncargoError("sin_perfil", "Cuéntale a Findy qué busca este cliente antes de encargárselo.")
            propiedad_id = None
        else:
            if not propiedad_id or not _es_propia(cur, user_id, propiedad_id):
                raise EncargoError("no_propia", "Solo puedes encargar compradores para un inmueble tuyo (con tu celular verificado).")
            cliente_id = None
        existe = scalar(cur, """
            SELECT id FROM encargos WHERE user_id = %s AND tipo = %s AND estado = 'activo'
              AND COALESCE(cliente_id, 0) = %s AND COALESCE(propiedad_id, 0) = %s
        """, (user_id, tipo, cliente_id or 0, propiedad_id or 0))
        if existe:
            db.conn.rollback()
            return {"ok": True, "encargo_id": existe, "ya_existia": True}
        cupo = cupo_en(cur, user_id)
        if cupo["disponibles"] <= 0:
            db.conn.rollback()
            if cupo["total"] == 0:
                raise EncargoError("sin_beneficio", "Los encargos de Findy vienen con Negocio, Cierre o Findy trabaja por ti. "
                                                    "También puedes canjear 120 Fyns por un encargo de 30 días.")
            raise EncargoError("sin_cupo", f"Ya tienes {cupo['activos']} encargos activos (tu cupo es {cupo['total']}). "
                                           "Cierra uno o suma más con Findy trabaja por ti o con Fyns.")
        eid = scalar(cur, """
            INSERT INTO encargos (user_id, tipo, cliente_id, propiedad_id, canal) VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (user_id, tipo, cliente_id, propiedad_id, canal if canal in ("web", "mcp") else "web"))
        db.conn.commit()
    trabajar(eid)   # primeros resultados de una vez
    return {"ok": True, "encargo_id": eid, **detalle(user_id, eid)}


def cerrar(user_id: int, encargo_id: int) -> Dict[str, Any]:
    with get_db() as db:
        db.cursor.execute("""
            UPDATE encargos SET estado = 'cerrado', cerrado_at = NOW() WHERE id = %s AND user_id = %s AND estado = 'activo'
        """, (encargo_id, user_id))
        n = db.cursor.rowcount
        db.conn.commit()
    if not n:
        raise EncargoError("no_encontrado", "Ese encargo no existe o ya estaba cerrado.")
    return {"ok": True}


# ── trabajar (worker) ────────────────────────────────────────────────────────

def _buscar_inmuebles(cur, e: Dict[str, Any]) -> List[Dict[str, Any]]:
    from src.services import busqueda
    c = fetch_one(cur, "SELECT perfil FROM clientes_agente WHERE id = %s", (e["cliente_id"],))
    ped = dict((c or {}).get("perfil") or {})
    if not busqueda.chips(ped):
        return []
    descartados = {f["propiedad_id"] for f in fetch_all(cur, """
        SELECT propiedad_id FROM cliente_inmuebles WHERE cliente_id = %s AND estado = 'descartado'
    """, (e["cliente_id"],))}
    ub = busqueda._ubicaciones(ped)
    out = []
    for p in busqueda._candidatos(ped, None):
        r = busqueda._puntuar(p, ped, ub)
        if r and r["score"] >= UMBRAL_INMUEBLE and r["id"] not in descartados:
            out.append({"tipo": "propiedad", "id": r["id"], "score": r["score"], "razones": list(r.get("cumple") or [])[:6]})
    return sorted(out, key=lambda x: x["score"], reverse=True)[:MAX_MATCHES]


def _buscar_compradores(cur, e: Dict[str, Any]) -> List[Dict[str, Any]]:
    from src.services import compradores_service as comp
    from src.services.property_service import get_property
    p = get_property(cur, e["propiedad_id"])
    if not p:
        return []
    res = comp.buscar_compradores(cur, comp._ficha_desde_propiedad(p), user_id=e["user_id"], limit=MAX_MATCHES * 2)
    out = []
    for c in res["compradores"]:
        if c["score"] >= UMBRAL_COMPRADOR:
            out.append({"tipo": "pedido", "id": c["pedido_id"], "score": c["score"],
                        "razones": [r["texto"] for r in c.get("razones") or [] if r.get("ok")][:6]})
    return out[:MAX_MATCHES]


def trabajar(encargo_id: int) -> int:
    """Corre un encargo: guarda las contrapartes nuevas. Devuelve cuántas son nuevas."""
    with get_db() as db:
        cur = db.cursor
        e = fetch_one(cur, "SELECT * FROM encargos WHERE id = %s AND estado = 'activo'", (encargo_id,))
        if not e:
            return 0
        candidatos = _buscar_inmuebles(cur, e) if e["tipo"] == "buscar_inmueble" else _buscar_compradores(cur, e)
        nuevos = 0
        for c in candidatos:
            cur.execute("""
                INSERT INTO encargo_matches (encargo_id, contraparte_tipo, contraparte_id, score, razones)
                VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id
            """, (encargo_id, c["tipo"], c["id"], c["score"], c["razones"]))
            nuevos += 1 if cur.fetchone() else 0
        cur.execute("UPDATE encargos SET ultimo_run_at = NOW() WHERE id = %s", (encargo_id,))
        db.conn.commit()
    return nuevos


def correr() -> Dict[str, int]:
    """Worker: trabaja los encargos activos (los de agentes con cupo vigente) y vence presentaciones viejas."""
    from src.services import job_lock
    if not job_lock.tomar("encargos", minutos=25):
        return {"omitido": 1}
    try:
        with get_db() as db:
            cur = db.cursor
            cur.execute(f"""
                UPDATE presentaciones SET estado = 'vencida', respondida_at = NOW()
                WHERE estado = 'pendiente' AND created_at < NOW() - INTERVAL '{DIAS_RESPUESTA} days'
            """)
            vencidas = cur.rowcount
            encargos = fetch_all(cur, "SELECT id, user_id FROM encargos WHERE estado = 'activo' ORDER BY id")
            db.conn.commit()
        # Si el agente ya no tiene cupo (bajó de plan), solo se trabajan sus encargos más antiguos que caben.
        por_usuario: Dict[int, List[int]] = {}
        for e in encargos:
            por_usuario.setdefault(e["user_id"], []).append(e["id"])
        trabajados = nuevos = 0
        for uid, ids in por_usuario.items():
            with get_db() as db:
                total = cupo_en(db.cursor, uid)["total"]
            for eid in ids[:total]:
                nuevos += trabajar(eid)
                trabajados += 1
        return {"encargos": trabajados, "matches_nuevos": nuevos, "presentaciones_vencidas": vencidas}
    finally:
        job_lock.soltar("encargos")


# ── lectura ─────────────────────────────────────────────────────────────────

def _dueno_de(cur, tipo: str, ref_id: int) -> Optional[Dict[str, Any]]:
    """El agente de Fynder dueño de la contraparte (activo, verificado y con términos), si lo hay."""
    if tipo == "propiedad":
        col = "(SELECT COALESCE(telefono, agente_captador_telefono) FROM propiedades WHERE id = %s)"
    else:
        uid = scalar(cur, "SELECT user_id FROM pedidos WHERE id = %s", (ref_id,))
        if uid:
            return fetch_one(cur, """
                SELECT id, nombre, telefono FROM chat_users
                WHERE id = %s AND activo AND telefono_verificado AND terminos_aceptados_at IS NOT NULL
            """, (uid,))
        col = "(SELECT agente_telefono FROM pedidos WHERE id = %s)"
    return fetch_one(cur, f"""
        SELECT id, nombre, telefono FROM chat_users
        WHERE activo AND telefono_verificado AND terminos_aceptados_at IS NOT NULL
          AND {_SQL_TEL10.format(col='telefono')} = {_SQL_TEL10.format(col=col)}
        LIMIT 1
    """, (ref_id,))


def _match_salida(cur, m: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    from src.services.clientes_service import propiedades_mini
    from src.services.redact import redact_phones
    out = {"id": m["id"], "tipo": m["contraparte_tipo"], "ref_id": m["contraparte_id"], "score": round(m["score"]),
           "razones": list(m["razones"] or []), "estado": m["estado"], "created_at": m["created_at"].isoformat()}
    if m["contraparte_tipo"] == "propiedad":
        out["propiedad"] = propiedades_mini([m["contraparte_id"]]).get(m["contraparte_id"])
    else:
        texto = scalar(cur, "SELECT texto_pedido FROM pedidos WHERE id = %s", (m["contraparte_id"],))
        out["pedido"] = {"id": m["contraparte_id"], "busca": redact_phones(texto or "", cut_signatures=True)}
    dueno = _dueno_de(cur, m["contraparte_tipo"], m["contraparte_id"])
    out["conecta"] = bool(dueno and dueno["id"] != user_id)
    p = fetch_one(cur, "SELECT id, estado FROM presentaciones WHERE match_id = %s", (m["id"],))
    out["presentacion"] = {"id": p["id"], "estado": p["estado"]} if p else None
    return out


def detalle(user_id: int, encargo_id: int) -> Dict[str, Any]:
    from src.services.clientes_service import propiedades_mini
    with get_db() as db:
        cur = db.cursor
        e = fetch_one(cur, """
            SELECT e.*, c.nombre AS cliente_nombre FROM encargos e
            LEFT JOIN clientes_agente c ON c.id = e.cliente_id
            WHERE e.id = %s AND e.user_id = %s
        """, (encargo_id, user_id))
        if not e:
            raise EncargoError("no_encontrado", "Ese encargo no existe.")
        matches = fetch_all(cur, """
            SELECT * FROM encargo_matches WHERE encargo_id = %s AND estado <> 'descartado'
            ORDER BY score DESC, created_at DESC LIMIT 20
        """, (encargo_id,))
        salida = [_match_salida(cur, m, user_id) for m in matches]
    return {
        "id": e["id"], "tipo": e["tipo"], "estado": e["estado"], "canal": e["canal"],
        "cliente": {"id": e["cliente_id"], "nombre": e["cliente_nombre"]} if e["cliente_id"] else None,
        "propiedad": propiedades_mini([e["propiedad_id"]]).get(e["propiedad_id"]) if e["propiedad_id"] else None,
        "ultimo_run_at": e["ultimo_run_at"].isoformat() if e["ultimo_run_at"] else None,
        "created_at": e["created_at"].isoformat(),
        "matches": salida, "nuevos": sum(1 for m in matches if m["estado"] == "nuevo"),
    }


def listar(user_id: int) -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        ids = [r["id"] for r in fetch_all(cur, """
            SELECT id FROM encargos WHERE user_id = %s AND (estado = 'activo' OR cerrado_at > NOW() - INTERVAL '30 days')
            ORDER BY estado, created_at DESC
        """, (user_id,))]
        cupo = cupo_en(cur, user_id)
        ben = beneficios_service.beneficios_en(cur, user_id)
    return {"cupo": cupo, "borroso": ben["borroso"]["encargos"] and cupo["total"] == 0,
            "encargos": [detalle(user_id, i) for i in ids], "presentaciones": presentaciones(user_id)}


def marcar_vistos(user_id: int, encargo_id: int) -> None:
    with get_db() as db:
        db.cursor.execute("""
            UPDATE encargo_matches m SET estado = 'visto' FROM encargos e
            WHERE m.encargo_id = e.id AND e.id = %s AND e.user_id = %s AND m.estado = 'nuevo'
        """, (encargo_id, user_id))
        db.conn.commit()


def descartar_match(user_id: int, match_id: int) -> None:
    with get_db() as db:
        db.cursor.execute("""
            UPDATE encargo_matches m SET estado = 'descartado' FROM encargos e
            WHERE m.encargo_id = e.id AND m.id = %s AND e.user_id = %s AND m.estado <> 'presentacion'
        """, (match_id, user_id))
        db.conn.commit()


# ── Findy Conecta ───────────────────────────────────────────────────────────

def pedir_presentacion(user_id: int, match_id: int, mensaje: Optional[str] = None) -> Dict[str, Any]:
    from src.services import suscripcion_service as s
    with get_db() as db:
        cur = db.cursor
        m = fetch_one(cur, """
            SELECT m.*, e.user_id FROM encargo_matches m JOIN encargos e ON e.id = m.encargo_id
            WHERE m.id = %s AND e.user_id = %s
        """, (match_id, user_id))
        if not m:
            raise EncargoError("no_encontrado", "Esa opción no existe.")
        if scalar(cur, "SELECT 1 FROM presentaciones WHERE match_id = %s", (match_id,)):
            raise EncargoError("ya_pedida", "Ya pediste esta presentación.")
        dueno = _dueno_de(cur, m["contraparte_tipo"], m["contraparte_id"])
    if not dueno or dueno["id"] == user_id:
        raise EncargoError("sin_conecta", "Quien tiene esta opción todavía no es agente de Fynder. Ábrela con una llave "
                                          "o pide a Fynder que coordine la visita.")
    # Que tenga con qué pagar la llave cuando acepten (no se cobra todavía).
    pre = s.preview_desbloqueo(user_id, m["contraparte_tipo"], m["contraparte_id"])
    if pre.get("error") in ("sin_creditos", "terminos_pendientes", "no_disponible", "pedido_vencido"):
        raise EncargoError(pre["error"], pre.get("mensaje") or "No se puede pedir esta presentación ahora.")
    with get_db() as db:
        cur = db.cursor
        prioridad = bool(beneficios_service.beneficios_en(cur, user_id)["prioridad"])
        pid = scalar(cur, """
            INSERT INTO presentaciones (match_id, solicitante_id, receptor_id, prioridad, mensaje)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (match_id, user_id, dueno["id"], prioridad, (mensaje or "").strip()[:500] or None))
        cur.execute("UPDATE encargo_matches SET estado = 'presentacion' WHERE id = %s", (match_id,))
        db.conn.commit()
    _avisar_receptor(pid)
    return {"ok": True, "presentacion_id": pid, "prioridad": prioridad,
            "mensaje": "Le pedimos la presentación. Si acepta, recibes su contacto (usa 1 llave) y él el tuyo."}


def _avisar_receptor(presentacion_id: int) -> None:
    try:
        from src.services import correo_service
        with get_db() as db:
            p = fetch_one(db.cursor, """
                SELECT p.id, u.nombre, COALESCE(NULLIF(TRIM(u.correo_personal), ''), u.email) AS destino
                FROM presentaciones p JOIN chat_users u ON u.id = p.receptor_id WHERE p.id = %s
            """, (presentacion_id,))
        if p:
            correo_service.presentacion_pedida(p["nombre"], p["destino"])
    except Exception as e:  # noqa: BLE001
        print(f"[CONECTA] No se pudo avisar la presentación {presentacion_id}: {e}")


def _presentacion_salida(cur, p: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    from src.services.clientes_service import propiedades_mini
    from src.services.redact import redact_phones
    m = fetch_one(cur, """
        SELECT m.*, e.tipo AS encargo_tipo, e.cliente_id, e.propiedad_id FROM encargo_matches m
        JOIN encargos e ON e.id = m.encargo_id WHERE m.id = %s
    """, (p["match_id"],))
    recibida = p["receptor_id"] == user_id
    otro = fetch_one(cur, "SELECT nombre, telefono FROM chat_users WHERE id = %s",
                     (p["solicitante_id"] if recibida else p["receptor_id"],))
    # Lo que se le cuenta a cada lado: a quien recibe, qué trae el otro; a quien pidió, a qué se refiere.
    if m["encargo_tipo"] == "buscar_inmueble":
        tuyo = propiedades_mini([m["contraparte_id"]]).get(m["contraparte_id"]) if m["contraparte_tipo"] == "propiedad" else None
        perfil = scalar(cur, "SELECT perfil FROM clientes_agente WHERE id = %s", (m["cliente_id"],)) or {}
        from src.services.red_service import texto_desde_perfil
        trae = {"tipo": "comprador", "busca": texto_desde_perfil(perfil)}
    else:
        texto = scalar(cur, "SELECT texto_pedido FROM pedidos WHERE id = %s", (m["contraparte_id"],))
        tuyo = {"pedido": redact_phones(texto or "", cut_signatures=True)}
        trae = {"tipo": "inmueble", "propiedad": propiedades_mini([m["propiedad_id"]]).get(m["propiedad_id"])}
    contacto = None
    if p["estado"] == "aceptada" and otro:
        contacto = {"nombre": otro["nombre"], "telefono": otro["telefono"]}
    return {"id": p["id"], "estado": p["estado"], "recibida": recibida, "prioridad": p["prioridad"],
            "mensaje": p["mensaje"], "agente": (otro or {}).get("nombre"), "sobre": tuyo, "trae": trae,
            "contacto": contacto, "created_at": p["created_at"].isoformat(),
            "respondida_at": p["respondida_at"].isoformat() if p["respondida_at"] else None}


def presentaciones(user_id: int) -> Dict[str, List[Dict[str, Any]]]:
    with get_db() as db:
        cur = db.cursor
        filas = fetch_all(cur, """
            SELECT * FROM presentaciones WHERE (receptor_id = %s OR solicitante_id = %s)
              AND (estado = 'pendiente' OR created_at > NOW() - INTERVAL '60 days')
            ORDER BY (estado = 'pendiente') DESC, prioridad DESC, created_at DESC LIMIT 60
        """, (user_id, user_id))
        salida = [_presentacion_salida(cur, p, user_id) for p in filas]
    return {"recibidas": [x for x in salida if x["recibida"]], "enviadas": [x for x in salida if not x["recibida"]]}


def responder(user_id: int, presentacion_id: int, aceptar: bool) -> Dict[str, Any]:
    """El receptor acepta o rechaza. Al aceptar, quien pidió paga la llave (desbloqueo normal)."""
    from src.services import suscripcion_service as s
    with get_db() as db:
        cur = db.cursor
        p = fetch_one(cur, """
            SELECT p.*, m.contraparte_tipo, m.contraparte_id FROM presentaciones p
            JOIN encargo_matches m ON m.id = p.match_id
            WHERE p.id = %s AND p.receptor_id = %s FOR UPDATE OF p
        """, (presentacion_id, user_id))
        if not p:
            raise EncargoError("no_encontrado", "Esa presentación no existe.")
        if p["estado"] != "pendiente":
            raise EncargoError("respondida", "Esa presentación ya no está pendiente.")
        if not aceptar:
            cur.execute("UPDATE presentaciones SET estado = 'rechazada', respondida_at = NOW() WHERE id = %s", (presentacion_id,))
            db.conn.commit()
            return {"ok": True, "estado": "rechazada"}
        db.conn.commit()
    r = s.desbloquear(p["solicitante_id"], p["contraparte_tipo"], p["contraparte_id"], canal="conecta")
    estado = "aceptada" if r.get("ok") else "fallida"
    with get_db() as db:
        db.cursor.execute("""
            UPDATE presentaciones SET estado = %s, respondida_at = NOW(), desbloqueo_id = %s WHERE id = %s
        """, (estado, r.get("desbloqueo_id"), presentacion_id))
        db.conn.commit()
        salida = _presentacion_salida(db.cursor, fetch_one(db.cursor, "SELECT * FROM presentaciones WHERE id = %s",
                                                           (presentacion_id,)), user_id)
    if estado == "fallida":
        return {"ok": False, "estado": estado, "error": r.get("error"),
                "mensaje": "No se pudo completar: " + (r.get("mensaje") or "el otro agente no tiene llaves disponibles.")}
    try:
        from src.services import correo_service
        with get_db() as db:
            u = fetch_one(db.cursor, """SELECT nombre, COALESCE(NULLIF(TRIM(correo_personal), ''), email) AS destino
                                        FROM chat_users WHERE id = %s""", (p["solicitante_id"],))
        if u:
            correo_service.presentacion_aceptada(u["nombre"], u["destino"])
    except Exception as e:  # noqa: BLE001
        print(f"[CONECTA] No se pudo avisar la aceptación {presentacion_id}: {e}")
    return {"ok": True, "estado": estado, "presentacion": salida}


def resumen_inicio(user_id: int) -> Dict[str, int]:
    """Para "Para hoy": opciones nuevas de sus encargos y presentaciones por responder."""
    with get_db() as db:
        cur = db.cursor
        nuevos = scalar(cur, """
            SELECT COUNT(*) FROM encargo_matches m JOIN encargos e ON e.id = m.encargo_id
            WHERE e.user_id = %s AND e.estado = 'activo' AND m.estado = 'nuevo'
        """, (user_id,)) or 0
        pendientes = scalar(cur, "SELECT COUNT(*) FROM presentaciones WHERE receptor_id = %s AND estado = 'pendiente'",
                            (user_id,)) or 0
    return {"opciones_nuevas": int(nuevos), "presentaciones_pendientes": int(pendientes)}
