"""
Servicio de diagnóstico: "¿por qué no rota mi propiedad?".

Combina la ficha del inmueble, su set de comparables, las estadísticas de la
zona y la demanda real para producir un diagnóstico estructurado con hallazgos
priorizados y acciones concretas. Pensado para que Claude lo traduzca a una
recomendación clara para el agente.

También expone `find_buyers_for_property`: compradores activos (pedidos) que
podrían encajar con el inmueble.
"""

from statistics import median
from typing import Any, Dict, List, Optional

from src.services.db import get_db, fetch_all
from src.services.textutils import accent_lower_raw, like_param, format_cop
from src.services.property_service import get_property, find_comparables
from src.services.market_service import zone_stats, demand_stats


def _percentile_of(values: List[float], target: float) -> Optional[float]:
    """Fracción [0-1] de `values` <= target. None si no hay datos."""
    vals = [v for v in values if v is not None]
    if not vals or target is None:
        return None
    return sum(1 for v in vals if v <= target) / len(vals)


def _median_or_none(values: List[Any]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    return median(vals) if vals else None


def find_buyers_for_property(cur, property_id, dias: int = 120,
                             limit: int = 15) -> Dict[str, Any]:
    """
    Compradores activos que podrían encajar con el inmueble.

    Heurística: pedidos recientes cuyo texto menciona la zona/ciudad del
    inmueble y cuyo presupuesto (si se conoce) alcanza al menos el 85% del
    precio. Los pedidos sin presupuesto se incluyen (no se descartan a ciegas).
    """
    base = get_property(cur, property_id)
    if not base:
        return {"error": f"Propiedad {property_id} no encontrada"}

    term = base.get("zona") or base.get("ciudad") or ""
    like = like_param(term)
    precio = base.get("precio")
    tipo = (base.get("tipo_propiedad") or "").lower()
    es_apto = any(k in tipo for k in ("apart", "apto", "estudio"))

    texto_norm = accent_lower_raw("texto_pedido")
    conditions = [
        "fecha_captura > NOW() - make_interval(days => %s)",
        f"{texto_norm} LIKE %s",
    ]
    params: List[Any] = [dias, like]

    # Banda de presupuesto: descarta al comprador de $8.000 millones que no va a
    # comprar un apto de $850 (antes solo había piso, sin techo).
    if precio:
        conditions.append("(presupuesto_estimado IS NULL OR presupuesto_estimado BETWEEN %s AND %s)")
        params.extend([int(precio * 0.85), int(precio * 1.8)])

    # Excluir tipos de inmueble claramente distintos (el pedido busca otra cosa).
    tipos_excluir = ["lote", "finca", "bodega", "local comercial", "oficina", "penthouse"]
    if es_apto:
        tipos_excluir.append("casa campestre")
    for t in tipos_excluir:
        conditions.append(f"{texto_norm} NOT LIKE %s")
        params.append(f"%{t}%")

    where = " AND ".join(conditions)
    params.append(limit)
    # Ordenar por CERCANÍA de presupuesto al precio (los más relevantes primero),
    # no por el presupuesto más alto.
    orden = ("ABS(COALESCE(presupuesto_estimado, %s) - %s) ASC, fecha_captura DESC"
             if precio else "fecha_captura DESC")
    if precio:
        params = params[:-1] + [int(precio), int(precio), limit]
    rows = fetch_all(cur, f"""
        SELECT id, agente_telefono, agente_nombre, texto_pedido,
               presupuesto_estimado, fecha_captura, grupo_id, canal
        FROM pedidos
        WHERE {where}
        ORDER BY {orden}
        LIMIT %s
    """, params)

    compradores = [{
        "pedido_id": r["id"],
        "agente_telefono": r["agente_telefono"],
        "agente_nombre": r["agente_nombre"],
        "texto_pedido": r["texto_pedido"],
        "presupuesto_estimado": int(r["presupuesto_estimado"]) if r["presupuesto_estimado"] else None,
        "presupuesto_legible": format_cop(r["presupuesto_estimado"]) if r["presupuesto_estimado"] else None,
        "fecha": r["fecha_captura"].isoformat() if r.get("fecha_captura") else None,
        "canal": r.get("canal"),
    } for r in rows]

    return {
        "propiedad_id": base["id"],
        "zona_buscada": term,
        "total_compradores": len(compradores),
        "compradores": compradores,
    }


def diagnose_property(cur, property_id) -> Dict[str, Any]:
    """
    Diagnóstico completo de por qué un inmueble no rota, con hallazgos
    priorizados (severidad alta/media/baja/ok) y acciones recomendadas.
    """
    comp_data = find_comparables(cur, property_id, limit=40)
    if "error" in comp_data:
        return comp_data

    base = comp_data["propiedad_base"]
    comps = comp_data["comparables"]

    zona = zone_stats(cur, base.get("ciudad"), base.get("zona"),
                      base.get("tipo_propiedad"), base.get("tipo_negocio") or "Venta")
    demanda = demand_stats(cur, base.get("ciudad"), base.get("zona"),
                           base.get("tipo_propiedad"))
    buyers = find_buyers_for_property(cur, property_id)

    # --- Métricas comparativas contra el set de comps ---
    precios = [c["precio"] for c in comps]
    m2s = [c["precio_m2"] for c in comps]
    fotos = [c["total_imagenes"] for c in comps]
    desc_lens = [c["descripcion_length"] for c in comps]
    amenidades = [c["total_amenidades"] for c in comps]
    dias_list = [c["dias_en_inventario"] for c in comps]

    pct_precio = _percentile_of(precios, base.get("precio"))
    pct_m2 = _percentile_of(m2s, base.get("precio_m2"))
    fotos_med = _median_or_none(fotos)
    desc_med = _median_or_none(desc_lens)
    amen_med = _median_or_none(amenidades)
    dias_med = _median_or_none(dias_list)

    hallazgos: List[Dict[str, Any]] = []

    def add(codigo, severidad, titulo, detalle, accion=None):
        hallazgos.append({"codigo": codigo, "severidad": severidad,
                          "titulo": titulo, "detalle": detalle, "accion": accion})

    # 1) Precio vs mercado (percentil de precio/m², el más justo porque normaliza área)
    if pct_m2 is not None and len(comps) >= 3:
        pct = round(pct_m2 * 100)
        if pct_m2 >= 0.80:
            add("precio_alto", "alta",
                f"Precio/m² en el percentil {pct} de la zona",
                f"Tu precio/m² ({format_cop(base.get('precio_m2'))}/m²) es más alto que el "
                f"{pct}% de los comparables. Es la causa #1 de baja rotación.",
                f"Considera acercarte a la mediana de la zona "
                f"({format_cop(zona.get('precio_m2_mediana'))}/m²).")
        elif pct_m2 <= 0.35:
            add("precio_competitivo", "ok",
                f"Precio/m² competitivo (percentil {pct})",
                "El precio no es el problema; revisa presentación y demanda.")
        else:
            add("precio_medio", "baja",
                f"Precio/m² en rango de mercado (percentil {pct})",
                "El precio está alineado; el freno probablemente es otro.")
    elif pct_precio is not None:
        pct = round(pct_precio * 100)
        add("precio_ref", "media" if pct_precio >= 0.75 else "baja",
            f"Precio en el percentil {pct} de comparables (sin área confiable)",
            "No hay área para calcular precio/m²; se usó el precio absoluto.")

    # 2) Fotos
    n_fotos = base.get("total_imagenes") or 0
    if fotos_med is not None and n_fotos < fotos_med * 0.7:
        add("pocas_fotos", "media",
            f"Solo {n_fotos} fotos vs mediana {round(fotos_med)} de la zona",
            "Los inmuebles con menos fotos reciben menos clics y visitas.",
            f"Sube al menos hasta {round(fotos_med)} fotos, incluyendo fachada y áreas comunes.")
    elif n_fotos == 0:
        add("sin_fotos", "alta", "El inmueble no tiene fotos",
            "Sin fotos es casi imposible que rote.", "Sube fotos cuanto antes.")

    # 3) Descripción
    desc_len = base.get("descripcion_length") or 0
    if desc_med is not None and desc_len < desc_med * 0.6:
        add("descripcion_corta", "baja",
            f"Descripción corta ({desc_len} car.) vs mediana {round(desc_med)}",
            "Una descripción pobre reduce interés y confianza.",
            "Enriquece la descripción (usa la mejora con IA).")

    # 4) Amenidades
    amen = base.get("total_amenidades") or 0
    if amen_med is not None and amen < amen_med * 0.6:
        add("pocas_amenidades", "baja",
            f"Menos amenidades listadas ({amen}) que la mediana ({round(amen_med)})",
            "Puede que existan pero no estén cargadas.",
            "Verifica y completa las amenidades del inmueble.")

    # 5) Antigüedad en inventario
    dias = base.get("dias_en_inventario") or 0
    if dias_med is not None and dias > max(dias_med * 1.3, 60):
        add("estancado", "media",
            f"{dias} días en inventario vs mediana {round(dias_med)} de la zona",
            "El inmueble lleva más tiempo publicado que sus comparables.",
            "Refresca precio y presentación para reactivar interés.")

    # 6) Demanda / balance
    dem_total = demanda.get("demanda_total", 0)
    if dem_total == 0:
        add("sin_demanda", "media",
            "No se detecta demanda reciente para esta zona/tipo",
            "En la ventana analizada no hay pedidos ni búsquedas que encajen.",
            "Evalúa ampliar el público objetivo o el canal de difusión.")
    else:
        n_buyers = buyers.get("total_compradores", 0)
        if n_buyers > 0:
            add("hay_compradores", "ok",
                f"Hay {n_buyers} comprador(es) activo(s) que podrían encajar",
                "Existe demanda que matchea el inmueble; contáctalos.",
                "Revisa `find_buyers_for_property` y contacta a los compradores.")

    # Severidad global.
    severidades = [h["severidad"] for h in hallazgos]
    if "alta" in severidades:
        veredicto = "problema_critico"
    elif "media" in severidades:
        veredicto = "mejorable"
    elif any(s == "baja" for s in severidades):
        veredicto = "ajustes_menores"
    else:
        veredicto = "saludable"

    return {
        "propiedad": {
            "id": base["id"], "slug": base["slug"], "titulo": base["titulo"],
            "ciudad": base["ciudad"], "zona": base["zona"],
            "precio": base["precio"], "precio_legible": base["precio_legible"],
            "precio_m2": base["precio_m2"], "area_construida": base["area_construida"],
            "habitaciones": base["habitaciones"], "total_imagenes": base["total_imagenes"],
            "dias_en_inventario": base["dias_en_inventario"],
        },
        "veredicto": veredicto,
        "nivel_comparacion": comp_data["nivel_comparacion"],
        "total_comparables": comp_data["total_comparables"],
        "posicion_mercado": {
            "percentil_precio_m2": round(pct_m2 * 100) if pct_m2 is not None else None,
            "percentil_precio": round(pct_precio * 100) if pct_precio is not None else None,
            "precio_m2_mediana_zona": zona.get("precio_m2_mediana"),
            "dias_inventario_mediana_zona": dias_med,
        },
        "demanda": {
            "demanda_total": dem_total,
            "compradores_potenciales": buyers.get("total_compradores", 0),
        },
        "hallazgos": hallazgos,
    }


# --------------------------------------------------------------------------
# Wrappers públicos.
# --------------------------------------------------------------------------

def diagnose_public(property_id):
    with get_db() as db:
        return diagnose_property(db.cursor, property_id)


def find_buyers_public(property_id, dias=120, limit=15):
    with get_db() as db:
        return find_buyers_for_property(db.cursor, property_id, dias, limit)
