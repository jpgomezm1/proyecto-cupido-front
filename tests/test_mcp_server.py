"""Tests del servidor MCP: registro de tools y gating de autenticación."""

import asyncio
import os

import pytest

from src.mcp_server import server as srv


EXPECTED_TOOLS = {
    "search_properties", "get_property",
    "get_zone_stats", "get_demand_stats", "get_supply_demand_balance",
    "find_comparables", "compare_properties", "estimate_price",
    "diagnose_property", "find_buyers_for_property", "list_my_properties",
    # Lote 1: cerrador / cazador / calificador
    "donde_captar", "capacidad_de_compra", "ficha_venta",
    "termometro_de_interes", "mis_listings_calientes",
    # Lote 2: costo total + match de comprador
    "costo_total_mensual", "match_comprador",
    # Lote 3: inteligencia de ubicación
    "que_hay_cerca",
    # Crear listing nativo + ordenar fotos
    "crear_listing", "revisar_fotos", "ordenar_fotos",
    # Piezas para el cliente final
    "generar_comparativa", "generar_ficha_cliente",
    # Preguntar sobre inmueble
    "preguntar_sobre_inmueble",
    "reporte_zona_captacion",
    # Documentos de cierre
    "generar_promesa_compraventa",
    # Coordinación por Fynder (red de seguridad sin contacto)
    "solicitar_visita",
    # Suscripción: desbloqueo de contactos y plan
    "ver_contacto", "ver_contacto_pedido", "mi_plan", "mis_desbloqueos",
    "reportar_contacto_invalido",
    # escrituras
    "propose_price_update_tool", "propose_description_update_tool",
    "propose_status_update_tool", "propose_fields_update_tool",
    "apply_change",
}


def test_all_tools_registered():
    tools = asyncio.run(srv.mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS.issubset(names), EXPECTED_TOOLS - names
    assert len(names) == len(EXPECTED_TOOLS)


def test_auth_gating_without_token(monkeypatch):
    # Sin token en el entorno, el wrapper central rechaza con no_autorizado
    # antes de ejecutar la tool (y sin tocar la BD).
    monkeypatch.delenv("FYNDER_MCP_TOKEN", raising=False)
    registros = []
    monkeypatch.setattr(srv.uso, "registrar", lambda *a, **k: registros.append(a))
    tool = srv.mcp._tool_manager.get_tool("get_zone_stats")
    out = asyncio.run(tool.run({}))
    assert out["error"] == "no_autorizado"
    assert registros[0][1] is None and registros[0][3] == "no_autorizado"


def _tool(nombre):
    return srv.mcp._tool_manager.get_tool(nombre)


def test_tools_are_async_and_keep_signature():
    # Corren en un hilo (no bloquean el event loop) y conservan su esquema.
    t = _tool("search_properties")
    assert t.is_async
    assert {"query", "limit", "offset"} <= set(t.parameters["properties"])


def test_annotations_distinguish_reads_from_writes():
    assert _tool("get_zone_stats").annotations.readOnlyHint is True
    assert _tool("propose_price_update_tool").annotations.readOnlyHint is True
    assert _tool("crear_listing").annotations.readOnlyHint is False
    visita = _tool("solicitar_visita").annotations
    assert visita.readOnlyHint is False and visita.openWorldHint is True
    assert _tool("apply_change").annotations.destructiveHint is True
    sin_titulo = [t.name for t in asyncio.run(srv.mcp.list_tools()) if not t.title]
    assert not sin_titulo, sin_titulo


def test_wrapper_binds_agent_sanitizes_and_logs(monkeypatch):
    from types import SimpleNamespace
    from src.mcp_server import identity_context as ic

    agente = SimpleNamespace(user_id=7, telefono="+573001112233", telefono_10="3001112233")
    monkeypatch.setattr(srv, "require_agent", lambda: agente)
    registros = []
    monkeypatch.setattr(srv.uso, "registrar", lambda *a, **k: registros.append(a))
    visto = {}

    def fake_zone_stats(*args):
        visto["agente"] = ic.current_agent()
        return {"zona": "Laureles", "telefono": "3001112233", "nota": "cel 3001112233"}

    monkeypatch.setattr(srv.ms, "get_zone_stats", fake_zone_stats)
    out = asyncio.run(_tool("get_zone_stats").run({"zona": "Laureles"}))

    assert visto["agente"] is agente            # identidad ligada a la llamada
    assert ic.current_agent() is not agente     # y liberada al terminar
    assert "telefono" not in out                # sanitize aplicado
    assert "3001112233" not in out["nota"]
    nombre, user_id, _ms, error, args = registros[0]
    assert (nombre, user_id, error) == ("get_zone_stats", 7, None)
    assert "zona" in list(args)


def test_solo_las_tools_autorizadas_revelan_contactos():
    from src.mcp_server.server import _TOOLS_QUE_REVELAN
    assert _TOOLS_QUE_REVELAN == {"ver_contacto", "ver_contacto_pedido", "mis_desbloqueos"}
    with pytest.raises(RuntimeError):
        @srv.mcp.tool(title="x", revela_contacto=True)
        def tool_intrusa() -> dict:
            return {}


def _agente_falso(monkeypatch):
    from types import SimpleNamespace
    agente = SimpleNamespace(user_id=7, telefono="+573001112233", telefono_10="3001112233")
    monkeypatch.setattr(srv, "require_agent", lambda: agente)
    monkeypatch.setattr(srv.uso, "registrar", lambda *a, **k: None)
    return agente


def test_contacto_revelado_sale_solo_por_ver_contacto(monkeypatch):
    from src.services.redact import ContactoRevelado
    _agente_falso(monkeypatch)
    monkeypatch.setattr(srv.suscripciones, "desbloquear", lambda *a, **k: {
        "ok": True, "contacto": {"telefono": "+573005556677", "nombre": "Ana", "agencia": None}})
    out = asyncio.run(_tool("ver_contacto").run({"codigo": "4521", "confirmar": True}))
    assert out["contacto_desbloqueado"]["telefono"] == "+573005556677"

    # Una tool normal que (por error) devuelve un ContactoRevelado no lo entrega.
    monkeypatch.setattr(srv.ms, "get_zone_stats",
                        lambda *a: {"fuga": ContactoRevelado("+573005556677", "Ana")})
    out = asyncio.run(_tool("get_zone_stats").run({}))
    assert out["fuga"] is None


def test_ver_contacto_sin_confirmar_no_cobra(monkeypatch):
    _agente_falso(monkeypatch)
    llamadas = []
    monkeypatch.setattr(srv.suscripciones, "preview_desbloqueo",
                        lambda *a: llamadas.append("preview") or {"ok": True, "costo": 1})
    monkeypatch.setattr(srv.suscripciones, "desbloquear",
                        lambda *a, **k: llamadas.append("desbloquear") or {"ok": True})
    asyncio.run(_tool("ver_contacto").run({"codigo": "4521"}))
    assert llamadas == ["preview"]


def test_uso_justo_en_busqueda(monkeypatch):
    _agente_falso(monkeypatch)
    monkeypatch.setattr(srv.suscripciones, "registrar_busqueda",
                        lambda uid: {"permitido": False, "usadas": 101, "limite": 100})
    llamada = []
    monkeypatch.setattr(srv.ps, "search", lambda **k: llamada.append(1) or {})
    out = asyncio.run(_tool("search_properties").run({"query": "apto en Laureles"}))
    assert out["error"] == "limite_diario"
    assert llamada == []
