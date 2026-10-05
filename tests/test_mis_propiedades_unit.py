"""Validación de la edición de inmuebles por su dueño (sin BD)."""
import pytest

from src.services.mis_propiedades_service import EdicionError, _origen, validar


def test_numeros_y_textos_se_normalizan():
    sets = validar({"titulo": "  Apto con vista  ", "precio": "650.000.000", "area_construida": "86,5",
                    "habitaciones": 3, "direccion": "Cra 70 # 1-2", "tipo_negocio": "Venta"})
    assert sets == {"titulo": "Apto con vista", "precio": 650_000_000, "area_construida": 86.5,
                    "habitaciones": 3, "direccion_completa": "Cra 70 # 1-2", "tipo_negocio": "Venta"}


def test_amenidades_lista_sin_repetir():
    sets = validar({"amenidades_internas": ["Balcón", "  Estudio ", "Balcón", ""]})
    assert sets["amenidades_internas"] == "Balcón|Estudio"


@pytest.mark.parametrize("cambios,campo", [
    ({"precio": 600}, "precio"),                      # escrito en millones por error
    ({"precio": None}, "precio"),
    ({"titulo": ""}, "titulo"),
    ({"estrato": 9}, "estrato"),
    ({"tipo_negocio": "Permuta"}, "tipo_negocio"),
    ({"tipo_negocio": "Arriendo"}, "tipo_negocio"),     # solo venta
    ({"tipo_propiedad": "Castillo"}, "tipo_propiedad"),
    ({"habitaciones": True}, "habitaciones"),
    ({"descripcion": "x" * 9000}, "descripcion"),
])
def test_errores_dicen_el_campo(cambios, campo):
    with pytest.raises(EdicionError) as e:
        validar(cambios)
    assert e.value.campo == campo


def test_sin_cambios_validos():
    with pytest.raises(EdicionError):
        validar({"agente_captador_telefono": "3000000000", "activa": False})


def test_opcionales_se_pueden_vaciar():
    assert validar({"administracion": "", "parqueaderos": None}) == {"administracion": None, "parqueaderos": None}


def test_origen():
    assert _origen("Wasi_Captado") == "wasi"
    assert _origen("Lobbie") == "lobbie"
    assert _origen("Fynder") == "fynder"
    assert _origen("Tu360_Captado") == "otro"
