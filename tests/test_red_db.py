"""
Tests de ESCRITURA de la red: compartir el pedido de un cliente (red_service).

Solo corren con FYNDER_TEST_DB_WRITE=1 contra una rama de prueba de Neon con las
migraciones 052, 057 y 058 aplicadas — nunca producción.
"""

import os
import random
from datetime import timedelta

import pytest

if os.getenv("FYNDER_TEST_DB_WRITE") != "1":
    pytest.skip("Tests de escritura: requieren FYNDER_TEST_DB_WRITE=1 y una rama de prueba",
                allow_module_level=True)

from src.services import (clientes_service as cli, compradores_service as comp, logros_service as l,  # noqa: E402
                          red_service as red, suscripcion_service as s)
from src.services.db import fetch_one, get_db, scalar  # noqa: E402

PERFIL = {"negocio": "venta", "tipos": ["apartamento"],
          "ubicaciones": [{"nombre": "Laureles", "municipio": "Medellín"}, {"nombre": "Estadio", "municipio": "Medellín"}],
          "presupuesto_max": 650_000_000, "habitaciones_min": 3, "obligatorias": ["balcon"]}


def _usuario(terminos=True):
    with get_db() as db:
        uid = scalar(db.cursor, """
            INSERT INTO chat_users (email, password_hash, nombre, telefono, activo, telefono_verificado,
                                    terminos_aceptados_at)
            VALUES (%s, 'x', 'Agente Red', %s, TRUE, TRUE, %s) RETURNING id
        """, (f"red-{random.randint(0, 10**9)}@fynder.invalid", f"+57301{random.randint(1000000, 9999999)}",
              "2026-10-01" if terminos else None))
        db.conn.commit()
    return uid


@pytest.fixture
def agentes(monkeypatch):
    monkeypatch.setattr(l, "FYNS_DESDE", l.FYNS_DESDE - timedelta(days=60))
    ids = [_usuario(), _usuario()]
    yield ids
    with get_db() as db:
        for uid in ids:
            db.cursor.execute("DELETE FROM pedidos WHERE user_id = %s", (uid,))
            db.cursor.execute("DELETE FROM chat_users WHERE id = %s", (uid,))
        db.conn.commit()


def _ficha(precio=600_000_000):
    return {"tipo": "apartamento", "negocio": "venta", "zona": "Laureles", "ciudad": "Medellín", "precio": precio,
            "habitaciones": 3, "banos": 2, "area": 95, "amenidades": ["balcón"], "texto": "Apartamento con balcón"}


def test_compartir_y_lo_encuentra_otro_agente(agentes):
    autor, otro = agentes
    c = cli.crear(autor, {"nombre": "Laura Martínez", "perfil": PERFIL})
    assert c["en_red"] is False and c["falta_para_red"] is None
    r = red.compartir_pedido(autor, c["id"])
    assert r["en_red"] and "Laureles" in r["texto"] and "Laura" not in r["texto"]
    with get_db() as db:
        p = fetch_one(db.cursor, "SELECT * FROM pedidos WHERE id = %s", (r["pedido_id"],))
        assert p["canal"] == "fynder_web" and p["criterios"]["zonas"] == ["Laureles", "Estadio"]
        res = comp.buscar_compradores(db.cursor, _ficha(), user_id=otro, limit=50)
    mio = [x for x in res["compradores"] if x["pedido_id"] == r["pedido_id"]]
    assert mio and mio[0]["desbloqueable"] is True
    assert s.preview_desbloqueo(otro, "pedido", r["pedido_id"]).get("error") != "pedido_no_desbloqueable"
    assert cli.obtener(autor, c["id"])["en_red"] is True


def test_sincroniza_y_retira(agentes):
    autor, otro = agentes
    c = cli.crear(autor, {"nombre": "Cliente", "perfil": PERFIL})
    pid = red.compartir_pedido(autor, c["id"])["pedido_id"]
    cli.actualizar(autor, c["id"], {"perfil": {**PERFIL, "presupuesto_max": 800_000_000}})
    with get_db() as db:
        assert "800" in scalar(db.cursor, "SELECT texto_pedido FROM pedidos WHERE id = %s", (pid,))
    red.compartir_pedido(autor, c["id"], activo=False)
    with get_db() as db:
        res = comp.buscar_compradores(db.cursor, _ficha(), user_id=otro, limit=200)
    assert pid not in {x["pedido_id"] for x in res["compradores"]}
    assert s.preview_desbloqueo(otro, "pedido", pid).get("error") == "no_disponible"
    assert cli.obtener(autor, c["id"])["en_red"] is False
    # Volver a compartir reusa el mismo pedido.
    assert red.compartir_pedido(autor, c["id"])["pedido_id"] == pid


def test_requisitos(agentes):
    autor, _ = agentes
    sin_terminos = _usuario(terminos=False)
    agentes.append(sin_terminos)
    c = cli.crear(sin_terminos, {"nombre": "X", "perfil": PERFIL})
    with pytest.raises(red.RedError) as e:
        red.compartir_pedido(sin_terminos, c["id"])
    assert e.value.codigo == "terminos"
    c2 = cli.crear(autor, {"nombre": "Y", "perfil": {"tipos": ["casa"]}})
    assert c2["falta_para_red"]
    with pytest.raises(red.RedError) as e:
        red.compartir_pedido(autor, c2["id"])
    assert e.value.codigo == "perfil_incompleto"


def test_compartir_paga_fyns(agentes):
    autor, _ = agentes
    c = cli.crear(autor, {"nombre": "Z", "perfil": PERFIL})
    pid = red.compartir_pedido(autor, c["id"], canal="mcp")["pedido_id"]
    l.evaluar(autor)
    with get_db() as db:
        assert scalar(db.cursor, "SELECT fyns FROM logros WHERE user_id = %s AND codigo = 'pedido' AND referencia = %s",
                      (autor, str(pid))) == 40
