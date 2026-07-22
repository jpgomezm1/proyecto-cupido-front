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
    # celular de 10 dígitos SIN separadores (el caso que se filtraba)
    assert "3113498087" not in redact_phones("contacto 3113498087")
    # no daña montos en millones
    assert redact_phones("hasta 3000 millones") == "hasta 3000 millones"


def test_cut_signature_pedidos_reales():
    """El texto de un pedido no debe filtrar nombre ni teléfono de agente."""
    firmados = [
        "Apto Castropol, 3 alcobas, 1.200 millones\n\n*SU RED INMOBILIARIA*\n🌻 *Ana Sierra*\n☎️ *3113498087*",
        "APTO POBLADO, 3 hab, piscina\nPresupuesto $600.000.000\n\nLuisa Morales \n3108287868",
        "Busco apto poblado 3 hab, contacto 300 123 4567 wpp",
    ]
    prohibidos = ["3113498087", "3108287868", "3001234567", "300 123 4567",
                  "Ana Sierra", "Luisa Morales"]
    for t in firmados:
        out = redact_phones(t, cut_signatures=True)
        for p in prohibidos:
            assert p not in out, f"FUGA: '{p}' en {out!r}"
    # el contenido útil (qué busca, presupuesto) se conserva
    out2 = redact_phones("Busco apto 3 hab poblado, 800 millones\n\nPedro Ruiz\n3001234567", cut_signatures=True)
    assert "800 millones" in out2 and "poblado" in out2.lower()


def test_claves_sensibles_cubren_lo_clave():
    for k in ("owner_phone", "agente_telefono", "agente_nombre", "asesor", "telefono"):
        assert k in SENSITIVE_KEYS
