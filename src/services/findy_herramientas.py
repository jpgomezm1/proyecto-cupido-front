"""
Las herramientas del modo Análisis de Findy (web): las mismas lecturas que el MCP de
lectura (`src/mcp_server/server.py`), llamando a los mismos servicios, para el agente
autenticado del chat web.

Reglas que se mantienen (no romper):
  - Solo LECTURA: nada escribe, envía mensajes ni revela contactos (ver_contacto y
    compañía NO están aquí; el contacto se obtiene con el botón de llave de la app).
  - Toda salida pasa por `redact.sanitize` (el mismo blindaje del MCP) antes de llegar
    al modelo, y se recorta para no inflar los tokens.
  - "Propio" se decide por el teléfono VERIFICADO del agente.
"""

import json
from typing import Any, Callable, Dict, List, Optional

from src.services import suscripcion_service as suscripciones
from src.services.redact import sanitize
from src.services.textutils import normalize_phone

MAX_CARACTERES = 14000


class Agente:
    """El agente del chat web que hace la pregunta."""

    def __init__(self, user: Dict[str, Any]):
        self.user_id = int(user["id"])
        self.telefono = user.get("telefono")
        self.telefono_10 = normalize_phone(user.get("telefono")) if user.get("telefono_verificado") else None


def _marcar(agente: Agente, props: List[Dict[str, Any]]) -> None:
    """`contacto_desbloqueado` y `es_propia` en cada inmueble (como el MCP)."""
    ids = [p["id"] for p in props if p.get("id") is not None]
    vistos = suscripciones.ids_desbloqueados(agente.user_id, "propiedad", ids)
    for p in props:
        p["contacto_desbloqueado"] = p.get("id") in vistos
        if "owner_phone" in p:
            p["es_propia"] = bool(agente.telefono_10) and normalize_phone(p.get("owner_phone")) == agente.telefono_10


# ── Las funciones (los imports van adentro: el chat web no carga lo que no usa) ──

def _buscar(a: Agente, query: str, limit: int = 8, offset: int = 0):
    from src.services import property_service as ps
    res = ps.search(query=query, limit=min(max(int(limit), 1), 12), offset=offset,
                    telefono=a.telefono, agente_id=a.user_id)
    _marcar(a, res.get("propiedades") or [])
    return res


def _ficha(a: Agente, id_or_slug: str):
    from src.services import property_service as ps
    prop = ps.get_property_public(id_or_slug)
    if not prop:
        return {"error": "no_encontrada", "mensaje": f"No existe la propiedad {id_or_slug}"}
    _marcar(a, [prop])
    return prop


def _zona(a, ciudad=None, zona=None, tipo_propiedad=None, tipo_negocio="Venta"):
    from src.services import market_service as ms
    return ms.get_zone_stats(ciudad, zona, tipo_propiedad, tipo_negocio)


def _demanda(a, ciudad=None, zona=None, tipo_propiedad=None, dias=90):
    from src.services import market_service as ms
    return ms.get_demand_stats(ciudad, zona, tipo_propiedad, dias)


def _balance(a, ciudad=None, zona=None, tipo_propiedad=None, tipo_negocio="Venta", dias=90):
    from src.services import market_service as ms
    return ms.get_supply_demand_balance(ciudad, zona, tipo_propiedad, tipo_negocio, dias)


def _por_precio(a, ciudad=None, zona=None, tipo_propiedad="apartamento", dias=120):
    from src.services import market_service as ms
    from src.services.db import get_db
    with get_db() as db:
        rangos = ms.segmentos_precio(db.cursor, ciudad, zona, tipo_propiedad or "apartamento", dias)
    return {"filtro": {"ciudad": ciudad, "zona": zona, "tipo_propiedad": tipo_propiedad, "ventana_dias": dias},
            "rangos": rangos,
            "nota": "oferta = inmuebles activos con precio en el rango; demanda = pedidos con presupuesto en el rango"}


def _donde_captar(a, ciudad=None, tipo_propiedad="apartamento", dias=90):
    from src.services import market_service as ms
    return ms.donde_captar_public(ciudad, tipo_propiedad, dias)


def _preguntar(a, property_id: str, pregunta: str):
    from src.services import qa_service as qa
    d = qa.dossier_public(property_id)
    if isinstance(d, dict):
        d["pregunta"] = pregunta
    return d


def _comparables(a, property_id: str, limit: int = 12):
    from src.services import property_service as ps
    return ps.get_comparables_public(property_id, min(int(limit), 20))


def _comparar(a, property_ids: List[str]):
    from src.services import property_service as ps
    return ps.compare_public(property_ids[:5])


def _estimar(a, ciudad=None, zona=None, tipo_propiedad=None, area_construida=None, habitaciones=None,
             tipo_negocio="Venta"):
    from src.services import property_service as ps
    return ps.estimate_price_public(ciudad=ciudad, zona=zona, tipo_propiedad=tipo_propiedad,
                                    area_construida=area_construida, habitaciones=habitaciones,
                                    tipo_negocio=tipo_negocio)


def _diagnostico(a, property_id: str):
    from src.services import diagnosis_service as ds
    return ds.diagnose_public(property_id)


def _compradores_de(a: Agente, property_id: str, dias: int = 120, limit: int = 10):
    from src.services import diagnosis_service as ds
    res = ds.find_buyers_public(property_id, dias, min(int(limit), 15))
    compradores = res.get("compradores") if isinstance(res, dict) else None
    if compradores:
        vistos = suscripciones.ids_desbloqueados(a.user_id, "pedido", [c["pedido_id"] for c in compradores])
        for c in compradores:
            c["contacto_desbloqueado"] = c["pedido_id"] in vistos
    return res


def _compradores_para(a: Agente, entrada: str, limit: int = 8):
    from src.services import compradores_service as cs
    return cs.buscar_compradores_public(entrada, a.user_id, limit=min(max(int(limit), 1), 15))


def _capacidad(a, ingreso_mensual: float, cuota_inicial: float = 0, tasa_mensual: float = 0.011,
               plazo_anos: int = 20, ciudad=None, zona=None, tipo_propiedad=None):
    from src.services import property_service as ps
    return ps.capacidad_de_compra_public(ingreso_mensual=ingreso_mensual, cuota_inicial=cuota_inicial,
                                         tasa_mensual=tasa_mensual, plazo_anos=plazo_anos,
                                         ciudad=ciudad, zona=zona, tipo_propiedad=tipo_propiedad)


def _costo_mensual(a, property_id: str, cuota_inicial=None, tasa_mensual: float = 0.011, plazo_anos: int = 20):
    from src.services import property_service as ps
    return ps.costo_total_mensual_public(property_id, cuota_inicial, tasa_mensual, plazo_anos)


def _encaje(a, property_id: str, presupuesto_max=None, habitaciones_min=None, parqueaderos_min=None,
            estrato_min=None, area_min=None, amenidades=None, zonas=None):
    from src.services import property_service as ps
    return ps.match_comprador_public(property_id, presupuesto_max=presupuesto_max,
                                     habitaciones_min=habitaciones_min, parqueaderos_min=parqueaderos_min,
                                     estrato_min=estrato_min, area_min=area_min,
                                     amenidades=amenidades, zonas=zonas)


def _pitch(a: Agente, property_id: str, perfil_comprador: Optional[str] = None):
    from src.services import property_service as ps
    return ps.ficha_venta_public(property_id, perfil_comprador, agente_id=a.user_id)


def _interes(a, property_id: str, dias: int = 30):
    from src.services import engagement_service as es
    return es.termometro_public(property_id, dias)


def _mis_calientes(a: Agente, dias: int = 30):
    if not a.telefono_10:
        return {"total": 0, "listings": [], "mensaje": "El celular del agente no está verificado: no hay inmuebles propios."}
    from src.services import engagement_service as es
    return es.mis_calientes_public(a.telefono_10, dias)


def _cerca(a, property_id: str):
    from src.services import location_service as ls
    return ls.que_hay_cerca_public(property_id)


# ── Esquemas para Claude ──

_S = {"type": "string"}
_N = {"type": "number"}
_I = {"type": "integer"}
_ZONA = {
    "ciudad": {**_S, "description": "Ciudad o municipio (Medellín, Envigado, Sabaneta…)"},
    "zona": {**_S, "description": "Barrio o zona (Laureles, El Poblado, Belén…)"},
    "tipo_propiedad": {**_S, "description": "apartamento, casa, lote, oficina, local…"},
}
_PID = {"property_id": {**_S, "description": "Id numérico o código del inmueble en Fynder"}}


def _h(nombre: str, fn: Callable, descripcion: str, props: Dict[str, Any], requeridos: List[str] = ()):
    return {"name": nombre, "fn": fn, "description": descripcion,
            "input_schema": {"type": "object", "properties": props, "required": list(requeridos)}}


HERRAMIENTAS: List[Dict[str, Any]] = [
    _h("buscar_inmuebles", _buscar,
       "Busca inmuebles en el inventario de Fynder con lenguaje natural ('apartamento en Laureles, 3 hab, "
       "hasta 600 millones'). Devuelve los inmuebles con id, precio, zona, m², precio/m² y por qué encajan.",
       {"query": _S, "limit": {**_I, "description": "Máximo 12 (por defecto 8)"}, "offset": _I}, ["query"]),
    _h("ficha_inmueble", _ficha, "La ficha completa de un inmueble por id o código.",
       {"id_or_slug": _S}, ["id_or_slug"]),
    _h("oferta_zona", _zona,
       "OFERTA de una zona: inventario activo, rango de precios, precio/m² mediano, área y habitaciones típicas.",
       {**_ZONA, "tipo_negocio": {**_S, "enum": ["Venta", "Arriendo"]}}),
    _h("demanda_zona", _demanda,
       "DEMANDA de una zona en los últimos `dias`: cuántos compradores buscan y su presupuesto típico.",
       {**_ZONA, "dias": _I}),
    _h("balance_zona", _balance,
       "Oferta contra demanda de una zona: compradores por inmueble y si está caliente, equilibrada o fría.",
       {**_ZONA, "tipo_negocio": {**_S, "enum": ["Venta", "Arriendo"]}, "dias": _I}),
    _h("oferta_demanda_por_precio", _por_precio,
       "OFERTA contra DEMANDA de una zona por RANGO DE PRECIO (datos reales, no estimados): en qué rango hay "
       "más compradores que inventario (hueco) y en cuál sobra oferta. Es la ÚNICA fuente válida para un "
       "gráfico de oferta vs demanda por precio.",
       {"ciudad": _ZONA["ciudad"], "zona": _ZONA["zona"], "tipo_propiedad": _ZONA["tipo_propiedad"], "dias": _I}),
    _h("donde_captar", _donde_captar,
       "Por zona, oferta activa contra compradores: dónde hay más demanda que inventario (dónde conviene captar).",
       {"ciudad": _ZONA["ciudad"], "tipo_propiedad": _ZONA["tipo_propiedad"], "dias": _I}),
    _h("estimar_precio", _estimar,
       "Precio de captación sugerido para un inmueble (precio/m² mediano de comparables × área) y su rango.",
       {**_ZONA, "area_construida": _N, "habitaciones": _I, "tipo_negocio": {**_S, "enum": ["Venta", "Arriendo"]}}),
    _h("comparables", _comparables, "Los comparables de mercado de un inmueble de Fynder.",
       {**_PID, "limit": _I}, ["property_id"]),
    _h("comparar_inmuebles", _comparar,
       "Compara 2 a 5 inmuebles lado a lado (precio, m², precio/m², habitaciones, amenidades, días publicados) "
       "con un veredicto de cuál es mejor valor.",
       {"property_ids": {"type": "array", "items": _S}}, ["property_ids"]),
    _h("diagnosticar_inmueble", _diagnostico,
       "Por qué un inmueble no se vende: precio frente a comparables, fotos, descripción, tiempo y demanda; "
       "hallazgos priorizados con acciones.", _PID, ["property_id"]),
    _h("compradores_de_inmueble", _compradores_de,
       "Pedidos de compradores recientes que encajan con un inmueble de Fynder (zona y presupuesto).",
       {**_PID, "dias": _I, "limit": _I}, ["property_id"]),
    _h("compradores_para", _compradores_para,
       "Búsqueda inversa: el agente da un link (Wasi, Lobbie, Fynder) o una descripción de SU inmueble y "
       "devuelve los pedidos que encajan, con score 0-100 y razones.",
       {"entrada": _S, "limit": _I}, ["entrada"]),
    _h("encaje_comprador", _encaje,
       "Qué tan bien le sirve un inmueble a un perfil de comprador: score 0-100, veredicto y razones.",
       {**_PID, "presupuesto_max": _N, "habitaciones_min": _I, "parqueaderos_min": _I, "estrato_min": _I,
        "area_min": _N, "amenidades": {"type": "array", "items": _S}, "zonas": {"type": "array", "items": _S}},
       ["property_id"]),
    _h("capacidad_de_compra", _capacidad,
       "Para cuánto le alcanza a un comprador con crédito (cuota ~30 % del ingreso) y cuántos inmuebles entran.",
       {"ingreso_mensual": _N, "cuota_inicial": _N, "tasa_mensual": _N, "plazo_anos": _I, **_ZONA},
       ["ingreso_mensual"]),
    _h("costo_mensual", _costo_mensual,
       "Cuánto sale vivir al mes en un inmueble: administración, servicios, predial y cuota del crédito.",
       {**_PID, "cuota_inicial": _N, "tasa_mensual": _N, "plazo_anos": _I}, ["property_id"]),
    _h("puntos_de_venta", _pitch,
       "Los puntos de venta de un inmueble (si está barato frente a la zona, destacados, gancho) para un pitch.",
       {**_PID, "perfil_comprador": _S}, ["property_id"]),
    _h("interes_inmueble", _interes, "Vistas, clics y contactos de un inmueble en los últimos `dias`.",
       {**_PID, "dias": _I}, ["property_id"]),
    _h("mis_inmuebles_calientes", _mis_calientes,
       "Los inmuebles PROPIOS del agente ordenados por interés real (vistas y contactos).", {"dias": _I}),
    _h("que_hay_cerca", _cerca,
       "Qué hay alrededor de un inmueble (colegios, Metro, supermercados, clínicas, parques) con distancias.",
       _PID, ["property_id"]),
]
_POR_NOMBRE = {h["name"]: h for h in HERRAMIENTAS}


def esquemas() -> List[Dict[str, Any]]:
    """Las herramientas como las recibe la API de Claude."""
    return [{k: h[k] for k in ("name", "description", "input_schema")} for h in HERRAMIENTAS]


def ejecutar(agente: Agente, nombre: str, args: Dict[str, Any]) -> str:
    """Corre una herramienta y devuelve su salida saneada y recortada (texto JSON)."""
    h = _POR_NOMBRE.get(nombre)
    if not h:
        return json.dumps({"error": "herramienta_desconocida"})
    try:
        res = h["fn"](agente, **(args or {}))
    except TypeError as e:
        res = {"error": "argumentos_invalidos", "mensaje": str(e)[:200]}
    texto = json.dumps(sanitize(res), ensure_ascii=False, default=str)
    if len(texto) > MAX_CARACTERES:
        texto = texto[:MAX_CARACTERES] + '… (recortado)"'
    return texto
