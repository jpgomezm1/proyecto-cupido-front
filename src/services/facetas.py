"""
Tipo, ubicación, área y habitaciones de un inmueble para estadísticas de mercado.

Las columnas que llenan los scrapers vienen incompletas (oct-2026: el tipo falta en
~2/3 de los activos, la zona en ~2/3 y las habitaciones en casi todo Wasi). La ficha
del buscador v3 (`propiedades_ficha`) y el catálogo de barrios (`propiedad_barrio`)
sí las tienen. `JOIN` expone, como alias `x`, el valor del portal y, si falta, el de la
ficha o el catálogo (el tipo, al revés: primero la ficha, que ya viene normalizado):

    FROM propiedades p {JOIN} WHERE ... x.tipo ... x.area ...

Las condiciones de `condiciones()` van contra esos alias.
"""
from typing import Any, List, Optional, Tuple

from src.services.textutils import accent_insensitive_expr, like_param

JOIN = """
    LEFT JOIN propiedades_ficha f ON f.propiedad_id = p.id
    LEFT JOIN propiedad_barrio pb ON pb.propiedad_id = p.id
    LEFT JOIN barrios b ON b.id = pb.barrio_id
    CROSS JOIN LATERAL (SELECT
        COALESCE(NULLIF(p.area_construida, 0), f.area_m2)                    AS area,
        COALESCE(p.habitaciones, f.habitaciones)                             AS hab,
        COALESCE(NULLIF(f.tipo, ''), NULLIF(p.tipo_propiedad, ''))           AS tipo,
        COALESCE(NULLIF(p.ciudad, ''), f.ciudad, pb.municipio)               AS ciudad,
        COALESCE(NULLIF(p.zona, ''), f.barrio, b.nombre)                     AS barrio,
        b.comuna                                                             AS comuna
    ) x
"""

# Columnas para completar una fila de `_PROPERTY_COLUMNS` (las usa property_service).
COLUMNAS = "x.tipo AS _tipo, x.barrio AS _barrio, x.ciudad AS _ciudad, x.area AS _area, x.hab AS _hab"


def _tipo_param(tipo: str) -> str:
    # La ficha escribe «casa_campestre»; el portal, «Casa Campestre». En LIKE el «_»
    # vale por un carácter cualquiera, así que el mismo patrón sirve para los dos.
    return like_param(tipo.strip().replace(" ", "_"))


def condiciones(ciudad: Optional[str] = None, zona: Optional[str] = None,
                tipo: Optional[str] = None, habitaciones: Optional[int] = None) -> Tuple[List[str], List[Any]]:
    """Condiciones WHERE (contra el alias `x`) y sus parámetros."""
    conds: List[str] = []
    params: List[Any] = []
    if ciudad:
        conds.append(f"{accent_insensitive_expr('x.ciudad')} LIKE %s")
        params.append(like_param(ciudad))
    if zona:
        # La zona que dice el agente puede ser un barrio («Conquistadores»), una comuna
        # («Laureles») o lo que escribió el portal.
        z = like_param(zona)
        conds.append(f"({accent_insensitive_expr('b.nombre')} LIKE %s OR {accent_insensitive_expr('b.comuna')} LIKE %s "
                     f"OR {accent_insensitive_expr('x.barrio')} LIKE %s)")
        params.extend([z, z, z])
    if tipo:
        conds.append(f"{accent_insensitive_expr('x.tipo')} LIKE %s")
        params.append(_tipo_param(tipo))
    if habitaciones is not None:
        conds.append("(x.hab IS NULL OR x.hab BETWEEN %s AND %s)")
        params.extend([habitaciones - 1, habitaciones + 1])
    return conds, params


def legible_tipo(tipo: Optional[str]) -> Optional[str]:
    """«casa_campestre» → «Casa campestre» (la ficha guarda claves)."""
    if not tipo:
        return tipo
    return tipo.replace("_", " ").strip().capitalize() if tipo.islower() else tipo
