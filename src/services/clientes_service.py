"""
Clientes del agente: los compradores con los que trabaja, su perfil y su selección.

El perfil es el mismo "pedido" estructurado del buscador v3 (`busqueda.py`): tipo,
zonas, presupuesto, mínimos, lo obligatorio y lo deseable. Se arma de tres formas:
  - el agente lo cuenta en sus palabras ("Laura busca apto en Laureles…") y la IA
    lo convierte (`descripcion`); si ya hay perfil, el texto nuevo lo ajusta;
  - se copia del pedido de una búsqueda de Findy (`perfil_desde_busqueda`);
  - se edita a mano desde la app (`perfil`).

Con ese perfil Findy busca para el cliente, y las alertas (`alertas_service`)
avisan cuando entra algo que encaja. El teléfono del cliente es un dato del
agente: nunca sale en piezas ni en el MCP.
"""

from typing import Any, Dict, List, Optional

from src.scrapers.utils import PropertyNormalizer
from src.services import busqueda
from src.services.db import fetch_all, fetch_one, get_db, scalar

PROPOSITOS = {"vivir", "invertir", "otro"}
PLAZOS = {"ya", "3_meses", "6_meses", "sin_afan"}
ESTADOS = {"activo", "en_pausa", "cerrado"}
ESTADOS_INMUEBLE = {"sugerido", "enviado", "le_gusta", "visita", "descartado"}
_CLAVES_PERFIL = {
    "negocio", "tipos", "ubicaciones", "ubicaciones_excluidas", "cerca_de", "edificios_referencia",
    "presupuesto_min", "presupuesto_max", "habitaciones_min", "habitaciones_max", "banos_min",
    "parqueaderos_min", "area_min", "area_max", "piso_min", "piso_max", "estrato_min",
    "antiguedad_max_anios", "administracion_max", "obligatorias", "deseables", "estados",
    "otras_preferencias", "moneda",
}


class ClienteError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


# ── perfil ─────────────────────────────────────────────────────────────────

def _limpiar_perfil(p: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Solo las claves del pedido, validadas por el mismo validador del buscador."""
    if not p:
        return {}
    base = {k: v for k, v in dict(p).items() if k in _CLAVES_PERFIL}
    base.setdefault("negocio", "venta")
    validado = busqueda._validar(base)
    return {k: v for k, v in validado.items() if k in _CLAVES_PERFIL and v not in (None, [], "")}


def perfil_desde_texto(texto: str, previo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """La IA convierte la descripción del agente en perfil (ajustando el anterior si existe)."""
    texto = (texto or "").strip()
    if not texto:
        return dict(previo or {})
    pedido = busqueda.interpretar(texto, previo or None)
    return _limpiar_perfil(pedido)


# ── salida ─────────────────────────────────────────────────────────────────

def slug(propiedad_id: int, titulo: Optional[str]) -> str:
    t = PropertyNormalizer.slugify_titulo(titulo or "") if titulo else ""
    return f"{propiedad_id}-{t}" if t else str(propiedad_id)


def propiedades_mini(ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """Resumen de inmuebles para tarjetas (sin contactos ni link de origen)."""
    if not ids:
        return {}
    with get_db() as db:
        filas = fetch_all(db.cursor, """
            SELECT p.id, p.titulo, p.precio, p.precio_texto, p.tipo_propiedad, p.activa,
                   COALESCE(f.ciudad, p.ciudad) AS ciudad, COALESCE(p.zona, f.barrio) AS zona,
                   COALESCE(p.habitaciones, f.habitaciones) AS habitaciones,
                   COALESCE(p.banos, f.banos) AS banos,
                   COALESCE(p.area_construida, f.area_m2) AS area_construida,
                   p.imagen_principal
            FROM propiedades p LEFT JOIN propiedades_ficha f ON f.propiedad_id = p.id
            WHERE p.id = ANY(%s)
        """, (list(ids),))
    precios = busqueda.cambios_de_precio([f["id"] for f in filas])
    out = {}
    for f in filas:
        out[f["id"]] = {
            "id": f["id"], "slug": slug(f["id"], f["titulo"]), "titulo": f["titulo"],
            "precio": int(f["precio"]) if f["precio"] else None, "precio_texto": f["precio_texto"],
            "tipo_propiedad": f["tipo_propiedad"], "ciudad": f["ciudad"], "zona": f["zona"],
            "habitaciones": f["habitaciones"], "banos": f["banos"],
            "area_construida": float(f["area_construida"]) if f["area_construida"] else None,
            "imagen_principal": f["imagen_principal"], "activa": bool(f["activa"]),
            "precio_anterior": None, "precio_cambio_at": None,
            **precios.get(f["id"], {}),
        }
    return out


def _salida(c: Dict[str, Any]) -> Dict[str, Any]:
    perfil = c.get("perfil") or {}
    return {
        "id": c["id"], "nombre": c["nombre"], "telefono": c.get("telefono"),
        "proposito": c.get("proposito"), "plazo": c.get("plazo"), "estado": c["estado"],
        "alertas": bool(c.get("alertas")), "notas": c.get("notas"),
        "perfil": perfil, "chips": busqueda.chips(perfil),
        "n_busquedas": int(c.get("n_busquedas") or 0), "n_inmuebles": int(c.get("n_inmuebles") or 0),
        "alertas_nuevas": int(c.get("alertas_nuevas") or 0),
        "created_at": c["created_at"].isoformat(), "updated_at": c["updated_at"].isoformat(),
    }


_SELECT = """
    SELECT c.*,
           (SELECT COUNT(*) FROM conversaciones_busqueda b WHERE b.cliente_id = c.id AND b.activa) AS n_busquedas,
           (SELECT COUNT(*) FROM cliente_inmuebles i WHERE i.cliente_id = c.id AND i.estado <> 'descartado') AS n_inmuebles,
           (SELECT COUNT(*) FROM alertas a WHERE a.cliente_id = c.id AND a.leida_at IS NULL) AS alertas_nuevas
    FROM clientes_agente c
"""


def _propio(cur, user_id: int, cliente_id: int) -> Dict[str, Any]:
    c = fetch_one(cur, _SELECT + " WHERE c.id = %s AND c.user_id = %s", (cliente_id, user_id))
    if not c:
        raise ClienteError("no_encontrado", "Ese cliente no existe.")
    return c


def _campos(datos: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "nombre" in datos:
        nombre = (datos.get("nombre") or "").strip()[:120]
        if not nombre:
            raise ClienteError("invalido", "El cliente necesita un nombre.")
        out["nombre"] = nombre
    if "telefono" in datos:
        out["telefono"] = ((datos.get("telefono") or "").strip()[:30]) or None
    if "notas" in datos:
        out["notas"] = ((datos.get("notas") or "").strip()[:4000]) or None
    for k, validos in (("proposito", PROPOSITOS), ("plazo", PLAZOS), ("estado", ESTADOS)):
        if k in datos:
            v = datos.get(k) or None
            if v is not None and v not in validos:
                raise ClienteError("invalido", f"Valor no válido para {k}.")
            if k == "estado" and v is None:
                continue
            out[k] = v
    if "alertas" in datos:
        out["alertas"] = bool(datos.get("alertas"))
    return out


# ── CRUD ───────────────────────────────────────────────────────────────────

def listar(user_id: int, estado: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_db() as db:
        if estado in ESTADOS:
            filas = fetch_all(db.cursor, _SELECT + " WHERE c.user_id = %s AND c.estado = %s ORDER BY c.updated_at DESC",
                              (user_id, estado))
        else:
            filas = fetch_all(db.cursor, _SELECT + " WHERE c.user_id = %s ORDER BY c.updated_at DESC", (user_id,))
    return [_salida(f) for f in filas]


def crear(user_id: int, datos: Dict[str, Any]) -> Dict[str, Any]:
    campos = _campos({"nombre": datos.get("nombre"), **{k: datos[k] for k in datos if k != "nombre"}})
    perfil = _limpiar_perfil(datos.get("perfil"))
    if (datos.get("descripcion") or "").strip():
        try:
            perfil = perfil_desde_texto(datos["descripcion"], perfil or None)
        except Exception as e:  # noqa: BLE001 — sin IA el cliente se crea igual
            print(f"[CLIENTES] No pude interpretar la descripción: {e}")
    import json
    with get_db() as db:
        cur = db.cursor
        n = scalar(cur, "SELECT COUNT(*) FROM clientes_agente WHERE user_id = %s", (user_id,)) or 0
        if n >= 500:
            raise ClienteError("limite", "Llegaste al máximo de clientes.")
        cols = ["user_id", "perfil"] + list(campos)
        vals = [user_id, json.dumps(perfil)] + list(campos.values())
        cur.execute(f"INSERT INTO clientes_agente ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
                    vals)
        cid = cur.fetchone()["id"]
        db.conn.commit()
        return _salida(_propio(cur, user_id, cid))


def obtener(user_id: int, cliente_id: int) -> Dict[str, Any]:
    from src.services import alertas_service
    with get_db() as db:
        cur = db.cursor
        c = _propio(cur, user_id, cliente_id)
        busquedas = fetch_all(cur, """
            SELECT id, nombre, fecha_actualizacion FROM conversaciones_busqueda
            WHERE cliente_id = %s AND activa ORDER BY fecha_actualizacion DESC LIMIT 30
        """, (cliente_id,))
        filas = fetch_all(cur, """
            SELECT propiedad_id, estado, nota, origen, score, razones, updated_at
            FROM cliente_inmuebles WHERE cliente_id = %s ORDER BY updated_at DESC
        """, (cliente_id,))
    minis = propiedades_mini([f["propiedad_id"] for f in filas])
    inmuebles = [{
        "propiedad": minis[f["propiedad_id"]], "estado": f["estado"], "nota": f["nota"], "origen": f["origen"],
        "score": round(f["score"], 1) if f["score"] is not None else None, "razones": list(f["razones"] or []),
        "updated_at": f["updated_at"].isoformat(),
    } for f in filas if f["propiedad_id"] in minis]
    return {
        **_salida(c),
        "busquedas": [{"id": b["id"], "nombre": b["nombre"],
                       "fecha_actualizacion": b["fecha_actualizacion"].isoformat() if b["fecha_actualizacion"] else None}
                      for b in busquedas],
        "inmuebles": inmuebles,
        "alertas": alertas_service.listar(user_id, cliente_id=cliente_id, limite=30),
    }


def actualizar(user_id: int, cliente_id: int, datos: Dict[str, Any]) -> Dict[str, Any]:
    import json
    campos = _campos(datos)
    with get_db() as db:
        actual = _propio(db.cursor, user_id, cliente_id)
    perfil = None
    if "perfil" in datos:
        perfil = _limpiar_perfil(datos.get("perfil"))
    if (datos.get("descripcion") or "").strip():
        try:
            perfil = perfil_desde_texto(datos["descripcion"], perfil if perfil is not None else (actual["perfil"] or None))
        except Exception as e:  # noqa: BLE001
            raise ClienteError("ia_no_disponible", "Findy no pudo leer ese texto ahora. Intenta de nuevo.") from e
    if perfil is not None:
        campos["perfil"] = json.dumps(perfil)
    if campos:
        with get_db() as db:
            sets = ", ".join(f"{k} = %s" for k in campos)
            db.cursor.execute(f"UPDATE clientes_agente SET {sets}, updated_at = NOW() WHERE id = %s AND user_id = %s",
                              list(campos.values()) + [cliente_id, user_id])
            db.conn.commit()
    with get_db() as db:
        return _salida(_propio(db.cursor, user_id, cliente_id))


def archivar(user_id: int, cliente_id: int) -> Dict[str, Any]:
    actualizar(user_id, cliente_id, {"estado": "cerrado"})
    return {"ok": True}


def perfil(user_id: int, cliente_id: int) -> Dict[str, Any]:
    with get_db() as db:
        return dict(_propio(db.cursor, user_id, cliente_id)["perfil"] or {})


# ── buscar para el cliente ─────────────────────────────────────────────────

def buscar(user_id: int, cliente_id: int, limite: int = 12) -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        c = _propio(cur, user_id, cliente_id)
        descartados = {f["propiedad_id"] for f in fetch_all(cur, """
            SELECT propiedad_id FROM cliente_inmuebles WHERE cliente_id = %s AND estado = 'descartado'
        """, (cliente_id,))}
    ped = dict(c["perfil"] or {})
    if not busqueda.chips(ped):
        raise ClienteError("sin_perfil", "Cuéntale a Findy qué busca este cliente para poder sugerirle opciones.")
    limite = max(1, min(int(limite or 12), 30))
    r = busqueda.buscar(busqueda.texto_de_pedido(ped), pedido=ped, limite=limite + len(descartados),
                        reordenar=busqueda.REORDENAR)
    elegidos = [x for x in r["resultados"] if x["id"] not in descartados][:limite]
    minis = propiedades_mini([x["id"] for x in elegidos])
    resultados = [{**minis[x["id"]], "score": x.get("score_final", x["score"]),
                   "razones": x.get("cumple") or [], "no_cumple": x.get("no_cumple") or []}
                  for x in elegidos if x["id"] in minis]
    return {"resultados": resultados, "total": r["total"]}


# ── selección del cliente ──────────────────────────────────────────────────

def _inmueble_salida(cur, cliente_id: int, propiedad_id: int) -> Dict[str, Any]:
    f = fetch_one(cur, """
        SELECT propiedad_id, estado, nota, origen, score, razones, updated_at
        FROM cliente_inmuebles WHERE cliente_id = %s AND propiedad_id = %s
    """, (cliente_id, propiedad_id))
    mini = propiedades_mini([propiedad_id]).get(propiedad_id)
    return {"propiedad": mini, "estado": f["estado"], "nota": f["nota"], "origen": f["origen"],
            "score": f["score"], "razones": list(f["razones"] or []), "updated_at": f["updated_at"].isoformat()}


def guardar_inmueble(user_id: int, cliente_id: int, propiedad_id: int, estado: Optional[str] = None,
                     nota: Optional[str] = None, origen: str = "manual") -> Dict[str, Any]:
    estado = estado or "sugerido"
    if estado not in ESTADOS_INMUEBLE:
        raise ClienteError("invalido", "Estado no válido.")
    with get_db() as db:
        cur = db.cursor
        _propio(cur, user_id, cliente_id)
        if not scalar(cur, "SELECT 1 FROM propiedades WHERE id = %s", (propiedad_id,)):
            raise ClienteError("no_encontrado", "Ese inmueble no existe.")
        cur.execute("""
            INSERT INTO cliente_inmuebles (cliente_id, propiedad_id, estado, nota, origen)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (cliente_id, propiedad_id) DO UPDATE SET
                estado = EXCLUDED.estado, nota = COALESCE(EXCLUDED.nota, cliente_inmuebles.nota), updated_at = NOW()
        """, (cliente_id, propiedad_id, estado, (nota or "").strip()[:1000] or None, origen))
        cur.execute("UPDATE clientes_agente SET updated_at = NOW() WHERE id = %s", (cliente_id,))
        db.conn.commit()
        return _inmueble_salida(cur, cliente_id, propiedad_id)


def actualizar_inmueble(user_id: int, cliente_id: int, propiedad_id: int, datos: Dict[str, Any]) -> Dict[str, Any]:
    sets, vals = [], []
    if "estado" in datos:
        if datos["estado"] not in ESTADOS_INMUEBLE:
            raise ClienteError("invalido", "Estado no válido.")
        sets.append("estado = %s"); vals.append(datos["estado"])
    if "nota" in datos:
        sets.append("nota = %s"); vals.append((datos.get("nota") or "").strip()[:1000] or None)
    with get_db() as db:
        cur = db.cursor
        _propio(cur, user_id, cliente_id)
        if sets:
            cur.execute(f"UPDATE cliente_inmuebles SET {', '.join(sets)}, updated_at = NOW() "
                        "WHERE cliente_id = %s AND propiedad_id = %s", vals + [cliente_id, propiedad_id])
            if cur.rowcount == 0:
                raise ClienteError("no_encontrado", "Ese inmueble no está en la selección del cliente.")
            db.conn.commit()
        return _inmueble_salida(cur, cliente_id, propiedad_id)


def quitar_inmueble(user_id: int, cliente_id: int, propiedad_id: int) -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        _propio(cur, user_id, cliente_id)
        cur.execute("DELETE FROM cliente_inmuebles WHERE cliente_id = %s AND propiedad_id = %s", (cliente_id, propiedad_id))
        db.conn.commit()
    return {"ok": True}


def perfil_desde_busqueda(user_id: int, cliente_id: int, conversation_id: int) -> Dict[str, Any]:
    import json
    with get_db() as db:
        cur = db.cursor
        _propio(cur, user_id, cliente_id)
        conv = fetch_one(cur, """
            SELECT criterios_acumulados FROM conversaciones_busqueda WHERE id = %s AND user_id = %s
        """, (conversation_id, user_id))
    if not conv:
        raise ClienteError("no_encontrado", "Esa búsqueda no existe.")
    crit = conv["criterios_acumulados"] or {}
    if isinstance(crit, str):
        crit = json.loads(crit)
    pedido = crit.get("pedido_v3")
    if not pedido:
        raise ClienteError("sin_perfil", "Esa búsqueda no tiene un pedido que se pueda guardar todavía.")
    return actualizar(user_id, cliente_id, {"perfil": pedido})
