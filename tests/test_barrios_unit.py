"""Barrios normalizados: lógica pura de barrios_service (sin base de datos)."""
from src.services import barrios_service as bs

CUADRO = {"type": "Polygon", "coordinates": [[[-75.60, 6.20], [-75.55, 6.20], [-75.55, 6.25], [-75.60, 6.25], [-75.60, 6.20]]]}


class CatalogoFalso(bs.Catalogo):
    """El mismo Catalogo, armado a mano en vez de leer la base."""

    def __init__(self):  # noqa: D401 — sin cursor
        self.barrios = {
            1: {"id": 1, "municipio": "Medellín", "municipio_clave": "medellin", "comuna": "11 - Laureles-Estadio",
                "nombre": "Laureles", "clave": "laureles", "tipo": "sector", "lat": 6.245, "lng": -75.59, "geojson": None},
            2: {"id": 2, "municipio": "Medellín", "municipio_clave": "medellin", "comuna": "14 - El Poblado",
                "nombre": "Castropol", "clave": "castropol", "tipo": "barrio", "lat": 6.215, "lng": -75.57, "geojson": CUADRO},
            3: {"id": 3, "municipio": "Envigado", "municipio_clave": "envigado", "comuna": None,
                "nombre": "Loma de las Brujas", "clave": "loma de las brujas", "tipo": "sector", "lat": 6.16, "lng": -75.58, "geojson": None},
            4: {"id": 4, "municipio": "Envigado", "municipio_clave": "envigado", "comuna": None,
                "nombre": "Zúñiga", "clave": "zuniga", "tipo": "barrio", "lat": 6.18, "lng": -75.585, "geojson": None},
        }
        A = lambda bid, mun, tipo="barrio", conf=0.9: {"barrio_id": bid, "municipio": mun, "tipo": tipo, "confianza": conf}  # noqa: E731
        self.alias = {
            ("medellin", "laureles"): A(1, "Medellín", "sector"),
            ("", "laureles"): A(1, "Medellín", "sector"),
            ("medellin", "castropol"): A(2, "Medellín"),
            ("envigado", "loma de las brujas"): A(3, "Envigado", "sector"),
            ("envigado", "zuniga"): A(4, "Envigado"),
            ("", "el poblado"): {"barrio_id": None, "municipio": "Medellín", "tipo": "municipio", "confianza": 0.9},
            ("", "envigado"): {"barrio_id": None, "municipio": "Envigado", "tipo": "municipio", "confianza": 0.95},
            ("", "medellin"): {"barrio_id": None, "municipio": "Medellín", "tipo": "municipio", "confianza": 0.95},
        }
        self.por_municipio = {}
        for b in self.barrios.values():
            self.por_municipio.setdefault(b["municipio_clave"], []).append(b)
        self.nombres_titulo = {"envigado": [("loma de las brujas", 3), ("zuniga", 4)], "medellin": [("castropol", 2), ("laureles", 1)]}
        self.cajas = [(6.20, 6.25, -75.60, -75.55, 2)]
        self.creado = 0


def test_clave():
    assert bs.clave("  Zúñiga – Sector  ") == "zuniga sector"
    assert bs.clave(None) == ""


def test_en_poligono():
    assert bs._en_poligono(6.22, -75.57, CUADRO)
    assert not bs._en_poligono(6.30, -75.57, CUADRO)


def test_por_texto_variantes_y_errores():
    cat = CatalogoFalso()
    assert cat.por_texto("Sector Laureles", "Medellín")[0] == 1          # quita "sector"
    assert cat.por_texto("laureles", "Bello")[0] == 1                    # alias sin municipio
    assert cat.por_texto("Castropoll", "Medellín")[0] == 2               # error de digitación
    assert cat.por_texto("Medellín", "Medellín") is None                 # es el municipio, no un barrio


def test_municipio_corrige_el_poblado():
    assert CatalogoFalso().municipio_de("El Poblado") == "Medellín"


def test_prioridades_de_asignacion():
    cat = CatalogoFalso()
    # Coordenadas exactas dentro del polígono oficial ganan sobre el texto.
    a = bs.asignar({"ciudad": "Medellín", "zona": "Laureles", "latitud": 6.22, "longitud": -75.57, "ubicacion_aproximada": False}, cat)
    assert (a["barrio_id"], a["fuente"]) == (2, "poligono")
    # Sin coordenadas exactas: el texto.
    a = bs.asignar({"ciudad": "Medellín", "zona": "Laureles", "latitud": 6.22, "longitud": -75.57, "ubicacion_aproximada": True}, cat)
    assert (a["barrio_id"], a["fuente"]) == (1, "texto")
    # Sin texto: el título, en su municipio.
    a = bs.asignar({"ciudad": "Envigado", "titulo": "APARTAMENTO EN LOMA DE LAS BRUJAS - ENVIGADO"}, cat)
    assert (a["barrio_id"], a["fuente"]) == (3, "titulo")
    # Sin texto ni título: el barrio más cercano (no un "sector").
    a = bs.asignar({"ciudad": "Envigado", "titulo": "Apartamento", "latitud": 6.181, "longitud": -75.584, "ubicacion_aproximada": True}, cat)
    assert (a["barrio_id"], a["fuente"]) == (4, "coordenadas") and a["confianza"] <= 0.6
    # Lejos de todo: sin barrio, pero con municipio.
    a = bs.asignar({"ciudad": "Envigado", "titulo": "Lote", "latitud": 6.5, "longitud": -75.2}, cat)
    assert a["barrio_id"] is None and a["municipio"] == "Envigado"


def test_barrios_de_pedido():
    cat = CatalogoFalso()
    assert bs.barrios_de_pedido({"zonas": ["Laureles", "Zuñiga", "Marte"], "ciudades": ["Medellín", "Envigado"]}, cat) == [1, 4]
