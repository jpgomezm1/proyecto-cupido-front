"""Códigos de acceso de la beta (R6): normalización y validaciones que no tocan la base."""
from datetime import datetime

import pytest

from src.services import codigos_acceso_service as codigos


def test_normalizar():
    assert codigos.normalizar("  beta-fynder ") == "BETA-FYNDER"
    assert codigos.normalizar("beta fynder 2026") == "BETAFYNDER2026"
    assert codigos.normalizar(None) == ""


def test_crear_rechaza_codigos_raros_sin_tocar_la_base():
    for malo in ("ab", "BETA/FYNDER", "ñandú-1"):
        with pytest.raises(codigos.CodigoError):
            codigos.crear(malo)


def _fila(**k):
    base = {"activo": True, "vence_at": None, "vencido": False, "usos": 0, "usos_max": 10}
    return {**base, **k}


def test_vigente():
    codigos._vigente(_fila())
    for fila, motivo in ((None, "invalido"), (_fila(activo=False), "invalido"),
                         (_fila(vence_at=datetime(2026, 1, 1), vencido=True), "vencido"),
                         (_fila(usos=10), "agotado")):
        with pytest.raises(codigos.CodigoError) as e:
            codigos._vigente(fila)
        assert e.value.codigo == motivo
