"""
IA del mapa de mercado (Claude).

- `preguntar`: "Pregúntale al mapa". El agente pregunta en lenguaje natural
  (¿dónde capto apartamentos de 3 habitaciones por menos de 600 millones?) y
  Claude responde con los datos agregados de las zonas: una respuesta corta en
  lenguaje de corredor, las zonas a resaltar (con el porqué), la métrica que
  conviene ver y, si aplica, filtros para los inmuebles.
- `lectura`: la "Lectura de Findy" de una zona o un área: titular, tres puntos
  y una recomendación de negocio (captar, vender, ajustar precio o esperar).

Solo ve datos agregados (nunca contactos). Respuestas con salida estructurada
(JSON Schema) para no depender de parsear texto libre. Ambas
cuentan para el uso justo diario del agente (como las búsquedas).
"""

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

import anthropic

from src.services import mapa_service, suscripcion_service

MODELO = os.getenv("FYNDER_MAPA_MODELO", "claude-sonnet-5-5")
MODELO_RESPALDO = "claude-haiku-4-5-20251001"
TTL_LECTURA = 6 * 3600

_cache_lectura: Dict[str, Any] = {}
_lock = threading.Lock()

ESTILO = """Eres Findy, el analista de mercado de Fynder para agentes inmobiliarios de Medellín y el Valle de Aburrá.
Hablas como un corredor experto, no como un reporte: directo, accionable, en español de Colombia.
- Dinero SIEMPRE en millones: "$620 millones", "$8,3 millones el m²". Nunca "B" ni "billón".
- Nada de jerga estadística (percentil, mediana, ratio): traduce a negocio ("hay 3 pedidos por cada 10 inmuebles", "lo típico de la zona").
- "Pedidos" son clientes compradores que otros agentes publicaron en los últimos 120 días. "Inmuebles" es la oferta en venta.
- Temperatura: caliente = mucha demanda frente a la oferta (momento de vendedor); fría = mucha oferta o poca demanda.
- Usa SOLO los datos que te doy. Si no alcanzan para responder, dilo y sugiere qué mirar en el mapa.
- Nunca inventes contactos, nombres ni links."""


def _cliente() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def _cerrar(schema: Any) -> Any:
    """Structured outputs exige additionalProperties: false en cada objeto (y no admite min/maxItems)."""
    if isinstance(schema, dict):
        schema = {k: _cerrar(v) for k, v in schema.items() if k not in ("minItems", "maxItems")}
        if schema.get("type") == "object":
            schema["additionalProperties"] = False
    elif isinstance(schema, list):
        schema = [_cerrar(v) for v in schema]
    return schema


def _llamar(prompt: str, herramienta: Dict[str, Any], max_tokens: int = 4000) -> Dict[str, Any]:
    """Respuesta JSON validada contra el esquema (structured outputs). Sonnet 5.5 no admite
    tool_choice forzado, así que se usa output_config.format; respaldo en Haiku 4.5."""
    esquema = _cerrar(herramienta["input_schema"])
    ultimo: Optional[Exception] = None
    for modelo, effort in ((MODELO, "low"), (MODELO_RESPALDO, None)):
        try:
            output_config: Dict[str, Any] = {"format": {"type": "json_schema", "schema": esquema}}
            if effort:
                output_config["effort"] = effort
            msg = _cliente().messages.create(
                model=modelo, max_tokens=max_tokens, system=ESTILO,
                messages=[{"role": "user", "content": f"{prompt}\n\n{herramienta['description']}"}],
                extra_body={"output_config": output_config})  # el SDK 0.75 aún no expone output_config
            if msg.stop_reason == "refusal":
                raise RuntimeError("refusal")
            texto = next(b.text for b in msg.content if b.type == "text")
            return json.loads(texto)
        except Exception as e:  # noqa: BLE001 — se intenta con el respaldo
            ultimo = e
            print(f"[MAPA-IA] {modelo} falló: {e}")
    raise mapa_service.MapaError("ia", "Findy no pudo responder en este momento. Intenta de nuevo.") from ultimo


def _uso_justo(user_id: int) -> None:
    uso = suscripcion_service.registrar_busqueda(user_id)
    if not uso.get("permitido"):
        raise mapa_service.MapaError("limite", "Llegaste al límite de consultas de IA de hoy. Mañana se renueva.")


def _m(n: Any) -> Optional[float]:
    return round(float(n) / 1_000_000, 1) if n else None


def _tabla_zonas(zonas: List[Dict[str, Any]]) -> str:
    filas = ["id | nombre | inmuebles | pedidos | temperatura | m2_millones | precio_tipico_millones | presupuesto_compradores_millones | dias_en_mercado | se_ofrece | se_busca"]
    for z in zonas:
        filas.append(" | ".join(str(x) for x in [
            z["id"], z["nombre"], z["inmuebles"], z["pedidos"], z["temperatura"], _m(z["precio_m2"]),
            _m(z["precio_mediana"]), _m(z["presupuesto_mediana"]),
            round(z["dias_mercado"]) if z.get("dias_mercado") is not None else None,
            ",".join(f"{k}:{v}" for k, v in (z.get("tipos") or {}).items()),
            ",".join(f"{k}:{v}" for k, v in (z.get("tipos_buscados") or {}).items()),
        ]))
    return "\n".join(filas)


_HERRAMIENTA_RESPUESTA = {
    "name": "responder_en_el_mapa",
    "description": "Responde la pregunta del agente y dice qué resaltar en el mapa.",
    "input_schema": {
        "type": "object",
        "properties": {
            "respuesta": {"type": "string", "description": "Respuesta en 2 a 5 frases (máx. 90 palabras). Puede usar **negrita** para cifras y zonas clave."},
            "zonas": {
                "type": "array", "maxItems": 6,
                "description": "Zonas a resaltar en orden de prioridad (ids exactos de la tabla).",
                "items": {"type": "object", "properties": {
                    "id": {"type": "string"},
                    "motivo": {"type": "string", "description": "Por qué, en máx. 12 palabras, con una cifra."},
                }, "required": ["id", "motivo"]},
            },
            "metrica": {"type": "string", "enum": ["temperatura", "precio", "demanda", "oferta"],
                        "description": "La lectura del mapa que mejor ilustra la respuesta."},
            "filtros": {
                "type": "object", "description": "Filtros para los inmuebles del mapa, solo si la pregunta los pide.",
                "properties": {
                    "tipo": {"type": "string", "enum": ["Apartamento", "Casa", "Apartaestudio", "Lote", "Local", "Oficina", "Finca"]},
                    "precio_max": {"type": "number", "description": "En pesos."},
                    "precio_min": {"type": "number", "description": "En pesos."},
                    "hab_min": {"type": "integer"},
                },
            },
            "siguiente": {"type": "string", "description": "Una pregunta de seguimiento útil (máx. 10 palabras)."},
        },
        "required": ["respuesta", "zonas", "metrica"],
    },
}


def preguntar(user_id: int, pregunta: str, zona_id: Optional[str] = None,
              area: Optional[List[List[float]]] = None) -> Dict[str, Any]:
    pregunta = " ".join((pregunta or "").split())[:400]
    if len(pregunta) < 4:
        raise mapa_service.MapaError("invalido", "Escribe tu pregunta.")
    _uso_justo(user_id)
    d = mapa_service.zonas()
    zonas = [z for z in d["zonas"] if z["inmuebles"] >= 3 or z["pedidos"] >= 3]
    contexto = ""
    if zona_id and zona_id in {z["id"] for z in zonas}:
        contexto = f"\nEl agente tiene abierta la zona con id «{zona_id}»."
    if area:
        a = mapa_service.area_detalle(area)
        contexto = (f"\nEl agente dibujó un área con {a['inmuebles']} inmuebles y {a['pedidos']} pedidos, "
                    f"m² típico {_m(a['precio_m2'])} millones, zonas: {', '.join(z['nombre'] for z in a['zonas_incluidas'])}.")
    prompt = (f"Datos de las zonas (oferta en venta y pedidos de compradores de los últimos 120 días):\n"
              f"{_tabla_zonas(zonas)}\n{contexto}\n\nPregunta del agente: «{pregunta}»")
    r = _llamar(prompt, _HERRAMIENTA_RESPUESTA)
    validas = {z["id"]: z for z in zonas}
    destacadas = []
    for item in r.get("zonas") or []:
        z = validas.get(str(item.get("id", "")).strip())
        if z and z["id"] not in {x["id"] for x in destacadas}:
            destacadas.append({"id": z["id"], "nombre": z["nombre"], "lat": z["lat"], "lng": z["lng"],
                               "motivo": str(item.get("motivo") or "")[:120]})
    filtros = {k: v for k, v in (r.get("filtros") or {}).items() if v not in (None, "", 0)}
    return {"respuesta": str(r.get("respuesta") or "").strip(), "zonas": destacadas,
            "metrica": r.get("metrica") if r.get("metrica") in ("temperatura", "precio", "demanda", "oferta") else "temperatura",
            "filtros": filtros, "siguiente": (r.get("siguiente") or "").strip() or None}


_HERRAMIENTA_LECTURA = {
    "name": "lectura_de_zona",
    "description": "Lectura de negocio de una zona o área para un agente inmobiliario.",
    "input_schema": {
        "type": "object",
        "properties": {
            "titular": {"type": "string", "description": "Máx. 9 palabras, con la idea principal."},
            "puntos": {"type": "array", "minItems": 2, "maxItems": 3,
                       "items": {"type": "string", "description": "Máx. 20 palabras, con una cifra concreta."}},
            "accion": {"type": "string", "enum": ["captar", "vender", "ajustar_precio", "esperar"],
                       "description": "Lo que más le conviene hacer al agente aquí."},
            "recomendacion": {"type": "string", "description": "Máx. 30 palabras, concreta (a qué precio, qué tipo, a quién)."},
        },
        "required": ["titular", "puntos", "accion", "recomendacion"],
    },
}


def lectura(user_id: int, zona_id: Optional[str] = None, area: Optional[List[List[float]]] = None) -> Dict[str, Any]:
    if zona_id:
        datos = mapa_service.zona_detalle(zona_id)
        if not datos:
            raise mapa_service.MapaError("no_encontrado", "Zona no encontrada.")
    elif area:
        datos = mapa_service.area_detalle(area)
    else:
        raise mapa_service.MapaError("invalido", "Falta la zona o el área.")
    clave = datos["id"]
    with _lock:
        c = _cache_lectura.get(clave)
        if c and time.time() - c["t"] < TTL_LECTURA:
            return c["r"]
    _uso_justo(user_id)
    resumen = {
        "nombre": datos["nombre"], "inmuebles_en_venta": datos["inmuebles"], "pedidos_120_dias": datos["pedidos"],
        "temperatura": datos["temperatura"], "m2_tipico_millones": _m(datos["precio_m2"]),
        "precio_tipico_millones": _m(datos["precio_mediana"]),
        "presupuesto_tipico_compradores_millones": _m(datos["presupuesto_mediana"]),
        "dias_tipicos_en_el_mercado": round(datos["dias_mercado"]) if datos.get("dias_mercado") is not None else None,
        "se_ofrece": datos["tipos"], "se_busca": datos["tipos_buscados"],
        "oportunidades_bajo_el_m2_de_la_zona": len(datos["oportunidades"]),
        "rango_de_precios": [{"desde_millones": _m(h["desde"]), "hasta_millones": _m(h["hasta"]), "inmuebles": h["n"]}
                             for h in datos["histograma"]],
    }
    if datos.get("zonas_incluidas"):
        resumen["zonas_dentro_del_area"] = [z["nombre"] for z in datos["zonas_incluidas"]]
    r = _llamar("Haz la lectura de negocio de esta " + ("zona" if datos["tipo"] == "zona" else "área dibujada por el agente")
                + ":\n" + json.dumps(resumen, ensure_ascii=False), _HERRAMIENTA_LECTURA, max_tokens=600)
    salida = {"titular": str(r.get("titular") or "").strip(), "puntos": [str(p).strip() for p in (r.get("puntos") or [])][:3],
              "accion": r.get("accion") if r.get("accion") in ("captar", "vender", "ajustar_precio", "esperar") else "esperar",
              "recomendacion": str(r.get("recomendacion") or "").strip()}
    with _lock:
        _cache_lectura[clave] = {"t": time.time(), "r": salida}
    return salida
