"""
Observatorio del mercado (admin): lo que Fynder sabe del mercado inmobiliario del
Valle de Aburrá con su propio inventario (avisos), la demanda (pedidos) y su
historia (cambios de precio, salidas del mercado).

Una consulta trae el inventario de venta con su barrio normalizado (barrios_service)
y todo se calcula en Python: precio por m² por barrio y comuna, distribución,
tiempo en el mercado, bajas de precio, oferta contra demanda, lo que piden y no
hay, y cuánto pesa cada característica en el precio. Se cachea 10 minutos.

Advertencias que el admin ve junto a los datos:
  - Son precios de LISTA (lo que piden), no de cierre.
  - "Salida" = el validador confirmó que el aviso ya no está publicado (fecha real
    de esa verificación); no siempre significa venta. Hay datos desde oct-2026.
  - La muestra son los avisos que llegan a Fynder (grupos de agentes y portales).
"""

import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from src.services.db import fetch_all, get_db

_CACHE: Dict[Tuple, Tuple[float, Any]] = {}
_LOCK = threading.Lock()
_TTL = 10 * 60
MIN_BARRIO = 5          # avisos activos para mostrar un barrio
SEMANAS = 26

_TIPO = """
    CASE
      WHEN p.tipo_propiedad ~* 'apartaestudio' THEN 'apartaestudio'
      WHEN p.tipo_propiedad ~* 'campestre|caba' THEN 'casa_campestre'
      WHEN p.tipo_propiedad ~* 'apartamento|departamento|penthouse|d.plex|^ph' THEN 'apartamento'
      WHEN p.tipo_propiedad ~* 'casa' THEN 'casa'
      WHEN p.tipo_propiedad ~* 'lote|terreno' THEN 'lote'
      WHEN p.tipo_propiedad ~* 'local|oficina|consultorio|bodega' THEN 'comercial'
      ELSE 'otro'
    END"""

BANDAS = [(0, 300e6, "< 300 M"), (300e6, 500e6, "300–500 M"), (500e6, 800e6, "500–800 M"),
          (800e6, 1200e6, "800 M–1.200 M"), (1200e6, 1e15, "> 1.200 M")]
HABS = ["1", "2", "3", "4+"]


def _q(xs: List[float], q: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    i = (len(s) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def _banda(precio: Optional[float]) -> Optional[str]:
    if not precio:
        return None
    for a, b, n in BANDAS:
        if a <= precio < b:
            return n
    return None


def _hab(h: Any) -> Optional[str]:
    try:
        h = int(h)
    except (TypeError, ValueError):
        return None
    return None if h <= 0 else ("4+" if h >= 4 else str(h))


def _semana(d: datetime) -> str:
    d = d.date() if isinstance(d, datetime) else d
    return (d - timedelta(days=d.weekday())).isoformat()


def _cargar(cur, municipio: Optional[str], tipo: Optional[str]) -> Dict[str, Any]:
    cond, params = ["COALESCE(lower(p.tipo_negocio), 'venta') <> 'arriendo'", "p.precio > 0"], []
    if municipio:
        cond.append("pb.municipio = %s")
        params.append(municipio)
    filas = fetch_all(cur, f"""
        SELECT p.id, p.precio::float AS precio, COALESCE(p.area_construida, f.area_m2)::float AS area,
               {_TIPO} AS tipo, pb.municipio AS municipio, pb.barrio_id, b.nombre AS barrio, b.comuna,
               b.lat AS b_lat, b.lng AS b_lng, COALESCE(p.estrato, f.estrato) AS estrato,
               COALESCE(p.habitaciones, f.habitaciones) AS habitaciones,
               p.fecha_creacion, s.salida_at AS fecha_actualizacion, p.activa, p.latitud, p.longitud,
               f.caracteristicas, pb.fuente AS barrio_fuente
        FROM propiedades p
        LEFT JOIN propiedades_ficha f ON f.propiedad_id = p.id
        LEFT JOIN propiedad_barrio pb ON pb.propiedad_id = p.id
        LEFT JOIN barrios b ON b.id = pb.barrio_id
        -- Salida = la verificación que confirmó que el aviso murió (no la última actualización).
        LEFT JOIN LATERAL (SELECT MIN(v.created_at) AS salida_at FROM verificaciones_disponibilidad v
                           WHERE v.propiedad_id = p.id AND v.veredicto = 'muerto') s ON NOT p.activa
        WHERE {' AND '.join(cond)}
    """, params)
    if tipo:
        filas = [f for f in filas if f["tipo"] == tipo]
    ids = [f["id"] for f in filas]
    cambios = fetch_all(cur, """
        SELECT propiedad_id, precio_anterior::float AS antes, precio_nuevo::float AS despues, created_at
        FROM cambios_precio WHERE aplicado AND propiedad_id = ANY(%s)
    """, (ids,)) if ids else []
    pedidos = fetch_all(cur, """
        SELECT id, criterios, barrio_ids, fecha_captura FROM pedidos
        WHERE criterios IS NOT NULL AND estado <> 'retirado' AND fecha_captura > NOW() - INTERVAL '365 days'
    """)
    return {"filas": filas, "cambios": cambios, "pedidos": pedidos}


def _m2(f: Dict[str, Any]) -> Optional[float]:
    a = f.get("area")
    if not a or a < 20 or a > 2000:
        return None
    v = f["precio"] / a
    return v if 500_000 <= v <= 40_000_000 else None   # descarta datos mal cargados


def calcular(municipio: Optional[str] = None, tipo: Optional[str] = "apartamento") -> Dict[str, Any]:
    llave = (municipio or "", tipo or "")
    with _LOCK:
        c = _CACHE.get(llave)
        if c and time.time() - c[0] < _TTL:
            return c[1]
    with get_db() as db:
        datos = _cargar(db.cursor, municipio, tipo)
    salida = _calcular(datos, municipio, tipo)
    with _LOCK:
        _CACHE[llave] = (time.time(), salida)
    return salida


def _calcular(d: Dict[str, Any], municipio: Optional[str], tipo: Optional[str]) -> Dict[str, Any]:
    ahora = datetime.now(timezone.utc)
    filas, cambios, pedidos = d["filas"], d["cambios"], d["pedidos"]
    activas = [f for f in filas if f["activa"]]
    salidas = [f for f in filas if not f["activa"] and f["fecha_actualizacion"] and f["fecha_creacion"]]
    ids_salidas = {f["id"] for f in salidas}

    def dias(f):
        fa, fc = f["fecha_actualizacion"], f["fecha_creacion"]
        fa = fa if fa.tzinfo else fa.replace(tzinfo=timezone.utc)
        fc = fc if fc.tzinfo else fc.replace(tzinfo=timezone.utc)
        return max(0, (fa - fc).days)

    bajaron = {c["propiedad_id"] for c in cambios if c["despues"] and c["antes"] and c["despues"] < c["antes"]}
    baja_pct = defaultdict(list)
    for c in cambios:
        if c["antes"] and c["despues"] and c["despues"] < c["antes"]:
            baja_pct[c["propiedad_id"]].append(1 - c["despues"] / c["antes"])

    # Demanda: pedidos de los últimos 180 días (por barrio y por banda/habitaciones).
    lim = ahora - timedelta(days=180)
    ped_rec = [p for p in pedidos if p["fecha_captura"] and (p["fecha_captura"] if p["fecha_captura"].tzinfo else p["fecha_captura"].replace(tzinfo=timezone.utc)) >= lim]
    dem_barrio = Counter(b for p in ped_rec for b in (p["barrio_ids"] or []))

    # ── KPIs ───────────────────────────────────────────────────────────────
    m2_act = [v for v in (_m2(f) for f in activas) if v]
    hace30 = ahora - timedelta(days=30)

    def _tz(x):
        return x if x is None or x.tzinfo else x.replace(tzinfo=timezone.utc)

    kpis = {
        "activos": len(activas),
        "nuevos_30d": sum(1 for f in filas if f["fecha_creacion"] and _tz(f["fecha_creacion"]) >= hace30),
        "salidas_30d": sum(1 for f in salidas if _tz(f["fecha_actualizacion"]) >= hace30),
        "m2_mediana": round(median(m2_act)) if m2_act else None,
        "precio_mediana": round(median([f["precio"] for f in activas])) if activas else None,
        "dias_mediana_salida": round(median([dias(f) for f in salidas])) if salidas else None,
        "pct_bajaron": round(100 * len(bajaron & {f["id"] for f in filas}) / len(filas), 1) if filas else 0,
        "baja_promedio_pct": round(100 * median([max(v) for v in baja_pct.values()]), 1) if baja_pct else None,
        "pedidos_180d": len(ped_rec),
    }

    # ── Serie semanal ──────────────────────────────────────────────────────
    sem = defaultdict(lambda: {"nuevos": 0, "salidas": 0, "bajas": 0, "pedidos": 0})
    desde = ahora - timedelta(weeks=SEMANAS)
    for f in filas:
        if f["fecha_creacion"] and _tz(f["fecha_creacion"]) >= desde:
            sem[_semana(f["fecha_creacion"])]["nuevos"] += 1
    for f in salidas:
        if _tz(f["fecha_actualizacion"]) >= desde:
            sem[_semana(f["fecha_actualizacion"])]["salidas"] += 1
    for c in cambios:
        if c["created_at"] and _tz(c["created_at"]) >= desde and c["despues"] and c["antes"] and c["despues"] < c["antes"]:
            sem[_semana(c["created_at"])]["bajas"] += 1
    for p in pedidos:
        if p["fecha_captura"] and _tz(p["fecha_captura"]) >= desde:
            sem[_semana(p["fecha_captura"])]["pedidos"] += 1
    semanas = [{"semana": k, **v} for k, v in sorted(sem.items())]

    # ── Por barrio ─────────────────────────────────────────────────────────
    por_b: Dict[int, Dict[str, Any]] = {}
    for f in filas:
        if not f["barrio_id"]:
            continue
        b = por_b.setdefault(f["barrio_id"], {"id": f["barrio_id"], "barrio": f["barrio"], "comuna": f["comuna"],
                                              "municipio": f["municipio"], "lat": f["b_lat"], "lng": f["b_lng"],
                                              "m2": [], "precios": [], "dias": [], "n_total": 0, "bajaron": 0, "activos": 0})
        b["n_total"] += 1
        if f["id"] in bajaron:
            b["bajaron"] += 1
        if f["activa"]:
            b["activos"] += 1
            v = _m2(f)
            if v:
                b["m2"].append(v)
            b["precios"].append(f["precio"])
        elif f["id"] in ids_salidas:
            b["dias"].append(dias(f))
    barrios = []
    for b in por_b.values():
        if b["activos"] < MIN_BARRIO or len(b["m2"]) < 3:
            continue
        dem = dem_barrio.get(b["id"], 0)
        barrios.append({
            "id": b["id"], "barrio": b["barrio"], "comuna": b["comuna"], "municipio": b["municipio"],
            "lat": b["lat"], "lng": b["lng"], "activos": b["activos"],
            "m2_mediana": round(median(b["m2"])), "m2_p25": round(_q(b["m2"], .25)), "m2_p75": round(_q(b["m2"], .75)),
            "m2_min": round(min(b["m2"])), "m2_max": round(max(b["m2"])),
            "precio_mediana": round(median(b["precios"])),
            "dias_salida": round(median(b["dias"])) if len(b["dias"]) >= 3 else None,
            "pct_bajaron": round(100 * b["bajaron"] / b["n_total"], 1),
            "demanda": dem, "demanda_por_oferta": round(dem / b["activos"], 2),
        })
    barrios.sort(key=lambda x: -x["activos"])

    # ── Por comuna ─────────────────────────────────────────────────────────
    # Las mismas métricas del mapa por barrio, sumando todos los barrios de la comuna.
    por_c: Dict[str, Dict[str, Any]] = {}
    for b in por_b.values():
        if not b["comuna"]:
            continue
        # "Zona 9" de Envigado no es la comuna 9 de Medellín: fuera de Medellín va con su municipio.
        nombre = b["comuna"] if b["municipio"] in (None, "Medellín") else f"{b['municipio']} · {b['comuna']}"
        c = por_c.setdefault(nombre, {"m2": [], "dias": [], "activos": 0, "demanda": 0})
        c["m2"] += b["m2"]
        c["dias"] += b["dias"]
        c["activos"] += b["activos"]
        c["demanda"] += dem_barrio.get(b["id"], 0)
    comunas = sorted([{"comuna": k, "activos": c["activos"], "m2_mediana": round(median(c["m2"])),
                       "demanda": c["demanda"], "demanda_por_oferta": round(c["demanda"] / c["activos"], 2),
                       "dias_salida": round(median(c["dias"])) if len(c["dias"]) >= 3 else None}
                      for k, c in por_c.items() if len(c["m2"]) >= 5],
                     key=lambda x: -x["m2_mediana"])

    # ── Oferta vs demanda: habitaciones × presupuesto ──────────────────────
    oferta = Counter((_hab(f["habitaciones"]), _banda(f["precio"])) for f in activas)
    demanda = Counter()
    for p in ped_rec:
        c = p["criterios"] if isinstance(p["criterios"], dict) else {}
        h, bnd = _hab(c.get("habitaciones_min")), _banda(c.get("presupuesto_max"))
        if h and bnd:
            demanda[(h, bnd)] += 1
    celdas = []
    for h in HABS:
        for _, _, bnd in BANDAS:
            o, dm = oferta.get((h, bnd), 0), demanda.get((h, bnd), 0)
            celdas.append({"habitaciones": h, "banda": bnd, "oferta": o, "demanda": dm,
                           "presion": round(dm / o, 2) if o else (None if not dm else 99)})

    # ── Características: % de avisos y prima de precio (contra la mediana de su barrio) ──
    med_barrio = {b["id"]: b["m2_mediana"] for b in barrios}
    con, sin = defaultdict(list), defaultdict(list)
    base = [(set(f["caracteristicas"] or []), _m2(f) / med_barrio[f["barrio_id"]]) for f in activas
            if _m2(f) and med_barrio.get(f["barrio_id"])]
    todas = Counter(k for cs, _ in base for k in cs)
    for cs, rel in base:
        for k in todas:
            (con if k in cs else sin)[k].append(rel)
    n_base = len(base)
    caracteristicas = []
    for k, n in todas.most_common(30):
        if len(con[k]) >= 25 and len(sin[k]) >= 25:
            caracteristicas.append({"caracteristica": k, "pct": round(100 * n / max(1, n_base), 1),
                                    "prima_pct": round(100 * (median(con[k]) - median(sin[k])), 1), "n": len(con[k])})
    caracteristicas.sort(key=lambda x: -x["prima_pct"])

    # ── Tiempo en el mercado (salidas) ─────────────────────────────────────
    cortes = [(0, 15, "< 15 d"), (15, 30, "15–30 d"), (30, 60, "1–2 meses"), (60, 120, "2–4 meses"), (120, 10_000, "+4 meses")]
    dd = [dias(f) for f in salidas]
    tiempo = [{"rango": n, "salidas": sum(1 for x in dd if a <= x < b)} for a, b, n in cortes]

    # ── Mapa de calor: puntos con su precio por m² ──────────────────────────
    puntos = [[float(f["latitud"]), float(f["longitud"]), round(_m2(f))] for f in activas
              if f["latitud"] is not None and f["longitud"] is not None and _m2(f)][:4000]

    # ── Calidad de los datos ───────────────────────────────────────────────
    fuentes = Counter(f["barrio_fuente"] or "sin_barrio" for f in filas)
    calidad = {"total": len(filas), "con_barrio": sum(1 for f in filas if f["barrio_id"]),
               "con_area": sum(1 for f in filas if _m2(f)), "fuentes_barrio": dict(fuentes),
               "pedidos_con_barrio": sum(1 for p in ped_rec if p["barrio_ids"])}

    municipios = Counter(f["municipio"] for f in activas if f["municipio"])
    return {
        "filtros": {"municipio": municipio, "tipo": tipo},
        "municipios": [{"municipio": m, "activos": n} for m, n in municipios.most_common(20)],
        "kpis": kpis, "semanas": semanas, "barrios": barrios, "comunas": comunas,
        "oferta_demanda": {"habitaciones": HABS, "bandas": [b[2] for b in BANDAS], "celdas": celdas},
        "caracteristicas": caracteristicas, "tiempo": tiempo, "puntos": puntos, "calidad": calidad,
        "generado": ahora.isoformat(),
    }
