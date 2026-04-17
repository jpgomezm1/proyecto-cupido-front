"""Teléfono helpers.

Normaliza números colombianos al formato canonico `+57XXXXXXXXXX`.

La misma función se usa en:
- chat_users_admin.create_user / update_user
- chat_auth.update_profile
- properties.scrape_wasi / scrape_tu360 / scrape_lobbie

Así el `telefono` guardado en `chat_users` siempre matchea con el
`agente_captador_telefono` guardado en `propiedades`, y el filtro de
"Mis Propiedades" en el front funciona sin ambigüedad.
"""

import re
from typing import Optional


def normalize_colombia_phone(phone: Optional[str]) -> Optional[str]:
    """Normaliza un teléfono colombiano a `+57XXXXXXXXXX`.

    Comportamiento:
    - None o string vacío (incluso solo whitespace) → None
    - "3001234567" → "+573001234567"
    - "03001234567" → "+573001234567" (strip leading 0)
    - "573001234567" → "+573001234567"
    - "+573001234567" → "+573001234567"
    - "300 123-4567" → "+573001234567"
    - Si ya trae otro prefijo internacional (ej: "+1..."), se respeta.
    """
    if phone is None:
        return None

    raw = phone.strip()
    if not raw:
        return None

    has_plus = raw.startswith('+')
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return None

    if has_plus:
        return '+' + digits

    if digits.startswith('57') and len(digits) >= 12:
        return '+' + digits

    return '+57' + digits.lstrip('0')
