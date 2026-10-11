"""
Tests del auto-registro (self-service) del MCP.

Solo cubren rutas de VALIDACIÓN, que ocurren antes de tocar la BD (no escriben
nada). El happy-path (crear usuario + token) se valida end-to-end manualmente
para no crear usuarios en la base compartida.
"""

import pytest

from src.services import mcp_signup_service as sus


@pytest.fixture(autouse=True)
def _alta_encendida(monkeypatch):
    # Las validaciones se prueban con el alta encendida (por defecto está apagada).
    monkeypatch.setenv("MCP_SIGNUP_ENABLED", "true")
    monkeypatch.delenv("MCP_SIGNUP_CODE", raising=False)


def test_signup_apagado_por_defecto(monkeypatch):
    monkeypatch.delenv("MCP_SIGNUP_ENABLED", raising=False)
    with pytest.raises(sus.SignupError, match="registro"):
        sus.self_register(nombre="Agente Real", email="a@b.com", acepta_terminos=True)


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
