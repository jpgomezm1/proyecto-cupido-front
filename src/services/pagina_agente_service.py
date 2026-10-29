"""
La página pública del agente (getfynder.com/a/<slug>) y su marca en las piezas.

El agente elige su dirección, escribe una presentación corta, marca sus zonas y
sube su logo (y su foto). La página muestra sus inmuebles activos, que son los
que captó con su celular verificado, y un botón para escribirle por WhatsApp.
Solo se publica con el celular verificado: el número que sale es ese.

Diseño (migración 069, `chat_users.pagina_config`): plantilla (8), color, tipografía (9),
fondo, esquinas, estilo de tarjetas, columnas, oscurecer la portada, animaciones,
portada, titular, secciones en orden (con su interruptor), destacados, cifras,
testimonios, preguntas frecuentes y redes. `normalizar` valida todo lo que entra;
lo que no sirve se descarta en silencio y nunca rompe la página.

Cifras (`pagina_eventos`): visitas, toques a WhatsApp, inmuebles abiertos y
valorador, por día. La página pública las registra con `registrar_evento`.

El logo también aparece en las piezas que el agente le envía a su cliente
(ficha, comparativa, reporte de zona), vía `agente_service.agente_publico`.
"""

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from zoneinfo import ZoneInfo

from psycopg2.extras import Json

from src.services.db import fetch_all, fetch_one, get_db

_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$")
_RESERVADOS = {"admin", "fynder", "chat", "api", "soporte", "ayuda", "login", "registro", "terminos",
               "agente", "agentes", "a", "www", "mapa", "zona", "ficha", "comparar", "compartir"}
_URL_IMG = re.compile(r"^https://[^\s]+$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_HANDLE = re.compile(r"^@?([A-Za-z0-9._-]{1,60})$")

PLANTILLAS = ("clasica", "editorial", "minimal", "lujo", "boutique", "audaz", "ejecutiva", "natural")
FUENTES = ("moderna", "geometrica", "contemporanea", "amigable", "fuerte", "elegante", "editorial", "lujo", "clasica")
# Estilo fino; "auto" = lo que trae la plantilla.
FONDOS = ("auto", "blanco", "hueso", "crema", "gris", "salvia", "oscuro", "noche")
ESQUINAS = ("auto", "rectas", "suaves", "redondas")
TARJETAS = ("auto", "borde", "sombra", "foto")
SECCIONES = ("sobre_mi", "destacados", "cifras", "inmuebles", "testimonios", "zonas", "preguntas", "valorador", "redes")
REDES = {
    "instagram": "https://instagram.com/{}", "facebook": "https://facebook.com/{}", "tiktok": "https://tiktok.com/@{}",
    "youtube": "https://youtube.com/@{}", "linkedin": "https://linkedin.com/in/{}", "web": None,
}
CIFRAS = ("anos", "vendidos", "familias")
EVENTOS_PUBLICOS = ("visita", "whatsapp", "inmueble", "valorar")
TZ = "America/Bogota"

DEFECTO = {
    "plantilla": "clasica", "color": "#16A34A", "fuente": "moderna", "titular": None, "subtitular": None,
    "portada_url": None, "secciones": [{"id": s, "visible": True} for s in SECCIONES], "destacados": [],
    "cifras": {}, "testimonios": [], "preguntas": [], "redes": {}, "mensaje_whatsapp": None,
    "fondo": "auto", "esquinas": "auto", "tarjetas": "auto", "columnas": 3, "oscurecer": 45, "animaciones": True,
}


class PaginaError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def _sugerir_slug(nombre: Optional[str]) -> str:
    import unicodedata
    base = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:40]
    return base or "mi-pagina"


def _tel10(u: Dict[str, Any]) -> Optional[str]:
    if not u.get("telefono_verificado") or not u.get("telefono"):
        return None
    return re.sub(r"\D", "", u["telefono"])[-10:]


# ── diseño ──────────────────────────────────────────────────────────────────

def _texto(v: Any, maximo: int) -> Optional[str]:
    return (v.strip()[:maximo] or None) if isinstance(v, str) else None


def _red(red: str, v: Any) -> Optional[str]:
    """Acepta el link o el usuario («@laura.inmuebles») y devuelve el link."""
    s = _texto(v, 200)
    if not s:
        return None
    if s.startswith("https://") and _URL_IMG.match(s):
        return s
    if s.startswith("http://"):
        return "https://" + s[7:]
    if red == "web":
        return f"https://{s}" if re.match(r"^[\w.-]+\.[a-z]{2,}(/\S*)?$", s, re.I) else None
    m = _HANDLE.match(s)
    return REDES[red].format(m.group(1)) if m else None


def normalizar(c: Any) -> Dict[str, Any]:
    """La configuración que se guarda y la que se pinta: siempre completa y válida."""
    c = c if isinstance(c, dict) else {}
    out = {**DEFECTO}
    if c.get("plantilla") in PLANTILLAS:
        out["plantilla"] = c["plantilla"]
    if isinstance(c.get("color"), str) and _COLOR.match(c["color"]):
        out["color"] = c["color"].upper()
    if c.get("fuente") in FUENTES:
        out["fuente"] = c["fuente"]
    for campo, opciones in (("fondo", FONDOS), ("esquinas", ESQUINAS), ("tarjetas", TARJETAS)):
        if c.get(campo) in opciones:
            out[campo] = c[campo]
    if c.get("columnas") in (2, 3):
        out["columnas"] = c["columnas"]
    if isinstance(c.get("oscurecer"), (int, float)) and not isinstance(c.get("oscurecer"), bool):
        out["oscurecer"] = max(0, min(80, int(c["oscurecer"])))
    if isinstance(c.get("animaciones"), bool):
        out["animaciones"] = c["animaciones"]
    out["titular"] = _texto(c.get("titular"), 90)
    out["subtitular"] = _texto(c.get("subtitular"), 160)
    out["mensaje_whatsapp"] = _texto(c.get("mensaje_whatsapp"), 160)
    portada = _texto(c.get("portada_url"), 500)
    out["portada_url"] = portada if portada and _URL_IMG.match(portada) else None

    # Secciones: las conocidas, en el orden del agente; las que falten van al final, visibles.
    vistas, orden = set(), []
    for s in c.get("secciones") or []:
        sid = s.get("id") if isinstance(s, dict) else None
        if sid in SECCIONES and sid not in vistas:
            vistas.add(sid)
            orden.append({"id": sid, "visible": bool(s.get("visible", True))})
    out["secciones"] = orden + [{"id": s, "visible": True} for s in SECCIONES if s not in vistas]

    out["destacados"] = [int(i) for i in (c.get("destacados") or []) if isinstance(i, int) or (isinstance(i, str) and i.isdigit())][:3]
    cifras = c.get("cifras") if isinstance(c.get("cifras"), dict) else {}
    out["cifras"] = {k: min(int(cifras[k]), 100000) for k in CIFRAS
                     if isinstance(cifras.get(k), (int, float)) and not isinstance(cifras.get(k), bool) and cifras[k] > 0}
    out["testimonios"] = [
        {"nombre": _texto(t.get("nombre"), 60), "texto": _texto(t.get("texto"), 300), "detalle": _texto(t.get("detalle"), 60)}
        for t in (c.get("testimonios") or []) if isinstance(t, dict) and _texto(t.get("texto"), 300)
    ][:6]
    out["preguntas"] = [
        {"p": _texto(q.get("p"), 140), "r": _texto(q.get("r"), 500)}
        for q in (c.get("preguntas") or []) if isinstance(q, dict) and _texto(q.get("p"), 140) and _texto(q.get("r"), 500)
    ][:8]
    redes = c.get("redes") if isinstance(c.get("redes"), dict) else {}
    out["redes"] = {r: url for r in REDES if (url := _red(r, redes.get(r)))}
    return out


# ── el agente ───────────────────────────────────────────────────────────────

_COLUMNAS = """id, nombre, telefono, telefono_verificado, activo, pagina_slug, pagina_activa, pagina_bio,
               pagina_zonas, logo_url, foto_url, marca_nombre, pagina_config"""


def _inmuebles(cur, tel10: Optional[str]) -> List[Dict[str, Any]]:
    from src.services.clientes_service import propiedades_mini
    from src.services.mis_propiedades_service import _ES_DUENO
    if not tel10:
        return []
    ids = [f["id"] for f in fetch_all(cur, f"""
        SELECT id FROM propiedades WHERE activa AND {_ES_DUENO}
        ORDER BY fecha_actualizacion DESC NULLS LAST LIMIT 60
    """, (tel10,))]
    minis = propiedades_mini(ids)
    return [minis[i] for i in ids if i in minis]


def _vista(u: Dict[str, Any], inmuebles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Lo que pinta la plantilla (igual en la página pública y en la vista previa del editor)."""
    tel = u["telefono"] if _tel10(u) else None
    config = normalizar(u.get("pagina_config"))
    ids = {p["id"] for p in inmuebles}
    config["destacados"] = [i for i in config["destacados"] if i in ids]
    return {
        "agente": {"id": u["id"], "nombre": u["nombre"], "bio": u["pagina_bio"], "marca_nombre": u["marca_nombre"],
                   "logo_url": u["logo_url"], "foto_url": u["foto_url"], "zonas": list(u["pagina_zonas"] or []),
                   "whatsapp": tel.replace("+", "") if tel else None, "telefono": tel},
        "config": config,
        "inmuebles": inmuebles,
        "total": len(inmuebles),
    }


def mi_pagina(user_id: int) -> Dict[str, Any]:
    with get_db() as db:
        u = fetch_one(db.cursor, f"SELECT {_COLUMNAS} FROM chat_users WHERE id = %s", (user_id,))
        if not u:
            raise PaginaError("no_encontrado", "Usuario no encontrado.")
        inmuebles = _inmuebles(db.cursor, _tel10(u))
        cifras = estadisticas(db.cursor, user_id)
    return {
        "slug": u["pagina_slug"], "sugerido": _sugerir_slug(u["nombre"]), "activa": bool(u["pagina_activa"]),
        "bio": u["pagina_bio"], "zonas": list(u["pagina_zonas"] or []), "logo_url": u["logo_url"],
        "foto_url": u["foto_url"], "marca_nombre": u["marca_nombre"],
        "puede_publicar": bool(u["telefono_verificado"]),
        "ruta": f"/a/{u['pagina_slug']}" if u["pagina_slug"] else None,
        "config": normalizar(u.get("pagina_config")),
        "vista": _vista(u, inmuebles),
        "estadisticas": cifras,
    }


def guardar(user_id: int, datos: Dict[str, Any]) -> Dict[str, Any]:
    sets, vals = [], []
    if "slug" in datos:
        slug = (datos.get("slug") or "").strip().lower()
        if not _SLUG.match(slug) or slug in _RESERVADOS:
            raise PaginaError("slug_invalido", "La dirección debe tener de 3 a 40 letras, números o guiones.")
        with get_db() as db:
            otro = fetch_one(db.cursor, "SELECT id FROM chat_users WHERE LOWER(pagina_slug) = %s AND id <> %s",
                             (slug, user_id))
        if otro:
            raise PaginaError("slug_ocupado", "Esa dirección ya la tiene otro agente. Prueba otra.")
        sets.append("pagina_slug = %s"); vals.append(slug)
    if "bio" in datos:
        sets.append("pagina_bio = %s"); vals.append(((datos.get("bio") or "").strip()[:600]) or None)
    if "marca_nombre" in datos:
        sets.append("marca_nombre = %s"); vals.append(((datos.get("marca_nombre") or "").strip()[:80]) or None)
    if "zonas" in datos:
        zonas = [z.strip()[:40] for z in (datos.get("zonas") or []) if isinstance(z, str) and z.strip()][:8]
        sets.append("pagina_zonas = %s"); vals.append(zonas)
    for campo in ("logo_url", "foto_url"):
        if campo in datos:
            url = (datos.get(campo) or "").strip() or None
            if url and not _URL_IMG.match(url):
                raise PaginaError("imagen_invalida", "La imagen debe ser un enlace https.")
            sets.append(f"{campo} = %s"); vals.append(url)
    if "config" in datos:
        sets.append("pagina_config = %s"); vals.append(Json(normalizar(datos.get("config"))))
    if "activa" in datos:
        activa = bool(datos.get("activa"))
        if activa:
            actual = mi_pagina(user_id)
            if not actual["puede_publicar"]:
                raise PaginaError("sin_celular", "Verifica tu celular para publicar tu página.")
            if not (datos.get("slug") or actual["slug"]):
                raise PaginaError("sin_slug", "Elige la dirección de tu página antes de publicarla.")
        sets.append("pagina_activa = %s"); vals.append(activa)
    if sets:
        with get_db() as db:
            db.cursor.execute(f"UPDATE chat_users SET {', '.join(sets)} WHERE id = %s", vals + [user_id])
            db.conn.commit()
    return mi_pagina(user_id)


def publica(slug: str) -> Dict[str, Any]:
    """Lo que ve cualquiera en /a/<slug>. Sin teléfonos de terceros: solo el del agente."""
    with get_db() as db:
        u = fetch_one(db.cursor, f"""
            SELECT {_COLUMNAS} FROM chat_users WHERE LOWER(pagina_slug) = %s AND pagina_activa AND activo
        """, ((slug or "").lower(),))
        if not u or not _tel10(u):
            raise PaginaError("no_encontrado", "Esta página no existe o no está publicada.")
        inmuebles = _inmuebles(db.cursor, _tel10(u))
    return _vista(u, inmuebles)


# ── cifras ──────────────────────────────────────────────────────────────────

def sumar(cur, user_id: int, tipo: str) -> int:
    """Suma 1 al contador del día y devuelve cuántos van hoy."""
    fila = fetch_one(cur, f"""
        INSERT INTO pagina_eventos (user_id, dia, tipo, n) VALUES (%s, (NOW() AT TIME ZONE '{TZ}')::date, %s, 1)
        ON CONFLICT (user_id, dia, tipo) DO UPDATE SET n = pagina_eventos.n + 1
        RETURNING n
    """, (user_id, tipo))
    return int(fila["n"])


def hoy(cur, user_id: int, tipo: str) -> int:
    fila = fetch_one(cur, f"""SELECT n FROM pagina_eventos WHERE user_id = %s AND tipo = %s
                              AND dia = (NOW() AT TIME ZONE '{TZ}')::date""", (user_id, tipo))
    return int(fila["n"]) if fila else 0


def registrar_evento(slug: str, tipo: str) -> None:
    """Desde la página pública (best-effort: nunca rompe la página)."""
    if tipo not in EVENTOS_PUBLICOS:
        raise PaginaError("evento_invalido", "Evento desconocido.")
    try:
        with get_db() as db:
            u = fetch_one(db.cursor, "SELECT id FROM chat_users WHERE LOWER(pagina_slug) = %s AND pagina_activa",
                          ((slug or "").lower(),))
            if u:
                sumar(db.cursor, u["id"], tipo)
                db.conn.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[PAGINA] evento {tipo} de {slug}: {e}")


def estadisticas(cur, user_id: int) -> Dict[str, Any]:
    filas = fetch_all(cur, f"""
        SELECT dia, tipo, n FROM pagina_eventos
        WHERE user_id = %s AND tipo <> 'ia' AND dia > (NOW() AT TIME ZONE '{TZ}')::date - 30
    """, (user_id,))
    hoy_ = datetime.now(ZoneInfo(TZ)).date()
    total = {t: {"7": 0, "30": 0} for t in EVENTOS_PUBLICOS}
    por_dia = {(hoy_ - timedelta(days=i)).isoformat(): 0 for i in range(29, -1, -1)}
    for f in filas:
        dia: date = f["dia"]
        total[f["tipo"]]["30"] += f["n"]
        if (hoy_ - dia).days < 7:
            total[f["tipo"]]["7"] += f["n"]
        if f["tipo"] == "visita" and dia.isoformat() in por_dia:
            por_dia[dia.isoformat()] += f["n"]
    return {"totales": total, "visitas_por_dia": [{"dia": d, "n": n} for d, n in por_dia.items()]}
