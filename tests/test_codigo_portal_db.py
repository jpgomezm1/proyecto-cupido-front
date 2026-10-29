"""R4: buscar un inmueble por el código del portal (lectura de la BD real del .env)."""
import pytest

from src.services import property_service as ps
from src.services.db import fetch_one, get_db


@pytest.fixture(scope="module")
def cur():
    with get_db() as db:
        yield db.cursor


def test_codigo_de_wasi_y_de_lobbie(cur):
    for fuente in ("Wasi", "Lobbie"):
        f = fetch_one(cur, """SELECT id, codigo_propiedad FROM propiedades
                              WHERE fuente = %s AND activa AND codigo_propiedad ~ '^[0-9]{6,9}$' LIMIT 1""", (fuente,))
        if not f:
            continue
        p = ps.get_property(cur, f["codigo_propiedad"])
        assert p and p["id"] == f["id"], fuente
        assert ps.get_property(cur, "#" + f["codigo_propiedad"])["id"] == f["id"]


def test_id_de_fynder_sigue_funcionando(cur):
    f = fetch_one(cur, "SELECT id FROM propiedades WHERE activa ORDER BY id LIMIT 1")
    assert ps.get_property(cur, f["id"])["id"] == f["id"]
    assert ps.get_property(cur, str(f["id"]))["id"] == f["id"]


def test_numero_que_no_existe(cur):
    assert ps.get_property(cur, "999999999999") is None
