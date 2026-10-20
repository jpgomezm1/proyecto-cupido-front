"""Embudo del agente nuevo (oct-2026): eventos del servidor y misiones de bienvenida. Sin BD."""
from unittest import mock

from src.services import eventos_uso_service as ev
from src.services import logros_service as lg
from src.services import tablero_service as tb


def test_eventos_del_servidor_se_aceptan():
    assert {"cuenta_creada", "celular_verificado"} <= ev.EVENTOS
    with mock.patch.object(ev, "get_db") as gdb:
        cur = gdb.return_value.__enter__.return_value.cursor
        ev.registrar_uno(7, "cuenta_creada", {"desde": "compartido"})
        filas = cur.executemany.call_args[0][1]
    assert filas[0][:2] == (7, "cuenta_creada")
    assert '"desde": "compartido"' in filas[0][3]


def test_registrar_uno_nunca_lanza():
    with mock.patch.object(ev, "get_db", side_effect=RuntimeError("sin BD")):
        ev.registrar_uno(7, "celular_verificado")


def test_el_embudo_lleva_los_pasos_del_servidor_en_orden():
    assert tb.PASOS_WEB[0] == "cuenta_creada"
    assert tb.PASOS_WEB.index("celular_verificado") < tb.PASOS_WEB.index("contacto_abierto")
    assert set(tb.PASOS_SERVIDOR) <= set(tb.PASOS_WEB)


def test_las_misiones_empiezan_por_el_valor_del_producto():
    assert list(lg.MISIONES)[:2] == ["primera_busqueda", "primer_contacto"]
    assert all(m["url"].startswith("/chat") for m in lg.MISIONES.values())
