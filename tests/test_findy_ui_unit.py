"""Las respuestas de Findy como programas OpenUI (findy_ui), sin BD ni IA.

Que el programa además lo entienda el parser de OpenUI con los esquemas reales se revisa en
el frontend: `npm run openui:validar` sobre programas de ejemplo.
"""
import re

from src.services import findy_ui as ui


def _lineas(p):
    return p.splitlines()


def test_valores_escapados():
    assert ui._v('dice "hola"\ny sigue') == '"dice \\"hola\\"\\ny sigue"'
    assert ui._v("Belén · $640 M") == '"Belén · $640 M"'
    assert ui._v({"valor": "3", "detalle": None}) == '{valor: "3"}'
    assert ui._v([1, 2.5, True, None]) == "[1, 2.5, true, null]"
    assert ui._llamada("Inmuebles", "Título", [1, 2], None) == 'Inmuebles("Título", [1, 2])'


def test_root_primero_y_todo_referenciado():
    p = ui.programa_preanalisis("¿Cómo está Laureles?", None, None)
    lineas = _lineas(p)
    assert lineas[0].startswith("root = Respuesta([")
    usados = set(re.findall(r"b\d+", lineas[0]))
    definidos = {l.split(" = ")[0] for l in lineas[1:]}
    assert usados == definidos
    assert 'AnalizarAFondo("¿Cómo está Laureles?")' in p


def test_preanalisis_con_zona_trae_cifras():
    balance = {"oferta_inventario": 336, "demanda_total": 73, "clasificacion": "frio",
               "detalle_oferta": {"precio_m2_mediana": 7_307_692, "dias_inventario_promedio": 148.5}}
    p = ui.programa_preanalisis("¿Cómo está Laureles?", "Laureles", balance)
    assert "**Laureles está fría: sobra oferta** en apartamentos." in p
    assert '{valor: "336", etiqueta: "apartamentos en venta hoy"}' in p and '"$7,3 M"' in p and '"148 días"' in p


def test_preanalisis_con_espejo_de_precios():
    balance = {"oferta_inventario": 337, "demanda_total": 73, "clasificacion": "frio", "detalle_oferta": {}}
    rangos = [{"rango": "Menos de $500M", "oferta": 29, "demanda": 15}, {"rango": "$500M a $800M", "oferta": 122, "demanda": 27},
              {"rango": "$800M a $1.200M", "oferta": 141, "demanda": 19}, {"rango": "Más de $3.000M", "oferta": 0, "demanda": 0}]
    p = ui.programa_preanalisis("¿Cómo está Laureles?", "Laureles", balance, rangos)
    assert 'Espejo("En Laureles, el rango con más compradores por apartamento: Menos de $500 M"' in p
    assert "Más de $3.000" not in p and '{etiqueta: "$500 M a $800 M", izq: 122, der: 27}' in p
    hueco = ui.programa_preanalisis("¿Cómo está Envigado?", "Envigado", balance,
                                    [{"rango": "$500M a $800M", "oferta": 321, "demanda": 74},
                                     {"rango": "$1.800M a $3.000M", "oferta": 34, "demanda": 47}])
    assert "En Envigado hay más compradores que apartamentos en venta en el rango $1.800 M a $3.000 M" in hueco


def test_compradores_destacados_y_plegados():
    def c(i, grupo, accion="conectar"):
        return {"pedido_id": i, "busca": "Apartamento en Laureles", "presupuesto_legible": "$700 millones",
                "score": 96, "nivel": "perfecto", "hace": "hace 2 días", "porque": "Lo pidió hace 2 días",
                "accion": accion, "grupo": grupo}
    lista = [c(1, "top"), c(2, "top"), c(3, "top"), c(4, "vale_la_pena"), c(5, "resto")]
    p = ui.programa_compradores("Encontré 5.", {"titulo": None, "tipo": "apartamento", "zona": "Laureles",
                                                "precio": 640_000_000, "precio_legible": "$640 millones",
                                                "area_m2": 95, "habitaciones": 3, "origen": "texto"},
                                lista, {"recientes": 4, "perfecto": 5}, 5)
    assert 'Compradores("Empieza por estos 3", [' in p
    assert 'Compradores("Otro que vale la pena", [' in p and p.rstrip().count("true)") == 1
    assert "pedido: 5" not in p                       # el «resto» no se lista, solo se cuenta
    assert "Te conectamos" in p                        # todos conectar → aviso
    assert "¿Y si lo bajo a $595 M?" in p
    assert 'TuInmueble("Apartamento en Laureles", "$640 millones", ["95 m²", "3 hab"], "Descrito por ti")' in p


def test_avisa_lo_que_las_publicaciones_no_traen():
    rs = [{"id": i, "requisitos": [{"texto": "piso 4+", "estado": "duda"}, {"texto": "balcón", "estado": "si"}]}
          for i in range(5)]
    p = ui.programa_busqueda("Encontré 5.", {"chips": ["Laureles"]}, rs, {"search_type": "v3"})
    assert "Las publicaciones casi nunca dicen el piso" in p and "balcón" not in p.split("Aviso(")[1].split(")")[0]
    # Si la mayoría sí lo trae, no hay aviso
    rs2 = [{"id": i, "requisitos": [{"texto": "piso 4+", "estado": "si" if i else "duda"}]} for i in range(5)]
    assert "Aviso(" not in ui.programa_busqueda("Encontré 5.", {}, rs2, {"search_type": "v3"})


def test_busqueda_sin_resultados_sugiere_ajustes():
    p = ui.programa_busqueda("No encontré.", {"chips": ["Laureles"]}, [], {"search_type": "v3"})
    assert 'Entendi(["Laureles"])' in p and "Inmuebles(" not in p and "Siguientes(" in p


def test_compradores_con_contexto_del_mercado():
    ctx = {"pedidos": 163, "pide": [{"texto": "balcón", "n": 44}, {"texto": "cuarto útil", "n": 26}],
           "presupuesto_mediana": 800_000_000, "pagan_contado": 25, "con_credito": 7}
    p = ui.programa_compradores("Encontré.", None, [{"pedido_id": 1, "busca": "Apto", "grupo": "top", "accion": "conectar"}],
                                {"recientes": 1, "perfecto": 1}, 163, ctx)
    assert 'Barras("Lo que más piden quienes encajan con tu inmueble", [{etiqueta: "Balcón", valor: 44, texto: "44 de 163"}' in p
    assert "la mitad tiene presupuesto de hasta $800 M, 25 pagan de contado, 7 con crédito." in p
    assert "Barras(" not in ui.programa_compradores("x", None, [], {}, 0, {"pedidos": 0})


def test_busqueda_con_comparativa_de_los_primeros():
    res = [{"id": i} for i in (11, 22, 33, 44)]
    link = "https://getfynder.com/comparar/abc.def"
    p = ui.programa_busqueda("Encontré 4", {"chips": []}, res, {"comparar": link})
    assert f'Inmuebles("4 inmuebles para tu cliente", [11, 22, 33, 44], "{link}")' in p
    sin = ui.programa_busqueda("Encontré 4", {"chips": []}, res, {})
    assert 'Inmuebles("4 inmuebles para tu cliente", [11, 22, 33, 44])' in sin
