"""
Tests de ESCRITURA del cupo de fotos con IA (prueba, plan, paquetes, carreras, tope diario).

Escriben en la BD: solo corren con FYNDER_TEST_DB_WRITE=1 contra una rama de
prueba de Neon con la migración 056 aplicada — nunca contra producción.
"""

import os
import random
from concurrent.futures import ThreadPoolExecutor

import pytest

if os.getenv("FYNDER_TEST_DB_WRITE") != "1":
    pytest.skip("Tests de escritura: requieren FYNDER_TEST_DB_WRITE=1 y una rama de prueba",
                allow_module_level=True)

from src.services import fotos_ia_service as f, suscripcion_service as svc  # noqa: E402
from src.services.db import get_db, scalar  # noqa: E402

URL = "https://ejemplo.com/foto.jpg"


@pytest.fixture
def agente():
    with get_db() as db:
        uid = scalar(db.cursor, """
            INSERT INTO chat_users (email, password_hash, nombre, activo)
            VALUES (%s, 'x', 'Prueba Fotos', TRUE) RETURNING id
        """, (f"fotos-{random.randint(0, 10**9)}@fynder.invalid",))
        pid = scalar(db.cursor, "SELECT id FROM propiedades LIMIT 1")
        db.conn.commit()
    yield uid, pid
    with get_db() as db:
        db.cursor.execute("DELETE FROM pagos WHERE user_id = %s", (uid,))
        db.cursor.execute("DELETE FROM chat_users WHERE id = %s", (uid,))
        db.conn.commit()


def _reservar(uid, pid):
    try:
        return f._reservar(uid, pid, URL)["fuente"]
    except f.FotoError as e:
        return e.codigo


def _abonar(uid, codigo):
    with get_db() as db:
        f.abonar_en(db.cursor, uid, codigo, "test", "test")
        db.conn.commit()


def test_prueba_es_de_una_sola_vez(agente):
    uid, pid = agente
    prueba = f.cupo(uid)["total"]
    assert [_reservar(uid, pid) for _ in range(prueba + 1)] == ["prueba"] * prueba + ["sin_cupo"]


def test_paquete_se_usa_despues_y_la_falla_no_cuenta(agente):
    uid, pid = agente
    for _ in range(f.cupo(uid)["total"]):
        _reservar(uid, pid)
    _abonar(uid, "fotos_10")
    assert f.cupo(uid)["extra"] == 10
    r = f._reservar(uid, pid, URL)
    assert r["fuente"] == "extra" and f.cupo(uid)["extra"] == 9
    f._fallo(r["id"], "falla simulada")
    assert f.cupo(uid)["extra"] == 10


def test_plan_primero_y_sin_pasarse_en_paralelo(agente):
    uid, pid = agente
    _abonar(uid, "fotos_10")
    svc.activar_plan(uid, "basico", referencia_pago="test")
    c = f.cupo(uid)
    assert c["fuente"] == "plan" and c["restantes"] == c["total"] + 10
    disponibles = c["restantes"]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda _: _reservar(uid, pid), range(disponibles + 5)))
    assert res.count("plan") == c["total"] and res.count("extra") == 10 and res.count("sin_cupo") == 5
    assert f.cupo(uid)["restantes"] == 0


def test_tope_diario(agente, monkeypatch):
    uid, pid = agente
    _abonar(uid, "fotos_10")
    monkeypatch.setattr(f, "LIMITE_DIA", 2)
    assert [_reservar(uid, pid) for _ in range(3)] == ["prueba", "prueba", "limite_dia"]
