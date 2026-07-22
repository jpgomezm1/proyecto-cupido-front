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


def capacidad_de_compra(cur, ingreso_mensual: float, cuota_inicial: float = 0,
                        tasa_mensual: float = 0.011, plazo_anos: int = 20,
                        max_cuota_pct: float = 0.30,
                        ciudad: Optional[str] = None, zona: Optional[str] = None,
                        tipo_propiedad: Optional[str] = None) -> Dict[str, Any]:
    """
    Estima para cuánto le alcanza a un comprador (matemática de crédito
    hipotecario colombiano) y, si se dan filtros de zona, cuántas propiedades
    entran en ese techo.

    - La cuota mensual máxima suele ser ~30% del ingreso.
    - Tasa por defecto ~1.1% mensual (referencia; ajústala si el banco da otra).
    - Con eso se despeja el monto máximo del crédito y se suma la cuota inicial.
    """
    ingreso_mensual = float(ingreso_mensual or 0)
    cuota_inicial = float(cuota_inicial or 0)
    if ingreso_mensual <= 0:
        return {"error": "Ingresa el ingreso mensual del comprador"}

    cuota_max = ingreso_mensual * max_cuota_pct
    n = plazo_anos * 12
    i = tasa_mensual
    # Valor presente de una anualidad: credito = cuota * (1-(1+i)^-n)/i
    if i > 0:
        credito_max = cuota_max * (1 - (1 + i) ** (-n)) / i
    else:
        credito_max = cuota_max * n
    precio_max = round(credito_max + cuota_inicial)

    tasa_anual = round(((1 + tasa_mensual) ** 12 - 1) * 100, 1)
    resultado = {
        "supuestos": {
            "ingreso_mensual": round(ingreso_mensual),
            "cuota_inicial": round(cuota_inicial),
            "cuota_mensual_max": round(cuota_max),
            "tasa_mensual": tasa_mensual,
            "tasa_anual_efectiva_aprox": tasa_anual,
            "plazo_anos": plazo_anos,
            "regla_cuota": f"{int(max_cuota_pct*100)}% del ingreso",
        },
        "credito_max": round(credito_max),
        "precio_max": precio_max,
        "precio_max_legible": format_cop(precio_max),
        # Nota prominente: el techo depende MUCHO de la tasa. Que Claude siempre
        # la mencione y aclare que es un supuesto ajustable.
        "supuesto_clave": (f"Calculado con tasa ~{tasa_anual}% anual ({tasa_mensual*100:.1f}% mensual) "
                           f"a {plazo_anos} años. Si el banco del comprador da otra tasa, el techo cambia; "
                           f"confírmala con su preaprobado."),
    }

    # Si hay filtros, cuántas propiedades entran en el techo.
    if any([ciudad, zona, tipo_propiedad]):
        conditions = ["p.activa = TRUE", "p.precio > 0", "p.precio <= %s", "p.tipo_negocio = 'Venta'"]
        params: List[Any] = [precio_max]
        if ciudad:
            conditions.append(f"{accent_insensitive_expr('p.ciudad')} LIKE %s"); params.append(like_param(ciudad))
        if zona:
            conditions.append(f"{accent_insensitive_expr('p.zona')} LIKE %s"); params.append(like_param(zona))
        if tipo_propiedad:
            conditions.append(f"{accent_insensitive_expr('p.tipo_propiedad')} LIKE %s"); params.append(like_param(tipo_propiedad))
        where = " AND ".join(conditions)
        cnt = fetch_one(cur, f"SELECT COUNT(*) AS n FROM propiedades p WHERE {where}", params) or {}
        resultado["opciones_dentro_del_techo"] = int(cnt.get("n") or 0)

    return resultado


# Estimaciones por estrato cuando faltan datos (servicios públicos mensuales y
# administración de respaldo). Cifras de referencia para vivienda familiar en
# el Valle de Aburrá; se marcan siempre como "estimado".
_SERVICIOS_POR_ESTRATO = {1: 160_000, 2: 200_000, 3: 280_000, 4: 380_000, 5: 480_000, 6: 650_000}
_ADMIN_FALLBACK_ESTRATO = {3: 300_000, 4: 450_000, 5: 650_000, 6: 1_000_000}


def _cuota_credito(monto: float, tasa_mensual: float, plazo_anos: int) -> float:
    """Cuota fija mensual de un crédito (sistema francés)."""
    n = plazo_anos * 12
    i = tasa_mensual
    if monto <= 0:
        return 0.0
    if i <= 0:
        return monto / n
    return monto * i / (1 - (1 + i) ** (-n))


def costo_total_mensual(cur, property_id, cuota_inicial: Optional[float] = None,
                        tasa_mensual: float = 0.011, plazo_anos: int = 20) -> Dict[str, Any]:
    """
    Costo mensual REAL de vivir en una propiedad: administración + servicios
    (estimados por estrato) + predial mensualizado + (opcional) cuota de crédito.

    Un apto "barato" con administración alta no es barato. Esta tool arma el
    número que el comprador colombiano de verdad pregunta.
    """
    p = get_property(cur, property_id)
    if not p:
        return {"error": f"Propiedad {property_id} no encontrada"}

    estrato = p.get("estrato")
    precio = p.get("precio") or 0

    # Administración: usar el dato si es plausible; si no, estimar por estrato.
    admin_raw = p.get("administracion")
    admin_estimada = False
    if admin_raw and 20_000 <= admin_raw <= 5_000_000:
        admin = int(admin_raw)
    else:
        admin = _ADMIN_FALLBACK_ESTRATO.get(estrato, 500_000)
        admin_estimada = True

    # Servicios públicos: estimado por estrato.
    servicios = _SERVICIOS_POR_ESTRATO.get(estrato, 350_000)

    # Predial mensualizado: estimación conservadora (~0,35% anual del valor comercial).
    predial_mensual = round(precio * 0.0035 / 12) if precio else 0

    componentes = {
        "administracion": admin,
        "administracion_estimada": admin_estimada,
        "servicios_estimados": servicios,
        "predial_mensual_estimado": predial_mensual,
    }

    total_sin_credito = admin + servicios + predial_mensual
    resultado = {
        "propiedad": {"id": p["id"], "slug": p["slug"], "titulo": p["titulo"],
                      "precio_legible": p["precio_legible"], "estrato": estrato, "zona": p["zona"]},
        "componentes": componentes,
        "costo_mensual_sin_credito": total_sin_credito,
        "costo_mensual_sin_credito_legible": format_cop(total_sin_credito),
        "nota": ("Servicios y predial son estimados por estrato/valor; la administración "
                 "es real cuando el dato existe y es plausible."),
    }

    if cuota_inicial is not None:
        monto_credito = max(precio - float(cuota_inicial), 0)
        cuota = round(_cuota_credito(monto_credito, tasa_mensual, plazo_anos))
        total_con_credito = total_sin_credito + cuota
        resultado["credito"] = {
            "cuota_inicial": round(float(cuota_inicial)),
            "monto_financiado": round(monto_credito),
            "cuota_mensual": cuota,
            "tasa_mensual": tasa_mensual, "plazo_anos": plazo_anos,
        }
        resultado["costo_mensual_total"] = total_con_credito
        resultado["costo_mensual_total_legible"] = format_cop(total_con_credito)

    return resultado


# Grupos de amenidades con sus variantes tal como aparecen en los listings
# colombianos. Permite que "zona de niños" matchee "Parque infantil", etc.
_AMENIDAD_SINONIMOS = {
    "piscina": ["piscina"],
    "gimnasio": ["gimnasio", "gym"],
    "zona_ninos": ["infantil", "juegos infantiles", "parque infantil", "zona infantil",
                   "ludoteca", "zona de ninos", "ninos", "juegos"],
    "seguridad": ["porteria", "vigilancia", "seguridad", "circuito cerrado", "cctv",
                  "recepcion", "guarda", "monitoreo"],
    "ascensor": ["ascensor"],
    "salon_social": ["salon comunal", "salon social", "salon de eventos"],
    "bbq": ["bbq", "asados", "zona humeda"],
    "turco_sauna": ["turco", "sauna", "jacuzzi", "vapor"],
    "mascotas": ["admite mascotas", "pet friendly", "mascotas"],
    "parqueadero_visitantes": ["parqueadero visitantes", "garaje visitantes", "visitantes"],
}


def _amenidad_presente(deseada: str, texto_norm: str) -> bool:
    """
    ¿La amenidad que pide el comprador está en el texto de la propiedad?
    Reconoce sinónimos ("zona de niños" ≈ "parque infantil"). Si no cae en
    ningún grupo conocido, hace match literal.
    """
    from src.services.textutils import strip_accents
    d = strip_accents(deseada).lower().strip()
    # Buscar a qué grupo pertenece lo que pidió el comprador.
    for variantes in _AMENIDAD_SINONIMOS.values():
        if any(v in d or d in v for v in variantes):
            return any(v in texto_norm for v in variantes)
    # Amenidad desconocida: match literal.
    return d in texto_norm


def match_comprador(cur, property_id, presupuesto_max: Optional[float] = None,
                    habitaciones_min: Optional[int] = None,
                    parqueaderos_min: Optional[int] = None,
                    estrato_min: Optional[int] = None,
                    area_min: Optional[float] = None,
                    amenidades: Optional[List[str]] = None,
                    zonas: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Puntúa qué tan bien le encaja una propiedad a un perfil de comprador (el que
    Claude extrae de una conversación/transcripción), con razones por criterio.
    Devuelve un score 0-100 y un veredicto.
    """
    p = get_property(cur, property_id)
    if not p:
        return {"error": f"Propiedad {property_id} no encontrada"}

    criterios = []          # (etiqueta, cumple(bool|None), peso, detalle)
    def add(etiqueta, cumple, peso, detalle):
        criterios.append({"criterio": etiqueta, "cumple": cumple, "peso": peso, "detalle": detalle})

    # Presupuesto (crítico).
    if presupuesto_max:
        precio = p.get("precio") or 0
        if precio <= presupuesto_max:
            add("presupuesto", True, 30, f"{p['precio_legible']} dentro del techo")
        elif precio <= presupuesto_max * 1.1:
            add("presupuesto", None, 30, f"{p['precio_legible']} apenas por encima (~10%), negociable")
        else:
            add("presupuesto", False, 30, f"{p['precio_legible']} se pasa del presupuesto")

    if habitaciones_min:
        h = p.get("habitaciones")
        add("habitaciones", (h is not None and h >= habitaciones_min), 20,
            f"tiene {h} (pedía {habitaciones_min}+)")

    if parqueaderos_min:
        pk = p.get("parqueaderos") or 0
        add("parqueaderos", pk >= parqueaderos_min, 15, f"tiene {pk} (pedía {parqueaderos_min}+)")

    if estrato_min:
        e = p.get("estrato")
        add("estrato", (e is not None and e >= estrato_min), 10, f"estrato {e} (pedía {estrato_min}+)")

    if area_min:
        a = p.get("area_construida") or 0
        add("area", a >= area_min, 10, f"{a:.0f} m² (pedía {area_min:.0f}+)")

    if amenidades:
        texto = f"{p.get('amenidades_internas') or ''} {p.get('amenidades_externas') or ''} {p.get('descripcion') or ''}"
        from src.services.textutils import strip_accents
        texto_n = strip_accents(texto).lower()
        # Match con sinónimos ("zona de niños" ≈ "parque infantil").
        encontradas = [a for a in amenidades if _amenidad_presente(a, texto_n)]
        faltantes = [a for a in amenidades if a not in encontradas]
        cumple = len(encontradas) == len(amenidades)
        add("amenidades", cumple if amenidades else None, 10,
            f"tiene {encontradas or 'ninguna'}" + (f", faltaría {faltantes}" if faltantes else ""))

    if zonas:
        from src.services.textutils import strip_accents
        pzona = strip_accents(f"{p.get('zona') or ''} {p.get('ciudad') or ''}").lower()
        cumple = any(strip_accents(z).lower() in pzona for z in zonas)
        add("zona", cumple, 15, f"está en {p.get('zona')} / {p.get('ciudad')}")

    # Score ponderado: cumple=1, parcial(None con peso)=0.5, no=0.
    peso_total = sum(c["peso"] for c in criterios) or 1
    ganado = 0
    for c in criterios:
        if c["cumple"] is True:
            ganado += c["peso"]
        elif c["cumple"] is None:
            ganado += c["peso"] * 0.5
    score = round(ganado / peso_total * 100)

    # Deal-breakers duros: presupuesto o habitaciones que NO cumplen.
    rompedores = [c["criterio"] for c in criterios
                  if c["cumple"] is False and c["criterio"] in ("presupuesto", "habitaciones")]

    if rompedores:
        veredicto = "no_encaja"
    elif score >= 80:
        veredicto = "encaja_bien"
    elif score >= 55:
        veredicto = "encaja_parcial"
    else:
        veredicto = "flojo"

    return {
        "propiedad": {"id": p["id"], "slug": p["slug"], "titulo": p["titulo"],
                      "precio_legible": p["precio_legible"], "zona": p["zona"]},
        "score": score,
        "veredicto": veredicto,
        "deal_breakers": rompedores,
        "criterios": criterios,
    }


def ficha_venta(cur, property_id, perfil: Optional[str] = None) -> Dict[str, Any]:
    """
    Devuelve los puntos de venta estructurados de una propiedad para que Claude
    redacte una ficha/pitch de WhatsApp: precio, posición de precio/m² vs la
    zona (barato/caro), destacados y diferenciadores. Si se pasa un `perfil`
    (texto libre del comprador), se incluye para que el pitch se personalice.
    """
    p = get_property(cur, property_id)
    if not p:
        return {"error": f"Propiedad {property_id} no encontrada"}

    # Posición de precio/m² vs la mediana de su zona.
    from src.services.market_service import zone_stats
    z = zone_stats(cur, p.get("ciudad"), p.get("zona"), p.get("tipo_propiedad"),
                   p.get("tipo_negocio") or "Venta")
    m2 = p.get("precio_m2")
    m2_zona = z.get("precio_m2_mediana")
    posicion = None
    if m2 and m2_zona:
        dif = (m2 - m2_zona) / m2_zona
        if dif <= -0.12:
            posicion = "barato"
        elif dif >= 0.12:
            posicion = "caro"
        else:
            posicion = "en_precio"

    destacados = []
    if p.get("area_construida"):
        destacados.append(f"{p['area_construida']:.0f} m²")
    if p.get("habitaciones"):
        destacados.append(f"{p['habitaciones']} habitaciones")
    if p.get("banos"):
        destacados.append(f"{p['banos']} baños")
    if p.get("parqueaderos"):
        destacados.append(f"{p['parqueaderos']} parqueaderos")
    if p.get("estrato"):
        destacados.append(f"estrato {p['estrato']}")
    if p.get("total_amenidades"):
        destacados.append(f"{p['total_amenidades']} amenidades")

    gancho_m2 = None
    if posicion == "barato" and m2 and m2_zona:
        gancho_m2 = (f"{format_cop(m2)}/m² cuando la zona está en {format_cop(m2_zona)}/m²")

    return {
        "propiedad": {
            "id": p["id"], "slug": p["slug"], "titulo": p["titulo"],
            "precio_legible": p["precio_legible"], "ciudad": p["ciudad"], "zona": p["zona"],
            "direccion": p.get("direccion"),
            "url": p.get("url"), "imagen_principal": p.get("imagen_principal"),
            "total_imagenes": p.get("total_imagenes"),
        },
        "posicion_precio": posicion,             # barato | en_precio | caro
        "gancho_precio_m2": gancho_m2,           # frase lista si es barato
        "destacados": destacados,
        "amenidades_internas": p.get("amenidades_internas"),
        "amenidades_externas": p.get("amenidades_externas"),
        "descripcion_actual": p.get("descripcion_ai") or p.get("descripcion"),
        "perfil_comprador": perfil,
        "instruccion": ("Redacta un mensaje corto de WhatsApp, cálido y directo, para vender esta "
                        "propiedad. Resalta el gancho de precio si existe y adapta al perfil del "
                        "comprador si se dio. Cierra invitando a agendar visita."),
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


def capacidad_de_compra_public(**kwargs):
    with get_db() as db:
        return capacidad_de_compra(db.cursor, **kwargs)


def ficha_venta_public(property_id, perfil=None):
    with get_db() as db:
        return ficha_venta(db.cursor, property_id, perfil)


def costo_total_mensual_public(property_id, cuota_inicial=None, tasa_mensual=0.011, plazo_anos=20):
    with get_db() as db:
        return costo_total_mensual(db.cursor, property_id, cuota_inicial, tasa_mensual, plazo_anos)


def match_comprador_public(property_id, **kwargs):
    with get_db() as db:
        return match_comprador(db.cursor, property_id, **kwargs)
