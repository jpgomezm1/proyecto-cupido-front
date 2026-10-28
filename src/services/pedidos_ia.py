"""
Estructura con Claude Haiku los textos libres del mercado:

- `estructurar_pedido(texto)`: un pedido ("Busco apto en Laureles, 3 alcobas,
  hasta 600 millones, NO primer piso") -> criterios del comprador. Versión 2: el
  mismo esquema del buscador v3 (ubicaciones, obligatorias/deseables del vocabulario
  de la ficha) más lo que trae un pedido de grupo: ubicaciones con nivel (barrio,
  sector, corredor), unidades puntuales o de referencia, opciones con «O», cómo paga,
  urgencia, perfil, comisión y si actualiza otro pedido. Llena también las claves de
  la versión 1 (zonas, ciudades, exigencias…) para lo que todavía las lee.
- `ficha_desde_texto(texto)`: la descripción de un inmueble que escribe el
  agente ("apto de 85 m² en Laureles, 3 hab, 520 millones") -> ficha.
- `estructurar_pendientes()`: llena `pedidos.criterios` de los recientes que no
  lo tienen (lo corre el worker y el script de carga inicial).

Se usa tool-use forzado: la salida siempre cumple el esquema. Sin dependencias
de Flask (lo usa también el MCP).
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from src.services.db import get_db, fetch_all

MODELO = os.getenv("FYNDER_MODELO_PEDIDOS", "claude-haiku-4-5")
VERSION = 2

_TIPOS = ["apartamento", "apartaestudio", "casa", "casa campestre", "penthouse", "duplex",
          "lote", "finca", "local", "oficina", "bodega", "consultorio"]

_SCHEMA_PEDIDO = {
    "type": "object",
    "properties": {
        "negocio": {"type": ["string", "null"], "enum": ["venta", "arriendo", None],
                    "description": "venta si compra; arriendo si busca arrendar. null si no se sabe."},
        "tipos": {"type": "array", "items": {"type": "string", "enum": _TIPOS},
                  "description": "Tipos de inmueble que acepta."},
        "zonas": {"type": "array", "items": {"type": "string"},
                  "description": "Barrios/sectores aceptados, con su nombre propio limpio (ej: 'Laureles', "
                                 "'El Poblado', 'Loma de las Brujas', 'San Lucas'). Si dice 'desde A hasta B', "
                                 "incluye A, B y los sectores conocidos entre ellos si los sabes."},
        "ciudades": {"type": "array", "items": {"type": "string"},
                     "description": "Municipios (ej: 'Medellín', 'Envigado', 'Sabaneta', 'Itagüí', 'Rionegro')."},
        "zonas_excluidas": {"type": "array", "items": {"type": "string"}},
        "presupuesto_min": {"type": ["integer", "null"], "description": "En pesos COP enteros."},
        "presupuesto_max": {"type": ["integer", "null"],
                            "description": "En pesos COP enteros. '600 millones' = 600000000; "
                                           "'1.800 hasta 2.200' (en millones) = 1800000000 a 2200000000."},
        "habitaciones_min": {"type": ["integer", "null"]},
        "banos_min": {"type": ["integer", "null"]},
        "parqueaderos_min": {"type": ["integer", "null"]},
        "area_min": {"type": ["number", "null"], "description": "m²"},
        "area_max": {"type": ["number", "null"], "description": "m²"},
        "exigencias": {"type": "array", "items": {"type": "string"},
                       "description": "Requisitos cortos en minúscula (ej: 'balcón', 'piscina', 'estudio', "
                                      "'unidad cerrada', 'vista', 'piso alto', 'ascensor', 'útil')."},
        "excluye": {"type": "array", "items": {"type": "string"},
                    "description": "Lo que NO acepta (ej: 'dúplex', 'primer piso')."},
    },
    "required": ["negocio", "tipos", "zonas", "ciudades", "zonas_excluidas", "presupuesto_min",
                 "presupuesto_max", "habitaciones_min", "banos_min", "parqueaderos_min",
                 "area_min", "area_max", "exigencias", "excluye"],
}

_SCHEMA_FICHA = {
    "type": "object",
    "properties": {
        "tipo": {"type": ["string", "null"], "enum": _TIPOS + [None]},
        "negocio": {"type": ["string", "null"], "enum": ["venta", "arriendo", None]},
        "ciudad": {"type": ["string", "null"]},
        "zona": {"type": ["string", "null"], "description": "Barrio o sector."},
        "precio": {"type": ["integer", "null"], "description": "Pesos COP enteros (520 millones = 520000000)."},
        "habitaciones": {"type": ["integer", "null"]},
        "banos": {"type": ["integer", "null"]},
        "parqueaderos": {"type": ["integer", "null"]},
        "area_m2": {"type": ["number", "null"]},
        "amenidades": {"type": "array", "items": {"type": "string"},
                       "description": "Cortas y en minúscula (balcón, piscina, estudio, vista, unidad cerrada...)."},
    },
    "required": ["tipo", "negocio", "ciudad", "zona", "precio", "habitaciones", "banos",
                 "parqueaderos", "area_m2", "amenidades"],
}

_SISTEMA = ("Eres un asistente inmobiliario de Medellín y el Valle de Aburrá (Colombia). "
            "Extraes datos estructurados de textos de agentes inmobiliarios. No inventes: si un dato "
            "no aparece, usa null o una lista vacía. Los precios en Colombia se dicen en millones.")


def _cliente():
    import anthropic  # perezoso: el MCP no lo importa si no se usa
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _extraer(texto: str, schema: Dict[str, Any], nombre: str, instruccion: str,
             sistema: Optional[str] = None, max_tokens: int = 800) -> Dict[str, Any]:
    # Con `sistema` (la extracción v2, ~5 mil tokens de esquema e instrucciones idénticos en cada pedido) se
    # cachea: la re-extracción de un lote paga esa parte a una décima del precio.
    cache = {"cache_control": {"type": "ephemeral"}} if sistema else {}
    resp = _cliente().messages.create(
        model=MODELO,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": sistema, **cache}] if sistema else _SISTEMA,
        tools=[{"name": nombre, "description": instruccion, "input_schema": schema, **cache}],
        tool_choice={"type": "tool", "name": nombre},
        messages=[{"role": "user", "content": texto[:4000]}],
    )
    for bloque in resp.content:
        if getattr(bloque, "type", None) == "tool_use":
            return dict(bloque.input)
    raise RuntimeError("El modelo no devolvió la estructura")


def estructurar_pedido_v1(texto: str) -> Dict[str, Any]:
    crit = _extraer(texto, _SCHEMA_PEDIDO, "guardar_pedido",
                    "Guarda los criterios del comprador que hizo este pedido.")
    crit["_v"] = 1
    return crit


# ─────────────────────────────────────────────────────────────────────────────
# Versión 2: el esquema del buscador + lo que trae un pedido de grupo
# ─────────────────────────────────────────────────────────────────────────────

def _schema_v2() -> Dict[str, Any]:
    from src.services.ficha_service import CARACTERISTICAS, ESTADOS, TIPOS
    lugar = {"type": "object", "properties": {
        "nombre": {"type": "string", "description": "Nombre propio limpio: 'Laureles', 'Loma de las Brujas', 'Envigado'."},
        "municipio": {"type": ["string", "null"], "description": "Municipio al que pertenece, si lo sabes."},
        "nivel": {"type": "string", "enum": ["region", "municipio", "barrio", "sector", "corredor"],
                  "description": "region (Valle de Aburrá, Oriente antioqueño), municipio (Envigado), barrio "
                                 "(Laureles), sector dentro de un barrio o vía ('Vía Linares', 'zona plana'), "
                                 "corredor ('desde X hasta Y')."},
        "dentro_de": {"type": ["string", "null"],
                      "description": "Para un sector: el barrio o municipio donde queda ('Vía Linares' → 'El Poblado')."},
        "referencia": {"type": ["string", "null"],
                       "description": "Límite o precisión que dio: 'arriba de la Inferior', 'hasta el Farmatodo', "
                                      "'hasta la Loma de los Mesa', 'parte baja'."},
    }, "required": ["nombre", "nivel"]}
    num = {"type": ["number", "null"]}
    ent = {"type": ["integer", "null"]}
    base = {
        "tipos": {"type": "array", "items": {"type": "string", "enum": TIPOS}},
        "ubicaciones": {"type": "array", "items": lugar},
        "presupuesto_min": num, "presupuesto_max": num,
        "habitaciones_min": ent, "banos_min": ent, "parqueaderos_min": ent,
        "area_min": num, "area_max": num,
        "obligatorias": {"type": "array", "items": {"type": "string", "enum": CARACTERISTICAS}},
        "piso_min": ent, "piso_max": ent, "antiguedad_max_anios": ent,
        "excluye": {"type": "array", "items": {"type": "string"}},
    }
    return {"type": "object", "properties": {
        "es_pedido": {"type": "boolean", "description": "false si el texto no es un pedido de inmueble."},
        "negocio": {"type": "string", "enum": ["venta", "arriendo"]},
        **base,
        "ubicaciones_excluidas": {"type": "array", "items": {"type": "string"}},
        "unidades": {"type": "array", "items": {"type": "object", "properties": {
            "nombre": {"type": "string"},
            "tipo": {"type": "string", "enum": ["puntual", "estilo"],
                     "description": "puntual = la quiere EN esa unidad o edificio ('en Urbanity'); estilo = "
                                    "una referencia de cómo la quiere ('tipo Montes', 'como Aguas del Bosque')."},
        }, "required": ["nombre", "tipo"]},
            "description": "Unidades, edificios, conjuntos o urbanizaciones con nombre propio. NUNCA van en ubicaciones."},
        "cerca_de": {"type": "array", "items": {"type": "string"},
                     "description": "Lugares de referencia: colegios, centros comerciales, estaciones, clínicas."},
        "deseables": {"type": "array", "items": {"type": "object", "properties": {
            "caracteristica": {"type": "string", "enum": CARACTERISTICAS},
            "peso": {"type": "integer", "enum": [1, 2, 3]}}, "required": ["caracteristica", "peso"]}},
        "estados": {"type": "array", "items": {"type": "string", "enum": ESTADOS}},
        "estrato_min": ent,
        "otras_preferencias": {"type": "array", "items": {"type": "string"},
                               "description": "Lo que no cabe en lo anterior, en pocas palabras."},
        "opciones": {"type": "array", "items": {"type": "object", "properties": {
            "etiqueta": {"type": "string", "description": "Corta: 'Valle de Aburrá', 'Si es apartamento'."},
            "condicion": {"type": ["string", "null"], "description": "La condición tal como la dijo, en pocas palabras."},
            **base}, "required": ["etiqueta"]},
            "description": "SOLO si el pedido tiene alternativas con condiciones distintas ('si es apto…, si es casa…', "
                           "'en el Valle 2 hab hasta 450, en el Oriente casa hasta 750'). Cada opción repite lo que "
                           "cambia. Una lista de zonas con las mismas condiciones NO son opciones."},
        "pago": {"type": ["string", "null"],
                 "enum": ["contado", "credito", "credito_preaprobado", "leasing", "subsidio", "permuta", "mixto", None]},
        "pago_nota": {"type": ["string", "null"], "description": "'70 % y 30 %', 'recursos propios + crédito'."},
        "urgencia": {"type": ["string", "null"], "enum": ["inmediata", "pronto", None]},
        "perfil": {"type": "array", "items": {"type": "string", "enum": [
            "inversion", "renta_corta", "familia", "adulto_mayor", "extranjero", "mascotas", "primera_vivienda",
            "estudiante", "uso_comercial"]}},
        "comision": {"type": ["string", "null"], "description": "'50/50', 'comparte comisión', 'colega'."},
        "es_actualizacion": {"type": "boolean",
                             "description": "true si dice que actualiza o cambia un pedido anterior."},
    }, "required": ["es_pedido", "negocio", "tipos", "ubicaciones", "ubicaciones_excluidas", "unidades", "cerca_de",
                    "obligatorias", "deseables", "excluye", "estados", "otras_preferencias", "opciones", "perfil",
                    "es_actualizacion"]}


_SISTEMA_V2 = """Eres el asistente de Fynder, una red de agentes inmobiliarios de Medellín, el Valle de Aburrá y \
el Oriente antioqueño. Te llega el pedido de un comprador tal como lo pegó un agente en un grupo de WhatsApp (con \
emojis, firmas y listas). Conviértelo en un pedido estructurado. No inventes: lo que no dice, vacío o null.

Reglas:
- Dinero en pesos y en unidades completas: "900 millones" = 900000000, "1.800" (presupuesto) = 1800000000. En \
arriendo, el canon mensual ("13 millones" = 13000000).
- Ubicaciones: cada lugar con su nivel. "Desde Loma de las Brujas hasta Loma de los Mesa" → dos ubicaciones \
nivel corredor (con referencia). "Balsos arriba de la Inferior" → Los Balsos, nivel barrio, referencia "arriba de \
la Inferior". "Las Palmas hasta el Farmatodo" → Las Palmas con referencia "hasta el Farmatodo" (el Farmatodo NO es \
una ubicación). "Zona plana cerca de Viva Envigado" → Envigado nivel sector, referencia "zona plana", y Viva \
Envigado en cerca_de. "El Poblado" y "Laureles" son barrios/sectores de Medellín.
- Sector dentro de un barrio: "Poblado vía Linares" → Vía Linares, nivel sector, dentro_de "El Poblado". "Valle \
de Aburrá" y "Oriente antioqueño" son nivel region.
- Unidades: SOLO urbanizaciones, edificios, conjuntos o proyectos con NOMBRE PROPIO, y van en unidades, NO en \
ubicaciones. "En Urbanity" → puntual. "Tipo Montes, La Reserva" → estilo. Palabras genéricas como "parcelación", \
"unidad cerrada", "edificio", "conjunto" NO son unidades (son características u otras_preferencias).
- Características: usa el vocabulario SOLO si es exactamente lo mismo; si no, va a otras_preferencias ("moderno", \
"cocina cerrada", "buenos acabados", "lote grande"). No deduzcas características que no dijo. "Indispensable", \
"debe", "requisito", "OJO" o una lista de lo que pide → obligatorias; "ojalá", "preferible", "sería un plus", \
"deseable" → deseables (peso 3 si dice "muy"). "Unidad completa" o "unidad cerrada" = unidad_cerrada. "Útil" = \
cuarto_util. "Parqueadero" = parqueaderos_min 1 (NO es parqueadero_cubierto, salvo que diga "cubierto"). Una \
característica va en obligatorias o en deseables, nunca en las dos. "Piso alto" → piso_min 6; "piso bajo" o "no muy alto" → piso_max 4; \
"no primer piso" → piso_min 2. "Máximo 10 años" → antiguedad_max_anios 10.
- Opciones: solo cuando hay condiciones distintas según la alternativa. Si las hay, lo común va arriba y cada \
opción lleva lo que cambia, INCLUIDAS sus ubicaciones ("si es en el Valle: Envigado, Sabaneta…; si es en el \
Oriente…" → las zonas del Valle van en la opción del Valle, no arriba). "Si es apartamento, máximo 10 años" → \
opción con tipos apartamento y antiguedad_max_anios 10.
- Pago: "de contado", "recursos propios" → contado; "crédito preaprobado" → credito_preaprobado.
- Perfil: SOLO si lo dice explícitamente: "para inversión" → inversion; "rentas cortas" → renta_corta; "señora \
adulta" → adulto_mayor; "es para extranjero" → extranjero; "familia", "niños" → familia. "Unidad familiar" o "3 \
habitaciones" NO dicen el perfil.
- es_pedido = false si no es un pedido (una oferta de inmueble, un saludo, una pregunta)."""


def _etiqueta(c: str) -> str:
    from src.services.busqueda import _ETIQUETAS_CARACT
    return _ETIQUETAS_CARACT.get(c, c.replace("_", " "))


def _compat_v1(p: Dict[str, Any]) -> Dict[str, Any]:
    """Las claves de la versión 1, para lo que todavía las lee (compradores, alertas, barrios)."""
    def lugares(ubs):
        zonas, ciudades = [], []
        for u in ubs or []:
            n = (u.get("nombre") or "").strip()
            if not n:
                continue
            if u.get("nivel") == "region":
                continue
            if u.get("nivel") == "municipio":
                ciudades.append(n)
            else:
                zonas.append(n)
                if u.get("municipio"):
                    ciudades.append(u["municipio"])
        return zonas, ciudades
    zonas, ciudades = lugares(p.get("ubicaciones"))
    tipos = list(p.get("tipos") or [])
    pmax = p.get("presupuesto_max")
    for o in p.get("opciones") or []:          # v1 no tiene opciones: la unión (como antes)
        z, c = lugares(o.get("ubicaciones"))
        zonas += [x for x in z if x not in zonas]
        ciudades += [x for x in c if x not in ciudades]
        tipos += [t for t in o.get("tipos") or [] if t not in tipos]
        if o.get("presupuesto_max") and (not pmax or o["presupuesto_max"] > pmax):
            pmax = o["presupuesto_max"]
    v1 = {
        "negocio": p.get("negocio"), "tipos": tipos, "zonas": zonas,
        "ciudades": list(dict.fromkeys(ciudades)) or [],
        "zonas_excluidas": list(p.get("ubicaciones_excluidas") or []),
        "presupuesto_min": p.get("presupuesto_min"), "presupuesto_max": pmax,
        "habitaciones_min": p.get("habitaciones_min"), "banos_min": p.get("banos_min"),
        "parqueaderos_min": p.get("parqueaderos_min"), "area_min": p.get("area_min"), "area_max": p.get("area_max"),
        "exigencias": [_etiqueta(c) for c in p.get("obligatorias") or []],
        "excluye": list(p.get("excluye") or []),
    }
    for k in ("presupuesto_min", "presupuesto_max"):
        if v1[k] is not None:
            v1[k] = int(v1[k])
    return v1


_PERFIL_PISTAS = {
    "inversion": r"invers", "renta_corta": r"renta|airbnb|alquiler corto", "familia": r"famil|niñ|hij",
    "adulto_mayor": r"adult|mayor|señor|abuel", "extranjero": r"extranjer", "mascotas": r"mascot|perr|gat[oa]",
    "primera_vivienda": r"primera vivienda", "estudiante": r"estudi|universi", "uso_comercial": r"comercial|negocio",
}


def _validar_v2(p: Dict[str, Any], texto: str = "") -> Dict[str, Any]:
    """Lo absurdo se descarta en vez de filtrar mal («17.000.000 millones»), y lo que el modelo deduce sin que el
    pedido lo diga (parqueadero «cubierto», perfil «familia») se quita contra el texto."""
    import re
    t = texto.lower()
    # A veces el modelo devuelve un texto donde va un objeto ("Laureles" en vez de {nombre: "Laureles"}).
    def objetos(lista, clave, extra):
        return [x if isinstance(x, dict) else {clave: str(x), **extra} for x in lista or [] if x]
    for g in [p] + [o for o in p.get("opciones") or [] if isinstance(o, dict)]:
        g["ubicaciones"] = objetos(g.get("ubicaciones"), "nombre", {"nivel": "barrio"})
    p["unidades"] = objetos(p.get("unidades"), "nombre", {"tipo": "estilo"})
    p["deseables"] = objetos(p.get("deseables"), "caracteristica", {"peso": 2})
    p["opciones"] = [o for o in p.get("opciones") or [] if isinstance(o, dict)]
    techo = 2e8 if p.get("negocio") == "arriendo" else 5e10
    for g in [p] + list(p.get("opciones") or []):
        for k in ("presupuesto_min", "presupuesto_max"):
            v = g.get(k)
            if v is not None and not (0 < float(v) <= techo):
                g[k] = None
        if "parqueadero_cubierto" in (g.get("obligatorias") or []) and "cubiert" not in t:
            g["obligatorias"] = [c for c in g["obligatorias"] if c != "parqueadero_cubierto"]
            g["parqueaderos_min"] = g.get("parqueaderos_min") or 1
        oblig = set(g.get("obligatorias") or [])
        if "deseables" in g:
            g["deseables"] = [d for d in g.get("deseables") or [] if d.get("caracteristica") not in oblig]
    if t:
        p["perfil"] = [x for x in p.get("perfil") or [] if re.search(_PERFIL_PISTAS.get(x, x), t)]
    p["unidades"] = [u for u in p.get("unidades") or [] if (u.get("nombre") or "").strip().lower()
                     not in {"parcelación", "parcelacion", "unidad cerrada", "unidad completa", "edificio", "conjunto"}]
    return p


def estructurar_pedido(texto: str) -> Dict[str, Any]:
    """Pedido de grupo → criterios versión 2 (con las claves de la versión 1 para compatibilidad)."""
    p = _validar_v2(_limpiar_ficha(_extraer(texto, _schema_v2(), "guardar_pedido",
                                            "Guarda el pedido del comprador, estructurado.", _SISTEMA_V2, max_tokens=1500)),
                    texto)
    return {**_compat_v1(p), **p, "_v": VERSION}


_VACIOS = {"", "unknown", "<unknown>", "desconocido", "n/a", "na", "null", "none", "-", "?"}


def _limpiar_ficha(f: Dict[str, Any]) -> Dict[str, Any]:
    """El modelo a veces responde «<UNKNOWN>» o NaN en vez de null: eso es null."""
    import math
    out: Dict[str, Any] = {}
    for k, v in f.items():
        if isinstance(v, str) and v.strip().lower() in _VACIOS:
            v = None
        elif isinstance(v, float) and math.isnan(v):
            v = None
        elif isinstance(v, list):
            v = [x for x in v if not (isinstance(x, str) and x.strip().lower() in _VACIOS)]
        out[k] = v
    return out


def ficha_desde_texto(texto: str, previa: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ficha del inmueble que describe el agente. Con `previa`, el mensaje la ajusta
    («¿y si lo bajo a 590?»): se devuelve completa, cambiando solo lo que el mensaje cambia."""
    if previa:
        anterior = {k: previa.get(k) for k in _SCHEMA_FICHA["properties"]}
        texto = (f"FICHA ANTERIOR DEL INMUEBLE:\n{json.dumps(anterior, ensure_ascii=False)}\n\n"
                 f"MENSAJE NUEVO DEL AGENTE:\n{texto}\n\n"
                 "Si el mensaje ajusta el mismo inmueble (precio, área, etc.), devuelve la ficha COMPLETA: "
                 "conserva lo anterior y cambia solo lo que el mensaje cambia. Si describe otro inmueble, "
                 "ignora la anterior.")
    return _limpiar_ficha(_extraer(texto, _SCHEMA_FICHA, "guardar_inmueble",
                                   "Guarda la ficha del inmueble que describe el agente."))


def estructurar_pendientes(dias: int = 120, limit: int = 300, concurrencia: int = 8) -> Dict[str, int]:
    """Estructura los pedidos recientes sin criterios. Devuelve {procesados, errores}."""
    with get_db() as db:
        filas = fetch_all(db.cursor, """
            SELECT id, texto_pedido FROM pedidos
            WHERE criterios IS NULL AND texto_pedido IS NOT NULL AND LENGTH(TRIM(texto_pedido)) > 10
              AND fecha_captura > NOW() - make_interval(days => %s)
            ORDER BY fecha_captura DESC
            LIMIT %s
        """, (dias, limit))
    if not filas:
        return {"procesados": 0, "errores": 0}

    def _uno(f) -> Optional[tuple]:
        try:
            return f["id"], estructurar_pedido(f["texto_pedido"])
        except Exception as e:  # noqa: BLE001 — un pedido malo no frena el lote
            print(f"[PEDIDOS-IA] pedido {f['id']}: {type(e).__name__}: {str(e)[:120]}")
            return None

    with ThreadPoolExecutor(max_workers=concurrencia) as ex:
        resultados: List[Optional[tuple]] = list(ex.map(_uno, filas))

    ok = [r for r in resultados if r]
    if ok:
        with get_db() as db:
            for pid, crit in ok:
                db.cursor.execute(
                    "UPDATE pedidos SET criterios = %s, criterios_at = NOW() WHERE id = %s",
                    (json.dumps(crit, ensure_ascii=False), pid))
            db.conn.commit()
    return {"procesados": len(ok), "errores": len(filas) - len(ok)}
