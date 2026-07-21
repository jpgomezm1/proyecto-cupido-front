"""
Utilidades de texto, teléfono y formato compartidas por la capa de servicios.

Sin dependencias externas: solo stdlib. La idea es no arrastrar el monolito de
`search_agent` para cosas simples (normalización de acentos, teléfonos, moneda).
"""

import re
import unicodedata
from typing import List, Optional

# Mapa de acentos frecuentes en español -> ascii, para usar dentro de SQL con
# translate() y así hacer matching accent-insensitive SIN depender de la
# extensión `unaccent` de Postgres (que puede no estar habilitada en Neon).
_ACCENT_FROM = "áéíóúüñÁÉÍÓÚÜÑ"
_ACCENT_TO = "aeiouunAEIOUUN"


def strip_accents(text: Optional[str]) -> str:
    """Quita acentos/diacríticos de un string (á -> a, ñ -> n)."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def accent_lower_raw(expr: str) -> str:
    """
    Normaliza cualquier expresión SQL *controlada por el código* a minúsculas sin
    acentos. Usar SOLO con expresiones literales del propio código (ej.
    "criterios_extraidos::text"), nunca con entrada de usuario.
    """
    return f"translate(lower({expr}), '{_ACCENT_FROM}', '{_ACCENT_TO}')"


def accent_insensitive_expr(column: str) -> str:
    """
    Devuelve una expresión SQL que normaliza `column` a minúsculas sin acentos,
    para comparar con un parámetro también normalizado.

    Ej: accent_insensitive_expr("p.ciudad") ->
        "translate(lower(p.ciudad), 'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN')"

    `column` DEBE ser un identificador controlado por el código (nunca entrada
    de usuario), ya que se interpola directamente.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", column):
        raise ValueError(f"Identificador de columna inválido: {column!r}")
    return accent_lower_raw(column)


def like_param(value: Optional[str]) -> str:
    """Normaliza un valor de usuario para comparar con `accent_insensitive_expr`
    usando LIKE con comodines (%valor%)."""
    return f"%{strip_accents(value).lower().strip()}%"


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    """
    Normaliza un teléfono a sus últimos 10 dígitos (el formato canónico de
    scoping en la BD: `RIGHT(REGEXP_REPLACE(...), 10)`). Colombia usa 10 dígitos
    nacionales; los prefijos +57 varían, por eso se comparan los últimos 10.
    """
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    return digits[-10:] if len(digits) >= 10 else digits


def split_image_urls(raw: Optional[str]) -> List[str]:
    """`propiedades.imagenes_urls` guarda URLs separadas por '|'."""
    if not raw:
        return []
    return [u.strip() for u in str(raw).split("|") if u.strip()]


def format_cop(value: Optional[float]) -> str:
    """
    Formatea un monto en pesos colombianos como lo diría un agente.

    IMPORTANTE: en español "billón" = 10^12, NO mil millones. Nunca se usa "B".
    Todo se expresa en MILLONES con separador de miles de punto (formato CO):
      650.000.000    -> "$650 millones"
      1.290.000.000  -> "$1.290 millones"
      8.770.000      -> "$8,8 millones"   (precio/m²)
      950.000        -> "$950.000"
    """
    if value is None:
        return "N/D"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "N/D"
    if v >= 1_000_000:
        millones = v / 1_000_000
        if millones >= 100:
            # Entero con separador de miles de punto (1290 -> "1.290").
            num = f"{millones:,.0f}".replace(",", ".")
        else:
            # Un decimal con coma decimal (8.77 -> "8,8").
            num = f"{millones:.1f}".replace(".", ",")
        return f"${num} millones"
    # Menos de un millón: monto completo con separador de miles de punto.
    return "$" + f"{v:,.0f}".replace(",", ".")
