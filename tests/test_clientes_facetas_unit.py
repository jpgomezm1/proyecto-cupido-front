"""Afinar el perfil de un cliente: facetas con cuántos quedarían (sin BD ni IA)."""
from decimal import Decimal

from src.services.clientes_service import facetas


def _base(n=40):
    return [{"id": i, "habitaciones": 2 + i % 3, "banos": 1 + i % 3, "area": Decimal(60 + i * 3),
             "precio": 800_000_000 + i * 5_000_000, "cumple": ["amoblado"] if i < 4 else ["piscina"] if i % 2 else []}
            for i in range(n)]


def test_pocas_no_hay_facetas():
    assert facetas({}, _base(5)) == []


def test_facetas_cuentan_y_proponen_cambio():
    ped = {"presupuesto_min": 800_000_000, "presupuesto_max": 1_000_000_000,
           "deseables": [{"caracteristica": "amoblado", "peso": 3}, {"caracteristica": "piscina", "peso": 2}]}
    fs = {(f["grupo"], f["etiqueta"]): f for f in facetas(ped, _base())}
    assert fs[("Habitaciones", "3 o más")]["n"] == sum(1 for i in range(40) if 2 + i % 3 >= 3)
    assert fs[("Habitaciones", "3 o más")]["cambio"] == {"habitaciones_min": 3}
    assert ("Área", "Desde 100 m²") in fs                      # el área llega como Decimal y cuenta igual
    assert fs[("Presupuesto", "Hasta $900 M")]["cambio"] == {"presupuesto_max": 900_000_000}
    amoblado = fs[("Que sí o sí tenga", "Amoblado")]
    assert amoblado["n"] == 4                                  # pocos, pero justo lo que no negocia
    assert amoblado["cambio"]["obligatorias"] == ["amoblado"]
    assert [d["caracteristica"] for d in amoblado["cambio"]["deseables"]] == ["piscina"]


def test_no_repite_lo_que_ya_pidio():
    fs = facetas({"habitaciones_min": 3, "area_min": 80}, _base())
    assert not any(f["grupo"] in ("Habitaciones", "Área") for f in fs)


def test_descarta_las_que_no_quitan_nada():
    base = [{**x, "habitaciones": 3} for x in _base()]
    assert not any(f["grupo"] == "Habitaciones" for f in facetas({}, base))
