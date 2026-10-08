"""
Herramientas para que el agente venda más con lo que solo Fynder ve: la oferta
y la demanda de toda la red al mismo tiempo.

  - `radar()`: el resumen diario de oportunidades.
      · bajo_precio: inmuebles recientes por debajo del precio por m² típico de
        su barrio y tipo (sirven al comprador que busca negocio).
      · bajaron: los que bajaron de precio en las últimas semanas.
      · demanda_sin_atender: zonas y tipos con muchos pedidos de compradores y
        poca oferta en su presupuesto (dónde salir a captar).
      · nuevos_con_demanda: lo que entró esta semana donde más se busca.
  - `calidad(property_id, tel10)`: qué tan bien está publicado un inmueble del
    agente y qué mejorar, con el precio frente a su zona.

Solo SQL y estadística: no usa IA, no tiene costo por consulta. El inventario y
las medianas se cachean unos minutos porque cambian despacio.
"""

import threading
import time
from collections import Counter, defaultdict
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from src.services import busqueda
from src.services.db import fetch_all, fetch_one, get_db

_CACHE: Dict[str, Tuple[float, Any]] = {}
_LOCK = threading.Lock()
_TTL = 20 * 60


def _cacheado(clave: str, fn):
    with _LOCK:
        v = _CACHE.get(clave)
        if v and time.time() - v[0] < _TTL:
            return v[1]
    dato = fn()
    with _LOCK:
        _CACHE[clave] = (time.time(), dato)
    return dato


def _inventario() -> List[Dict[str, Any]]:
    def cargar():
        with get_db() as db:
            filas = fetch_all(db.cursor, f"""
                SELECT p.id, p.precio, p.fecha_creacion,
                       COALESCE(f.tipo, {busqueda._TIPO_ORIGINAL}) AS tipo,
                       COALESCE(f.barrio, p.zona) AS barrio, COALESCE(f.ciudad, p.ciudad) AS ciudad,
                       COALESCE(p.area_construida, f.area_m2) AS area
                FROM propiedades p LEFT JOIN propiedades_ficha f ON f.propiedad_id = p.id
                WHERE p.activa AND p.precio > 0
                  AND COALESCE(f.negocio, lower(p.tipo_negocio), 'venta') <> 'arriendo'
            """)
        for f in filas:
            f["clave"] = busqueda._clave(f["barrio"])
            f["precio"] = float(f["precio"])
            f["area"] = float(f["area"]) if f["area"] else None
        return filas
    return _cacheado("inventario", cargar)


def _medianas() -> Dict[Tuple[str, str], Tuple[float, int]]:
    """(barrio, tipo) → (mediana de precio por m², cuántos inmuebles)."""
    def calcular():
        grupos = defaultdict(list)
        for f in _inventario():
            if f["area"] and f["area"] >= 20 and f["clave"] and f["tipo"]:
                grupos[(f["clave"], f["tipo"])].append(f["precio"] / f["area"])
        return {k: (median(v), len(v)) for k, v in grupos.items() if len(v) >= 5}
    return _cacheado("medianas", calcular)


def _bandas(presupuesto: float) -> str:
    for tope, nombre in ((400e6, "hasta $400 M"), (700e6, "$400 a $700 M"), (1000e6, "$700 a $1.000 M"),
                         (1500e6, "$1.000 a $1.500 M"), (2500e6, "$1.500 a $2.500 M")):
        if presupuesto <= tope:
            return nombre
    return "más de $2.500 M"


def _demanda() -> List[Dict[str, Any]]:
    """Pedidos de los últimos 120 días por (barrio, tipo), contra la oferta que les alcanza."""
    def calcular():
        with get_db() as db:
            pedidos = fetch_all(db.cursor, """
                SELECT criterios FROM pedidos
                WHERE criterios IS NOT NULL AND fecha_captura > NOW() - INTERVAL '120 days'
            """)
        grupos: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for p in pedidos:
            c = p["criterios"] or {}
            if (c.get("negocio") or "venta") == "arriendo":
                continue
            tipos = [t for t in (c.get("tipos") or []) if t] or []
            for z in c.get("zonas") or []:
                clave = busqueda._clave(z)
                if not clave:
                    continue
                for t in tipos:
                    g = grupos.setdefault((clave, t), {"nombres": Counter(), "presupuestos": [], "pedidos": 0})
                    g["pedidos"] += 1
                    g["nombres"][z.strip().title()] += 1
                    if c.get("presupuesto_max"):
                        g["presupuestos"].append(float(c["presupuesto_max"]))
        inv = _inventario()
        por_clave = defaultdict(list)
        for f in inv:
            por_clave[(f["clave"], f["tipo"])].append(f["precio"])
        out = []
        for (clave, tipo), g in grupos.items():
            if g["pedidos"] < 4:
                continue
            pres = median(g["presupuestos"]) if g["presupuestos"] else None
            oferta_total = len(por_clave.get((clave, tipo), []))
            oferta = sum(1 for x in por_clave.get((clave, tipo), []) if not pres or x <= pres * 1.1)
            out.append({"zona": g["nombres"].most_common(1)[0][0], "tipo": tipo, "pedidos": g["pedidos"],
                        "oferta": oferta, "oferta_total": oferta_total,
                        "presupuesto_tipico": int(pres) if pres else None,
                        "banda": _bandas(pres) if pres else None,
                        "presion": round(g["pedidos"] / (oferta + 1), 2)})
        return sorted(out, key=lambda x: (x["presion"], x["pedidos"]), reverse=True)
    return _cacheado("demanda", calcular)


def _tipo_humano(t: Optional[str]) -> str:
    return (t or "inmueble").replace("_", " ")


def radar(limite: int = 8) -> Dict[str, Any]:
    from src.services.clientes_service import propiedades_mini
    inv = _inventario()
    med = _medianas()
    reciente = time.time() - 120 * 86400

    bajo = []
    for f in inv:
        m = med.get((f["clave"], f["tipo"]))
        if not m or not f["area"] or f["area"] < 20 or f["precio"] < 100e6:
            continue
        ppm = f["precio"] / f["area"]
        desc = 1 - ppm / m[0]
        creado = f["fecha_creacion"].timestamp() if f["fecha_creacion"] else 0
        if 0.15 <= desc <= 0.35:   # más de 35 % casi siempre es un dato mal cargado (área o precio)
            bajo.append((creado >= reciente, desc, f, m))
    # Primero lo reciente (lo que todavía nadie ha movido), luego el mayor descuento.
    bajo.sort(key=lambda x: (x[0], x[1]), reverse=True)
    bajo = [(d, f, m) for _, d, f, m in bajo[:limite]]

    with get_db() as db:
        bajas = fetch_all(db.cursor, """
            SELECT DISTINCT ON (c.propiedad_id) c.propiedad_id, c.precio_anterior, c.precio_nuevo, c.created_at
            FROM cambios_precio c JOIN propiedades p ON p.id = c.propiedad_id AND p.activa
            WHERE c.aplicado AND c.precio_nuevo < c.precio_anterior AND c.created_at > NOW() - INTERVAL '21 days'
            ORDER BY c.propiedad_id, c.created_at DESC
        """)
    bajas.sort(key=lambda b: 1 - b["precio_nuevo"] / b["precio_anterior"], reverse=True)
    bajas = bajas[:limite]

    demanda = _demanda()
    calientes_claves = {(d["zona"] and busqueda._clave(d["zona"]), d["tipo"]): d for d in demanda[:40]}
    semana = time.time() - 10 * 86400
    nuevos = [f for f in inv if f["fecha_creacion"] and f["fecha_creacion"].timestamp() >= semana
              and (f["clave"], f["tipo"]) in calientes_claves]
    nuevos.sort(key=lambda f: calientes_claves[(f["clave"], f["tipo"])]["pedidos"], reverse=True)
    nuevos = nuevos[:limite]

    minis = propiedades_mini([x[1]["id"] for x in bajo] + [b["propiedad_id"] for b in bajas] + [f["id"] for f in nuevos])
    return {
        "bajo_precio": [{**minis[f["id"]], "descuento_pct": round(d * 100), "precio_m2": round(f["precio"] / f["area"]),
                         "mediana_m2_zona": round(m[0]), "comparables": m[1],
                         "lectura": f"{round(d * 100)} % por debajo del metro típico de {_tipo_humano(f['tipo'])} en {f['barrio']}"}
                        for d, f, m in bajo if f["id"] in minis],
        "bajaron": [{**minis[b["propiedad_id"]], "precio_anterior": int(b["precio_anterior"]),
                     "baja_pct": round((1 - b["precio_nuevo"] / b["precio_anterior"]) * 100, 1),
                     "precio_cambio_at": b["created_at"].isoformat()}
                    for b in bajas if b["propiedad_id"] in minis],
        "demanda_sin_atender": demanda[:limite],
        "nuevos_con_demanda": [{**minis[f["id"]], "pedidos_zona": calientes_claves[(f["clave"], f["tipo"])]["pedidos"],
                                "lectura": f"{calientes_claves[(f['clave'], f['tipo'])]['pedidos']} pedidos buscan "
                                           f"{_tipo_humano(f['tipo'])} en {calientes_claves[(f['clave'], f['tipo'])]['zona']}"}
                               for f in nuevos if f["id"] in minis],
    }


# ── calidad del aviso ──────────────────────────────────────────────────────

def calidad(property_id: int, tel10: str) -> Dict[str, Any]:
    """Puntaje 0-100 de qué tan bien está publicado un inmueble del agente y qué mejorar."""
    from src.services import mis_propiedades_service as mp
    with get_db() as db:
        p = mp._salida(mp._cargar(db.cursor, property_id, tel10))
        ficha = fetch_one(db.cursor, "SELECT tipo, barrio FROM propiedades_ficha WHERE propiedad_id = %s", (property_id,))
        validada = fetch_one(db.cursor, "SELECT fecha_ultima_validacion FROM propiedades WHERE id = %s", (property_id,))

    checks: List[Dict[str, Any]] = []

    def chequeo(clave, peso, ok, texto_ok, texto_mal, accion=None):
        checks.append({"clave": clave, "peso": peso, "ok": bool(ok), "texto": texto_ok if ok else texto_mal,
                       "accion": None if ok else accion})

    fotos = p["fotos"] or []
    chequeo("fotos", 25, len(fotos) >= 8, f"{len(fotos)} fotos: suficientes.",
            f"Tiene {len(fotos)} {'foto' if len(fotos) == 1 else 'fotos'}; los avisos con 8 o más reciben más interés.",
            "agregar_fotos")
    titulo = (p["titulo"] or "").strip()
    chequeo("titulo", 10, 25 <= len(titulo) <= 90 and not titulo.isupper(), "Título claro y de buen largo.",
            "El título es muy corto, muy largo o está todo en mayúsculas.", "mejorar_titulo")
    desc = (p["descripcion"] or "").strip()
    chequeo("descripcion", 20, len(desc) >= 350, "Descripción completa.",
            f"La descripción tiene {len(desc)} caracteres; una buena cuenta la distribución, el edificio y la zona.",
            "mejorar_descripcion")
    faltan = [et for k, et in (("area_construida", "área"), ("habitaciones", "habitaciones"), ("banos", "baños"),
                               ("parqueaderos", "parqueaderos"), ("estrato", "estrato"), ("administracion", "administración"))
              if not p.get(k)]
    chequeo("datos", 15, not faltan, "Datos completos.", "Faltan datos: " + ", ".join(faltan) + ".", "completar_datos")
    amen = (p["amenidades_internas"] or []) + (p["amenidades_externas"] or [])
    chequeo("amenidades", 5, len(amen) >= 4, "Características bien listadas.",
            "Lista las características (balcón, ascensor, piscina…): son filtros que usan los compradores.",
            "completar_datos")

    precio_zona = None
    tipo = (ficha or {}).get("tipo")
    barrio = (ficha or {}).get("barrio") or p.get("zona")
    m = _medianas().get((busqueda._clave(barrio), tipo)) if tipo and barrio else None
    if m and p.get("precio") and p.get("area_construida"):
        ppm = p["precio"] / p["area_construida"]
        dif = ppm / m[0] - 1
        precio_zona = {"precio_m2": round(ppm), "mediana_m2_zona": round(m[0]), "comparables": m[1],
                       "diferencia_pct": round(dif * 100, 1), "zona": barrio}
        chequeo("precio", 20, dif <= 0.15,
                "Precio en línea con su zona." if dif >= -0.15 else "Precio por debajo de su zona: es un buen argumento de venta.",
                f"Está {round(dif * 100)} % por encima del metro típico en {barrio}; puede tardar en moverse.",
                "revisar_precio")
    else:
        chequeo("precio", 20, True, "Sin suficientes comparables en su zona para evaluar el precio.", "")

    fv = (validada or {}).get("fecha_ultima_validacion")
    chequeo("vigente", 5, bool(fv) and (time.time() - fv.timestamp()) < 10 * 86400,
            "Verificado como publicado esta semana.", "No se ha verificado recientemente que siga publicado.", None)

    total = sum(c["peso"] for c in checks)
    puntaje = round(100 * sum(c["peso"] for c in checks if c["ok"]) / total) if total else 0
    nivel = "excelente" if puntaje >= 85 else "bueno" if puntaje >= 65 else "por_mejorar"
    return {"propiedad_id": property_id, "puntaje": puntaje, "nivel": nivel, "checks": checks,
            "precio_vs_zona": precio_zona}
