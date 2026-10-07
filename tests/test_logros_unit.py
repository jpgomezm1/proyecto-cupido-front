"""Rachas y premios (lógica pura de logros_service)."""
from datetime import date, timedelta

from src.services.logros_service import hitos_ganados, racha_hasta, record, siguiente_hito

HOY = date(2026, 10, 7)


def dias(*atras):
    return {HOY - timedelta(days=k) for k in atras}


def test_racha_cuenta_hasta_hoy():
    r = racha_hasta(dias(0, 1, 2), HOY)
    assert r["dias"] == 3 and r["hoy"] and r["inicio"] == HOY - timedelta(days=2)


def test_racha_sigue_viva_si_hoy_aun_no_hay_uso():
    r = racha_hasta(dias(1, 2, 3, 4), HOY)
    assert r["dias"] == 4 and not r["hoy"]


def test_racha_se_rompe_con_un_dia_sin_uso():
    assert racha_hasta(dias(2, 3, 4), HOY)["dias"] == 0
    assert racha_hasta(dias(0, 2, 3), HOY)["dias"] == 1


def test_record():
    assert record(dias(0, 1, 5, 6, 7, 8)) == 4
    assert record(set()) == 0


def test_hitos_doble_con_ia():
    assert hitos_ganados(2, 2) == []
    assert hitos_ganados(3, 1) == [{"hito": 3, "con_ia": False, "llaves": 1}]
    assert hitos_ganados(7, 7) == [{"hito": 3, "con_ia": True, "llaves": 2},
                                   {"hito": 7, "con_ia": True, "llaves": 4}]
    assert [h["llaves"] for h in hitos_ganados(14, 5)] == [2, 2, 3]


def test_siguiente_hito():
    assert siguiente_hito(0) == {"dias": 3, "faltan": 3, "llaves": 1, "llaves_ia": 2}
    assert siguiente_hito(5)["dias"] == 7
    assert siguiente_hito(14) is None
