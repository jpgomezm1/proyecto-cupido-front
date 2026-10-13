"""
Tests de ESCRITURA de "compradores para tus inmuebles" (alertas tipo 'comprador').

Solo corren con FYNDER_TEST_DB_WRITE=1 contra una rama de prueba de Neon con la
migración 058 aplicada — nunca producción. Toman un inmueble activo de la rama y
le ponen como captador al agente de prueba.
"""

import os
import random

import pytest

if os.getenv("FYNDER_TEST_DB_WRITE") != "1":
    pytest.skip("Tests de escritura: requieren FYNDER_TEST_DB_WRITE=1 y una rama de prueba",
                allow_module_level=True)

from src.services import alertas_service as al, clientes_service as cli, red_service as red, suscripcion_service as s  # noqa: E402
from src.services.db import fetch_one, get_db, scalar  # noqa: E402


def _usuario(nombre):
    tel = f"+57302{random.randint(1000000, 9999999)}"
    with get_db() as db:
        uid = scalar(db.cursor, """
            INSERT INTO chat_users (email, password_hash, nombre, telefono, activo, telefono_verificado, terminos_aceptados_at)
            VALUES (%s, 'x', %s, %s, TRUE, TRUE, NOW()) RETURNING id
        """, (f"comp-{random.randint(0, 10**9)}@fynder.invalid", nombre, tel))
        db.conn.commit()
    return uid, tel


@pytest.fixture
def escena():
    dueno, tel = _usuario("Dueño")
    comprador, _ = _usuario("Comprador")
    with get_db() as db:
        c = db.cursor
        p = fetch_one(c, """
            SELECT p.id, p.telefono, p.precio, p.zona, p.ciudad, p.tipo_propiedad FROM propiedades p
            WHERE p.activa AND p.precio > 200000000 AND p.zona IS NOT NULL AND p.tipo_propiedad ILIKE 'apartamento%%'
            ORDER BY p.id DESC LIMIT 1
        """)
        c.execute("UPDATE propiedades SET telefono = %s WHERE id = %s", (tel, p["id"]))
        c.execute("UPDATE alertas_cursor SET valor = NOW() - INTERVAL '1 minute' WHERE clave = 'pedidos'")
        c.execute("UPDATE alertas_cursor SET valor = NOW() WHERE clave IN ('inmuebles', 'precios')")
        db.conn.commit()
    yield dueno, comprador, p
    with get_db() as db:
        c = db.cursor
        c.execute("UPDATE propiedades SET telefono = %s WHERE id = %s", (p["telefono"], p["id"]))
        for uid in (dueno, comprador):
            c.execute("DELETE FROM pedidos WHERE user_id = %s", (uid,))
            c.execute("DELETE FROM chat_users WHERE id = %s", (uid,))
        db.conn.commit()


def _compartir_pedido_que_encaja(comprador, p):
    perfil = {"negocio": "venta", "tipos": ["apartamento"], "ubicaciones": [{"nombre": p["zona"], "municipio": p["ciudad"]}],
              "presupuesto_max": int(p["precio"] * 1.1)}
    c = cli.crear(comprador, {"nombre": "Cliente del comprador", "perfil": perfil})
    return red.compartir_pedido(comprador, c["id"])["pedido_id"]


def test_alerta_borrosa_sin_plan_y_con_detalle_en_negocio(escena):
    dueno, comprador, p = escena
    pid = _compartir_pedido_que_encaja(comprador, p)
    res = al.generar()
    assert res.get("comprador", 0) >= 1
    alertas = [a for a in al.listar(dueno) if a["tipo"] == "comprador"]
    assert alertas and alertas[0]["propiedad"]["id"] == p["id"]
    assert alertas[0]["bloqueada"] and alertas[0]["pedido_id"] is None and "Negocio" in alertas[0]["detalle"]
    s.activar_plan(dueno, "medio", referencia_pago="t")
    a = [a for a in al.listar(dueno) if a["tipo"] == "comprador"][0]
    assert not a["bloqueada"] and a["pedido_id"] == pid and "Busco" in a["detalle"]


def test_no_se_avisa_su_propio_pedido_ni_dos_veces(escena):
    dueno, comprador, p = escena
    _compartir_pedido_que_encaja(dueno, p)   # el dueño comparte un pedido que encaja con su propio inmueble
    al.generar()
    assert not [a for a in al.listar(dueno) if a["tipo"] == "comprador"]
    _compartir_pedido_que_encaja(comprador, p)
    al.generar()
    al.generar()
    with get_db() as db:
        assert scalar(db.cursor, "SELECT COUNT(*) FROM alertas WHERE user_id = %s AND tipo = 'comprador'", (dueno,)) == 1
