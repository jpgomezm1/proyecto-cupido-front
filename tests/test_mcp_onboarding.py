"""
Tests del auto-registro (self-service) del MCP.

Solo cubren rutas de VALIDACIÓN, que ocurren antes de tocar la BD (no escriben
nada). El happy-path (crear usuario + token) se valida end-to-end manualmente
para no crear usuarios en la base compartida.
"""

import pytest

from src.services import mcp_signup_service as sus


def test_rejects_short_name():
    with pytest.raises(sus.SignupError):
        sus.self_register(nombre="A", email="a@b.com")


def test_rejects_invalid_email():
    with pytest.raises(sus.SignupError):
        sus.self_register(nombre="Agente Real", email="no-es-un-correo")


def test_rejects_invalid_phone():
    with pytest.raises(sus.SignupError):
        sus.self_register(nombre="Agente Real", email="a@b.com", telefono="abc")


def test_disabled_signup(monkeypatch):
    monkeypatch.setenv("MCP_SIGNUP_ENABLED", "false")
    with pytest.raises(sus.SignupError):
        sus.self_register(nombre="Agente Real", email="a@b.com")


def test_invite_code_required(monkeypatch):
    monkeypatch.setenv("MCP_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("MCP_SIGNUP_CODE", "SECRETO123")
    with pytest.raises(sus.SignupError):
        sus.self_register(nombre="Agente Real", email="a@b.com", invite_code="malo")
