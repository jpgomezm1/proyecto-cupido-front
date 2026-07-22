"""
Inteligencia de ubicación: "¿qué hay cerca?" de una propiedad.

Usa OpenStreetMap (Overpass API) — 100% gratis, sin API key — para listar
colegios, universidades, estaciones de Metro, supermercados, centros
comerciales, clínicas/hospitales, parques y bancos alrededor de una propiedad,
ordenados por distancia real.

Notas:
- Solo funciona con propiedades geolocalizadas (~73% de la base).
- Overpass tiene límites de uso: se usa timeout + fallback a un mirror + cache
  en memoria por coordenada para no golpear la API de más.
- Los datos de OSM son de referencia; la cobertura en el Valle de Aburrá es
  buena pero no perfecta.
"""

import math
import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from src.services.db import get_db, fetch_one
from src.services.property_service import get_property

_OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
_UA = "FynderMCP/1.0 (real-estate assistant for Colombian agents)"

# Categorías consultadas: (etiqueta, filtro Overpass, radio en metros).
_CATEGORIAS = [
    ("colegios",        '["amenity"~"^(school|kindergarten)$"]', 1200),
    ("universidades",   '["amenity"="university"]',              2500),
    ("metro",           '["railway"="station"]',                 2000),
    ("supermercados",   '["shop"~"^(supermarket|convenience)$"]', 1000),
    ("centros_comerciales", '["shop"="mall"]',                   2500),
    ("salud",           '["amenity"~"^(hospital|clinic)$"]',     2000),
    ("parques",         '["leisure"="park"]',                    1200),
    ("bancos",          '["amenity"="bank"]',                    1200),
]

# Cache simple en memoria: (lat,lon redondeados) -> (timestamp, resultado).
_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 60 * 60 * 24  # 24h


# Bounding box aproximado de Colombia. Muchas propiedades traen lat/lon = 0,0
# ("Null Island") o coordenadas fuera del país: son basura y no sirven.
_CO_LAT = (1.0, 13.5)
_CO_LON = (-80.0, -66.0)


def _coords_validas(lat, lon) -> bool:
    """True si la coordenada es usable (dentro de Colombia, no 0,0)."""
    if lat is None or lon is None:
        return False
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if abs(lat) < 0.01 and abs(lon) < 0.01:  # 0,0 = Null Island
        return False
    return _CO_LAT[0] <= lat <= _CO_LAT[1] and _CO_LON[0] <= lon <= _CO_LON[1]


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Distancia en metros entre dos coordenadas."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1, math.sqrt(a)))


def _build_query(lat: float, lon: float) -> str:
    partes = []
    for _etq, filtro, radio in _CATEGORIAS:
        partes.append(f'node{filtro}(around:{radio},{lat},{lon});')
        partes.append(f'way{filtro}(around:{radio},{lat},{lon});')
    return f'[out:json][timeout:25];({"".join(partes)});out center 60;'


def _categoria_de_tags(tags: Dict[str, str]) -> Optional[str]:
    amen = tags.get("amenity")
    if amen in ("school", "kindergarten"):
        return "colegios"
    if amen == "university":
        return "universidades"
    if amen in ("hospital", "clinic"):
        return "salud"
    if amen == "bank":
        return "bancos"
    if tags.get("railway") == "station":
        return "metro"
    shop = tags.get("shop")
    if shop in ("supermarket", "convenience"):
        return "supermercados"
    if shop == "mall":
        return "centros_comerciales"
    if tags.get("leisure") == "park":
        return "parques"
    return None


def _consultar_overpass(lat: float, lon: float) -> Optional[List[Dict[str, Any]]]:
    query = _build_query(lat, lon)
    headers = {"User-Agent": _UA}
    for url in _OVERPASS_URLS:
        try:
            resp = httpx.post(url, data={"data": query}, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("elements", [])
        except Exception:
            continue
    return None


def _lugares_cercanos(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    key = f"{round(lat, 4)},{round(lon, 4)}"
    with _cache_lock:
        hit = _cache.get(key)
        if hit and (time.time() - hit[0]) < _CACHE_TTL:
            return hit[1]

    elementos = _consultar_overpass(lat, lon)
    if elementos is None:
        return None

    por_categoria: Dict[str, List[Dict[str, Any]]] = {etq: [] for etq, _, _ in _CATEGORIAS}
    vistos = set()
    for e in elementos:
        tags = e.get("tags", {}) or {}
        cat = _categoria_de_tags(tags)
        if not cat:
            continue
        # coordenada del elemento (node -> lat/lon; way -> center).
        elat = e.get("lat") or (e.get("center") or {}).get("lat")
        elon = e.get("lon") or (e.get("center") or {}).get("lon")
        if elat is None or elon is None:
            continue
        nombre = tags.get("name")
        if not nombre:
            continue  # sin nombre no aporta al agente
        dist = round(_haversine_m(lat, lon, elat, elon))
        dedup = (cat, nombre)
        if dedup in vistos:
            continue
        vistos.add(dedup)
        por_categoria[cat].append({"nombre": nombre, "distancia_m": dist,
                                    "distancia": _fmt_dist(dist)})

    # Ordenar cada categoría por distancia y quedarnos con las más cercanas.
    resultado = {}
    for cat, items in por_categoria.items():
        items.sort(key=lambda x: x["distancia_m"])
        if items:
            resultado[cat] = items[:5]

    with _cache_lock:
        _cache[key] = (time.time(), resultado)
    return resultado


def _fmt_dist(m: int) -> str:
    if m < 1000:
        return f"{m} m"
    return f"{m/1000:.1f} km"


def que_hay_cerca(cur, property_id) -> Dict[str, Any]:
    """Devuelve los puntos de interés cercanos a una propiedad, por categoría."""
    p = get_property(cur, property_id)
    if not p:
        return {"error": f"Propiedad {property_id} no encontrada"}
    if not _coords_validas(p.get("latitud"), p.get("longitud")):
        return {
            "propiedad": {"id": p["id"], "slug": p["slug"], "zona": p["zona"]},
            "sin_geolocalizacion": True,
            "mensaje": ("Esta propiedad no tiene una ubicación exacta válida cargada "
                        "(coordenadas en 0,0 o fuera del país), así que no puedo mirar qué "
                        "hay alrededor. Para aprovechar esto, hay que cargarle la dirección/mapa real."),
        }

    cercanos = _lugares_cercanos(float(p["latitud"]), float(p["longitud"]))
    if cercanos is None:
        return {
            "propiedad": {"id": p["id"], "slug": p["slug"], "zona": p["zona"]},
            "error_fuente": True,
            "mensaje": "El servicio de mapas no respondió en este momento; intenta de nuevo en un rato.",
        }

    # Resumen de titulares para que Claude lo cuente rápido.
    titulares = []
    for cat in ("metro", "colegios", "centros_comerciales", "supermercados", "salud", "parques"):
        items = cercanos.get(cat)
        if items:
            mas_cerca = items[0]
            etq = {"metro": "estación de Metro", "colegios": "colegio",
                   "centros_comerciales": "centro comercial", "supermercados": "supermercado",
                   "salud": "clínica/hospital", "parques": "parque"}[cat]
            titulares.append(f"{etq} más cercano: {mas_cerca['nombre']} a {mas_cerca['distancia']}")

    return {
        "propiedad": {"id": p["id"], "slug": p["slug"], "titulo": p["titulo"],
                      "zona": p["zona"], "direccion": p.get("direccion")},
        "titulares": titulares,
        "cerca": cercanos,
        "fuente": "OpenStreetMap",
    }


def que_hay_cerca_public(property_id):
    with get_db() as db:
        return que_hay_cerca(db.cursor, property_id)
