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

# Teléfonos colombianos. Se es AGRESIVO: ante la duda, redactar. Un teléfono
# filtrado es inaceptable; redactar un precio ocasional (que igual se muestra en
# los campos estructurados) es tolerable.
_PHONE_PATTERNS = [
    # Celular con o SIN separadores: 3xx xxx xxxx / 3xxxxxxxxx, con +57 opcional.
    re.compile(r"(?<!\d)(?:\+?57[\s.\-]?)?3\d{2}[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"),
    # Número tras palabra/emoji de contacto (cel, tel, wpp, ☎, 📞, etc.).
    re.compile(r"(?i)(?:cel(?:ular)?|tel(?:efono|éfono)?|whats?app|wpp|contacto|llamar|escribir|☎|📞|📱|✆)"
               r"\s*[:\-]?\s*\+?\d[\d\s.\-]{5,13}\d"),
    # Fijo de 7 dígitos aislado.
    re.compile(r"(?<!\d)\d{7}(?!\d)"),
    # Indicativo + fijo (604 xxx xxxx).
    re.compile(r"(?<!\d)60\d[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"),
]
_REDACTED = "[contacto oculto]"

# Marcadores de firma de agente en el texto de un pedido. Desde el primero que
# aparezca, se corta el resto del texto (ahí van nombre + teléfono del agente).
_SIGNATURE_MARKERS = [
    "su red inmobiliaria", "red inmobiliaria", "hagamos negocios",
    "☎", "📞", "📱", "✆", "🌻", "🫱", "wpp", "whatsapp",
    "asesor", "agente:", "atentamente", "cordial", "inmobiliaria",
]


# Una línea "parece nombre de persona": corta, 1-4 palabras, mayúscula inicial,
# sin dígitos ni URLs. Usada para cortar el nombre que precede a un teléfono.
_NAME_LINE = re.compile(r"^[\*\s]*[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ.]+){0,3}[\*\s]*$")
_HAS_PHONE = re.compile(r"3\d{2}[\s.\-]?\d{3}[\s.\-]?\d{4}|\d{7}")


def _cut_signature(text: str) -> str:
    """
    Corta el bloque de firma del agente (nombre + teléfono) que suele ir al final
    del texto de un pedido. Estrategia por líneas: corta desde el primer marcador
    de firma, desde la primera línea con teléfono, e incluye hacia atrás las
    líneas cortas que parecen un nombre propio (la firma).
    """
    lines = text.split("\n")
    cut_idx = len(lines)

    for i, ln in enumerate(lines):
        stripped = ln.strip()
        low = stripped.lower()
        # Marcador de firma al INICIO de la línea (☎, 🌻, "su red", "asesor"...).
        empieza_marcador = any(low.startswith(m) or low[:3] in m for m in _SIGNATURE_MARKERS if m)
        marcador_en_linea = any(m in low for m in _SIGNATURE_MARKERS)
        tiene_tel = bool(_HAS_PHONE.search(ln))
        # Línea de PURA firma: corta y con teléfono, o empieza con marcador.
        es_firma = (empieza_marcador
                    or (tiene_tel and len(stripped) <= 45)
                    or (marcador_en_linea and len(stripped) <= 45))
        if es_firma:
            cut_idx = i
            break

    # Retroceder sobre líneas vacías o que parezcan un nombre (la firma).
    j = cut_idx - 1
    while j >= 0:
        s = lines[j].strip()
        if s == "" or _NAME_LINE.match(s):
            j -= 1
        else:
            break
    cut_idx = j + 1

    return "\n".join(lines[:cut_idx]).rstrip(" -*_·\n\t")


def redact_phones(text: str, cut_signatures: bool = False) -> str:
    """
    Redacta teléfonos dentro de un texto libre (agresivo con contactos,
    conservador con montos escritos con separadores).

    `cut_signatures=True` además corta el bloque de firma del agente — se usa
    para el texto de pedidos, que suele terminar con nombre + teléfono.
    """
    if not text or not isinstance(text, str):
        return text
    out = _cut_signature(text) if cut_signatures else text
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
