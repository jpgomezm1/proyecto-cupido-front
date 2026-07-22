"""Tests del servidor MCP: registro de tools y gating de autenticación."""

import asyncio
import os

import pytest

from src.mcp_server import server as srv
from src.mcp_server.identity_context import clear_identity_cache


EXPECTED_TOOLS = {
    "search_properties", "get_property", "get_property_images",
    "get_zone_stats", "get_demand_stats", "get_supply_demand_balance",
    "find_comparables", "compare_properties", "estimate_price",
    "diagnose_property", "find_buyers_for_property", "list_my_properties",
    # Lote 1: cerrador / cazador / calificador
    "donde_captar", "capacidad_de_compra", "ficha_venta",
    "termometro_de_interes", "mis_listings_calientes",
    # Lote 2: costo total + match de comprador
    "costo_total_mensual", "match_comprador",
    # escrituras
    "propose_price_update_tool", "propose_description_update_tool",
    "propose_status_update_tool", "register_buyer_match_tool", "apply_change",
}


def test_all_tools_registered():
    tools = asyncio.run(srv.mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS.issubset(names), EXPECTED_TOOLS - names
    assert len(names) == len(EXPECTED_TOOLS)


def test_auth_gating_without_token(monkeypatch):
    # Sin token en el entorno, las tools deben rechazar con no_autorizado.
    monkeypatch.delenv("FYNDER_MCP_TOKEN", raising=False)
    clear_identity_cache()
    err = srv._agent_or_error()
    assert err is not None
    assert err["error"] == "no_autorizado"
