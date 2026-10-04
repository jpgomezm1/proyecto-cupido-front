"""Tests de comparativa/brochure (tokens + render, sin red)."""
import pytest
from src.services import share_service as sh
from src.mcp_server import share_pages as sp


def test_token_roundtrip():
    tok = sh.make_token("cmp", [84, 89, 105])
    p = sh.verify_token(tok)
    assert p["k"] == "cmp" and p["ids"] == [84, 89, 105]


def test_token_tampered():
    tok = sh.make_token("fic", [84])
    with pytest.raises(sh.ShareError):
        sh.verify_token(tok[:-3] + "xxx")


def test_legacy_pages_redirect_to_frontend():
    """/comparar?t= y /ficha?t= (links viejos) redirigen 301 a la app de React."""
    from starlette.applications import Starlette
    from starlette.testclient import TestClient
    from src.mcp_server import brand

    c = TestClient(Starlette(routes=sp.share_pages_routes()))
    tok = sh.make_token("cmp", [1, 2])
    r = c.get(f"/comparar?t={tok}", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == f"{brand.frontend_url()}/comparar/{tok}"
    r = c.get("/ficha?t=abc.def", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == f"{brand.frontend_url()}/ficha/abc.def"
    r = c.get("/ficha", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == f"{brand.frontend_url()}/"


def test_links():
    # Links elegantes en el dominio de Fynder (no el del MCP).
    assert "fyndercol.netlify.app/comparar/" in sh.link_comparativa([1, 2])
    assert "fyndercol.netlify.app/ficha/" in sh.link_brochure(1)


# --------------------------------------------------------------------------
# Atribución al agente que comparte (clave "a" en el token).
# --------------------------------------------------------------------------

def test_token_with_agente_roundtrip():
    tok = sh.make_token("cmp", [1, 2], agente_id=42)
    p = sh.verify_token(tok)
    assert p["k"] == "cmp" and p["ids"] == [1, 2] and p["a"] == 42


def test_token_without_agente_has_no_a():
    p = sh.verify_token(sh.make_token("fic", [7]))
    assert "a" not in p
    p = sh.verify_token(sh.make_token("fic", [7], agente_id=None))
    assert "a" not in p


def test_token_zona_with_agente():
    p = sh.verify_token(sh.make_token_zona("Medellín", "Laureles", "apartamento", agente_id=9))
    assert p["k"] == "zona" and p["zona"] == "Laureles" and p["a"] == 9
    p = sh.verify_token(sh.make_token_zona("Medellín", "Laureles", "apartamento"))
    assert "a" not in p


def test_old_token_still_verifies():
    """Un token emitido antes de existir "a" (payload sin esa clave) sigue siendo válido."""
    old = sh._sign({"k": "cmp", "ids": [3, 4]})
    p = sh.verify_token(old)
    assert p["ids"] == [3, 4] and p.get("a") is None


def test_links_include_agente():
    for link in (sh.link_comparativa([1, 2], agente_id=5),
                 sh.link_brochure(1, agente_id=5),
                 sh.link_reporte_zona("Bogotá", "Chicó", "apartamento", agente_id=5)):
        token = link.rsplit("/", 1)[1]
        assert sh.verify_token(token)["a"] == 5


def test_prop_limpia_link_detalle_lleva_agente(monkeypatch):
    monkeypatch.setattr(sh, "get_property", lambda cur, pid: {"id": pid, "titulo": "Apto bonito"})
    p = sh._prop_limpia(None, 10, agente_id=77)
    assert p["link_detalle"].endswith("?a=77")
    p = sh._prop_limpia(None, 10)
    assert "?a=" not in p["link_detalle"]


class _FakeDB:
    cursor = None


class _FakeCtx:
    def __enter__(self):
        return _FakeDB()

    def __exit__(self, *a):
        return False


def test_agente_publico_none_si_no_verificado(monkeypatch):
    from src.services import agente_service as ag
    monkeypatch.setattr(ag, "get_db", lambda: _FakeCtx())
    # La consulta exige activo AND telefono_verificado: si no hay fila → None.
    monkeypatch.setattr(ag, "fetch_one", lambda cur, sql, params=None: None)
    assert ag.agente_publico(1) is None
    # Sin teléfono también → None.
    monkeypatch.setattr(ag, "fetch_one", lambda cur, sql, params=None: {"id": 1, "nombre": "Ana", "telefono": None})
    assert ag.agente_publico(1) is None
    # Ids inválidos → None sin tocar la BD.
    assert ag.agente_publico(None) is None
    assert ag.agente_publico("abc") is None


def test_agente_publico_verificado(monkeypatch):
    from src.services import agente_service as ag
    captured = {}

    def fake_fetch(cur, sql, params=None):
        captured["sql"] = sql
        return {"id": 3, "nombre": "Ana Gómez", "telefono": "+573001112233"}

    monkeypatch.setattr(ag, "get_db", lambda: _FakeCtx())
    monkeypatch.setattr(ag, "fetch_one", fake_fetch)
    out = ag.agente_publico("3")
    assert out == {"id": 3, "name": "Ana Gómez", "phone": "+573001112233", "whatsapp": "573001112233"}
    assert "telefono_verificado" in captured["sql"] and "activo" in captured["sql"]
