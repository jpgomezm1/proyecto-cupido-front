"""Firmas de Wompi (sin BD ni red): checksum de eventos e integridad del checkout."""
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest

from src.services import pagos_service as svc

# Ejemplo de la documentación de Wompi (eventos). El checksum es el SHA256 de la
# concatenación que la doc muestra: id + status + amount_in_cents + timestamp + secreto
# (el valor de checksum impreso en la doc es ilustrativo y no corresponde a ese texto).
SECRETO_DOC = "prod_events_OcHnIzeBl5socpwByQ4hA52Em3USQ93Z"
CONCATENADO_DOC = "1234-1610641025-49201APPROVED44900001530291411" + SECRETO_DOC
EVENTO = {
    "event": "transaction.updated",
    "data": {"transaction": {"id": "1234-1610641025-49201", "status": "APPROVED",
                             "amount_in_cents": 4490000, "reference": "MZQ3X2DE2SMX", "currency": "COP"}},
    "environment": "prod",
    "signature": {
        "properties": ["transaction.id", "transaction.status", "transaction.amount_in_cents"],
        "checksum": hashlib.sha256(CONCATENADO_DOC.encode()).hexdigest().upper(),
    },
    "timestamp": 1530291411,
}


@pytest.fixture
def llaves(monkeypatch):
    monkeypatch.setenv("WOMPI_PUBLIC_KEY", "pub_prod_x")
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "prv_prod_x")
    monkeypatch.setenv("WOMPI_EVENTS_SECRET", SECRETO_DOC)
    monkeypatch.setenv("WOMPI_INTEGRITY_SECRET", "prod_integrity_x")


def test_checksum_del_ejemplo_oficial(llaves):
    assert svc.checksum_valido(EVENTO)
    assert svc.checksum_valido(EVENTO, EVENTO["signature"]["checksum"].lower())


@pytest.mark.parametrize("cambio", [
    lambda e: e["data"]["transaction"].update(status="DECLINED"),
    lambda e: e["data"]["transaction"].update(amount_in_cents=100),
    lambda e: e.update(timestamp=1530291412),
    lambda e: e["signature"].update(checksum="00" * 32),
    lambda e: e["signature"].update(properties=[]),
])
def test_checksum_rechaza_alteraciones(llaves, cambio):
    import copy
    e = copy.deepcopy(EVENTO)
    cambio(e)
    assert not svc.checksum_valido(e)


def test_evento_con_firma_invalida_no_toca_la_bd(llaves, monkeypatch):
    monkeypatch.setattr(svc, "_aplicar", lambda *a, **k: pytest.fail("no debe aplicarse"))
    malo = {**EVENTO, "signature": {**EVENTO["signature"], "checksum": "00" * 32}}
    assert svc.procesar_evento(malo) == {"ok": False, "error": "firma_invalida"}


def test_sin_secreto_nunca_valida(monkeypatch):
    monkeypatch.delenv("WOMPI_EVENTS_SECRET", raising=False)
    assert not svc.checksum_valido(EVENTO)
    assert not svc.habilitado()


def test_firma_integridad(llaves):
    esperado = hashlib.sha256(b"FY1-BAS-ABC5000000COPprod_integrity_x").hexdigest()
    assert svc.firma_integridad("FY1-BAS-ABC", 5000000) == esperado


def test_checkout_url_lleva_firma_y_redireccion(llaves, monkeypatch):
    class Cur:
        def execute(self, *a): pass

    class Db:
        cursor = Cur()
        class conn:
            @staticmethod
            def commit(): pass

    class Ctx:
        def __enter__(self): return Db()
        def __exit__(self, *a): return False

    respuestas = iter([
        {"codigo": "basico", "nombre": "Visita", "precio_cop": 50000},
        {"id": 7, "nombre": "Ana", "email": "ana@x.co", "telefono": None, "activo": True},
    ])
    monkeypatch.setattr(svc, "get_db", lambda: Ctx())
    monkeypatch.setattr(svc, "fetch_one", lambda *a, **k: next(respuestas))
    r = svc.crear_pago(7, "basico", "http://localhost:4242")
    q = {k: v[0] for k, v in parse_qs(urlparse(r["checkout_url"]).query).items()}
    assert q["amount-in-cents"] == "5000000" and q["currency"] == "COP"
    assert q["reference"] == r["referencia"] and r["referencia"].startswith("FY7-BAS-")
    assert q["signature:integrity"] == svc.firma_integridad(r["referencia"], 5000000)
    assert "redirect-url" not in q and r["sin_redireccion"] is True   # Wompi bloquea localhost
    assert q["customer-data:email"] == "ana@x.co"
    assert "prv_prod_x" not in r["checkout_url"] and "prod_integrity_x" not in r["checkout_url"]


@pytest.mark.parametrize("llaves_env,esperado", [
    (("pub_test_a", "prv_test_b", "test_events_c", "test_integrity_d"), "sandbox"),
    (("pub_prod_a", "prv_prod_b", "prod_events_c", "prod_integrity_d"), "production"),
    (("pub_prod_a", "prv_test_b", "prod_events_c", "prod_integrity_d"), None),   # mezcladas
    (("pub_test_a", "prv_test_b", "test_events_c", ""), None),                   # falta una
])
def test_ambiente_sale_de_las_llaves(monkeypatch, llaves_env, esperado):
    for nombre, valor in zip(svc._LLAVES, llaves_env):
        monkeypatch.setenv(nombre, valor)
    assert svc.ambiente() == esperado
    assert svc.habilitado() is (esperado is not None)
    if esperado:
        assert svc._api() == svc._API[esperado]


def test_redireccion_en_produccion(llaves, monkeypatch):
    class Ctx:
        def __enter__(self):
            class Db:
                class cursor:
                    @staticmethod
                    def execute(*a): pass
                class conn:
                    @staticmethod
                    def commit(): pass
            return Db()
        def __exit__(self, *a): return False
    respuestas = iter([{"codigo": "pro", "nombre": "Pro", "precio_cop": 100000},
                       {"id": 3, "nombre": None, "email": None, "telefono": None, "activo": True}])
    monkeypatch.setattr(svc, "get_db", lambda: Ctx())
    monkeypatch.setattr(svc, "fetch_one", lambda *a, **k: next(respuestas))
    r = svc.crear_pago(3, "pro", "https://getfynder.com")
    q = {k: v[0] for k, v in parse_qs(urlparse(r["checkout_url"]).query).items()}
    assert q["redirect-url"] == f"https://getfynder.com/chat/pago?ref={r['referencia']}"
    assert r["sin_redireccion"] is False and "customer-data:email" not in q
