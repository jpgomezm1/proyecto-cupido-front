"""
Valorador para propietarios (migración 063; diseño en negocio/estrategia/benchmark-idealista.md).

El propietario valora su inmueble gratis en /valorar (o en /a/<slug>/valorar, la página de
un agente) y, si quiere vender o arrendar, deja su WhatsApp, lo confirma con un código y
autoriza el tratamiento de sus datos (Ley 1581). Desde ahí es un contacto más:

  - Desde Fynder: lo ven los agentes en Mercado › Propietarios y lo abren con una llave,
    máximo 3 (suscripcion_service, tipo 'valoracion'). Vence a los 30 días.
  - Desde la página de un agente: es solo de ese agente y no le cuesta llave.

La estimación son precios de publicación (no de cierre): mediana del precio por m² de los
inmuebles activos parecidos (mismo tipo, área entre 0,6 y 1,6 veces, habitaciones ±1) en el
barrio; si hay pocos, en la comuna y luego en el municipio. Sin IA.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import timedelta
from typing import Any, Dict, List, Optional

from src.services import facetas
from src.services.db import fetch_all, fetch_one, get_db, scalar
from src.services.textutils import normalize_phone
from src.services.whatsapp_sender import WhatsAppSendError, enviar_whatsapp

TIPOS = {
    "apartamento": "Apartamento", "casa": "Casa", "apartaestudio": "Apartaestudio",
    "casa_campestre": "Casa campestre", "finca": "Finca", "lote": "Lote",
    "local": "Local", "oficina": "Oficina", "bodega": "Bodega",
}
INTENCIONES = {"vender": "vender", "arrendar": "arrendar", "ambos": "vender o arrendar"}
PLAZOS = {"ya": "Ya", "3_meses": "En los próximos 3 meses", "6_meses": "En 6 meses", "explorando": "Solo explorando"}

MIN_MUESTRA = 8           # para hablar de un barrio o una comuna
MIN_MUESTRA_MUNICIPIO = 5
MAX_AGENTES = 3           # agentes que pueden abrir un mismo propietario
VIGENCIA_DIAS = 30
VIGENCIA_CODIGO = timedelta(minutes=10)
MAX_CODIGOS = 3           # por valoración
MAX_INTENTOS = 5
MAX_VALORACIONES_IP_DIA = 40
CONSENTIMIENTO_VERSION = "valorador-2026-10"


class ValoradorError(Exception):
    def __init__(self, codigo: str, mensaje: str, campo: Optional[str] = None):
        super().__init__(mensaje)
        self.codigo, self.mensaje, self.campo = codigo, mensaje, campo


def _frontend() -> str:
    return (os.getenv("FYNDER_FRONTEND_URL") or "https://getfynder.com").rstrip("/")


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


def _redondear(v: float, venta: bool) -> int:
    paso = 1_000_000 if venta else 50_000
    return int(round(v / paso) * paso)


# ---------------------------------------------------------------------------
# Estimación
# ---------------------------------------------------------------------------

def _niveles(b: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Del más cercano al más amplio: barrio → comuna (Medellín) o municipio (el resto).
    Medellín entero no sirve de referencia (El Poblado y Manrique no se parecen): ahí no
    se sube más allá de la comuna."""
    niveles = [{"nivel": "barrio", "nombre": b["nombre"], "sql": "pb.barrio_id = %s", "params": [b["id"]],
                "minimo": MIN_MUESTRA}]
    if b.get("comuna"):
        niveles.append({"nivel": "comuna", "nombre": b["comuna"], "sql": "b.comuna = %s AND b.municipio = %s",
                        "params": [b["comuna"], b["municipio"]], "minimo": MIN_MUESTRA})
        return niveles
    niveles.append({"nivel": "municipio", "nombre": b["municipio"],
                    "sql": "COALESCE(b.municipio, pb.municipio) = %s", "params": [b["municipio"]],
                    "minimo": MIN_MUESTRA_MUNICIPIO})
    return niveles


def _rango(cur, negocio: str, tipo: str, area: float, hab: Optional[int], niveles: List[Dict[str, Any]]):
    venta = negocio == "Venta"
    for n in niveles:
        conds, params = facetas.condiciones(tipo=tipo, habitaciones=hab)
        agg = fetch_one(cur, f"""
            SELECT COUNT(*) AS muestra,
                   percentile_cont(0.25) WITHIN GROUP (ORDER BY p.precio / x.area) AS p25,
                   percentile_cont(0.50) WITHIN GROUP (ORDER BY p.precio / x.area) AS p50,
                   percentile_cont(0.75) WITHIN GROUP (ORDER BY p.precio / x.area) AS p75
            FROM propiedades p {facetas.JOIN}
            WHERE p.activa AND p.precio > 0 AND p.tipo_negocio = %s AND x.area BETWEEN %s AND %s
              AND {n['sql']} {''.join(' AND ' + c for c in conds)}
        """, [negocio, area * 0.6, area * 1.6, *n["params"], *params]) or {}
        muestra = int(agg.get("muestra") or 0)
        if muestra >= n["minimo"] and agg.get("p50"):
            p25, p50, p75 = (float(agg[k]) for k in ("p25", "p50", "p75"))
            return {
                "nivel": n["nivel"], "zona": n["nombre"], "muestra": muestra,
                "m2": round(p50), "bajo": _redondear(p25 * area, venta), "medio": _redondear(p50 * area, venta),
                "alto": _redondear(p75 * area, venta),
            }
    return None


def estimar(cur, tipo: str, barrio: Dict[str, Any], area: float, habitaciones: Optional[int]) -> Dict[str, Any]:
    niveles = _niveles(barrio)
    venta = _rango(cur, "Venta", tipo, area, habitaciones, niveles)
    arriendo = _rango(cur, "Arriendo", tipo, area, habitaciones, niveles)
    return {"venta": venta, "arriendo": arriendo, "precios_de": "publicación",
            "zona": {"barrio": barrio["nombre"], "comuna": barrio.get("comuna"), "municipio": barrio["municipio"]}}


# ---------------------------------------------------------------------------
# El recorrido del propietario (público, sin cuenta)
# ---------------------------------------------------------------------------

def barrios(q: str, limite: int = 12) -> List[Dict[str, Any]]:
    from src.services.barrios_service import buscar
    if len((q or "").strip()) < 2:
        return []
    return [{"id": b["id"], "nombre": b["nombre"], "municipio": b["municipio"], "comuna": b.get("comuna")}
            for b in buscar(q, limite)]


def _agente_publico(cur, slug: Optional[str]) -> Optional[Dict[str, Any]]:
    if not slug:
        return None
    u = fetch_one(cur, """
        SELECT id, nombre, marca_nombre, logo_url, foto_url, pagina_slug FROM chat_users
        WHERE LOWER(pagina_slug) = %s AND pagina_activa AND activo AND telefono_verificado
    """, (slug.lower(),))
    if not u:
        raise ValoradorError("agente", "Esta página de valoración no existe o no está publicada.")
    return u


def _agente_salida(u: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not u:
        return None
    return {"nombre": u["nombre"], "marca_nombre": u.get("marca_nombre"), "logo_url": u.get("logo_url"),
            "foto_url": u.get("foto_url"), "slug": u.get("pagina_slug")}


def agente(slug: str) -> Dict[str, Any]:
    with get_db() as db:
        return _agente_salida(_agente_publico(db.cursor, slug))


def valorar(datos: Dict[str, Any], ip: Optional[str] = None) -> Dict[str, Any]:
    tipo = (datos.get("tipo") or "").strip().lower()
    if tipo not in TIPOS:
        raise ValoradorError("invalido", "Elige el tipo de inmueble.", "tipo")
    try:
        area = float(datos.get("area"))
    except (TypeError, ValueError):
        raise ValoradorError("invalido", "Escribe el área en metros cuadrados.", "area")
    if not 15 <= area <= 20000:
        raise ValoradorError("invalido", "El área debe estar entre 15 y 20.000 m².", "area")
    hab = datos.get("habitaciones")
    hab = int(hab) if str(hab or "").isdigit() and 0 <= int(hab) <= 12 else None
    banos = datos.get("banos")
    banos = int(banos) if str(banos or "").isdigit() and 0 <= int(banos) <= 12 else None
    ip_hash = _hash(f"ip:{ip}") if ip else None

    with get_db() as db:
        cur = db.cursor
        b = fetch_one(cur, "SELECT id, nombre, comuna, municipio FROM barrios WHERE id = %s",
                      (int(datos.get("barrio_id") or 0),))
        if not b:
            raise ValoradorError("invalido", "Elige el barrio de la lista.", "barrio")
        if ip_hash and (scalar(cur, """
                SELECT COUNT(*) FROM valoraciones WHERE ip_hash = %s AND created_at > NOW() - INTERVAL '1 day'
            """, (ip_hash,)) or 0) >= MAX_VALORACIONES_IP_DIA:
            raise ValoradorError("limite", "Hiciste muchas valoraciones hoy. Inténtalo mañana.")
        ag = _agente_publico(cur, datos.get("agente"))
        resultado = estimar(cur, tipo, b, area, hab)
        token = secrets.token_urlsafe(18)
        cur.execute("""
            INSERT INTO valoraciones (token, agente_id, tipo_propiedad, barrio_id, barrio, comuna, municipio,
                                      area, habitaciones, banos, resultado, desde, ip_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (token, ag["id"] if ag else None, tipo, b["id"], b["nombre"], b["comuna"], b["municipio"],
              area, hab, banos, json.dumps(resultado), (datos.get("desde") or "")[:60] or None, ip_hash))
        db.conn.commit()
    return {"token": token, "resultado": resultado, "agente": _agente_salida(ag)}


def _valoracion(cur, token: str) -> Dict[str, Any]:
    v = fetch_one(cur, "SELECT * FROM valoraciones WHERE token = %s", (token or "",))
    if not v:
        raise ValoradorError("no_encontrada", "No encontramos esta valoración. Vuelve a empezar.")
    return v


def pedir_contacto(token: str, datos: Dict[str, Any]) -> Dict[str, Any]:
    nombre = re.sub(r"\s+", " ", (datos.get("nombre") or "")).strip()[:120]
    if len(nombre) < 2:
        raise ValoradorError("invalido", "Escribe tu nombre.", "nombre")
    tel10 = normalize_phone(datos.get("telefono") or "")
    if not tel10 or len(tel10) != 10 or not tel10.startswith("3"):
        raise ValoradorError("invalido", "Escribe un celular colombiano de 10 dígitos (empieza por 3).", "telefono")
    intencion = datos.get("intencion")
    if intencion not in INTENCIONES:
        raise ValoradorError("invalido", "Cuéntanos si quieres vender o arrendar.", "intencion")
    plazo = datos.get("plazo") if datos.get("plazo") in PLAZOS else "explorando"
    if not datos.get("acepta"):
        raise ValoradorError("invalido", "Para conectarte con un agente necesitamos tu autorización.", "acepta")
    tel = "+57" + tel10

    with get_db() as db:
        cur = db.cursor
        v = _valoracion(cur, token)
        if v["estado"] in ("activa", "retirada"):
            raise ValoradorError("ya", "Esta valoración ya tiene tu contacto confirmado.")
        if v["codigos_enviados"] >= MAX_CODIGOS or (scalar(cur, """
                SELECT COALESCE(SUM(codigos_enviados), 0) FROM valoraciones
                WHERE telefono = %s AND created_at > NOW() - INTERVAL '1 day'
            """, (tel,)) or 0) >= MAX_CODIGOS * 2:
            raise ValoradorError("limite", "Ya pediste varios códigos. Espera un rato e inténtalo de nuevo.")
        codigo = f"{secrets.randbelow(1_000_000):06d}"
        cur.execute("""
            UPDATE valoraciones SET nombre = %s, telefono = %s, intencion = %s, plazo = %s,
                   consentimiento_at = NOW(), consentimiento_version = %s, estado = 'pendiente',
                   codigo_hash = %s, codigo_expira_at = NOW() + %s, codigo_intentos = 0,
                   codigos_enviados = codigos_enviados + 1
            WHERE id = %s
        """, (nombre, tel, intencion, plazo, CONSENTIMIENTO_VERSION, _hash(f"{v['id']}:{codigo}"),
              VIGENCIA_CODIGO, v["id"]))
        db.conn.commit()

    try:
        enviar_whatsapp(tel, f"Tu código de Fynder es *{codigo}*.\n\nCon él confirmas que quieres que un agente "
                             "te contacte por tu inmueble. Vence en 10 minutos. Si no lo pediste, ignora este mensaje.")
    except WhatsAppSendError as e:
        print(f"⚠️ No se pudo enviar el código de la valoración {v['id']}: {e}")
        raise ValoradorError("envio", "No pudimos enviarte el código por WhatsApp. Inténtalo de nuevo en unos minutos.")
    return {"ok": True, "telefono": f"*** *** {tel10[-4:]}", "vence_minutos": 10}


def verificar(token: str, codigo: str) -> Dict[str, Any]:
    codigo = re.sub(r"\D", "", codigo or "")
    if len(codigo) != 6:
        raise ValoradorError("invalido", "El código tiene 6 dígitos.", "codigo")
    with get_db() as db:
        cur = db.cursor
        v = _valoracion(cur, token)
        if v["estado"] == "activa":
            return {"ok": True, "ya": True}
        if v["estado"] != "pendiente" or not v.get("codigo_hash"):
            raise ValoradorError("invalido", "Primero pide el código.")
        if v["codigo_intentos"] >= MAX_INTENTOS:
            raise ValoradorError("limite", "Demasiados intentos. Pide un código nuevo.")
        if v["codigo_expira_at"] < scalar(cur, "SELECT NOW()"):
            raise ValoradorError("vencido", "El código venció. Pide uno nuevo.")
        if not hmac.compare_digest(v["codigo_hash"], _hash(f"{v['id']}:{codigo}")):
            cur.execute("UPDATE valoraciones SET codigo_intentos = codigo_intentos + 1 WHERE id = %s", (v["id"],))
            db.conn.commit()
            raise ValoradorError("incorrecto", "El código no coincide.", "codigo")
        retiro = secrets.token_urlsafe(18)
        cur.execute("""
            UPDATE valoraciones SET estado = 'activa', verificada_at = NOW(), token_retiro = %s, codigo_hash = NULL
            WHERE id = %s
        """, (retiro, v["id"]))
        ag = fetch_one(cur, "SELECT id, nombre, telefono FROM chat_users WHERE id = %s",
                       (v["agente_id"],)) if v.get("agente_id") else None
        db.conn.commit()

    _avisar(v, ag, retiro)
    return {"ok": True, "agente": {"nombre": ag["nombre"]} if ag else None}


def _resumen(v: Dict[str, Any]) -> str:
    return f"{TIPOS.get(v['tipo_propiedad'], v['tipo_propiedad'])} de {float(v['area']):.0f} m² en {v['barrio']}"


def _avisar(v: Dict[str, Any], ag: Optional[Dict[str, Any]], retiro: str) -> None:
    """Al propietario: confirmación y cómo retirarse. Al agente de la página: que tiene un propietario."""
    quien = f"*{ag['nombre']}* te escribirá" if ag else "Hasta 3 agentes de tu zona podrán escribirte"
    try:
        enviar_whatsapp(v["telefono"], f"¡Listo, {v['nombre'].split()[0]}! {quien} por tu {_resumen(v).lower()}.\n\n"
                                       f"Si cambias de opinión, aquí dejas de recibir mensajes: {_frontend()}/valorar/retirar/{retiro}")
    except WhatsAppSendError as e:
        print(f"⚠️ No se pudo confirmar la valoración {v['id']}: {e}")
    if ag and ag.get("telefono"):
        try:
            enviar_whatsapp(ag["telefono"], f"🏠 Un propietario valoró su inmueble en tu página: {_resumen(v)} y quiere "
                                            f"{INTENCIONES[v['intencion']]} ({PLAZOS[v['plazo']].lower()}).\n\n"
                                            f"Su contacto está en Fynder: {_frontend()}/chat/mercado/propietarios")
        except WhatsAppSendError as e:
            print(f"⚠️ No se pudo avisar al agente {ag['id']} de la valoración {v['id']}: {e}")


def retirar(token_retiro: str) -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        v = fetch_one(cur, "SELECT id, estado FROM valoraciones WHERE token_retiro = %s", (token_retiro or "",))
        if not v:
            raise ValoradorError("no_encontrada", "Este link no es válido.")
        if v["estado"] != "retirada":
            cur.execute("UPDATE valoraciones SET estado = 'retirada', retirada_at = NOW() WHERE id = %s", (v["id"],))
            db.conn.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Del lado del agente
# ---------------------------------------------------------------------------

_VISIBLE = f"""
    v.estado = 'activa' AND v.verificada_at > NOW() - INTERVAL '{VIGENCIA_DIAS} days'
    AND (v.agente_id IS NULL OR v.agente_id = %(u)s)
"""


def _abiertos_sql() -> str:
    # El agente de la página (o el mismo dueño, si es agente) no ocupa uno de los 3 cupos.
    return """(SELECT COUNT(*) FROM desbloqueos d WHERE d.tipo = 'valoracion' AND d.ref_id = v.id
              AND d.estado = 'vigente' AND d.motivo_gratis IS DISTINCT FROM 'propia')"""


def hay_para(cur, user_id: int) -> bool:
    """¿Tiene propietarios para ver? (herramientas por etapas)."""
    return bool(scalar(cur, f"SELECT 1 FROM valoraciones v WHERE {_VISIBLE} LIMIT 1", {"u": user_id}))


def para_agente(user_id: int, limite: int = 100) -> Dict[str, Any]:
    """Propietarios que quieren vender o arrendar. Sin contacto: sale con un desbloqueo."""
    with get_db() as db:
        filas = fetch_all(db.cursor, f"""
            SELECT v.id, v.tipo_propiedad, v.barrio, v.comuna, v.municipio, v.area, v.habitaciones, v.banos,
                   v.intencion, v.plazo, v.resultado, v.verificada_at, v.agente_id = %(u)s AS propio,
                   {_abiertos_sql()} AS abiertos,
                   EXISTS (SELECT 1 FROM desbloqueos d WHERE d.tipo = 'valoracion' AND d.ref_id = v.id
                           AND d.user_id = %(u)s AND d.estado = 'vigente') AS desbloqueado
            FROM valoraciones v
            WHERE {_VISIBLE}
            ORDER BY v.verificada_at DESC LIMIT %(l)s
        """, {"u": user_id, "l": limite})
    items = []
    for f in filas:
        propio = bool(f["propio"])
        if not propio and not f["desbloqueado"] and f["abiertos"] >= MAX_AGENTES:
            continue
        r = f["resultado"] or {}
        items.append({
            "id": f["id"], "tipo": TIPOS.get(f["tipo_propiedad"], f["tipo_propiedad"]),
            "barrio": f["barrio"], "comuna": f["comuna"], "municipio": f["municipio"],
            "area": float(f["area"]), "habitaciones": f["habitaciones"], "banos": f["banos"],
            "intencion": f["intencion"], "plazo": f["plazo"], "plazo_texto": PLAZOS.get(f["plazo"]),
            "venta": r.get("venta"), "arriendo": r.get("arriendo"),
            "fecha": f["verificada_at"].isoformat(), "propio": propio, "desbloqueado": bool(f["desbloqueado"]),
            "abiertos": int(f["abiertos"]), "max_agentes": MAX_AGENTES,
        })
    return {"items": items, "total": len(items), "vigencia_dias": VIGENCIA_DIAS}


def mi_valorador(user_id: int) -> Dict[str, Any]:
    """Para la pestaña Mi página: su link y cuánto le ha servido."""
    with get_db() as db:
        cur = db.cursor
        u = fetch_one(cur, "SELECT pagina_slug, pagina_activa FROM chat_users WHERE id = %s", (user_id,))
        n = fetch_one(cur, """
            SELECT COUNT(*) AS valoraciones, COUNT(*) FILTER (WHERE estado = 'activa') AS propietarios
            FROM valoraciones WHERE agente_id = %s
        """, (user_id,)) or {}
    slug = (u or {}).get("pagina_slug")
    activa = bool(u and u.get("pagina_activa") and slug)
    return {"activo": activa, "link": f"{_frontend()}/a/{slug}/valorar" if activa else None,
            "valoraciones": int(n.get("valoraciones") or 0), "propietarios": int(n.get("propietarios") or 0)}


def resolver_contacto(cur, ref) -> Dict[str, Any]:
    """Para suscripcion_service._resolver (tipo 'valoracion')."""
    try:
        vid = int(ref)
    except (TypeError, ValueError):
        return {"error": "no_encontrada", "mensaje": f"Propietario inválido: {ref}"}
    v = fetch_one(cur, """
        SELECT id, tipo_propiedad, area, barrio, nombre, telefono, estado, verificada_at, agente_id,
               verificada_at < NOW() - make_interval(days => %s) AS vencida
        FROM valoraciones WHERE id = %s
    """, (VIGENCIA_DIAS, vid))
    if not v:
        return {"error": "no_encontrada", "mensaje": f"No encontré el propietario {vid}."}
    return {
        "ref_id": v["id"], "codigo": f"propietario-{v['id']}", "titulo": f"Propietario · {_resumen(v)}",
        "estado": v["estado"], "vencida": bool(v["vencida"]), "agente_id": v["agente_id"],
        "contacto": {"telefono": v["telefono"], "nombre": v["nombre"], "agencia": None},
    }


def regla_desbloqueo(cur, user_id: int, r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """None si se puede abrir (y cuánto cuesta lo decide _evaluar); si no, el error."""
    if r.get("agente_id") and r["agente_id"] != user_id:
        return {"error": "no_disponible", "mensaje": "Este propietario pidió hablar solo con el agente de cuya página llegó. No se cobra."}
    if r.get("estado") != "activa":
        return {"error": "no_disponible", "mensaje": "Este propietario ya no quiere que lo contacten. No se cobra."}
    if r.get("vencida"):
        return {"error": "no_disponible", "mensaje": f"Este propietario lleva más de {VIGENCIA_DIAS} días publicado; ya no se abre. No se cobra."}
    return None


def agotado(cur, user_id: int, ref_id: int) -> bool:
    """Ya lo abrieron MAX_AGENTES agentes (sin contar a este)."""
    return (scalar(cur, """
        SELECT COUNT(*) FROM desbloqueos WHERE tipo = 'valoracion' AND ref_id = %s AND estado = 'vigente' AND user_id <> %s
          AND motivo_gratis IS DISTINCT FROM 'propia'
    """, (ref_id, user_id)) or 0) >= MAX_AGENTES
