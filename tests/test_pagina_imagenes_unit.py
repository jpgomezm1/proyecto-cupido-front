"""Imágenes con IA de Mi página: cupo, reglas del prompt y que una falla no descuente (sin BD ni IA)."""

import pytest

from src.services import fyns_service
from src.services import pagina_imagenes_service as s


def test_cupo_gasta_plan_y_luego_extra():
    c = s.calcular("plan", incluidas=10, usadas=4, compradas=5, gastadas=0, hoy=1)
    assert (c["del_plan"], c["extra"], c["restantes"]) == (6, 5, 11)
    c = s.calcular("prueba", incluidas=3, usadas=5, compradas=5, gastadas=7, hoy=0)
    assert (c["del_plan"], c["extra"], c["restantes"]) == (0, 0, 0) and not c["con_plan"]


def test_instruccion_lleva_reglas_y_estilo():
    t = s.instruccion("  terraza con vista a Laureles  ", "atardecer")
    assert "Sin texto" in t and "terraza con vista a Laureles" in t and s.ESTILOS["atardecer"] in t
    assert s.ESTILOS["natural"] in s.instruccion("sala", "inventado")


def test_formatos_validos():
    assert s.FORMATOS == {"ancha": "1536x1024", "cuadrada": "1024x1024", "vertical": "1024x1536"}


def test_fyns_tiene_imagenes():
    assert fyns_service.CATALOGO["imagenes_5"]["costo"] == 50


def test_descripcion_corta_no_gasta(monkeypatch):
    llamadas = []
    monkeypatch.setattr(s, "cupo", lambda uid: llamadas.append(uid) or {})
    with pytest.raises(s.ImagenError) as e:
        s.generar(1, "  ab ")
    assert e.value.codigo == "datos" and not llamadas


def test_falla_de_la_ia_libera_el_cupo(monkeypatch):
    import sys
    import types

    from src.services import storage_service
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setattr(storage_service, "storage_disponible", lambda: True)
    monkeypatch.setattr(s, "cupo", lambda uid: {"restantes": 2})
    monkeypatch.setattr(s, "_reservar", lambda *a: 77)
    fallos = []
    monkeypatch.setattr(s, "_fallo", lambda iid, err: fallos.append(iid))

    class Rota:
        class images:  # noqa: N801
            @staticmethod
            def generate(**k):
                raise RuntimeError("boom")

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=lambda: Rota))
    with pytest.raises(s.ImagenError) as e:
        s.generar(1, "terraza con vista", "lujo", "ancha")
    assert e.value.codigo == "ia" and fallos == [77]


def test_sin_cupo_no_reserva(monkeypatch):
    monkeypatch.setattr(s, "cupo", lambda uid: {"restantes": 0, "con_plan": True, "total": 10})
    monkeypatch.setattr(s, "_reservar", lambda *a: pytest.fail("no debía reservar"))
    with pytest.raises(s.ImagenError) as e:
        s.generar(1, "terraza con vista")
    assert e.value.codigo == "sin_cupo" and e.value.status == 402
