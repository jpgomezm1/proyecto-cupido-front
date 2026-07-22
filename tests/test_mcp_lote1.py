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


# ---- Lote 2 ----

def test_costo_credito_math():
    # cuota de crédito: función pura, sin BD.
    from src.services.property_service import _cuota_credito
    cuota = _cuota_credito(200_000_000, 0.011, 20)
    assert 1_500_000 < cuota < 3_500_000  # rango razonable


@requires_db
def test_costo_total_mensual(sample_property_id):
    c = ps.costo_total_mensual_public(sample_property_id, cuota_inicial=100_000_000)
    assert c["costo_mensual_sin_credito"] > 0
    assert "credito" in c and c["credito"]["cuota_mensual"] > 0
    assert c["componentes"]["administracion"] <= 5_000_000  # nunca la basura


@requires_db
def test_match_comprador(sample_property_id):
    m = ps.match_comprador_public(sample_property_id, presupuesto_max=5_000_000_000,
                                  habitaciones_min=1)
    assert 0 <= m["score"] <= 100
    assert m["veredicto"] in {"encaja_bien", "encaja_parcial", "flojo", "no_encaja"}


@requires_db
def test_match_dealbreaker_presupuesto(sample_property_id):
    # presupuesto imposible -> deal breaker + no_encaja
    m = ps.match_comprador_public(sample_property_id, presupuesto_max=1_000_000)
    assert "presupuesto" in m["deal_breakers"]
    assert m["veredicto"] == "no_encaja"
