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

from mcp.server.fastmcp import FastMCP, Image
from mcp.server.auth.settings import (
    AuthSettings, ClientRegistrationOptions, RevocationOptions,
)
from mcp.server.transport_security import TransportSecuritySettings

from functools import wraps

from src.mcp_server.identity_context import require_agent, current_agent, AuthError
from src.mcp_server.oauth_provider import FynderOAuthProvider, public_base_url, DEFAULT_SCOPES
from src.services.redact import sanitize as _sanitize
from src.services import property_service as ps
from src.services import market_service as ms
from src.services import diagnosis_service as ds
from src.services import write_service as ws
from src.services import engagement_service as es
from src.services import location_service as ls
from src.services import listing_service as lst

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
    "(el link listo para enviarle al cliente por WhatsApp). No inventes URLs; usa "
    "solo el 'link_compartir' que viene en los datos.\n\n"
    "PUBLICAR PROPIEDADES: para crear un listing, primero reúne los datos mínimos "
    "obligatorios (precio, área, tipo, ubicación) y adviértele al agente que "
    "necesitará FOTOS. Sin fotos el listing queda como borrador y NO se publica; "
    "entrégale siempre el 'link_subir_fotos' y explícale que se publica solo al "
    "subir la primera foto.\n\n"
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
# BLINDAJE DE PRIVACIDAD (obligatorio): ninguna tool puede entregar datos de
# contacto de agentes. Se envuelve `mcp.tool` para que la salida de TODA tool
# (actual o futura) pase por `sanitize()`. Imposible de saltar por descuido.
# ---------------------------------------------------------------------------
_orig_tool = mcp.tool


def _tool_saneada(*t_args, **t_kwargs):
    deco = _orig_tool(*t_args, **t_kwargs)

    def wrapper(fn):
        @wraps(fn)
        def envuelta(*args, **kwargs):
            return _sanitize(fn(*args, **kwargs))
        return deco(envuelta)
    return wrapper


mcp.tool = _tool_saneada


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
    return ps.search(query=query, limit=limit,
                     telefono=agent.telefono if agent else None,
                     agente_id=agent.user_id if agent else None)


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
    Encuentra la DEMANDA activa (pedidos recientes) que podría encajar con una
    propiedad: matchea por zona y presupuesto, y muestra qué buscan y su
    presupuesto. Sirve para saber si hay mercado para el inmueble.

    PRIVACIDAD: Fynder NUNCA comparte el contacto (teléfono/nombre) de otros
    agentes. El match con el comprador se gestiona dentro de Fynder, no
    entregando datos de contacto. No prometas ni pidas esos datos.

    Úsala para "¿hay compradores buscando algo como esto?" tras un diagnóstico.
    """
    err = _agent_or_error()
    if err:
        return err
    return ds.find_buyers_public(property_id, dias, limit)


# =========================================================================
# CAZADOR: DÓNDE CAPTAR
# =========================================================================

@mcp.tool()
def donde_captar(ciudad: Optional[str] = None, tipo_propiedad: str = "apartamento",
                 dias: int = 90) -> Dict[str, Any]:
    """
    Mapa de oportunidad de CAPTACIÓN: por zona, cruza cuánta oferta activa hay
    contra cuántos compradores están buscando, y devuelve dónde hay más demanda
    que inventario (el hueco donde conviene captar).

    Úsala para "¿dónde debería captar?" o "¿en qué zona hay demanda sin oferta?".
    """
    err = _agent_or_error()
    if err:
        return err
    return ms.donde_captar_public(ciudad, tipo_propiedad, dias)


# =========================================================================
# CALIFICADOR: CAPACIDAD DE COMPRA
# =========================================================================

@mcp.tool()
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
    err = _agent_or_error()
    if err:
        return err
    return ps.capacidad_de_compra_public(
        ingreso_mensual=ingreso_mensual, cuota_inicial=cuota_inicial,
        tasa_mensual=tasa_mensual, plazo_anos=plazo_anos,
        ciudad=ciudad, zona=zona, tipo_propiedad=tipo_propiedad,
    )


# =========================================================================
# CERRADOR: FICHA / PITCH PARA WHATSAPP + INTERÉS REAL
# =========================================================================

@mcp.tool()
def ficha_venta(property_id: str, perfil_comprador: Optional[str] = None) -> Dict[str, Any]:
    """
    Devuelve los puntos de venta de una propiedad (precio, si está barato/caro
    vs la zona, destacados, amenidades, gancho de precio/m²) para que redactes
    una ficha o pitch de WhatsApp listo para enviar. Si pasas el perfil del
    comprador, personaliza el mensaje a esa familia/persona.

    Úsala para "hazme el mensaje de WhatsApp para venderle esta al cliente X".
    """
    err = _agent_or_error()
    if err:
        return err
    agent = current_agent()
    return ps.ficha_venta_public(property_id, perfil_comprador,
                                 agente_id=agent.user_id if agent else None)


@mcp.tool()
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
    err = _agent_or_error()
    if err:
        return err
    return ps.costo_total_mensual_public(property_id, cuota_inicial, tasa_mensual, plazo_anos)


@mcp.tool()
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
    err = _agent_or_error()
    if err:
        return err
    return ps.match_comprador_public(
        property_id, presupuesto_max=presupuesto_max, habitaciones_min=habitaciones_min,
        parqueaderos_min=parqueaderos_min, estrato_min=estrato_min, area_min=area_min,
        amenidades=amenidades, zonas=zonas,
    )


@mcp.tool()
def termometro_de_interes(property_id: str, dias: int = 30) -> Dict[str, Any]:
    """
    Muestra el interés REAL de una propiedad: cuántas veces la vieron, cuántos
    clics, y cuántos la contactaron por WhatsApp/teléfono en los últimos `dias`.
    Distingue "no la ven" (falta difusión) de "la ven pero no llaman" (precio o
    presentación).

    Úsala para "¿mi propiedad X está generando interés?" o "¿por qué no llaman?".
    """
    err = _agent_or_error()
    if err:
        return err
    return es.termometro_public(property_id, dias)


@mcp.tool()
def mis_listings_calientes(dias: int = 30) -> Dict[str, Any]:
    """
    Rankea TUS propiedades por interés real (vistas + contactos) en los últimos
    `dias`: cuáles están jalando y cuáles están muertas sin una sola vista.

    Úsala para "¿cuáles de mis propiedades están calientes?".
    """
    err = _agent_or_error()
    if err:
        return err
    agent = current_agent()
    if not agent.has_inventory_scope:
        return {"total": 0, "listings": [],
                "mensaje": "Tu usuario no tiene un teléfono asociado para identificar inventario propio."}
    return es.mis_calientes_public(agent.telefono_10, dias)


# =========================================================================
# UBICACIÓN: QUÉ HAY CERCA
# =========================================================================

@mcp.tool()
def que_hay_cerca(property_id: str) -> Dict[str, Any]:
    """
    Dice qué hay ALREDEDOR de una propiedad: colegios, universidades, estaciones
    de Metro, supermercados, centros comerciales, clínicas, parques y bancos,
    con la distancia real a cada uno. Responde la pregunta #1 del comprador.

    Úsala para "¿qué hay cerca del #X?", "¿tiene colegios cerca?", "¿queda cerca
    del Metro?". (Requiere que la propiedad tenga ubicación cargada.)
    """
    err = _agent_or_error()
    if err:
        return err
    return ls.que_hay_cerca_public(property_id)


# =========================================================================
# CREAR LISTING (publicar propiedad nativa en Fynder)
# =========================================================================

@mcp.tool()
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

    TÚ redactas el `titulo` y la `descripcion` atractivos y armas las amenidades
    (separadas por '|', ej. "Piscina|Gimnasio|Zona infantil") con lo que el
    agente te cuente y las fotos que te describa — sin llamar a otra IA.

    CÓMO FUNCIONA LA PUBLICACIÓN: si creas el listing SIN fotos, queda como
    BORRADOR (no aparece en búsquedas). En la respuesta viene `link_subir_fotos`:
    DÁSELO SIEMPRE al agente y explícale que la propiedad se PUBLICA SOLA en
    cuanto suba al menos una foto por ese link. Revisa `estado_publicacion` y
    `requiere_fotos` en la respuesta y comunícaselo.

    Úsala cuando el agente diga "publica/crea/sube una propiedad/listing".
    """
    err = _agent_or_error()
    if err:
        return err
    agent = current_agent()
    if not agent.has_inventory_scope:
        return {"error": "sin_telefono",
                "mensaje": "Tu usuario no tiene teléfono asociado; no puedo asignarte la propiedad."}
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
# ORDENAR FOTOS DE UN LISTING (apalancando la visión del LLM)
# =========================================================================

@mcp.tool()
def revisar_fotos(property_id: str):
    """
    Devuelve las FOTOS de una propiedad propia como imágenes numeradas para que
    TÚ las veas y decidas el mejor orden de presentación (portada primero, luego
    sala, cocina, habitaciones, baños, y por último exteriores/amenidades).

    Úsala ANTES de `ordenar_fotos`: mira las imágenes, decide el orden ideal y
    luego llama `ordenar_fotos` con las posiciones en el orden que elegiste.
    Solo funciona sobre propiedades que el agente captó.
    """
    err = _agent_or_error()
    if err:
        return err
    agent = current_agent()
    # Verificar ownership.
    prop = ps.get_property_public(property_id)
    if not prop:
        return {"error": "no_encontrada"}
    from src.services.textutils import normalize_phone
    if normalize_phone(prop.get("owner_phone")) != agent.telefono_10:
        return {"error": "no_es_tuya", "mensaje": "Solo puedes ordenar fotos de propiedades que tú captaste."}

    data = lst.listar_fotos(prop["id"])
    if data.get("total", 0) == 0:
        return {"mensaje": "La propiedad no tiene fotos todavía."}

    import httpx
    salida = [
        f"Fotos de la propiedad #{prop['id']} — {data.get('titulo') or ''}. "
        f"Son {data['total']}, numeradas 1 a {data['total']}. Míralas, decide el "
        f"mejor orden de presentación y luego llama ordenar_fotos con las posiciones "
        f"en ese orden (la primera será la portada)."
    ]
    for foto in data["fotos"]:
        salida.append(f"— Foto {foto['posicion']}:")
        try:
            r = httpx.get(foto["url"], timeout=15, follow_redirects=True)
            if r.status_code == 200:
                fmt = "png" if "png" in r.headers.get("content-type", "").lower() else "jpeg"
                salida.append(Image(data=r.content, format=fmt))
            else:
                salida.append(f"(no se pudo cargar la foto {foto['posicion']})")
        except Exception:
            salida.append(f"(no se pudo cargar la foto {foto['posicion']})")
    return salida


@mcp.tool()
def ordenar_fotos(property_id: str, orden: List[int]) -> Dict[str, Any]:
    """
    Reordena las fotos de una propiedad PROPIA. `orden` es la lista de POSICIONES
    actuales (1-indexed) en el orden que quieres. Ej: si hay 4 fotos y pasas
    [3,1,4,2], la foto #3 queda de PORTADA. Debe incluir cada posición una vez.

    Primero usa `revisar_fotos` para ver las imágenes y decidir el orden ideal
    (portada atractiva, luego áreas sociales, habitaciones, y exteriores).
    """
    err = _agent_or_error()
    if err:
        return err
    agent = current_agent()
    prop = ps.get_property_public(property_id)
    if not prop:
        return {"error": "no_encontrada"}
    from src.services.textutils import normalize_phone
    if normalize_phone(prop.get("owner_phone")) != agent.telefono_10:
        return {"error": "no_es_tuya", "mensaje": "Solo puedes ordenar fotos de propiedades que tú captaste."}
    try:
        return lst.reordenar_fotos(prop["id"], orden)
    except lst.ListingError as e:
        return {"error": "orden_invalido", "mensaje": str(e)}


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
