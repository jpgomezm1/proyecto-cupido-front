"""Tests de inteligencia de ubicación (funciones puras + parseo, sin red)."""

from src.services.location_service import (
    _haversine_m, _categoria_de_tags, _fmt_dist, _build_query,
)


def test_haversine_conocida():
    # ~1.11 km por 0.01 grados de latitud.
    d = _haversine_m(6.20, -75.57, 6.21, -75.57)
    assert 1050 < d < 1150


def test_categoria_mapping():
    assert _categoria_de_tags({"amenity": "school"}) == "colegios"
    assert _categoria_de_tags({"amenity": "kindergarten"}) == "colegios"
    assert _categoria_de_tags({"amenity": "university"}) == "universidades"
    assert _categoria_de_tags({"amenity": "hospital"}) == "salud"
    assert _categoria_de_tags({"railway": "station"}) == "metro"
    assert _categoria_de_tags({"shop": "supermarket"}) == "supermercados"
    assert _categoria_de_tags({"shop": "mall"}) == "centros_comerciales"
    assert _categoria_de_tags({"leisure": "park"}) == "parques"
    assert _categoria_de_tags({"amenity": "toilets"}) is None


def test_fmt_dist():
    assert _fmt_dist(500) == "500 m"
    assert _fmt_dist(1500) == "1.5 km"


def test_build_query_incluye_categorias():
    q = _build_query(6.21, -75.56)
    assert "school" in q and "railway" in q and "supermarket" in q
    assert "around:" in q and "out center" in q
