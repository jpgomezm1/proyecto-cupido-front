"""Valorador para propietarios (sin BD): niveles de comparación, reglas para abrir y la lista del agente."""
from datetime import datetime, timezone
from unittest import mock

import pytest

from src.services import valorador_service as vs


def test_medellin_no_sube_a_todo_el_municipio():
    niveles = vs._niveles({"id": 1, "nombre": "Conquistadores", "comuna": "11 - Laureles-Estadio", "municipio": "Medellín"})
    assert [n["nivel"] for n in niveles] == ["barrio", "comuna"]


def test_otro_municipio_sube_del_barrio_al_municipio():
    niveles = vs._niveles({"id": 2, "nombre": "Zuñiga", "comuna": None, "municipio": "Envigado"})
    assert [n["nivel"] for n in niveles] == ["barrio", "municipio"]


def test_rango_usa_el_primer_nivel_con_muestra_suficiente():
    respuestas = iter([{"muestra": 3, "p25": 1, "p50": 1, "p75": 1},                     # barrio: pocos
                       {"muestra": 40, "p25": 6_000_000, "p50": 7_000_000, "p75": 8_000_000}])
    niveles = vs._niveles({"id": 1, "nombre": "B", "comuna": "C", "municipio": "Medellín"})
    with mock.patch.object(vs, "fetch_one", side_effect=lambda *a, **k: next(respuestas)):
        r = vs._rango(None, "Venta", "apartamento", 100, 3, niveles)
    assert r["nivel"] == "comuna" and r["muestra"] == 40
    assert (r["bajo"], r["medio"], r["alto"]) == (600_000_000, 700_000_000, 800_000_000)


def test_sin_comparables_no_inventa_rango():
    niveles = vs._niveles({"id": 1, "nombre": "B", "comuna": None, "municipio": "La Ceja"})
    with mock.patch.object(vs, "fetch_one", return_value={"muestra": 2, "p50": 5}):
        assert vs._rango(None, "Arriendo", "casa", 80, None, niveles) is None


@pytest.mark.parametrize("r,error", [
    ({"agente_id": 9, "estado": "activa", "vencida": False}, "no_disponible"),   # es de otro agente
    ({"agente_id": None, "estado": "retirada", "vencida": False}, "no_disponible"),
    ({"agente_id": None, "estado": "activa", "vencida": True}, "no_disponible"),
    ({"agente_id": None, "estado": "activa", "vencida": False}, None),
    ({"agente_id": 7, "estado": "activa", "vencida": False}, None),              # el de su página
])
def test_reglas_para_abrir(r, error):
    res = vs.regla_desbloqueo(None, 7, r)
    assert (res or {}).get("error") == error


def test_la_lista_oculta_los_agotados_salvo_si_ya_lo_abri_o_es_mio():
    base = {"tipo_propiedad": "apartamento", "barrio": "B", "comuna": None, "municipio": "M", "area": 90,
            "habitaciones": 3, "banos": 2, "intencion": "vender", "plazo": "ya", "resultado": {},
            "verificada_at": datetime(2026, 10, 20, tzinfo=timezone.utc)}
    filas = [{**base, "id": 1, "propio": False, "abiertos": 3, "desbloqueado": False},
             {**base, "id": 2, "propio": False, "abiertos": 3, "desbloqueado": True},
             {**base, "id": 3, "propio": True, "abiertos": 3, "desbloqueado": False},
             {**base, "id": 4, "propio": False, "abiertos": 1, "desbloqueado": False}]
    with mock.patch.object(vs, "get_db"), mock.patch.object(vs, "fetch_all", return_value=filas):
        r = vs.para_agente(7)
    assert [i["id"] for i in r["items"]] == [2, 3, 4]
    assert "telefono" not in r["items"][0] and "nombre" not in r["items"][0]


def test_contacto_exige_autorizacion_y_celular():
    with pytest.raises(vs.ValoradorError) as e:
        vs.pedir_contacto("t", {"nombre": "Ana", "telefono": "3001234567", "intencion": "vender", "acepta": False})
    assert e.value.campo == "acepta"
    with pytest.raises(vs.ValoradorError) as e:
        vs.pedir_contacto("t", {"nombre": "Ana", "telefono": "6041234567", "intencion": "vender", "acepta": True})
    assert e.value.campo == "telefono"
