"""
Servicio de ESCRITURAS del MCP (patrón propose -> apply).

Toda mutación:
1. Se propone con un `propose_*` que valida propiedad + propiedad del agente
   (ownership) y devuelve un PREVIEW + un `confirmation_token`.
2. Se ejecuta con `apply_change(confirmation_token)`.

El `confirmation_token` es **stateless**: contiene la acción firmada con HMAC
(no se guarda estado en memoria, así que funciona con múltiples workers). Al
aplicar se re-verifica firma, expiración, que quien aplica es el mismo agente
que propuso, y la propiedad del inmueble — y además el UPDATE lleva el filtro de
ownership en el propio WHERE (defensa en profundidad). Cada cambio queda en
`eventos_log`.

Scoping: un agente solo puede modificar inmuebles que él captó
(`agente_captador_telefono` con los mismos últimos 10 dígitos).
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, List, Optional

from src.services.db import get_db, fetch_one
from src.services.textutils import normalize_phone, format_cop
from src.services.property_service import get_property
from src.services import market_service as ms

# Ventana de validez del confirmation_token.
_TOKEN_TTL_SECONDS = 600  # 10 minutos

_ESTADOS_VALIDOS = {
    "vendido":     {"activa": False, "estado": "Vendido"},
    "inactivo":    {"activa": False, "estado": "Inactivo"},
    "pausado":     {"activa": False, "estado": "Pausado"},
    "disponible":  {"activa": True,  "estado": "Disponible"},
}


class WriteError(Exception):
    """Error de negocio en una operación de escritura (ownership, validación)."""


def _secret() -> bytes:
    secret = os.getenv("FYNDER_MCP_SECRET") or os.getenv("JWT_SECRET")
    if not secret:
        raise WriteError(
            "Falta FYNDER_MCP_SECRET (o JWT_SECRET) en el entorno; las escrituras "
            "están deshabilitadas por seguridad."
        )
    return secret.encode("utf-8")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _make_token(payload: Dict[str, Any]) -> str:
    payload = dict(payload)
    payload["exp"] = int(time.time()) + _TOKEN_TTL_SECONDS
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def _verify_token(token: str, agent_phone_10: str) -> Dict[str, Any]:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        raise WriteError("confirmation_token con formato inválido")

    expected = _b64e(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise WriteError("confirmation_token inválido (firma no coincide)")

    payload = json.loads(_b64d(body))
    if payload.get("exp", 0) < int(time.time()):
        raise WriteError("confirmation_token expirado; vuelve a proponer el cambio")
    if payload.get("owner") != agent_phone_10:
        raise WriteError("Este cambio fue propuesto por otro agente; no puedes aplicarlo")
    return payload


def _require_owned(cur, property_id, agent_phone_10: str) -> Dict[str, Any]:
    """Carga la propiedad y verifica que la captó el agente. Lanza si no."""
    prop = get_property(cur, property_id)
    if not prop:
        raise WriteError(f"La propiedad {property_id} no existe")
    owner_10 = normalize_phone(prop.get("owner_phone"))
    if not owner_10 or owner_10 != agent_phone_10:
        raise WriteError(
            "Solo puedes modificar propiedades que tú captaste. Esta propiedad "
            "no está a tu nombre."
        )
    return prop


# =========================================================================
# PROPOSE
# =========================================================================

def propose_price_update(agent, property_id, nuevo_precio: int) -> Dict[str, Any]:
    if nuevo_precio is None or int(nuevo_precio) <= 0:
        raise WriteError("El nuevo precio debe ser un entero positivo (en COP)")
    nuevo_precio = int(nuevo_precio)
    with get_db() as db:
        prop = _require_owned(db.cursor, property_id, agent.telefono_10)
        zona = ms.zone_stats(db.cursor, prop.get("ciudad"), prop.get("zona"),
                             prop.get("tipo_propiedad"), prop.get("tipo_negocio") or "Venta")

    actual = prop.get("precio")
    delta_pct = round((nuevo_precio - actual) / actual * 100, 1) if actual else None
    area = prop.get("area_construida")
    nuevo_m2 = (nuevo_precio / area) if area else None

    token = _make_token({
        "action": "price", "property_id": prop["id"],
        "owner": agent.telefono_10, "nuevo_precio": nuevo_precio,
    })
    return {
        "accion": "actualizar_precio",
        "propiedad": {"id": prop["id"], "slug": prop["slug"], "titulo": prop["titulo"]},
        "preview": {
            "precio_actual": actual,
            "precio_actual_legible": format_cop(actual),
            "precio_nuevo": nuevo_precio,
            "precio_nuevo_legible": format_cop(nuevo_precio),
            "cambio_pct": delta_pct,
            "nuevo_precio_m2": round(nuevo_m2) if nuevo_m2 else None,
            "precio_m2_mediana_zona": zona.get("precio_m2_mediana"),
        },
        "confirmation_token": token,
        "instruccion": "Para confirmar, llama apply_change con este confirmation_token.",
    }


def propose_description_update(agent, property_id, nueva_descripcion: str) -> Dict[str, Any]:
    if not nueva_descripcion or len(nueva_descripcion.strip()) < 20:
        raise WriteError("La nueva descripción es muy corta (mínimo 20 caracteres)")
    nueva_descripcion = nueva_descripcion.strip()
    with get_db() as db:
        prop = _require_owned(db.cursor, property_id, agent.telefono_10)

    token = _make_token({
        "action": "description", "property_id": prop["id"],
        "owner": agent.telefono_10, "descripcion": nueva_descripcion,
    })
    actual = prop.get("descripcion") or ""
    return {
        "accion": "actualizar_descripcion",
        "propiedad": {"id": prop["id"], "slug": prop["slug"], "titulo": prop["titulo"]},
        "preview": {
            "longitud_actual": len(actual),
            "longitud_nueva": len(nueva_descripcion),
            "descripcion_nueva": nueva_descripcion,
        },
        "confirmation_token": token,
        "instruccion": "Para confirmar, llama apply_change con este confirmation_token.",
    }


def propose_status_update(agent, property_id, nuevo_estado: str) -> Dict[str, Any]:
    estado_key = (nuevo_estado or "").strip().lower()
    if estado_key not in _ESTADOS_VALIDOS:
        raise WriteError(
            f"Estado inválido '{nuevo_estado}'. Opciones: {', '.join(_ESTADOS_VALIDOS)}"
        )
    with get_db() as db:
        prop = _require_owned(db.cursor, property_id, agent.telefono_10)

    token = _make_token({
        "action": "status", "property_id": prop["id"],
        "owner": agent.telefono_10, "estado_key": estado_key,
    })
    return {
        "accion": "actualizar_estado",
        "propiedad": {"id": prop["id"], "slug": prop["slug"], "titulo": prop["titulo"]},
        "preview": {
            "estado_actual": prop.get("estado"),
            "activa_actual": prop.get("activa"),
            "estado_nuevo": _ESTADOS_VALIDOS[estado_key]["estado"],
            "activa_nueva": _ESTADOS_VALIDOS[estado_key]["activa"],
        },
        "confirmation_token": token,
        "instruccion": "Para confirmar, llama apply_change con este confirmation_token.",
    }


def register_buyer_match(agent, property_id, comprador_telefono: str,
                         notas: Optional[str] = None) -> Dict[str, Any]:
    """
    Registra un match con un comprador (crea una interacción y la audita). Es
    aditivo (no muta datos existentes), así que se ejecuta directo, pero scoped:
    solo sobre inmuebles propios.
    """
    comprador_10 = normalize_phone(comprador_telefono)
    if not comprador_10:
        raise WriteError("Teléfono de comprador inválido")

    with get_db() as db:
        prop = _require_owned(db.cursor, property_id, agent.telefono_10)
        db.cursor.execute("""
            INSERT INTO interacciones (
                agente_comprador_telefono, propiedad_id,
                agente_vendedor_telefono, estado, notas_estado
            ) VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (comprador_telefono, prop["id"], agent.telefono, "Seleccionado", notas))
        interaccion_id = db.cursor.fetchone()["id"]
        db.conn.commit()

        db.log_evento(
            tipo_evento="mcp_match_registrado",
            agente_telefono=agent.telefono,
            propiedad_id=prop["id"],
            interaccion_id=interaccion_id,
            datos_evento={"comprador_telefono": comprador_telefono, "notas": notas,
                          "origen": "mcp"},
        )

    return {
        "ok": True,
        "interaccion_id": interaccion_id,
        "propiedad_id": prop["id"],
        "comprador_telefono": comprador_telefono,
        "mensaje": "Match registrado. Aparecerá en el pipeline de interacciones.",
    }


# =========================================================================
# APPLY
# =========================================================================

def apply_change(agent, confirmation_token: str) -> Dict[str, Any]:
    payload = _verify_token(confirmation_token, agent.telefono_10)
    action = payload.get("action")
    property_id = payload.get("property_id")
    owner_10 = agent.telefono_10

    with get_db() as db:
        # El WHERE incluye ownership: defensa en profundidad aunque el token ya lo valida.
        own_clause = ("RIGHT(REGEXP_REPLACE(agente_captador_telefono,'[^0-9]','','g'),10) = %s")

        if action == "price":
            db.cursor.execute(f"""
                UPDATE propiedades SET precio = %s, fecha_actualizacion = NOW()
                WHERE id = %s AND {own_clause}
                RETURNING id, precio
            """, (payload["nuevo_precio"], property_id, owner_10))
            resumen = {"campo": "precio", "valor": payload["nuevo_precio"]}

        elif action == "description":
            desc = payload["descripcion"]
            db.cursor.execute(f"""
                UPDATE propiedades
                SET descripcion = %s, descripcion_length = %s, fecha_actualizacion = NOW()
                WHERE id = %s AND {own_clause}
                RETURNING id
            """, (desc, len(desc), property_id, owner_10))
            resumen = {"campo": "descripcion", "longitud": len(desc)}

        elif action == "status":
            cfg = _ESTADOS_VALIDOS[payload["estado_key"]]
            db.cursor.execute(f"""
                UPDATE propiedades
                SET activa = %s, estado = %s, fecha_actualizacion = NOW()
                WHERE id = %s AND {own_clause}
                RETURNING id
            """, (cfg["activa"], cfg["estado"], property_id, owner_10))
            resumen = {"campo": "estado", "estado": cfg["estado"], "activa": cfg["activa"]}

        else:
            raise WriteError(f"Acción desconocida en el token: {action}")

        row = db.cursor.fetchone()
        if not row:
            db.conn.rollback()
            raise WriteError(
                "No se aplicó el cambio: la propiedad no existe o no es tuya."
            )
        db.conn.commit()

        db.log_evento(
            tipo_evento=f"mcp_{action}_update",
            agente_telefono=agent.telefono,
            propiedad_id=property_id,
            datos_evento={"origen": "mcp", **resumen},
        )

    return {"ok": True, "propiedad_id": property_id, "aplicado": resumen}


# =========================================================================
# Registro de tools en el servidor MCP.
# =========================================================================

def register_write_tools(mcp) -> None:
    """Registra las herramientas de escritura en la instancia FastMCP."""
    from src.mcp_server.identity_context import require_agent, AuthError

    def _guard():
        try:
            return require_agent(), None
        except AuthError as e:
            return None, {"error": "no_autorizado", "mensaje": str(e)}

    def _wrap(fn, *args):
        agent, err = _guard()
        if err:
            return err
        try:
            return fn(agent, *args)
        except WriteError as e:
            return {"error": "escritura_rechazada", "mensaje": str(e)}

    @mcp.tool()
    def propose_price_update_tool(property_id: str, nuevo_precio: int) -> Dict[str, Any]:
        """
        PROPONE cambiar el precio de una propiedad PROPIA. Devuelve un preview
        (precio actual vs nuevo, % de cambio, precio/m² resultante vs mediana de
        zona) y un confirmation_token. NO aplica el cambio: para aplicarlo, llama
        `apply_change` con el token. Solo funciona sobre inmuebles que tú captaste.
        """
        return _wrap(propose_price_update, property_id, nuevo_precio)

    @mcp.tool()
    def propose_description_update_tool(property_id: str, nueva_descripcion: str) -> Dict[str, Any]:
        """
        PROPONE reemplazar la descripción de una propiedad PROPIA por una mejor
        (puedes redactarla tú). Devuelve un preview y un confirmation_token; para
        aplicar, llama `apply_change`. Solo sobre inmuebles propios.
        """
        return _wrap(propose_description_update, property_id, nueva_descripcion)

    @mcp.tool()
    def propose_status_update_tool(property_id: str, nuevo_estado: str) -> Dict[str, Any]:
        """
        PROPONE cambiar el estado de una propiedad PROPIA. Estados válidos:
        'vendido', 'inactivo', 'pausado', 'disponible'. Marcar 'vendido' la saca
        del inventario activo. Devuelve preview + confirmation_token; aplica con
        `apply_change`.
        """
        return _wrap(propose_status_update, property_id, nuevo_estado)

    @mcp.tool()
    def register_buyer_match_tool(property_id: str, comprador_telefono: str,
                                  notas: str = None) -> Dict[str, Any]:
        """
        Registra un match entre una propiedad PROPIA y un comprador (crea una
        interacción en el pipeline). Úsala tras `find_buyers_for_property` cuando
        el agente decide contactar/avanzar con un comprador.
        """
        return _wrap(register_buyer_match, property_id, comprador_telefono, notas)

    @mcp.tool()
    def apply_change(confirmation_token: str) -> Dict[str, Any]:
        """
        APLICA un cambio previamente propuesto, usando el confirmation_token que
        devolvió una tool `propose_*`. Este es el paso que efectivamente escribe
        en la base de datos. El token expira a los 10 minutos.
        """
        agent, err = _guard()
        if err:
            return err
        try:
            return apply_change_impl(agent, confirmation_token)
        except WriteError as e:
            return {"error": "escritura_rechazada", "mensaje": str(e)}


# Alias interno para poder registrar `apply_change` como tool sin choque de nombres.
apply_change_impl = apply_change
