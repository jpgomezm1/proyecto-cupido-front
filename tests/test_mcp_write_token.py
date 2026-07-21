"""Tests del token de confirmación firmado (crypto/validación, sin BD)."""

import time
import pytest

from src.services import write_service as w


def _payload():
    return {"action": "price", "property_id": 123, "owner": "3122655340", "nuevo_precio": 500_000_000}


def test_token_roundtrip_ok():
    token = w._make_token(_payload())
    data = w._verify_token(token, "3122655340")
    assert data["action"] == "price"
    assert data["property_id"] == 123
    assert data["nuevo_precio"] == 500_000_000


def test_token_wrong_owner_rejected():
    token = w._make_token(_payload())
    with pytest.raises(w.WriteError):
        w._verify_token(token, "9999999999")


def test_token_tampered_signature_rejected():
    token = w._make_token(_payload())
    with pytest.raises(w.WriteError):
        w._verify_token(token[:-3] + "zzz", "3122655340")


def test_token_tampered_body_rejected():
    token = w._make_token(_payload())
    body, sig = token.split(".", 1)
    with pytest.raises(w.WriteError):
        w._verify_token("AAAA" + body + "." + sig, "3122655340")


def test_token_expired_rejected(monkeypatch):
    token = w._make_token(_payload())
    # Avanzar el reloj más allá del TTL.
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + w._TOKEN_TTL_SECONDS + 10)
    with pytest.raises(w.WriteError):
        w._verify_token(token, "3122655340")


def test_estado_validation():
    assert set(w._ESTADOS_VALIDOS) == {"vendido", "inactivo", "pausado", "disponible"}
    assert w._ESTADOS_VALIDOS["vendido"]["activa"] is False
    assert w._ESTADOS_VALIDOS["disponible"]["activa"] is True
