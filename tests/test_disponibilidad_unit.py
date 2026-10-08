"""Detectores de disponibilidad por portal (sin red ni base)."""

import json

import pytest

from src.services import disponibilidad_service as d


class _Resp:
    def __init__(self, status, text="", url="https://x.test/p/1"):
        self.status_code, self.text, self.url = status, text, url


class _Session:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc = resp, exc

    def get(self, *a, **k):
        if self.exc:
            raise self.exc
        return self.resp


def _diag(url, status=200, text="", final=None, exc=None):
    return d.diagnosticar(_Session(_Resp(status, text, final or url), exc), url)


WASI = "https://info.wasi.co/apartamento-venta-poblado/9630539?shared=whatsapp"
LOBBIE = "https://app.lobbieapp.com/sp/1hDV/1dP/1/0"
PULPPO = "https://asesor.tu360inmobiliario-pulppo.com/property/69aa07e533ced612a12eb096"


def _next(prop):
    data = {"props": {"pageProps": {"property": prop}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def test_portal_de():
    assert d.portal_de(WASI) == "wasi"
    assert d.portal_de(LOBBIE) == "lobbie"
    assert d.portal_de(PULPPO) == "pulppo"
    assert d.portal_de("https://fyndercol.netlify.app/compartir/abc") == "propio"
    assert d.portal_de("https://sararealestate.com.co/x") == "generico"


def test_wasi():
    assert _diag(WASI, text='<div id="bodyContent"><div class="fotorama">').veredicto == "vivo"
    muerto = _diag(WASI, text="<title>Casa</title> No se encontró inmueble .")
    assert (muerto.veredicto, muerto.motivo) == ("muerto", "wasi: no se encontró inmueble")
    assert _diag(WASI, final="https://info.wasi.co/es").veredicto == "muerto"
    assert _diag(WASI, text="<html>algo raro</html>").veredicto == "incierto"


def test_lobbie():
    assert _diag(LOBBIE, text="<title>Lote en venta</title>").veredicto == "vivo"
    assert _diag(LOBBIE, status=404, text="<title>Lobbie</title>").veredicto == "muerto"
    assert _diag(LOBBIE, text="<title>Lobbie</title>").veredicto == "incierto"


def test_pulppo_lee_el_estado_real():
    vivo = _diag(PULPPO, text=_next({"status": {"last": "published"}}))
    assert vivo.veredicto == "vivo"
    muerto = _diag(PULPPO, text=_next({"status": {"last": "cancelled",
                                                  "reasonToFinish": "Otro asesor la concretó"}}))
    assert muerto.veredicto == "muerto" and "Otro asesor" in muerto.motivo
    assert _diag(PULPPO, text=_next({"status": {"last": "completed"}})).veredicto == "muerto"
    assert _diag(PULPPO, text=_next({"status": {"last": "edition"}})).veredicto == "incierto"
    assert _diag(PULPPO, text="<html>sin datos</html>").veredicto == "incierto"


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_errores_temporales_no_desactivan(status):
    assert _diag(WASI, status=status).veredicto == "incierto"


def test_red_y_casos_sin_portal():
    import requests
    assert _diag(WASI, exc=requests.exceptions.Timeout()).veredicto == "incierto"
    assert _diag(WASI, exc=requests.exceptions.ConnectionError()).veredicto == "incierto"
    assert d.diagnosticar(_Session(), None).motivo == "sin_url"
    assert d.diagnosticar(_Session(), "https://getfynder.com/ficha/x").veredicto == "incierto"


def test_estado_de_negocio_y_compatibilidad():
    assert d._estado(d.Veredicto("vivo", "ok", 200, "wasi")) == "disponible"
    assert d._estado(d.Veredicto("muerto", "http_404", 404, "lobbie")) == "404"
    assert d._estado(d.Veredicto("muerto", "pulppo: cancelled", 200, "pulppo")) == "no_disponible"
    assert d._estado(d.Veredicto("incierto", "timeout", None, "wasi")) == "desconocido"
    activa, motivo, _ = d.check_url(_Session(_Resp(200, "No se encontró inmueble", WASI)), WASI, "Wasi")
    assert activa is False and motivo.startswith("wasi")


def test_tamano_lote():
    assert d.tamano_lote(7000, 7, 30) == 21
    assert d.tamano_lote(0, 7, 30) == 1
