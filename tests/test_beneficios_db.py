"""
Tests de ESCRITURA de beneficios y complementos (beneficios_service, pago de un complemento).

Solo corren con FYNDER_TEST_DB_WRITE=1 contra una rama de prueba de Neon con la
migración 058 aplicada — nunca producción.
"""

import os
import random
from datetime import datetime

import pytest

if os.getenv("FYNDER_TEST_DB_WRITE") != "1":
    pytest.skip("Tests de escritura: requieren FYNDER_TEST_DB_WRITE=1 y una rama de prueba",
                allow_module_level=True)

from src.services import beneficios_service as b, pagos_service as pg, suscripcion_service as s  # noqa: E402
from src.services.db import fetch_one, get_db, scalar  # noqa: E402


@pytest.fixture
def uid(monkeypatch):
    monkeypatch.setattr(pg, "_notificar", lambda *a, **k: None)
    import src.services.analytics as analytics
    monkeypatch.setattr(analytics, "capturar", lambda *a, **k: None)
    with get_db() as db:
        u = scalar(db.cursor, "INSERT INTO chat_users (email, password_hash, nombre, activo) VALUES (%s, 'x', 'B', TRUE) RETURNING id",
                   (f"benef-{random.randint(0, 10**9)}@fynder.invalid",))
        db.conn.commit()
    yield u
    with get_db() as db:
        db.cursor.execute("DELETE FROM pagos WHERE user_id = %s", (u,))
        db.cursor.execute("DELETE FROM chat_users WHERE id = %s", (u,))
        db.conn.commit()


def _activar(u, codigo):
    with get_db() as db:
        r = b.activar_complemento_en(db.cursor, u, codigo, "test", "test")
        db.conn.commit()
    return r


def test_borroso_sin_plan_y_en_visita(uid):
    x = b.beneficios(uid)
    assert x["encargos"] == 0 and x["borroso"] == {"vitrina": True, "compradores": True, "encargos": True}
    s.activar_plan(uid, "basico", referencia_pago="t")
    assert b.beneficios(uid)["borroso"]["vitrina"] is True


def test_planes_y_complementos_se_suman(uid):
    s.activar_plan(uid, "medio", referencia_pago="t")
    x = b.beneficios(uid)
    assert (x["encargos"], x["vitrina"], x["marca_piezas"], x["compradores"]) == (2, 1, 3, 1)
    _activar(uid, "trabaja")
    x = b.beneficios(uid)
    assert (x["encargos"], x["vitrina"], x["prioridad"]) == (12, 4, 1) and x["marca_piezas"] == 3
    _activar(uid, "marca")
    x = b.beneficios(uid)
    assert x["marca_piezas"] == b.ILIMITADO and x["informes"] == 10 and x["links"] == b.ILIMITADO
    assert {c["codigo"] for c in x["complementos"]} == {"trabaja", "marca"}


def test_renovar_no_pierde_dias(uid):
    a = _activar(uid, "trabaja")
    r = _activar(uid, "trabaja")
    assert datetime.fromisoformat(r["inicio"]) == datetime.fromisoformat(a["fin"])
    assert len(b.beneficios(uid)["complementos"]) == 1


def test_pago_wompi_de_complemento(uid):
    with get_db() as db:
        db.cursor.execute("INSERT INTO pagos (referencia, user_id, plan_codigo, monto_cop) VALUES (%s, %s, 'ambos', 45000)",
                          (f"TEST-COMP-{uid}", uid))
        db.conn.commit()
    r = pg._aplicar({"reference": f"TEST-COMP-{uid}", "status": "APPROVED", "amount_in_cents": 4_500_000,
                     "currency": "COP", "id": "t", "payment_method_type": "PSE"}, "test")
    assert r["estado"] == "aprobado"
    with get_db() as db:
        p = fetch_one(db.cursor, "SELECT complemento_periodo_id, suscripcion_id FROM pagos WHERE referencia = %s",
                      (f"TEST-COMP-{uid}",))
    assert p["complemento_periodo_id"] and p["suscripcion_id"] is None
    x = b.beneficios(uid)
    assert x["encargos"] == 10 and x["marca_piezas"] == b.ILIMITADO
    with pytest.raises(s.SuscripcionError):
        s.activar_plan(uid, "trabaja", referencia_pago="t")   # un complemento no es un plan
