"""Tests del blindaje de privacidad: nunca entregar contacto de agentes."""

from src.services.redact import sanitize, redact_phones, SENSITIVE_KEYS


def test_sanitize_elimina_claves_contacto():
    d = {"id": 1, "precio": 500, "owner_phone": "+573001234567", "asesor": "Juan",
         "inmobiliaria": "X", "telefono": "3001112233", "zona": "El Poblado"}
    c = sanitize(d)
    assert "owner_phone" not in c and "asesor" not in c
    assert "inmobiliaria" not in c and "telefono" not in c
    assert c["zona"] == "El Poblado" and c["precio"] == 500  # lo legítimo se queda


def test_sanitize_recursivo():
    d = {"compradores": [{"agente_telefono": "3001", "agente_nombre": "Ana", "busca": "apto"}]}
    c = sanitize(d)
    assert "agente_telefono" not in c["compradores"][0]
    assert "agente_nombre" not in c["compradores"][0]
    assert c["compradores"][0]["busca"] == "apto"


def test_redact_phones():
    assert "[contacto oculto]" in redact_phones("llámame al +57 300 123 4567")
    assert "[contacto oculto]" in redact_phones("celular 3001234567")
    # no daña montos en millones
    assert redact_phones("hasta 3000 millones") == "hasta 3000 millones"


def test_claves_sensibles_cubren_lo_clave():
    for k in ("owner_phone", "agente_telefono", "agente_nombre", "asesor", "telefono"):
        assert k in SENSITIVE_KEYS
