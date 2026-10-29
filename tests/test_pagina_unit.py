"""Mi página: la configuración de diseño siempre sale completa y válida (sin BD)."""

from src.services import pagina_agente_service as p
from src.services import pagina_ia_service as ia


def test_defecto_completo():
    c = p.normalizar(None)
    assert c["plantilla"] == "clasica" and c["fuente"] == "moderna"
    assert [s["id"] for s in c["secciones"]] == list(p.SECCIONES)
    assert all(s["visible"] for s in c["secciones"])


def test_valores_invalidos_se_descartan():
    c = p.normalizar({"plantilla": "neon", "color": "rojo", "fuente": "comic", "portada_url": "http://x.com/a.jpg",
                      "cifras": {"anos": True, "vendidos": -1, "familias": "12"}, "destacados": ["a", None]})
    assert c["plantilla"] == "clasica" and c["color"] == p.DEFECTO["color"] and c["fuente"] == "moderna"
    assert c["portada_url"] is None and c["cifras"] == {} and c["destacados"] == []


def test_secciones_respetan_orden_y_completan():
    c = p.normalizar({"secciones": [{"id": "preguntas", "visible": False}, {"id": "preguntas"}, {"id": "otra"}]})
    ids = [s["id"] for s in c["secciones"]]
    assert ids[0] == "preguntas" and c["secciones"][0]["visible"] is False
    assert sorted(ids) == sorted(p.SECCIONES) and len(ids) == len(p.SECCIONES)


def test_redes_aceptan_usuario_o_link():
    c = p.normalizar({"redes": {"instagram": "@laura.inm", "tiktok": "http://tiktok.com/@x", "web": "laura.com",
                                "facebook": "no vale!!", "youtube": "https://youtube.com/@canal"}})
    assert c["redes"] == {"instagram": "https://instagram.com/laura.inm", "tiktok": "https://tiktok.com/@x",
                          "youtube": "https://youtube.com/@canal", "web": "https://laura.com"}


def test_listas_con_tope_y_sin_vacios():
    c = p.normalizar({"testimonios": [{"texto": "Bien", "nombre": "Ana"}] * 9 + [{"texto": ""}],
                      "preguntas": [{"p": "¿?", "r": "Sí"}] * 12 + [{"p": "sin respuesta"}],
                      "destacados": [1, 2, 3, 4], "titular": "x" * 200})
    assert len(c["testimonios"]) == 6 and len(c["preguntas"]) == 8
    assert c["destacados"] == [1, 2, 3] and len(c["titular"]) == 90


def test_paleta_de_la_ia_es_valida():
    assert all(p._COLOR.match(col) for col in ia.PALETA)
    assert ia.PALETA[0] == p.DEFECTO["color"]


def test_estilo_fino():
    c = p.normalizar({"fondo": "salvia", "esquinas": "redondas", "tarjetas": "foto", "columnas": 2, "oscurecer": 200, "animaciones": False})
    assert (c["fondo"], c["esquinas"], c["tarjetas"], c["columnas"], c["oscurecer"], c["animaciones"]) == ("salvia", "redondas", "foto", 2, 80, False)
    c = p.normalizar({"fondo": "neon", "columnas": 5, "oscurecer": True, "animaciones": "si", "plantilla": "boutique", "fuente": "lujo"})
    assert (c["fondo"], c["columnas"], c["oscurecer"], c["animaciones"]) == ("auto", 3, 45, True)
    assert c["plantilla"] == "boutique" and c["fuente"] == "lujo"
