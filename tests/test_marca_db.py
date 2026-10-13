"""
Tests de ESCRITURA de "Tu marca" (marca propia, quién vio tu link, informe de captación).

Solo corren con FYNDER_TEST_DB_WRITE=1 contra una rama de prueba de Neon con la
migración 058 aplicada — nunca producción.
"""

import os
import random

import pytest

if os.getenv("FYNDER_TEST_DB_WRITE") != "1":
    pytest.skip("Tests de escritura: requieren FYNDER_TEST_DB_WRITE=1 y una rama de prueba",
                allow_module_level=True)

from src.services import (beneficios_service as b, correo_service, fyns_service as fyns,  # noqa: E402
                          marca_service as m, share_service as sh, suscripcion_service as s)
from src.services.db import get_db, scalar  # noqa: E402


@pytest.fixture
def uid(monkeypatch):
    avisos = []
    monkeypatch.setattr(correo_service, "pieza_vista", lambda *a, **k: avisos.append(a))
    with get_db() as db:
        u = scalar(db.cursor, """
            INSERT INTO chat_users (email, password_hash, nombre, telefono, activo, telefono_verificado, terminos_aceptados_at)
            VALUES (%s, 'x', 'Marca', %s, TRUE, TRUE, NOW()) RETURNING id
        """, (f"marca-{random.randint(0, 10**9)}@fynder.invalid", f"+57305{random.randint(1000000, 9999999)}"))
        db.conn.commit()
    u_avisos = (u, avisos)
    yield u_avisos
    with get_db() as db:
        db.cursor.execute("DELETE FROM chat_users WHERE id = %s", (u,))
        db.conn.commit()


def test_marca_propia_con_cupo(uid):
    u, _ = uid
    assert m.firmar(u, "ficha", "fic:1") is False                 # sin plan: con la marca de Fynder
    s.activar_plan(u, "medio", referencia_pago="t")              # Negocio: 3 piezas con marca al mes
    assert [m.firmar(u, "ficha", f"fic:{i}") for i in range(4)] == [True, True, True, False]
    with get_db() as db:
        b.activar_complemento_en(db.cursor, u, "marca", "t", "t")
        db.conn.commit()
    assert m.firmar(u, "ficha", "fic:9") is True                  # Tu marca: sin límite
    tok = sh.make_token("fic", [1], u, marca=True)
    assert sh.verify_token(tok)["m"] == 1


def test_quien_vio_sin_y_con_beneficio(uid):
    u, avisos = uid
    m.registrar_vista(u, "ficha", "fic:1", "Apto en Laureles")
    v = m.vistas(u)["piezas"][0]
    assert v["abierta"] and v["vistas"] is None and not avisos     # sin plan: solo sabe que la abrió
    s.activar_plan(u, "medio", referencia_pago="t")              # 5 links con detalle al mes
    m.registrar_vista(u, "comparativa", "cmp:1,2", "la comparativa")
    m.registrar_vista(u, "comparativa", "cmp:1,2", "la comparativa")
    v = [p for p in m.vistas(u)["piezas"] if p["clave"] == "cmp:1,2"][0]
    assert v["vistas"] == 2 and v["con_detalle"]
    assert len(avisos) == 1                                       # un aviso, no uno por vista


def test_informe_cupo_y_fyns(uid):
    u, _ = uid
    with get_db() as db:
        pid = scalar(db.cursor, "SELECT id FROM propiedades WHERE activa AND area_construida > 0 ORDER BY id DESC LIMIT 1")
    with pytest.raises(m.MarcaError) as e:
        m.generar_informe(u, pid)
    assert e.value.codigo == "sin_beneficio"
    s.activar_plan(u, "medio", referencia_pago="t")              # 1 informe al mes
    r = m.generar_informe(u, pid)
    assert r["ok"] and "/informe/" in r["link"]
    datos = m.datos_informe_publico(r["informe_id"])
    assert datos["inmueble"]["propiedad_id"] == pid and "estimacion" in datos
    with pytest.raises(m.MarcaError) as e:
        m.generar_informe(u, pid)
    assert e.value.codigo == "sin_cupo"
    with get_db() as db:
        db.cursor.execute("INSERT INTO fyns_movimientos (user_id, cantidad, motivo) VALUES (%s, 60, 'ajuste')", (u,))
        db.conn.commit()
    fyns.canjear(u, "informe")
    assert m.generar_informe(u, None, {"zona": "Laureles", "ciudad": "Medellín", "tipo": "Apartamento", "area": 90})["ok"]
