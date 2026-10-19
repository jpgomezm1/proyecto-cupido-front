"""
Tests de ESCRITURA del cupo del modo Análisis (prueba, plan, extra por Fyns, carreras, tope diario).

Escriben en la BD: solo corren con FYNDER_TEST_DB_WRITE=1 contra una rama de
prueba de Neon con la migración 062 aplicada — nunca contra producción.
"""

import os
import random
from concurrent.futures import ThreadPoolExecutor

import pytest

if os.getenv("FYNDER_TEST_DB_WRITE") != "1":
    pytest.skip("Tests de escritura: requieren FYNDER_TEST_DB_WRITE=1 y una rama de prueba",
                allow_module_level=True)

from src.services import analisis_service as a, fyns_service, suscripcion_service as svc  # noqa: E402
from src.services.db import get_db, scalar  # noqa: E402


@pytest.fixture
def agente():
    with get_db() as db:
        uid = scalar(db.cursor, """
            INSERT INTO chat_users (email, password_hash, nombre, activo)
            VALUES (%s, 'x', 'Prueba Análisis', TRUE) RETURNING id
        """, (f"analisis-{random.randint(0, 10**9)}@fynder.invalid",))
        db.conn.commit()
    yield uid
    with get_db() as db:
        db.cursor.execute("DELETE FROM pagos WHERE user_id = %s", (uid,))
        db.cursor.execute("DELETE FROM chat_users WHERE id = %s", (uid,))
        db.conn.commit()


def _reservar(uid):
    try:
        return a.reservar(uid, None, "¿cómo está Belén?", "test")["fuente"]
    except a.AnalisisError as e:
        return e.codigo


def _abonar(uid, n):
    with get_db() as db:
        a.abonar_en(db.cursor, uid, n, "test", "test")
        db.conn.commit()


def test_prueba_es_de_una_sola_vez(agente):
    prueba = a.cupo(agente)["total"]
    assert prueba == 5
    assert [_reservar(agente) for _ in range(prueba + 1)] == ["prueba"] * prueba + ["sin_cupo"]


def test_extra_despues_y_la_falla_no_cuenta(agente):
    for _ in range(a.cupo(agente)["total"]):
        _reservar(agente)
    _abonar(agente, 5)
    r = a.reservar(agente, None, "x", "test")
    assert r["fuente"] == "extra" and a.cupo(agente)["extra"] == 4
    a.fallo(r["id"], "falla simulada", 0.01)
    assert a.cupo(agente)["extra"] == 5
    a.terminar(a.reservar(agente, None, "x", "test")["id"], ["get_zone_stats"], 1000, 200, 0, 0.02)
    assert a.cupo(agente)["extra"] == 4


def test_plan_primero_y_sin_pasarse_en_paralelo(agente):
    _abonar(agente, 5)
    svc.activar_plan(agente, "basico", referencia_pago="test")
    c = a.cupo(agente)
    assert c["fuente"] == "plan" and c["total"] == 15 and c["restantes"] == 20
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda _: _reservar(agente), range(25)))
    assert res.count("plan") == 15 and res.count("extra") == 5 and res.count("sin_cupo") == 5
    assert a.cupo(agente)["restantes"] == 0


def test_tope_diario(agente, monkeypatch):
    monkeypatch.setattr(a, "LIMITE_DIA", 2)
    assert [_reservar(agente) for _ in range(3)] == ["prueba", "prueba", "limite_dia"]


def test_canje_de_fyns(agente):
    with get_db() as db:
        db.cursor.execute("INSERT INTO fyns_movimientos (user_id, cantidad, motivo, referencia) VALUES (%s, 60, 'ajuste', 'test')",
                          (agente,))
        db.conn.commit()
    r = fyns_service.canjear(agente, "analisis_5")
    assert r["costo"] == 50 and r["saldo"] == 10
    assert a.cupo(agente)["extra"] == 5
    with pytest.raises(fyns_service.FynsError):
        fyns_service.canjear(agente, "analisis_5")
