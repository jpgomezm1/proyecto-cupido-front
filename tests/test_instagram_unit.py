"""Instagram de Fynder: lógica pura de la sincronización con Buffer (sin red ni base)."""
from src.services import instagram_service as ig


def _p(id_, estado, texto="Hola", tipo="post", due="2026-10-20T18:30:00Z", sent=None):
    return {"id": id_, "estado": estado, "texto": texto, "tipo": tipo, "dueAt": due, "sentAt": sent,
            "miniaturas": [], "imagenes": [], "metricas": None, "link": None, "error": None}


def test_normalizar_metricas_reactions_y_porcentaje():
    m = ig.normalizar_metricas([
        {"type": "reach", "value": 520}, {"type": "reactions", "value": 30}, {"type": "likes", "value": 99},
        {"type": "engagementRate", "value": 0.034, "unit": None}, {"type": "raro", "value": 3},
        {"type": "saves", "value": None},
    ])
    assert m == {"reach": 520, "likes": 30, "engagementRate": 3.4000000000000004}
    assert ig.normalizar_metricas([{"type": "engagementRate", "value": 3.4, "unit": "percentage"}]) == {"engagementRate": 3.4}
    assert ig.normalizar_metricas(None) is None


def test_error_reintentado_no_se_cuenta():
    fallo = _p("a", "error", texto="Mito #02", due="2026-10-20T18:30:00Z")
    salio = _p("b", "sent", texto="Mito #02", due="2026-10-20T18:31:00Z", sent="2026-10-20T18:31:00Z")
    otro = _p("c", "error", texto="Otro texto")
    ids = [p["id"] for p in ig.sin_errores_reintentados([fallo, salio, otro])]
    assert ids == ["b", "c"]


def test_por_avisar_una_vez_por_estado_y_siembra():
    posts = [_p("a", "sent"), _p("b", "error"), _p("c", "scheduled"), _p("d", "sent")]
    assert ig.por_avisar(posts, {}, primera_vez=True) == []
    lista = ig.por_avisar(posts, {"a": "sent", "b": None, "d": "error"}, primera_vez=False)
    assert [(a["post"]["id"], a["motivo"]) for a in lista] == [("b", "fallo"), ("d", "publicado")]


def test_tipo_legible_y_primeras_lineas():
    assert ig.tipo_legible("story", 1) == "Historia"
    assert ig.tipo_legible("post", 6) == "Carrusel · 6"
    assert ig.primeras_lineas("El termómetro\n\nLaureles sube", 2) == "El termómetro · Laureles sube"


def test_correo_publicado_lleva_link_y_marca():
    p = _p("a", "sent", texto="El termómetro: Laureles", sent="2026-10-20T23:30:00Z")
    p["link"] = "https://instagram.com/p/x"
    c = ig._correo({"post": p, "motivo": "publicado"}, None)
    assert c["asunto"].startswith("✅ Publicado en Instagram")
    assert "https://instagram.com/p/x" in c["html"] and "/admin/instagram" in c["texto"]
