"""
Orquestador de IA para crear listings DESDE LA WEB de Fynder.

IMPORTANTE: esto usa los tokens de Anthropic de FYNDER. Solo se usa en el camino
web (donde no hay una IA conectada). Desde el MCP NO se llama esto — la IA del
cliente (Claude/ChatGPT) ya genera el contenido con sus propios tokens.

Orquesta lo que ya existe:
- ImageAnalyzer (Claude Vision) -> detecta amenidades/estilo/calidad de las fotos.
- Claude Haiku -> título + descripción vendedores a partir de los datos + fotos.
- estimate_price (comparables) -> precio sugerido.
"""

import json
import os
from typing import Any, Dict, List, Optional

_MODEL_TEXTO = "claude-haiku-4-5-20251001"


def analizar_fotos(image_urls: List[str]) -> Dict[str, Any]:
    """Analiza las fotos subidas y devuelve amenidades/estilo/calidad detectados."""
    if not image_urls:
        return {}
    try:
        from src.core.image_analyzer import get_image_analyzer
        res = get_image_analyzer().analyze_property_images(image_urls[:5])
        return {
            "estilo": res.get("estilo_predominante"),
            "ambiente": res.get("ambiente_general"),
            "calidad_fotos": res.get("calidad_promedio"),
            "caracteristicas_visibles": res.get("todas_caracteristicas") or [],
            "puntos_destacados": res.get("todos_puntos_destacados") or [],
            "tags": res.get("tags_visuales") or [],
        }
    except Exception as e:
        return {"error": f"No se pudieron analizar las fotos: {e}"}


def generar_contenido(datos: Dict[str, Any], analisis_fotos: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Genera título + descripción + amenidades sugeridas con Claude Haiku, a partir
    de los datos duros del agente y (si hay) el análisis de las fotos.
    """
    try:
        import anthropic
    except ImportError:
        return {"error": "anthropic no disponible"}

    hechos = []
    for k, etq in [("tipo_propiedad", "Tipo"), ("ciudad", "Ciudad"), ("zona", "Zona/Barrio"),
                   ("area_construida", "Área m²"), ("habitaciones", "Habitaciones"),
                   ("banos", "Baños"), ("parqueaderos", "Parqueaderos"), ("estrato", "Estrato"),
                   ("piso", "Piso"), ("ano_construccion", "Año")]:
        if datos.get(k):
            hechos.append(f"{etq}: {datos[k]}")
    hechos_txt = ", ".join(hechos) or "Sin datos"

    fotos_txt = ""
    if analisis_fotos and not analisis_fotos.get("error"):
        vis = analisis_fotos.get("caracteristicas_visibles") or []
        pts = analisis_fotos.get("puntos_destacados") or []
        if vis or pts:
            fotos_txt = f"\nLo que se ve en las fotos: {', '.join(vis[:12])}. Destacados: {', '.join(pts[:6])}."

    prompt = f"""Eres un copywriter inmobiliario experto en Colombia. Crea el contenido de venta de una propiedad NUEVA.

DATOS DE LA PROPIEDAD: {hechos_txt}{fotos_txt}

Genera:
1. Un TÍTULO corto y atractivo (máx 70 caracteres, sin el precio).
2. Una DESCRIPCIÓN vendedora de 2-3 párrafos en español colombiano, cálida y profesional. Resalta lo que la hace especial. NO inventes datos que no estén arriba.
3. AMENIDADES detectadas de las fotos/datos, separadas por '|' (ej. "Piscina|Gimnasio|Zona infantil|Portería 24h"). Si no hay evidencia, deja vacío.

FORMATO — JSON puro sin markdown:
{{"titulo": "...", "descripcion": "Párrafo 1.\\n\\nPárrafo 2.", "amenidades": "Piscina|Gimnasio"}}"""

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        msg = client.messages.create(model=_MODEL_TEXTO, max_tokens=1024,
                                     messages=[{"role": "user", "content": prompt}])
        txt = msg.content[0].text.strip()
        if txt.startswith("```"):
            txt = txt.split("```")[1].replace("json", "", 1).strip()
        data = json.loads(txt)
        return {
            "titulo": data.get("titulo"),
            "descripcion": data.get("descripcion"),
            "amenidades": data.get("amenidades"),
        }
    except Exception as e:
        return {"error": f"No se pudo generar el contenido: {e}"}


def sugerir_precio(datos: Dict[str, Any]) -> Dict[str, Any]:
    """Sugiere precio con base en comparables de la zona (sin IA, solo datos)."""
    try:
        from src.services.property_service import estimate_price_public
        return estimate_price_public(
            ciudad=datos.get("ciudad"), zona=datos.get("zona"),
            tipo_propiedad=datos.get("tipo_propiedad"),
            area_construida=datos.get("area_construida"),
            habitaciones=datos.get("habitaciones"),
            tipo_negocio=datos.get("tipo_negocio") or "Venta",
        )
    except Exception as e:
        return {"error": str(e)}


def autocompletar(datos: Dict[str, Any], image_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Autocompletar mágico para la web: analiza fotos + genera título/descripción/
    amenidades + sugiere precio. Devuelve todo para que el agente revise y ajuste.
    """
    analisis = analizar_fotos(image_urls or [])
    contenido = generar_contenido(datos, analisis)
    precio = sugerir_precio(datos)
    return {
        "analisis_fotos": analisis,
        "titulo_sugerido": contenido.get("titulo"),
        "descripcion_sugerida": contenido.get("descripcion"),
        "amenidades_sugeridas": contenido.get("amenidades"),
        "precio_sugerido": precio.get("precio_estimado"),
        "precio_sugerido_legible": precio.get("precio_estimado_legible"),
        "precio_rango": precio.get("rango_estimado"),
        "precio_baja_confianza": precio.get("baja_confianza"),
        "errores": [x for x in [analisis.get("error"), contenido.get("error"), precio.get("error")] if x],
    }
