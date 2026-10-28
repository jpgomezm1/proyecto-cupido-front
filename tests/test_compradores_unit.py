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


def test_porque_dice_frescura_margen_y_zona():
    from src.services import compradores_service as cs
    ficha = {"precio": 640_000_000, "zona": "Laureles"}
    assert cs._porque({"zonas": ["Laureles"]}, ficha, 2, 700_000_000) == \
        "Su presupuesto te cubre con $60 M de margen · solo busca en Laureles"
    assert "Pide $20 M menos: negociable" in cs._porque({"zonas": ["Laureles", "Belén"]}, ficha, 0, 620_000_000)
    assert "busca en 2 zonas, entre ellas la tuya" in cs._porque({"zonas": ["Laureles", "Belén"]}, ficha, 0, 620_000_000)
    assert cs._porque({}, ficha, 1, 642_000_000) == "Su presupuesto es justo tu precio"
    assert cs._porque({}, ficha, 2, 700_000_000, "Valle de Aburrá").startswith("Encaja con su opción «Valle de Aburrá»")


def test_valor_premia_lo_reciente_sobre_lo_viejo():
    from datetime import datetime, timedelta
    from src.services import compradores_service as cs
    ficha = {"precio": 600_000_000, "zona": "Laureles"}
    ayer = {"fecha_captura": datetime.now() - timedelta(days=1)}
    viejo = {"fecha_captura": datetime.now() - timedelta(days=90)}
    assert cs._valor(90, ayer, {}, ficha) > cs._valor(100, viejo, {}, ficha)


def test_pedido_con_opciones_y_unidad_puntual():
    from src.services import compradores_service as cs
    from src.services.pedidos_ia import _compat_v1
    v2 = {"_v": 2, "negocio": "venta", "tipos": ["apartamento", "casa"], "ubicaciones": [], "unidades": [],
          "opciones": [
              {"etiqueta": "Valle de Aburrá", "tipos": ["apartamento"], "presupuesto_max": 450_000_000, "habitaciones_min": 2,
               "ubicaciones": [{"nombre": "Envigado", "nivel": "municipio"}, {"nombre": "Laureles", "nivel": "barrio"}]},
              {"etiqueta": "Oriente", "tipos": ["casa"], "presupuesto_max": 750_000_000, "habitaciones_min": 3,
               "ubicaciones": [{"nombre": "Oriente antioqueño", "nivel": "region"}]}]}
    crit = {**v2, **_compat_v1(v2)}
    apto = {"tipo": "apartamento", "negocio": "venta", "ciudad": "Envigado", "zona": "Zúñiga", "precio": 430_000_000,
            "habitaciones": 2, "texto": ""}
    puntaje, razones, desc, opcion, _ = cs.puntuar_pedido(apto, crit)
    assert not desc and opcion == "Valle de Aburrá" and puntaje >= 90          # el municipio cuenta aunque nombre barrios

    urb = {"_v": 2, "zonas": ["Belén Fátima", "Laureles"], "ciudades": ["Medellín"],
           "unidades": [{"nombre": "Urbanity", "tipo": "puntual"}], "presupuesto_max": 620_000_000}
    ficha = {"zona": "Laureles", "ciudad": "Medellín", "precio": 640_000_000, "texto": "apto en Laureles"}
    p, raz, _, op, c = cs.puntuar_pedido(ficha, urb)
    filas = {f["criterio"]: f for f in cs.detalle_encaje(ficha, c, raz, op)}
    assert filas["Zona"]["estado"] == "si" and filas["Zona"]["nota"] == "1 de sus 2 opciones de zona"
    assert filas["Unidad"]["estado"] == "no" and filas["Unidad"]["nota"] == "Es una de sus alternativas"
    assert filas["Precio"]["estado"] == "duda" and "$20 M por encima" in filas["Precio"]["nota"]
