"""
Tests de ESCRITURA de la Vitrina (acceso por plan, Fyns, exclusividad de 72 h y tope de 3 por contacto).

Solo corren con FYNDER_TEST_DB_WRITE=1 contra una rama de prueba de Neon con la
migración 058 aplicada — nunca producción.
"""

import os
import random
from datetime import timedelta

import pytest

if os.getenv("FYNDER_TEST_DB_WRITE") != "1":
    pytest.skip("Tests de escritura: requieren FYNDER_TEST_DB_WRITE=1 y una rama de prueba",
                allow_module_level=True)

from src.services import fyns_service as fyns, suscripcion_service as s, vitrina_service as v  # noqa: E402
from src.services.db import fetch_one, get_db, scalar  # noqa: E402


def _usuario():
    with get_db() as db:
        uid = scalar(db.cursor, """
            INSERT INTO chat_users (email, password_hash, nombre, telefono, activo, telefono_verificado, terminos_aceptados_at)
            VALUES (%s, 'x', 'V', %s, TRUE, TRUE, NOW()) RETURNING id
        """, (f"vit-{random.randint(0, 10**9)}@fynder.invalid", f"+57304{random.randint(1000000, 9999999)}"))
        db.conn.commit()
    return uid


@pytest.fixture
def escena():
    semana = v.lunes()
    usuarios = [_usuario() for _ in range(4)]
    with get_db() as db:
        c = db.cursor
        pid = scalar(c, "SELECT id FROM propiedades WHERE activa ORDER BY id DESC LIMIT 1")
        c.execute("DELETE FROM vitrina_items WHERE semana = %s", (semana,))
        c.execute("""INSERT INTO vitrina_items (semana, tipo, ref_id, exclusiva_hasta) VALUES (%s, 'propiedad', %s, NOW() + INTERVAL '72 hours')""",
                  (semana, pid))
        db.conn.commit()
    yield usuarios, pid, semana
    with get_db() as db:
        c = db.cursor
        c.execute("DELETE FROM vitrina_items WHERE semana = %s AND ref_id = %s", (semana, pid))
        for u in usuarios:
            c.execute("DELETE FROM chat_users WHERE id = %s", (u,))
        db.conn.commit()


def test_borrosa_sin_acceso_y_completa_con_cierre(escena):
    (visita, cierre, *_), pid, _ = escena
    s.activar_plan(visita, "basico", referencia_pago="t")
    r = v.ver(visita)
    assert r["borrosa"] and r["items"] == [] and r["resumen"]["inmuebles"] >= 1
    s.activar_plan(cierre, "pro", referencia_pago="t")
    r = v.ver(cierre)
    assert not r["borrosa"] and any(i["ref_id"] == pid for i in r["items"]) and r["acceso"] == "plan"


def test_negocio_una_al_mes(escena):
    (negocio, *_), _, semana = escena
    s.activar_plan(negocio, "medio", referencia_pago="t")
    with get_db() as db:   # ya usó la de este mes en otra semana
        db.cursor.execute("INSERT INTO vitrina_accesos (user_id, semana, fuente) VALUES (%s, %s, 'plan')",
                          (negocio, semana - timedelta(days=7) if (semana - timedelta(days=7)).month == semana.month else semana + timedelta(days=7)))
        db.conn.commit()
    assert v.ver(negocio)["borrosa"]


def test_con_fyns(escena):
    (u, *_), _, _ = escena
    with get_db() as db:
        db.cursor.execute("INSERT INTO fyns_movimientos (user_id, cantidad, motivo) VALUES (%s, 150, 'ajuste')", (u,))
        db.conn.commit()
    assert v.ver(u)["borrosa"]
    fyns.canjear(u, "vitrina")
    assert v.ver(u)["acceso"] == "fyns"
    with pytest.raises(fyns.FynsError):
        fyns.canjear(u, "vitrina")   # ya la tiene


def test_exclusividad_y_tope_de_tres(escena):
    (fuera, miembro, *otros), pid, _ = escena
    s.activar_plan(miembro, "pro", referencia_pago="t")
    with get_db() as db:
        assert v.regla_desbloqueo(db.cursor, fuera, "propiedad", pid)["error"] == "vitrina_exclusiva"
        assert v.regla_desbloqueo(db.cursor, miembro, "propiedad", pid) is None
        for u in otros + [fuera]:   # 3 agentes ya lo abrieron
            db.cursor.execute("""INSERT INTO desbloqueos (user_id, tipo, ref_id, fuente_credito) VALUES (%s, 'propiedad', %s, 'gratis')""",
                              (u, pid))
        db.conn.commit()
        assert v.regla_desbloqueo(db.cursor, miembro, "propiedad", pid)["error"] == "vitrina_agotada"
        assert s.preview_desbloqueo(miembro, "propiedad", pid).get("error") == "vitrina_agotada"
        # Pasadas las 72 h, vuelve a ser un contacto normal.
        db.cursor.execute("UPDATE vitrina_items SET exclusiva_hasta = NOW() - INTERVAL '1 minute' WHERE ref_id = %s", (pid,))
        db.conn.commit()
        assert v.regla_desbloqueo(db.cursor, fuera, "propiedad", pid) is None
        db.cursor.execute("DELETE FROM desbloqueos WHERE ref_id = %s AND fuente_credito = 'gratis' AND user_id = ANY(%s)",
                          (pid, otros + [fuera]))
        db.conn.commit()


def test_proponer_y_publicar_no_revientan():
    assert set(v.proponer()) == {"propiedad", "pedido"}
    assert "semana" in v.publicar_semana()
