"""
Mapa de mercado para el agente: zonas, oferta, demanda y precios sobre el mapa.

Cómo se arma (los datos reales son desordenados):
  - Muchos inmuebles traen coordenadas pero no el barrio, y los pedidos traen el
    barrio escrito pero no coordenadas. Por eso las ZONAS se construyen con los
    inmuebles que sí tienen nombre de zona: su centro es la mediana de sus
    coordenadas (descartando puntos a más de 3 km, que suelen ser errores de
    geocodificación). Luego, los inmuebles sin nombre se asignan a la zona más
    cercana (≤ 1,5 km) para que las estadísticas usen todo el inventario.
  - La DEMANDA son los pedidos de los últimos 120 días con criterios
    estructurados: cada zona pedida se cruza por nombre normalizado (y alias).
  - La TEMPERATURA compara demanda contra oferta (pedidos por cada inmueble) y
    se reparte en tercios entre las zonas: caliente, tibia, fría.

Nunca devuelve contactos ni links del portal de origen (lo que Fynder cobra):
solo datos del inmueble y, para pedidos, los criterios y si se pueden abrir con
una llave. Las zonas se cachean 10 minutos en memoria.
"""

import math
import re
import statistics
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.services.db import get_db, fetch_all, fetch_one

# Valle de Aburrá + Oriente cercano (donde está casi todo el inventario).
BBOX_REGION = (5.95, -75.75, 6.45, -75.30)  # sur, oeste, norte, este
DIAS_DEMANDA = 120
MIN_INMUEBLES_ZONA = 4
RADIO_OUTLIER_KM = 3.0
RADIO_ASIGNACION_KM = 1.5
TTL_CACHE = 600

_ALIAS = {
    "poblado": "el poblado", "alto de las palmas": "las palmas", "alto de palmas": "las palmas",
    "palmas": "las palmas", "via las palmas": "las palmas", "llano grande": "llanogrande",
    "laureles estadio": "laureles", "estadio": "estadio", "envigado centro": "envigado",
    "sabaneta centro": "sabaneta", "medellin": None, "antioquia": None, "valle de aburra": None,
}

_cache: Dict[str, Any] = {"t": 0.0, "datos": None}
_lock = threading.Lock()


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


def _mediana(xs: List[float]) -> Optional[float]:
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


# ---------------------------------------------------------------------------
# Zonas (cacheadas)
# ---------------------------------------------------------------------------

_SQL_INMUEBLES = """
    SELECT id, zona, latitud::float AS lat, longitud::float AS lng, precio, precio_m2,
           area_construida, tipo_propiedad, fecha_creacion
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
            SELECT id, criterios, fecha_captura FROM pedidos
            WHERE criterios IS NOT NULL AND fecha_captura > NOW() - INTERVAL '{DIAS_DEMANDA} days'
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
        c = (_mediana([p["lat"] for p in ps]), _mediana([p["lng"] for p in ps]))
        buenos = [p for p in ps if _km(c, (p["lat"], p["lng"])) <= RADIO_OUTLIER_KM]
        if len(buenos) < MIN_INMUEBLES_ZONA:
            continue
        c = (_mediana([p["lat"] for p in buenos]), _mediana([p["lng"] for p in buenos]))
        zonas[k] = {"id": k, "nombre": nombres[k].most_common(1)[0][0], "lat": c[0], "lng": c[1], "_inm": []}

    # 2. Todo el inventario con coordenadas cae en su zona (o en la más cercana)
    centros = [(k, (z["lat"], z["lng"])) for k, z in zonas.items()]
    for p in inmuebles:
        k = _norm(p.get("zona"))
        if k not in zonas:
            cerca = min(((kk, _km(cc, (p["lat"], p["lng"]))) for kk, cc in centros), key=lambda x: x[1], default=(None, 99))
            k = cerca[0] if cerca[1] <= RADIO_ASIGNACION_KM else None
        if k:
            zonas[k]["_inm"].append(p)

    # 3. Demanda: pedidos que nombran la zona
    demanda: Dict[str, List[dict]] = defaultdict(list)
    for ped in pedidos:
        crit = ped.get("criterios") or {}
        vistos = set()
        for z in crit.get("zonas") or []:
            k = _norm(z)
            if not k or k in vistos:
                continue
            if k not in zonas:  # "Loma de los González" → contiene/está contenida en una zona conocida
                k = next((kk for kk in zonas if kk in k or k in kk), None)
            if k and k not in vistos:
                vistos.add(k)
                demanda[k].append(ped)

    # 4. Estadísticas por zona
    for k, z in zonas.items():
        inm = z.pop("_inm")
        peds = demanda.get(k, [])
        pm2 = [v for v in (_pm2_valido(p.get("precio_m2")) for p in inm) if v]
        presup = [float((p["criterios"] or {}).get("presupuesto_max")) for p in peds
                  if (p["criterios"] or {}).get("presupuesto_max")]
        tipos = Counter((p.get("tipo_propiedad") or "Otro").strip().title() for p in inm)
        tipos_buscados = Counter(t.title() for p in peds for t in ((p["criterios"] or {}).get("tipos") or []))
        z.update({
            "inmuebles": len(inm),
            "pedidos": len(peds),
            "precio_m2": _mediana(pm2),
            "precio_mediana": _mediana([float(p["precio"]) for p in inm if p.get("precio")]),
            "presupuesto_mediana": _mediana(presup),
            "dias_mercado": _mediana([_dias(p.get("fecha_creacion")) for p in inm]),
            "tipos": dict(tipos.most_common(4)),
            "tipos_buscados": dict(tipos_buscados.most_common(4)),
            "ratio": round(len(peds) / max(1, len(inm)), 3),
        })

    # 5. Temperatura por tercios del ratio demanda/oferta (solo zonas con algo de demanda)
    con_demanda = sorted(z["ratio"] for z in zonas.values() if z["pedidos"] > 0)
    t1 = con_demanda[len(con_demanda) // 3] if con_demanda else 0
    t2 = con_demanda[(2 * len(con_demanda)) // 3] if con_demanda else 0
    for z in zonas.values():
        z["temperatura"] = "fria" if z["pedidos"] == 0 or z["ratio"] < t1 else ("caliente" if z["ratio"] >= t2 else "tibia")

    lista = sorted(zonas.values(), key=lambda z: -(z["inmuebles"] + z["pedidos"] * 3))
    return {"zonas": lista, "por_id": {z["id"]: z for z in lista},
            "totales": {"inmuebles": len(inmuebles), "pedidos": len(pedidos), "zonas": len(lista)},
            "generado": datetime.now(timezone.utc).isoformat()}


def _datos() -> Dict[str, Any]:
    with _lock:
        if _cache["datos"] is None or time.time() - _cache["t"] > TTL_CACHE:
            _cache["datos"] = _construir()
            _cache["t"] = time.time()
        return _cache["datos"]


def zonas() -> Dict[str, Any]:
    d = _datos()
    return {"zonas": d["zonas"], "totales": d["totales"], "generado": d["generado"]}


def _zona_de(lat: float, lng: float) -> Optional[Dict[str, Any]]:
    d = _datos()
    mejor = min(((z, _km((z["lat"], z["lng"]), (lat, lng))) for z in d["zonas"]), key=lambda x: x[1], default=(None, 99))
    return mejor[0] if mejor[1] <= RADIO_ASIGNACION_KM else None


# ---------------------------------------------------------------------------
# Inmuebles en el área visible
# ---------------------------------------------------------------------------

def _tarjeta(p: Dict[str, Any], pm2_zona: Optional[float]) -> Dict[str, Any]:
    pm2 = _pm2_valido(p.get("precio_m2"))
    return {
        "id": p["id"], "slug": str(p["id"]), "lat": p["lat"], "lng": p["lng"],
        "titulo": (p.get("titulo") or "").strip()[:90] or None,
        "tipo": (p.get("tipo_propiedad") or "").strip().title() or None,
        "precio": float(p["precio"]) if p.get("precio") else None,
        "precio_m2": pm2, "area": float(p["area_construida"]) if p.get("area_construida") else None,
        "habitaciones": p.get("habitaciones"), "banos": p.get("banos"),
        "imagen": p.get("imagen_principal"), "zona": (p.get("zona") or "").strip().title() or None,
        "dias": _dias(p.get("fecha_creacion")),
        "vs_zona": round(pm2 / pm2_zona - 1, 3) if pm2 and pm2_zona else None,
    }


def inmuebles(bbox: Tuple[float, float, float, float], tipo: Optional[str] = None,
              precio_min: Optional[float] = None, precio_max: Optional[float] = None,
              hab_min: Optional[int] = None, limite: int = 500) -> Dict[str, Any]:
    s, w, n, e = bbox
    filtros, params = ["latitud BETWEEN %s AND %s", "longitud BETWEEN %s AND %s"], [s, n, w, e]
    if tipo:
        filtros.append("tipo_propiedad ILIKE %s")
        params.append(tipo)
    if precio_min:
        filtros.append("precio >= %s")
        params.append(precio_min)
    if precio_max:
        filtros.append("precio <= %s")
        params.append(precio_max)
    if hab_min:
        filtros.append("habitaciones >= %s")
        params.append(hab_min)
    donde = " AND ".join(["activa", "COALESCE(tipo_negocio, 'Venta') ILIKE 'venta'"] + filtros)
    with get_db() as db:
        cur = db.cursor
        resumen = fetch_one(cur, f"""
            SELECT COUNT(*) AS total,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY precio_m2)
                     FILTER (WHERE precio_m2 BETWEEN 1000000 AND 40000000) AS pm2,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY precio) FILTER (WHERE precio > 0) AS precio
            FROM propiedades WHERE {donde}
        """, params)
        filas = fetch_all(cur, f"""
            SELECT id, titulo, zona, latitud::float AS lat, longitud::float AS lng, precio, precio_m2,
                   area_construida, habitaciones, banos, tipo_propiedad, imagen_principal, fecha_creacion
            FROM propiedades WHERE {donde}
            ORDER BY fecha_creacion DESC NULLS LAST LIMIT %s
        """, params + [limite])
    salida = []
    for p in filas:
        z = _zona_de(p["lat"], p["lng"])
        salida.append(_tarjeta(p, z["precio_m2"] if z else None))
    return {"total": int(resumen["total"] or 0), "mostrados": len(salida),
            "precio_m2_mediana": float(resumen["pm2"]) if resumen.get("pm2") else None,
            "precio_mediana": float(resumen["precio"]) if resumen.get("precio") else None,
            "inmuebles": salida}


# ---------------------------------------------------------------------------
# Detalle de una zona
# ---------------------------------------------------------------------------

def _resumen_pedido(p: Dict[str, Any]) -> Dict[str, Any]:
    # Solo criterios estructurados: el texto libre puede traer el nombre o la firma de quien pidió
    # (eso se obtiene con una llave), así que no se muestra.
    c = p.get("criterios") or {}
    return {
        "id": p["id"], "fecha": p["fecha_captura"].isoformat() if p.get("fecha_captura") else None,
        "tipos": c.get("tipos") or [], "zonas": (c.get("zonas") or [])[:4],
        "presupuesto_max": c.get("presupuesto_max"), "presupuesto_min": c.get("presupuesto_min"),
        "habitaciones_min": c.get("habitaciones_min"), "area_min": c.get("area_min"),
        "exigencias": (c.get("exigencias") or [])[:4],
    }


def zona_detalle(zona_id: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    d = _datos()
    z = d["por_id"].get(zona_id)
    if not z:
        return None
    radio_deg = 0.02  # ~2 km: los inmuebles se filtran luego por pertenencia a la zona
    with get_db() as db:
        cur = db.cursor
        filas = fetch_all(cur, """
            SELECT id, titulo, zona, latitud::float AS lat, longitud::float AS lng, precio, precio_m2,
                   area_construida, habitaciones, banos, tipo_propiedad, imagen_principal, fecha_creacion
            FROM propiedades
            WHERE activa AND COALESCE(tipo_negocio, 'Venta') ILIKE 'venta'
              AND latitud BETWEEN %s AND %s AND longitud BETWEEN %s AND %s
        """, (z["lat"] - radio_deg, z["lat"] + radio_deg, z["lng"] - radio_deg, z["lng"] + radio_deg))
        peds = fetch_all(cur, f"""
            SELECT p.id, p.criterios, p.fecha_captura,
                   RIGHT(REGEXP_REPLACE(COALESCE(p.agente_telefono, ''), '[^0-9]', '', 'g'), 10) AS tel10
            FROM pedidos p
            WHERE p.criterios IS NOT NULL AND p.fecha_captura > NOW() - INTERVAL '{DIAS_DEMANDA} days'
            ORDER BY p.fecha_captura DESC
        """)
        verificados = {r["tel10"] for r in fetch_all(cur, """
            SELECT RIGHT(REGEXP_REPLACE(COALESCE(telefono, ''), '[^0-9]', '', 'g'), 10) AS tel10
            FROM chat_users WHERE activo AND telefono_verificado AND terminos_aceptados_at IS NOT NULL
        """)}
        abiertos = set()
        if user_id:
            abiertos = {r["ref_id"] for r in fetch_all(cur, """
                SELECT ref_id FROM desbloqueos WHERE user_id = %s AND tipo = 'pedido' AND estado = 'vigente'
            """, (user_id,))}

    inm = [p for p in filas if (_zona_de(p["lat"], p["lng"]) or {}).get("id") == zona_id]
    tarjetas = [_tarjeta(p, z["precio_m2"]) for p in inm]
    oportunidades = sorted([t for t in tarjetas if t["vs_zona"] is not None and t["vs_zona"] <= -0.08],
                           key=lambda t: t["vs_zona"])[:8]
    recientes = sorted([t for t in tarjetas if t["dias"] is not None], key=lambda t: t["dias"])[:8]

    # Histograma de precios (6 tramos entre p5 y p95)
    precios = sorted(t["precio"] for t in tarjetas if t["precio"])
    histograma = []
    if len(precios) >= 4:
        lo, hi = precios[int(len(precios) * 0.05)], precios[int(len(precios) * 0.95) - 1]
        paso = max(1.0, (hi - lo) / 6)
        for i in range(6):
            a, b = lo + i * paso, lo + (i + 1) * paso
            histograma.append({"desde": a, "hasta": b, "n": sum(1 for x in precios if a <= x < b or (i == 5 and x == b))})

    pedidos_zona = []
    for p in peds:
        crit_zonas = [_norm(x) for x in ((p.get("criterios") or {}).get("zonas") or [])]
        if any(k and (k == zona_id or k in zona_id or zona_id in k) for k in crit_zonas):
            r = _resumen_pedido(p)
            r["desbloqueable"] = p["tel10"] in verificados
            r["abierto"] = p["id"] in abiertos
            pedidos_zona.append(r)
        if len(pedidos_zona) >= 20:
            break

    return {**z, "oportunidades": oportunidades, "recientes": recientes, "histograma": histograma,
            "pedidos_lista": pedidos_zona}


def buscar_zona(texto: str) -> List[Dict[str, Any]]:
    k = _norm(texto) or ""
    if not k:
        return []
    d = _datos()
    hits = [z for z in d["zonas"] if k in z["id"]]
    return [{"id": z["id"], "nombre": z["nombre"], "lat": z["lat"], "lng": z["lng"],
             "inmuebles": z["inmuebles"], "pedidos": z["pedidos"]} for z in hits[:8]]
