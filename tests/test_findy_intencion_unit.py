"""Una sola barra en Findy: el router de intención por reglas (sin IA)."""
import pytest

from src.services import findy_intencion as fi

CASOS = [
    # Buscar inmuebles para un cliente (frases del journey y de los grupos)
    ("Busco para mi cliente un apartamento en venta en Laureles o Belén, de 3 habitaciones y 2 baños, con "
     "parqueadero, hasta $650 millones. Que tenga balcón y no sea primer piso.", None, "propiedades"),
    ("Busco apto para compra en Urbanity, Belén Fátima, Laureles Unicentro, 3 habitaciones, presupuesto hasta 620 "
     "millones", None, "propiedades"),
    ("Solicito Apartamento: Laureles, Nogal, Belén. 3 alcobas, 2 baños, balcón. Presupuesto $750.000.000", None, "propiedades"),
    ("Necesito casa en Envigado con patio para mi clienta", None, "propiedades"),
    ("Mi cliente busca apto en El Poblado hasta 900 millones", None, "propiedades"),
    ("Tengo un cliente que busca apartamento en Sabaneta", None, "propiedades"),
    ("apto en laureles 3 hab hasta 600", "propiedades", "propiedades"),
    # Tengo un inmueble: ¿quién lo busca?
    ("Tengo un apartamento en venta en Laureles, 3 habitaciones, 2 baños, 1 parqueadero, 95 m², piso 6 con "
     "ascensor y balcón, en $640 millones.", None, "compradores"),
    ("https://inmobiliaria.wasi.co/apartamento-venta-laureles/123456", None, "compradores"),
    ("código 4521", None, "compradores"),
    ("¿Quién busca un apto como este? 85 m² en Envigado, 520 millones", None, "compradores"),
    ("Capté una casa en Rionegro de 400 m²", None, "compradores"),
    ("Estoy vendiendo un local en el centro", None, "compradores"),
    ("Mi apartamento en Belén, compradores para él", None, "compradores"),
    # Preguntas de mercado
    ("¿Cómo está el mercado de apartamentos en Laureles?", None, "analisis"),
    ("¿A cuánto capto un apartamento de 90 m² en Laureles?", None, "analisis"),
    ("¿En qué zona de Medellín conviene más captar ahora?", None, "analisis"),
    ("Compáralo con Belén y dime en cuál le conviene más captar", "analisis", "analisis"),
    ("¿Dónde capto en Envigado?", None, "analisis"),
    ("¿Por qué no se vende mi apto de Belén?", None, "analisis"),
    ("¿Cuánto se demora en venderse un apto en Sabaneta?", None, "analisis"),
    ("Tengo un apto en Laureles de 90 m², ¿a cuánto lo capto?", None, "analisis"),
    ("¿Cuánto vale el m2 en El Poblado?", None, "analisis"),
    # Seguir la conversación
    ("¿Y si lo bajo a $590 millones, cuántos más aparecen?", "compradores", "compradores"),
    ("¿Y si fuera de 2 habitaciones?", "compradores", "compradores"),
    ("Son muchas, déjame solo las 5 mejores para mi cliente.", "propiedades", "propiedades"),
    ("Que tenga ascensor y sea piso 4 o más alto.", "propiedades", "propiedades"),
    ("Quita lo del ascensor.", "propiedades", "propiedades"),
    ("Mejor solo en Laureles y súbele a $700 millones.", "propiedades", "propiedades"),
    ("¿Y en Belén?", "preanalisis", "analisis"),
]


@pytest.mark.parametrize("texto,previo,esperado", CASOS)
def test_reglas(texto, previo, esperado):
    modo, razon = fi.clasificar(texto, previo) if previo else fi.por_reglas(texto)
    assert modo == esperado, f"{texto!r} → {modo} ({razon})"


def test_sin_senal_va_a_la_ia_y_si_falla_busca(monkeypatch):
    monkeypatch.setattr(fi, "_con_ia", lambda t, p: None)
    assert fi.clasificar("hola") == ("propiedades", "por_defecto")
    monkeypatch.setattr(fi, "_con_ia", lambda t, p: "analisis")
    assert fi.clasificar("qué opinas de Itagüí") == ("analisis", "ia")
