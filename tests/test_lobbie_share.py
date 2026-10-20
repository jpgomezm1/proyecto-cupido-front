"""La página de compartir de Lobbie (oct-2026): ubicación, tipo y cifras en bloques share-*."""
from bs4 import BeautifulSoup

from src.scrapers.lobbie import LobbieScraper

HTML = """
<html><head><title>Apartamento en venta</title></head><body>
<div class="share-hero-overlay">
  <p class="share-hero-overlay__location">Rodeo alto, Medellin</p>
  <p class="share-hero-overlay__price">COP 395.000.000</p>
</div>
<div class="share-card">
  <h1>Apartamento en venta</h1>
  <div>Código: <span>408436</span></div>
  <p class="share-fact-row">65 m² · 2 alcobas · 2 baños · 1 parqueaderos</p>
  <div>Más datos</div>
  <div><div>Administración</div><div>COP 350.000</div></div>
  <div><div>Estrato</div><div>0</div></div>
  <div>Descripción</div><p>Espectacular apartamento en piso 22.</p>
  <div>Esta página fue creada con Lobbie</div>
</div>
</body></html>
"""


def test_formato_share_completa_los_campos():
    soup = BeautifulSoup(HTML, "lxml")
    d = LobbieScraper()._extraer_datos_ssr(soup, HTML)
    assert d["codigo_propiedad"] == "408436"
    assert d["precio"] == 395_000_000
    assert d["tipo_propiedad"] == "Apartamento"
    assert d["tipo_negocio"] == "Venta"
    assert d["ciudad"] == "Medellín"
    assert d["zona"]
    assert d["area_construida"] == 65.0
    assert (d["habitaciones"], d["banos"], d["parqueaderos"]) == (2, 2, 1)
    assert d["administracion"] == 350_000
    assert d["estrato"] is None  # 0 = no especificado
    assert d["titulo"].startswith("Apartamento en")


def test_arriendo_en_el_encabezado():
    html = HTML.replace("Apartamento en venta", "Casa en arriendo")
    d = LobbieScraper()._extraer_datos_ssr(BeautifulSoup(html, "lxml"), html)
    assert d["tipo_propiedad"] == "Casa"
    assert d["tipo_negocio"] == "Arriendo"
