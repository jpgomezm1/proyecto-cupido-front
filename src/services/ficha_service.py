"""
Ficha estructurada de cada inmueble (tabla propiedades_ficha, migración 051).

Los portales dejan la mitad de los datos en el texto: tipo, barrio, habitaciones,
baños o área vienen en el título, la descripción o el link. Este servicio arma
una ficha normalizada en dos pasos:

  1. Determinístico: el link de Wasi trae tipo, negocio, barrio y ciudad
     (`casa-venta-altos-del-escobero-envigado`).
  2. IA (Claude Haiku, salida forzada por esquema): lee título y descripción y
     devuelve los números, el estado y las características con un vocabulario
     controlado, más un resumen de una línea.

Las columnas originales de `propiedades` nunca se tocan; el buscador usa
COALESCE(original, ficha). `fuente_hash` cambia si cambian el texto o el precio,
y entonces la ficha se rehace.
"""

import hashlib
import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import unquote, urlparse

from src.services.db import fetch_all, get_db

MODELO = os.getenv("FYNDER_MODELO_FICHA", "claude-haiku-4-5")
VERSION = 1

TIPOS = ["apartamento", "apartaestudio", "casa", "casa_campestre", "finca", "lote",
         "local", "oficina", "consultorio", "bodega", "edificio", "hotel", "otro"]

ESTADOS = ["sobre_planos", "nuevo", "usado", "remodelado", "para_remodelar"]

# Vocabulario controlado: lo que los agentes piden y lo que el buscador puede filtrar o puntuar.
CARACTERISTICAS = [
    "penthouse", "duplex", "terraza", "balcon", "patio", "jardin", "estudio",
    "cuarto_servicio", "cuarto_util", "chimenea", "vista_panoramica", "vista_verde",
    "iluminado", "tranquilo", "cerca_via_principal", "piso_alto", "primer_piso",
    "unidad_cerrada", "porteria_24h", "ascensor", "piscina", "gimnasio", "zona_bbq",
    "parque_infantil", "zonas_verdes", "salon_social", "coworking", "acepta_mascotas",
    "cocina_abierta", "cocina_integral", "parqueadero_cubierto", "parqueadero_visitantes",
    "amoblado", "cerca_transporte", "cerca_centro_comercial", "parcelacion",
    "agua_propia", "uso_comercial", "renta_actual",
]

_TIPO_SLUG = {
    "apartamento": "apartamento", "departamento": "apartamento", "piso": "apartamento",
    "penthouse": "apartamento", "dúplex": "apartamento", "duplex": "apartamento",
    "ph": "apartamento", "apartaestudio": "apartaestudio", "casa": "casa",
    "chalet": "casa", "casa-campestre": "casa_campestre", "campestre": "casa_campestre",
    "cabaña": "casa_campestre", "finca": "finca", "lote-terreno": "lote", "lote": "lote",
    "terreno": "lote", "lote-comercial": "lote", "local": "local", "oficina": "oficina",
    "consultorio": "consultorio", "bodega": "bodega", "edificio": "edificio",
    "edificio-apartamentos": "edificio", "hoteles": "hotel", "condominio": "casa",
}
_CARACT_SLUG = {"penthouse": "penthouse", "dúplex": "duplex", "duplex": "duplex", "ph": "penthouse"}


def _plano(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


def fuente_hash(p: Dict[str, Any]) -> str:
    base = "|".join(str(p.get(k) or "") for k in ("titulo", "descripcion", "precio", "url"))
    return hashlib.md5(base.encode("utf-8")).hexdigest()


# ── 1. Link de Wasi ──────────────────────────────────────────────────────────

def _ciudades_conocidas() -> List[str]:
    with get_db() as db:
        filas = fetch_all(db.cursor, """
            SELECT ciudad FROM propiedades WHERE ciudad IS NOT NULL
            GROUP BY ciudad HAVING COUNT(*) >= 3
        """)
    return sorted({r["ciudad"] for r in filas}, key=lambda c: -len(c))


def desde_link_wasi(url: Optional[str], ciudades: Iterable[str]) -> Dict[str, Any]:
    """`.../casa-venta-altos-del-escobero-envigado/123` → tipo, negocio, barrio, ciudad."""
    host = urlparse(url or "").netloc.lower()
    if not host.endswith("wasi.co"):
        return {}
    seg = unquote(urlparse(url).path.strip("/").split("/")[0]).lower()
    m = re.match(r"(.+?)-(venta-y-arriendo|venta|arriendo)-(.+)$", seg)
    if not m:
        return {}
    tipo_slug, negocio, resto = m.groups()
    out: Dict[str, Any] = {"negocio": "arriendo" if negocio == "arriendo" else "venta"}
    if tipo_slug in _TIPO_SLUG:
        out["tipo"] = _TIPO_SLUG[tipo_slug]
    if tipo_slug in _CARACT_SLUG:
        out["caracteristicas"] = [_CARACT_SLUG[tipo_slug]]
    resto_plano = _plano(resto)
    for ciudad in ciudades:
        cslug = re.sub(r"\s+", "-", _plano(ciudad))
        if resto_plano == cslug or resto_plano.endswith("-" + cslug):
            out["ciudad"] = ciudad
            barrio = resto_plano[: len(resto_plano) - len(cslug)].strip("-")
            barrio, otra = _limpiar_barrio(barrio, ciudades)
            # "envigado-loma-escobero-medellín": el agente escribió el municipio
            # real en la zona y dejó Medellín como ciudad del portal.
            if otra and _plano(ciudad) == "medellin":
                out["ciudad"] = otra
            if barrio:
                out["barrio"] = barrio.replace("-", " ").title()
            break
    return out


def _limpiar_barrio(barrio: str, ciudades: Iterable[str]):
    """Quita municipios pegados al barrio. Devuelve (barrio, municipio_encontrado_al_inicio)."""
    otra = None
    slugs = [(c, re.sub(r"\s+", "-", _plano(c))) for c in ciudades]
    cambio = True
    while barrio and cambio:
        cambio = False
        for c, cs in slugs:
            if barrio == cs:
                return "", otra or c
            if barrio.startswith(cs + "-"):
                otra = otra or c
                barrio, cambio = barrio[len(cs) + 1:], True
            elif barrio.endswith("-" + cs):
                barrio, cambio = barrio[: -len(cs) - 1], True
    return barrio, otra


# ── 2. Reglas sobre el texto (gratis) ───────────────────────────────────────

_NUM = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
        "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
_N = r"(\d{1,2}|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)"


def _n(t: str) -> Optional[int]:
    return int(t) if t.isdigit() else _NUM.get(t)


_REGLAS_NUM = {
    "habitaciones": [rf"\b{_N}\s+(?:amplias\s+|c[oó]modas\s+|espaciosas\s+)?(?:habitaciones|alcobas|cuartos|dormitorios|espacios de descanso|habitaci[oó]n|alcoba)\b",
                     r"habitaciones:\s*(\d+)"],
    "banos": [rf"\b{_N}\s+(?:baños|banos|baño)\b", r"ba[nñ]os:\s*(\d+)"],
    "parqueaderos": [rf"\b{_N}\s+(?:parqueaderos?|garajes?|celdas? de parqueo|plazas? de parqueo)\b",
                     r"garaje:\s*(\d+)"],
    "estrato": [r"estrato:?\s*([1-6])\b"],
    "piso": [r"\bpiso\s+(\d{1,2})\b"],
}
_AREA = [r"[áa]rea (?:construida|privada|total)?:?\s*([\d.,]+)\s*(?:m2|m²|mts|metros)",
         r"\b([\d.,]{2,7})\s*(?:m2|m²|mts2?|metros cuadrados)"]
_ADMIN = r"administraci[oó]n(?: de)?:?\s*\$?\s*([\d.]{5,11})"

_REGLAS_CARACT = {
    "terraza": r"terraza", "balcon": r"balc[oó]n", "patio": r"\bpatio", "jardin": r"jard[ií]n",
    "estudio": r"\bestudio\b", "cuarto_servicio": r"(?:cuarto|alcoba|habitaci[oó]n) de servicio",
    "cuarto_util": r"cuarto [úu]til|dep[oó]sito", "chimenea": r"chimenea",
    "vista_panoramica": r"vistas? panor[áa]micas?|vista a la ciudad",
    "vista_verde": r"vista (?:a|al|hacia)?\s*(?:la )?(?:zona verde|bosque|monta[ñn]a|naturaleza|verde)",
    "iluminado": r"iluminad|luminos|luz natural", "tranquilo": r"tranquil|silencios",
    "unidad_cerrada": r"unidad cerrada|conjunto cerrado|urbanizaci[oó]n cerrada|unidad residencial",
    "porteria_24h": r"porter[ií]a|vigilancia 24|seguridad 24",
    "ascensor": r"ascensor", "piscina": r"piscina", "gimnasio": r"gimnasio|\bgym\b",
    "zona_bbq": r"bbq|barbacoa|asador", "parque_infantil": r"parque infantil|juegos infantiles",
    "zonas_verdes": r"zonas? verdes?", "salon_social": r"sal[oó]n social|sal[oó]n comunal",
    "coworking": r"coworking", "acepta_mascotas": r"mascotas|pet friendly",
    "cocina_abierta": r"cocina (?:abierta|americana|de concepto abierto|tipo americano)",
    "cocina_integral": r"cocina integral", "parqueadero_visitantes": r"parqueaderos? de visitantes",
    "amoblado": r"amoblad|amueblad", "penthouse": r"penthouse|pent-house",
    "duplex": r"d[uú]plex", "parcelacion": r"parcelaci[oó]n", "uso_comercial": r"uso comercial",
    "renta_actual": r"arrendad[oa] actualmente|con renta|actualmente arrendad",
}


def desde_texto(p: Dict[str, Any]) -> Dict[str, Any]:
    """Números y características que se leen con reglas del título y la descripción."""
    t = f"{p.get('titulo') or ''}. {p.get('descripcion') or ''}".lower()
    out: Dict[str, Any] = {}
    for campo, reglas in _REGLAS_NUM.items():
        for rx in reglas:
            m = re.search(rx, t)
            if m and _n(m.group(1)) is not None:
                out[campo] = _n(m.group(1))
                break
    for rx in _AREA:
        m = re.search(rx, t)
        if m:
            crudo = m.group(1).strip(".,")
            try:
                v = float(crudo.replace(".", "").replace(",", ".")) if re.search(r"\.\d{3}\b", crudo) \
                    else float(crudo.replace(",", "."))
            except ValueError:
                continue
            if 10 <= v <= 100000:
                out["area_m2"] = v
                break
    m = re.search(_ADMIN, t)
    if m:
        try:
            out["administracion"] = int(m.group(1).replace(".", ""))
        except ValueError:
            pass
    out["caracteristicas"] = sorted(c for c, rx in _REGLAS_CARACT.items() if re.search(rx, t))
    if re.search(r"para remodelar|para reformar|para actualizar", t):
        out["estado"] = "para_remodelar"
    elif "sobre planos" in t:
        out["estado"] = "sobre_planos"
    elif re.search(r"para estrenar|\bnuevo\b", t):
        out["estado"] = "nuevo"
    elif re.search(r"remodelad|renovad|reformad", t):
        out["estado"] = "remodelado"
    return out


_RESIDENCIAL = {"apartamento", "casa", "casa_campestre", "finca"}


def completa_por_reglas(f: Dict[str, Any]) -> bool:
    """¿La ficha armada sin IA ya tiene lo que el buscador necesita?"""
    if not f.get("tipo") or not f.get("ciudad") or not f.get("area_m2"):
        return False
    if f["tipo"] in _RESIDENCIAL and not f.get("habitaciones"):
        return False
    return True


def ficha_por_reglas(p: Dict[str, Any], pista: Dict[str, Any]) -> Dict[str, Any]:
    """Ficha sin IA: link + reglas + columnas originales. El resumen es el título."""
    texto = desde_texto(p)
    base = {
        "tipo": None, "habitaciones": p.get("habitaciones") or texto.get("habitaciones"),
        "banos": p.get("banos") or texto.get("banos"), "parqueaderos": texto.get("parqueaderos"),
        "area_m2": p.get("area_construida") or texto.get("area_m2"), "piso": texto.get("piso"),
        "estrato": p.get("estrato") or texto.get("estrato"), "administracion": texto.get("administracion"),
        "estado": texto.get("estado"), "caracteristicas": texto.get("caracteristicas", []),
        "ciudad": p.get("ciudad"), "resumen": (p.get("titulo") or "")[:200],
    }
    f = armar_ficha(p, base, pista)
    if not f["tipo"] and p.get("tipo_propiedad"):
        tp = _plano(p["tipo_propiedad"])
        f["tipo"] = next((v for k, v in _TIPO_SLUG.items() if _plano(k) in tp), None)
    f["modelo"] = "reglas"
    return f


# ── 3. IA ────────────────────────────────────────────────────────────────────

_HERRAMIENTA = {
    "name": "ficha",
    "description": "Ficha normalizada del inmueble, solo con lo que dice el texto.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tipo": {"type": ["string", "null"], "enum": TIPOS + [None]},
            "negocio": {"type": ["string", "null"], "enum": ["venta", "arriendo", None]},
            "barrio": {"type": ["string", "null"],
                       "description": "Barrio o sector (p. ej. 'Los Balsos', 'Zúñiga', 'Llanogrande'). No la ciudad."},
            "ciudad": {"type": ["string", "null"], "description": "Municipio (Medellín, Envigado, Rionegro…)."},
            "habitaciones": {"type": ["integer", "null"]},
            "banos": {"type": ["integer", "null"]},
            "parqueaderos": {"type": ["integer", "null"]},
            "area_m2": {"type": ["number", "null"], "description": "Área construida o privada en m²."},
            "area_lote_m2": {"type": ["number", "null"]},
            "piso": {"type": ["integer", "null"], "description": "Piso en el que está (apartamentos)."},
            "estrato": {"type": ["integer", "null"]},
            "ano_construccion": {"type": ["integer", "null"]},
            "administracion": {"type": ["integer", "null"], "description": "Cuota mensual en pesos."},
            "estado": {"type": ["string", "null"], "enum": ESTADOS + [None]},
            "caracteristicas": {"type": "array", "items": {"type": "string", "enum": CARACTERISTICAS}},
            "resumen": {"type": "string", "description": "Una frase de máximo 25 palabras con lo distintivo."},
        },
        "required": ["tipo", "caracteristicas", "resumen"],
    },
}

_SISTEMA = """Extraes la ficha de un inmueble en venta o arriendo en Antioquia (Colombia) a partir \
de su publicación. Usa SOLO lo que dice el texto; si un dato no aparece, déjalo en null. \
"3 alcobas" = 3 habitaciones; "garaje"/"parqueadero" = parqueaderos; "mts"/"m2" = área. \
"Penthouse" y "dúplex" son apartamentos (márcalos en características). Las características deben \
salir de lo que el texto afirma: no infieras piscina o gimnasio si no se mencionan. "Unidad cerrada" \
o "conjunto cerrado" = unidad_cerrada; "parcelación" = parcelacion."""


def _texto_para_ia(p: Dict[str, Any], pista: Dict[str, Any]) -> str:
    partes = [f"Título: {p.get('titulo') or ''}"]
    if pista:
        partes.append(f"Datos del link: {json.dumps(pista, ensure_ascii=False)}")
    for k in ("tipo_propiedad", "ciudad", "zona", "habitaciones", "banos", "area_construida", "estrato"):
        if p.get(k) not in (None, ""):
            partes.append(f"{k}: {p[k]}")
    desc = re.sub(r"\s+", " ", p.get("descripcion") or "")[:2500]
    partes.append(f"Descripción: {desc}")
    return "\n".join(partes)


def _llamar_ia(cliente, p: Dict[str, Any], pista: Dict[str, Any]) -> Dict[str, Any]:
    import time
    t0 = time.time()
    r = cliente.messages.create(
        model=MODELO, max_tokens=700, system=_SISTEMA,
        tools=[_HERRAMIENTA], tool_choice={"type": "tool", "name": "ficha"},
        messages=[{"role": "user", "content": _texto_para_ia(p, pista)}],
    )
    try:
        from src.core.ai_usage_tracker import get_ai_tracker
        get_ai_tracker().track_anthropic_response(MODELO, "ficha_inmueble", "ficha_service.enriquecer", r, t0,
                                                  context={"propiedad_id": p.get("id")})
    except Exception:  # noqa: BLE001
        pass
    return next(b for b in r.content if b.type == "tool_use").input


def _entero(v, minimo=0, maximo=None):
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    if n < minimo or (maximo is not None and n > maximo):
        return None
    return n


def armar_ficha(p: Dict[str, Any], ia: Dict[str, Any], pista: Dict[str, Any]) -> Dict[str, Any]:
    """Combina link + IA y valida rangos. El link manda en tipo/barrio/ciudad."""
    caract = sorted({c for c in (ia.get("caracteristicas") or []) if c in CARACTERISTICAS}
                    | set(pista.get("caracteristicas") or []))
    area = ia.get("area_m2")
    try:
        area = float(area) if area is not None and 5 <= float(area) <= 100000 else None
    except (TypeError, ValueError):
        area = None
    lote = ia.get("area_lote_m2")
    try:
        lote = float(lote) if lote is not None and 5 <= float(lote) <= 10_000_000 else None
    except (TypeError, ValueError):
        lote = None
    tipo = pista.get("tipo") or (ia.get("tipo") if ia.get("tipo") in TIPOS else None)
    return {
        "propiedad_id": p["id"],
        "tipo": tipo,
        "negocio": pista.get("negocio") or ia.get("negocio"),
        "barrio": pista.get("barrio") or (ia.get("barrio") or None),
        "ciudad": pista.get("ciudad") or (ia.get("ciudad") or None),
        "habitaciones": _entero(ia.get("habitaciones"), 0, 30),
        "banos": _entero(ia.get("banos"), 0, 30),
        "parqueaderos": _entero(ia.get("parqueaderos"), 0, 50),
        "area_m2": area,
        "area_lote_m2": lote,
        "piso": _entero(ia.get("piso"), -3, 80),
        "estrato": _entero(ia.get("estrato"), 1, 6),
        "ano_construccion": _entero(ia.get("ano_construccion"), 1900, 2035),
        "administracion": _entero(ia.get("administracion"), 0, 50_000_000),
        "estado": ia.get("estado") if ia.get("estado") in ESTADOS else None,
        "caracteristicas": caract,
        "resumen": (ia.get("resumen") or "")[:300] or None,
        "fuente_hash": fuente_hash(p),
        "modelo": MODELO,
        "version": VERSION,
    }


_COLUMNAS = ["propiedad_id", "tipo", "negocio", "barrio", "ciudad", "habitaciones", "banos",
             "parqueaderos", "area_m2", "area_lote_m2", "piso", "estrato", "ano_construccion",
             "administracion", "estado", "caracteristicas", "resumen", "fuente_hash", "modelo", "version"]


def guardar(cur, ficha: Dict[str, Any]) -> None:
    cols = ", ".join(_COLUMNAS)
    marcas = ", ".join(["%s"] * len(_COLUMNAS))
    act = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLUMNAS[1:])
    cur.execute(f"""
        INSERT INTO propiedades_ficha ({cols}) VALUES ({marcas})
        ON CONFLICT (propiedad_id) DO UPDATE SET {act}, updated_at = NOW()
    """, [ficha[c] for c in _COLUMNAS])


def pendientes(limite: int, solo_activas: bool = True) -> List[Dict[str, Any]]:
    """Inmuebles sin ficha o con ficha vieja (cambió el texto/precio o la versión)."""
    with get_db() as db:
        filas = fetch_all(db.cursor, f"""
            SELECT p.id, p.titulo, p.descripcion, p.precio, p.url, p.tipo_propiedad, p.ciudad,
                   p.zona, p.habitaciones, p.banos, p.area_construida, p.estrato,
                   f.fuente_hash AS hash_actual, f.version AS version_actual
            FROM propiedades p
            LEFT JOIN propiedades_ficha f ON f.propiedad_id = p.id
            WHERE {'p.activa AND' if solo_activas else ''} TRUE
            ORDER BY (f.propiedad_id IS NULL) DESC, p.id DESC
        """)
    out = []
    for p in filas:
        if p["hash_actual"] != fuente_hash(p) or (p["version_actual"] or 0) < VERSION:
            out.append(p)
            if len(out) >= limite:
                break
    return out


def enriquecer(limite: int = 200, hilos: int = 6, con_ia: bool = True) -> Dict[str, int]:
    """
    Arma y guarda las fichas pendientes: primero link + reglas (gratis), y la IA
    solo si a la ficha le falta lo esencial (tipo, ciudad, área, habitaciones).
    Lo corren el worker y scripts/enriquecer_fichas.py.
    """
    props = pendientes(limite)
    if not props:
        return {"procesadas": 0, "errores": 0, "con_ia": 0}
    ciudades = _ciudades_conocidas()
    cliente = None
    if con_ia:
        import anthropic
        cliente = anthropic.Anthropic()

    def uno(p):
        pista = desde_link_wasi(p.get("url"), ciudades)
        por_reglas = ficha_por_reglas(p, pista)
        if completa_por_reglas(por_reglas) or not con_ia:
            return por_reglas
        try:
            return armar_ficha(p, _llamar_ia(cliente, p, pista), pista)
        except Exception as e:  # noqa: BLE001 — queda la ficha por reglas
            print(f"[FICHA] #{p['id']}: {str(e)[:120]}")
            return por_reglas

    with ThreadPoolExecutor(hilos) as pool:
        fichas = list(pool.map(uno, props))
    ok = [f for f in fichas if f]
    with get_db() as db:
        for f in ok:
            guardar(db.cursor, f)
        db.conn.commit()
    return {"procesadas": len(ok), "errores": len(props) - len(ok),
            "con_ia": sum(1 for f in ok if f["modelo"] != "reglas")}
