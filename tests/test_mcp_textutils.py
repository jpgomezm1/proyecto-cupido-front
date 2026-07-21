"""Tests unitarios de utilidades de texto/teléfono (sin BD)."""

from src.services.textutils import (
    strip_accents, normalize_phone, like_param, format_cop,
    split_image_urls, accent_insensitive_expr,
)
import pytest


def test_strip_accents():
    assert strip_accents("Medellín") == "Medellin"
    assert strip_accents("El Poblado") == "El Poblado"
    assert strip_accents("Bogotá Ñu") == "Bogota Nu"
    assert strip_accents(None) == ""


def test_normalize_phone_last10():
    assert normalize_phone("+573122655340") == "3122655340"
    assert normalize_phone("57 312 265 5340") == "3122655340"
    assert normalize_phone("3122655340") == "3122655340"
    assert normalize_phone("abc") is None
    assert normalize_phone(None) is None


def test_like_param_normalizes():
    assert like_param("El Poblado") == "%el poblado%"
    assert like_param("Medellín") == "%medellin%"


def test_format_cop():
    assert format_cop(1_290_000_000) == "$1.29B"
    assert format_cop(650_000_000) == "$650M"
    assert format_cop(None) == "N/D"


def test_split_image_urls():
    assert split_image_urls("a|b|c") == ["a", "b", "c"]
    assert split_image_urls("  x | | y ") == ["x", "y"]
    assert split_image_urls(None) == []


def test_accent_insensitive_expr_validates_identifier():
    assert "translate(lower(p.ciudad)" in accent_insensitive_expr("p.ciudad")
    with pytest.raises(ValueError):
        accent_insensitive_expr("p.ciudad); DROP TABLE x;--")
