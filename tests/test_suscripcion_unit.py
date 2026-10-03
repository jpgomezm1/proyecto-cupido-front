"""Tests sin BD del modelo de suscripción: contacto usable, revelado y frescura."""

from datetime import datetime, timedelta, timezone

import pytest

from src.services import suscripcion_service as svc
from src.services.disponibilidad_service import tamano_lote
from src.services.property_service import frescura
from src.services.redact import ContactoRevelado, sanitize


@pytest.mark.parametrize("tel,esperado", [
    ("+573001112233", "3001112233"),
    ("300 111 2233", "3001112233"),
    ("6044445566", "6044445566"),           # fijo con indicativo
    ("573001234567-1622@g.us", None),      # id de grupo de WhatsApp
    ("300***2233", None),                  # enmascarado
    ("300XXX2233", None),
    ("1234567", None),                     # corto
    ("3333333333", None),                  # dígitos repetidos
    ("1234567890", None),                  # no es celular ni fijo
    ("", None),
    (None, None),
])
def test_contacto_usable(tel, esperado):
    assert svc.contacto_usable(tel) == esperado


def test_contacto_usable_excluye_numeros_de_fynder(monkeypatch):
    monkeypatch.setenv("FYNDER_TELEFONOS_PROPIOS", "+57 300 999 8877, 3110000000")
    assert svc.contacto_usable("3009998877") is None
    assert svc.contacto_usable("3001112233") == "3001112233"


def test_contacto_revelado_solo_con_revelar():
    c = ContactoRevelado("+573001112233", "Ana", "Inmo X")
    salida = {"contacto_desbloqueado": c, "nota": "cel 3005556677", "telefono": "3005556677"}

    abierto = sanitize(salida, revelar=True)
    assert abierto["contacto_desbloqueado"]["telefono"] == "+573001112233"
    assert abierto["contacto_desbloqueado"]["whatsapp_link"] == "https://wa.me/573001112233"
    # Lo que rodea al contacto se sigue saneando.
    assert "telefono" not in abierto
    assert "3005556677" not in abierto["nota"]

    cerrado = sanitize({"items": [c, {"x": c}]})
    assert cerrado == {"items": [None, {"x": None}]}


def test_tamano_lote_cubre_el_inventario_en_los_dias_objetivo():
    # 7.276 activas, 7 días, cada 30 min = 336 corridas → 22 por corrida.
    n = tamano_lote(7276, 7, 30)
    assert n == 22
    assert n * 7 * 48 >= 7276
    assert tamano_lote(0, 7, 30) == 1


def test_frescura():
    ahora = datetime.now(timezone.utc)
    assert frescura(None) == {"verificada_hace_dias": None, "verificacion_vencida": True}
    assert frescura(ahora - timedelta(days=3)) == {"verificada_hace_dias": 3, "verificacion_vencida": False}
    assert frescura(ahora - timedelta(days=9))["verificacion_vencida"] is True
    # Fechas sin zona horaria (columnas TIMESTAMP) también funcionan.
    assert frescura(datetime.now() - timedelta(days=1))["verificada_hace_dias"] == 1
