"""
Estructura con Claude Haiku los textos libres del mercado:

- `estructurar_pedido(texto)`: un pedido ("Busco apto en Laureles, 3 alcobas,
  hasta 600 millones, NO primer piso") -> criterios del comprador.
- `ficha_desde_texto(texto)`: la descripción de un inmueble que escribe el
  agente ("apto de 85 m² en Laureles, 3 hab, 520 millones") -> ficha.
- `estructurar_pendientes()`: llena `pedidos.criterios` de los recientes que no
  lo tienen (lo corre el worker y el script de carga inicial).

Se usa tool-use forzado: la salida siempre cumple el esquema. Sin dependencias
de Flask (lo usa también el MCP).
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from src.services.db import get_db, fetch_all

MODELO = os.getenv("FYNDER_MODELO_PEDIDOS", "claude-haiku-4-5")
VERSION = 1

_TIPOS = ["apartamento", "apartaestudio", "casa", "casa campestre", "penthouse", "duplex",
          "lote", "finca", "local", "oficina", "bodega", "consultorio"]

_SCHEMA_PEDIDO = {
    "type": "object",
    "properties": {
        "negocio": {"type": ["string", "null"], "enum": ["venta", "arriendo", None],
                    "description": "venta si compra; arriendo si busca arrendar. null si no se sabe."},
        "tipos": {"type": "array", "items": {"type": "string", "enum": _TIPOS},
                  "description": "Tipos de inmueble que acepta."},
        "zonas": {"type": "array", "items": {"type": "string"},
                  "description": "Barrios/sectores aceptados, con su nombre propio limpio (ej: 'Laureles', "
                                 "'El Poblado', 'Loma de las Brujas', 'San Lucas'). Si dice 'desde A hasta B', "
                                 "incluye A, B y los sectores conocidos entre ellos si los sabes."},
        "ciudades": {"type": "array", "items": {"type": "string"},
                     "description": "Municipios (ej: 'Medellín', 'Envigado', 'Sabaneta', 'Itagüí', 'Rionegro')."},
        "zonas_excluidas": {"type": "array", "items": {"type": "string"}},
        "presupuesto_min": {"type": ["integer", "null"], "description": "En pesos COP enteros."},
        "presupuesto_max": {"type": ["integer", "null"],
                            "description": "En pesos COP enteros. '600 millones' = 600000000; "
                                           "'1.800 hasta 2.200' (en millones) = 1800000000 a 2200000000."},
        "habitaciones_min": {"type": ["integer", "null"]},
        "banos_min": {"type": ["integer", "null"]},
        "parqueaderos_min": {"type": ["integer", "null"]},
        "area_min": {"type": ["number", "null"], "description": "m²"},
        "area_max": {"type": ["number", "null"], "description": "m²"},
        "exigencias": {"type": "array", "items": {"type": "string"},
                       "description": "Requisitos cortos en minúscula (ej: 'balcón', 'piscina', 'estudio', "
                                      "'unidad cerrada', 'vista', 'piso alto', 'ascensor', 'útil')."},
        "excluye": {"type": "array", "items": {"type": "string"},
                    "description": "Lo que NO acepta (ej: 'dúplex', 'primer piso')."},
    },
    "required": ["negocio", "tipos", "zonas", "ciudades", "zonas_excluidas", "presupuesto_min",
                 "presupuesto_max", "habitaciones_min", "banos_min", "parqueaderos_min",
                 "area_min", "area_max", "exigencias", "excluye"],
}

_SCHEMA_FICHA = {
    "type": "object",
    "properties": {
        "tipo": {"type": ["string", "null"], "enum": _TIPOS + [None]},
        "negocio": {"type": ["string", "null"], "enum": ["venta", "arriendo", None]},
        "ciudad": {"type": ["string", "null"]},
        "zona": {"type": ["string", "null"], "description": "Barrio o sector."},
        "precio": {"type": ["integer", "null"], "description": "Pesos COP enteros (520 millones = 520000000)."},
        "habitaciones": {"type": ["integer", "null"]},
        "banos": {"type": ["integer", "null"]},
        "parqueaderos": {"type": ["integer", "null"]},
        "area_m2": {"type": ["number", "null"]},
        "amenidades": {"type": "array", "items": {"type": "string"},
                       "description": "Cortas y en minúscula (balcón, piscina, estudio, vista, unidad cerrada...)."},
    },
    "required": ["tipo", "negocio", "ciudad", "zona", "precio", "habitaciones", "banos",
                 "parqueaderos", "area_m2", "amenidades"],
}

_SISTEMA = ("Eres un asistente inmobiliario de Medellín y el Valle de Aburrá (Colombia). "
            "Extraes datos estructurados de textos de agentes inmobiliarios. No inventes: si un dato "
            "no aparece, usa null o una lista vacía. Los precios en Colombia se dicen en millones.")


def _cliente():
    import anthropic  # perezoso: el MCP no lo importa si no se usa
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _extraer(texto: str, schema: Dict[str, Any], nombre: str, instruccion: str) -> Dict[str, Any]:
    resp = _cliente().messages.create(
        model=MODELO,
        max_tokens=800,
        system=_SISTEMA,
        tools=[{"name": nombre, "description": instruccion, "input_schema": schema}],
        tool_choice={"type": "tool", "name": nombre},
        messages=[{"role": "user", "content": texto[:4000]}],
    )
    for bloque in resp.content:
        if getattr(bloque, "type", None) == "tool_use":
            return dict(bloque.input)
    raise RuntimeError("El modelo no devolvió la estructura")


def estructurar_pedido(texto: str) -> Dict[str, Any]:
    crit = _extraer(texto, _SCHEMA_PEDIDO, "guardar_pedido",
                    "Guarda los criterios del comprador que hizo este pedido.")
    crit["_v"] = VERSION
    return crit


def ficha_desde_texto(texto: str) -> Dict[str, Any]:
    return _extraer(texto, _SCHEMA_FICHA, "guardar_inmueble",
                    "Guarda la ficha del inmueble que describe el agente.")


def estructurar_pendientes(dias: int = 120, limit: int = 300, concurrencia: int = 8) -> Dict[str, int]:
    """Estructura los pedidos recientes sin criterios. Devuelve {procesados, errores}."""
    with get_db() as db:
        filas = fetch_all(db.cursor, """
            SELECT id, texto_pedido FROM pedidos
            WHERE criterios IS NULL AND texto_pedido IS NOT NULL AND LENGTH(TRIM(texto_pedido)) > 10
              AND fecha_captura > NOW() - make_interval(days => %s)
            ORDER BY fecha_captura DESC
            LIMIT %s
        """, (dias, limit))
    if not filas:
        return {"procesados": 0, "errores": 0}

    def _uno(f) -> Optional[tuple]:
        try:
            return f["id"], estructurar_pedido(f["texto_pedido"])
        except Exception as e:  # noqa: BLE001 — un pedido malo no frena el lote
            print(f"[PEDIDOS-IA] pedido {f['id']}: {type(e).__name__}: {str(e)[:120]}")
            return None

    with ThreadPoolExecutor(max_workers=concurrencia) as ex:
        resultados: List[Optional[tuple]] = list(ex.map(_uno, filas))

    ok = [r for r in resultados if r]
    if ok:
        with get_db() as db:
            for pid, crit in ok:
                db.cursor.execute(
                    "UPDATE pedidos SET criterios = %s, criterios_at = NOW() WHERE id = %s",
                    (json.dumps(crit, ensure_ascii=False), pid))
            db.conn.commit()
    return {"procesados": len(ok), "errores": len(filas) - len(ok)}
