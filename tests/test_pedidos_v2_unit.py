"""Pedidos versión 2 (pedidos_ia): reglas fijas y compatibilidad con la versión 1, sin IA ni BD."""
from src.services import pedidos_ia as pia


def test_compat_v1_regiones_unidades_y_opciones():
    p = {"negocio": "venta", "tipos": [],
         "ubicaciones": [{"nombre": "Laureles", "nivel": "barrio", "municipio": "Medellín"},
                         {"nombre": "Envigado", "nivel": "municipio"}],
         "unidades": [{"nombre": "Urbanity", "tipo": "puntual"}],
         "obligatorias": ["unidad_cerrada", "balcon"], "excluye": ["primer piso"],
         "presupuesto_max": 450_000_000,
         "opciones": [{"etiqueta": "Oriente", "tipos": ["casa"], "presupuesto_max": 750_000_000,
                       "ubicaciones": [{"nombre": "Oriente antioqueño", "nivel": "region"}]}]}
    v1 = pia._compat_v1(p)
    assert v1["zonas"] == ["Laureles"]                      # ni el municipio, ni la región, ni la unidad
    assert set(v1["ciudades"]) == {"Medellín", "Envigado"}
    assert v1["tipos"] == ["casa"] and v1["presupuesto_max"] == 750_000_000   # unión de las opciones
    assert v1["exigencias"] == ["unidad cerrada", "balcón"] and v1["excluye"] == ["primer piso"]


def test_validar_quita_lo_que_el_pedido_no_dice():
    p = {"negocio": "venta", "perfil": ["familia", "extranjero"], "obligatorias": ["parqueadero_cubierto", "ascensor"],
         "deseables": [{"caracteristica": "ascensor", "peso": 2}, {"caracteristica": "balcon", "peso": 1}],
         "unidades": [{"nombre": "Parcelación", "tipo": "estilo"}, {"nombre": "Urbanity", "tipo": "puntual"}],
         "presupuesto_max": 17_000_000_000_000, "opciones": []}
    v = pia._validar_v2(p, "Es para extranjero. Parqueadero y ascensor indispensables. Hasta 17.000.000 millones")
    assert v["perfil"] == ["extranjero"]                                  # «familia» no aparece en el texto
    assert v["obligatorias"] == ["ascensor"] and v["parqueaderos_min"] == 1   # «parqueadero» no es «cubierto»
    assert [d["caracteristica"] for d in v["deseables"]] == ["balcon"]   # no repite una obligatoria
    assert [u["nombre"] for u in v["unidades"]] == ["Urbanity"]          # «parcelación» no es una unidad
    assert v["presupuesto_max"] is None                                  # absurdo → sin dato


def test_validar_respeta_el_parqueadero_cubierto_si_lo_dice():
    v = pia._validar_v2({"obligatorias": ["parqueadero_cubierto"], "opciones": []}, "parqueadero cubierto")
    assert v["obligatorias"] == ["parqueadero_cubierto"]


def test_arriendo_con_su_propio_techo():
    v = pia._validar_v2({"negocio": "arriendo", "presupuesto_max": 13_000_000, "opciones": []}, "")
    assert v["presupuesto_max"] == 13_000_000


def test_acepta_textos_donde_van_objetos():
    v = pia._validar_v2({"ubicaciones": ["Laureles"], "unidades": ["Urbanity"], "deseables": ["balcon"],
                         "opciones": ["opción rara", {"etiqueta": "A", "ubicaciones": ["Envigado"]}]}, "")
    assert v["ubicaciones"] == [{"nombre": "Laureles", "nivel": "barrio"}]
    assert v["unidades"][0]["nombre"] == "Urbanity" and v["deseables"][0]["caracteristica"] == "balcon"
    assert len(v["opciones"]) == 1 and v["opciones"][0]["ubicaciones"][0]["nombre"] == "Envigado"
    assert pia._compat_v1(v)["zonas"] == ["Laureles", "Envigado"]
