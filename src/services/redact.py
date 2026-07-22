"""
Saneamiento de salidas del MCP: NUNCA entregar información de contacto de agentes.

Requisito duro: bajo ninguna circunstancia el MCP puede devolver teléfonos,
nombres, correos o datos de contacto de agentes (ni del captador, ni de quien
puso un pedido, ni de terceros).

Dos capas:
1. Se ELIMINAN claves sensibles de cualquier dict que salga de una tool.
2. Se REDACTAN teléfonos que aparezcan dentro de textos libres (ej. el texto de
   un pedido), de forma conservadora para no dañar precios.

`sanitize()` se aplica centralmente a la salida de TODAS las tools (ver server.py),
así ninguna tool nueva puede filtrar por descuido.
"""

import re
from typing import Any

# Claves cuyo valor es información de contacto de un agente. Se comparan en
# minúsculas; cualquier dict que salga del MCP pierde estas claves.
SENSITIVE_KEYS = {
    "owner_phone", "telefono", "asesor", "inmobiliaria",
    "agente_captador_telefono", "agente_telefono", "agente_nombre",
    "agente_comprador_telefono", "agente_vendedor_telefono",
    "comprador_telefono", "correo_personal", "email", "nombre_agente",
    "phone", "celular", "whatsapp",
}

# Teléfonos colombianos: celular (3xx xxx xxxx), fijo, con o sin +57, con
# separadores. También números precedidos por palabras de contacto.
_PHONE_PATTERNS = [
    re.compile(r"\+?57[\s\-]?3\d{2}[\s\-]?\d{3}[\s\-]?\d{4}"),          # +57 3xx xxx xxxx
    re.compile(r"\b3\d{2}[\s\-]\d{3}[\s\-]?\d{4}\b"),                    # 3xx xxx xxxx (con separador)
    re.compile(r"(?i)(?:cel(?:ular)?|tel(?:efono|éfono)?|whats?app|wpp|contacto|llamar|escribir)\s*[:\-]?\s*\+?\d[\d\s\-]{6,13}\d"),
    re.compile(r"\b\d{7}\b"),                                            # fijo de 7 dígitos
]
_REDACTED = "[contacto oculto]"


def redact_phones(text: str) -> str:
    """Redacta teléfonos dentro de un texto libre (conservador con precios)."""
    if not text or not isinstance(text, str):
        return text
    out = text
    for pat in _PHONE_PATTERNS:
        out = pat.sub(_REDACTED, out)
    return out


def sanitize(obj: Any) -> Any:
    """
    Devuelve una copia de `obj` sin claves de contacto de agentes y con los
    teléfonos redactados en los textos. Recorre dicts y listas recursivamente.
    """
    if isinstance(obj, dict):
        clean = {}
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in SENSITIVE_KEYS:
                continue  # se elimina por completo
            clean[k] = sanitize(v)
        return clean
    if isinstance(obj, (list, tuple)):
        return [sanitize(x) for x in obj]
    if isinstance(obj, str):
        return redact_phones(obj)
    return obj
