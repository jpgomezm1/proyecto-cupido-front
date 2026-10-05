"""Puntaje inmueble <-> pedido (sin BD ni IA)."""
from src.services.compradores_service import _misma_zona, es_entrada_de_inmueble, puntuar


def ficha(**kw):
    base = {"tipo": "Apartamento", "negocio": "venta", "ciudad": "Medellín", "zona": "Laureles",
            "precio": 560_000_000, "habitaciones": 3, "banos": 2, "parqueaderos": 1, "area_m2": 86,
            "amenidades": ["balcón", "ascensor"], "texto": "Apartamento con balcón y buena luz"}
    base.update(kw)
    return base


def pedido(**kw):
    base = {"negocio": "venta", "tipos": ["apartamento"], "zonas": ["Laureles"], "ciudades": ["Medellín"],
            "zonas_excluidas": [], "presupuesto_min": None, "presupuesto_max": 600_000_000,
            "habitaciones_min": 3, "banos_min": 2, "parqueaderos_min": 1, "area_min": 70, "area_max": 90,
            "exigencias": ["balcón"], "excluye": []}
    base.update(kw)
    return base


def test_encaje_perfecto_cerca_de_100():
    puntaje, razones, descartado = puntuar(ficha(), pedido())
    assert not descartado
    assert puntaje >= 90
    assert all(r["ok"] for r in razones if r["criterio"] in ("zona", "presupuesto", "habitaciones"))


def test_otro_tipo_descarta():
    assert puntuar(ficha(tipo="Casa"), pedido())[2] is True


def test_arriendo_vs_venta_descarta():
    assert puntuar(ficha(negocio="arriendo"), pedido())[2] is True


def test_muy_por_encima_del_presupuesto_descarta():
    assert puntuar(ficha(precio=900_000_000), pedido())[2] is True


def test_un_poco_por_encima_baja_pero_no_descarta():
    p_ok = puntuar(ficha(), pedido())[0]
    p, razones, desc = puntuar(ficha(precio=650_000_000), pedido())
    assert not desc and p < p_ok
    assert any(r["criterio"] == "presupuesto" and r["ok"] is None for r in razones)


def test_no_acepta_duplex():
    assert puntuar(ficha(texto="Hermoso dúplex en Laureles"), pedido(excluye=["dúplex"]))[2] is True


def test_zona_excluida_descarta():
    assert puntuar(ficha(zona="La Abadía", ciudad="Envigado"),
                   pedido(zonas=["Loma de las Brujas"], ciudades=["Envigado"], zonas_excluidas=["Abadía"]))[2] is True


def test_otra_zona_queda_limitada():
    p, razones, _ = puntuar(ficha(zona="Belén"), pedido())
    assert p <= 55
    assert any(r["criterio"] == "zona" and r["ok"] is False for r in razones)


def test_misma_zona_tolerante():
    assert _misma_zona("El Poblado", "poblado")
    assert _misma_zona("Loma de las Brujas", "Las Brujas")
    assert _misma_zona("Laureles", "Laureles Estadio")
    assert not _misma_zona("Laureles", "Belén")


def test_exigencia_no_mencionada_queda_por_confirmar():
    _, razones, _ = puntuar(ficha(amenidades=[], texto="Apartamento"), pedido(exigencias=["piscina"]))
    assert {"criterio": "exigencias", "ok": None, "texto": "piscina"} in razones


def test_links_son_entrada_de_inmueble():
    assert es_entrada_de_inmueble("mira este https://inmobiliaria.wasi.co/apartamento-venta-laureles/123")
    assert not es_entrada_de_inmueble("apto en laureles 3 hab")
