"""Mensajes de la línea de ventas (sin base de datos)."""
from src.services import ventas_service as v

CIFRAS = {"inmuebles": 6958, "pedidos": 4015}


def _a(**kw):
    base = {"telefono_10": "3001234567", "nombre": "Carolina Restrepo", "gancho": {"tipo": "general"}}
    base.update(kw)
    return base


def test_primer_nombre_ignora_lo_que_no_es_nombre():
    assert v._primer_nombre("Carolina Restrepo") == "Carolina"
    assert v._primer_nombre("LuzEnith Agudelo") == "Luzenith"
    assert v._primer_nombre("Dueño") is None
    assert v._primer_nombre("Inmobiliaria Los Andes") == "Los" or v._primer_nombre("Inmobiliaria Los Andes") is None
    assert v._primer_nombre("Comprador") is None
    assert v._primer_nombre(None) is None


def test_millones_y_mas_de():
    assert v._millones(620_000_000) == "$620 millones"
    assert v._millones(2_200_000_000) == "$2,2 mil millones"
    assert v._millones(None) is None
    assert v._mas_de(6958) == "6.900"
    assert v._mas_de(4015) == "4.000"


def test_mensaje_inmueble_lleva_datos_permiso_y_salida():
    a = _a(gancho={"tipo": "inmueble", "n": 14, "tipo_inmueble": "apartamento", "zona": "Laureles", "precio": 620_000_000})
    m = v.mensaje(a, "Laura", CIFRAS)
    assert m.startswith("Hola Carolina")
    assert "14" in m and "Laureles" in m
    assert "15 minutos" in m or "llamada corta" in m
    assert v.SALIDA in m
    assert "Tenemos" not in m       # los compradores no son de Fynder


def test_mensaje_sin_nombre_ni_remitente():
    m = v.mensaje(_a(nombre="Dueño"), "", CIFRAS)
    assert m.startswith("Hola, te escribo de Fynder")
    assert "6.900" in m and "4.000" in m


def test_mensaje_hernan_nombra_a_hernan_aunque_tenga_otro_gancho():
    assert "Hernán" in v.mensaje(_a(gancho={"tipo": "hernan"}), "Laura", CIFRAS)
    otro = _a(fuente="hernan", gancho={"tipo": "inventario", "n": 9})
    assert "Hernán" in v.mensaje(otro, "Laura", CIFRAS)
    assert "Hernán" in v.mensaje(_a(fuente="hernan", gancho=None), "Laura", CIFRAS)


def test_mensajes_caben_en_whatsapp_y_el_link_se_codifica():
    for g in ({"tipo": "inmueble", "n": 3, "tipo_inmueble": "casa", "zona": "Envigado", "precio": 900_000_000},
              {"tipo": "pedido", "n": 6, "busca": "apartamento de 3 habitaciones en Belén hasta $450 millones", "dias": 14},
              {"tipo": "inventario", "n": 33}, {"tipo": "general"}):
        m = v.mensaje(_a(gancho=g), "Laura", CIFRAS)
        assert len(m) < 600
        link = v.link_whatsapp("3001234567", m)
        assert link.startswith("https://wa.me/573001234567?text=") and " " not in link


def test_variante_estable_por_telefono():
    assert v._variante("3001234567", 3) == v._variante("3001234567", 3)
