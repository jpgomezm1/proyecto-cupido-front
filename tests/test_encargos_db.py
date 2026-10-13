"""
Tests de ESCRITURA de encargos de Findy y Findy Conecta (encargos_service).

Solo corren con FYNDER_TEST_DB_WRITE=1 contra una rama de prueba de Neon con la
migración 058 aplicada — nunca producción.
"""

import os
import random

import pytest

if os.getenv("FYNDER_TEST_DB_WRITE") != "1":
    pytest.skip("Tests de escritura: requieren FYNDER_TEST_DB_WRITE=1 y una rama de prueba",
                allow_module_level=True)

from src.services import (clientes_service as cli, correo_service, encargos_service as enc,  # noqa: E402
                          fyns_service as fyns, red_service as red, suscripcion_service as s)
from src.services.db import fetch_one, get_db, scalar  # noqa: E402


def _usuario(nombre):
    tel = f"+57303{random.randint(1000000, 9999999)}"
    with get_db() as db:
        uid = scalar(db.cursor, """
            INSERT INTO chat_users (email, password_hash, nombre, telefono, activo, telefono_verificado, terminos_aceptados_at)
            VALUES (%s, 'x', %s, %s, TRUE, TRUE, NOW()) RETURNING id
        """, (f"enc-{random.randint(0, 10**9)}@fynder.invalid", nombre, tel))
        db.conn.commit()
    return uid, tel


@pytest.fixture
def escena(monkeypatch):
    monkeypatch.setattr(correo_service, "enviar", lambda *a, **k: None)
    dueno, tel = _usuario("Dueña del inmueble")
    buscador, _ = _usuario("Agente que busca")
    with get_db() as db:
        c = db.cursor
        p = fetch_one(c, """
            SELECT id, telefono, precio, zona, ciudad FROM propiedades
            WHERE activa AND precio > 200000000 AND zona IS NOT NULL AND tipo_propiedad ILIKE 'apartamento%%'
            ORDER BY id DESC LIMIT 1
        """)
        c.execute("UPDATE propiedades SET telefono = %s WHERE id = %s", (tel, p["id"]))
        db.conn.commit()
    # Que el desbloqueo no consulte el portal en vivo.
    monkeypatch.setattr(s, "verificar_disponibilidad",
                        lambda pid, **kw: {"estado": "disponible", "activo": True, "verificado_en": "x"})
    yield dueno, buscador, p
    with get_db() as db:
        c = db.cursor
        c.execute("UPDATE propiedades SET telefono = %s WHERE id = %s", (p["telefono"], p["id"]))
        for uid in (dueno, buscador):
            c.execute("DELETE FROM pedidos WHERE user_id = %s", (uid,))
            c.execute("DELETE FROM chat_users WHERE id = %s", (uid,))
        db.conn.commit()


def _perfil_que_encaja(p):
    return {"negocio": "venta", "tipos": ["apartamento"], "ubicaciones": [{"nombre": p["zona"], "municipio": p["ciudad"]}],
            "presupuesto_max": int(p["precio"] * 1.1)}


def test_sin_beneficio_no_hay_encargos_y_con_fyns_si(escena):
    _, buscador, p = escena
    c = cli.crear(buscador, {"nombre": "Ana", "perfil": _perfil_que_encaja(p)})
    with pytest.raises(enc.EncargoError) as e:
        enc.crear(buscador, "buscar_inmueble", cliente_id=c["id"])
    assert e.value.codigo == "sin_beneficio"
    with get_db() as db:
        db.cursor.execute("INSERT INTO fyns_movimientos (user_id, cantidad, motivo) VALUES (%s, 120, 'ajuste')", (buscador,))
        db.conn.commit()
    fyns.canjear(buscador, "encargo")
    r = enc.crear(buscador, "buscar_inmueble", cliente_id=c["id"])
    assert r["ok"] and r["tipo"] == "buscar_inmueble"
    assert enc.crear(buscador, "buscar_inmueble", cliente_id=c["id"])["ya_existia"]


def test_conecta_buscar_inmueble_acepta_y_cobra_una_llave(escena):
    dueno, buscador, p = escena
    s.activar_plan(buscador, "medio", referencia_pago="t")      # 2 encargos y 15 llaves
    c = cli.crear(buscador, {"nombre": "Ana", "perfil": _perfil_que_encaja(p)})
    r = enc.crear(buscador, "buscar_inmueble", cliente_id=c["id"])
    m = [x for x in r["matches"] if x["tipo"] == "propiedad" and x["ref_id"] == p["id"]]
    assert m and m[0]["conecta"] is True
    llaves = s.estado(buscador)["disponibles"]
    pres = enc.pedir_presentacion(buscador, m[0]["id"], "Tengo una compradora lista")
    rec = enc.presentaciones(dueno)["recibidas"]
    assert rec and rec[0]["estado"] == "pendiente" and rec[0]["trae"]["tipo"] == "comprador"
    assert rec[0]["contacto"] is None                        # todavía no hay contactos
    out = enc.responder(dueno, pres["presentacion_id"], True)
    assert out["ok"] and out["presentacion"]["contacto"]["telefono"]   # la dueña ve al buscador
    env = enc.presentaciones(buscador)["enviadas"][0]
    assert env["estado"] == "aceptada" and env["contacto"]["telefono"]  # el buscador ve a la dueña
    assert s.estado(buscador)["disponibles"] == llaves - 1
    with pytest.raises(enc.EncargoError):
        enc.responder(dueno, pres["presentacion_id"], True)   # ya respondida


def test_conecta_buscar_comprador_y_rechazo(escena):
    dueno, buscador, p = escena
    s.activar_plan(dueno, "pro", referencia_pago="t")
    c = cli.crear(buscador, {"nombre": "Luis", "perfil": _perfil_que_encaja(p)})
    pedido_id = red.compartir_pedido(buscador, c["id"])["pedido_id"]
    r = enc.crear(dueno, "buscar_comprador", propiedad_id=p["id"])
    m = [x for x in r["matches"] if x["tipo"] == "pedido" and x["ref_id"] == pedido_id]
    assert m and m[0]["conecta"]
    pres = enc.pedir_presentacion(dueno, m[0]["id"])
    rec = enc.presentaciones(buscador)["recibidas"][0]
    assert rec["trae"]["tipo"] == "inmueble" and rec["prioridad"] is False
    assert enc.responder(buscador, pres["presentacion_id"], False)["estado"] == "rechazada"


def test_no_es_su_inmueble(escena):
    _, buscador, p = escena
    s.activar_plan(buscador, "pro", referencia_pago="t")
    with pytest.raises(enc.EncargoError) as e:
        enc.crear(buscador, "buscar_comprador", propiedad_id=p["id"])
    assert e.value.codigo == "no_propia"
