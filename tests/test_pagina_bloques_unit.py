"""Mi página por bloques: validación, compatibilidad con `secciones` y topes (sin BD)."""

from src.services import pagina_agente_service as p


def test_config_vieja_da_portada_y_secciones_en_orden():
    c = p.normalizar({"secciones": [{"id": "preguntas", "visible": False}, {"id": "sobre_mi"}]})
    tipos = [b["tipo"] for b in c["bloques"]]
    assert tipos[0] == "portada" and tipos[1:3] == ["preguntas", "sobre_mi"]
    assert sorted(tipos[1:]) == sorted(p.SECCIONES)
    assert c["bloques"][1]["visible"] is False
    assert c["secciones"][0] == {"id": "preguntas", "visible": False}


def test_sin_config_todo_visible():
    c = p.normalizar(None)
    assert [b["tipo"] for b in c["bloques"]] == ["portada", *p.SECCIONES]
    assert all(b["visible"] for b in c["bloques"])


def test_unicos_una_vez_repetibles_varias_y_portada_primero():
    c = p.normalizar({"bloques": [
        {"id": "aaaa1111", "tipo": "proceso", "datos": {"pasos": [{"titulo": "Te escucho"}]}},
        {"id": "aaaa1111", "tipo": "proceso", "datos": {"pasos": [{"titulo": "Busco"}]}},
        {"tipo": "testimonios"}, {"tipo": "testimonios"}, {"tipo": "portada"}, {"tipo": "inventado"},
    ]})
    tipos = [b["tipo"] for b in c["bloques"]]
    assert tipos == ["portada", "proceso", "proceso", "testimonios"]
    ids = [b["id"] for b in c["bloques"]]
    assert len(set(ids)) == len(ids) and ids[1] == "aaaa1111"
    # Las secciones quitadas del editor salen ocultas para el frontend anterior
    assert {"id": "preguntas", "visible": False} in c["secciones"]


def test_tope_de_bloques():
    c = p.normalizar({"bloques": [{"tipo": "banner"}] * 50})
    assert len(c["bloques"]) == p.MAX_BLOQUES and c["bloques"][0]["tipo"] == "portada"


def test_datos_invalidos_se_descartan():
    c = p.normalizar({"bloques": [
        {"tipo": "texto_imagen", "datos": {"titulo": "x" * 200, "imagen_url": "http://a.com/f.jpg", "lado": "arriba",
                                           "boton": {"accion": "link", "url": "javascript:alert(1)"}}},
        {"tipo": "banner", "estilo": {"fondo": "imagen"}, "datos": {"boton": {"accion": "whatsapp"}}},
        {"tipo": "servicios", "datos": {"items": [{"titulo": "Venta", "icono": "cohete"}, {"texto": "sin título"}] + [{"titulo": "x"}] * 9}},
        {"tipo": "galeria", "datos": {"imagenes": [{"url": "https://a.com/1.jpg"}, {"url": "ftp://x"}], "columnas": 7}},
    ]})
    ti, ba, se, ga = c["bloques"][1:]
    assert len(ti["datos"]["titulo"]) == 90 and ti["datos"]["imagen_url"] is None
    assert ti["datos"]["lado"] == "izq" and ti["datos"]["boton"] is None
    assert ba["estilo"]["fondo"] == "pagina" and ba["datos"]["boton"] == {"texto": "Escríbeme", "accion": "whatsapp"}
    assert len(se["datos"]["items"]) == 6 and se["datos"]["items"][0] == {"titulo": "Venta", "texto": None, "icono": "casa"}
    assert ga["datos"]["imagenes"] == [{"url": "https://a.com/1.jpg", "pie": None}] and ga["datos"]["columnas"] == 3


def test_video_solo_de_proveedores_conocidos():
    assert p.video_de("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3") == {"proveedor": "youtube", "vid": "dQw4w9WgXcQ"}
    assert p.video_de("https://youtu.be/dQw4w9WgXcQ") == {"proveedor": "youtube", "vid": "dQw4w9WgXcQ"}
    assert p.video_de("https://youtube.com/shorts/dQw4w9WgXcQ")["vid"] == "dQw4w9WgXcQ"
    assert p.video_de("https://vimeo.com/123456789") == {"proveedor": "vimeo", "vid": "123456789"}
    assert p.video_de("https://www.instagram.com/reel/C1a2B3c4D5/") == {"proveedor": "instagram", "vid": "C1a2B3c4D5"}
    assert p.video_de("https://malicioso.com/watch?v=dQw4w9WgXcQ") is None
    c = p.normalizar({"bloques": [{"tipo": "video", "datos": {"url": "https://youtu.be/dQw4w9WgXcQ"}},
                                  {"tipo": "video", "datos": {"video": {"proveedor": "youtube", "vid": "<script>"}}}]})
    assert c["bloques"][1]["datos"]["video"] == {"proveedor": "youtube", "vid": "dQw4w9WgXcQ"}
    assert c["bloques"][2]["datos"]["video"] is None


def test_fondo_de_imagen_con_url():
    c = p.normalizar({"bloques": [{"tipo": "proceso", "estilo": {"fondo": "imagen", "imagen_url": "https://a.com/f.jpg", "espacio": "amplio"}}]})
    assert c["bloques"][1]["estilo"] == {"fondo": "imagen", "imagen_url": "https://a.com/f.jpg", "espacio": "amplio"}
