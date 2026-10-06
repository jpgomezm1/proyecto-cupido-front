"""Validación del seguimiento de contactos (sin BD)."""
from datetime import date

from src.services.seguimiento_service import salida, validar


def test_estado_nota_recordatorio():
    assert validar(estado="visita", nota="  Le gustó, quiere ir el sábado ", recordatorio="2026-10-12") == {
        "estado": "visita", "nota": "Le gustó, quiere ir el sábado", "recordatorio": date(2026, 10, 12)}


def test_se_pueden_borrar_nota_y_recordatorio():
    assert validar(nota="", recordatorio=None) == {"nota": None, "recordatorio": None}


def test_errores():
    assert "error" in validar(estado="ganado")
    assert "error" in validar(recordatorio="12/10/2026")
    assert "error" in validar(nota="x" * 2001)
    assert "error" in validar()


def test_sin_registro_es_por_contactar():
    assert salida(None)["estado"] == "por_contactar"
    assert salida({"seg_estado": None})["estado"] == "por_contactar"
