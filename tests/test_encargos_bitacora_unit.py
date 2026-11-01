"""Encargos que aprenden: lo que no le gustó de un inmueble ajusta el perfil (reglas, sin IA ni BD)."""
from src.services.encargos_bitacora_service import aplicar_motivos

PERFIL = {"tipos": ["apartamento"], "ubicaciones": [{"nombre": "El Poblado"}],
          "presupuesto_min": 800_000_000, "presupuesto_max": 1_000_000_000,
          "deseables": [{"caracteristica": "piso_alto", "peso": 2}]}
INMUEBLE = {"id": 1, "precio": 950_000_000, "zona": "Castropol", "area_construida": 90}


def test_caro_baja_el_tope_por_debajo_de_ese_precio():
    q = aplicar_motivos(PERFIL, INMUEBLE, ["caro"], "no_le_gusta")
    assert q["presupuesto_max"] == 900_000_000


def test_caro_no_rompe_el_rango():
    q = aplicar_motivos({**PERFIL, "presupuesto_min": 900_000_000}, INMUEBLE, ["caro"], "no_le_gusta")
    assert q["presupuesto_max"] == 1_000_000_000


def test_zona_se_excluye_si_no_es_la_que_pidio():
    q = aplicar_motivos(PERFIL, INMUEBLE, ["zona"], "no_le_gusta")
    assert q["ubicaciones_excluidas"] == ["Castropol"]
    q2 = aplicar_motivos(PERFIL, {**INMUEBLE, "zona": "El Poblado"}, ["zona"], "no_le_gusta")
    assert not q2.get("ubicaciones_excluidas")


def test_pequeno_oscuro_y_piso_bajo():
    q = aplicar_motivos(PERFIL, INMUEBLE, ["pequeno", "oscuro", "piso_bajo", "parqueadero"], "no_le_gusta")
    assert q["area_min"] == 99
    assert set(q["obligatorias"]) == {"iluminado", "piso_alto"}
    assert not any(d["caracteristica"] == "piso_alto" for d in q["deseables"])   # pasó de ojalá a sí o sí
    assert q["parqueaderos_min"] == 1


def test_le_gusto_la_vista_suma_un_ojala():
    q = aplicar_motivos(PERFIL, INMUEBLE, ["vista", "precio"], "le_gusta")
    assert {"caracteristica": "vista_panoramica", "peso": 3} in q["deseables"]
    assert q["presupuesto_max"] == PERFIL["presupuesto_max"]


def test_no_toca_el_perfil_original():
    aplicar_motivos(PERFIL, INMUEBLE, ["oscuro", "zona"], "no_le_gusta")
    assert "obligatorias" not in PERFIL and "ubicaciones_excluidas" not in PERFIL
