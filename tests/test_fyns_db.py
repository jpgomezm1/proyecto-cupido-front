"""
Tests de ESCRITURA de Fyns (ganar por días, rachas, publicar y misiones; tope; canjes).

Escriben en la BD: solo corren con FYNDER_TEST_DB_WRITE=1 contra una rama de
prueba de Neon con las migraciones 049, 056 y 057 aplicadas — nunca producción.
"""

import json
import os
import random
from datetime import timedelta

import pytest

if os.getenv("FYNDER_TEST_DB_WRITE") != "1":
    pytest.skip("Tests de escritura: requieren FYNDER_TEST_DB_WRITE=1 y una rama de prueba",
                allow_module_level=True)

from src.services import fotos_ia_service, fyns_service as fyns, logros_service as l, suscripcion_service as s  # noqa: E402
from src.services.db import get_db, scalar  # noqa: E402


@pytest.fixture
def agente(monkeypatch):
    with get_db() as db:
        hoy = l._hoy(db.cursor)
    monkeypatch.setattr(l, "FYNS_DESDE", hoy - timedelta(days=30))
    with get_db() as db:
        uid = scalar(db.cursor, """
            INSERT INTO chat_users (email, password_hash, nombre, telefono, activo, telefono_verificado)
            VALUES (%s, 'x', 'Prueba Fyns', %s, TRUE, TRUE) RETURNING id
        """, (f"fyns-{random.randint(0, 10**9)}@fynder.invalid", f"+57300{random.randint(1000000, 9999999)}"))
        db.conn.commit()
    yield uid, hoy
    with get_db() as db:
        db.cursor.execute("DELETE FROM eventos_log WHERE datos_evento->>'user_id' = %s", (str(uid),))
        db.cursor.execute("DELETE FROM chat_users WHERE id = %s", (uid,))
        db.conn.commit()


def _uso(uid, dias_atras, mcp=True):
    """Simula un día con uso real: una tool del MCP o una búsqueda web."""
    with get_db() as db:
        c = db.cursor
        for k in dias_atras:
            if mcp:
                c.execute("""INSERT INTO mcp_tool_calls (user_id, tool, ok, duracion_ms, created_at)
                             VALUES (%s, 'search_properties', TRUE, 10,
                                     (NOW() AT TIME ZONE 'UTC') - make_interval(days => %s))""", (uid, k))
            else:
                c.execute(f"""INSERT INTO uso_diario (user_id, fecha, busquedas)
                             VALUES (%s, (NOW() AT TIME ZONE '{l.TZ}')::date - %s, 1)
                             ON CONFLICT (user_id, fecha) DO NOTHING""", (uid, k))
        db.conn.commit()


def _saldo(uid):
    with get_db() as db:
        return fyns.saldo_en(db.cursor, uid)


def test_mcp_paga_mas_que_web_y_no_paga_dos_veces(agente):
    uid, _ = agente
    _uso(uid, [1, 2], mcp=True)     # 2 días con IA: misiones conectar (+300) y consulta (+100), días +15 c/u
    _uso(uid, [3], mcp=False)       # 1 día web: +3
    l.evaluar(uid)
    primera = _saldo(uid)
    l.evaluar(uid)
    assert _saldo(uid) == primera   # idempotente
    # Tope del plan prueba (150): las misiones solas lo llenan.
    with get_db() as db:
        assert fyns.ganados_mes_en(db.cursor, uid) == fyns.tope_mes_en(db.cursor, uid) == 150


def test_tope_sube_con_el_plan_y_racha_con_ia(agente):
    uid, _ = agente
    s.activar_plan(uid, "pro", referencia_pago="test")   # tope 600
    _uso(uid, range(1, 8), mcp=True)                     # 7 días seguidos (ayer hacia atrás), todos con IA
    l.evaluar(uid)
    with get_db() as db:
        codigos = {r["codigo"]: r["n"] for r in __import__("src.services.db", fromlist=["x"]).fetch_all(
            db.cursor, "SELECT codigo, SUM(fyns) n FROM logros WHERE user_id = %s GROUP BY codigo", (uid,))}
    assert codigos["dia"] == 7 * 15
    assert codigos["conectar_ia"] == 300 and codigos["consulta_ia"] == 100 and codigos["perfil"] == 50
    # 555 de misiones y días; la racha (75) solo cabe hasta el tope de Cierre (600).
    assert codigos["racha"] == 600 - 555 and _saldo(uid) == 600


def test_publicar_paga_segun_canal(agente):
    uid, _ = agente
    with get_db() as db:
        c = db.cursor
        pids = [r["id"] for r in __import__("src.services.db", fromlist=["x"]).fetch_all(
            c, "SELECT id FROM propiedades WHERE activa LIMIT 2")]
        for pid, canal in zip(pids, ("mcp", "web")):
            c.execute("""INSERT INTO eventos_log (tipo_evento, propiedad_id, datos_evento, fecha_evento)
                         VALUES ('listing_creado_fynder', %s, %s, NOW())""",
                      (pid, json.dumps({"user_id": uid, "canal": canal})))
        db.conn.commit()
    l.evaluar(uid)
    with get_db() as db:
        pagos = sorted(r["fyns"] for r in __import__("src.services.db", fromlist=["x"]).fetch_all(
            db.cursor, "SELECT fyns FROM logros WHERE user_id = %s AND codigo = 'publicar'", (uid,)))
    assert pagos == [10, 40]


def test_canjes(agente):
    uid, _ = agente
    with get_db() as db:
        db.cursor.execute("INSERT INTO fyns_movimientos (user_id, cantidad, motivo) VALUES (%s, 170, 'ajuste')", (uid,))
        db.conn.commit()
    llaves_antes = s.estado(uid)["disponibles"]
    r = fyns.canjear(uid, "llave")
    assert r["saldo"] == 70 and s.estado(uid)["disponibles"] == llaves_antes + 1
    extra_antes = fotos_ia_service.cupo(uid)["extra"]
    assert fyns.canjear(uid, "fotos_5")["saldo"] == 10
    assert fotos_ia_service.cupo(uid)["extra"] == extra_antes + 5
    with pytest.raises(fyns.FynsError) as e:
        fyns.canjear(uid, "llave")
    assert e.value.codigo == "sin_fyns"
    with pytest.raises(fyns.FynsError):
        fyns.canjear(uid, "yate")


def test_aviso_mcp_no_felicita_solo_por_un_dia(agente):
    uid, _ = agente
    s.activar_plan(uid, "pro", referencia_pago="test")   # tope 600: que el tope no recorte los montos
    with get_db() as db:   # ya tiene las misiones: solo quedan días por ganar
        for cod in ("conectar_ia", "consulta_ia", "perfil"):
            db.cursor.execute("INSERT INTO logros (user_id, codigo, avisado_mcp) VALUES (%s, %s, TRUE)", (uid, cod))
        db.conn.commit()
    _uso(uid, [1], mcp=True)
    l.evaluar(uid)
    assert l.aviso_mcp(uid) is None          # un día suelto no se anuncia
    _uso(uid, range(2, 8), mcp=True)          # completa 7 días seguidos
    l.evaluar(uid)
    aviso = l.aviso_mcp(uid)
    assert aviso and aviso["fyns_ganados"] == 7 * 15 + 75 and "Racha de 7 días con tu IA" in aviso["logros"]
    assert l.aviso_mcp(uid) is None          # ya avisado
