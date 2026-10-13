"""
La Vitrina (migración 058, parte 5): cada lunes, pocas oportunidades curadas.

  1. `proponer()` (worker, a diario): candidatos que cumplen TODOS los criterios
     → `vitrina_candidatos` (pendientes de revisión del admin):
       inmuebles: ≥20 % y ≤35 % por debajo del precio por m² de su barrio y tipo
         (≥8 comparables), Fynder confirmó que sigue publicado en las últimas 72 h,
         publicado hace < 30 días, ≥5 fotos y con contacto;
       pedidos top: presupuesto ≥ 500 millones, zona + tipo + presupuesto claros,
         de los últimos 7 días, quien pidió es usuario verificado con términos.
  2. El admin aprueba o rechaza (~10 min por semana).
  3. `publicar_semana()` (lunes): hasta 8 inmuebles y 8 pedidos aprobados pasan a
     `vitrina_items`, con 72 h de exclusividad.
  4. Quién la ve: Cierre y "Findy trabaja por ti", semanal; Negocio, una vez al
     mes (la primera semana que abre); Visita y sin plan, borrosa (solo cifras) o
     con Fyns (100 por la semana). `vitrina_accesos` registra cada apertura.
  5. Exclusividad (`regla_desbloqueo`, la usa suscripcion_service al cobrar):
     durante las 72 h solo quien tiene acceso a esa semana abre esos contactos, y
     cada contacto lo pueden abrir como máximo 3 agentes.
"""

import json
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from src.services import beneficios_service
from src.services.db import fetch_all, fetch_one, get_db, scalar

MAX_INMUEBLES = 8
MAX_PEDIDOS = 8
HORAS_EXCLUSIVA = 72
MAX_POR_CONTACTO = 3
DESCUENTO_MIN, DESCUENTO_MAX = 0.20, 0.35
COMPARABLES_MIN = 8
PRESUPUESTO_TOP = 500_000_000


class VitrinaError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def lunes(d: Optional[date] = None) -> date:
    d = d or date.today()
    return d - timedelta(days=d.weekday())


# ── 1. proponer ─────────────────────────────────────────────────────────────

def _inmuebles_oportunidad(cur) -> List[Dict[str, Any]]:
    from src.services import radar_service as radar
    med = radar._medianas()
    cands = {}
    for f in radar._inventario():
        m = med.get((f["clave"], f["tipo"]))
        if not m or m[1] < COMPARABLES_MIN or not f["area"] or f["area"] < 20 or f["precio"] < 100e6:
            continue
        desc = 1 - (f["precio"] / f["area"]) / m[0]
        if DESCUENTO_MIN <= desc <= DESCUENTO_MAX:
            cands[f["id"]] = {"descuento_pct": round(desc * 100), "comparables": m[1]}
    if not cands:
        return []
    filas = fetch_all(cur, """
        SELECT id FROM propiedades
        WHERE id = ANY(%s) AND activa
          AND fecha_ultima_validacion > NOW() - INTERVAL '72 hours'
          AND fecha_creacion > NOW() - INTERVAL '30 days'
          AND COALESCE(total_imagenes, 0) >= 5
          AND COALESCE(NULLIF(telefono, ''), NULLIF(agente_captador_telefono, '')) IS NOT NULL
    """, (list(cands),))
    return [{"tipo": "propiedad", "ref_id": f["id"], "score": cands[f["id"]]["descuento_pct"], "motivo": cands[f["id"]]}
            for f in filas]


def _pedidos_top(cur) -> List[Dict[str, Any]]:
    from src.services.compradores_service import _SQL_DESBLOQUEABLE
    filas = fetch_all(cur, f"""
        SELECT p.id, p.criterios, p.presupuesto_estimado FROM pedidos p
        WHERE p.criterios IS NOT NULL AND p.estado <> 'retirado'
          AND p.fecha_captura > NOW() - INTERVAL '7 days'
          AND {_SQL_DESBLOQUEABLE}
    """)
    out = []
    for f in filas:
        c = f["criterios"] if isinstance(f["criterios"], dict) else {}
        tope = c.get("presupuesto_max") or f.get("presupuesto_estimado") or 0
        if not (c.get("tipos") and (c.get("zonas") or c.get("ciudades")) and tope and tope >= PRESUPUESTO_TOP):
            continue
        out.append({"tipo": "pedido", "ref_id": f["id"], "score": round(tope / 1e6),
                    "motivo": {"presupuesto": int(tope), "zonas": (c.get("zonas") or c.get("ciudades"))[:3]}})
    return out


def proponer() -> Dict[str, int]:
    """Agrega a la cola de revisión los candidatos nuevos que cumplen los criterios."""
    nuevos = {"propiedad": 0, "pedido": 0}
    with get_db() as db:
        cur = db.cursor
        for c in _inmuebles_oportunidad(cur) + _pedidos_top(cur):
            cur.execute("""
                INSERT INTO vitrina_candidatos (tipo, ref_id, score, motivo) VALUES (%s, %s, %s, %s)
                ON CONFLICT (tipo, ref_id) DO NOTHING RETURNING id
            """, (c["tipo"], c["ref_id"], c["score"], json.dumps(c["motivo"])))
            if cur.fetchone():
                nuevos[c["tipo"]] += 1
        db.conn.commit()
    return nuevos


# ── 2. revisión del admin ──────────────────────────────────────────────────

def candidatos(estado: str = "pendiente") -> List[Dict[str, Any]]:
    from src.services.clientes_service import propiedades_mini
    from src.services.redact import redact_phones
    with get_db() as db:
        filas = fetch_all(db.cursor, """
            SELECT v.*, pe.texto_pedido FROM vitrina_candidatos v
            LEFT JOIN pedidos pe ON v.tipo = 'pedido' AND pe.id = v.ref_id
            WHERE v.estado = %s ORDER BY v.tipo, v.score DESC, v.created_at DESC LIMIT 200
        """, (estado,))
    minis = propiedades_mini([f["ref_id"] for f in filas if f["tipo"] == "propiedad"])
    return [{"id": f["id"], "tipo": f["tipo"], "ref_id": f["ref_id"], "score": f["score"], "motivo": f["motivo"],
             "estado": f["estado"], "created_at": f["created_at"].isoformat(),
             "propiedad": minis.get(f["ref_id"]) if f["tipo"] == "propiedad" else None,
             "pedido": redact_phones(f["texto_pedido"] or "", cut_signatures=True) if f["tipo"] == "pedido" else None}
            for f in filas]


def revisar(candidato_id: int, aprobar: bool, admin: Optional[str] = None) -> Dict[str, Any]:
    with get_db() as db:
        db.cursor.execute("""
            UPDATE vitrina_candidatos SET estado = %s, revisado_por = %s WHERE id = %s AND estado = 'pendiente'
        """, ("aprobado" if aprobar else "rechazado", admin, candidato_id))
        n = db.cursor.rowcount
        db.conn.commit()
    if not n:
        raise VitrinaError("no_encontrado", "Ese candidato no existe o ya fue revisado.")
    return {"ok": True}


# ── 3. publicar ─────────────────────────────────────────────────────────────

def publicar_semana(hoy: Optional[date] = None) -> Dict[str, Any]:
    """Pasa a la Vitrina de esta semana los aprobados (los mejores primero). Idempotente por semana."""
    semana = lunes(hoy)
    with get_db() as db:
        cur = db.cursor
        if scalar(cur, "SELECT 1 FROM vitrina_items WHERE semana = %s LIMIT 1", (semana,)):
            return {"semana": semana.isoformat(), "ya_publicada": True}
        publicados = 0
        for tipo, maximo in (("propiedad", MAX_INMUEBLES), ("pedido", MAX_PEDIDOS)):
            filas = fetch_all(cur, """
                SELECT id, ref_id, motivo FROM vitrina_candidatos
                WHERE tipo = %s AND estado = 'aprobado' ORDER BY score DESC, created_at LIMIT %s
            """, (tipo, maximo))
            for i, f in enumerate(filas):
                cur.execute("""
                    INSERT INTO vitrina_items (semana, tipo, ref_id, motivo, orden, exclusiva_hasta)
                    VALUES (%s, %s, %s, %s, %s, NOW() + make_interval(hours => %s)) ON CONFLICT DO NOTHING
                """, (semana, tipo, f["ref_id"], json.dumps(f["motivo"]), i, HORAS_EXCLUSIVA))
                cur.execute("UPDATE vitrina_candidatos SET estado = 'publicado' WHERE id = %s", (f["id"],))
                publicados += 1
        db.conn.commit()
    return {"semana": semana.isoformat(), "publicados": publicados}


# ── 4. acceso ───────────────────────────────────────────────────────────────

def _acceso_en(cur, user_id: int, semana: date, consumir: bool) -> Optional[str]:
    """Con qué ve esta semana ('plan', 'complemento', 'fyns') o None. `consumir` registra la mensual."""
    fuente = scalar(cur, "SELECT fuente FROM vitrina_accesos WHERE user_id = %s AND semana = %s", (user_id, semana))
    if fuente:
        return fuente
    ben = beneficios_service.beneficios_en(cur, user_id)
    if ben["vitrina"] >= 4:
        fuente = "complemento" if any(c["codigo"] in ("trabaja", "ambos") for c in ben["complementos"]) else "plan"
    elif ben["vitrina"] >= 1:
        usadas = scalar(cur, """
            SELECT COUNT(*) FROM vitrina_accesos WHERE user_id = %s AND fuente = 'plan'
              AND semana >= date_trunc('month', %s::date)
        """, (user_id, semana)) or 0
        fuente = "plan" if usadas < ben["vitrina"] else None
    if fuente and consumir:
        cur.execute("INSERT INTO vitrina_accesos (user_id, semana, fuente) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (user_id, semana, fuente))
    return fuente


def abrir_con_fyns_en(cur, user_id: int, referencia: str) -> None:
    """Canje de Fyns: acceso a la Vitrina de esta semana."""
    cur.execute("INSERT INTO vitrina_accesos (user_id, semana, fuente) VALUES (%s, %s, 'fyns') ON CONFLICT DO NOTHING",
                (user_id, lunes()))


def _abiertos(cur, tipo: str, ref_id: int, desde) -> int:
    t = "propiedad" if tipo == "propiedad" else "pedido"
    return int(scalar(cur, """
        SELECT COUNT(*) FROM desbloqueos WHERE tipo = %s AND ref_id = %s AND estado = 'vigente' AND created_at >= %s
    """, (t, ref_id, desde)) or 0)


def ver(user_id: int, abrir: bool = True) -> Dict[str, Any]:
    """La Vitrina de esta semana: completa si tiene acceso (y `abrir` consume la mensual), si no, borrosa."""
    from src.services.clientes_service import propiedades_mini
    from src.services.redact import redact_phones
    semana = lunes()
    with get_db() as db:
        cur = db.cursor
        items = fetch_all(cur, """
            SELECT i.*, pe.texto_pedido FROM vitrina_items i
            LEFT JOIN pedidos pe ON i.tipo = 'pedido' AND pe.id = i.ref_id
            WHERE i.semana = %s ORDER BY i.tipo, i.orden
        """, (semana,))
        acceso = _acceso_en(cur, user_id, semana, consumir=abrir and bool(items))
        ben = beneficios_service.beneficios_en(cur, user_id)
        cupos = {(i["tipo"], i["ref_id"]): max(0, MAX_POR_CONTACTO - _abiertos(cur, i["tipo"], i["ref_id"], i["publicada_at"]))
                 for i in items}
        db.conn.commit()
    resumen = {"inmuebles": sum(1 for i in items if i["tipo"] == "propiedad"),
               "pedidos": sum(1 for i in items if i["tipo"] == "pedido")}
    base = {"semana": semana.isoformat(), "resumen": resumen, "acceso": acceso,
            "exclusiva_hasta": max((i["exclusiva_hasta"] for i in items), default=None),
            "vitrina_beneficio": ben["vitrina"], "costo_fyns": 100}
    if base["exclusiva_hasta"]:
        base["exclusiva_hasta"] = base["exclusiva_hasta"].isoformat()
    if not acceso:
        return {**base, "borrosa": True, "items": []}
    minis = propiedades_mini([i["ref_id"] for i in items if i["tipo"] == "propiedad"])
    salida = []
    for i in items:
        x = {"tipo": i["tipo"], "ref_id": i["ref_id"], "motivo": i["motivo"],
             "cupos_restantes": cupos[(i["tipo"], i["ref_id"])], "exclusiva_hasta": i["exclusiva_hasta"].isoformat()}
        if i["tipo"] == "propiedad":
            x["propiedad"] = minis.get(i["ref_id"])
        else:
            x["pedido"] = redact_phones(i["texto_pedido"] or "", cut_signatures=True)
        salida.append(x)
    return {**base, "borrosa": False, "items": salida}


# ── 5. exclusividad al desbloquear ─────────────────────────────────────────

def regla_desbloqueo(cur, user_id: int, tipo: str, ref_id: int) -> Optional[Dict[str, str]]:
    """Error si el contacto está en la Vitrina, dentro de las 72 h, y no se puede abrir; None si se puede."""
    t = "propiedad" if tipo == "propiedad" else "pedido"
    i = fetch_one(cur, """
        SELECT semana, publicada_at FROM vitrina_items
        WHERE tipo = %s AND ref_id = %s AND exclusiva_hasta > NOW() ORDER BY publicada_at DESC LIMIT 1
    """, (t, ref_id))
    if not i:
        return None
    if not _acceso_en(cur, user_id, i["semana"], consumir=False):
        return {"error": "vitrina_exclusiva",
                "mensaje": "Esta oportunidad está en la Vitrina de la semana: los primeros 3 días solo la abren sus miembros. "
                           "Mira cómo entrar en Mi plan (o con 100 Fyns)."}
    if _abiertos(cur, t, ref_id, i["publicada_at"]) >= MAX_POR_CONTACTO:
        return {"error": "vitrina_agotada",
                "mensaje": f"Este contacto de la Vitrina ya lo abrieron {MAX_POR_CONTACTO} agentes, el máximo. No se cobra."}
    return None
