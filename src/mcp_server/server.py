"""
Servidor MCP de Fynder — definición de la instancia FastMCP y sus herramientas.

Cada herramienta exige un agente autenticado (`require_agent`), de modo que solo
usuarios con acceso vigente a Fynder pueden usar el MCP (base para la
suscripción). Las lecturas de mercado son globales; "mis propiedades" y las
escrituras quedan scoped al teléfono del agente.

Los docstrings de cada tool son la interfaz que ve Claude: describen QUÉ hace y
CUÁNDO usarla.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import anyio
import httpx
from mcp.server.fastmcp import FastMCP, Image
from mcp.server.auth.settings import (
    AuthSettings, ClientRegistrationOptions, RevocationOptions,
)
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from src.mcp_server.identity_context import (
    require_agent, current_agent, bind_agent, unbind_agent, AuthError,
)
from src.mcp_server.oauth_provider import FynderOAuthProvider, public_base_url, DEFAULT_SCOPES
from src.services.redact import sanitize as _sanitize
from src.services.textutils import normalize_phone
from src.services import mcp_uso_service as uso
from src.services import property_service as ps
from src.services import market_service as ms
from src.services import diagnosis_service as ds
from src.services import write_service as ws
from src.services import engagement_service as es
from src.services import location_service as ls
from src.services import listing_service as lst
from src.services import share_service as sh
from src.services import qa_service as qa
from src.services import documento_service as doc
from src.services import interes_service as interes
from src.services import suscripcion_service as suscripciones
from src.services.redact import ContactoRevelado

_INSTRUCTIONS = (
    "Fynder es la plataforma inmobiliaria para agentes en Colombia. Usa estas "
    "herramientas para buscar propiedades, analizar precios y demanda de una "
    "zona, comparar inmuebles, y diagnosticar por qué una propiedad no se está "
    "vendiendo (no rota).\n\n"
    "TU INTERLOCUTOR ES UN AGENTE INMOBILIARIO, NO UN ESTADÍSTICO. Habla como un "
    "corredor experto, no como un reporte técnico:\n"
    "- Traduce SIEMPRE los números a lenguaje de negocio. En vez de 'percentil "
    "82' di 'está más caro que 8 de cada 10 de la zona'. En vez de 'ratio "
    "demanda/oferta 1.35' di 'hay más compradores que oferta, es momento de "
    "vendedor'. En vez de 'p25-p75' di 'donde se mueve la mayoría'.\n"
    "- Evita jerga: percentil, mediana, cuartil, ratio, desviación. Si usas un "
    "número, explica qué significa para vender o captar.\n"
    "- Sé directo y accionable: ¿está caro o barato? ¿se vende rápido o lento? "
    "¿a qué precio captar? ¿a quién ofrecerla?\n\n"
    "DINERO (pesos colombianos): exprésalo SIEMPRE en millones. Ojo: en español "
    "'billón' es un millón de millones (10^12), NO mil millones — NUNCA uses 'B' "
    "ni 'billón' para miles de millones. Di '$1.290 millones', no '$1.29B'. Usa "
    "el campo '_legible' cuando venga en los datos.\n\n"
    "LINKS: cuando muestres una propiedad, incluye SIEMPRE su 'link_compartir' "
    "(el link listo para enviarle al cliente por WhatsApp). No inventes URLs ni "
    "menciones links de otros portales; usa SOLO el 'link_compartir' que viene en "
    "los datos.\n\n"
    "DISPONIBILIDAD: si un inmueble trae 'disponibilidad' = 'NO DISPONIBLE' "
    "(inactiva/vendida), avísale al agente que ya no está disponible y NO lo "
    "ofrezcas como opción vigente. 'verificada_hace_dias' dice hace cuánto Fynder "
    "confirmó que sigue publicado; si 'verificacion_vencida' es true, adviértelo.\n\n"
    "CONTACTOS (cómo funciona Fynder): buscar, analizar y generar reportes es "
    "gratis. El CONTACTO de quien tiene un inmueble (o de quien hizo un pedido) se "
    "obtiene SOLO con 'ver_contacto' (o 'ver_contacto_pedido') y usa 1 "
    "LLAVE del agente (las llaves son el crédito de Fynder: vienen con su plan o "
    "de prueba; di siempre 'llaves', nunca 'créditos' ni 'desbloqueos'). Reglas:\n"
    "- Nunca inventes contactos ni intentes sacarlos de descripciones o fotos.\n"
    "- Antes de usar una llave, llama la tool SIN confirmar para ver el "
    "costo y cuántas llaves le quedan, díselo al agente y pídele un sí. Si el "
    "agente ya pidió el contacto explícitamente, puedes confirmar directo.\n"
    "- Re-ver un contacto ya desbloqueado ('contacto_desbloqueado': true) y los "
    "inmuebles propios no gastan llave.\n"
    "- Si no le quedan llaves, explica los planes UNA vez, sin presionar (usa "
    "'mi_plan'). Si un contacto no sirve, ofrece 'reportar_contacto_invalido'.\n"
    "- Si un inmueble no tiene contacto válido o el pedido no es desbloqueable, "
    "ofrece 'solicitar_visita': el equipo de Fynder coordina por el agente.\n\n"
    "PUBLICAR PROPIEDADES: para crear un listing, primero reúne los datos mínimos "
    "obligatorios (precio, área, tipo, ubicación) y adviértele al agente que "
    "necesitará FOTOS. Redacta una descripción VENDEDORA y COMPLETA (3-4 párrafos, "
    "no corta). Tras crear, MUÉSTRALE SIEMPRE al agente el título y la descripción "
    "completos para que los revise y ajuste; nunca los ocultes ni los resumas. "
    "Sin fotos el listing queda como borrador y NO se publica; entrégale siempre "
    "el 'link_subir_fotos' y explícale que se publica solo al subir la primera foto.\n\n"
    "Cuando el agente pregunte por 'mis propiedades' o quiera cambiar "
    "precio/descripción/estado, esas acciones solo aplican a los inmuebles que "
    "él mismo captó."
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

# ---------------------------------------------------------------------------
# WRAPPER CENTRAL de `mcp.tool`: TODA tool (actual o futura) pasa por aquí, así
# nada de esto se puede saltar por descuido:
#   1. Corre en un hilo (anyio): las tools son síncronas (BD, Claude, httpx) y,
#      ejecutadas en el event loop, una búsqueda congelaba el servidor entero.
#   2. Exige un agente autenticado y lo liga a la llamada (`current_agent()`).
#   3. Uso justo: las tools con `costo_ia=True` (gastan tokens nuestros) suman
#      al tope diario del usuario y se rechazan al pasarlo.
#   4. BLINDAJE DE CONTACTOS (obligatorio): la salida pasa por `sanitize()`. El
#      contacto de un agente es lo que se cobra: solo sale como
#      `ContactoRevelado` desde una tool registrada con `revela_contacto=True`,
#      y solo las de `_TOOLS_QUE_REVELAN` pueden registrarse así.
#   5. Registra el uso (tool, agente, duración, error) en `mcp_tool_calls`.
# ---------------------------------------------------------------------------
_orig_tool = mcp.tool

# Únicas tools que pueden entregar un contacto (desbloqueado y pagado).
_TOOLS_QUE_REVELAN = frozenset({"ver_contacto", "ver_contacto_pedido", "mis_desbloqueos"})


def _codigo_error(result: Any) -> Optional[str]:
    """Código de error de negocio de una respuesta de tool, si lo hay."""
    if isinstance(result, dict) and result.get("error"):
        return str(result["error"])
    return None


def _tool_saneada(*t_args, revela_contacto: bool = False, costo_ia: bool = False, **t_kwargs):
    deco = _orig_tool(*t_args, **t_kwargs)

    def wrapper(fn):
        nombre = t_kwargs.get("name") or fn.__name__
        if revela_contacto and nombre not in _TOOLS_QUE_REVELAN:
            raise RuntimeError(f"La tool {nombre} no está autorizada para revelar contactos")

        def ejecutar(kwargs: Dict[str, Any]) -> Any:
            inicio = time.monotonic()
            agent, error = None, None
            try:
                try:
                    agent = require_agent()
                except AuthError as e:
                    error = "no_autorizado"
                    return {"error": "no_autorizado", "mensaje": str(e)}
                if costo_ia:
                    uso_dia = suscripciones.registrar_busqueda(agent.user_id)
                    if not uso_dia["permitido"]:
                        error = "limite_diario"
                        return {"error": "limite_diario",
                                "mensaje": f"Llegaste al uso justo diario ({uso_dia['limite']} "
                                           "búsquedas). Se renueva mañana."}
                cv = bind_agent(agent)
                try:
                    result = fn(**kwargs)
                finally:
                    unbind_agent(cv)
                error = _codigo_error(result)
                return _sanitize(result, revelar=revela_contacto)
            except Exception as e:
                error = type(e).__name__
                raise
            finally:
                uso.registrar(nombre, agent.user_id if agent else None,
                              (time.monotonic() - inicio) * 1000, error, kwargs.keys())

        @wraps(fn)
        async def envuelta(**kwargs):
            return await anyio.to_thread.run_sync(ejecutar, kwargs)
        return deco(envuelta)
    return wrapper


mcp.tool = _tool_saneada

# Anotaciones MCP: le dicen al cliente (Claude) qué tools solo leen y cuáles
# escriben, envían mensajes o sobrescriben datos.
_LECTURA = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
_LECTURA_EXTERNA = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


def _escritura(*, destructiva: bool = False, idempotente: bool = False,
               externa: bool = False) -> ToolAnnotations:
    return ToolAnnotations(readOnlyHint=False, destructiveHint=destructiva,
                           idempotentHint=idempotente, openWorldHint=externa)


def _es_propia(prop: Dict[str, Any]) -> bool:
    """¿La propiedad la captó el agente autenticado (con teléfono verificado)?"""
    tel10 = current_agent().telefono_10
    return bool(tel10) and normalize_phone(prop.get("owner_phone")) == tel10


def _marcar_desbloqueos(props: List[Dict[str, Any]]) -> None:
    """Agrega `contacto_desbloqueado` y `es_propia` a cada propiedad (in place)."""
    ids = [p["id"] for p in props if p.get("id") is not None]
    vistos = suscripciones.ids_desbloqueados(current_agent().user_id, "propiedad", ids)
    for p in props:
        p["contacto_desbloqueado"] = p.get("id") in vistos
        if "owner_phone" in p:
            p["es_propia"] = _es_propia(p)


# =========================================================================
# BÚSQUEDA Y FICHA
# =========================================================================

@mcp.tool(title="Buscar propiedades", annotations=_LECTURA, costo_ia=True)
def search_properties(query: str, limit: int = 10, offset: int = 0) -> Dict[str, Any]:
    """
    Busca propiedades en el inventario de Fynder usando lenguaje natural.

    Úsala cuando el agente describe lo que busca en palabras, p. ej.
    "apartamento en El Poblado, 3 habitaciones, hasta 900 millones" o
    "casas en Envigado con parqueadero". Extrae criterios automáticamente y
    devuelve resultados rankeados.

    Args:
        query: La búsqueda en lenguaje natural del agente.
        limit: Máximo de resultados (por defecto 10).
        offset: Cuántos resultados saltar, para pedir la siguiente página con la
            MISMA query (ej. offset=10 trae los resultados 11-20).
    """
    agent = current_agent()
    res = ps.search(query=query, limit=limit, offset=offset,
                    telefono=agent.telefono, agente_id=agent.user_id)
    _marcar_desbloqueos(res.get("propiedades") or [])
    return res


@mcp.tool(title="Ficha de una propiedad", annotations=_LECTURA)
def get_property(id_or_slug: str) -> Dict[str, Any]:
    """
    Obtiene la ficha completa de una propiedad por su id numérico o su slug
    (código de propiedad). Incluye precio, área, precio/m², specs, amenidades,
    descripción, días en inventario y las URLs de sus fotos (`imagenes_urls`).
    Para VER las fotos de una propiedad propia, usa `revisar_fotos`.
    """
    prop = ps.get_property_public(id_or_slug)
    if not prop:
        return {"error": "no_encontrada", "mensaje": f"No existe la propiedad {id_or_slug}"}
    _marcar_desbloqueos([prop])
    return prop


# =========================================================================
# MERCADO: ZONA, DEMANDA Y BALANCE
# =========================================================================

@mcp.tool(title="Oferta de una zona", annotations=_LECTURA)
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
    return ms.get_zone_stats(ciudad, zona, tipo_propiedad, tipo_negocio)


@mcp.tool(title="Demanda de una zona", annotations=_LECTURA)
def get_demand_stats(ciudad: Optional[str] = None, zona: Optional[str] = None,
                     tipo_propiedad: Optional[str] = None, dias: int = 90) -> Dict[str, Any]:
    """
    Estadísticas de DEMANDA de una zona en los últimos `dias`: cuántos
    compradores están buscando (pedidos + búsquedas) y su presupuesto típico.

    Úsala para "¿hay demanda para apartaestudios en El Poblado?".
    """
    return ms.get_demand_stats(ciudad, zona, tipo_propiedad, dias)


@mcp.tool(title="Balance oferta vs demanda", annotations=_LECTURA)
def get_supply_demand_balance(ciudad: Optional[str] = None, zona: Optional[str] = None,
                              tipo_propiedad: Optional[str] = None,
                              tipo_negocio: str = "Venta", dias: int = 90) -> Dict[str, Any]:
    """
    Balance OFERTA vs DEMANDA de una zona: ratio y clasificación
    (caliente / equilibrado / frío). Un ratio alto significa más compradores
    que inventario (buen momento para captar/vender ahí).

    Úsala para "¿está caliente o fría la zona X?" o para decidir dónde captar.
    """
    return ms.get_supply_demand_balance(ciudad, zona, tipo_propiedad, tipo_negocio, dias)


# =========================================================================
# PREGUNTAR SOBRE UN INMUEBLE
# =========================================================================

@mcp.tool(title="Preguntar sobre un inmueble", annotations=_LECTURA)
def preguntar_sobre_inmueble(property_id: str, pregunta: str) -> Dict[str, Any]:
    """
    Responde preguntas sobre un inmueble ("¿tiene piscina?", "¿de qué año es?",
    "¿cuánto es la administración?", "¿la cocina se ve remodelada?", "¿tiene
    buena luz natural?"). Devuelve TODO lo que Fynder sabe de la propiedad:
    specs, amenidades, descripción y lo que la IA detectó en las FOTOS (estilo,
    estado, ambientes, calidad). Con eso respóndele al agente.

    Si el dato no está, dilo con honestidad (no inventes): sugiere confirmarlo
    con quien tiene el inmueble (su contacto se obtiene con `ver_contacto`).

    Úsala para cualquier duda puntual sobre una propiedad específica.
    """
    d = qa.dossier_public(property_id)
    if isinstance(d, dict):
        d["pregunta"] = pregunta
    return d


# =========================================================================
# COMPARATIVAS Y ESTIMACIÓN
# =========================================================================

@mcp.tool(title="Comparables de mercado", annotations=_LECTURA)
def find_comparables(property_id: str, limit: int = 20) -> Dict[str, Any]:
    """
    Encuentra los comparables de mercado de una propiedad (mismo tipo/zona,
    habitaciones ±1, área ±30%). Base para entender dónde está parada frente a
    inmuebles similares.
    """
    return ps.get_comparables_public(property_id, limit)


@mcp.tool(title="Comparar propiedades", annotations=_LECTURA)
def compare_properties(property_ids: List[str]) -> Dict[str, Any]:
    """
    Compara 2 o más propiedades específicas lado a lado (precio, precio/m²,
    área, habitaciones, amenidades, fotos, días en inventario) y da un veredicto
    de cuál es mejor valor, más económica y más amplia.

    Úsala cuando el agente quiere decidir entre varias opciones o mostrarle
    alternativas a un comprador.
    """
    return ps.compare_public(property_ids)


@mcp.tool(title="Estimar precio de captación", annotations=_LECTURA)
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
    return ps.estimate_price_public(
        ciudad=ciudad, zona=zona, tipo_propiedad=tipo_propiedad,
        area_construida=area_construida, habitaciones=habitaciones,
        tipo_negocio=tipo_negocio,
    )


# =========================================================================
# DIAGNÓSTICO Y DEMANDA MATCHEADA (la joya)
# =========================================================================

@mcp.tool(title="Diagnosticar por qué no rota", annotations=_LECTURA)
def diagnose_property(property_id: str) -> Dict[str, Any]:
    """
    Diagnostica por qué una propiedad NO ROTA (no se vende). Analiza su posición
    de precio/m² frente a comparables, cantidad/calidad de fotos, descripción,
    amenidades, tiempo en inventario y demanda real; devuelve hallazgos
    priorizados (alta/media/baja) con acciones concretas.

    Úsala cuando el agente pregunta "¿por qué no se me vende esta propiedad?" o
    "¿qué le pasa a mi inmueble?".
    """
    return ds.diagnose_public(property_id)


@mcp.tool(title="Compradores para una propiedad", annotations=_LECTURA)
def find_buyers_for_property(property_id: str, dias: int = 120,
                             limit: int = 15) -> Dict[str, Any]:
    """
    Encuentra la DEMANDA activa (pedidos recientes) que podría encajar con una
    propiedad: matchea por zona y presupuesto, y muestra qué buscan y su
    presupuesto. Sirve para saber si hay mercado para el inmueble.

    Cada pedido trae `desbloqueable`: si es true, el agente puede obtener el
    contacto de quien lo hizo con `ver_contacto_pedido` (usa 1 llave). Si
    es false, quien lo hizo aún no es usuario de Fynder: ofrece `solicitar_visita`.

    Úsala para "¿hay compradores buscando algo como esto?" tras un diagnóstico.
    """
    res = ds.find_buyers_public(property_id, dias, limit)
    compradores = res.get("compradores") if isinstance(res, dict) else None
    if compradores:
        vistos = suscripciones.ids_desbloqueados(
            current_agent().user_id, "pedido", [c["pedido_id"] for c in compradores])
        for c in compradores:
            c["contacto_desbloqueado"] = c["pedido_id"] in vistos
    return res


# =========================================================================
# CAZADOR: DÓNDE CAPTAR
# =========================================================================

@mcp.tool(title="Dónde captar", annotations=_LECTURA)
def donde_captar(ciudad: Optional[str] = None, tipo_propiedad: str = "apartamento",
                 dias: int = 90) -> Dict[str, Any]:
    """
    Mapa de oportunidad de CAPTACIÓN: por zona, cruza cuánta oferta activa hay
    contra cuántos compradores están buscando, y devuelve dónde hay más demanda
    que inventario (el hueco donde conviene captar).

    Úsala para "¿dónde debería captar?" o "¿en qué zona hay demanda sin oferta?".
    """
    return ms.donde_captar_public(ciudad, tipo_propiedad, dias)


# =========================================================================
# CALIFICADOR: CAPACIDAD DE COMPRA
# =========================================================================

@mcp.tool(title="Capacidad de compra", annotations=_LECTURA)
def capacidad_de_compra(ingreso_mensual: float, cuota_inicial: float = 0,
                        tasa_mensual: float = 0.011, plazo_anos: int = 20,
                        ciudad: Optional[str] = None, zona: Optional[str] = None,
                        tipo_propiedad: Optional[str] = None) -> Dict[str, Any]:
    """
    Estima para cuánto le alcanza a un comprador con crédito hipotecario
    (regla ~30% del ingreso para la cuota) y, si das zona/tipo, cuántas
    propiedades entran en ese techo.

    Úsala para pre-calificar: "gana $8 millones y tiene $150 millones de inicial,
    ¿para cuánto le da y qué hay en Envigado?".
    """
    return ps.capacidad_de_compra_public(
        ingreso_mensual=ingreso_mensual, cuota_inicial=cuota_inicial,
        tasa_mensual=tasa_mensual, plazo_anos=plazo_anos,
        ciudad=ciudad, zona=zona, tipo_propiedad=tipo_propiedad,
    )


# =========================================================================
# CERRADOR: FICHA / PITCH PARA WHATSAPP + INTERÉS REAL
# =========================================================================

@mcp.tool(title="Pitch de venta (texto para el agente)", annotations=_LECTURA)
def ficha_venta(property_id: str, perfil_comprador: Optional[str] = None) -> Dict[str, Any]:
    """
    Devuelve los puntos de venta de una propiedad (precio, si está barato/caro
    vs la zona, destacados, amenidades, gancho de precio/m²) para que redactes
    una ficha o pitch de WhatsApp listo para enviar. Si pasas el perfil del
    comprador, personaliza el mensaje a esa familia/persona.

    Úsala para "hazme el mensaje de WhatsApp para venderle esta al cliente X".
    """
    agent = current_agent()
    return ps.ficha_venta_public(property_id, perfil_comprador,
                                 agente_id=agent.user_id)


@mcp.tool(title="Costo total mensual", annotations=_LECTURA)
def costo_total_mensual(property_id: str, cuota_inicial: Optional[float] = None,
                        tasa_mensual: float = 0.011, plazo_anos: int = 20) -> Dict[str, Any]:
    """
    Calcula cuánto le sale AL MES vivir en una propiedad: administración +
    servicios (estimados por estrato) + predial mensualizado + (si pasas cuota
    inicial) la cuota del crédito. Un apto barato con administración alta no es
    barato: esta tool arma el número real.

    Úsala para "¿en cuánto le sale vivir ahí al mes?" o para comparar el costo
    mensual de dos propiedades.
    """
    return ps.costo_total_mensual_public(property_id, cuota_inicial, tasa_mensual, plazo_anos)


@mcp.tool(title="Compradores para un inmueble (link o descripción)", annotations=_LECTURA)
def compradores_para_inmueble(entrada: str, limit: int = 10) -> Dict[str, Any]:
    """
    Búsqueda inversa: el agente TIENE un inmueble y quiere saber qué pedidos de
    compradores encajan. `entrada` puede ser un link de Wasi o Lobbie, un link o
    código de Fynder, o una descripción ("apto de 85 m² en Laureles, 3 hab,
    520 millones"). Devuelve la ficha que se entendió y los pedidos ordenados por
    `score` (0-100) con `razones` (zona, presupuesto, habitaciones...).

    Cada pedido trae `desbloqueable`: si es true, el contacto de quien lo hizo
    se obtiene con `ver_contacto_pedido` (usa 1 llave). Si es false, ofrece
    `solicitar_visita`. Para un inmueble que ya está en Fynder también sirve
    `find_buyers_for_property`.
    """
    from src.services import compradores_service as cs
    return cs.buscar_compradores_public(entrada, current_agent().user_id, limit=min(max(limit, 1), 25))


@mcp.tool(title="Encaje con un comprador", annotations=_LECTURA)
def match_comprador(property_id: str, presupuesto_max: Optional[float] = None,
                    habitaciones_min: Optional[int] = None,
                    parqueaderos_min: Optional[int] = None,
                    estrato_min: Optional[int] = None,
                    area_min: Optional[float] = None,
                    amenidades: Optional[List[str]] = None,
                    zonas: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Puntúa qué tan bien le encaja una propiedad a un perfil de comprador (el que
    extraes de una conversación o transcripción), con un score 0-100, veredicto
    y razones por criterio. Marca deal-breakers (presupuesto o habitaciones que
    no cumplen).

    Úsala después de leer una transcripción: "¿qué tan bien le sirve el #X a
    esta familia?" pasando lo que necesitan (habitaciones, presupuesto,
    parqueaderos, amenidades como ['piscina','gimnasio'], zonas, etc.).
    """
    return ps.match_comprador_public(
        property_id, presupuesto_max=presupuesto_max, habitaciones_min=habitaciones_min,
        parqueaderos_min=parqueaderos_min, estrato_min=estrato_min, area_min=area_min,
        amenidades=amenidades, zonas=zonas,
    )


@mcp.tool(title="Termómetro de interés", annotations=_LECTURA)
def termometro_de_interes(property_id: str, dias: int = 30) -> Dict[str, Any]:
    """
    Muestra el interés REAL de una propiedad: cuántas veces la vieron, cuántos
    clics, y cuántos la contactaron por WhatsApp/teléfono en los últimos `dias`.
    Distingue "no la ven" (falta difusión) de "la ven pero no llaman" (precio o
    presentación).

    Úsala para "¿mi propiedad X está generando interés?" o "¿por qué no llaman?".
    """
    return es.termometro_public(property_id, dias)


@mcp.tool(title="Mis propiedades más calientes", annotations=_LECTURA)
def mis_listings_calientes(dias: int = 30) -> Dict[str, Any]:
    """
    Rankea TUS propiedades por interés real (vistas + contactos) en los últimos
    `dias`: cuáles están jalando y cuáles están muertas sin una sola vista.

    Úsala para "¿cuáles de mis propiedades están calientes?".
    """
    agent = current_agent()
    if not agent.has_inventory_scope:
        return {"total": 0, "listings": [],
                "mensaje": "Tu teléfono todavía no está verificado en Fynder. Escríbenos para verificarlo y así ver y gestionar tus propios inmuebles."}
    return es.mis_calientes_public(agent.telefono_10, dias)


# =========================================================================
# UBICACIÓN: QUÉ HAY CERCA
# =========================================================================

@mcp.tool(title="Qué hay cerca", annotations=_LECTURA_EXTERNA)
def que_hay_cerca(property_id: str) -> Dict[str, Any]:
    """
    Dice qué hay ALREDEDOR de una propiedad: colegios, universidades, estaciones
    de Metro, supermercados, centros comerciales, clínicas, parques y bancos,
    con la distancia real a cada uno. Responde la pregunta #1 del comprador.

    Úsala para "¿qué hay cerca del #X?", "¿tiene colegios cerca?", "¿queda cerca
    del Metro?". (Requiere que la propiedad tenga ubicación cargada.)
    """
    return ls.que_hay_cerca_public(property_id)


# =========================================================================
# CREAR LISTING (publicar propiedad nativa en Fynder)
# =========================================================================

@mcp.tool(title="Publicar propiedad", annotations=_escritura())
def crear_listing(precio: int, area_construida: float, tipo_propiedad: str,
                  ciudad: Optional[str] = None, zona: Optional[str] = None,
                  habitaciones: Optional[int] = None, banos: Optional[int] = None,
                  parqueaderos: Optional[int] = None, estrato: Optional[int] = None,
                  titulo: Optional[str] = None, descripcion: Optional[str] = None,
                  amenidades_internas: Optional[str] = None,
                  amenidades_externas: Optional[str] = None,
                  direccion_completa: Optional[str] = None,
                  administracion: Optional[int] = None,
                  piso: Optional[int] = None, ano_construccion: Optional[int] = None,
                  tipo_negocio: str = "Venta",
                  imagenes_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Publica una propiedad NUEVA en Fynder (listing nativo del agente autenticado).

    ANTES DE LLAMAR ESTA TOOL, reúne con el agente los REQUISITOS MÍNIMOS. Si
    falta algo, PREGÚNTALE — no inventes ni publiques a medias:
    - OBLIGATORIOS (el agente los da; tú no puedes saberlos): precio en pesos
      (ej. 600000000), area_construida en m², tipo_propiedad, y ubicación
      (ciudad y/o zona).
    - MUY RECOMENDADOS: habitaciones, baños, parqueaderos, estrato. Pídeselos.
    - FOTOS: son OBLIGATORIAS para publicar. Como no se suben por el chat,
      adviértele desde el principio que va a necesitar fotos y que se las pedirás
      con un link al final.

    TÚ redactas el `titulo` y la `descripcion` (sin llamar a otra IA):
    - `titulo`: atractivo, corto, con el gancho principal (máx ~70 caracteres).
    - `descripcion`: VENDEDORA y COMPLETA, de 3 a 4 párrafos (apunta a 700-1200
      caracteres, NO la dejes corta). Cubre: (1) apertura con lo mejor del
      inmueble y su ubicación; (2) distribución y espacios (habitaciones, cocina,
      balcón, iluminación, acabados); (3) amenidades del edificio y del entorno
      (colegios, transporte, comercio si aplica); (4) cierre que invite a la
      visita. Español colombiano, cálido y profesional. No inventes datos que el
      agente no dio.
    - `amenidades`: separadas por '|' (ej. "Piscina|Gimnasio|Zona infantil").

    SIEMPRE, después de crear, MUÉSTRALE al agente el TÍTULO y la DESCRIPCIÓN
    completos que generaste (no un resumen) y pregúntale si quiere ajustarlos.
    Si pide cambios (más largo, otro tono, resaltar algo), reescríbela y aplícala
    con propose_description_update_tool + apply_change.

    CÓMO FUNCIONA LA PUBLICACIÓN: si creas el listing SIN fotos, queda como
    BORRADOR (no aparece en búsquedas). En la respuesta viene `link_subir_fotos`:
    DÁSELO SIEMPRE al agente y explícale que la propiedad se PUBLICA SOLA en
    cuanto suba al menos una foto por ese link. Revisa `estado_publicacion` y
    `requiere_fotos` en la respuesta y comunícaselo.

    Úsala cuando el agente diga "publica/crea/sube una propiedad/listing".
    """
    agent = current_agent()
    if not agent.has_inventory_scope:
        return {"error": "sin_telefono",
                "mensaje": "Tu teléfono todavía no está verificado en Fynder. Escríbenos para verificarlo y así ver y gestionar tus propios inmuebles."}
    try:
        data = {
            "precio": precio, "area_construida": area_construida, "tipo_propiedad": tipo_propiedad,
            "ciudad": ciudad, "zona": zona, "habitaciones": habitaciones, "banos": banos,
            "parqueaderos": parqueaderos, "estrato": estrato, "titulo": titulo,
            "descripcion": descripcion, "amenidades_internas": amenidades_internas,
            "amenidades_externas": amenidades_externas, "direccion_completa": direccion_completa,
            "administracion": administracion, "piso": piso, "ano_construccion": ano_construccion,
            "tipo_negocio": tipo_negocio, "imagenes_urls": imagenes_urls,
        }
        return lst.crear_listing(agent.telefono, data,
                                 agente_nombre=agent.nombre, agente_user_id=agent.user_id)
    except lst.ListingError as e:
        return {"error": "datos_incompletos", "mensaje": str(e)}


# =========================================================================
# PIEZAS PARA EL CLIENTE FINAL: comparativa y brochure
# =========================================================================

@mcp.tool(title="Comparativa para el cliente (link)", annotations=_LECTURA)
def generar_comparativa(property_ids: List[str]) -> Dict[str, Any]:
    """
    Genera una COMPARATIVA visual de 2 o más inmuebles para enviarle al CLIENTE
    final por WhatsApp: una página web bonita (con branding Fynder) que muestra
    las propiedades lado a lado con fotos, precios, specs y un veredicto de mejor
    valor. Devuelve un `link` listo para compartir.

    Úsala cuando el agente diga "arma/mándame una comparativa de X, Y, Z para mi
    cliente". Requiere al menos 2 propiedades.
    """
    ids = []
    for x in property_ids:
        p = ps.get_property_public(x)
        if p:
            ids.append(p["id"])
    if len(ids) < 2:
        return {"error": "faltan_propiedades",
                "mensaje": "Necesito al menos 2 propiedades válidas para comparar."}
    return {
        "ok": True,
        "total": len(ids),
        "link": sh.link_comparativa(ids, agente_id=getattr(current_agent(), "user_id", None)),
        "mensaje": "Comparativa lista. Envíale este link al cliente por WhatsApp; se ve bonita en el celular.",
    }


@mcp.tool(title="Reporte de zona para un dueño (link)", annotations=_LECTURA)
def reporte_zona_captacion(ciudad: Optional[str] = None, zona: Optional[str] = None,
                           tipo_propiedad: str = "apartamento") -> Dict[str, Any]:
    """
    Genera un REPORTE de mercado de una zona para que el agente se lo mande a un
    DUEÑO que quiere captar: una página bonita (branding Fynder) con cuántos
    inmuebles hay en venta, precio típico, precio/m², qué tan rápido se vende y
    cuántos compradores están buscando — con un mensaje de captación. Devuelve un
    `link` para compartir.

    Úsala cuando el agente diga "arma un reporte de [zona] para mandarle a un
    dueño / para captar".
    """
    if not ciudad and not zona:
        return {"error": "falta_zona", "mensaje": "Dime la ciudad o el barrio de la zona."}
    return {
        "ok": True,
        "link": sh.link_reporte_zona(ciudad, zona, tipo_propiedad,
                                     agente_id=getattr(current_agent(), "user_id", None)),
        "mensaje": "Reporte de zona listo. Mándaselo al dueño por WhatsApp para captar su propiedad.",
    }


@mcp.tool(title="Ficha visual para el cliente (link)", annotations=_LECTURA)
def generar_ficha_cliente(property_id: str) -> Dict[str, Any]:
    """
    Genera una FICHA/BROCHURE visual de UN inmueble para enviarle al CLIENTE
    final: una página web elegante (branding Fynder) con foto grande, precio,
    specs, descripción, amenidades y galería. Devuelve un `link` para compartir.

    Úsala cuando el agente quiera "mandarle la ficha/el brochure de esta
    propiedad a un cliente". (Distinta de `ficha_venta`, que arma el pitch de
    texto para el agente; esta es la página visual para el cliente.)
    """
    p = ps.get_property_public(property_id)
    if not p:
        return {"error": "no_encontrada"}
    return {
        "ok": True,
        "link": sh.link_brochure(p["id"], agente_id=getattr(current_agent(), "user_id", None)),
        "mensaje": "Ficha lista. Envíale este link al cliente por WhatsApp.",
    }


# =========================================================================
# DOCUMENTOS DE CIERRE: promesa de compraventa (BORRADOR)
# =========================================================================

@mcp.tool(title="Borrador de promesa de compraventa", annotations=_escritura())
def generar_promesa_compraventa(
    property_id: str,
    comprador_nombre: Optional[str] = None, comprador_cedula: Optional[str] = None,
    comprador_domicilio: Optional[str] = None,
    vendedor_nombre: Optional[str] = None, vendedor_cedula: Optional[str] = None,
    vendedor_domicilio: Optional[str] = None,
    precio_total: Optional[int] = None, arras: Optional[int] = None,
    cuota_inicial: Optional[int] = None, forma_pago: Optional[str] = None,
    plazo_escrituracion_dias: Optional[int] = None, notaria: Optional[str] = None,
    matricula_inmobiliaria: Optional[str] = None, fecha_entrega: Optional[str] = None,
    ciudad_firma: Optional[str] = None, clausula_penal: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Genera un BORRADOR de PROMESA DE COMPRAVENTA (Colombia) para un negocio.
    Devuelve un `link` a un documento imprimible/descargable en PDF.

    IMPORTANTE — es un BORRADOR de apoyo, NO asesoría legal ni documento
    definitivo; debe revisarlo un abogado/notaría. Adviértele esto al agente.

    ANTES de llamar, reúne con el agente los datos (pregúntalos si faltan; los que
    no tengas se dejan en blanco para llenar a mano): matrícula inmobiliaria,
    nombre y cédula del COMPRADOR y del VENDEDOR, precio total, forma de pago,
    arras/cuota inicial, notaría, plazo de escrituración y fecha de entrega. El
    inmueble (dirección, área) se toma de Fynder.

    La respuesta trae `campos_faltantes` si algo quedó sin completar: díselos al
    agente para que los consiga.
    """
    agent = current_agent()
    prop = ps.get_property_public(property_id)
    if not prop:
        return {"error": "no_encontrada"}
    res = doc.crear_promesa(
        prop["id"], agent.telefono,
        comprador={"nombre": comprador_nombre, "cedula": comprador_cedula, "domicilio": comprador_domicilio},
        vendedor={"nombre": vendedor_nombre, "cedula": vendedor_cedula, "domicilio": vendedor_domicilio},
        terminos={"precio_total": precio_total, "arras": arras, "cuota_inicial": cuota_inicial,
                  "forma_pago": forma_pago, "plazo_escrituracion_dias": plazo_escrituracion_dias,
                  "notaria": notaria, "matricula_inmobiliaria": matricula_inmobiliaria,
                  "fecha_entrega": fecha_entrega, "ciudad_firma": ciudad_firma,
                  "clausula_penal": clausula_penal},
        agente_nombre=agent.nombre,
    )
    if res.get("error"):
        return res
    # Avisar qué falta (leyendo el documento generado).
    from src.services.documento_service import get_documento
    docdata = get_documento(res["share_id"])
    faltantes = (docdata.get("documento") or {}).get("campos_faltantes", [])
    res["campos_faltantes"] = faltantes
    return res


# =========================================================================
# ORDENAR FOTOS DE UN LISTING (apalancando la visión del LLM)
# =========================================================================

@mcp.tool(title="Ver fotos de mi propiedad", annotations=_LECTURA_EXTERNA)
def revisar_fotos(property_id: str):
    """
    Devuelve las FOTOS de una propiedad propia como imágenes numeradas para que
    TÚ las veas y decidas el mejor orden de presentación (portada primero, luego
    sala, cocina, habitaciones, baños, y por último exteriores/amenidades).

    Úsala ANTES de `ordenar_fotos`: mira las imágenes, decide el orden ideal y
    luego llama `ordenar_fotos` con las posiciones en el orden que elegiste.
    Solo funciona sobre propiedades que el agente captó.
    """
    prop = ps.get_property_public(property_id)
    if not prop:
        return {"error": "no_encontrada"}
    if not _es_propia(prop):
        return {"error": "no_es_tuya", "mensaje": "Solo puedes ordenar fotos de propiedades que tú captaste."}

    data = lst.listar_fotos(prop["id"])
    if data.get("total", 0) == 0:
        return {"mensaje": "La propiedad no tiene fotos todavía."}

    salida = [
        f"Fotos de la propiedad #{prop['id']} — {data.get('titulo') or ''}. "
        f"Son {data['total']}, numeradas 1 a {data['total']}. Míralas, decide el "
        f"mejor orden de presentación y luego llama ordenar_fotos con las posiciones "
        f"en ese orden (la primera será la portada)."
    ]
    # Descarga en paralelo: en serie, 20 fotos podían tardar decenas de segundos.
    with ThreadPoolExecutor(max_workers=6) as pool:
        imagenes = list(pool.map(_descargar_foto, [f["url"] for f in data["fotos"]]))
    for foto, img in zip(data["fotos"], imagenes):
        salida.append(f"— Foto {foto['posicion']}:")
        salida.append(img or f"(no se pudo cargar la foto {foto['posicion']})")
    return salida


def _descargar_foto(url: str) -> Optional[Image]:
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True)
        if r.status_code != 200:
            return None
        fmt = "png" if "png" in r.headers.get("content-type", "").lower() else "jpeg"
        return Image(data=r.content, format=fmt)
    except Exception:
        return None


@mcp.tool(title="Reordenar fotos de mi propiedad", annotations=_escritura(idempotente=True))
def ordenar_fotos(property_id: str, orden: List[int]) -> Dict[str, Any]:
    """
    Reordena las fotos de una propiedad PROPIA. `orden` es la lista de POSICIONES
    actuales (1-indexed) en el orden que quieres. Ej: si hay 4 fotos y pasas
    [3,1,4,2], la foto #3 queda de PORTADA. Debe incluir cada posición una vez.

    Primero usa `revisar_fotos` para ver las imágenes y decidir el orden ideal
    (portada atractiva, luego áreas sociales, habitaciones, y exteriores).
    """
    prop = ps.get_property_public(property_id)
    if not prop:
        return {"error": "no_encontrada"}
    if not _es_propia(prop):
        return {"error": "no_es_tuya", "mensaje": "Solo puedes ordenar fotos de propiedades que tú captaste."}
    try:
        return lst.reordenar_fotos(prop["id"], orden)
    except lst.ListingError as e:
        return {"error": "orden_invalido", "mensaje": str(e)}


# =========================================================================
# INVENTARIO PROPIO
# =========================================================================

@mcp.tool(title="Mis propiedades", annotations=_LECTURA)
def list_my_properties(limit: int = 50) -> Dict[str, Any]:
    """
    Lista las propiedades que captó el agente autenticado (su inventario
    propio), con su estado de actividad y días en inventario. Punto de partida
    para diagnosticar o actualizar sus inmuebles.
    """
    agent = current_agent()
    if not agent.has_inventory_scope:
        return {"total": 0, "propiedades": [],
                "mensaje": "Tu teléfono todavía no está verificado en Fynder. Escríbenos para verificarlo y así ver y gestionar tus propios inmuebles."}
    return ps.list_my_properties_public(agent.telefono_10, limit)


@mcp.tool(title="Pedir a Fynder que coordine (sin contacto)", annotations=_escritura(idempotente=True, externa=True))
def solicitar_visita(codigo: str, cliente_ref: str = None, preguntas: str = None) -> Dict[str, Any]:
    """
    Le pide al equipo de Fynder que coordine una visita POR el agente: Fynder
    registra el interés, verifica que el inmueble siga disponible y contacta a
    ambas partes. Es la red de seguridad cuando el agente no puede hablar directo:

    - `ver_contacto` respondió `sin_contacto` (el inmueble no tiene un contacto
      válido cargado), o
    - el pedido no es desbloqueable (quien lo hizo aún no es usuario de Fynder), o
    - el agente prefiere explícitamente que Fynder coordine.

    Si el agente solo quiere el contacto, usa `ver_contacto`, no esta tool.

    - `codigo`: código del inmueble (obligatorio).
    - `cliente_ref`: referencia libre del cliente comprador (opcional; ej. "familia López").
    - `preguntas`: dudas para el dueño que el equipo de Fynder debe resolver (opcional).

    Al terminar, dile al agente que el equipo de Fynder le confirmará la visita.
    """
    agent = current_agent()
    if not agent.telefono:
        return {"error": "sin_telefono",
                "mensaje": "Tu usuario no tiene un teléfono asociado para identificarte como comprador."}
    return interes.orquestar_solicitud(
        propiedad_ref=codigo,
        comprador_telefono=agent.telefono,
        cliente_ref=cliente_ref,
        preguntas=preguntas,
        fuente="MCP",
    )


# =========================================================================
# CONTACTOS: desbloqueos con llaves (lo que se cobra) y plan
# =========================================================================

def _respuesta_desbloqueo(res: Dict[str, Any]) -> Dict[str, Any]:
    """Envuelve el contacto en `ContactoRevelado`: solo así sobrevive al saneo."""
    if res.get("ok") and res.get("contacto"):
        c = res.pop("contacto")
        res["contacto_desbloqueado"] = ContactoRevelado(
            telefono=c.get("telefono"), nombre=c.get("nombre"), agencia=c.get("agencia"))
    return res


@mcp.tool(title="Ver contacto de quien tiene el inmueble",
          annotations=_escritura(idempotente=True, externa=True), revela_contacto=True)
def ver_contacto(codigo: str, confirmar: bool = False) -> Dict[str, Any]:
    """
    Devuelve el CONTACTO (nombre, celular, inmobiliaria y link de WhatsApp) de
    quien tiene un inmueble. Usa 1 llave del agente (el crédito de Fynder).

    Dos pasos:
    1. Llámala con `confirmar=false` (por defecto): NO gasta nada; responde el
       costo en llaves (`costo`: 0 o 1) y las llaves que le quedan
       (`disponibles`). Díselo al agente.
    2. Con su sí, llámala con `confirmar=true`: Fynder verifica EN VIVO que el
       inmueble siga publicado (puede tardar unos segundos) y entrega el contacto.

    No se cobra si el inmueble ya no está disponible, si no tiene un contacto
    válido (`sin_contacto` → ofrece `solicitar_visita`), si ya estaba
    desbloqueado o si es del propio agente. Si responde `sin_creditos` (no le
    quedan llaves), explica los planes una vez (vienen en la respuesta) sin
    presionar. Si responde `terminos_pendientes`, el agente debe aceptar los
    términos en Fynder.
    """
    agent = current_agent()
    if not confirmar:
        return suscripciones.preview_desbloqueo(agent.user_id, "propiedad", codigo)
    return _respuesta_desbloqueo(
        suscripciones.desbloquear(agent.user_id, "propiedad", codigo, canal="mcp"))


@mcp.tool(title="Ver contacto de quien hizo un pedido",
          annotations=_escritura(idempotente=True, externa=True), revela_contacto=True)
def ver_contacto_pedido(pedido_id: int, confirmar: bool = False) -> Dict[str, Any]:
    """
    Devuelve el CONTACTO de quien hizo un pedido (un comprador buscando algo),
    para los pedidos que `find_buyers_for_property` marca `desbloqueable=true`.
    Usa 1 llave. Mismo flujo de dos pasos que `ver_contacto`: primero sin
    confirmar (costo y llaves disponibles), luego con `confirmar=true`.

    Si el pedido no es desbloqueable (quien lo hizo aún no es usuario de Fynder),
    no se cobra: ofrece `solicitar_visita`.
    """
    agent = current_agent()
    if not confirmar:
        return suscripciones.preview_desbloqueo(agent.user_id, "pedido", pedido_id)
    return _respuesta_desbloqueo(
        suscripciones.desbloquear(agent.user_id, "pedido", pedido_id, canal="mcp"))


@mcp.tool(title="Mi plan y mis llaves", annotations=_LECTURA)
def mi_plan() -> Dict[str, Any]:
    """
    Plan del agente: cuántas llaves le quedan (las del plan del mes y las de
    prueba o paquetes extra), cuándo vence, los planes disponibles con su
    precio y cómo activarlos o renovarlos (consignación + activación de Fynder).

    Úsala para "¿cuántas llaves me quedan?", "¿qué plan tengo?" o "¿cómo
    compro más llaves?".
    """
    return suscripciones.estado(current_agent().user_id)


@mcp.tool(title="Mis contactos desbloqueados", annotations=_LECTURA, revela_contacto=True)
def mis_desbloqueos(limit: int = 20, offset: int = 0) -> Dict[str, Any]:
    """
    Lista los contactos que el agente ya desbloqueó (inmuebles y pedidos), con
    el contacto incluido. Volver a verlos no gasta llave. Cada uno trae
    `desbloqueo_id`, que sirve para `reportar_contacto_invalido`.
    """
    res = suscripciones.listar_desbloqueos(current_agent().user_id, limit, offset)
    for item in res.get("items", []):
        c = item.pop("contacto")
        item["contacto"] = ContactoRevelado(
            telefono=c.get("telefono"), nombre=c.get("nombre"), agencia=c.get("agencia")) \
            if c.get("telefono") else None
    return res


@mcp.tool(title="Reportar contacto que no sirve", annotations=_escritura())
def reportar_contacto_invalido(desbloqueo_id: int, motivo: str,
                               detalle: Optional[str] = None) -> Dict[str, Any]:
    """
    Reporta un contacto desbloqueado que no sirvió, para que Fynder lo corrija y
    le devuelva la llave (hay un máximo de devoluciones automáticas al mes; por
    encima, el equipo de Fynder revisa el reporte).

    - `desbloqueo_id`: viene en `mis_desbloqueos` o en la respuesta de `ver_contacto`.
    - `motivo`: uno de 'numero_equivocado', 'no_contesta', 'no_es_el_agente',
      'ya_no_disponible', 'otro'.
    - `detalle`: texto libre opcional.
    """
    return suscripciones.reportar_invalido(current_agent().user_id, desbloqueo_id, motivo, detalle)


# Las herramientas de ESCRITURA (propose/apply) se registran en write_tools.
ws.register_write_tools(mcp)
