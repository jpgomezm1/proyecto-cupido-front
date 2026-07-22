"""Tests de las tools del Lote 1: donde_captar, capacidad, ficha, termómetro."""

import pytest
from tests.conftest import requires_db
from src.services import market_service as ms
from src.services import property_service as ps
from src.services import engagement_service as es


def test_capacidad_de_compra_math():
    # No requiere BD: solo matemática de crédito.
    r = ps.capacidad_de_compra(None, ingreso_mensual=8_000_000, cuota_inicial=150_000_000)
    assert r["precio_max"] > 150_000_000
    assert r["supuestos"]["cuota_mensual_max"] == 2_400_000
    assert "precio_max_legible" in r


def test_capacidad_sin_ingreso():
    r = ps.capacidad_de_compra(None, ingreso_mensual=0)
    assert "error" in r


@requires_db
def test_donde_captar_shape():
    d = ms.donde_captar_public(ciudad="medellin", tipo_propiedad="apartamento", top=5)
    assert "oportunidades" in d
    for o in d["oportunidades"]:
        assert o["oferta_activa"] > 0 and o["demanda_90d"] > 0
        # sin basura de zona mal cargada
        assert "apartamento" not in o["lugar"].lower()


@requires_db
def test_ficha_venta_shape(sample_property_id):
    f = ps.ficha_venta_public(sample_property_id)
    assert "propiedad" in f and "destacados" in f
    assert f["posicion_precio"] in {"barato", "en_precio", "caro", None}


@requires_db
def test_termometro_shape(sample_property_id):
    t = es.termometro_public(sample_property_id, dias=365)
    assert "interes" in t and "estado" in t
    assert set(t["interes"]) >= {"vistas", "contactos_whatsapp", "visitantes_unicos"}
