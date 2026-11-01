"""
Encargos que aprenden (migración 070): la bitácora de cada encargo.

Findy deja ahí lo que hace y pregunta por el avance; el agente responde, califica
las opciones y cuenta cómo va. Con eso Findy afina el perfil del cliente y vuelve a
buscar.

    registrar(cur, encargo_id, autor, tipo, texto, datos)   una entrada (y marca actividad)
    novedad(cur, e, match_ids)                              «Encontré N opciones…» (la llama el worker)
    preguntar(encargo_id)                                   seguimiento, cuando hay algo que contar:
        · 2 días después de mostrar opciones sin opinión → «¿Qué le pareció?»
        · una semana sin noticias → «¿Cómo va?» (sigue / visitó / negocia / compró / ya no busca)
        Máximo una pregunta pendiente por encargo y una al día.
    responder(user, entrada_id, opcion)                     respuesta a «¿Cómo va?» (cambia la etapa o cierra)
    opinar(user, match_id, opinion, motivos, texto)         le gustó / no le gustó y por qué → aprende
    nota(user, encargo_id, texto)                           lo que el agente cuenta → la IA ajusta el perfil
    cambiar_etapa / cerrar_con_resultado
    bitacora(user, encargo_id)                              la conversación, con las opciones adentro

Aprender: los motivos de un toque ajustan el perfil con reglas (sin IA); el texto libre
lo interpreta la IA (clientes_service.perfil_desde_texto) con el uso justo diario. Cada
cambio queda como «aprendizaje» con el antes y el después.
"""

import math
from typing import Any, Dict, List, Optional

from psycopg2.extras import Json

from src.services.db import fetch_all, fetch_one, get_db, scalar

DIAS_PARA_OPINION = 2
DIAS_SIN_NOTICIAS = 7

ETAPAS = ("buscando", "propuesto", "visitando", "negociando", "cerrado")

# Motivos de un toque. «No le gustó» ajusta el perfil; «le gustó» refuerza lo que aplique.
MOTIVOS_NO = {
    "caro": "Muy caro", "zona": "No le gustó la zona", "pequeno": "Muy pequeño", "oscuro": "Oscuro",
    "ruido": "Ruidoso", "piso_bajo": "Piso muy bajo", "parqueadero": "Sin parqueadero",
    "estado": "Para remodelar", "distribucion": "La distribución",
}
MOTIVOS_SI = {
    "precio": "El precio", "zona": "La zona", "tamano": "El tamaño", "vista": "La vista",
    "acabados": "Los acabados", "distribucion": "La distribución", "luz": "La luz",
}

OPCIONES_ESTADO = {
    "sigue": "Sigue buscando", "visito": "Ya visitó algunos", "negocia": "Está negociando",
    "compro": "Ya compró", "no_busca": "Ya no está buscando",
}
OPCIONES_ESTADO_COMPRADOR = {
    "sigue": "Sigo buscando comprador", "visito": "Ya hubo visitas", "negocia": "Estoy negociando",
    "compro": "Ya se vendió", "no_busca": "Ya no lo vendo",
}


class BitacoraError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


# ── base ────────────────────────────────────────────────────────────────────

def registrar(cur, encargo_id: int, autor: str, tipo: str, texto: str, datos: Optional[Dict[str, Any]] = None) -> int:
    eid = scalar(cur, """
        INSERT INTO encargo_bitacora (encargo_id, autor, tipo, texto, datos) VALUES (%s, %s, %s, %s, %s) RETURNING id
    """, (encargo_id, autor, tipo, texto[:2000], Json(datos or {})))
    if autor == "agente":
        cur.execute("UPDATE encargos SET ultima_actividad_at = NOW() WHERE id = %s", (encargo_id,))
    return eid


def _encargo(cur, user_id: int, encargo_id: int) -> Dict[str, Any]:
    e = fetch_one(cur, """
        SELECT e.*, c.nombre AS cliente_nombre, c.perfil AS cliente_perfil FROM encargos e
        LEFT JOIN clientes_agente c ON c.id = e.cliente_id
        WHERE e.id = %s AND e.user_id = %s
    """, (encargo_id, user_id))
    if not e:
        raise BitacoraError("no_encontrado", "Ese encargo no existe.")
    return e


def _quien(e: Dict[str, Any]) -> str:
    return (e.get("cliente_nombre") or "tu cliente").split(" ")[0] if e["tipo"] == "buscar_inmueble" else "tu inmueble"


def novedad(cur, e: Dict[str, Any], match_ids: List[int]) -> None:
    """Las opciones nuevas que encontró el worker, como una entrada de la bitácora."""
    if not match_ids:
        return
    n = len(match_ids)
    if e["tipo"] == "buscar_inmueble":
        nombre = (scalar(cur, "SELECT nombre FROM clientes_agente WHERE id = %s", (e["cliente_id"],)) or "tu cliente").split(" ")[0]
        texto = f"Encontré {'una opción nueva' if n == 1 else f'{n} opciones nuevas'} para {nombre}. Míralas y cuéntame qué le parecen."
    else:
        texto = f"Encontré {'un comprador nuevo' if n == 1 else f'{n} compradores nuevos'} para tu inmueble."
    registrar(cur, e["id"], "findy", "novedad", texto, {"match_ids": match_ids})


# ── seguimiento ─────────────────────────────────────────────────────────────

def _pendiente(cur, encargo_id: int) -> bool:
    return bool(scalar(cur, "SELECT 1 FROM encargo_bitacora WHERE encargo_id = %s AND tipo = 'pregunta' AND NOT respondida",
                       (encargo_id,)))


def preguntar(encargo_id: int) -> Optional[int]:
    """El worker la llama tras trabajar cada encargo. Devuelve el id de la pregunta o None."""
    with get_db() as db:
        cur = db.cursor
        e = fetch_one(cur, """
            SELECT e.*, c.nombre AS cliente_nombre FROM encargos e LEFT JOIN clientes_agente c ON c.id = e.cliente_id
            WHERE e.id = %s AND e.estado = 'activo' AND (e.proxima_pregunta_at IS NULL OR e.proxima_pregunta_at <= NOW())
        """, (encargo_id,))
        if not e or _pendiente(cur, encargo_id):
            return None
        quien = _quien(e)
        pid = None
        if e["tipo"] == "buscar_inmueble":
            sin_opinion = [r["id"] for r in fetch_all(cur, f"""
                SELECT id FROM encargo_matches
                WHERE encargo_id = %s AND opinion IS NULL AND estado <> 'descartado'
                  AND created_at < NOW() - INTERVAL '{DIAS_PARA_OPINION} days'
                  AND NOT EXISTS (SELECT 1 FROM encargo_bitacora b WHERE b.encargo_id = %s AND b.tipo = 'pregunta'
                                  AND b.datos->>'clase' = 'opinion' AND b.datos->'match_ids' @> to_jsonb(encargo_matches.id))
                ORDER BY score DESC LIMIT 3
            """, (encargo_id, encargo_id))]
            if sin_opinion:
                pid = registrar(cur, encargo_id, "findy", "pregunta",
                                f"¿Qué le parecieron a {quien} estas opciones? Con lo que me digas afino la búsqueda.",
                                {"clase": "opinion", "match_ids": sin_opinion})
        if pid is None and scalar(cur, f"SELECT %s < NOW() - INTERVAL '{DIAS_SIN_NOTICIAS} days'", (e["ultima_actividad_at"],)):
            opciones = OPCIONES_ESTADO if e["tipo"] == "buscar_inmueble" else OPCIONES_ESTADO_COMPRADOR
            texto = (f"Hace una semana no sé de {quien}. ¿Cómo va?" if e["tipo"] == "buscar_inmueble"
                     else "Hace una semana no sé de tu inmueble. ¿Cómo va la venta?")
            pid = registrar(cur, encargo_id, "findy", "pregunta", texto,
                            {"clase": "estado", "opciones": [{"id": k, "texto": v} for k, v in opciones.items()]})
        if pid:
            cur.execute("UPDATE encargos SET proxima_pregunta_at = NOW() + INTERVAL '1 day' WHERE id = %s", (encargo_id,))
        db.conn.commit()
        return pid


def _cerrar_preguntas(cur, encargo_id: int, clase: Optional[str] = None) -> None:
    cur.execute(f"""
        UPDATE encargo_bitacora SET respondida = TRUE
        WHERE encargo_id = %s AND tipo = 'pregunta' AND NOT respondida {"AND datos->>'clase' = %s" if clase else ""}
    """, (encargo_id, clase) if clase else (encargo_id,))


def responder(user_id: int, entrada_id: int, opcion: str) -> Dict[str, Any]:
    """Respuesta a una pregunta de Findy («¿Cómo va?» o «todavía no los ha visto»)."""
    with get_db() as db:
        cur = db.cursor
        b = fetch_one(cur, """
            SELECT b.*, e.user_id, e.tipo AS e_tipo FROM encargo_bitacora b JOIN encargos e ON e.id = b.encargo_id
            WHERE b.id = %s AND e.user_id = %s AND b.tipo = 'pregunta'
        """, (entrada_id, user_id))
        if not b:
            raise BitacoraError("no_encontrado", "Esa pregunta no existe.")
        eid = b["encargo_id"]
        clase = (b["datos"] or {}).get("clase")
        cur.execute("UPDATE encargo_bitacora SET respondida = TRUE WHERE id = %s", (entrada_id,))
        if clase == "opinion" and opcion == "no_ha_visto":
            registrar(cur, eid, "agente", "respuesta", "Todavía no las ha visto.")
            registrar(cur, eid, "findy", "respuesta", "Listo, te vuelvo a preguntar en unos días.")
            cur.execute("UPDATE encargos SET proxima_pregunta_at = NOW() + INTERVAL '3 days' WHERE id = %s", (eid,))
            db.conn.commit()
            return {"ok": True}
        opciones = OPCIONES_ESTADO if b["e_tipo"] == "buscar_inmueble" else OPCIONES_ESTADO_COMPRADOR
        if clase != "estado" or opcion not in opciones:
            raise BitacoraError("invalido", "Esa respuesta no aplica.")
        registrar(cur, eid, "agente", "respuesta", opciones[opcion])
        db.conn.commit()
    if opcion == "compro":
        return cerrar_con_resultado(user_id, eid, "ganado")
    if opcion == "no_busca":
        return cerrar_con_resultado(user_id, eid, "perdido")
    etapa = {"visito": "visitando", "negocia": "negociando"}.get(opcion)
    if etapa:
        return cambiar_etapa(user_id, eid, etapa)
    with get_db() as db:
        registrar(db.cursor, eid, "findy", "respuesta", "Perfecto, sigo buscando. Te aviso apenas encuentre algo que valga la pena.")
        db.conn.commit()
    return {"ok": True}


def cambiar_etapa(user_id: int, encargo_id: int, etapa: str) -> Dict[str, Any]:
    if etapa not in ETAPAS or etapa == "cerrado":
        raise BitacoraError("invalido", "Etapa no válida.")
    textos = {"buscando": "Volvimos a buscar.", "propuesto": "Ya le mostraste opciones.",
              "visitando": "Están en visitas. Cuéntame qué le van pareciendo y afino.",
              "negociando": "¡Van negociando! Si se cae, sigo buscando sin que tengas que pedírmelo."}
    with get_db() as db:
        cur = db.cursor
        _encargo(cur, user_id, encargo_id)
        cur.execute("UPDATE encargos SET etapa = %s, ultima_actividad_at = NOW() WHERE id = %s", (etapa, encargo_id))
        registrar(cur, encargo_id, "findy", "estado", textos[etapa], {"etapa": etapa})
        db.conn.commit()
    return {"ok": True, "etapa": etapa}


def cerrar_con_resultado(user_id: int, encargo_id: int, resultado: Optional[str]) -> Dict[str, Any]:
    if resultado not in (None, "ganado", "perdido"):
        raise BitacoraError("invalido", "Resultado no válido.")
    with get_db() as db:
        cur = db.cursor
        e = _encargo(cur, user_id, encargo_id)
        if e["estado"] != "activo":
            raise BitacoraError("cerrado", "Ese encargo ya estaba cerrado.")
        cur.execute("""
            UPDATE encargos SET estado = 'cerrado', etapa = 'cerrado', resultado = %s, cerrado_at = NOW(),
                   ultima_actividad_at = NOW() WHERE id = %s
        """, (resultado, encargo_id))
        _cerrar_preguntas(cur, encargo_id)
        texto = {"ganado": "¡Felicitaciones por el cierre! 🎉 Cierro este encargo y libero el cupo.",
                 "perdido": "Entendido, cierro este encargo y libero el cupo. Cuando quieras lo retomamos."}.get(
            resultado, "Cerré este encargo y liberé el cupo.")
        registrar(cur, encargo_id, "findy", "estado", texto, {"etapa": "cerrado", "resultado": resultado})
        db.conn.commit()
    return {"ok": True, "estado": "cerrado", "resultado": resultado}


# ── aprender ────────────────────────────────────────────────────────────────

def _bajar(n: float, paso: int = 10_000_000) -> int:
    return int(math.floor(n / paso) * paso)


def aplicar_motivos(perfil: Dict[str, Any], p: Dict[str, Any], motivos: List[str], opinion: str) -> Dict[str, Any]:
    """Reglas: lo que no le gustó de ESTE inmueble se vuelve un ajuste del perfil (sin IA)."""
    q = dict(perfil or {})
    obligatorias = list(q.get("obligatorias") or [])
    def si_o_si(car: str) -> None:
        if car not in obligatorias:
            obligatorias.append(car)
        q["deseables"] = [d for d in q.get("deseables") or [] if d.get("caracteristica") != car]
    if opinion == "no_le_gusta":
        for m in motivos:
            if m == "caro" and p.get("precio"):
                tope = _bajar(p["precio"] * 0.95)
                if tope > (q.get("presupuesto_min") or 0) and tope < (q.get("presupuesto_max") or float("inf")):
                    q["presupuesto_max"] = tope
            elif m == "zona" and p.get("zona"):
                zona = p["zona"].strip()
                pedidas = [u.get("nombre", "").lower() for u in q.get("ubicaciones") or []]
                if zona.lower() not in pedidas and zona not in (q.get("ubicaciones_excluidas") or []):
                    q["ubicaciones_excluidas"] = list(q.get("ubicaciones_excluidas") or []) + [zona]
            elif m == "pequeno" and p.get("area_construida"):
                q["area_min"] = max(q.get("area_min") or 0, int(round(float(p["area_construida"]) * 1.1)))
            elif m == "oscuro":
                si_o_si("iluminado")
            elif m == "ruido":
                si_o_si("tranquilo")
            elif m == "piso_bajo":
                si_o_si("piso_alto")
            elif m == "parqueadero":
                q["parqueaderos_min"] = max(1, q.get("parqueaderos_min") or 0)
            elif m == "estado":
                otras = list(q.get("otras_preferencias") or [])
                frase = "En buen estado, sin tener que remodelar"
                if frase not in otras:
                    q["otras_preferencias"] = otras + [frase]
    else:
        deseables = list(q.get("deseables") or [])
        for m in motivos:
            car = {"vista": "vista_panoramica", "luz": "iluminado"}.get(m)
            if car and car not in obligatorias and not any(d.get("caracteristica") == car for d in deseables):
                deseables.append({"caracteristica": car, "peso": 3})
        q["deseables"] = deseables
    q["obligatorias"] = obligatorias
    return q


def _guardar_perfil_y_contar(cur, e: Dict[str, Any], nuevo: Dict[str, Any], porque: str) -> Optional[Dict[str, List[str]]]:
    """Guarda el perfil del cliente si cambió y deja el aprendizaje en la bitácora."""
    from src.services import busqueda
    from src.services.clientes_service import _limpiar_perfil
    antes = dict(e.get("cliente_perfil") or {})
    nuevo = _limpiar_perfil(nuevo)
    a = [c["texto"] for c in busqueda.chips(antes)]
    d = [c["texto"] for c in busqueda.chips(nuevo)]
    cambio = {"mas": [x for x in d if x not in a], "menos": [x for x in a if x not in d]}
    if not cambio["mas"] and not cambio["menos"]:
        return None
    cur.execute("UPDATE clientes_agente SET perfil = %s, updated_at = NOW() WHERE id = %s", (Json(nuevo), e["cliente_id"]))
    partes = []
    if cambio["mas"]:
        partes.append("ahora busco " + ", ".join(cambio["mas"]).lower())
    if cambio["menos"]:
        partes.append("dejo de pedir " + ", ".join(cambio["menos"]).lower())
    registrar(cur, e["id"], "findy", "aprendizaje", f"Aprendí {porque}: {'; '.join(partes)}.", cambio)
    e["cliente_perfil"] = nuevo
    return cambio


def _con_ia(user_id: int) -> None:
    from src.services import suscripcion_service
    if not suscripcion_service.registrar_busqueda(user_id).get("permitido"):
        raise BitacoraError("limite", "Llegaste al límite de IA de hoy. Mañana se renueva; los botones siguen funcionando.")


def opinar(user_id: int, match_id: int, opinion: str, motivos: Optional[List[str]] = None,
           texto: Optional[str] = None) -> Dict[str, Any]:
    from src.services import clientes_service
    from src.services.clientes_service import propiedades_mini
    if opinion not in ("le_gusta", "no_le_gusta"):
        raise BitacoraError("invalido", "La opinión es le gustó o no le gustó.")
    validos = MOTIVOS_SI if opinion == "le_gusta" else MOTIVOS_NO
    motivos = [m for m in (motivos or []) if m in validos][:5]
    texto = (texto or "").strip()[:500]
    with get_db() as db:
        cur = db.cursor
        m = fetch_one(cur, """
            SELECT m.*, e.user_id FROM encargo_matches m JOIN encargos e ON e.id = m.encargo_id
            WHERE m.id = %s AND e.user_id = %s
        """, (match_id, user_id))
        if not m:
            raise BitacoraError("no_encontrado", "Esa opción no existe.")
        e = _encargo(cur, user_id, m["encargo_id"])
        cur.execute("""
            UPDATE encargo_matches SET opinion = %s, motivos = %s, opinion_at = NOW(),
                   estado = CASE WHEN %s = 'no_le_gusta' AND estado <> 'presentacion' THEN 'descartado' ELSE estado END
            WHERE id = %s
        """, (opinion, motivos, opinion, match_id))
        p = propiedades_mini([m["contraparte_id"]]).get(m["contraparte_id"]) if m["contraparte_tipo"] == "propiedad" else None
        nombre_op = (p or {}).get("titulo") or "esta opción"
        quien = _quien(e)
        razones = ", ".join(validos[x].lower() for x in motivos)
        registrar(cur, e["id"], "agente", "respuesta",
                  f"{'Le gustó' if opinion == 'le_gusta' else 'No le gustó'} «{nombre_op}»"
                  + (f": {razones}" if razones else "") + (f". {texto}" if texto else ""),
                  {"match_id": match_id, "opinion": opinion, "motivos": motivos})
        if e["etapa"] == "buscando":
            cur.execute("UPDATE encargos SET etapa = 'propuesto' WHERE id = %s", (e["id"],))
        # Responder la pregunta de opinión cuando ya se opinó de todas sus opciones.
        for b in fetch_all(cur, """
            SELECT id, datos FROM encargo_bitacora WHERE encargo_id = %s AND tipo = 'pregunta' AND NOT respondida
              AND datos->>'clase' = 'opinion'
        """, (e["id"],)):
            ids = [int(i) for i in (b["datos"] or {}).get("match_ids") or []]
            faltan = scalar(cur, "SELECT COUNT(*) FROM encargo_matches WHERE id = ANY(%s) AND opinion IS NULL", (ids,)) if ids else 0
            if not faltan:
                cur.execute("UPDATE encargo_bitacora SET respondida = TRUE WHERE id = %s", (b["id"],))
        cambio = None
        if e["tipo"] == "buscar_inmueble" and p:
            cambio = _guardar_perfil_y_contar(cur, e, aplicar_motivos(e["cliente_perfil"], p, motivos, opinion),
                                              f"de lo que {'le gustó' if opinion == 'le_gusta' else 'no le gustó'} a {quien}")
        db.conn.commit()
    # Su selección en la ficha del cliente refleja la opinión.
    if e["tipo"] == "buscar_inmueble" and p:
        try:
            clientes_service.guardar_inmueble(user_id, e["cliente_id"], p["id"],
                                              "le_gusta" if opinion == "le_gusta" else "descartado", origen="busqueda")
        except Exception as ex:  # noqa: BLE001
            print(f"[ENCARGOS] selección del cliente: {ex}")
    if texto and e["tipo"] == "buscar_inmueble":
        try:
            cambio = _aprender_de_texto(user_id, e["id"],
                                        f"Sobre «{nombre_op}»: {'le gustó' if opinion == 'le_gusta' else 'no le gustó'}. {texto}") or cambio
        except BitacoraError as ex:  # sin cupo de IA: la opinión ya quedó guardada
            print(f"[ENCARGOS] sin IA para la nota: {ex.mensaje}")
    if cambio:
        _rebuscar(e["id"])
    return {"ok": True, "aprendio": cambio}


def _aprender_de_texto(user_id: int, encargo_id: int, texto: str) -> Optional[Dict[str, List[str]]]:
    from src.services.clientes_service import perfil_desde_texto
    _con_ia(user_id)
    with get_db() as db:
        cur = db.cursor
        e = _encargo(cur, user_id, encargo_id)
        nuevo = perfil_desde_texto(texto, dict(e["cliente_perfil"] or {}))
        # La IA reescribe el perfil; las notas sueltas de antes no se pierden.
        otras = list(nuevo.get("otras_preferencias") or [])
        nuevo["otras_preferencias"] = otras + [x for x in (e["cliente_perfil"] or {}).get("otras_preferencias") or [] if x not in otras]
        cambio = _guardar_perfil_y_contar(cur, e, nuevo, "de lo que me contaste")
        db.conn.commit()
    return cambio


def nota(user_id: int, encargo_id: int, texto: str) -> Dict[str, Any]:
    texto = (texto or "").strip()[:1000]
    if not texto:
        raise BitacoraError("vacio", "Escribe algo para contarle a Findy.")
    with get_db() as db:
        cur = db.cursor
        e = _encargo(cur, user_id, encargo_id)
        if e["estado"] != "activo":
            raise BitacoraError("cerrado", "Ese encargo está cerrado.")
        registrar(cur, encargo_id, "agente", "nota", texto)
        db.conn.commit()
    cambio = _aprender_de_texto(user_id, encargo_id, texto) if e["tipo"] == "buscar_inmueble" else None
    if cambio:
        _rebuscar(encargo_id)
    else:
        with get_db() as db:
            registrar(db.cursor, encargo_id, "findy", "respuesta",
                      "Lo anoté. No cambia lo que busco, pero lo tengo en cuenta." if e["tipo"] == "buscar_inmueble" else "Lo anoté.")
            db.conn.commit()
    return {"ok": True, "aprendio": cambio}


def _rebuscar(encargo_id: int) -> None:
    """Tras aprender, busca otra vez de una (las opciones nuevas llegan como novedad)."""
    from src.services import encargos_service
    try:
        encargos_service.trabajar(encargo_id)
    except Exception as ex:  # noqa: BLE001
        print(f"[ENCARGOS] rebuscar {encargo_id}: {ex}")


# ── lectura ─────────────────────────────────────────────────────────────────

def bitacora(user_id: int, encargo_id: int, limite: int = 80) -> List[Dict[str, Any]]:
    from src.services.encargos_service import _match_salida
    with get_db() as db:
        cur = db.cursor
        _encargo(cur, user_id, encargo_id)
        filas = fetch_all(cur, """
            SELECT * FROM (SELECT * FROM encargo_bitacora WHERE encargo_id = %s ORDER BY created_at DESC LIMIT %s) b
            ORDER BY created_at
        """, (encargo_id, limite))
        ids = sorted({int(i) for f in filas for i in (f["datos"] or {}).get("match_ids") or []})
        # Opciones que no salen en ninguna entrada (encontradas antes de la bitácora): van al inicio.
        sueltas = [m["id"] for m in fetch_all(cur, """
            SELECT id FROM encargo_matches WHERE encargo_id = %s AND estado <> 'descartado' AND NOT (id = ANY(%s))
            ORDER BY score DESC LIMIT 10
        """, (encargo_id, ids or [0]))]
        todos = ids + sueltas
        matches = {m["id"]: m for m in fetch_all(cur, "SELECT * FROM encargo_matches WHERE id = ANY(%s)", (todos,))} if todos else {}
        salida_m = {i: _match_salida(cur, m, user_id) for i, m in matches.items()}
    out = []
    if sueltas:
        out.append({"id": 0, "autor": "findy", "tipo": "novedad", "respondida": True,
                    "texto": "Esto es lo que llevo encontrado. Cuéntame qué le parece a tu cliente y afino la búsqueda.",
                    "datos": {"match_ids": sueltas, "opciones": [salida_m[i] for i in sueltas if i in salida_m]},
                    "created_at": (filas[0]["created_at"] if filas else matches[sueltas[0]]["created_at"]).isoformat()})
    for f in filas:
        d = dict(f["datos"] or {})
        if d.get("match_ids"):
            d["opciones"] = [salida_m[int(i)] for i in d["match_ids"] if int(i) in salida_m]
        out.append({"id": f["id"], "autor": f["autor"], "tipo": f["tipo"], "texto": f["texto"], "datos": d,
                    "respondida": f["respondida"], "created_at": f["created_at"].isoformat()})
    return out


def motivos_catalogo() -> Dict[str, Any]:
    return {"no_le_gusta": [{"id": k, "texto": v} for k, v in MOTIVOS_NO.items()],
            "le_gusta": [{"id": k, "texto": v} for k, v in MOTIVOS_SI.items()]}
