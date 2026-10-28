"""
Buscador v3 de Fynder: del pedido del agente a los inmuebles que encajan, con el porqué.

Cuatro etapas:

  1. Entender (`interpretar`): Claude lee el pedido —con emojis, listas, barrios,
     exclusiones, "le gusta tipo X"— y devuelve un pedido estructurado validado
     por esquema: lo obligatorio, lo deseable con su peso, lo excluido. En una
     conversación recibe el pedido anterior y devuelve el pedido completo
     actualizado (nada de reglas regex para "más barato" o "mejor con balcón").
  2. Ubicar (`Gazetteer`): cada barrio, municipio o lugar de referencia se
     resuelve contra el inventario real (centro geográfico de los inmuebles de
     ese barrio) y los lugares conocidos, para puntuar por cercanía y no solo
     por coincidencia de texto.
  3. Recuperar (`_candidatos`): filtros duros amplios en SQL (negocio, tipo,
     precio, mínimos con tolerancia, exclusiones) sobre la ficha completa
     (COALESCE de las columnas originales y propiedades_ficha), más la similitud
     semántica del embedding cuando existe.
  4. Calificar (`_puntuar`, `reordenar`): puntaje explicable por componentes
     (ubicación, precio, tamaño, características) y, opcionalmente, un segundo
     paso con IA sobre los mejores 25 que lee la ficha completa.

Cada resultado trae `cumple` / `no_cumple` para mostrarle al agente el porqué.
"""

import json
import math
import os
import re
import threading
import time
import unicodedata
from collections import defaultdict
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from src.services.db import fetch_all, get_db
from src.services.ficha_service import CARACTERISTICAS, ESTADOS, TIPOS

MODELO = os.getenv("FYNDER_MODELO_BUSQUEDA", "claude-haiku-4-5")
MODELO_RESPALDO = os.getenv("FYNDER_MODELO_BUSQUEDA_RESPALDO", "claude-sonnet-4-6")
TRM = float(os.getenv("FYNDER_TRM_COP", "4000"))  # pesos por dólar para pedidos en USD

# ─────────────────────────────────────────────────────────────────────────────
# 1. Entender el pedido
# ─────────────────────────────────────────────────────────────────────────────

_ETIQUETAS_CARACT = {
    "penthouse": "penthouse", "duplex": "dúplex", "terraza": "terraza", "balcon": "balcón",
    "patio": "patio", "jardin": "jardín", "estudio": "estudio", "cuarto_servicio": "cuarto de servicio",
    "cuarto_util": "cuarto útil", "chimenea": "chimenea", "vista_panoramica": "vista panorámica",
    "vista_verde": "vista a verde", "iluminado": "iluminado", "tranquilo": "tranquilo / sin ruido",
    "cerca_via_principal": "cerca a vía principal", "piso_alto": "piso alto", "primer_piso": "primer piso",
    "unidad_cerrada": "unidad cerrada", "porteria_24h": "portería 24 h", "ascensor": "ascensor",
    "piscina": "piscina", "gimnasio": "gimnasio", "zona_bbq": "zona BBQ", "parque_infantil": "parque infantil",
    "zonas_verdes": "zonas verdes", "salon_social": "salón social", "coworking": "coworking",
    "acepta_mascotas": "acepta mascotas", "cocina_abierta": "cocina abierta",
    "cocina_integral": "cocina integral", "parqueadero_cubierto": "parqueadero cubierto",
    "parqueadero_visitantes": "parqueadero de visitantes", "amoblado": "amoblado",
    "cerca_transporte": "cerca a transporte", "cerca_centro_comercial": "cerca a centro comercial",
    "parcelacion": "parcelación", "agua_propia": "agua propia", "uso_comercial": "uso comercial",
    "renta_actual": "con renta",
}

_HERRAMIENTA = {
    "name": "pedido",
    "description": "El pedido del cliente, normalizado. Solo lo que el texto dice o implica con claridad.",
    "input_schema": {
        "type": "object",
        "properties": {
            "es_busqueda": {"type": "boolean",
                            "description": "false si el mensaje no es un pedido de inmueble (saludo, pregunta general)."},
            "negocio": {"type": "string", "enum": ["venta", "arriendo"]},
            "tipos": {"type": "array", "items": {"type": "string", "enum": TIPOS},
                      "description": "Tipos aceptables. 'apto' = apartamento. Vacío si no lo dice."},
            "moneda": {"type": "string", "enum": ["COP", "USD"]},
            "presupuesto_min": {"type": ["integer", "null"], "description": "En unidades completas: 900 millones = 900000000."},
            "presupuesto_max": {"type": ["integer", "null"], "description": "Techo. '1.200 millones' = 1200000000; '1,5 MM' = 1500000000."},
            "habitaciones_min": {"type": ["integer", "null"]},
            "habitaciones_max": {"type": ["integer", "null"], "description": "Solo si pide un máximo explícito."},
            "banos_min": {"type": ["integer", "null"]},
            "parqueaderos_min": {"type": ["integer", "null"]},
            "area_min": {"type": ["number", "null"]},
            "area_max": {"type": ["number", "null"]},
            "piso_min": {"type": ["integer", "null"]},
            "piso_max": {"type": ["integer", "null"]},
            "estrato_min": {"type": ["integer", "null"]},
            "antiguedad_max_anios": {"type": ["integer", "null"]},
            "administracion_max": {"type": ["integer", "null"]},
            "ubicaciones": {
                "type": "array",
                "description": "Barrios, sectores o municipios donde busca, en orden de preferencia.",
                "items": {"type": "object", "properties": {
                    "nombre": {"type": "string"},
                    "municipio": {"type": ["string", "null"], "description": "Municipio al que pertenece si lo sabes."},
                }, "required": ["nombre"]},
            },
            "ubicaciones_excluidas": {"type": "array", "items": {"type": "string"},
                                      "description": "Barrios o sectores que NO quiere."},
            "cerca_de": {"type": "array", "items": {"type": "string"},
                         "description": "Lugares de referencia: colegios, centros comerciales, vías, estaciones."},
            "edificios_referencia": {"type": "array", "items": {"type": "string"},
                                     "description": "Unidades o edificios que le gustan como referencia ('tipo Cibeles')."},
            "obligatorias": {"type": "array", "items": {"type": "string", "enum": CARACTERISTICAS},
                             "description": "Características imprescindibles ('debe tener', 'muy importante', 'indispensable')."},
            "deseables": {"type": "array", "items": {"type": "object", "properties": {
                "caracteristica": {"type": "string", "enum": CARACTERISTICAS},
                "peso": {"type": "integer", "enum": [1, 2, 3]},
            }, "required": ["caracteristica", "peso"]},
                "description": "Lo que suma pero no es imprescindible ('ojalá', 'le gusta'). Peso 3 = muy importante."},
            "estados": {"type": "array", "items": {"type": "string", "enum": ESTADOS},
                        "description": "Estado aceptable si lo pide ('para remodelar', 'para estrenar')."},
            "otras_preferencias": {"type": "array", "items": {"type": "string"},
                                   "description": "Preferencias que no caben en lo anterior, en pocas palabras."},
            "cantidad": {"type": "integer",
                         "description": "Cuántas opciones quiere ver, solo si lo dice ('las 5 mejores' = 5, 'dame 3' = 3)."},
        },
        "required": ["es_busqueda", "negocio", "tipos", "moneda", "ubicaciones", "ubicaciones_excluidas",
                     "cerca_de", "edificios_referencia", "obligatorias", "deseables", "estados",
                     "otras_preferencias"],
    },
}

_SISTEMA_PEDIDO = """Eres el asistente de búsqueda de Fynder, una red de agentes inmobiliarios de \
Medellín, el Valle de Aburrá y el Oriente antioqueño. Te llega el pedido de un agente (a veces \
copiado de un grupo de WhatsApp, con emojis y listas). Conviértelo en un pedido estructurado.

Reglas:
- Dinero en pesos colombianos y en unidades completas: "900 millones" = 900000000, \
"1.200 millones" o "1,2 MM" = 1200000000, "$750'000.000" = 750000000. "Hasta X" o "presupuesto X" \
es presupuesto_max. Si viene en dólares, moneda = USD y el número en dólares.
- "3 habitaciones" o "3 alcobas" es habitaciones_min = 3 (no pongas máximo salvo que lo diga).
- "Más de 100 metros" = area_min 100. "Piso bajo"/"primeros pisos" = piso_max 4. "Piso alto" = piso_min 6.
- Barrios y sectores van en ubicaciones con su municipio si lo sabes (Los Balsos → Medellín; \
Zúñiga → Envigado; Llanogrande → Rionegro; Loma de los Bernal → Medellín). "Desde X hasta Y" son \
dos ubicaciones. "El Poblado" o "Laureles" son sectores válidos. El nombre de una inmobiliaria \
NO es una ubicación.
- "Todo el Poblado excepto Astorga…" → ubicaciones [El Poblado] y ubicaciones_excluidas [Astorga, …].
- "Le gusta tipo Cibeles, Aguas del Bosque" → edificios_referencia.
- "Cerca del colegio Montessori / de Oviedo / del metro" → cerca_de.
- Lo que dice "debe", "indispensable", "muy importante", "OJO" → obligatorias si es una característica \
del vocabulario; "ojalá", "le gusta", "preferible" → deseables.
- "Con parqueadero" = parqueaderos_min 1 (NO es parqueadero_cubierto, salvo que diga "cubierto"). "No primer piso" = piso_min 2.
- "Unidad completa/cerrada" = unidad_cerrada. "Sin ruido" = tranquilo. "Vista a verde/montaña" = vista_verde.
- Si hay un pedido anterior y el mensaje lo ajusta ("más barato", "mejor en Envigado", "con balcón"), \
devuelve el pedido COMPLETO actualizado: conserva lo anterior y cambia solo lo que el mensaje cambia. \
"Más barato" sin cifra: baja el presupuesto_max un 15 %. Si el mensaje es un pedido nuevo y distinto, \
ignora el anterior.
- Si hay un pedido anterior y el mensaje habla de los resultados sin cambiar lo que busca ("son muchas", \
"solo las 5 mejores", "dame menos", "¿por qué esas?"), ES búsqueda (es_busqueda = true): devuelve el \
pedido anterior COMPLETO y, si dice cuántas, ponlo en cantidad. es_busqueda = false es solo para \
saludos o preguntas que no tienen nada que ver con buscar inmuebles."""


def _llamar(modelo: str, mensajes: List[dict]) -> Dict[str, Any]:
    import anthropic
    cliente = anthropic.Anthropic()
    t0 = time.time()
    r = cliente.messages.create(
        model=modelo, max_tokens=1200,
        system=[{"type": "text", "text": _SISTEMA_PEDIDO, "cache_control": {"type": "ephemeral"}}],
        tools=[_HERRAMIENTA], tool_choice={"type": "tool", "name": "pedido"},
        messages=mensajes,
    )
    try:
        from src.core.ai_usage_tracker import get_ai_tracker
        get_ai_tracker().track_anthropic_response(modelo, "search_extraction", "busqueda.interpretar", r, t0)
    except Exception:  # noqa: BLE001 — el registro de uso nunca tumba la búsqueda
        pass
    return next(b for b in r.content if b.type == "tool_use").input


def _validar(p: Dict[str, Any]) -> Dict[str, Any]:
    """Rangos sanos y conversión de moneda. Lo absurdo se descarta en vez de filtrar mal."""
    def num(k, lo, hi):
        v = p.get(k)
        try:
            v = float(v)
        except (TypeError, ValueError):
            p[k] = None
            return
        p[k] = v if lo <= v <= hi else None

    if p.get("moneda") == "USD":
        for k in ("presupuesto_min", "presupuesto_max"):
            if p.get(k):
                p[k] = p[k] * TRM
    for k in ("presupuesto_min", "presupuesto_max", "administracion_max"):
        num(k, 1, 1e12)
    # "900" sin "millones" casi siempre quiere decir millones.
    for k in ("presupuesto_min", "presupuesto_max"):
        if p.get(k) and p[k] < 20_000:
            p[k] *= 1_000_000
        if p.get(k) and p[k] < 20_000_000 and p.get("negocio") != "arriendo":
            p[k] = None
    for k, lo, hi in (("habitaciones_min", 0, 20), ("habitaciones_max", 0, 20), ("banos_min", 0, 20),
                      ("parqueaderos_min", 0, 20), ("area_min", 5, 100000), ("area_max", 5, 100000),
                      ("piso_min", -2, 80), ("piso_max", -2, 80), ("estrato_min", 1, 6),
                      ("antiguedad_max_anios", 0, 100), ("cantidad", 1, 30)):
        num(k, lo, hi)
    if p.get("cantidad"):
        p["cantidad"] = int(p["cantidad"])
    p["tipos"] = [t for t in p.get("tipos") or [] if t in TIPOS]
    p["obligatorias"] = [c for c in p.get("obligatorias") or [] if c in CARACTERISTICAS]
    p["deseables"] = [d for d in p.get("deseables") or []
                      if d.get("caracteristica") in CARACTERISTICAS and d["caracteristica"] not in p["obligatorias"]]
    p["estados"] = [e for e in p.get("estados") or [] if e in ESTADOS]
    p["ubicaciones"] = [u for u in p.get("ubicaciones") or [] if (u.get("nombre") or "").strip()]
    return p


def interpretar(texto: str, previo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Texto del agente (+ pedido anterior) → pedido estructurado y validado."""
    contenido = texto.strip()
    if previo:
        anterior = {k: v for k, v in previo.items() if not k.startswith("_")}
        contenido = (f"PEDIDO ANTERIOR:\n{json.dumps(anterior, ensure_ascii=False)}\n\n"
                     f"MENSAJE NUEVO DEL AGENTE:\n{contenido}")
    mensajes = [{"role": "user", "content": contenido}]
    ultimo_error = None
    for modelo in (MODELO, MODELO_RESPALDO):
        try:
            p = _validar(_llamar(modelo, mensajes))
            p["_modelo"] = modelo
            return p
        except Exception as e:  # noqa: BLE001 — pasamos al modelo de respaldo
            ultimo_error = e
    raise RuntimeError(f"No pude interpretar el pedido: {ultimo_error}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Ubicar
# ─────────────────────────────────────────────────────────────────────────────

_RUIDO = {"el", "la", "los", "las", "de", "del", "sector", "barrio", "urbanizacion", "parte", "zona", "y"}

# Municipios donde hay inventario. Solo estos cuentan como municipio: en los datos
# a veces la "ciudad" es un barrio ("El Poblado").
MUNICIPIOS = [
    "Medellín", "Envigado", "Sabaneta", "Itagüí", "La Estrella", "Bello", "Copacabana", "Girardota",
    "Caldas", "Rionegro", "El Retiro", "La Ceja", "Guarne", "Marinilla", "El Carmen de Viboral",
    "La Unión", "El Santuario", "San Vicente", "Guatapé", "El Peñol", "Santa Fe de Antioquia",
    "San Jerónimo", "Sopetrán", "Barbosa", "Amagá", "Fredonia", "Jardín", "Jericó", "Venecia",
]


def _plano(t: Optional[str]) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9ñ ]+", " ", t).strip()


def _clave(t: Optional[str]) -> str:
    return " ".join(w for w in _plano(t).split() if w not in _RUIDO)


def _km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    dlat = math.radians(b[0] - a[0])
    dlng = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlng / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


class Gazetteer:
    """Barrios y municipios del inventario real, con su centro geográfico."""

    def __init__(self):
        with get_db() as db:
            filas = fetch_all(db.cursor, """
                SELECT COALESCE(f.ciudad, p.ciudad) AS ciudad,
                       COALESCE(f.barrio, p.zona) AS barrio,
                       p.zona, p.latitud AS lat, p.longitud AS lng
                FROM propiedades p LEFT JOIN propiedades_ficha f ON f.propiedad_id = p.id
                WHERE p.activa
            """)
        puntos = defaultdict(list)
        self.municipios: Dict[str, str] = {_clave(m): m for m in MUNICIPIOS}
        self.municipios["itagui"] = "Itagüí"
        for r in filas:
            for nombre in {r["barrio"], r["zona"]}:
                k = _clave(nombre)
                if k and r["lat"] and r["lng"]:
                    puntos[k].append((float(r["lat"]), float(r["lng"])))
        self.centros: Dict[str, Tuple[float, float]] = {}
        for k, ps in puntos.items():
            if len(ps) < 2:
                continue
            c = (median(p[0] for p in ps), median(p[1] for p in ps))
            buenos = [p for p in ps if _km(c, p) <= 4]
            if len(buenos) >= 2:
                self.centros[k] = (median(p[0] for p in buenos), median(p[1] for p in buenos))
        try:
            from src.core.search_config import LANDMARKS_COORDENADAS, SUBBARRIO_A_ZONA_PADRE
            self.lugares = {_clave(k): v for k, v in LANDMARKS_COORDENADAS.items()}
            hijos = defaultdict(set)
            for sub, padre in SUBBARRIO_A_ZONA_PADRE.items():
                hijos[_clave(padre)].add(_clave(sub))
            self.hijos = dict(hijos)
        except Exception:  # noqa: BLE001
            self.lugares, self.hijos = {}, {}
        self.creado = time.time()

    def resolver(self, nombre: str) -> Dict[str, Any]:
        """→ {claves: nombres que cuentan como "en la zona", centro, municipio}"""
        k = _clave(nombre)
        if not k:
            return {}
        if k in self.municipios:
            return {"municipio": self.municipios[k], "claves": {k}, "centro": self.centros.get(k)}
        claves = {k} | self.hijos.get(k, set())
        # "Loma de los Bernal" ↔ "loma bernal"; "San Lucas" dentro de "san lucas poblado"
        for c in self.centros:
            if len(k) >= 5 and (c == k or c.startswith(k + " ") or c.endswith(" " + k) or k.startswith(c + " ")):
                claves.add(c)
        puntos = [self.centros[c] for c in claves if c in self.centros]
        centro = (median(p[0] for p in puntos), median(p[1] for p in puntos)) if puntos else None
        return {"claves": claves, "centro": centro}

    def lugar(self, nombre: str) -> Optional[Tuple[float, float]]:
        k = _clave(nombre)
        if k in self.lugares:
            return self.lugares[k]
        for c, v in self.lugares.items():
            if len(c) >= 5 and (c in k or k in c):
                return v
        return self.resolver(nombre).get("centro")


_GAZ: Optional[Gazetteer] = None
_GAZ_LOCK = threading.Lock()


def gazetteer() -> Gazetteer:
    global _GAZ
    with _GAZ_LOCK:
        if _GAZ is None or time.time() - _GAZ.creado > 3600:
            _GAZ = Gazetteer()
        return _GAZ


# ─────────────────────────────────────────────────────────────────────────────
# 3. Recuperar candidatos
# ─────────────────────────────────────────────────────────────────────────────

_TIPO_ORIGINAL = """
    CASE
      WHEN p.tipo_propiedad ~* 'apartaestudio' THEN 'apartaestudio'
      WHEN p.tipo_propiedad ~* 'campestre|caba' THEN 'casa_campestre'
      WHEN p.tipo_propiedad ~* 'apartamento|departamento|penthouse|d.plex|^ph' THEN 'apartamento'
      WHEN p.tipo_propiedad ~* 'casa' THEN 'casa'
      WHEN p.tipo_propiedad ~* 'finca' THEN 'finca'
      WHEN p.tipo_propiedad ~* 'lote|terreno' THEN 'lote'
      WHEN p.tipo_propiedad ~* 'local' THEN 'local'
      WHEN p.tipo_propiedad ~* 'oficina' THEN 'oficina'
      WHEN p.tipo_propiedad ~* 'consultorio' THEN 'consultorio'
      WHEN p.tipo_propiedad ~* 'bodega' THEN 'bodega'
      WHEN p.tipo_propiedad ~* 'edificio' THEN 'edificio'
      WHEN p.tipo_propiedad ~* 'hotel' THEN 'hotel'
    END"""

# Tipos que se aceptan entre sí (una casa campestre sirve si piden finca, etc.).
_FAMILIA = {
    "apartamento": {"apartamento"}, "apartaestudio": {"apartaestudio", "apartamento"},
    "casa": {"casa"}, "casa_campestre": {"casa_campestre", "finca"}, "finca": {"finca", "casa_campestre"},
    "lote": {"lote"}, "local": {"local"}, "oficina": {"oficina", "consultorio"},
    "consultorio": {"consultorio", "oficina"}, "bodega": {"bodega"}, "edificio": {"edificio"},
    "hotel": {"hotel"}, "otro": set(),
}


def _candidatos(ped: Dict[str, Any], vector: Optional[List[float]],
                ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """`ids`: limita la búsqueda a esos inmuebles (lo usan las alertas de cruce)."""
    cond = ["p.activa", "p.precio IS NOT NULL"]
    params: List[Any] = []
    if ids is not None:
        cond.append("p.id = ANY(%s)")
        params.append(list(ids))
    if ped.get("negocio") == "arriendo":
        cond.append("COALESCE(f.negocio, lower(p.tipo_negocio), 'venta') = 'arriendo'")
    else:
        cond.append("COALESCE(f.negocio, lower(p.tipo_negocio), 'venta') <> 'arriendo'")
    tipos = set()
    for t in ped.get("tipos") or []:
        tipos |= _FAMILIA.get(t, {t})
    if tipos:
        cond.append(f"COALESCE(f.tipo, {_TIPO_ORIGINAL}) = ANY(%s)")
        params.append(sorted(tipos))
    pmax, pmin = ped.get("presupuesto_max"), ped.get("presupuesto_min")
    if pmax:
        cond.append("p.precio <= %s")
        params.append(pmax * 1.15)
        cond.append("p.precio >= %s")
        params.append((pmin * 0.85) if pmin else pmax * 0.40)
    elif pmin:
        cond.append("p.precio >= %s")
        params.append(pmin * 0.85)
    for col, k, holgura in (("COALESCE(p.habitaciones, f.habitaciones)", "habitaciones_min", 1),
                            ("COALESCE(p.banos, f.banos)", "banos_min", 1),
                            ("COALESCE(p.parqueaderos, f.parqueaderos)", "parqueaderos_min", 1)):
        if ped.get(k):
            cond.append(f"({col} IS NULL OR {col} >= %s)")
            params.append(ped[k] - holgura)
    if ped.get("area_min"):
        cond.append("(COALESCE(p.area_construida, f.area_m2) IS NULL OR COALESCE(p.area_construida, f.area_m2) >= %s)")
        params.append(ped["area_min"] * 0.85)

    sim = "NULL::float"
    if vector:
        sim = "1 - (e.embedding <=> %s::vector)"
        params.insert(0, "[" + ",".join(f"{x:.6f}" for x in vector) + "]")

    sql = f"""
        SELECT p.id, p.precio, p.titulo, p.latitud AS lat, p.longitud AS lng, p.zona,
               COALESCE(f.ciudad, p.ciudad) AS ciudad, COALESCE(f.barrio, p.zona) AS barrio,
               COALESCE(f.tipo, {_TIPO_ORIGINAL}) AS tipo,
               COALESCE(p.habitaciones, f.habitaciones) AS habitaciones,
               COALESCE(p.banos, f.banos) AS banos,
               COALESCE(p.parqueaderos, f.parqueaderos) AS parqueaderos,
               COALESCE(p.area_construida, f.area_m2) AS area,
               COALESCE(f.piso, p.piso) AS piso,
               COALESCE(p.estrato, f.estrato) AS estrato,
               COALESCE(p.ano_construccion, f.ano_construccion) AS ano,
               COALESCE(p.administracion, f.administracion) AS administracion,
               f.estado, COALESCE(f.caracteristicas, '{{}}') AS caracteristicas, f.resumen,
               {sim} AS similitud
        FROM propiedades p
        LEFT JOIN propiedades_ficha f ON f.propiedad_id = p.id
        LEFT JOIN property_embeddings e ON e.propiedad_id = p.id
        WHERE {' AND '.join(cond)}
        LIMIT 3000
    """
    with get_db() as db:
        return fetch_all(db.cursor, sql, params)


def _embedding_texto(texto: str) -> Optional[List[float]]:
    """Embedding del pedido tal cual; corre en paralelo con la interpretación."""
    try:
        from src.core.embeddings import get_embeddings_manager
        return get_embeddings_manager().generate_embedding("Inmueble: " + texto[:1200])
    except Exception:  # noqa: BLE001 — sin embedding se busca igual
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Calificar
# ─────────────────────────────────────────────────────────────────────────────

def _millones(v) -> str:
    return f"${v / 1e6:,.0f} M".replace(",", ".")


def _ubicaciones(ped: Dict[str, Any]) -> Dict[str, Any]:
    g = gazetteer()
    zonas, anclas, municipios = [], [], set()
    for u in ped.get("ubicaciones") or []:
        r = g.resolver(u["nombre"])
        if r.get("municipio"):
            municipios.add(_clave(r["municipio"]))
        else:
            zonas.append((u["nombre"], r.get("claves") or {_clave(u["nombre"])}, _clave(u.get("municipio"))))
        if r.get("centro") and not r.get("municipio"):
            anclas.append((u["nombre"], r["centro"]))
    for lugar in (ped.get("cerca_de") or []) + (ped.get("edificios_referencia") or []):
        c = g.lugar(lugar)
        if c:
            anclas.append((lugar, c))
    excluidas = set()
    for x in ped.get("ubicaciones_excluidas") or []:
        excluidas |= g.resolver(x).get("claves") or {_clave(x)}
    return {"zonas": zonas, "anclas": anclas, "municipios": municipios, "excluidas": excluidas}


def _en(claves: set, *textos) -> bool:
    for t in textos:
        k = _clave(t)
        if not k:
            continue
        for c in claves:
            if c and (k == c or f" {c} " in f" {k} "):
                return True
    return False


def _puntuar(p: Dict[str, Any], ped: Dict[str, Any], ub: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cumple, no_cumple = [], []
    nombre_lugar = p.get("barrio") or p.get("ciudad") or "?"

    # Exclusiones: fuera.
    if ub["excluidas"] and _en(ub["excluidas"], p.get("barrio"), p.get("zona"), p.get("titulo")):
        return None

    # Ubicación (0–1)
    s_ub = 1.0
    hay_ub = bool(ub["zonas"] or ub["municipios"] or ub["anclas"])
    if hay_ub:
        s_ub = 0.0
        if ub["zonas"] and any(_en(cl, p.get("barrio"), p.get("zona"), p.get("titulo")) for _, cl, _ in ub["zonas"]):
            s_ub = 1.0
        elif ub["municipios"] and (_clave(p.get("ciudad")) in ub["municipios"]
                                   or _en(ub["municipios"], p.get("barrio"), p.get("zona"))):
            s_ub = 1.0
        if s_ub < 1 and p.get("lat") and ub["anclas"]:
            d = min(_km((float(p["lat"]), float(p["lng"])), c) for _, c in ub["anclas"])
            s_ub = max(s_ub, 0.85 if d <= 0.7 else 0.65 if d <= 1.5 else 0.35 if d <= 2.5 else 0.0)
        if s_ub < 0.45 and ub["zonas"] and any(m and m == _clave(p.get("ciudad")) for _, _, m in ub["zonas"]):
            # Mismo municipio: si no sabemos el barrio puede servir; si es otro barrio, poco.
            sin_barrio = not p.get("barrio") or _clave(p.get("barrio")) == _clave(p.get("ciudad"))
            s_ub = max(s_ub, 0.45 if sin_barrio else 0.25)
        if s_ub >= 1:
            cumple.append(f"en {nombre_lugar}")
        elif s_ub >= 0.6:
            cumple.append(f"cerca: {nombre_lugar}")
        else:
            no_cumple.append(f"zona: {nombre_lugar}")

    # Precio (0–1)
    s_pr = 1.0
    pmax, pmin, precio = ped.get("presupuesto_max"), ped.get("presupuesto_min"), float(p["precio"])
    if pmax:
        if precio <= pmax:
            piso = pmin or pmax * 0.7
            s_pr = 1.0 if precio >= piso else max(0.35, 1 - (piso - precio) / piso * 1.5)
            cumple.append(_millones(precio))
        else:
            exceso = precio / pmax - 1
            s_pr = max(0.0, 0.8 - exceso * 5)
            no_cumple.append(f"{_millones(precio)} ({exceso:.0%} sobre el presupuesto)")
    elif pmin and precio < pmin:
        s_pr = 0.5

    # Tamaño y mínimos (0–1, promedio de lo pedido; dato faltante = 0,6)
    partes = []

    def minimo(valor, req, etq, unidad=""):
        if not req:
            return
        if valor is None:
            partes.append(0.6)
        elif float(valor) >= req:
            partes.append(1.0)
            cumple.append(f"{valor:g}{unidad} {etq}" if isinstance(valor, (int, float)) else f"{valor} {etq}")
        else:
            falta = (req - float(valor)) / max(req, 1)
            partes.append(max(0.0, 0.6 - falta * 2))
            no_cumple.append(f"{float(valor):g}{unidad} {etq} (pide {req:g})")

    minimo(p.get("habitaciones"), ped.get("habitaciones_min"), "hab")
    minimo(p.get("banos"), ped.get("banos_min"), "baños")
    minimo(p.get("parqueaderos"), ped.get("parqueaderos_min"), "parq")
    minimo(float(p["area"]) if p.get("area") else None, ped.get("area_min"), "", " m²")
    if ped.get("habitaciones_max") and p.get("habitaciones") and p["habitaciones"] > ped["habitaciones_max"]:
        partes.append(0.5)
    if ped.get("area_max") and p.get("area") and float(p["area"]) > ped["area_max"] * 1.15:
        partes.append(0.5)
    # Lo que pidió más allá de las cifras de la tarjeta: sí / no / por confirmar (la publicación no lo dice).
    requisitos = []
    if ped.get("piso_min") or ped.get("piso_max"):
        p0, p1 = ped.get("piso_min"), ped.get("piso_max")
        etq = f"piso {int(p0)}+" if p0 and not p1 else f"hasta piso {int(p1)}" if p1 and not p0 else f"piso {int(p0)}–{int(p1)}"
        if p.get("piso") is None:
            requisitos.append({"texto": etq, "estado": "duda"})
        else:
            ok = (not p0 or p["piso"] >= p0) and (not p1 or p["piso"] <= p1)
            requisitos.append({"texto": f"piso {p['piso']:g}" if isinstance(p["piso"], (int, float)) else etq,
                               "estado": "si" if ok else "no"})
    if ped.get("piso_max") and p.get("piso") is not None:
        partes.append(1.0 if p["piso"] <= ped["piso_max"] else 0.3)
    if ped.get("piso_min") and p.get("piso") is not None:
        partes.append(1.0 if p["piso"] >= ped["piso_min"] else 0.4)
    if ped.get("estrato_min") and p.get("estrato"):
        partes.append(1.0 if p["estrato"] >= ped["estrato_min"] else 0.4)
    if ped.get("antiguedad_max_anios") and p.get("ano"):
        partes.append(1.0 if (time.localtime().tm_year - p["ano"]) <= ped["antiguedad_max_anios"] else 0.4)
    if ped.get("administracion_max") and p.get("administracion"):
        partes.append(1.0 if p["administracion"] <= ped["administracion_max"] * 1.05 else 0.4)
    s_tam = sum(partes) / len(partes) if partes else 1.0

    # Tipo: lo pedido exacto vale más que un tipo de la misma familia.
    s_tipo = 1.0
    if ped.get("tipos"):
        s_tipo = 1.0 if p.get("tipo") in ped["tipos"] else 0.75 if p.get("tipo") else 0.6

    # Características
    tiene = set(p.get("caracteristicas") or [])
    factor_oblig = 1.0
    for c in ped.get("obligatorias") or []:
        requisitos.append({"texto": _ETIQUETAS_CARACT.get(c, c), "estado": "si" if c in tiene else "duda"})
        if c in tiene:
            cumple.append(_ETIQUETAS_CARACT.get(c, c))
        else:
            factor_oblig *= 0.7
            no_cumple.append(f"sin {_ETIQUETAS_CARACT.get(c, c)} confirmado")
    des = ped.get("deseables") or []
    s_des = 1.0
    if des:
        total = sum(d["peso"] for d in des)
        logrado = sum(d["peso"] for d in des if d["caracteristica"] in tiene)
        s_des = logrado / total
        for d in des:
            requisitos.append({"texto": _ETIQUETAS_CARACT.get(d["caracteristica"], d["caracteristica"]),
                               "estado": "si" if d["caracteristica"] in tiene else "duda", "deseable": True})
            if d["caracteristica"] in tiene:
                cumple.append(_ETIQUETAS_CARACT.get(d["caracteristica"], d["caracteristica"]))
    if ped.get("estados") and p.get("estado"):
        s_des = (s_des + (1.0 if p["estado"] in ped["estados"] else 0.3)) / 2

    sim = p.get("similitud")
    s_sem = max(0.0, min(1.0, (float(sim) - 0.25) / 0.35)) if sim is not None else 0.5

    pesos = {"ub": 0.32 if hay_ub else 0, "pr": 0.22, "tam": 0.18, "tipo": 0.08, "des": 0.10, "sem": 0.10}
    total = sum(pesos.values())
    score = (pesos["ub"] * s_ub + pesos["pr"] * s_pr + pesos["tam"] * s_tam + pesos["tipo"] * s_tipo
             + pesos["des"] * s_des + pesos["sem"] * s_sem) / total
    # Lo que falla en ubicación o precio pesa más que un promedio: un inmueble
    # perfecto en otra zona no debe ganarle a uno bueno en la zona pedida.
    if hay_ub and s_ub < 0.3:
        score *= 0.55
    if s_pr < 0.3:
        score *= 0.6
    score *= factor_oblig
    return {"id": p["id"], "score": round(score * 100, 1), "cumple": cumple[:6], "no_cumple": no_cumple[:4],
            "requisitos": requisitos, "_p": p}


# ─────────────────────────────────────────────────────────────────────────────
# Reordenar con IA (opcional)
# ─────────────────────────────────────────────────────────────────────────────

_SISTEMA_RERANK = """Eres un agente inmobiliario senior de Medellín. Califica qué tan bien encaja cada \
inmueble con el pedido: 3 = encaja, 2 = buena opción (falla una preferencia), 1 = marginal \
(incumple algo obligatorio pero cerca), 0 = no sirve. Conoce la geografía del Valle de Aburrá y el \
Oriente. No penalices datos que falten salvo que sean críticos. Califica TODOS los ids."""

_HERR_RERANK = {
    "name": "calificar",
    "description": "Calificación de cada candidato.",
    "input_schema": {"type": "object", "properties": {"calificaciones": {"type": "array", "items": {
        "type": "object", "properties": {
            "id": {"type": "integer"}, "grado": {"type": "integer", "enum": [0, 1, 2, 3]},
            "nota": {"type": "string", "description": "Máximo 12 palabras: lo que más pesa a favor o en contra."}},
        "required": ["id", "grado", "nota"]}}}, "required": ["calificaciones"]},
}


def _ficha_corta(p: Dict[str, Any]) -> str:
    datos = [p.get("tipo") or "?", _millones(float(p["precio"])), f"{p.get('barrio') or '?'}, {p.get('ciudad') or '?'}"]
    for k, etq in (("area", "m²"), ("habitaciones", "hab"), ("banos", "baños"), ("parqueaderos", "parq"),
                   ("piso", "piso"), ("estrato", "estrato"), ("ano", "año")):
        if p.get(k) is not None:
            datos.append(f"{float(p[k]):g} {etq}" if k in ("area",) else f"{etq} {p[k]}" if k in ("piso", "estrato", "ano") else f"{p[k]} {etq}")
    if p.get("caracteristicas"):
        datos.append("características: " + ", ".join(p["caracteristicas"][:12]))
    return " · ".join(datos) + (f"\n  {p['resumen']}" if p.get("resumen") else "") + \
        (f"\n  Título: {p['titulo']}" if p.get("titulo") else "")


def reordenar_ia(texto: str, resultados: List[Dict[str, Any]], n: int = 25) -> List[Dict[str, Any]]:
    """Segundo paso: Claude Haiku lee los mejores n y los califica 0–3."""
    import anthropic
    top = resultados[:n]
    if len(top) < 2:
        return resultados
    lista = "\n".join(f"[id {r['id']}] {_ficha_corta(r['_p'])}" for r in top)
    try:
        r = anthropic.Anthropic().messages.create(
            model=MODELO, max_tokens=2500, system=_SISTEMA_RERANK,
            tools=[_HERR_RERANK], tool_choice={"type": "tool", "name": "calificar"},
            messages=[{"role": "user", "content": f"PEDIDO:\n{texto}\n\nCANDIDATOS:\n{lista}"}])
        notas = {c["id"]: c for c in next(b for b in r.content if b.type == "tool_use").input["calificaciones"]}
    except Exception:  # noqa: BLE001 — sin el segundo paso queda el orden del puntaje
        return resultados
    for res in top:
        c = notas.get(res["id"])
        if c:
            res["grado_ia"], res["nota_ia"] = c["grado"], c["nota"]
    top.sort(key=lambda x: (x.get("grado_ia", 1.5), x["score"]), reverse=True)
    return top + resultados[n:]


# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────

def buscar(texto: str, previo: Optional[Dict[str, Any]] = None, limite: int = 10,
           reordenar: Optional[str] = None, pedido: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Busca inmuebles para un pedido en lenguaje natural.

    reordenar: None (solo puntaje), 'ia' (Claude) o 'jev' (TypeSafe, si hay llave).
    pedido: pedido ya estructurado (p. ej. desde el MCP); si viene, no se llama al LLM.
    """
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.time()
    with ThreadPoolExecutor(2) as pool:
        f_vec = pool.submit(_embedding_texto, texto if not previo else
                            texto + " " + " ".join(u["nombre"] for u in previo.get("ubicaciones") or []))
        pool.submit(gazetteer)
        ped = _validar(dict(pedido)) if pedido else interpretar(texto, previo)
        vector = f_vec.result()
    if not pedido and ped.get("cantidad"):  # "solo las 5 mejores"
        limite = ped["cantidad"]
    if not ped.get("es_busqueda", True):
        return {"pedido": ped, "resultados": [], "tipo": "no_es_busqueda", "ms": 0}
    cands = _candidatos(ped, vector)
    ub = _ubicaciones(ped)
    puntuados = [r for r in (_puntuar(p, ped, ub) for p in cands) if r]
    puntuados.sort(key=lambda r: r["score"], reverse=True)
    # El mismo aviso publicado dos veces (mismo título y precio) sale una sola vez.
    vistos, unicos = set(), []
    for r in puntuados:
        huella = ((r["_p"].get("titulo") or "").strip().lower(), r["_p"].get("precio"))
        if huella[0] and huella in vistos:
            continue
        vistos.add(huella)
        unicos.append(r)
    puntuados = unicos
    if reordenar == "ia":
        puntuados = reordenar_ia(texto, puntuados)
    elif reordenar == "jev":
        from src.services.busqueda_jev import reordenar_jev
        puntuados = reordenar_jev(texto, ped, puntuados)
    resultados = []
    for r in puntuados[:limite]:
        p = r.pop("_p")
        r.update({k: p.get(k) for k in ("precio", "tipo", "barrio", "ciudad", "habitaciones", "banos", "area", "titulo")})
        resultados.append(r)
    for r in puntuados[limite:]:
        r.pop("_p", None)
    return {"pedido": ped, "resultados": resultados, "total": len(puntuados),
            "tipo": "v3" + (f"+{reordenar}" if reordenar else ""), "ms": round((time.time() - t0) * 1000)}


# ─────────────────────────────────────────────────────────────────────────────
# Puente con el chat de Findy y el MCP (misma forma que PropertySearchAgent)
# ─────────────────────────────────────────────────────────────────────────────

def activo() -> bool:
    """Interruptor: FYNDER_BUSQUEDA_V3=1 usa este motor; si no, el buscador anterior."""
    return os.getenv("FYNDER_BUSQUEDA_V3", "0").lower() in ("1", "true", "si", "sí")


REORDENAR = os.getenv("FYNDER_BUSQUEDA_REORDENAR", "jev") or None  # 'jev', 'ia' o '' (solo puntaje)

_COLUMNAS = """id, id::text AS slug, codigo_propiedad, fuente, url, titulo, precio, precio_texto,
    tipo_propiedad, estado, ciudad, zona, direccion_completa, area_construida, habitaciones,
    banos, parqueaderos, estrato, piso, ano_construccion, administracion, predial,
    amenidades_internas, amenidades_externas, total_amenidades, asesor, telefono, inmobiliaria,
    imagen_principal, total_imagenes, descripcion, fecha_creacion, fecha_actualizacion, fecha_ultima_validacion"""


def chips(ped: Dict[str, Any]) -> List[Dict[str, str]]:
    """El pedido en frases cortas para la interfaz: [{tipo, texto}]."""
    out: List[Dict[str, str]] = []
    for t in ped.get("tipos") or []:
        out.append({"tipo": "tipo", "texto": t.replace("_", " ").capitalize()})
    for u in ped.get("ubicaciones") or []:
        out.append({"tipo": "zona", "texto": u.get("nombre", "")})
    for x in ped.get("ubicaciones_excluidas") or []:
        out.append({"tipo": "zona", "texto": f"Sin {x}"})
    for x in ped.get("cerca_de") or []:
        out.append({"tipo": "zona", "texto": f"Cerca de {x}"})
    pmin, pmax = ped.get("presupuesto_min"), ped.get("presupuesto_max")
    if pmin and pmax:
        out.append({"tipo": "precio", "texto": f"{_millones(pmin)} a {_millones(pmax)}"})
    elif pmax:
        out.append({"tipo": "precio", "texto": f"Hasta {_millones(pmax)}"})
    elif pmin:
        out.append({"tipo": "precio", "texto": f"Desde {_millones(pmin)}"})
    for k, et in (("habitaciones_min", "hab"), ("banos_min", "baños"), ("parqueaderos_min", "parq.")):
        if ped.get(k):
            out.append({"tipo": "hab", "texto": f"{int(ped[k])}+ {et}"})
    if ped.get("area_min") or ped.get("area_max"):
        a0, a1 = ped.get("area_min"), ped.get("area_max")
        out.append({"tipo": "area", "texto": f"{int(a0)}–{int(a1)} m²" if a0 and a1 else
                    (f"Desde {int(a0)} m²" if a0 else f"Hasta {int(a1)} m²")})
    if ped.get("estrato_min"):
        out.append({"tipo": "otro", "texto": f"Estrato {int(ped['estrato_min'])}+"})
    p0, p1 = ped.get("piso_min"), ped.get("piso_max")
    if p0 or p1:
        out.append({"tipo": "otro", "texto": f"Piso {int(p0)} a {int(p1)}" if p0 and p1 else
                    (f"Piso {int(p0)} o más" if p0 else f"Hasta piso {int(p1)}")})
    for c in ped.get("obligatorias") or []:
        out.append({"tipo": "obligatoria", "texto": _ETIQUETAS_CARACT.get(c, c)})
    for d in ped.get("deseables") or []:
        out.append({"tipo": "deseable", "texto": "Ideal: " + _ETIQUETAS_CARACT.get(d["caracteristica"], d["caracteristica"])})
    for x in ped.get("otras_preferencias") or []:
        out.append({"tipo": "otro", "texto": str(x)})
    return [c for c in out if c["texto"]]


def texto_de_pedido(ped: Dict[str, Any]) -> str:
    """Una frase con el pedido, para el embedding cuando se busca desde un perfil guardado."""
    return ", ".join(c["texto"] for c in chips(ped)) or "inmueble en venta"


def cambios_de_precio(ids: List[int], dias: int = 30) -> Dict[int, Dict[str, Any]]:
    """Último cambio de precio aplicado en los últimos `dias`: {id: {precio_anterior, precio_cambio_at}}."""
    if not ids:
        return {}
    with get_db() as db:
        filas = fetch_all(db.cursor, f"""
            SELECT DISTINCT ON (propiedad_id) propiedad_id, precio_anterior, created_at
            FROM cambios_precio
            WHERE propiedad_id = ANY(%s) AND aplicado AND created_at > NOW() - INTERVAL '{int(dias)} days'
            ORDER BY propiedad_id, created_at DESC
        """, (list(ids),))
    return {f["propiedad_id"]: {"precio_anterior": int(f["precio_anterior"]) if f["precio_anterior"] else None,
                                "precio_cambio_at": f["created_at"].isoformat()} for f in filas}


def criterios_legibles(ped: Dict[str, Any]) -> Dict[str, Any]:
    """El pedido v3 en las claves que ya pinta el frontend (chips de criterios)."""
    c = {
        "ubicaciones": [u["nombre"] for u in ped.get("ubicaciones") or []] or None,
        "tipo_propiedad": ", ".join(ped.get("tipos") or []) or None,
        "precio_min": ped.get("presupuesto_min"), "precio_max": ped.get("presupuesto_max"),
        "habitaciones_min": ped.get("habitaciones_min"), "habitaciones_max": ped.get("habitaciones_max"),
        "banos_min": ped.get("banos_min"), "parqueaderos_min": ped.get("parqueaderos_min"),
        "area_min": ped.get("area_min"), "area_max": ped.get("area_max"),
        "estrato": ped.get("estrato_min"),
        "amenidades_requeridas": [_ETIQUETAS_CARACT.get(x, x) for x in ped.get("obligatorias") or []] or None,
    }
    return {k: v for k, v in c.items() if v not in (None, [], "")}


def buscar_compat(texto: str, previo: Optional[Dict[str, Any]] = None, limite: int = 10) -> Dict[str, Any]:
    """
    `buscar` con la respuesta de `PropertySearchAgent.search`: filas completas de
    `propiedades` + match_score / match_reasons (lo que cumple) y `no_cumple`.
    El pedido estructurado va en criteria['pedido_v3'] para el siguiente turno.
    """
    try:
        r = buscar(texto, previo=previo, limite=limite, reordenar=REORDENAR)
    except Exception as e:  # noqa: BLE001 — la IA no pudo leer el pedido
        print(f"[BUSQUEDA-V3] error: {e}")
        return {"success": False, "error_type": "ai_unavailable", "results": [], "total_found": 0,
                "criteria": {"pedido_v3": previo} if previo else {}}
    ped = r["pedido"]
    if r["tipo"] == "no_es_busqueda" and previo:
        ped = previo  # un mensaje que no es búsqueda no borra lo que el agente ya pidió
    criteria = {**criterios_legibles(ped), "pedido_v3": ped, "chips": [c["texto"] for c in chips(ped)]}
    if r["tipo"] == "no_es_busqueda":
        return {"success": True, "results": [], "total_found": 0, "criteria": criteria,
                "search_type": "no_es_busqueda",
                "mensaje_usuario": "Cuéntame qué busca tu cliente: tipo de inmueble, zona y presupuesto."}
    filas: Dict[Any, Dict[str, Any]] = {}
    ids = [x["id"] for x in r["resultados"]]
    if ids:
        with get_db() as db:
            filas = {f["id"]: f for f in fetch_all(
                db.cursor, f"SELECT {_COLUMNAS} FROM propiedades WHERE id = ANY(%s)", (ids,))}
    resultados = []
    try:
        precios = cambios_de_precio(ids)
    except Exception:  # noqa: BLE001 — sin la migración 052 se busca igual
        precios = {}
    for x in r["resultados"]:
        f = filas.get(x["id"])
        if not f:
            continue
        # Lo que la publicación no trae lo completa la ficha (barrio, habitaciones…).
        f = {**f, "zona": f.get("zona") or x.get("barrio"), "ciudad": f.get("ciudad") or x.get("ciudad"),
             "habitaciones": f.get("habitaciones") or x.get("habitaciones"),
             "banos": f.get("banos") or x.get("banos"),
             "area_construida": f.get("area_construida") or x.get("area")}
        f.update(precios.get(x["id"], {}))
        # Frescura: sin esto la tarjeta dice «Sin verificar» aunque se haya verificado ayer.
        from src.services.property_service import frescura
        # Lo publicado en Fynder no tiene portal que verificar: cuenta su última actualización.
        fecha = f.get("fecha_ultima_validacion") or (f.get("fecha_actualizacion") if f.get("fuente") == "Fynder" else None)
        f["verificada_hace_dias"] = frescura(fecha)["verificada_hace_dias"]
        resultados.append({**f, "match_score": x.get("score_final", x["score"]),
                           "match_reasons": x.get("cumple") or [], "no_cumple": x.get("no_cumple") or [],
                           "requisitos": x.get("requisitos") or []})
    scores = [x["match_score"] for x in resultados]
    return {
        "success": True, "results": resultados, "total_found": len(resultados), "total_candidatos": r["total"],
        "criteria": criteria,
        "search_type": r["tipo"], "elapsed_ms": r["ms"],
        "alignment_info": {"avg_score": round(sum(scores) / len(scores), 1), "best_score": max(scores),
                           "per_result_scores": scores} if scores else None,
        "mensaje_usuario": None if resultados else
            "No encontré inmuebles para ese pedido. Prueba ampliando la zona o el presupuesto.",
    }
