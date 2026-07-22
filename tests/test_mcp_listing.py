"""Tests de creación de listings (validación + token de fotos)."""

import time
import pytest

from tests.conftest import requires_db
from src.services import listing_service as lst


def test_photo_token_roundtrip():
    tok = lst.build_photo_token(999, "3001112233")
    p = lst.verify_photo_token(tok)
    assert p["pid"] == 999 and p["owner"] == "3001112233"


def test_photo_token_tampered():
    tok = lst.build_photo_token(999, "3001112233")
    with pytest.raises(lst.ListingError):
        lst.verify_photo_token(tok[:-3] + "zzz")


def test_photo_token_expired(monkeypatch):
    tok = lst.build_photo_token(999, "3001112233")
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + lst._PHOTO_TTL + 10)
    with pytest.raises(lst.ListingError):
        lst.verify_photo_token(tok)


@requires_db
def test_crear_listing_valida_obligatorios():
    # sin precio
    with pytest.raises(lst.ListingError):
        lst.crear_listing("+573001112233", {"area_construida": 90, "tipo_propiedad": "Apartamento",
                                             "ciudad": "Sabaneta"})
    # sin ubicación
    with pytest.raises(lst.ListingError):
        lst.crear_listing("+573001112233", {"precio": 500000000, "area_construida": 90,
                                             "tipo_propiedad": "Apartamento"})
    # precio inválido
    with pytest.raises(lst.ListingError):
        lst.crear_listing("+573001112233", {"precio": -5, "area_construida": 90,
                                             "tipo_propiedad": "Apartamento", "ciudad": "Sabaneta"})


@requires_db
def test_crear_y_borrar_listing():
    """Crea un listing real y lo limpia (incluye evento y foto ref)."""
    from src.services.db import get_db
    res = lst.crear_listing("+573009998877", {
        "precio": 550000000, "area_construida": 85, "tipo_propiedad": "Apartamento",
        "ciudad": "Sabaneta", "zona": "Test", "habitaciones": 3,
        "titulo": "Listing de prueba automatizado",
        "amenidades_externas": "Piscina|Porteria",
    }, agente_nombre="Test", agente_user_id=None)
    assert res["ok"] and res["id"]
    assert res["link_compartir"] and res["link_subir_fotos"]
    pid = res["id"]
    try:
        with get_db() as db:
            db.cursor.execute("SELECT fuente, activa FROM propiedades WHERE id=%s", (pid,))
            row = db.cursor.fetchone()
            assert row["fuente"] == "Fynder" and row["activa"] is True
    finally:
        with get_db() as db:
            db.cursor.execute("DELETE FROM eventos_log WHERE propiedad_id=%s", (pid,))
            db.cursor.execute("DELETE FROM propiedades WHERE id=%s", (pid,))
            db.conn.commit()
