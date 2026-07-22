"""
Servicio de inteligencia de mercado.

Estadísticas de OFERTA (inventario en `propiedades`) y DEMANDA (búsquedas en
`solicitudes_mercado` y pedidos de compradores en `pedidos`), más el balance
oferta/demanda de una zona. Todo SQL parametrizado, sin llamadas a IA, por lo
que es 100% testeable contra la BD real.

Convención: las funciones internas reciben un cursor (`cur`) para poder
componerse dentro de una sola conexión; los wrappers públicos abren su propia
conexión.
"""

from typing import Any, Dict, List, Optional

from src.services.db import get_db, fetch_all, fetch_one
from src.services.textutils import (
    accent_insensitive_expr,
    accent_lower_raw,
    like_param,
    format_cop,
)

# Umbral mínimo de inventario para considerar que las estadísticas de una zona
# son estadísticamente razonables (por debajo, se marca baja_confianza).
MIN_MUESTRA_CONFIABLE = 5


def _location_filter(ciudad: Optional[str], zona: Optional[str],
                     tipo_propiedad: Optional[str], tipo_negocio: Optional[str],
                     alias: str = "p"):
    """Construye condiciones WHERE + params para filtrar propiedades por zona."""
    conditions = [f"{alias}.activa = TRUE", f"{alias}.precio IS NOT NULL", f"{alias}.precio > 0"]
    params: List[Any] = []

    if tipo_negocio:
        conditions.append(f"{alias}.tipo_negocio = %s")
        params.append(tipo_negocio)
    if ciudad:
        conditions.append(f"{accent_insensitive_expr(f'{alias}.ciudad')} LIKE %s")
        params.append(like_param(ciudad))
    if zona:
        conditions.append(f"{accent_insensitive_expr(f'{alias}.zona')} LIKE %s")
        params.append(like_param(zona))
    if tipo_propiedad:
        conditions.append(f"{accent_insensitive_expr(f'{alias}.tipo_propiedad')} LIKE %s")
        params.append(like_param(tipo_propiedad))

    return conditions, params


def zone_stats(cur, ciudad: Optional[str] = None, zona: Optional[str] = None,
               tipo_propiedad: Optional[str] = None,
               tipo_negocio: str = "Venta") -> Dict[str, Any]:
    """
    Estadísticas de OFERTA de una zona: inventario activo, distribución de
    precios (percentiles), precio/m², área, habitaciones, fotos y antigüedad
    promedio del inventario.
    """
    conditions, params = _location_filter(ciudad, zona, tipo_propiedad, tipo_negocio)
    where = " AND ".join(conditions)

    agg = fetch_one(cur, f"""
        SELECT
            COUNT(*)                                                      AS inventario,
            MIN(p.precio)                                                 AS precio_min,
            MAX(p.precio)                                                 AS precio_max,
            AVG(p.precio)                                                 AS precio_promedio,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY p.precio)        AS precio_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY p.precio)        AS precio_mediana,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY p.precio)        AS precio_p75,
            percentile_cont(0.50) WITHIN GROUP (
                ORDER BY p.precio / NULLIF(p.area_construida, 0)
            ) FILTER (WHERE p.area_construida > 0)                        AS precio_m2_mediana,
            AVG(p.area_construida) FILTER (WHERE p.area_construida > 0)   AS area_promedio,
            AVG(p.habitaciones)   FILTER (WHERE p.habitaciones IS NOT NULL) AS habitaciones_promedio,
            AVG(p.total_imagenes)                                         AS fotos_promedio,
            AVG(EXTRACT(DAY FROM NOW() - p.fecha_creacion))               AS dias_inventario_promedio
        FROM propiedades p
        WHERE {where}
    """, params) or {}

    inventario = int(agg.get("inventario") or 0)

    # Distribución por número de habitaciones (mix del inventario).
    hab_rows = fetch_all(cur, f"""
        SELECT p.habitaciones AS habitaciones, COUNT(*) AS total
        FROM propiedades p
        WHERE {where} AND p.habitaciones IS NOT NULL
        GROUP BY p.habitaciones
        ORDER BY p.habitaciones
    """, params)

    def _f(key):
        v = agg.get(key)
        return float(v) if v is not None else None

    return {
        "filtro": {
            "ciudad": ciudad, "zona": zona,
            "tipo_propiedad": tipo_propiedad, "tipo_negocio": tipo_negocio,
        },
        "inventario_activo": inventario,
        "baja_confianza": inventario < MIN_MUESTRA_CONFIABLE,
        "precio": {
            "min": _f("precio_min"),
            "p25": _f("precio_p25"),
            "mediana": _f("precio_mediana"),
            "p75": _f("precio_p75"),
            "max": _f("precio_max"),
            "promedio": _f("precio_promedio"),
            "mediana_legible": format_cop(_f("precio_mediana")),
        },
        "precio_m2_mediana": _f("precio_m2_mediana"),
        "area_promedio": _f("area_promedio"),
        "habitaciones_promedio": _f("habitaciones_promedio"),
        "fotos_promedio": _f("fotos_promedio"),
        "dias_inventario_promedio": _f("dias_inventario_promedio"),
        "mix_habitaciones": [
            {"habitaciones": r["habitaciones"], "cantidad": int(r["total"])}
            for r in hab_rows
        ],
    }


def demand_stats(cur, ciudad: Optional[str] = None, zona: Optional[str] = None,
                 tipo_propiedad: Optional[str] = None, dias: int = 90) -> Dict[str, Any]:
    """
    Estadísticas de DEMANDA de una zona en los últimos `dias`.

    Dos fuentes:
    - `solicitudes_mercado`: búsquedas realizadas (criterios_extraidos JSONB).
    - `pedidos`: pedidos de compradores capturados en grupos de WhatsApp
      (texto libre + presupuesto_estimado).

    El matching por zona es por texto (ILIKE accent-insensitive) porque los
    pedidos no vienen estructurados; es una señal aproximada pero útil.
    """
    term = zona or ciudad or ""
    # Un patrón "%%" (término vacío) matchea todo el universo en LIKE, así que no
    # hace falta un caso especial: la propia zona filtra, o cuenta la demanda global.
    like = like_param(term)

    # Búsquedas (solicitudes_mercado) — matching sobre el JSONB casteado a texto.
    sol = fetch_one(cur, f"""
        SELECT
            COUNT(*) AS total,
            AVG(NULLIF((criterios_extraidos->>'precio_max'), '')::numeric) AS presupuesto_promedio
        FROM solicitudes_mercado
        WHERE activa = TRUE
          AND fecha_solicitud > NOW() - make_interval(days => %s)
          AND {accent_lower_raw('criterios_extraidos::text')} LIKE %s
    """, (dias, like)) or {}

    # Pedidos de compradores (texto libre + presupuesto parseado).
    ped = fetch_one(cur, f"""
        SELECT
            COUNT(*) AS total,
            AVG(presupuesto_estimado) FILTER (WHERE presupuesto_estimado IS NOT NULL) AS presupuesto_promedio,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY presupuesto_estimado)
                FILTER (WHERE presupuesto_estimado IS NOT NULL)                       AS presupuesto_mediana
        FROM pedidos
        WHERE fecha_captura > NOW() - make_interval(days => %s)
          AND {accent_lower_raw('texto_pedido')} LIKE %s
    """, (dias, like)) or {}

    total_busquedas = int(sol.get("total") or 0)
    total_pedidos = int(ped.get("total") or 0)

    return {
        "filtro": {"ciudad": ciudad, "zona": zona,
                   "tipo_propiedad": tipo_propiedad, "ventana_dias": dias},
        "busquedas": total_busquedas,
        "pedidos_compradores": total_pedidos,
        "demanda_total": total_busquedas + total_pedidos,
        "presupuesto_busquedas_promedio": (
            float(sol["presupuesto_promedio"]) if sol.get("presupuesto_promedio") else None
        ),
        "presupuesto_pedidos_promedio": (
            float(ped["presupuesto_promedio"]) if ped.get("presupuesto_promedio") else None
        ),
        "presupuesto_pedidos_mediana": (
            float(ped["presupuesto_mediana"]) if ped.get("presupuesto_mediana") else None
        ),
    }


def supply_demand_balance(cur, ciudad: Optional[str] = None, zona: Optional[str] = None,
                          tipo_propiedad: Optional[str] = None,
                          tipo_negocio: str = "Venta", dias: int = 90) -> Dict[str, Any]:
    """
    Balance oferta vs demanda de una zona. Devuelve el ratio y una clasificación
    caliente/equilibrado/frío pensada para que Claude la explique al agente.

    - ratio = demanda / oferta. > 1 => más compradores que inventario (caliente).
    """
    oferta = zone_stats(cur, ciudad, zona, tipo_propiedad, tipo_negocio)
    demanda = demand_stats(cur, ciudad, zona, tipo_propiedad, dias)

    inventario = oferta["inventario_activo"]
    demanda_total = demanda["demanda_total"]
    ratio = (demanda_total / inventario) if inventario > 0 else None

    if ratio is None:
        clasificacion = "sin_oferta"
    elif ratio >= 1.5:
        clasificacion = "caliente"        # mucha más demanda que inventario
    elif ratio >= 0.5:
        clasificacion = "equilibrado"
    else:
        clasificacion = "frio"            # sobreoferta

    return {
        "filtro": {"ciudad": ciudad, "zona": zona,
                   "tipo_propiedad": tipo_propiedad,
                   "tipo_negocio": tipo_negocio, "ventana_dias": dias},
        "oferta_inventario": inventario,
        "demanda_total": demanda_total,
        "ratio_demanda_oferta": round(ratio, 2) if ratio is not None else None,
        "clasificacion": clasificacion,
        "baja_confianza": oferta["baja_confianza"],
        "detalle_oferta": oferta,
        "detalle_demanda": demanda,
    }


def segmentos_precio(cur, ciudad: Optional[str], zona: Optional[str],
                     tipo_propiedad: str = "apartamento", dias: int = 120) -> List[Dict[str, Any]]:
    """
    Cruza OFERTA vs DEMANDA por rango de precio en una zona. Le dice al dueño en
    qué rango hay más compradores que inventario (hueco) o sobreoferta.
    """
    bandas = [
        ("Menos de $500M", 0, 500_000_000),
        ("$500M a $800M", 500_000_000, 800_000_000),
        ("$800M a $1.200M", 800_000_000, 1_200_000_000),
        ("$1.200M a $1.800M", 1_200_000_000, 1_800_000_000),
        ("$1.800M a $3.000M", 1_800_000_000, 3_000_000_000),
        ("Más de $3.000M", 3_000_000_000, None),
    ]
    term = zona or ciudad or ""
    like = like_param(term)
    ciudadn = accent_insensitive_expr("p.ciudad")
    zonan = accent_insensitive_expr("p.zona")
    tipo_like = like_param(tipo_propiedad)

    out = []
    for etq, lo, hi in bandas:
        of_cond = [f"p.activa", "p.tipo_negocio='Venta'", "p.precio > %s",
                   f"{accent_insensitive_expr('p.tipo_propiedad')} LIKE %s",
                   f"({ciudadn} LIKE %s OR {zonan} LIKE %s)"]
        of_params: List[Any] = [lo, tipo_like, like, like]
        if hi is not None:
            of_cond.append("p.precio <= %s"); of_params.append(hi)
        oferta = fetch_one(cur, f"SELECT COUNT(*) n FROM propiedades p WHERE {' AND '.join(of_cond)}", of_params)
        oferta = int((oferta or {}).get("n") or 0)

        dem_cond = ["fecha_captura > NOW() - make_interval(days => %s)",
                    f"{accent_lower_raw('texto_pedido')} LIKE %s",
                    "presupuesto_estimado > %s"]
        dem_params: List[Any] = [dias, like, lo]
        if hi is not None:
            dem_cond.append("presupuesto_estimado <= %s"); dem_params.append(hi)
        demanda = fetch_one(cur, f"SELECT COUNT(*) n FROM pedidos WHERE {' AND '.join(dem_cond)}", dem_params)
        demanda = int((demanda or {}).get("n") or 0)

        if oferta == 0 and demanda == 0:
            continue
        out.append({"rango": etq, "oferta": oferta, "demanda": demanda,
                    "hueco": demanda > oferta})
    return out


def donde_captar(cur, ciudad: Optional[str] = None, tipo_propiedad: str = "apartamento",
                 dias: int = 90, top: int = 8) -> Dict[str, Any]:
    """
    Mapa de oportunidad de CAPTACIÓN: cruza oferta activa vs demanda reciente por
    LUGAR (municipio o barrio) y devuelve dónde hay más compradores que
    inventario. Pensado para "¿dónde capto?".

    Nota de datos: en la base, municipios como Envigado/Sabaneta viven en
    `ciudad` y barrios como El Poblado/Laureles en `zona`. Por eso el "lugar" se
    mide contra AMBAS columnas, y la demanda (texto libre de pedidos) contra ese
    mismo término, para que oferta y demanda sean comparables.
    """
    ciudadn = accent_insensitive_expr("p.ciudad")
    zonan = accent_insensitive_expr("p.zona")

    # Candidatos: municipios (ciudad) y barrios (zona) con inventario relevante.
    lugares = fetch_all(cur, f"""
        SELECT key, MODE() WITHIN GROUP (ORDER BY label) AS label, SUM(c) AS c
        FROM (
            SELECT {ciudadn} AS key, p.ciudad AS label, COUNT(*) AS c
            FROM propiedades p
            WHERE p.activa AND p.tipo_negocio='Venta' AND p.ciudad IS NOT NULL AND p.ciudad<>''
              AND {accent_insensitive_expr('p.tipo_propiedad')} LIKE %s
            GROUP BY {ciudadn}, p.ciudad
            UNION ALL
            SELECT {zonan} AS key, p.zona AS label, COUNT(*) AS c
            FROM propiedades p
            WHERE p.activa AND p.tipo_negocio='Venta' AND p.zona IS NOT NULL AND p.zona<>''
              AND {accent_insensitive_expr('p.tipo_propiedad')} LIKE %s
            GROUP BY {zonan}, p.zona
        ) u
        GROUP BY key
        HAVING SUM(c) >= 10
        ORDER BY SUM(c) DESC
        LIMIT 25
    """, (like_param(tipo_propiedad), like_param(tipo_propiedad)))

    # Palabras que delatan una `zona` mal cargada (ej. "apartamento en el poblado").
    _BASURA = ("apartamento", "apartaestudio", "casa", "apto", "venta", "arriendo", "local", "oficina")

    tipo_like = like_param(tipo_propiedad)
    oportunidades = []
    for lg in lugares:
        key = (lg["key"] or "").strip()
        if not key or len(key) < 3:
            continue
        if any(b in key for b in _BASURA):
            continue
        term = f"%{key}%"
        # Oferta: propiedades cuyo barrio O municipio coincide con el lugar.
        of = fetch_one(cur, f"""
            SELECT COUNT(*) AS n FROM propiedades p
            WHERE p.activa AND p.tipo_negocio='Venta'
              AND {accent_insensitive_expr('p.tipo_propiedad')} LIKE %s
              AND ({ciudadn} LIKE %s OR {zonan} LIKE %s)
        """, (tipo_like, term, term)) or {}
        oferta = int(of.get("n") or 0)
        dem = fetch_one(cur, f"""
            SELECT COUNT(*) AS n FROM pedidos
            WHERE fecha_captura > NOW() - make_interval(days => %s)
              AND {accent_lower_raw('texto_pedido')} LIKE %s
        """, (dias, term)) or {}
        demanda = int(dem.get("n") or 0)
        if demanda == 0 or oferta == 0:
            continue
        ratio = demanda / oferta
        oportunidades.append({
            "lugar": (lg.get("label") or key).strip().title(),
            "oferta_activa": oferta, "demanda_90d": demanda,
            "compradores_por_inmueble": round(ratio, 1),
        })

    oportunidades.sort(key=lambda o: o["compradores_por_inmueble"], reverse=True)
    top_ops = oportunidades[:top]
    for o in top_ops:
        r = o["compradores_por_inmueble"]
        if r >= 3:
            o["lectura"] = f"Hueco fuerte: ~{r} compradores por cada inmueble en venta. Muy buena zona para captar."
        elif r >= 1:
            o["lectura"] = f"A favor del vendedor: más demanda que oferta (~{r} compradores por inmueble)."
        else:
            o["lectura"] = f"Saturado: sobra oferta ({o['oferta_activa']} activos, {o['demanda_90d']} buscando)."

    return {
        "filtro": {"tipo_propiedad": tipo_propiedad, "ventana_dias": dias},
        "nota": "La demanda son pedidos de compradores de los últimos %d días; la oferta es inventario activo hoy." % dias,
        "oportunidades": top_ops,
    }


# --------------------------------------------------------------------------
# Wrappers públicos (abren su propia conexión). Los usa el MCP directamente.
# --------------------------------------------------------------------------

def get_zone_stats(ciudad=None, zona=None, tipo_propiedad=None, tipo_negocio="Venta"):
    with get_db() as db:
        return zone_stats(db.cursor, ciudad, zona, tipo_propiedad, tipo_negocio)


def get_demand_stats(ciudad=None, zona=None, tipo_propiedad=None, dias=90):
    with get_db() as db:
        return demand_stats(db.cursor, ciudad, zona, tipo_propiedad, dias)


def get_supply_demand_balance(ciudad=None, zona=None, tipo_propiedad=None,
                              tipo_negocio="Venta", dias=90):
    with get_db() as db:
        return supply_demand_balance(db.cursor, ciudad, zona, tipo_propiedad, tipo_negocio, dias)


def donde_captar_public(ciudad=None, tipo_propiedad="apartamento", dias=90, top=8):
    with get_db() as db:
        return donde_captar(db.cursor, ciudad, tipo_propiedad, dias, top)
