"""Tests de comparativa/brochure (tokens + render, sin red)."""
import pytest
from src.services import share_service as sh
from src.mcp_server import share_pages as sp


def test_token_roundtrip():
    tok = sh.make_token("cmp", [84, 89, 105])
    p = sh.verify_token(tok)
    assert p["k"] == "cmp" and p["ids"] == [84, 89, 105]


def test_token_tampered():
    tok = sh.make_token("fic", [84])
    with pytest.raises(sh.ShareError):
        sh.verify_token(tok[:-3] + "xxx")


def test_render_no_agent_data():
    """La comparativa/brochure NUNCA muestran datos de contacto de agente."""
    data = {"propiedades": [{
        "id": 1, "titulo": "Apto", "precio": 500000000, "precio_legible": "$500 millones",
        "ciudad": "Medellín", "zona": "El Poblado", "tipo": "Apartamento", "area": 80,
        "precio_m2": 6000000, "habitaciones": 3, "banos": 2, "parqueaderos": 1, "estrato": 5,
        "amenidades": ["Piscina"], "descripcion": "Bonito", "imagenes": [], "imagen_principal": None,
    }], "veredicto": {"mejor_valor": 1, "mas_economica": 1, "mas_amplia": 1}}
    html = sp._render_comparativa(data)
    assert "El Poblado" in html and "Piscina" in html
    # No debe filtrar datos concretos de contacto de agente.
    for leak in ("owner_phone", "3001112233", "agente_telefono", "inmobiliaria"):
        assert leak not in html.lower()


def test_links():
    # Links elegantes en el dominio de Fynder (no el del MCP).
    assert "fyndercol.netlify.app/comparar/" in sh.link_comparativa([1, 2])
    assert "fyndercol.netlify.app/ficha/" in sh.link_brochure(1)
