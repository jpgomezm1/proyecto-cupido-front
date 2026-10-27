"""Índice Fynder mensual y herramientas del valorador en el MCP (sin BD)."""
from datetime import date
from types import SimpleNamespace
from unittest import mock

import pytest

from src.services import indice_service as ix


def _z(zona, m2, pedidos, activos, var=None, aptos=40):
    return {"zona": zona, "m2_mediana": m2, "pedidos": pedidos, "activos": activos, "var_m2_pct": var, "aptos": aptos}


def test_mes_acepta_aaaa_mm_y_rechaza_basura():
    assert ix._mes("2026-10") == date(2026, 10, 1)
    assert ix._mes(date(2026, 12, 15)) == date(2026, 12, 1)
    assert ix._siguiente(date(2026, 12, 1)) == date(2027, 1, 1)
    with pytest.raises(ix.IndiceError):
        ix._mes("octubre")


def test_destacados_ordenan_y_no_inventan():
    zonas = [_z("14 - El Poblado", 8_800_000, 300, 2000, 1.5), _z("11 - Laureles-Estadio", 7_300_000, 120, 440, -0.8),
             _z("Bello", 5_500_000, 0, 99, None), _z("Rionegro", 7_800_000, 18, 350, None, aptos=10)]
    d = ix._destacados(zonas)
    assert [z["zona"] for z in d["mas_caras"]] == ["14 - El Poblado", "11 - Laureles-Estadio", "Bello"]  # Rionegro: pocos aptos
    assert d["mas_demanda"][0]["zona"] == "11 - Laureles-Estadio" and "Bello" not in [z["zona"] for z in d["mas_demanda"]]
    assert [z["zona"] for z in d["subieron"]] == ["14 - El Poblado"]
    assert [z["zona"] for z in d["bajaron"]] == ["11 - Laureles-Estadio"]


def test_nota_de_prensa_con_formato_colombiano():
    total = {**_z("Total", 8_014_706, 690, 7799, 2.35), "nuevos": 1570, "salieron": 884}
    zonas = [_z("14 - El Poblado", 8_800_000, 328, 1996), _z("11 - Laureles-Estadio", 7_364_341, 121, 445)]
    e = {"titular": "Laureles, la más buscada", "nombre": "octubre de 2026", "total": total, "zonas": zonas,
         "destacados": ix._destacados(zonas)}
    with mock.patch.object(ix, "edicion", return_value=e):
        nota = ix.nota_de_prensa("2026-10")
    assert nota.startswith("Laureles, la más buscada")
    assert "$8,0 millones" in nota and "7.799 inmuebles" in nota and "690 pedidos" in nota
    assert "subió 2,4 %" in nota or "subió 2,3 %" in nota
    assert "Laureles-Estadio (comuna 11)" in nota


def test_una_edicion_publicada_no_se_recalcula():
    cur = mock.MagicMock()
    db = mock.MagicMock(cursor=cur)
    with mock.patch.object(ix, "get_db") as g, mock.patch.object(ix, "fetch_one", return_value={"estado": "publicado"}):
        g.return_value.__enter__.return_value = db
        with pytest.raises(ix.IndiceError) as e:
            ix.calcular("2026-10")
    assert e.value.codigo == "publicado"


def test_mcp_propietarios_filtra_por_zona_e_intencion():
    from src.mcp_server import server as srv
    items = [{"id": 1, "barrio": "Conquistadores", "comuna": "11 - Laureles-Estadio", "municipio": "Medellín", "intencion": "vender"},
             {"id": 2, "barrio": "Zuñiga", "comuna": None, "municipio": "Envigado", "intencion": "arrendar"},
             {"id": 3, "barrio": "Laureles", "comuna": "11 - Laureles-Estadio", "municipio": "Medellín", "intencion": "ambos"}]
    fn = getattr(srv.propietarios_que_venden, "__wrapped__", srv.propietarios_que_venden)
    with mock.patch.object(srv, "current_agent", return_value=SimpleNamespace(user_id=7)), \
            mock.patch("src.services.valorador_service.para_agente", return_value={"items": items, "vigencia_dias": 30}), \
            mock.patch("src.services.valorador_service.mi_valorador", return_value={"activo": False}):
        r = fn(zona="laureles", intencion="vender")
    assert [p["id"] for p in r["propietarios"]] == [1, 3]
