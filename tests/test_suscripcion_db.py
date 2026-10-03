"""
Tests de ESCRITURA del modelo de suscripción (saldo, cobro, carreras, reembolsos).

Escriben en la BD, así que solo corren con FYNDER_TEST_DB_WRITE=1 y deben
apuntar a una rama de prueba de Neon con la migración 040 aplicada — nunca a
producción. La verificación de disponibilidad (HTTP) se reemplaza por un doble.
"""

import os
import random
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

if os.getenv("FYNDER_TEST_DB_WRITE") != "1":
    pytest.skip("Tests de escritura: requieren FYNDER_TEST_DB_WRITE=1 y una rama de prueba",
                allow_module_level=True)

from src.services import suscripcion_service as svc  # noqa: E402
from src.services.db import get_db, fetch_all, fetch_one  # noqa: E402


@pytest.fixture(autouse=True)
def disponible(monkeypatch):
    """Por defecto, todo inmueble verificado en vivo está disponible."""
    monkeypatch.setattr(svc, "verificar_disponibilidad",
                        lambda pid: {"estado": "disponible", "activo": True, "verificado_en": "x"})


def _tel():
    return f"30099{random.randint(10000, 99999)}"


def _crear_usuario(tel=None, verificado=True, terminos=True):
    tel = tel or _tel()
    with get_db() as db:
        db.cursor.execute("""
            INSERT INTO chat_users (email, nombre, password_hash, telefono, activo,
                                    telefono_verificado, terminos_aceptados_at)
            VALUES (%s, 'Test', 'x', %s, TRUE, %s, CASE WHEN %s THEN NOW() END)
            RETURNING id
        """, (f"test{random.randint(0, 10**9)}@test.co", "+57" + tel, verificado, terminos))
        uid = db.cursor.fetchone()["id"]
        db.conn.commit()
    return uid, tel


@pytest.fixture(scope="module")
def inmuebles():
    """Inmuebles activos con un contacto usable (y distintos captadores)."""
    with get_db() as db:
        rows = fetch_all(db.cursor, """
            SELECT id, agente_captador_telefono FROM propiedades
            WHERE activa AND agente_captador_telefono ~ '3[0-9]{9}'
            ORDER BY id LIMIT 200
        """)
    utiles = [r for r in rows if svc.contacto_usable(r["agente_captador_telefono"])]
    assert len(utiles) >= 6
    return utiles


def test_terminos_pendientes(inmuebles):
    uid, _ = _crear_usuario(terminos=False)
    res = svc.desbloquear(uid, "propiedad", inmuebles[0]["id"])
    assert res["error"] == "terminos_pendientes"


def test_prueba_solo_con_telefono_verificado():
    uid, _ = _crear_usuario(verificado=False)
    assert svc.estado(uid)["disponibles"] == 0
    uid, _ = _crear_usuario()
    assert svc.estado(uid)["disponibles"] == svc.CREDITOS_PRUEBA


def test_una_prueba_por_telefono():
    uid1, tel = _crear_usuario()
    assert svc.estado(uid1)["saldo"] == 2
    uid2, _ = _crear_usuario(tel=tel)
    assert svc.estado(uid2)["saldo"] == 0


def test_cobro_reverlo_gratis_y_sin_creditos(inmuebles):
    uid, _ = _crear_usuario()
    a, b, c = (p["id"] for p in inmuebles[:3])

    r1 = svc.desbloquear(uid, "propiedad", a)
    assert r1["ok"] and r1["cobrado"] and r1["fuente"] == "saldo"
    assert r1["contacto"]["telefono"]
    assert r1["disponibles_restantes"] == 1

    again = svc.desbloquear(uid, "propiedad", a)
    assert again["ok"] and not again["cobrado"] and again["ya_desbloqueado"]
    assert again["disponibles_restantes"] == 1

    assert svc.desbloquear(uid, "propiedad", b)["cobrado"]
    sin = svc.desbloquear(uid, "propiedad", c)
    assert sin["error"] == "sin_creditos" and sin["planes"]


def test_no_cobra_si_no_esta_disponible(inmuebles, monkeypatch):
    uid, _ = _crear_usuario()
    monkeypatch.setattr(svc, "verificar_disponibilidad", lambda pid: {"estado": "404", "activo": False})
    res = svc.desbloquear(uid, "propiedad", inmuebles[0]["id"])
    assert res["error"] == "no_disponible"
    assert svc.estado(uid)["disponibles"] == 2


def test_plan_se_consume_antes_que_el_saldo(inmuebles):
    uid, _ = _crear_usuario()
    act = svc.activar_plan(uid, "basico", "TEST-123", admin="pytest")
    est = svc.estado(uid)
    assert est["plan"]["codigo"] == "basico"
    assert est["disponibles"] == 7 + 2

    res = svc.desbloquear(uid, "propiedad", inmuebles[0]["id"])
    assert res["fuente"] == "plan"
    est = svc.estado(uid)
    assert (est["plan_disponibles"], est["saldo"]) == (6, 2)

    # Renovar antes del vencimiento: el periodo nuevo arranca al fin del anterior.
    ren = svc.activar_plan(uid, "pro", "TEST-124", admin="pytest")
    assert ren["inicio"] == act["fin"]


def test_reembolso_devuelve_el_credito_y_tiene_tope(inmuebles, monkeypatch):
    monkeypatch.setenv("FYNDER_REEMBOLSOS_MES", "1")
    uid, _ = _crear_usuario()
    d1 = svc.desbloquear(uid, "propiedad", inmuebles[0]["id"])
    d2 = svc.desbloquear(uid, "propiedad", inmuebles[1]["id"])
    assert svc.estado(uid)["disponibles"] == 0

    r1 = svc.reportar_invalido(uid, d1["desbloqueo_id"], "numero_equivocado")
    assert r1["reembolsado"]
    assert svc.estado(uid)["disponibles"] == 1
    assert svc.reportar_invalido(uid, d1["desbloqueo_id"], "otro")["error"] == "ya_reembolsado"

    r2 = svc.reportar_invalido(uid, d2["desbloqueo_id"], "no_contesta")
    assert r2["ok"] and not r2["reembolsado"]          # pasó el tope: queda para el admin
    assert svc.estado(uid)["disponibles"] == 1


def test_inmueble_propio_es_gratis(inmuebles):
    prop = inmuebles[0]
    tel = svc.contacto_usable(prop["agente_captador_telefono"])
    uid, _ = _crear_usuario(tel=tel)
    res = svc.desbloquear(uid, "propiedad", prop["id"])
    assert res["ok"] and res["fuente"] == "gratis" and not res["cobrado"]


def test_carrera_un_credito_dos_inmuebles(inmuebles, monkeypatch):
    uid, _ = _crear_usuario()
    svc.desbloquear(uid, "propiedad", inmuebles[0]["id"])     # queda 1 crédito

    def lenta(pid):
        time.sleep(0.5)
        return {"estado": "disponible", "activo": True}
    monkeypatch.setattr(svc, "verificar_disponibilidad", lenta)

    with ThreadPoolExecutor(2) as pool:
        res = list(pool.map(lambda p: svc.desbloquear(uid, "propiedad", p["id"]), inmuebles[1:3]))
    oks = [r for r in res if r.get("ok")]
    errores = [r.get("error") for r in res if not r.get("ok")]
    assert len(oks) == 1 and errores == ["sin_creditos"]
    assert svc.estado(uid)["disponibles"] == 0


def test_carrera_mismo_inmueble_cobra_una_vez(inmuebles, monkeypatch):
    uid, _ = _crear_usuario()

    def lenta(pid):
        time.sleep(0.5)
        return {"estado": "disponible", "activo": True}
    monkeypatch.setattr(svc, "verificar_disponibilidad", lenta)

    with ThreadPoolExecutor(2) as pool:
        res = list(pool.map(lambda _: svc.desbloquear(uid, "propiedad", inmuebles[3]["id"]), range(2)))
    assert all(r.get("ok") for r in res)
    assert sum(1 for r in res if r["cobrado"]) == 1
    assert svc.estado(uid)["disponibles"] == 1


def test_pedido_solo_si_quien_pidio_es_usuario_fynder():
    with get_db() as db:
        pedido = fetch_one(db.cursor, """
            SELECT id, agente_telefono FROM pedidos
            WHERE agente_telefono ~ '3[0-9]{9}' AND agente_telefono NOT LIKE '%%@g.us%%'
              AND fecha_captura > NOW() - INTERVAL '50 days'
            ORDER BY fecha_captura DESC LIMIT 1
        """)
    if not pedido:
        pytest.skip("No hay pedidos recientes con teléfono")
    uid, _ = _crear_usuario()
    tel_autor = svc.contacto_usable(pedido["agente_telefono"])

    with get_db() as db:   # que el autor no sea usuario verificado con términos
        db.cursor.execute("""
            UPDATE chat_users SET terminos_aceptados_at = NULL
            WHERE RIGHT(REGEXP_REPLACE(COALESCE(telefono,''),'[^0-9]','','g'),10) = %s
        """, (tel_autor,))
        db.conn.commit()
    res = svc.desbloquear(uid, "pedido", pedido["id"])
    assert res["error"] == "pedido_no_desbloqueable"

    _crear_usuario(tel=tel_autor)          # el autor se vuelve usuario Fynder
    res = svc.desbloquear(uid, "pedido", pedido["id"])
    assert res["ok"] and res["cobrado"]


def test_uso_justo(monkeypatch):
    monkeypatch.setenv("FYNDER_FAIR_USE_DIARIO", "2")
    uid, _ = _crear_usuario()
    assert [svc.registrar_busqueda(uid)["permitido"] for _ in range(3)] == [True, True, False]
