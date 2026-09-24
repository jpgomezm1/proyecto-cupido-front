"""
Tests de PATCH /api/listings/<id>/precio (el agente cambia el precio desde
Mis Propiedades del chat).

Los tests contra la BD corren dentro de una transacción que se revierte al final
(commit neutralizado), así que no dejan cambios en la base.
"""

from contextlib import contextmanager

import pytest
from flask import Flask

from tests.conftest import requires_db
import src.api.listings as listings_mod
import src.api.chat_auth as chat_auth_mod


AGENTE = {"id": 1, "email": "a@b.co", "nombre": "Agente", "telefono": "+573001112233",
          "correo_personal": None}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(chat_auth_mod, "get_current_user", lambda: dict(AGENTE))
    app = Flask(__name__)
    app.register_blueprint(listings_mod.listings_bp)
    return app.test_client()


def _patch(client, pid, body):
    return client.patch(f"/api/listings/{pid}/precio", json=body)


# ---------------------------------------------------------------------------
# Validación (sin BD)
# ---------------------------------------------------------------------------

def test_requiere_auth(monkeypatch):
    monkeypatch.setattr(chat_auth_mod, "get_current_user", lambda: None)
    app = Flask(__name__)
    app.register_blueprint(listings_mod.listings_bp)
    r = app.test_client().patch("/api/listings/1/precio", json={"precio": 500_000_000})
    assert r.status_code == 401


@pytest.mark.parametrize("body", [{}, {"precio": None}, {"precio": ""}, {"precio": True},
                                  {"precio": "abc"}])
def test_precio_invalido(client, body):
    r = _patch(client, 1, body)
    assert r.status_code == 400
    assert r.get_json()["success"] is False


@pytest.mark.parametrize("precio", [600, 99_999, 100_000_000_001, -5])
def test_precio_fuera_de_rango(client, precio):
    r = _patch(client, 1, {"precio": precio})
    assert r.status_code == 400
    assert "rango" in r.get_json()["error"]


def test_usuario_sin_telefono(monkeypatch):
    monkeypatch.setattr(chat_auth_mod, "get_current_user", lambda: {**AGENTE, "telefono": None})
    app = Flask(__name__)
    app.register_blueprint(listings_mod.listings_bp)
    r = app.test_client().patch("/api/listings/1/precio", json={"precio": 500_000_000})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Contra la BD real, en una transacción que se revierte
# ---------------------------------------------------------------------------

class _NoCommitConn:
    """Proxy de la conexión: `commit` no hace nada para poder revertir al final."""

    def __init__(self, conn):
        self._conn = conn

    def commit(self):
        pass

    def rollback(self):
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.fixture
def db_rollback(monkeypatch):
    from src.services.db import get_db as real_get_db

    with real_get_db() as db:
        real_conn = db.conn
        db.conn = _NoCommitConn(real_conn)

        @contextmanager
        def fake_get_db():
            yield db

        monkeypatch.setattr(listings_mod, "get_db", fake_get_db)
        try:
            yield db
        finally:
            real_conn.rollback()


def _propiedad_con_dueno(db):
    db.cursor.execute("""
        SELECT id, precio, area_construida, agente_captador_telefono
        FROM propiedades
        WHERE agente_captador_telefono IS NOT NULL
          AND LENGTH(REGEXP_REPLACE(agente_captador_telefono, '[^0-9]', '', 'g')) >= 10
          AND precio > 0 AND area_construida > 0
        ORDER BY id DESC LIMIT 1
    """)
    row = db.cursor.fetchone()
    if not row:
        pytest.skip("No hay propiedades con captador en la BD")
    return row


@requires_db
def test_cambia_precio_de_propiedad_propia(monkeypatch, db_rollback):
    prop = _propiedad_con_dueno(db_rollback)
    monkeypatch.setattr(chat_auth_mod, "get_current_user",
                        lambda: {**AGENTE, "telefono": prop["agente_captador_telefono"]})
    app = Flask(__name__)
    app.register_blueprint(listings_mod.listings_bp)

    nuevo = int(prop["precio"]) + 1_000_000
    r = app.test_client().patch(f"/api/listings/{prop['id']}/precio", json={"precio": nuevo})
    data = r.get_json()
    assert r.status_code == 200, data
    assert data["data"]["precio"] == nuevo
    assert data["data"]["precio_anterior"] == prop["precio"]
    assert data["data"]["slug"]
    # El trigger calcular_precio_m2 recalcula el precio por m².
    assert data["data"]["precio_m2"] == pytest.approx(nuevo / float(prop["area_construida"]), rel=1e-6)

    db_rollback.cursor.execute(
        "SELECT datos_evento FROM eventos_log WHERE tipo_evento = 'agent_price_update' "
        "AND propiedad_id = %s ORDER BY id DESC LIMIT 1", (prop["id"],))
    ev = db_rollback.cursor.fetchone()
    assert ev and ev["datos_evento"]["precio_nuevo"] == nuevo


@requires_db
def test_no_puede_cambiar_precio_ajeno(client, db_rollback):
    # AGENTE (+573001112233) no es dueño de esta propiedad.
    db_rollback.cursor.execute("""
        SELECT id, precio FROM propiedades
        WHERE agente_captador_telefono IS NOT NULL
          AND RIGHT(REGEXP_REPLACE(agente_captador_telefono, '[^0-9]', '', 'g'), 10) <> '3001112233'
        ORDER BY id DESC LIMIT 1
    """)
    prop = db_rollback.cursor.fetchone()
    if not prop:
        pytest.skip("No hay propiedades de otro agente")
    r = _patch(client, prop["id"], {"precio": 777_000_000})
    assert r.status_code == 404
    db_rollback.cursor.execute("SELECT precio FROM propiedades WHERE id = %s", (prop["id"],))
    assert db_rollback.cursor.fetchone()["precio"] == prop["precio"]


@requires_db
def test_propiedad_inexistente(client, db_rollback):
    r = _patch(client, 2_000_000_000, {"precio": 500_000_000})
    assert r.status_code == 404
