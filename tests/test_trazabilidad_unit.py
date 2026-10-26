"""Economía, rentabilidad, «Qué necesita atención hoy» y línea de tiempo (sin BD)."""
from datetime import date, datetime, timezone
from unittest import mock

from src.services import atencion_service as at
from src.services import economia_service as ec
from src.services import linea_tiempo_service as lt


def test_atencion_ordena_por_urgencia_y_aisla_errores():
    def roto(cur):
        raise RuntimeError("falta la tabla")
    revisiones = [
        lambda cur: at._item("feedback", "Feedback", 2, "", "/admin/feedback", "info"),
        roto,
        lambda cur: at._item("soporte", "Soporte", 1, "", "/admin/soporte", "mal"),
        lambda cur: None,
    ]
    with mock.patch.object(at, "REVISIONES", revisiones), mock.patch.object(at, "get_db"):
        r = at.hoy()
    assert [i["clave"] for i in r["items"]] == ["soporte", "feedback"]
    assert len(r["errores"]) == 1


def test_rentabilidad_reparte_costos_y_ordena_por_margen():
    base = {"ia_busqueda": 1.0, "ia_plataforma": 10.0, "busquedas": 100}  # 0,01 USD por búsqueda
    filas = [
        {"id": 1, "nombre": "Paga", "ingresos": 80000, "analisis_usd": 0.5, "fotos": 2, "busquedas": 50, "contactos": 5, "plan": "Negocio"},
        {"id": 2, "nombre": "Gratis", "ingresos": 0, "analisis_usd": 0, "fotos": 0, "busquedas": 30, "contactos": 1, "plan": None},
        {"id": 3, "nombre": "Inactivo", "ingresos": 0, "analisis_usd": 0, "fotos": 0, "busquedas": 0, "contactos": 0, "plan": None},
    ]
    with mock.patch.object(ec, "get_db"), mock.patch.object(ec, "fetch_one", return_value=base), \
            mock.patch.object(ec, "fetch_all", return_value=filas), mock.patch.object(ec, "TRM", 4000.0):
        r = ec.rentabilidad(30)
    ids = [a["id"] for a in r["agentes"]]
    assert ids == [2, 1]  # el inactivo no sale; primero el de peor margen
    paga = r["agentes"][1]
    assert paga["costo"] == round((0.5 + 2 * ec.COSTO_FOTO_USD + 50 * 0.01) * 4000)
    assert r["resumen"]["costo_plataforma"] == 40000
    assert r["resumen"]["costo_por_contacto"] == round((r["resumen"]["costo_directo"] + 40000) / 6)


def test_linea_de_tiempo_normaliza_fechas_y_ordena():
    fuentes = [("cuenta", "a"), ("uso", "b"), ("dinero", "c")]
    respuestas = iter([
        [{"fecha": datetime(2026, 10, 1, 12), "titulo": "Creó su cuenta", "detalle": None}],          # UTC sin zona
        [{"fecha": datetime(2026, 10, 5, 7, tzinfo=timezone.utc), "titulo": "Buscó", "detalle": "Apto"}],
        [{"fecha": date(2026, 10, 3), "titulo": "Plan", "detalle": " · "}],                             # solo fecha
    ])
    with mock.patch.object(lt, "_FUENTES", fuentes), mock.patch.object(lt, "get_db"), \
            mock.patch.object(lt, "fetch_one", return_value={"telefono": "+573001234567", "t": "3001234567"}), \
            mock.patch.object(lt, "fetch_all", side_effect=lambda *a, **k: next(respuestas)):
        r = lt.de(7)
    assert [e["titulo"] for e in r["eventos"]] == ["Buscó", "Plan", "Creó su cuenta"]
    assert all(e["fecha"].endswith("+00:00") for e in r["eventos"])
    assert r["eventos"][1]["detalle"] is None  # un detalle vacío no se muestra
