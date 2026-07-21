"""
Servicio de propiedades.

Lectura y análisis de inmuebles individuales: obtener ficha, encontrar
comparables de mercado, comparar varios inmuebles lado a lado, estimar precio de
captación, y listar el inventario propio de un agente.

La búsqueda en lenguaje natural (`search`) reutiliza el `PropertySearchAgent`
existente vía import perezoso, para no arrastrar el monolito (ni sus deps de
Flask/IA) al importar este módulo.
"""

from typing import Any, Dict, List, Optional

from src.services.db import get_db, fetch_all, fetch_one
from src.services.textutils import (
    accent_insensitive_expr,
    like_param,
    split_image_urls,
    format_cop,
)

# Proyección canónica de una propiedad (columnas reales de `propiedades`).
_PROPERTY_COLUMNS = """
    p.id,
    p.codigo_propiedad,
    p.titulo,
    p.precio,
    p.precio_texto,
    p.tipo_propiedad,
    p.tipo_negocio,
    p.estado,
    p.ciudad,
    p.zona,
    p.direccion_completa,
    p.latitud,
    p.longitud,
    p.area_construida,
    p.habitaciones,
    p.banos,
    p.parqueaderos,
    p.estrato,
    p.piso,
    p.ano_construccion,
    p.administracion,
    p.amenidades_internas,
    p.amenidades_externas,
    p.total_amenidades,
    p.imagenes_urls,
    p.total_imagenes,
    p.imagen_principal,
    p.imagenes_hd_count,
    p.descripcion,
    p.descripcion_ai,
    p.descripcion_length,
    p.fuente,
    p.url,
    p.agente_captador_telefono,
    p.activa,
    p.fecha_creacion,
    p.fecha_actualizacion,
    EXTRACT(DAY FROM NOW() - p.fecha_creacion)::int AS dias_en_inventario,
    CASE WHEN p.area_construida > 0
         THEN p.precio / p.area_construida END       AS precio_m2
"""


def _row_to_property(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza una fila de propiedad a un dict serializable y estable."""
    if not row:
        return {}
    precio = row.get("precio")
    area = row.get("area_construida")
    return {
        "id": row["id"],
        "slug": row.get("codigo_propiedad"),
        "titulo": row.get("titulo"),
        "precio": int(precio) if precio is not None else None,
        "precio_legible": format_cop(precio),
        "tipo_propiedad": row.get("tipo_propiedad"),
        "tipo_negocio": row.get("tipo_negocio"),
        "ciudad": row.get("ciudad"),
        "zona": row.get("zona"),
        "direccion": row.get("direccion_completa"),
        "latitud": float(row["latitud"]) if row.get("latitud") is not None else None,
        "longitud": float(row["longitud"]) if row.get("longitud") is not None else None,
        "area_construida": float(area) if area is not None else None,
        "precio_m2": float(row["precio_m2"]) if row.get("precio_m2") is not None else None,
        "habitaciones": row.get("habitaciones"),
        "banos": row.get("banos"),
        "parqueaderos": row.get("parqueaderos"),
        "estrato": row.get("estrato"),
        "piso": row.get("piso"),
        "ano_construccion": row.get("ano_construccion"),
        "administracion": row.get("administracion"),
        "total_amenidades": row.get("total_amenidades"),
        "amenidades_internas": row.get("amenidades_internas"),
        "amenidades_externas": row.get("amenidades_externas"),
        "total_imagenes": row.get("total_imagenes"),
        "imagenes_hd": row.get("imagenes_hd_count"),
        "imagen_principal": row.get("imagen_principal"),
        "imagenes_urls": split_image_urls(row.get("imagenes_urls")),
        "descripcion": row.get("descripcion"),
        "descripcion_ai": row.get("descripcion_ai"),
        "descripcion_length": row.get("descripcion_length"),
        "fuente": row.get("fuente"),
        "url": row.get("url"),
        "owner_phone": row.get("agente_captador_telefono"),
        "activa": row.get("activa"),
        "dias_en_inventario": row.get("dias_en_inventario"),
    }


def get_property(cur, id_or_slug) -> Optional[Dict[str, Any]]:
    """Obtiene una propiedad por id numérico o por slug (`codigo_propiedad`)."""
    id_or_slug = str(id_or_slug).strip()
    if id_or_slug.isdigit():
        where, param = "p.id = %s", int(id_or_slug)
    else:
        where, param = "p.codigo_propiedad = %s", id_or_slug
    row = fetch_one(cur, f"SELECT {_PROPERTY_COLUMNS} FROM propiedades p WHERE {where}", (param,))
    return _row_to_property(row) if row else None


def find_comparables(cur, property_id, limit: int = 20,
                     incluir_inactivas: bool = False) -> Dict[str, Any]:
    """
    Encuentra el set de comparables de mercado para una propiedad:
    misma ciudad + tipo + tipo_negocio, habitaciones ±1, área ±30%.

    Si la misma zona no da suficientes comps, relaja de zona -> ciudad, y lo
    reporta en `nivel_comparacion` para que el diagnóstico sea honesto.
    """
    base = get_property(cur, property_id)
    if not base:
        return {"error": f"Propiedad {property_id} no encontrada"}

    def _query(usar_zona: bool) -> List[Dict[str, Any]]:
        conditions = [
            "p.id != %s",
            "p.tipo_negocio = %s",
            "p.precio IS NOT NULL AND p.precio > 0",
        ]
        params: List[Any] = [base["id"], base.get("tipo_negocio") or "Venta"]

        if not incluir_inactivas:
            conditions.append("p.activa = TRUE")
        if base.get("ciudad"):
            conditions.append(f"{accent_insensitive_expr('p.ciudad')} LIKE %s")
            params.append(like_param(base["ciudad"]))
        if usar_zona and base.get("zona"):
            conditions.append(f"{accent_insensitive_expr('p.zona')} LIKE %s")
            params.append(like_param(base["zona"]))
        if base.get("tipo_propiedad"):
            conditions.append(f"{accent_insensitive_expr('p.tipo_propiedad')} LIKE %s")
            params.append(like_param(base["tipo_propiedad"]))
        if base.get("habitaciones") is not None:
            conditions.append("(p.habitaciones IS NULL OR p.habitaciones BETWEEN %s AND %s)")
            params.extend([base["habitaciones"] - 1, base["habitaciones"] + 1])
        if base.get("area_construida"):
            lo = base["area_construida"] * 0.70
            hi = base["area_construida"] * 1.30
            conditions.append("(p.area_construida IS NULL OR p.area_construida BETWEEN %s AND %s)")
            params.extend([lo, hi])

        where = " AND ".join(conditions)
        params.append(limit)
        rows = fetch_all(cur, f"""
            SELECT {_PROPERTY_COLUMNS}
            FROM propiedades p
            WHERE {where}
            ORDER BY p.precio
            LIMIT %s
        """, params)
        return [_row_to_property(r) for r in rows]

    comps = _query(usar_zona=True)
    nivel = "zona"
    if len(comps) < 3 and base.get("zona"):
        # Muy pocos comps en la zona -> relajar a ciudad.
        comps = _query(usar_zona=False)
        nivel = "ciudad"

    return {
        "propiedad_base": base,
        "nivel_comparacion": nivel,
        "total_comparables": len(comps),
        "comparables": comps,
    }


def compare_properties(cur, property_ids: List[Any]) -> Dict[str, Any]:
    """
    Comparativa lado a lado de 2+ inmuebles concretos. Devuelve la matriz de
    atributos y un veredicto simple de mejor valor (menor precio/m²) para que
    Claude lo explique.
    """
    if not property_ids or len(property_ids) < 2:
        return {"error": "Se requieren al menos 2 propiedades para comparar"}

    props = []
    for pid in property_ids:
        p = get_property(cur, pid)
        if p:
            props.append(p)

    if len(props) < 2:
        return {"error": "No se encontraron suficientes propiedades válidas para comparar"}

    # Métricas comparables clave por inmueble.
    def _metric(p):
        return {
            "id": p["id"], "slug": p["slug"], "titulo": p["titulo"],
            "ciudad": p["ciudad"], "zona": p["zona"],
            "precio": p["precio"], "precio_legible": p["precio_legible"],
            "area_construida": p["area_construida"], "precio_m2": p["precio_m2"],
            "habitaciones": p["habitaciones"], "banos": p["banos"],
            "parqueaderos": p["parqueaderos"], "estrato": p["estrato"],
            "total_amenidades": p["total_amenidades"],
            "total_imagenes": p["total_imagenes"],
            "dias_en_inventario": p["dias_en_inventario"],
        }

    filas = [_metric(p) for p in props]

    # Veredictos: mejor precio/m², más barata, más amplia.
    con_m2 = [f for f in filas if f["precio_m2"]]
    mejor_valor = min(con_m2, key=lambda f: f["precio_m2"])["id"] if con_m2 else None
    con_precio = [f for f in filas if f["precio"]]
    mas_economica = min(con_precio, key=lambda f: f["precio"])["id"] if con_precio else None
    con_area = [f for f in filas if f["area_construida"]]
    mas_amplia = max(con_area, key=lambda f: f["area_construida"])["id"] if con_area else None

    return {
        "total": len(filas),
        "comparativa": filas,
        "veredicto": {
            "mejor_valor_precio_m2": mejor_valor,
            "mas_economica": mas_economica,
            "mas_amplia": mas_amplia,
        },
    }


def estimate_price(cur, ciudad: Optional[str] = None, zona: Optional[str] = None,
                   tipo_propiedad: Optional[str] = None, area_construida: Optional[float] = None,
                   habitaciones: Optional[int] = None,
                   tipo_negocio: str = "Venta") -> Dict[str, Any]:
    """
    Estima un precio de captación sugerido a partir de comparables de la zona,
    usando el precio/m² mediano del segmento y el área objetivo.
    """
    conditions = [
        "p.activa = TRUE",
        "p.precio IS NOT NULL AND p.precio > 0",
        "p.area_construida > 0",
        "p.tipo_negocio = %s",
    ]
    params: List[Any] = [tipo_negocio]
    if ciudad:
        conditions.append(f"{accent_insensitive_expr('p.ciudad')} LIKE %s")
        params.append(like_param(ciudad))
    if zona:
        conditions.append(f"{accent_insensitive_expr('p.zona')} LIKE %s")
        params.append(like_param(zona))
    if tipo_propiedad:
        conditions.append(f"{accent_insensitive_expr('p.tipo_propiedad')} LIKE %s")
        params.append(like_param(tipo_propiedad))
    if habitaciones is not None:
        conditions.append("(p.habitaciones IS NULL OR p.habitaciones BETWEEN %s AND %s)")
        params.extend([habitaciones - 1, habitaciones + 1])

    where = " AND ".join(conditions)
    agg = fetch_one(cur, f"""
        SELECT
            COUNT(*) AS muestra,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY p.precio / p.area_construida) AS m2_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY p.precio / p.area_construida) AS m2_mediana,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY p.precio / p.area_construida) AS m2_p75
        FROM propiedades p
        WHERE {where}
    """, params) or {}

    muestra = int(agg.get("muestra") or 0)
    m2_med = float(agg["m2_mediana"]) if agg.get("m2_mediana") else None

    resultado = {
        "filtro": {"ciudad": ciudad, "zona": zona, "tipo_propiedad": tipo_propiedad,
                   "area_construida": area_construida, "habitaciones": habitaciones,
                   "tipo_negocio": tipo_negocio},
        "muestra_comparables": muestra,
        "baja_confianza": muestra < 5,
        "precio_m2_mediana": m2_med,
        "precio_m2_p25": float(agg["m2_p25"]) if agg.get("m2_p25") else None,
        "precio_m2_p75": float(agg["m2_p75"]) if agg.get("m2_p75") else None,
    }
    if m2_med and area_construida:
        estimado = m2_med * area_construida
        resultado["precio_estimado"] = round(estimado)
        resultado["precio_estimado_legible"] = format_cop(estimado)
        if agg.get("m2_p25") and agg.get("m2_p75"):
            resultado["rango_estimado"] = {
                "bajo": round(float(agg["m2_p25"]) * area_construida),
                "alto": round(float(agg["m2_p75"]) * area_construida),
            }
    return resultado


def list_my_properties(cur, telefono_10: str, limit: int = 50) -> Dict[str, Any]:
    """
    Lista el inventario captado por un agente (match por últimos 10 dígitos del
    teléfono, igual que el resto del sistema).
    """
    if not telefono_10:
        return {"total": 0, "propiedades": [], "sin_scope": True}

    rows = fetch_all(cur, f"""
        SELECT {_PROPERTY_COLUMNS}
        FROM propiedades p
        WHERE p.agente_captador_telefono IS NOT NULL
          AND RIGHT(REGEXP_REPLACE(p.agente_captador_telefono, '[^0-9]', '', 'g'), 10) = %s
        ORDER BY p.activa DESC, p.fecha_creacion DESC
        LIMIT %s
    """, (telefono_10, limit))
    props = [_row_to_property(r) for r in rows]
    activas = [p for p in props if p["activa"]]
    return {
        "total": len(props),
        "activas": len(activas),
        "propiedades": props,
    }


# --------------------------------------------------------------------------
# Búsqueda en lenguaje natural (reusa el PropertySearchAgent existente).
# --------------------------------------------------------------------------

# Cache del agente para no reinstanciar (evita el costo de _detect_available_model).
_search_agent = None


def _get_search_agent():
    global _search_agent
    if _search_agent is None:
        # Import perezoso: no arrastrar el monolito ni sus deps al importar este
        # módulo. Modelo fijado -> se salta la llamada de detección por init.
        from src.core.search_agent import PropertySearchAgent, MODEL
        _search_agent = PropertySearchAgent(model=MODEL)
    return _search_agent


def search(query: str, limit: int = 10, telefono: Optional[str] = None) -> Dict[str, Any]:
    """
    Búsqueda en lenguaje natural sobre el inventario, reutilizando el
    `PropertySearchAgent` (extracción de criterios con Claude + SQL + ranking +
    vector). Devuelve una forma compacta y estable para el MCP.
    """
    agent = _get_search_agent()
    resp = agent.search(query=query, limit=limit, sender=telefono) or {}

    # PropertySearchAgent.search devuelve las filas bajo la clave 'results'
    # (con 'total_found' y 'criteria'). Antes se leía 'resultados'/'properties'
    # (claves inexistentes) => siempre 0 resultados.
    resultados = resp.get("results") or []
    propiedades = []
    for r in resultados:
        precio = r.get("precio")
        area = r.get("area_construida")
        precio_m2 = (float(precio) / float(area)) if precio and area else None
        propiedades.append({
            "id": r.get("id"),
            "slug": r.get("codigo_propiedad") or r.get("slug"),
            "titulo": r.get("titulo") or r.get("title"),
            "precio": int(precio) if precio not in (None, "") else None,
            "precio_legible": format_cop(precio),
            "tipo_propiedad": r.get("tipo_propiedad"),
            "ciudad": r.get("ciudad"),
            "zona": r.get("zona"),
            "habitaciones": r.get("habitaciones"),
            "banos": r.get("banos"),
            "area_construida": float(area) if area else None,
            "precio_m2": precio_m2,
            "url": r.get("url"),
            "score": r.get("match_score") or r.get("alignment_score"),
        })

    return {
        "query": query,
        "criterios_extraidos": resp.get("criteria"),
        "total": resp.get("total_found", len(propiedades)),
        "propiedades": propiedades,
        # Si el buscador no encontró nada, pasa el motivo/sugerencias para que
        # Claude lo comunique como "sin coincidencias", no como un error.
        "sin_resultados": len(propiedades) == 0,
        "mensaje": resp.get("mensaje_usuario"),
        "sugerencias": resp.get("sugerencias"),
    }


# --------------------------------------------------------------------------
# Wrappers públicos.
# --------------------------------------------------------------------------

def get_property_public(id_or_slug):
    with get_db() as db:
        return get_property(db.cursor, id_or_slug)


def get_comparables_public(property_id, limit=20):
    with get_db() as db:
        return find_comparables(db.cursor, property_id, limit)


def compare_public(property_ids):
    with get_db() as db:
        return compare_properties(db.cursor, property_ids)


def estimate_price_public(**kwargs):
    with get_db() as db:
        return estimate_price(db.cursor, **kwargs)


def list_my_properties_public(telefono_10, limit=50):
    with get_db() as db:
        return list_my_properties(db.cursor, telefono_10, limit)
