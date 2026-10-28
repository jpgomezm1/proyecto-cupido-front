"""Títulos de las conversaciones de Findy (E2): sin «3.0 hab», sin «B», y distinguibles entre sí."""
from src.core.search_context import generate_conversation_name, millones_corto
from src.core.search_context import nombre_compradores as _nombre_compradores


def test_millones_siempre_en_millones():
    assert millones_corto(650_000_000) == "$650 M"
    assert millones_corto(1_800_000_000) == "$1.800 M"


def test_busqueda_sin_decimales_ni_b():
    n = generate_conversation_name({"tipo_propiedad": "Apartamento", "ubicaciones": ["Laureles"],
                                    "habitaciones_min": 3.0, "precio_max": 1_400_000_000})
    assert n == "Apto en Laureles · 3+ hab · hasta $1.400 M"
    assert "3.0" not in n and "B" not in n


def test_busqueda_varias_zonas():
    n = generate_conversation_name({"tipo_propiedad": ["Casa"], "ubicaciones": ["Envigado", "Sabaneta", "La Estrella"]})
    assert n == "Casa en Envigado o Sabaneta +1"


def test_busqueda_sin_datos_no_nombra():
    assert generate_conversation_name({"tipo_propiedad": "Apartamento"}) is None


def test_compradores_con_area_y_precio():
    a = _nombre_compradores({"tipo": "apartamento", "zona": "Laureles", "area_m2": 95.4, "precio": 640_000_000})
    b = _nombre_compradores({"tipo": "apartamento", "zona": "Laureles", "area_m2": 120, "precio": 890_000_000})
    assert a == "Compradores · Apto en Laureles · 95 m² · $640 M"
    assert a != b
