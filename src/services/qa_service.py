"""
Dossier de un inmueble para responder preguntas.

Reúne TODO lo que se sabe de una propiedad (specs, amenidades desglosadas,
descripción y lo que la IA detectó en las fotos) para que el LLM responda
cualquier pregunta del agente ("¿tiene piscina?", "¿de qué año es?", "¿la cocina
se ve remodelada?", "¿tiene buena luz?"). No responde el tool: le da al LLM el
contexto para que él responda con sus tokens y sea honesto cuando el dato no está.
"""

from typing import Any, Dict, List

from src.services.db import get_db, fetch_all
from src.services.property_service import get_property


def _amenidades(p: Dict[str, Any]) -> List[str]:
    out = []
    for campo in ("amenidades_internas", "amenidades_externas"):
        for a in (p.get(campo) or "").split("|"):
            a = a.strip()
            if a and a not in out:
                out.append(a)
    return out


def _analisis_fotos(cur, property_id: int) -> List[Dict[str, Any]]:
    """Lo que la IA de visión detectó en las fotos (por ambiente)."""
    rows = fetch_all(cur, """
        SELECT tipo_espacio, ambiente, estilo_detectado, calidad_imagen,
               descripcion_visual, caracteristicas_visibles, puntos_destacados
        FROM property_image_analysis
        WHERE propiedad_id = %s
        ORDER BY es_imagen_principal DESC NULLS LAST, id
        LIMIT 12
    """, (property_id,))
    fotos = []
    for r in rows:
        item = {
            "espacio": r.get("tipo_espacio"),
            "ambiente": r.get("ambiente"),
            "estilo": r.get("estilo_detectado"),
            "calidad_1a10": r.get("calidad_imagen"),
            "descripcion_visual": r.get("descripcion_visual"),
        }
        # caracteristicas/puntos pueden venir como JSON/lista/texto.
        for k_src, k_dst in [("caracteristicas_visibles", "caracteristicas"),
                             ("puntos_destacados", "destacados")]:
            v = r.get(k_src)
            if isinstance(v, list):
                item[k_dst] = v
            elif isinstance(v, str) and v.strip():
                item[k_dst] = v
        fotos.append({k: val for k, val in item.items() if val not in (None, "", [])})
    return fotos


def dossier_inmueble(cur, property_id) -> Dict[str, Any]:
    """
    Devuelve el dossier completo del inmueble para responder preguntas.
    Nunca incluye datos de contacto del agente (el sanitize global igual limpia).
    """
    p = get_property(cur, property_id)
    if not p:
        return {"error": f"Propiedad {property_id} no encontrada"}

    fotos = _analisis_fotos(cur, p["id"])

    return {
        "propiedad": {
            "id": p["id"], "slug": p["slug"], "titulo": p["titulo"],
            "precio_legible": p["precio_legible"], "tipo": p["tipo_propiedad"],
            "ciudad": p["ciudad"], "zona": p["zona"], "direccion": p.get("direccion"),
        },
        "caracteristicas": {
            "area_m2": p.get("area_construida"),
            "habitaciones": p.get("habitaciones"),
            "banos": p.get("banos"),
            "parqueaderos": p.get("parqueaderos"),
            "estrato": p.get("estrato"),
            "piso": p.get("piso"),
            "ano_construccion": p.get("ano_construccion"),
            "administracion": p.get("administracion"),
            "precio_m2": p.get("precio_m2"),
        },
        "amenidades": _amenidades(p),
        "caracteristicas_adicionales": p.get("caracteristicas_adicionales") if p.get("caracteristicas_adicionales") else None,
        "descripcion": p.get("descripcion_ai") or p.get("descripcion"),
        "lo_que_se_ve_en_las_fotos": fotos or None,
        "nota": ("Responde la pregunta del agente SOLO con esta información. Si un dato NO "
                 "aparece aquí (ej. piso, año, o una amenidad no listada), dilo con honestidad: "
                 "'no está cargado en Fynder, confírmalo con el agente que captó el inmueble'. "
                 "No inventes."),
    }


def dossier_public(property_id):
    with get_db() as db:
        return dossier_inmueble(db.cursor, property_id)
