"""Admin › Crecimiento: forma de las respuestas (sin BD)."""
from datetime import datetime
from unittest import mock

from src.services import crecimiento_service as cs


def _con(filas_por_llamada):
    it = iter(filas_por_llamada)
    return mock.patch.object(cs, "fetch_all", side_effect=lambda *a, **k: next(it))


def test_embudo_suma_canales_y_lee_lo_de_arriba():
    canales = [
        {"canal": "directo", "cuentas": 4, "entraron": 3, "verificaron": 2, "buscaron": 3, "contacto": 1, "pagaron": 0, "ingresos": 0},
        {"canal": "compartido", "cuentas": 2, "entraron": 2, "verificaron": 2, "buscaron": 2, "contacto": 1, "pagaron": 1, "ingresos": 50000},
    ]
    share = [{"event_type": "share_viewed", "n": 100, "personas": 40}, {"event_type": "signup_clicked", "n": 5, "personas": 5}]
    with mock.patch.object(cs, "get_db"), _con([canales, share]):
        r = cs.embudo(30)
    assert [c["canal"] for c in r["canales"]] == ["compartido", "directo"]  # primero el que paga
    assert r["total"]["cuentas"] == 6 and r["total"]["ingresos"] == 50000
    assert r["compartido_arriba"] == {"vistas": 100, "personas": 40, "clic_registro": 5}


def test_cohorte_abierta_queda_vacia():
    fila = {"cohorte": datetime(2026, 10, 19), "agentes": 3, "s1": 2, "s2": 0, "s4": 0, "contacto": 1, "pago": 0,
            "cerrada_s1": True, "cerrada_s2": False, "cerrada_s4": False}
    with mock.patch.object(cs, "get_db"), _con([[fila]]):
        r = cs.cohortes(10)
    c = r["cohortes"][0]
    assert c["semana"] == "2026-10-19" and c["s1"] == 2 and c["s2"] is None and c["s4"] is None
