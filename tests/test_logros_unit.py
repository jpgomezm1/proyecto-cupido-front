"""Rachas y premios (lógica pura de logros_service)."""
from datetime import date, timedelta

from src.services.logros_service import dias_a_pagar, hitos_ganados, racha_hasta, record, siguiente_hito

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


def test_racha_paga_cada_7_dias_y_mas_con_ia():
    assert hitos_ganados(6, 6) == []
    assert hitos_ganados(7, 3) == [{"hito": 7, "con_ia": False, "fyns": 15}]
    assert hitos_ganados(14, 14) == [{"hito": 7, "con_ia": True, "fyns": 75},
                                     {"hito": 14, "con_ia": True, "fyns": 75}]
    assert [h["fyns"] for h in hitos_ganados(21, 10)] == [75, 15, 15]


def test_siguiente_hito():
    assert siguiente_hito(0) == {"dias": 7, "faltan": 7, "fyns": 15, "fyns_ia": 75}
    assert siguiente_hito(7)["dias"] == 14
    assert siguiente_hito(20)["faltan"] == 1


def test_dias_a_pagar(monkeypatch):
    import src.services.logros_service as l
    monkeypatch.setattr(l, "FYNS_DESDE", HOY - timedelta(days=3))
    todos, ia = dias(0, 1, 2, 3, 4, 20), dias(1)
    pagos = {d["fecha"]: d["fyns"] for d in dias_a_pagar(todos, ia, HOY)}
    # Antes de FYNS_DESDE no se paga; hoy sin IA espera a que termine el día.
    assert pagos == {HOY - timedelta(days=1): 15, HOY - timedelta(days=2): 3, HOY - timedelta(days=3): 3}
    assert {d["fecha"] for d in dias_a_pagar(todos, dias(0), HOY)} >= {HOY}
