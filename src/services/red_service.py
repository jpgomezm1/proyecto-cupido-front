"""
La red de Fynder: lo que los agentes comparten desde Fynder (migración 058).

Compartir el pedido de un cliente: el perfil del cliente (el mismo pedido del
buscador v3) se publica como un pedido de la red (`pedidos`, canal fynder_web
o fynder_mcp), con los criterios que usa "compradores para tu inmueble"
(`compradores_service.puntuar`). Así la red se alimenta de sus usuarios y no
solo de los grupos de WhatsApp, y el pedido se puede desbloquear desde el
primer minuto: quien lo comparte tiene el celular verificado y los términos
aceptados (Ley 1581).

El texto del pedido sale solo del perfil: nunca el nombre ni el teléfono del
cliente. Mientras está compartido, se sincroniza cuando cambia el perfil.
"""

import json
from typing import Any, Dict, List, Optional

from src.services.db import fetch_one, get_db, scalar
from src.services.textutils import format_cop

CANALES = {"web": "fynder_web", "mcp": "fynder_mcp"}
_TIPOS_PEDIDO = {"apartamento", "apartaestudio", "casa", "casa campestre", "penthouse", "duplex",
                 "lote", "finca", "local", "oficina", "bodega", "consultorio"}


class RedError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def criterios_desde_perfil(perfil: Dict[str, Any]) -> Dict[str, Any]:
    """Perfil del cliente (buscador v3) → criterios de un pedido (pedidos_ia/compradores)."""
    p = perfil or {}
    ubic = [u for u in p.get("ubicaciones") or [] if (u.get("nombre") or "").strip()]
    tipos = [t.replace("_", " ").lower() for t in p.get("tipos") or []]
    return {
        "_v": 1,
        "negocio": p.get("negocio"),
        "tipos": [t for t in tipos if t in _TIPOS_PEDIDO],
        "zonas": [u["nombre"].strip() for u in ubic],
        "ciudades": sorted({u["municipio"].strip() for u in ubic if (u.get("municipio") or "").strip()}),
        "zonas_excluidas": [x for x in p.get("ubicaciones_excluidas") or [] if x],
        "presupuesto_min": p.get("presupuesto_min"),
        "presupuesto_max": p.get("presupuesto_max"),
        "habitaciones_min": p.get("habitaciones_min"),
        "banos_min": p.get("banos_min"),
        "parqueaderos_min": p.get("parqueaderos_min"),
        "area_min": p.get("area_min"),
        "area_max": p.get("area_max"),
        "exigencias": [c.replace("_", " ") for c in p.get("obligatorias") or []],
        "excluye": [],
    }


def texto_desde_perfil(perfil: Dict[str, Any]) -> str:
    """'Busco apartamento en Laureles o Estadio, 3+ habitaciones, hasta $650 millones.'"""
    p = perfil or {}
    tipos = [t.replace("_", " ") for t in p.get("tipos") or []] or ["inmueble"]
    zonas = [u.get("nombre") for u in p.get("ubicaciones") or [] if u.get("nombre")]
    partes: List[str] = []
    verbo = "Busco en arriendo" if p.get("negocio") == "arriendo" else "Busco"
    partes.append(f"{verbo} {' o '.join(tipos)}" + (f" en {', '.join(zonas[:-1]) + ' o ' + zonas[-1] if len(zonas) > 1 else zonas[0]}" if zonas else ""))
    for k, n in (("habitaciones_min", "habitaciones"), ("banos_min", "baños"), ("parqueaderos_min", "parqueaderos")):
        if p.get(k):
            partes.append(f"{int(p[k])}+ {n}")
    if p.get("area_min"):
        partes.append(f"desde {int(p['area_min'])} m²")
    pmin, pmax = p.get("presupuesto_min"), p.get("presupuesto_max")
    if pmax:
        partes.append(f"de {format_cop(pmin)} hasta {format_cop(pmax)}" if pmin else f"hasta {format_cop(pmax)}")
    if p.get("obligatorias"):
        partes.append("con " + ", ".join(c.replace("_", " ") for c in p["obligatorias"][:4]))
    if p.get("ubicaciones_excluidas"):
        partes.append("no en " + ", ".join(p["ubicaciones_excluidas"][:3]))
    return ", ".join(partes) + "."


def _publicable(perfil: Dict[str, Any]) -> Optional[str]:
    """Qué le falta al perfil para que un pedido sirva en la red (o None)."""
    p = perfil or {}
    if not p.get("tipos"):
        return "Falta el tipo de inmueble (apartamento, casa…)."
    if not any((u.get("nombre") or "").strip() for u in p.get("ubicaciones") or []):
        return "Falta al menos una zona."
    if not (p.get("presupuesto_max") or p.get("presupuesto_min")):
        return "Falta el presupuesto."
    return None


def _usuario_habilitado(cur, user_id: int) -> Dict[str, Any]:
    u = fetch_one(cur, """
        SELECT id, nombre, telefono, telefono_verificado, terminos_aceptados_at
        FROM chat_users WHERE id = %s AND activo
    """, (user_id,))
    if not u:
        raise RedError("no_encontrado", "Usuario no encontrado.")
    if not u.get("telefono_verificado") or not u.get("telefono"):
        raise RedError("telefono_no_verificado", "Verifica tu celular para compartir pedidos: es el contacto que verán los agentes.")
    if not u.get("terminos_aceptados_at"):
        raise RedError("terminos", "Acepta los términos de Fynder para compartir pedidos con la red.")
    return u


def estado_pedido(cur, cliente: Dict[str, Any]) -> Dict[str, Any]:
    """{en_red, pedido_id, falta} para mostrar el interruptor del cliente."""
    pid = cliente.get("pedido_id")
    activo = bool(pid and scalar(cur, "SELECT 1 FROM pedidos WHERE id = %s AND estado <> 'retirado'", (pid,)))
    return {"en_red": activo, "pedido_id": pid if activo else None, "falta": _publicable(cliente.get("perfil") or {})}


def compartir_pedido(user_id: int, cliente_id: int, activo: bool = True, canal: str = "web") -> Dict[str, Any]:
    """Publica (o retira) el pedido de un cliente en la red."""
    with get_db() as db:
        cur = db.cursor
        c = fetch_one(cur, "SELECT * FROM clientes_agente WHERE id = %s AND user_id = %s", (cliente_id, user_id))
        if not c:
            raise RedError("no_encontrado", "Ese cliente no existe.")
        if not activo:
            if c.get("pedido_id"):
                cur.execute("UPDATE pedidos SET estado = 'retirado' WHERE id = %s AND user_id = %s",
                            (c["pedido_id"], user_id))
            db.conn.commit()
            return {"ok": True, **estado_pedido(cur, c)}
        u = _usuario_habilitado(cur, user_id)
        perfil = c.get("perfil") or {}
        falta = _publicable(perfil)
        if falta:
            raise RedError("perfil_incompleto", f"Antes de compartirlo: {falta}")
        crit, texto = criterios_desde_perfil(perfil), texto_desde_perfil(perfil)
        presupuesto = perfil.get("presupuesto_max") or perfil.get("presupuesto_min")
        pid = c.get("pedido_id")
        existe = pid and scalar(cur, "SELECT 1 FROM pedidos WHERE id = %s AND user_id = %s", (pid, user_id))
        if existe:
            cur.execute("""
                UPDATE pedidos SET texto_pedido = %s, mensaje_completo = %s, criterios = %s, criterios_at = NOW(),
                       presupuesto_estimado = %s, agente_telefono = %s, agente_nombre = %s, estado = 'procesado',
                       fecha_captura = CASE WHEN estado = 'retirado' THEN NOW() ELSE fecha_captura END
                WHERE id = %s
            """, (texto, texto, json.dumps(crit), presupuesto, u["telefono"], u.get("nombre"), pid))
        else:
            pid = scalar(cur, """
                INSERT INTO pedidos (grupo_id, agente_telefono, agente_nombre, texto_pedido, mensaje_completo,
                                     procesado, estado, presupuesto_estimado, canal, criterios, criterios_at, user_id)
                VALUES ('fynder', %s, %s, %s, %s, TRUE, 'procesado', %s, %s, %s, NOW(), %s) RETURNING id
            """, (u["telefono"], u.get("nombre"), texto, texto, presupuesto, CANALES.get(canal, "fynder_web"),
                  json.dumps(crit), user_id))
            cur.execute("UPDATE clientes_agente SET pedido_id = %s WHERE id = %s", (pid, cliente_id))
        db.conn.commit()
        c["pedido_id"] = pid
        return {"ok": True, "texto": texto, **estado_pedido(cur, c)}


def sincronizar(user_id: int, cliente_id: int) -> None:
    """Si el pedido del cliente está en la red, lo actualiza con el perfil nuevo. Nunca lanza."""
    try:
        with get_db() as db:
            c = fetch_one(db.cursor, "SELECT pedido_id, perfil, estado FROM clientes_agente WHERE id = %s AND user_id = %s",
                          (cliente_id, user_id))
        if not c or not c.get("pedido_id"):
            return
        with get_db() as db:
            vivo = scalar(db.cursor, "SELECT 1 FROM pedidos WHERE id = %s AND estado <> 'retirado'", (c["pedido_id"],))
        if not vivo:
            return
        if c.get("estado") == "cerrado" or _publicable(c.get("perfil") or {}):
            compartir_pedido(user_id, cliente_id, activo=False)
        else:
            compartir_pedido(user_id, cliente_id, activo=True)
    except Exception as e:  # noqa: BLE001
        print(f"[RED] No se pudo sincronizar el pedido del cliente {cliente_id}: {e}")
