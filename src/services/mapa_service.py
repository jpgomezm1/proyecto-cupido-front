"""
Mapa de mercado para el agente: zonas, oferta, demanda y precios sobre el mapa.

Cómo se arma (los datos reales son desordenados):
  - Muchos inmuebles traen coordenadas pero no el barrio, y los pedidos traen el
    barrio escrito pero no coordenadas. Por eso las ZONAS se construyen con los
    inmuebles que sí tienen nombre de zona: su centro es la mediana de sus
    coordenadas (descartando puntos a más de 3 km, que suelen ser errores de
    geocodificación). Luego, los inmuebles sin nombre se asignan a la zona más
    cercana (≤ 1,5 km) para que las estadísticas usen todo el inventario.
  - La FORMA de cada zona es la envolvente convexa de sus inmuebles, inflada
    unos metros (o un hexágono si tiene muy pocos puntos).
  - La DEMANDA son los pedidos de los últimos 120 días con criterios
    estructurados: cada zona pedida se cruza por nombre normalizado (y alias).
  - La TEMPERATURA compara demanda contra oferta (pedidos por cada inmueble) y
    se reparte en tercios entre las zonas: caliente, tibia, fría.
  - Los HEXÁGONOS (~400 m) agregan el inventario en una malla regular; la
    demanda de cada zona se reparte entre sus hexágonos según su inventario.
  - Un ÁREA dibujada por el agente se analiza igual que una zona: inventario
    dentro del polígono y la demanda de las zonas que caen en él.

Nunca devuelve contactos ni links del portal de origen (lo que Fynder cobra):
solo datos del inmueble y, para pedidos, los criterios y si se pueden abrir con
una llave. Todo lo agregado se cachea 10 minutos en memoria.
"""

import hashlib
import json
import math
import re
import statistics
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.services.db import get_db, fetch_all, fetch_one

# Valle de Aburrá + Oriente cercano (donde está casi todo el inventario).
BBOX_REGION = (5.95, -75.75, 6.45, -75.30)  # sur, oeste, norte, este
DIAS_DEMANDA = 120
MIN_INMUEBLES_ZONA = 4
RADIO_OUTLIER_KM = 3.0
RADIO_ASIGNACION_KM = 1.5
RADIO_FORMA_KM = 2.0
BUFFER_FORMA_M = 140
HEX_M = 420  # radio del hexágono (centro → vértice)
TTL_CACHE = 600
MAX_VERTICES_AREA = 200

_ALIAS = {
    "poblado": "el poblado", "alto de las palmas": "las palmas", "alto de palmas": "las palmas",
    "palmas": "las palmas", "via las palmas": "las palmas", "llano grande": "llanogrande",
    "laureles estadio": "laureles", "estadio": "estadio", "envigado centro": "envigado",
    "sabaneta centro": "sabaneta", "medellin": None, "antioquia": None, "valle de aburra": None,
}

_cache: Dict[str, Any] = {"t": 0.0, "datos": None}
_lock = threading.Lock()


class MapaError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _norm(texto: Optional[str]) -> Optional[str]:
    if not texto:
        return None
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t or len(t) < 3:
        return None
    if t in _ALIAS:
        return _ALIAS[t]
    return t


def _km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _mediana(xs: Iterable[Optional[float]]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return float(statistics.median(xs)) if xs else None


def _pm2_valido(pm2: Any) -> Optional[float]:
    try:
        v = float(pm2)
    except (TypeError, ValueError):
        return None
    return v if 1_000_000 <= v <= 40_000_000 else None


def _dias(fecha: Any) -> Optional[int]:
    if not fecha:
        return None
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - fecha).days)


# Proyección local en metros alrededor de Medellín (suficiente para el valle).
_LAT0 = 6.22
_MX = 111_320 * math.cos(math.radians(_LAT0))
_MY = 110_574


def _a_m(lng: float, lat: float) -> Tuple[float, float]:
    return lng * _MX, lat * _MY


def _a_geo(x: float, y: float) -> List[float]:
    return [round(x / _MX, 6), round(y / _MY, 6)]


def _envolvente(puntos: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Envolvente convexa (monotone chain) en metros."""
    pts = sorted(set(puntos))
    if len(pts) <= 2:
        return pts

    def cruz(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    abajo, arriba = [], []
    for p in pts:
        while len(abajo) >= 2 and cruz(abajo[-2], abajo[-1], p) <= 0:
            abajo.pop()
        abajo.append(p)
    for p in reversed(pts):
        while len(arriba) >= 2 and cruz(arriba[-2], arriba[-1], p) <= 0:
            arriba.pop()
        arriba.append(p)
    return abajo[:-1] + arriba[:-1]


def _hexagono_m(cx: float, cy: float, r: float) -> List[Tuple[float, float]]:
    return [(cx + r * math.cos(math.radians(30 + 60 * i)), cy + r * math.sin(math.radians(30 + 60 * i))) for i in range(6)]


def _forma_zona(lat: float, lng: float, puntos: List[Tuple[float, float]]) -> List[List[float]]:
    """Polígono (GeoJSON, cerrado) de la zona: envolvente inflada o hexágono."""
    cx, cy = _a_m(lng, lat)
    pm = [_a_m(x, y) for x, y in puntos if _km((lat, lng), (y, x)) <= RADIO_FORMA_KM]
    hull = _envolvente(pm)
    if len(hull) < 3:
        anillo = _hexagono_m(cx, cy, 380)
    else:
        anillo = []
        for x, y in hull:
            dx, dy = x - cx, y - cy
            d = math.hypot(dx, dy) or 1.0
            anillo.append((x + dx / d * BUFFER_FORMA_M, y + dy / d * BUFFER_FORMA_M))
    coords = [_a_geo(x, y) for x, y in anillo]
    return coords + [coords[0]]


def _dentro(lng: float, lat: float, anillo: List[List[float]]) -> bool:
    """Punto en polígono (ray casting) con coordenadas [lng, lat]."""
    dentro = False
    j = len(anillo) - 1
    for i in range(len(anillo)):
        xi, yi = anillo[i]
        xj, yj = anillo[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            dentro = not dentro
        j = i
    return dentro


def _hex_de(lng: float, lat: float) -> Tuple[int, int]:
    """Celda axial (q, r) del hexágono puntiagudo de radio HEX_M que contiene el punto."""
    x, y = _a_m(lng, lat)
    q = (math.sqrt(3) / 3 * x - y / 3) / HEX_M
    r = (2 / 3 * y) / HEX_M
    # redondeo cúbico
    cx, cz = q, r
    cy = -cx - cz
    rx, ry, rz = round(cx), round(cy), round(cz)
    dx, dy, dz = abs(rx - cx), abs(ry - cy), abs(rz - cz)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy > dz:
        ry = -rx - rz
    else:
        rz = -rx - ry
    return int(rx), int(rz)


def _hex_poligono(q: int, r: int) -> List[List[float]]:
    cx = HEX_M * math.sqrt(3) * (q + r / 2)
    cy = HEX_M * 1.5 * r
    coords = [_a_geo(x, y) for x, y in _hexagono_m(cx, cy, HEX_M * 0.985)]
    return coords + [coords[0]]


# ---------------------------------------------------------------------------
# Construcción (cacheada)
# ---------------------------------------------------------------------------

_SQL_INMUEBLES = """
    SELECT id, zona, latitud::float AS lat, longitud::float AS lng, precio, precio_m2,
           area_construida, habitaciones, tipo_propiedad, fecha_creacion
    FROM propiedades
    WHERE activa AND COALESCE(tipo_negocio, 'Venta') ILIKE 'venta'
      AND latitud BETWEEN %s AND %s AND longitud BETWEEN %s AND %s
"""


def _construir() -> Dict[str, Any]:
    s, w, n, e = BBOX_REGION
    with get_db() as db:
        cur = db.cursor
        inmuebles = fetch_all(cur, _SQL_INMUEBLES, (s, n, w, e))
        pedidos = fetch_all(cur, f"""
            SELECT id, criterios, fecha_captura,
                   RIGHT(REGEXP_REPLACE(COALESCE(agente_telefono, ''), '[^0-9]', '', 'g'), 10) AS tel10
            FROM pedidos
            WHERE criterios IS NOT NULL AND fecha_captura > NOW() - INTERVAL '{DIAS_DEMANDA} days'
            ORDER BY fecha_captura DESC
        """)

    # 1. Centros de zona con los inmuebles que traen nombre
    por_zona: Dict[str, List[dict]] = defaultdict(list)
    nombres: Dict[str, Counter] = defaultdict(Counter)
    for p in inmuebles:
        k = _norm(p.get("zona"))
        if k:
            por_zona[k].append(p)
            nombres[k][str(p["zona"]).strip().title()] += 1

    zonas: Dict[str, Dict[str, Any]] = {}
    for k, ps in por_zona.items():
        if len(ps) < MIN_INMUEBLES_ZONA:
            continue
        c = (_mediana(p["lat"] for p in ps), _mediana(p["lng"] for p in ps))
        buenos = [p for p in ps if _km(c, (p["lat"], p["lng"])) <= RADIO_OUTLIER_KM]
        if len(buenos) < MIN_INMUEBLES_ZONA:
            continue
        c = (_mediana(p["lat"] for p in buenos), _mediana(p["lng"] for p in buenos))
        zonas[k] = {"id": k, "nombre": nombres[k].most_common(1)[0][0], "lat": c[0], "lng": c[1], "_inm": []}

    # 2. Todo el inventario con coordenadas cae en su zona (o en la más cercana)
    centros = [(k, (z["lat"], z["lng"])) for k, z in zonas.items()]
    for p in inmuebles:
        k = _norm(p.get("zona"))
        if k not in zonas:
            cerca = min(((kk, _km(cc, (p["lat"], p["lng"]))) for kk, cc in centros), key=lambda x: x[1], default=(None, 99))
            k = cerca[0] if cerca[1] <= RADIO_ASIGNACION_KM else None
        p["_zona"] = k
        if k:
            zonas[k]["_inm"].append(p)

    # 3. Demanda: pedidos que nombran la zona
    demanda: Dict[str, List[dict]] = defaultdict(list)
    for ped in pedidos:
        crit = ped.get("criterios") or {}
        vistos: List[str] = []
        for z in crit.get("zonas") or []:
            k = _norm(z)
            if not k:
                continue
            if k not in zonas:  # "Loma de los González" → contiene/está contenida en una zona conocida
                k = next((kk for kk in zonas if kk in k or k in kk), None)
            if k and k not in vistos:
                vistos.append(k)
                demanda[k].append(ped)
        ped["_zonas"] = vistos

    # 4. Estadísticas y forma por zona
    for k, z in zonas.items():
        inm = z["_inm"]
        z.update(_estadisticas(inm, demanda.get(k, [])))
        z["poligono"] = _forma_zona(z["lat"], z["lng"], [(p["lng"], p["lat"]) for p in inm])

    # 5. Temperatura por tercios del ratio demanda/oferta (solo zonas con algo de demanda)
    con_demanda = sorted(z["ratio"] for z in zonas.values() if z["pedidos"] > 0)
    t1 = con_demanda[len(con_demanda) // 3] if con_demanda else 0
    t2 = con_demanda[(2 * len(con_demanda)) // 3] if con_demanda else 0
    for z in zonas.values():
        z["temperatura"] = _temperatura(z["pedidos"], z["ratio"], t1, t2)

    # 6. Precio por m² de referencia de cada inmueble (mediana de su zona) y malla de hexágonos
    pm2_zona = {k: z["precio_m2"] for k, z in zonas.items()}
    celdas: Dict[Tuple[int, int], Dict[str, Any]] = defaultdict(lambda: {"inm": [], "zonas": Counter()})
    puntos = []
    for p in inmuebles:
        pm2 = _pm2_valido(p.get("precio_m2"))
        ref = pm2_zona.get(p.get("_zona"))
        vs = round(pm2 / ref - 1, 3) if pm2 and ref else None
        puntos.append({"i": p["id"], "x": round(p["lng"], 6), "y": round(p["lat"], 6),
                       "p": float(p["precio"]) if p.get("precio") else None, "m": pm2, "v": vs,
                       "t": (p.get("tipo_propiedad") or "").strip().title() or None, "h": p.get("habitaciones"),
                       "z": p.get("_zona")})
        celda = celdas[_hex_de(p["lng"], p["lat"])]
        celda["inm"].append(p)
        if p.get("_zona"):
            celda["zonas"][p["_zona"]] += 1

    hexagonos = []
    for (q, r), c in celdas.items():
        dem = sum(zonas[k]["pedidos"] * nk / max(1, zonas[k]["inmuebles"]) for k, nk in c["zonas"].items())
        hexagonos.append({"id": f"{q}:{r}", "poligono": _hex_poligono(q, r), "inmuebles": len(c["inm"]),
                          "precio_m2": _mediana(_pm2_valido(p.get("precio_m2")) for p in c["inm"]),
                          "demanda": round(dem, 1), "ratio": round(dem / max(1, len(c["inm"])), 3)})

    for z in zonas.values():
        z.pop("_inm")
    lista = sorted(zonas.values(), key=lambda z: -(z["inmuebles"] + z["pedidos"] * 3))
    return {"zonas": lista, "por_id": {z["id"]: z for z in lista}, "puntos": puntos,
            "puntos_por_id": {pt["i"]: pt for pt in puntos}, "hexagonos": hexagonos,
            "pedidos": pedidos, "umbral": (t1, t2),
            "totales": {"inmuebles": len(inmuebles), "pedidos": len(pedidos), "zonas": len(lista)},
            "generado": datetime.now(timezone.utc).isoformat()}


def _temperatura(pedidos: int, ratio: float, t1: float, t2: float) -> str:
    if pedidos == 0 or ratio < t1:
        return "fria"
    return "caliente" if ratio >= t2 else "tibia"


def _estadisticas(inm: List[dict], peds: List[dict]) -> Dict[str, Any]:
    pm2 = [v for v in (_pm2_valido(p.get("precio_m2")) for p in inm) if v]
    presup = [float((p["criterios"] or {}).get("presupuesto_max")) for p in peds
              if (p["criterios"] or {}).get("presupuesto_max")]
    tipos = Counter(p["tipo_propiedad"].strip().title() for p in inm if (p.get("tipo_propiedad") or "").strip())
    tipos_buscados = Counter(t.title() for p in peds for t in ((p["criterios"] or {}).get("tipos") or []))
    return {
        "inmuebles": len(inm),
        "pedidos": len(peds),
        "precio_m2": _mediana(pm2),
        "precio_mediana": _mediana(float(p["precio"]) for p in inm if p.get("precio")),
        "presupuesto_mediana": _mediana(presup),
        "dias_mercado": _mediana(_dias(p.get("fecha_creacion")) for p in inm),
        "tipos": dict(tipos.most_common(4)),
        "tipos_buscados": dict(tipos_buscados.most_common(4)),
        "ratio": round(len(peds) / max(1, len(inm)), 3),
    }


def _datos() -> Dict[str, Any]:
    with _lock:
        if _cache["datos"] is None or time.time() - _cache["t"] > TTL_CACHE:
            _cache["datos"] = _construir()
            _cache["t"] = time.time()
        return _cache["datos"]


# ---------------------------------------------------------------------------
# Capas para el mapa
# ---------------------------------------------------------------------------

def capas() -> Dict[str, Any]:
    """Todo lo agregado de una vez: zonas (con forma), hexágonos y puntos del inventario."""
    d = _datos()
    return {"zonas": d["zonas"], "hexagonos": d["hexagonos"], "puntos": d["puntos"],
            "totales": d["totales"], "generado": d["generado"]}


def zonas() -> Dict[str, Any]:
    d = _datos()
    return {"zonas": d["zonas"], "totales": d["totales"], "generado": d["generado"]}


# ---------------------------------------------------------------------------
# Análisis de una zona o de un área dibujada
# ---------------------------------------------------------------------------

def _tarjetas(ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not ids:
        return {}
    with get_db() as db:
        filas = fetch_all(db.cursor, """
            SELECT id, titulo, zona, latitud::float AS lat, longitud::float AS lng, precio, precio_m2,
                   area_construida, habitaciones, banos, tipo_propiedad, imagen_principal, fecha_creacion
            FROM propiedades WHERE id = ANY(%s)
        """, (ids,))
    d = _datos()
    salida = {}
    for p in filas:
        pt = d["puntos_por_id"].get(p["id"]) or {}
        salida[p["id"]] = {
            "id": p["id"], "slug": str(p["id"]), "lat": p["lat"], "lng": p["lng"],
            "titulo": (p.get("titulo") or "").strip()[:90] or None,
            "tipo": (p.get("tipo_propiedad") or "").strip().title() or None,
            "precio": float(p["precio"]) if p.get("precio") else None,
            "precio_m2": _pm2_valido(p.get("precio_m2")),
            "area": float(p["area_construida"]) if p.get("area_construida") else None,
            "habitaciones": p.get("habitaciones"), "banos": p.get("banos"),
            "imagen": p.get("imagen_principal"), "zona": (p.get("zona") or "").strip().title() or None,
            "dias": _dias(p.get("fecha_creacion")), "vs_zona": pt.get("v"),
        }
    return salida


def _resumen_pedido(p: Dict[str, Any], verificados: set, abiertos: set) -> Dict[str, Any]:
    # Solo criterios estructurados: el texto libre puede traer el nombre o la firma de quien pidió
    # (eso se obtiene con una llave), así que no se muestra.
    c = p.get("criterios") or {}
    return {
        "id": p["id"], "fecha": p["fecha_captura"].isoformat() if p.get("fecha_captura") else None,
        "tipos": c.get("tipos") or [], "zonas": (c.get("zonas") or [])[:4],
        "presupuesto_max": c.get("presupuesto_max"), "presupuesto_min": c.get("presupuesto_min"),
        "habitaciones_min": c.get("habitaciones_min"), "area_min": c.get("area_min"),
        "exigencias": (c.get("exigencias") or [])[:4],
        "desbloqueable": p.get("tel10") in verificados, "abierto": p["id"] in abiertos,
    }


def _analizar(puntos: List[Dict[str, Any]], pedidos: List[Dict[str, Any]], user_id: Optional[int]) -> Dict[str, Any]:
    """Bloques de detalle comunes a zonas y áreas, a partir de puntos del caché."""
    pm2_local = _mediana(pt["m"] for pt in puntos)
    # Oportunidades: m² ≥ 8% por debajo de su zona (o del área, si no tiene zona)
    def vs(pt):
        if pt.get("v") is not None:
            return pt["v"]
        return round(pt["m"] / pm2_local - 1, 3) if pt.get("m") and pm2_local else None
    oport_ids = [pt["i"] for pt in sorted((pt for pt in puntos if (vs(pt) or 0) <= -0.08), key=vs)[:8]]
    precios = sorted(pt["p"] for pt in puntos if pt.get("p"))
    histograma = []
    if len(precios) >= 4:
        lo, hi = precios[int(len(precios) * 0.05)], precios[max(0, int(len(precios) * 0.95) - 1)]
        paso = max(1.0, (hi - lo) / 6)
        for i in range(6):
            a, b = lo + i * paso, lo + (i + 1) * paso
            histograma.append({"desde": a, "hasta": b, "n": sum(1 for x in precios if a <= x < b or (i == 5 and x == b))})

    with get_db() as db:
        cur = db.cursor
        rec = fetch_all(cur, "SELECT id FROM propiedades WHERE id = ANY(%s) ORDER BY fecha_creacion DESC NULLS LAST LIMIT 8",
                        ([pt["i"] for pt in puntos][:3000],)) if puntos else []
        verificados = {r["tel10"] for r in fetch_all(cur, """
            SELECT RIGHT(REGEXP_REPLACE(COALESCE(telefono, ''), '[^0-9]', '', 'g'), 10) AS tel10
            FROM chat_users WHERE activo AND telefono_verificado AND terminos_aceptados_at IS NOT NULL
        """)}
        abiertos = set()
        if user_id:
            abiertos = {r["ref_id"] for r in fetch_all(cur, """
                SELECT ref_id FROM desbloqueos WHERE user_id = %s AND tipo = 'pedido' AND estado = 'vigente'
            """, (user_id,))}
    rec_ids = [r["id"] for r in rec]
    tarjetas = _tarjetas(list(dict.fromkeys(oport_ids + rec_ids)))
    return {
        "oportunidades": [tarjetas[i] for i in oport_ids if i in tarjetas],
        "recientes": [tarjetas[i] for i in rec_ids if i in tarjetas],
        "histograma": histograma,
        "pedidos_lista": [_resumen_pedido(p, verificados, abiertos) for p in pedidos[:20]],
    }


def zona_detalle(zona_id: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    d = _datos()
    z = d["por_id"].get(zona_id)
    if not z:
        return None
    puntos = [pt for pt in d["puntos"] if pt.get("z") == zona_id]
    pedidos = [p for p in d["pedidos"] if zona_id in (p.get("_zonas") or [])]
    return {**z, "tipo": "zona", **_analizar(puntos, pedidos, user_id)}


def _validar_poligono(poligono: Any) -> List[List[float]]:
    if not isinstance(poligono, list) or not (3 <= len(poligono) <= MAX_VERTICES_AREA):
        raise MapaError("invalido", "El área necesita entre 3 y 200 puntos.")
    anillo = []
    for v in poligono:
        try:
            lng, lat = float(v[0]), float(v[1])
        except (TypeError, ValueError, IndexError):
            raise MapaError("invalido", "Coordenadas inválidas.")
        if not (-80 <= lng <= -66 and -5 <= lat <= 14):
            raise MapaError("invalido", "El área está fuera de Colombia.")
        anillo.append([lng, lat])
    if anillo[0] != anillo[-1]:
        anillo.append(anillo[0])
    return anillo


def area_detalle(poligono: Any, user_id: Optional[int] = None, nombre: Optional[str] = None) -> Dict[str, Any]:
    anillo = _validar_poligono(poligono)
    d = _datos()
    xs, ys = [v[0] for v in anillo], [v[1] for v in anillo]
    caja = (min(xs), min(ys), max(xs), max(ys))
    puntos = [pt for pt in d["puntos"] if caja[0] <= pt["x"] <= caja[2] and caja[1] <= pt["y"] <= caja[3]
              and _dentro(pt["x"], pt["y"], anillo)]
    # Zonas del área: su centro cae dentro, o ≥ 30% de su inventario está dentro.
    por_zona = Counter(pt.get("z") for pt in puntos if pt.get("z"))
    zonas_area = [z for z in d["zonas"]
                  if _dentro(z["lng"], z["lat"], anillo) or (z["inmuebles"] and por_zona.get(z["id"], 0) / z["inmuebles"] >= 0.3)]
    ids_zona = {z["id"] for z in zonas_area}
    pedidos = [p for p in d["pedidos"] if ids_zona & set(p.get("_zonas") or [])]
    # Las estadísticas usan los inmuebles completos del caché (tipo, precio, fecha)
    ids = {pt["i"] for pt in puntos}
    with get_db() as db:
        inm = fetch_all(db.cursor, """
            SELECT id, precio, precio_m2, tipo_propiedad, fecha_creacion FROM propiedades WHERE id = ANY(%s)
        """, (list(ids),)) if ids else []
    est = _estadisticas(inm, pedidos)
    t1, t2 = d["umbral"]
    lat_c, lng_c = statistics.mean(ys[:-1]), statistics.mean(xs[:-1])
    huella = hashlib.sha1(json.dumps([[round(a, 5), round(b, 5)] for a, b in anillo]).encode()).hexdigest()[:12]
    return {
        "id": f"area:{huella}", "tipo": "area", "nombre": nombre or "Área dibujada", "lat": lat_c, "lng": lng_c,
        "poligono": anillo, **est, "temperatura": _temperatura(est["pedidos"], est["ratio"], t1, t2),
        "zonas_incluidas": [{"id": z["id"], "nombre": z["nombre"]} for z in zonas_area][:12],
        **_analizar(puntos, pedidos, user_id),
    }


def buscar_zona(texto: str) -> List[Dict[str, Any]]:
    k = _norm(texto) or ""
    if not k:
        return []
    d = _datos()
    hits = [z for z in d["zonas"] if k in z["id"]]
    return [{"id": z["id"], "nombre": z["nombre"], "lat": z["lat"], "lng": z["lng"],
             "inmuebles": z["inmuebles"], "pedidos": z["pedidos"]} for z in hits[:8]]


# ---------------------------------------------------------------------------
# Áreas guardadas por el agente
# ---------------------------------------------------------------------------

def listar_areas(user_id: int) -> List[Dict[str, Any]]:
    with get_db() as db:
        filas = fetch_all(db.cursor, """
            SELECT id, nombre, color, poligono, created_at FROM mapa_areas
            WHERE user_id = %s ORDER BY created_at DESC LIMIT 50
        """, (user_id,))
    return [{"id": f["id"], "nombre": f["nombre"], "color": f["color"], "poligono": f["poligono"],
             "creada": f["created_at"].isoformat()} for f in filas]


def guardar_area(user_id: int, nombre: str, poligono: Any, color: Optional[str] = None) -> Dict[str, Any]:
    anillo = _validar_poligono(poligono)
    nombre = " ".join((nombre or "").split())[:60]
    if len(nombre) < 2:
        raise MapaError("invalido", "Ponle un nombre al área.")
    color = color if color and re.fullmatch(r"#[0-9A-Fa-f]{6}", color) else "#2AE38C"
    with get_db() as db:
        n = fetch_one(db.cursor, "SELECT COUNT(*) AS n FROM mapa_areas WHERE user_id = %s", (user_id,))["n"]
        if n >= 50:
            raise MapaError("limite", "Tienes 50 áreas guardadas; borra alguna para guardar otra.")
        db.cursor.execute("""
            INSERT INTO mapa_areas (user_id, nombre, color, poligono) VALUES (%s, %s, %s, %s)
            RETURNING id, created_at
        """, (user_id, nombre, color, json.dumps(anillo)))
        fila = db.cursor.fetchone()
        db.conn.commit()
    return {"id": fila["id"], "nombre": nombre, "color": color, "poligono": anillo, "creada": fila["created_at"].isoformat()}


def borrar_area(user_id: int, area_id: int) -> bool:
    with get_db() as db:
        db.cursor.execute("DELETE FROM mapa_areas WHERE id = %s AND user_id = %s RETURNING id", (area_id, user_id))
        ok = db.cursor.fetchone() is not None
        db.conn.commit()
    return ok
