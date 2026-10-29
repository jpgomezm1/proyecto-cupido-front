"""Renovación automática con tarjeta (R19): lo que se valida antes de tocar la base o Wompi."""
import pytest

from src.services import renovacion_service as ren


def test_marca_por_bin():
    assert ren._marca("424242") == "Visa"
    assert ren._marca("510510") == "Mastercard"
    assert ren._marca("222300") == "Mastercard"
    assert ren._marca(None) == "Tarjeta"


def test_activar_exige_autorizacion_y_token(monkeypatch):
    monkeypatch.setattr(ren.pagos, "habilitado", lambda: True)
    with pytest.raises(ren.RenovacionError) as e:
        ren.activar(1, "negocio", "tok_test_123", acepta=False)
    assert e.value.codigo == "sin_autorizacion"
    with pytest.raises(ren.RenovacionError) as e:
        ren.activar(1, "negocio", "4242424242424242", acepta=True)      # nunca el número de la tarjeta
    assert e.value.codigo == "invalido"


def test_sin_pasarela_no_activa(monkeypatch):
    monkeypatch.setattr(ren.pagos, "habilitado", lambda: False)
    with pytest.raises(ren.RenovacionError) as e:
        ren.activar(1, "negocio", "tok_test_123", acepta=True)
    assert e.value.codigo == "no_disponible"
