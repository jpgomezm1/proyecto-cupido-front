"""Chat de Mi página: solo pasan las operaciones que se pueden aplicar (sin BD ni IA)."""

import json

import pytest

from src.services import pagina_chat_service as s

BLOQUES = [{"id": "portada", "tipo": "portada"}, {"id": "sobremi", "tipo": "sobre_mi"}, {"id": "ab12cd34", "tipo": "banner"}]


def op(**k):
    base = {"op": "", "campo": "", "id": "", "ruta": "", "tipo": "", "despues": "", "valor_json": "", "plantilla_inicio": ""}
    return {**base, **k}


def test_operaciones_validas_pasan_con_valor_parseado():
    r = s.validar([
        op(op="config", campo="plantilla", valor_json='"lujo"'),
        op(op="config", campo="color", valor_json='"#1E3A8A"'),
        op(op="agente", campo="zonas", valor_json='["Laureles", "Envigado"]'),
        op(op="bloque", id="ab12cd34", ruta="datos.titulo", valor_json='"¿Vas a vender?"'),
        op(op="bloque", id="ab12cd34", ruta="estilo.fondo", valor_json='"oscuro"'),
        op(op="agregar", tipo="proceso", despues="sobremi", valor_json=json.dumps({"datos": {"titulo": "Así trabajo"}})),
        op(op="mover", id="ab12cd34", despues="portada"),
        op(op="ocultar", id="portada"),
        op(op="inicio", plantilla_inicio="lujo"),
    ], BLOQUES)
    assert [x["op"] for x in r] == ["config", "config", "agente", "bloque", "bloque", "agregar", "mover", "ocultar", "inicio"]
    assert r[2]["valor"] == ["Laureles", "Envigado"]
    assert r[5]["datos"] == {"titulo": "Así trabajo"} and r[5]["despues"] == "sobremi"


def test_se_descarta_lo_que_no_cuadra():
    r = s.validar([
        op(op="config", campo="pagina_slug", valor_json='"otro"'),          # campo fuera de la lista
        op(op="bloque", id="noexiste", ruta="datos.titulo", valor_json='"x"'),
        op(op="bloque", id="ab12cd34", ruta="datos.__proto__.x", valor_json='"x"'),
        op(op="bloque", id="portada", ruta="datos.titulo", valor_json='"x"'),  # la portada no tiene datos
        op(op="quitar", id="portada"),
        op(op="mover", id="ab12cd34", despues="noexiste"),
        op(op="agregar", tipo="portada"),
        op(op="agregar", tipo="banner", despues="noexiste"),
        op(op="inicio", plantilla_inicio="otra"),
        op(op="borrar_todo"),
    ], BLOQUES)
    assert r == []


def test_urls_peligrosas_no_pasan_y_texto_suelto_si():
    r = s.validar([
        op(op="agente", campo="logo_url", valor_json='"javascript:alert(1)"'),
        op(op="agente", campo="foto_url", valor_json='"http://inseguro.com/a.jpg"'),
        op(op="config", campo="titular", valor_json="Texto sin comillas"),
        op(op="config", campo="portada_url", valor_json='"https://a.com/f.jpg"'),
    ], BLOQUES)
    assert r == [{"op": "config", "campo": "titular", "valor": "Texto sin comillas"},
                 {"op": "config", "campo": "portada_url", "valor": "https://a.com/f.jpg"}]


def test_imagen_propuesta_con_destino_valido():
    ids = {b["id"] for b in BLOQUES}
    assert s._imagen({"imagen": {"proponer": False}}, ids) is None
    im = s._imagen({"imagen": {"proponer": True, "descripcion": "terraza en Laureles", "estilo": "atardecer", "formato": "ancha",
                               "id": "ab12cd34", "ruta": "datos.imagen_url"}}, ids)
    assert im == {"descripcion": "terraza en Laureles", "estilo": "atardecer", "formato": "ancha", "id": "ab12cd34", "ruta": "datos.imagen_url"}
    im = s._imagen({"imagen": {"proponer": True, "descripcion": "sala luminosa", "estilo": "x", "formato": "x", "id": "nada", "ruta": "otra"}}, ids)
    assert (im["id"], im["ruta"], im["estilo"], im["formato"]) == ("portada", "config.portada_url", "natural", "ancha")
    # «nuevo»: la sección que se agrega en la misma respuesta; la portada siempre va a config.portada_url
    nuevo = {"proponer": True, "descripcion": "terraza en Laureles", "estilo": "natural", "formato": "ancha", "id": "nuevo", "ruta": "datos.imagen_url"}
    assert s._imagen({"imagen": nuevo}, ids, agrega=True)["id"] == "nuevo"
    assert s._imagen({"imagen": nuevo}, ids, agrega=False)["id"] == "portada"
    assert s._imagen({"imagen": {**nuevo, "id": "portada", "ruta": "estilo.imagen_url"}}, ids)["ruta"] == "config.portada_url"


def test_sin_mensaje_del_agente_no_llama_a_la_ia(monkeypatch):
    monkeypatch.setattr(s.ia, "_llamar", lambda *a, **k: pytest.fail("no debía llamar a la IA"))
    with pytest.raises(s.ChatPaginaError):
        s.conversar(1, [{"rol": "findy", "texto": "Hola"}], {"config": {}})


def test_cupo_diario_se_respeta(monkeypatch):
    def lleno(uid):
        raise s.ia.PaginaIAError("limite", "Usaste los 30 mensajes de hoy")
    monkeypatch.setattr(s.ia, "_cupo", lleno)
    monkeypatch.setattr(s.ia, "_llamar", lambda *a, **k: pytest.fail("no debía llamar a la IA"))
    with pytest.raises(s.ia.PaginaIAError):
        s.conversar(1, [{"rol": "agente", "texto": "hazla azul"}], {"config": {"bloques": BLOQUES}})
