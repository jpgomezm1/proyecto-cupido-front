"""
Regresión de fugas de contacto en la API Flask (solo lectura sobre la BD real).

El contacto de quien tiene un inmueble es lo que Fynder cobra: sin token de
admin, ninguna respuesta puede traerlo. Requiere Flask (venv del backend).
"""

import os
import re

import pytest

pytest.importorskip("flask")

os.environ.setdefault("VALIDACION_ENABLED", "false")

CELULAR = re.compile(r"(?<!\d)3\d{9}(?!\d)")
CLAVES_CONTACTO = {"owner_phone", "owner_name", "source_url", "asesor", "inmobiliaria",
                   "agente_telefono", "agente_nombre", "contacto_responsable"}


@pytest.fixture(scope="module")
def client():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("Sin DATABASE_URL")
    from src.main import app
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture(scope="module")
def admin_headers():
    from src.api.auth import AUTHORIZED_USERS, generate_token
    if not AUTHORIZED_USERS or not os.getenv("JWT_SECRET"):
        pytest.skip("Sin usuarios admin configurados")
    email, data = next(iter(AUTHORIZED_USERS.items()))
    return {"Authorization": f"Bearer {generate_token(email, data)}"}


def _textos(obj):
    """Todos los strings de la respuesta (los precios numéricos no cuentan)."""
    if isinstance(obj, dict):
        return " ".join(_textos(v) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(_textos(x) for x in obj)
    return obj if isinstance(obj, str) else ""


def _claves(obj, acc=None):
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(k)
            _claves(v, acc)
    elif isinstance(obj, list):
        for x in obj:
            _claves(x, acc)
    return acc


def test_lista_publica_sin_contactos(client):
    r = client.get("/api/properties?limit=20")
    assert r.status_code == 200
    body = r.get_json()
    assert body["data"], "se esperaban propiedades"
    assert not (_claves(body) & CLAVES_CONTACTO)
    assert not CELULAR.search(_textos(body))


def test_detalle_publico_sin_contactos(client):
    slug = client.get("/api/properties?limit=1").get_json()["data"][0]["shareable_slug"]
    body = client.get(f"/api/properties/{slug}").get_json()
    assert body["success"]
    assert not (_claves(body) & CLAVES_CONTACTO)
    assert not CELULAR.search(_textos(body))


def test_admin_si_ve_el_contacto(client, admin_headers):
    body = client.get("/api/properties?limit=50", headers=admin_headers).get_json()
    assert "owner_phone" in body["data"][0]


def test_filtrar_por_telefono_ajeno_no_revela_inventario(client, admin_headers):
    # Un teléfono con inventario real (visto como admin)...
    props = client.get("/api/properties?limit=50", headers=admin_headers).get_json()["data"]
    tel = next(p["owner_phone"] for p in props if p.get("owner_phone"))
    # ...no sirve para listar sus inmuebles sin ser admin.
    r = client.get(f"/api/properties?owner_phone={tel}&limit=5")
    assert r.get_json()["total_count"] == 0


@pytest.mark.parametrize("metodo,ruta", [
    ("get", "/api/pedidos"),
    ("get", "/api/pedidos/export"),
    ("get", "/api/agents/precargadas"),
    ("get", "/api/agents"),
    ("get", "/api/dashboard/overview"),
    ("get", "/api/deals"),
    ("get", "/api/whatsapp-groups"),
    ("post", "/api/search/ai"),
    ("put", "/api/properties/1/captador"),
    ("post", "/api/properties/1/verificar"),
    ("post", "/api/scrape-wasi"),
])
def test_rutas_admin_exigen_token(client, metodo, ruta):
    r = getattr(client, metodo)(ruta, json={})
    assert r.status_code == 401, (ruta, r.status_code)


def test_rutas_publicas_siguen_abiertas(client):
    assert client.get("/api/analytics/market/prices").status_code == 200
    r = client.post("/api/share-analytics/events", json={})
    assert r.status_code != 401
