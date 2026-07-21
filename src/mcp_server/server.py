"""
Servidor MCP de Fynder — definición de la instancia FastMCP y sus herramientas.

Cada herramienta exige un agente autenticado (`require_agent`), de modo que solo
usuarios con acceso vigente a Fynder pueden usar el MCP (base para la
suscripción). Las lecturas de mercado son globales; "mis propiedades" y las
escrituras quedan scoped al teléfono del agente.

Los docstrings de cada tool son la interfaz que ve Claude: describen QUÉ hace y
CUÁNDO usarla.
"""

from typing import Any, Dict, List, Optional

from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.settings import (
    AuthSettings, ClientRegistrationOptions, RevocationOptions,
)
from mcp.server.transport_security import TransportSecuritySettings

from src.mcp_server.identity_context import require_agent, current_agent, AuthError
from src.mcp_server.oauth_provider import FynderOAuthProvider, public_base_url, DEFAULT_SCOPES
from src.services import property_service as ps
from src.services import market_service as ms
from src.services import diagnosis_service as ds
from src.services import write_service as ws

_INSTRUCTIONS = (
    "Fynder es la plataforma inmobiliaria para agentes en Colombia. Usa "
    "estas herramientas para buscar propiedades, analizar precios y demanda "
    "de una zona, comparar inmuebles, y diagnosticar por qué una propiedad "
    "no se está vendiendo (no rota). Responde siempre en español, con cifras "
    "concretas y recomendaciones accionables. Los montos están en pesos "
    "colombianos (COP). Cuando el agente pregunte por 'mis propiedades' o "
    "quiera cambiar precio/descripción/estado, esas acciones solo aplican a "
    "los inmuebles que él mismo captó."
)

_base = public_base_url()

# Protección anti-DNS-rebinding: por defecto FastMCP solo permite localhost, lo
# que rechaza el host real de Heroku (421 Invalid Host header). Autorizamos el
# host público (derivado de MCP_PUBLIC_URL) + localhost para dev.
_netloc = urlparse(_base).netloc or "localhost:8767"
_bare = _netloc.split(":")[0]
_allowed_hosts = list({
    _netloc, _bare, f"{_bare}:*",
    "localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "[::1]:*",
})

mcp = FastMCP(
    name="Fynder",
    instructions=_INSTRUCTIONS,
    # Streamable HTTP sin estado en memoria: cada request es independiente, así
    # funciona con múltiples workers/dynos (Heroku corre 2 workers por defecto).
    # Sin esto, la sesión creada en un worker no la encuentra otro -> 404
    # "Session terminated" al pedir la lista de tools.
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts,
        allowed_origins=["https://claude.ai", "https://claude.com", _base],
    ),
    # OAuth 2.1: el MCP es su propio Authorization Server, autenticando contra
    # los chat_users de Fynder. El SDK expone metadata/authorize/token/register.
    auth_server_provider=FynderOAuthProvider(),
    auth=AuthSettings(
        issuer_url=_base,
        resource_server_url=f"{_base}/mcp",
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=DEFAULT_SCOPES, default_scopes=DEFAULT_SCOPES,
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=None,
    ),
)


def _agent_or_error() -> Optional[Dict[str, Any]]:
    """Helper: valida auth y devuelve un dict de error si falla (o None si ok)."""
    try:
        require_agent()
        return None
    except AuthError as e:
        return {"error": "no_autorizado", "mensaje": str(e)}


# =========================================================================
# BÚSQUEDA Y FICHA
# =========================================================================

@mcp.tool()
def search_properties(query: str, limit: int = 10) -> Dict[str, Any]:
    """
    Busca propiedades en el inventario de Fynder usando lenguaje natural.

    Úsala cuando el agente describe lo que busca en palabras, p. ej.
    "apartamento en El Poblado, 3 habitaciones, hasta 900 millones" o
    "casas en Envigado con parqueadero". Extrae criterios automáticamente y
    devuelve resultados rankeados.

    Args:
        query: La búsqueda en lenguaje natural del agente.
        limit: Máximo de resultados (por defecto 10).
    """
    err = _agent_or_error()
    if err:
        return err
    agent = current_agent()
    return ps.search(query=query, limit=limit, telefono=agent.telefono if agent else None)


@mcp.tool()
def get_property(id_or_slug: str) -> Dict[str, Any]:
    """
    Obtiene la ficha completa de una propiedad por su id numérico o su slug
    (código de propiedad). Incluye precio, área, precio/m², specs, amenidades,
    número de fotos, descripción y días en inventario.
    """
    err = _agent_or_error()
    if err:
        return err
    prop = ps.get_property_public(id_or_slug)
    return prop or {"error": "no_encontrada", "mensaje": f"No existe la propiedad {id_or_slug}"}


@mcp.tool()
def get_property_images(id_or_slug: str, limit: int = 8) -> Dict[str, Any]:
    """
    Devuelve las URLs de las imágenes de una propiedad (hasta `limit`), para que
    el agente o Claude las revisen. Útil para evaluar calidad y cantidad de
    fotos, un factor clave de rotación.
    """
    err = _agent_or_error()
    if err:
        return err
    prop = ps.get_property_public(id_or_slug)
    if not prop:
        return {"error": "no_encontrada", "mensaje": f"No existe la propiedad {id_or_slug}"}
    imgs = prop.get("imagenes_urls", [])[:limit]
    return {
        "propiedad_id": prop["id"],
        "total_imagenes": prop.get("total_imagenes"),
        "imagenes_hd": prop.get("imagenes_hd"),
        "imagen_principal": prop.get("imagen_principal"),
        "imagenes": imgs,
    }


# =========================================================================
# MERCADO: ZONA, DEMANDA Y BALANCE
# =========================================================================

@mcp.tool()
def get_zone_stats(ciudad: Optional[str] = None, zona: Optional[str] = None,
                   tipo_propiedad: Optional[str] = None,
                   tipo_negocio: str = "Venta") -> Dict[str, Any]:
    """
    Estadísticas de OFERTA de una zona: inventario activo, distribución de
    precios (percentiles), precio/m² mediano, área y habitaciones promedio,
    fotos promedio y antigüedad del inventario.

    Úsala para responder "¿cómo está el mercado en El Poblado?" o "¿cuál es el
    precio/m² típico de apartamentos en Laureles?".
    """
    err = _agent_or_error()
    if err:
        return err
    return ms.get_zone_stats(ciudad, zona, tipo_propiedad, tipo_negocio)


@mcp.tool()
def get_demand_stats(ciudad: Optional[str] = None, zona: Optional[str] = None,
                     tipo_propiedad: Optional[str] = None, dias: int = 90) -> Dict[str, Any]:
    """
    Estadísticas de DEMANDA de una zona en los últimos `dias`: cuántos
    compradores están buscando (pedidos + búsquedas) y su presupuesto típico.

    Úsala para "¿hay demanda para apartaestudios en El Poblado?".
    """
    err = _agent_or_error()
    if err:
        return err
    return ms.get_demand_stats(ciudad, zona, tipo_propiedad, dias)


@mcp.tool()
def get_supply_demand_balance(ciudad: Optional[str] = None, zona: Optional[str] = None,
                              tipo_propiedad: Optional[str] = None,
                              tipo_negocio: str = "Venta", dias: int = 90) -> Dict[str, Any]:
    """
    Balance OFERTA vs DEMANDA de una zona: ratio y clasificación
    (caliente / equilibrado / frío). Un ratio alto significa más compradores
    que inventario (buen momento para captar/vender ahí).

    Úsala para "¿está caliente o fría la zona X?" o para decidir dónde captar.
    """
    err = _agent_or_error()
    if err:
        return err
    return ms.get_supply_demand_balance(ciudad, zona, tipo_propiedad, tipo_negocio, dias)


# =========================================================================
# COMPARATIVAS Y ESTIMACIÓN
# =========================================================================

@mcp.tool()
def find_comparables(property_id: str, limit: int = 20) -> Dict[str, Any]:
    """
    Encuentra los comparables de mercado de una propiedad (mismo tipo/zona,
    habitaciones ±1, área ±30%). Base para entender dónde está parada frente a
    inmuebles similares.
    """
    err = _agent_or_error()
    if err:
        return err
    return ps.get_comparables_public(property_id, limit)


@mcp.tool()
def compare_properties(property_ids: List[str]) -> Dict[str, Any]:
    """
    Compara 2 o más propiedades específicas lado a lado (precio, precio/m²,
    área, habitaciones, amenidades, fotos, días en inventario) y da un veredicto
    de cuál es mejor valor, más económica y más amplia.

    Úsala cuando el agente quiere decidir entre varias opciones o mostrarle
    alternativas a un comprador.
    """
    err = _agent_or_error()
    if err:
        return err
    return ps.compare_public(property_ids)


@mcp.tool()
def estimate_price(ciudad: Optional[str] = None, zona: Optional[str] = None,
                   tipo_propiedad: Optional[str] = None,
                   area_construida: Optional[float] = None,
                   habitaciones: Optional[int] = None,
                   tipo_negocio: str = "Venta") -> Dict[str, Any]:
    """
    Estima un precio de captación sugerido para un inmueble, con base en el
    precio/m² mediano de comparables de la zona y el área objetivo. Devuelve
    también un rango (percentiles 25-75).

    Úsala para "¿a cuánto debería captar un apto de 80m² en Sabaneta?".
    """
    err = _agent_or_error()
    if err:
        return err
    return ps.estimate_price_public(
        ciudad=ciudad, zona=zona, tipo_propiedad=tipo_propiedad,
        area_construida=area_construida, habitaciones=habitaciones,
        tipo_negocio=tipo_negocio,
    )


# =========================================================================
# DIAGNÓSTICO Y DEMANDA MATCHEADA (la joya)
# =========================================================================

@mcp.tool()
def diagnose_property(property_id: str) -> Dict[str, Any]:
    """
    Diagnostica por qué una propiedad NO ROTA (no se vende). Analiza su posición
    de precio/m² frente a comparables, cantidad/calidad de fotos, descripción,
    amenidades, tiempo en inventario y demanda real; devuelve hallazgos
    priorizados (alta/media/baja) con acciones concretas.

    Úsala cuando el agente pregunta "¿por qué no se me vende esta propiedad?" o
    "¿qué le pasa a mi inmueble?".
    """
    err = _agent_or_error()
    if err:
        return err
    return ds.diagnose_public(property_id)


@mcp.tool()
def find_buyers_for_property(property_id: str, dias: int = 120,
                             limit: int = 15) -> Dict[str, Any]:
    """
    Encuentra compradores activos (pedidos recientes) que podrían encajar con
    una propiedad: matchea por zona y presupuesto. Devuelve el contacto del
    agente que hizo cada pedido para poder cerrar el match.

    Úsala para "¿quién está buscando algo como esto?" tras un diagnóstico.
    """
    err = _agent_or_error()
    if err:
        return err
    return ds.find_buyers_public(property_id, dias, limit)


# =========================================================================
# INVENTARIO PROPIO
# =========================================================================

@mcp.tool()
def list_my_properties(limit: int = 50) -> Dict[str, Any]:
    """
    Lista las propiedades que captó el agente autenticado (su inventario
    propio), con su estado de actividad y días en inventario. Punto de partida
    para diagnosticar o actualizar sus inmuebles.
    """
    err = _agent_or_error()
    if err:
        return err
    agent = current_agent()
    if not agent.has_inventory_scope:
        return {"total": 0, "propiedades": [],
                "mensaje": "Tu usuario no tiene un teléfono asociado para identificar inventario propio."}
    return ps.list_my_properties_public(agent.telefono_10, limit)


# Las herramientas de ESCRITURA (propose/apply) se registran en write_tools.
ws.register_write_tools(mcp)
