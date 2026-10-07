"""Validaciones del registro web y del código del celular (sin BD)."""
import pytest

from src.services import registro_service as svc


@pytest.mark.parametrize("entrada,esperado", [
    ("3001234567", "+573001234567"),
    ("+57 300 123 4567", "+573001234567"),
    ("573001234567", "+573001234567"),
    ("(300) 123-4567", "+573001234567"),
])
def test_celular_normaliza(entrada, esperado):
    assert svc._celular(entrada) == esperado


@pytest.mark.parametrize("malo", [None, "", "12345", "6041234567", "2001234567"])
def test_celular_invalido(malo):
    with pytest.raises(svc.RegistroError) as e:
        svc._celular(malo)
    assert e.value.campo == "telefono"


BASE = dict(nombre="Ana Gómez", email="ana@correo.co", clave="clave-segura", telefono="3001234567",
            acepta_terminos=True)


@pytest.mark.parametrize("cambio,campo", [
    ({"nombre": "A"}, "nombre"),
    ({"email": "ana@"}, "email"),
    ({"clave": "corta"}, "clave"),
    ({"telefono": "123"}, "telefono"),
    ({"acepta_terminos": False}, "terminos"),
])
def test_registro_valida_antes_de_tocar_la_bd(monkeypatch, cambio, campo):
    monkeypatch.setattr(svc, "get_db", lambda: pytest.fail("no debe tocar la BD"))
    with pytest.raises(svc.RegistroError) as e:
        svc.registrar(**{**BASE, **cambio})
    assert e.value.campo == campo


@pytest.mark.parametrize("codigo", ["", "12345", "abcdef", "1234567"])
def test_codigo_debe_tener_6_digitos(monkeypatch, codigo):
    monkeypatch.setattr(svc, "get_db", lambda: pytest.fail("no debe tocar la BD"))
    with pytest.raises(svc.RegistroError) as e:
        svc.verificar_codigo(1, codigo)
    assert e.value.codigo == "invalido"


def test_hash_depende_del_usuario():
    assert svc._hash(1, "123456") != svc._hash(2, "123456")
    assert len(svc._hash(1, "123456")) == 64
