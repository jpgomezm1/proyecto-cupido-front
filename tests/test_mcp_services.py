"""
Tests de integración de la capa de servicios contra la BD real.

TODOS son de solo lectura (o rechazos que no escriben), por lo que son seguros
de correr contra producción. Hacen skip si no hay conexión.
"""

import pytest

from tests.conftest import requires_db
from src.services import market_service as ms
from src.services import property_service as ps
from src.services import diagnosis_service as ds
from src.services import write_service as w
from src.services.identity_service import AgentIdentity, resolve_agent


@requires_db
def test_zone_stats_shape():
    z = ms.get_zone_stats(ciudad="medellin", tipo_propiedad="apartamento")
    assert z["inventario_activo"] >= 0
    assert "precio" in z and "mediana" in z["precio"]
    assert "mix_habitaciones" in z


@requires_db
def test_zone_stats_accent_insensitive():
    con = ms.get_zone_stats(ciudad="medellín")["inventario_activo"]
    sin = ms.get_zone_stats(ciudad="medellin")["inventario_activo"]
    assert con == sin and con > 0


@requires_db
def test_demand_and_balance():
    d = ms.get_demand_stats(zona="poblado")
    assert d["demanda_total"] >= 0
    b = ms.get_supply_demand_balance(ciudad="medellin", zona="laureles", tipo_propiedad="apartamento")
    assert b["clasificacion"] in {"caliente", "equilibrado", "frio", "sin_oferta"}
    assert "detalle_oferta" in b and "detalle_demanda" in b


@requires_db
def test_get_property_and_comparables(sample_property_id):
    p = ps.get_property_public(sample_property_id)
    assert p and p["id"] == sample_property_id
    assert "precio_m2" in p and "imagenes_urls" in p
    c = ps.get_comparables_public(sample_property_id, limit=10)
    assert c["nivel_comparacion"] in {"zona", "ciudad"}
    assert c["total_comparables"] >= 0


@requires_db
def test_compare_needs_two():
    r = ps.compare_public([1])
    assert "error" in r


@requires_db
def test_diagnose_shape(sample_property_id):
    d = ds.diagnose_public(sample_property_id)
    assert d["veredicto"] in {"problema_critico", "mejorable", "ajustes_menores", "saludable"}
    assert isinstance(d["hallazgos"], list)
    assert "posicion_mercado" in d and "demanda" in d


@requires_db
def test_find_buyers_shape(sample_property_id):
    b = ds.find_buyers_public(sample_property_id, limit=5)
    assert b["total_compradores"] >= 0
    assert isinstance(b["compradores"], list)


@requires_db
def test_estimate_price():
    e = ps.estimate_price_public(ciudad="medellin", zona="el poblado",
                                 tipo_propiedad="apartamento", area_construida=80)
    assert e["muestra_comparables"] >= 0
    if e.get("precio_estimado"):
        assert e["precio_estimado"] > 0


@requires_db
def test_resolve_agent_invalid_token():
    assert resolve_agent("token-que-no-existe-xyz") is None
    assert resolve_agent("") is None
    assert resolve_agent(None) is None


@requires_db
def test_write_rejects_unowned_property(sample_property_id):
    """Un agente con teléfono falso NO puede proponer cambios sobre un inmueble
    que no captó. No escribe nada (propose es de solo lectura)."""
    fake_agent = AgentIdentity(user_id=-1, email="x@x.com", nombre="Fake",
                               telefono="+570000000000", telefono_10="0000000000")
    with pytest.raises(w.WriteError):
        w.propose_price_update(fake_agent, sample_property_id, 500_000_000)
