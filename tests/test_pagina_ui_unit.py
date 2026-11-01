"""Programas OpenUI del chat de Mi página: bien formados y con el texto escapado."""

from src.services import pagina_ui


def test_programa_con_controles():
    p = pagina_ui.programa('Te dejo opciones "a tu gusto": ¿cuál?', [
        {"tipo": "paleta", "titulo": "Elige un color", "opciones": ["#1E3A8A", "#0F766E"]},
        {"tipo": "textos", "titulo": "Titular", "opciones": ["Tu hogar en Laureles", "Casas con carácter"],
         "destino": {"op": "config", "campo": "titular"}},
    ])
    lineas = p.splitlines()
    assert lineas[0] == "root = Respuesta([b0, b1, b2])"
    assert lineas[1] == 'b0 = Texto("Te dejo opciones \\"a tu gusto\\": ¿cuál?")'
    assert lineas[2] == 'b1 = Paleta("Elige un color", ["#1E3A8A", "#0F766E"])'
    assert lineas[3] == 'b2 = Textos("Titular", ["Tu hogar en Laureles", "Casas con carácter"], {op: "config", campo: "titular"})'
