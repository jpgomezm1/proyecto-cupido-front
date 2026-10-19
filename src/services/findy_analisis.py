"""
El modo Análisis de Findy (web): Claude con las herramientas de lectura del mercado
(`findy_herramientas`) responde con texto corto y componentes de la app (OpenUI Lang).

El frontend define los componentes (mvp-tu360/src/lib/openui/) y de ahí sale, con
`npm run openui:prompt`, el texto que le explica al modelo cómo usarlos:
`src/core/openui/findy_componentes.txt`. Si se cambia un componente, se regenera.

`analizar()` es un generador de eventos para el streaming (SSE) del endpoint:
  {"tipo": "estado", "texto": "Revisando la oferta de la zona…"}   (antes de cada herramienta)
  {"tipo": "texto", "delta": "..."}                                 (la respuesta, a medida que llega)
  {"tipo": "fin", "contenido": "...", "herramientas": [...], "uso": {...}}
El cupo (analisis_service) y el guardado del mensaje los hace el endpoint.
"""

import json
import os
import time
from typing import Any, Dict, Iterator, List

from src.services import findy_herramientas as fh

MODELO = os.getenv("FYNDER_MODELO_ANALISIS", "claude-sonnet-4-6")
MAX_RONDAS = int(os.getenv("FYNDER_ANALISIS_RONDAS", "6"))
MAX_TOKENS = 4000

# USD por millón de tokens (Sonnet): entrada, salida, escritura y lectura de caché.
_PRECIOS = {"entrada": 3.0, "salida": 15.0, "cache_escritura": 3.75, "cache_lectura": 0.30}

_PROMPT_COMPONENTES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "openui", "findy_componentes.txt")

_ESTADOS = {
    "buscar_inmuebles": "Buscando inmuebles…",
    "ficha_inmueble": "Leyendo la ficha del inmueble…",
    "oferta_zona": "Revisando la oferta de la zona…",
    "demanda_zona": "Contando los compradores de la zona…",
    "balance_zona": "Cruzando oferta y demanda…",
    "donde_captar": "Buscando dónde hay más compradores que oferta…",
    "estimar_precio": "Calculando el precio con comparables…",
    "comparables": "Buscando comparables…",
    "comparar_inmuebles": "Comparando los inmuebles…",
    "diagnosticar_inmueble": "Diagnosticando el inmueble…",
    "compradores_de_inmueble": "Buscando compradores para el inmueble…",
    "compradores_para": "Buscando compradores para tu inmueble…",
    "encaje_comprador": "Midiendo el encaje con el comprador…",
    "capacidad_de_compra": "Calculando la capacidad de compra…",
    "costo_mensual": "Calculando el costo mensual…",
    "puntos_de_venta": "Armando los puntos de venta…",
    "interes_inmueble": "Revisando el interés del inmueble…",
    "mis_inmuebles_calientes": "Revisando tus inmuebles…",
    "que_hay_cerca": "Mirando qué hay cerca…",
}

_SISTEMA = """Eres Findy, el analista de mercado de Fynder, la plataforma inmobiliaria para agentes en Colombia \
(Medellín y el Valle de Aburrá sobre todo). Le hablas a un AGENTE INMOBILIARIO, de tú, como un colega experto: \
directo, accionable, sin jerga estadística (nada de percentil, mediana, ratio: di "8 de cada 10", "donde se mueve \
la mayoría", "hay más compradores que oferta").

CÓMO TRABAJAS
- Usa las herramientas para responder: primero todas las que necesites (en paralelo si son independientes) y \
después responde UNA sola vez. No escribas nada antes de terminar de usar las herramientas.
- TODA cifra que muestres sale de una herramienta. Nunca inventes números, inmuebles, barrios ni compradores. \
Si una herramienta no trae el dato, dilo con honestidad y sugiere otra pregunta.
- Nunca repartas, estimes ni extrapoles un total en partes (por banda, por habitaciones, por zona) si la \
herramienta no trae ese desglose: en ese caso NO hagas ese gráfico. Una cuenta simple entre dos cifras que sí \
vinieron (p. ej. compradores ÷ inmuebles) sí vale.
- El título de cada gráfico dice exactamente qué miden sus datos: si los datos son de la OFERTA (lo que hay en \
venta), no lo titules como lo que buscan los compradores, y al revés.
- Si la pregunta no se puede responder con las herramientas (o no es del mercado inmobiliario), dilo en una línea \
y sugiere qué sí puedes analizar.
- Si falta un dato esencial (la zona, el inmueble), pregúntalo en una línea en vez de adivinar.

DINERO
- Pesos colombianos, siempre en millones: "$1.290 millones", "$6,9 M el m²". En español "billón" es un millón de \
millones: NUNCA uses "B" ni "billón" para miles de millones.

CONTACTOS (lo que Fynder cobra)
- Tú nunca das ni pides contactos, teléfonos ni links de otros portales. El contacto de quien tiene un inmueble o \
hizo un pedido se obtiene en la app con el botón de la llave, que ya va en las tarjetas de inmuebles. Si el agente \
pide un contacto, dile que use la llave de la tarjeta.

LA RESPUESTA (el formato exacto va abajo, en las instrucciones de los componentes)
- Arranca con un Texto de 1 a 3 frases con la conclusión (qué significa para captar, vender o negociar). Luego los \
componentes. Cierra, si aplica, con las siguientes preguntas sugeridas (botones).
- Elige los componentes que mejor cuentan el dato: cifras clave, termómetro, barras, dona, tabla, lista de \
inmuebles. Una gráfica dice UNA cosa; el título del componente la dice en palabras.
- Para mostrar inmuebles usa SIEMPRE el componente de inmuebles con sus ids reales (la app pinta la tarjeta con su \
foto, precio y botón de llave). No copies los datos del inmueble a mano.
- Breve: un agente lo lee en el celular entre visitas.
"""


def _prompt_componentes() -> str:
    try:
        with open(_PROMPT_COMPONENTES, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Responde solo con texto (los componentes no están disponibles)."


def _costo(uso: Dict[str, int]) -> float:
    return round(sum(uso[k] * _PRECIOS[k] for k in _PRECIOS) / 1e6, 5)


def _historial(mensajes: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Los últimos turnos de la conversación (texto), alternando usuario/asistente."""
    salida: List[Dict[str, Any]] = []
    for m in mensajes[-6:]:
        rol = "assistant" if m.get("role") == "assistant" else "user"
        texto = (m.get("content") or "").strip()[:3000]
        if not texto:
            continue
        if salida and salida[-1]["role"] == rol:
            salida[-1]["content"] += "\n\n" + texto
        else:
            salida.append({"role": rol, "content": texto})
    while salida and salida[0]["role"] != "user":
        salida.pop(0)
    while salida and salida[-1]["role"] != "assistant":   # la pregunta nueva va al final
        salida.pop()
    return salida


def analizar(user: Dict[str, Any], pregunta: str, historial: List[Dict[str, str]]) -> Iterator[Dict[str, Any]]:
    import anthropic

    cliente = anthropic.Anthropic()
    agente = fh.Agente(user)
    herramientas = fh.esquemas()
    herramientas[-1] = {**herramientas[-1], "cache_control": {"type": "ephemeral"}}
    sistema = [
        {"type": "text", "text": _SISTEMA},
        {"type": "text", "text": _prompt_componentes(), "cache_control": {"type": "ephemeral"}},
    ]
    mensajes: List[Dict[str, Any]] = _historial(historial) + [{"role": "user", "content": pregunta}]
    uso = {"entrada": 0, "salida": 0, "cache_escritura": 0, "cache_lectura": 0}
    usadas: List[str] = []
    contenido = ""
    t0 = time.time()

    for ronda in range(MAX_RONDAS):
        ultima = ronda == MAX_RONDAS - 1
        with cliente.messages.stream(
            model=MODELO, max_tokens=MAX_TOKENS, system=sistema, messages=mensajes,
            tools=herramientas, **({"tool_choice": {"type": "none"}} if ultima else {}),
        ) as s:
            for ev in s:
                if ev.type == "text":
                    contenido += ev.text
                    yield {"tipo": "texto", "delta": ev.text}
            final = s.get_final_message()
        u = final.usage
        uso["entrada"] += u.input_tokens or 0
        uso["salida"] += u.output_tokens or 0
        uso["cache_escritura"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        uso["cache_lectura"] += getattr(u, "cache_read_input_tokens", 0) or 0
        try:
            from src.core.ai_usage_tracker import get_ai_tracker
            get_ai_tracker().track_anthropic_response(MODELO, "findy_analisis", "findy_analisis.analizar", final, t0)
        except Exception:  # noqa: BLE001 — el registro de uso nunca tumba el análisis
            pass

        llamadas = [b for b in final.content if b.type == "tool_use"]
        if final.stop_reason != "tool_use" or not llamadas:
            break
        mensajes.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in final.content]})
        resultados = []
        for b in llamadas:
            yield {"tipo": "estado", "texto": _ESTADOS.get(b.name, "Consultando el mercado…")}
            usadas.append(b.name)
            resultados.append({"type": "tool_result", "tool_use_id": b.id,
                               "content": fh.ejecutar(agente, b.name, b.input)})
        mensajes.append({"role": "user", "content": resultados})
        if contenido and not contenido.endswith("\n"):
            contenido += "\n"

    yield {"tipo": "fin", "contenido": contenido.strip(), "herramientas": usadas,
           "uso": {**uso, "costo_usd": _costo(uso), "ms": int((time.time() - t0) * 1000)}}
