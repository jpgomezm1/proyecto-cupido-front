"""Correos de activación: a quién le toca cuál y a quién nunca se le escribe."""
from datetime import datetime, timedelta, timezone

import pytest

from src.services import correo_service as c

AHORA = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)


def agente(dias=0.0, verificado=True, busco=False, contactos=0, ultimo_contacto_dias=None):
    return {"desde": AHORA - timedelta(days=dias), "verificado": verificado, "busco": busco,
            "contactos": contactos,
            "ultimo_contacto": None if ultimo_contacto_dias is None else AHORA - timedelta(days=ultimo_contacto_dias)}


@pytest.mark.parametrize("u, disp, plan, esperado", [
    (agente(0.5, verificado=False), 0, False, None),               # recién registrado: aún no
    (agente(1, verificado=False), 0, False, "act_verifica"),
    (agente(10, verificado=False), 0, False, None),                # ya pasó la ventana
    (agente(1), 2, False, None),                                   # verificado hace poco
    (agente(3), 2, False, "act_primera_busqueda"),
    (agente(3, busco=True), 2, False, None),                       # ya buscó, aún es pronto
    (agente(6, busco=True), 2, False, "act_llaves_esperando"),
    (agente(6, busco=True), 0, False, None),                       # sin llaves que esperar
    (agente(20, contactos=2, ultimo_contacto_dias=1), 0, False, "act_sin_llaves"),
    (agente(20, contactos=2, ultimo_contacto_dias=1), 0, True, None),   # tiene plan (en gracia)
    (agente(20, contactos=2, ultimo_contacto_dias=1), 1, False, None),  # le queda una
    (agente(40, contactos=2, ultimo_contacto_dias=30), 0, False, None), # inactivo hace rato
])
def test_momento_activacion(u, disp, plan, esperado):
    assert c.momento_activacion(u, AHORA, disp, plan) == esperado


@pytest.mark.parametrize("email, real", [
    ("ana@gmail.com", True),
    ("x@fynder.co", False),       # cuentas precargadas
    ("x@FYNDER.COM", False),
    ("mcp-123@fynder.invalid", False),
    ("", False),
    (None, False),
])
def test_destinatario_real(email, real):
    assert c.destinatario_real(email) is real


def test_relleno_no_se_envia(monkeypatch):
    llamadas = []
    monkeypatch.setattr(c.resend, "api_key", "re_test")
    monkeypatch.setattr(c.resend.Emails, "send", lambda params: llamadas.append(params))
    assert c._enviar_ya("x@fynder.co", "a", "<p>a</p>", "a", "prueba") is False
    assert llamadas == []


def test_plantillas_renderizan(monkeypatch):
    enviados = []
    monkeypatch.setattr(c, "enviar", lambda para, asunto, html_, texto, etiqueta, **kw: enviados.append((etiqueta, html_, texto)))
    monkeypatch.setattr(c, "_planes_mensuales", lambda: [
        {"codigo": "basico", "nombre": "Visita", "desbloqueos_mes": 7, "precio_cop": 50000}])
    c.act_verifica("Ana María", "ana@gmail.com")
    c.act_primera_busqueda("Ana", "ana@gmail.com", 2)
    c.act_llaves_esperando("Ana", "ana@gmail.com", 1)
    c.act_sin_llaves("Ana", "ana@gmail.com")
    assert [e[0] for e in enviados] == ["act_verifica", "act_primera_busqueda", "act_llaves_esperando", "act_sin_llaves"]
    assert "/chat/findy?q=Apartamento%20en%20Laureles" in enviados[1][1]
    assert "1 llave sin usar" in enviados[2][1]
    assert "$50.000" in enviados[3][1]
    assert all("Ana" in e[2] for e in enviados)
