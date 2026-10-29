"""
Asistente con IA de «Mi página» (migración 069).

    armar(user_id, indicaciones)          propuesta completa: titular, presentación, preguntas
                                          frecuentes, plantilla, color, tipografía, fondo, esquinas y destacados,
                                          a partir del perfil, las zonas y los inmuebles del agente
    mejorar(user_id, campo, texto, pedido) reescribe un texto («más corto», «más cercano»…)

No guarda nada: el editor muestra la propuesta y el agente decide. Gratis con tope
diario (`TOPE_DIARIO`, contado en pagina_eventos tipo 'ia'); si la IA falla, no se cuenta.
"""

import json
import os
import time
from collections import Counter
from typing import Any, Dict, List, Optional

import anthropic

from src.services import pagina_agente_service as pagina
from src.services.db import fetch_one, get_db

MODELO = os.getenv("FYNDER_PAGINA_MODELO", "claude-sonnet-5-5")
MODELO_RESPALDO = "claude-haiku-4-5-20251001"
TOPE_DIARIO = int(os.getenv("FYNDER_PAGINA_IA_DIA", "10"))

# Colores que se ven bien en las cuatro plantillas (los mismos del editor).
PALETA = ["#16A34A", "#0F766E", "#2563EB", "#1E3A8A", "#7C3AED", "#BE185D", "#B45309", "#B91C1C", "#0A0A0A", "#A16207",
          "#9A3412", "#4D7C0F", "#0E7490", "#8B5E3C"]

ESTILO = """Eres el redactor de marca de Fynder. Escribes la página web personal de un agente inmobiliario
de Colombia (Medellín y el Valle de Aburrá sobre todo), la que comparte en su Instagram y por WhatsApp.
- Español de Colombia, tuteando al cliente. Cálido y profesional, sin exagerar ni prometer lo que no consta.
- Concreto: usa las zonas, los tipos de inmueble y los rangos de precio reales que te doy.
- Nunca inventes cifras (años, ventas, premios), certificaciones, testimonios ni datos de contacto.
- Dinero en millones: "$450 millones". Nunca "B" ni "billón".
- Sin emojis, sin mayúsculas sostenidas, sin hashtags."""


class PaginaIAError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def _cerrar(schema: Any) -> Any:
    """Structured outputs exige additionalProperties: false en cada objeto (y no admite min/maxItems)."""
    if isinstance(schema, dict):
        schema = {k: _cerrar(v) for k, v in schema.items() if k not in ("minItems", "maxItems", "maxLength")}
        if schema.get("type") == "object":
            schema["additionalProperties"] = False
    elif isinstance(schema, list):
        schema = [_cerrar(v) for v in schema]
    return schema


def _llamar(prompt: str, esquema: Dict[str, Any], uso: str, max_tokens: int = 2500) -> Dict[str, Any]:
    from src.core.ai_usage_tracker import get_ai_tracker
    ultimo: Optional[Exception] = None
    for modelo, effort in ((MODELO, "low"), (MODELO_RESPALDO, None)):
        try:
            output_config: Dict[str, Any] = {"format": {"type": "json_schema", "schema": _cerrar(esquema)}}
            if effort:
                output_config["effort"] = effort
            t0 = time.time()
            msg = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY")).messages.create(
                model=modelo, max_tokens=max_tokens, system=ESTILO,
                messages=[{"role": "user", "content": prompt}],
                extra_body={"output_config": output_config})  # el SDK 0.75 aún no expone output_config
            get_ai_tracker().track_anthropic_response(modelo, uso, f"pagina_ia.{uso}", msg, t0)
            if msg.stop_reason == "refusal":
                raise RuntimeError("refusal")
            return json.loads(next(b.text for b in msg.content if b.type == "text"))
        except Exception as e:  # noqa: BLE001 — se intenta con el respaldo
            ultimo = e
            print(f"[PAGINA-IA] {modelo} falló: {e}")
    raise PaginaIAError("ia", "La IA no pudo responder en este momento. Intenta de nuevo.") from ultimo


def _cupo(user_id: int) -> int:
    with get_db() as db:
        usados = pagina.hoy(db.cursor, user_id, "ia")
    if usados >= TOPE_DIARIO:
        raise PaginaIAError("limite", f"Usaste los {TOPE_DIARIO} usos de IA de hoy para tu página. Mañana se renuevan.")
    return usados


def _contar(user_id: int) -> int:
    with get_db() as db:
        n = pagina.sumar(db.cursor, user_id, "ia")
        db.conn.commit()
    return max(TOPE_DIARIO - n, 0)


def _m(n: Optional[float]) -> Optional[str]:
    return f"${round(n / 1_000_000):,} millones".replace(",", ".") if n else None


def _resumen_inventario(inmuebles: List[Dict[str, Any]]) -> str:
    if not inmuebles:
        return "No tiene inmuebles activos publicados todavía."
    tipos = Counter((p.get("tipo_propiedad") or "inmueble").lower() for p in inmuebles)
    zonas = Counter(z for p in inmuebles if (z := p.get("zona")))
    precios = sorted(p["precio"] for p in inmuebles if p.get("precio"))
    lineas = [f"{len(inmuebles)} inmuebles activos.",
              "Tipos: " + ", ".join(f"{t} ({n})" for t, n in tipos.most_common(4)) + "."]
    if zonas:
        lineas.append("Zonas: " + ", ".join(f"{z} ({n})" for z, n in zonas.most_common(6)) + ".")
    if precios:
        lineas.append(f"Precios entre {_m(precios[0])} y {_m(precios[-1])}.")
    lineas.append("Lista (id | título | precio | zona):")
    lineas += [f"{p['id']} | {p['titulo']} | {_m(p.get('precio')) or '—'} | {p.get('zona') or '—'}" for p in inmuebles[:25]]
    return "\n".join(lineas)


_ESQUEMA_ARMAR = {
    "type": "object",
    "properties": {
        "titular": {"type": "string", "description": "Titular de la portada, máx. 70 caracteres. Qué hace y dónde, con gancho."},
        "subtitular": {"type": "string", "description": "Una frase de apoyo, máx. 140 caracteres."},
        "bio": {"type": "string", "description": "Presentación en primera persona, 2 párrafos cortos, máx. 550 caracteres."},
        "zonas": {"type": "array", "items": {"type": "string"}, "description": "Hasta 6 zonas donde trabaja (de su inventario y de lo que ya escribió)."},
        "preguntas": {"type": "array", "description": "4 preguntas frecuentes de sus clientes con respuesta breve y útil.",
                      "items": {"type": "object", "properties": {"p": {"type": "string"}, "r": {"type": "string"}}, "required": ["p", "r"]}},
        "mensaje_whatsapp": {"type": "string", "description": "Mensaje prellenado con el que el cliente le escribe, máx. 120 caracteres, en primera persona del cliente."},
        "plantilla": {"type": "string", "enum": list(pagina.PLANTILLAS),
                      "description": "clasica: cercana y versátil; editorial: portada grande con foto, para quien tiene buenas fotos; minimal: sobria; lujo: oscura y elegante, alto valor; boutique: cálida y refinada, foto en arco; audaz: bloque de color y titular gigante, para destacar; ejecutiva: dividida, sobria y corporativa; natural: tonos tierra, amable, para familias."},
        "color": {"type": "string", "enum": PALETA, "description": "Color de marca que combine con el estilo."},
        "fuente": {"type": "string", "enum": list(pagina.FUENTES),
                   "description": "moderna, geometrica, contemporanea, amigable y fuerte son sans; elegante, editorial, lujo y clasica son serif."},
        "fondo": {"type": "string", "enum": [f for f in pagina.FONDOS if f != "auto"], "description": "Fondo de la página que combine con la plantilla."},
        "esquinas": {"type": "string", "enum": [e for e in pagina.ESQUINAS if e != "auto"]},
        "destacados": {"type": "array", "items": {"type": "integer"}, "description": "Hasta 3 ids de su lista para destacar arriba (los más atractivos)."},
        "explicacion": {"type": "string", "description": "Una o dos frases para el agente: por qué este estilo."},
    },
    "required": ["titular", "subtitular", "bio", "zonas", "preguntas", "mensaje_whatsapp", "plantilla", "color", "fuente",
                 "fondo", "esquinas", "destacados", "explicacion"],
}


def armar(user_id: int, indicaciones: Optional[str] = None) -> Dict[str, Any]:
    _cupo(user_id)
    actual = pagina.mi_pagina(user_id)
    a = actual["vista"]["agente"]
    inmuebles = actual["vista"]["inmuebles"]
    prompt = "\n".join(filter(None, [
        "Arma la página web de este agente.",
        f"Nombre: {a['nombre']}",
        f"Marca o inmobiliaria: {a['marca_nombre']}" if a.get("marca_nombre") else None,
        f"Zonas que escribió: {', '.join(a['zonas'])}" if a.get("zonas") else None,
        f"Su presentación actual (mejórala, respeta los hechos): {a['bio']}" if a.get("bio") else None,
        f"Tiene foto propia: {'sí' if a.get('foto_url') else 'no'}. Tiene logo: {'sí' if a.get('logo_url') else 'no'}.",
        "Inventario:", _resumen_inventario(inmuebles),
        f"Lo que pide el agente: {indicaciones.strip()[:400]}" if indicaciones and indicaciones.strip() else None,
    ]))
    r = _llamar(prompt, _ESQUEMA_ARMAR, "pagina_armar")
    ids = {p["id"] for p in inmuebles}
    propuesta = {
        "titular": (r.get("titular") or "")[:90] or None,
        "subtitular": (r.get("subtitular") or "")[:160] or None,
        "bio": (r.get("bio") or "")[:600] or None,
        "zonas": [z.strip()[:40] for z in r.get("zonas") or [] if isinstance(z, str) and z.strip()][:8],
        "preguntas": [{"p": q["p"][:140], "r": q["r"][:500]} for q in r.get("preguntas") or [] if q.get("p") and q.get("r")][:8],
        "mensaje_whatsapp": (r.get("mensaje_whatsapp") or "")[:160] or None,
        "plantilla": r.get("plantilla") if r.get("plantilla") in pagina.PLANTILLAS else "clasica",
        "color": r.get("color") if r.get("color") in PALETA else PALETA[0],
        "fuente": r.get("fuente") if r.get("fuente") in pagina.FUENTES else "moderna",
        "fondo": r.get("fondo") if r.get("fondo") in pagina.FONDOS else "auto",
        "esquinas": r.get("esquinas") if r.get("esquinas") in pagina.ESQUINAS else "auto",
        "destacados": [i for i in r.get("destacados") or [] if i in ids][:3],
        "explicacion": (r.get("explicacion") or "")[:300],
    }
    return {"propuesta": propuesta, "quedan": _contar(user_id)}


CAMPOS = {
    "titular": ("el titular de la portada", 90),
    "subtitular": ("la frase de apoyo de la portada", 160),
    "bio": ("su presentación en primera persona", 600),
    "respuesta": ("la respuesta a una pregunta frecuente", 500),
    "testimonio": ("un testimonio de un cliente (corrige la redacción, no inventes hechos)", 300),
    "mensaje_whatsapp": ("el mensaje prellenado con que el cliente le escribe por WhatsApp", 160),
}


def mejorar(user_id: int, campo: str, texto: str, pedido: Optional[str] = None, contexto: Optional[str] = None) -> Dict[str, Any]:
    if campo not in CAMPOS:
        raise PaginaIAError("campo_invalido", "Ese texto no se puede mejorar con IA.")
    texto = (texto or "").strip()
    if not texto and campo not in ("titular", "subtitular", "bio", "mensaje_whatsapp"):
        raise PaginaIAError("vacio", "Escribe algo primero y la IA lo mejora.")
    _cupo(user_id)
    with get_db() as db:
        u = fetch_one(db.cursor, "SELECT nombre, marca_nombre, pagina_zonas FROM chat_users WHERE id = %s", (user_id,))
    que, maximo = CAMPOS[campo]
    prompt = "\n".join(filter(None, [
        f"Reescribe {que} de la página de {u['nombre']}"
        + (f" ({u['marca_nombre']})" if u.get("marca_nombre") else "") + ".",
        f"Zonas: {', '.join(u['pagina_zonas'] or [])}" if u.get("pagina_zonas") else None,
        f"Contexto: {contexto.strip()[:300]}" if contexto and contexto.strip() else None,
        f"Texto actual: {texto}" if texto else "No hay texto todavía: escríbelo desde cero.",
        f"Cómo lo quiere: {pedido.strip()[:200]}" if pedido and pedido.strip() else "Hazlo más claro y con más gancho.",
        f"Máximo {maximo} caracteres.",
    ]))
    r = _llamar(prompt, {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"]},
                "pagina_mejorar", max_tokens=800)
    return {"texto": (r.get("texto") or "").strip()[:maximo], "quedan": _contar(user_id)}


def cupo(user_id: int) -> Dict[str, int]:
    with get_db() as db:
        usados = pagina.hoy(db.cursor, user_id, "ia")
    return {"tope": TOPE_DIARIO, "quedan": max(TOPE_DIARIO - usados, 0)}
