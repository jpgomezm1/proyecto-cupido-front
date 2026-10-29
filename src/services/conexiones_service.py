"""
«Te conectamos» con llave (migración 068, R20).

Cuando quien hizo un pedido no está en Fynder, su contacto no se puede abrir con llave (Ley 1581: no
autorizó que se compartiera). El agente paga 1 llave y el equipo de Fynder le escribe a quien pidió,
le pide permiso y, si acepta, le pasa el contacto al agente. Si rechaza o no responde en 48 h, la llave
vuelve sola.

  solicitar(user_id, pedido_id)      cobra la llave (un desbloqueo 'pedido' vigente, SIN contacto) y
                                     deja la conexión pendiente; avisa al equipo
  pendientes()                       Admin › Conexiones: lo que hay que atender
  resolver(id, aceptada, admin)      aceptada → el desbloqueo recibe el contacto (sale en Contactos);
                                     rechazada → vuelve la llave
  vencer()                           worker: pendientes de más de 48 h → sin_respuesta, vuelve la llave
  estados(user_id, pedido_ids)       {pedido_id: 'conectando' | 'conectado'} para la tarjeta del comprador
"""

from typing import Any, Dict, List, Optional

from src.services import suscripcion_service as sus
from src.services.db import fetch_all, fetch_one, get_db, scalar


class ConexionError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def solicitar(user_id: int, pedido_id: int) -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        u = sus._usuario(cur, user_id)
        if not u or not u.get("activo"):
            raise ConexionError("no_encontrado", "Usuario no encontrado.")
        if u.get("terminos_aceptados_at") is None:
            raise ConexionError("terminos_pendientes", "Antes de usar tu primera llave debes aceptar los términos de Fynder.")
        p = fetch_one(cur, """SELECT id, agente_telefono, agente_nombre, estado FROM pedidos WHERE id = %s""", (pedido_id,))
        if not p or p["estado"] in ("retirado", "reemplazado"):
            raise ConexionError("no_encontrado", "Ese pedido ya no está vigente.")
        tel = sus.contacto_usable(p.get("agente_telefono"))
        if not tel:
            raise ConexionError("sin_contacto", "No tenemos cómo escribirle a quien hizo ese pedido. No se cobra.")
        if sus._es_propio(u, tel[-10:]):
            raise ConexionError("propio", "Ese pedido es tuyo.")
        ya = fetch_one(cur, """SELECT d.id, d.contacto_telefono, c.estado FROM desbloqueos d
                               LEFT JOIN conexiones c ON c.desbloqueo_id = d.id
                               WHERE d.user_id = %s AND d.tipo = 'pedido' AND d.ref_id = %s AND d.estado = 'vigente'""",
                       (user_id, pedido_id))
        if ya:
            return {"ok": True, "ya": True, "estado": "conectado" if ya["contacto_telefono"] else "conectando"}

        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (sus._LOCK_COBRO, user_id))
        s = sus._saldos(cur, user_id)
        if s["plan_disponibles"] > 0:
            fuente, suscripcion_id = "plan", s["periodo"]["id"]
        elif s["saldo"] > 0:
            fuente, suscripcion_id = "saldo", None
        else:
            db.conn.rollback()
            raise ConexionError("sin_creditos", "No te quedan llaves. Recarga en Mi cuenta › Plan.")
        # La llave se gasta como cualquier contacto, todavía sin el contacto (llega cuando acepte).
        d = fetch_one(cur, """
            INSERT INTO desbloqueos (user_id, tipo, ref_id, fuente_credito, suscripcion_id, canal)
            VALUES (%s, 'pedido', %s, %s, %s, 'conectar')
            ON CONFLICT (user_id, tipo, ref_id) DO UPDATE SET
                estado = 'vigente', fuente_credito = EXCLUDED.fuente_credito, suscripcion_id = EXCLUDED.suscripcion_id,
                contacto_telefono = NULL, contacto_nombre = NULL, canal = 'conectar', created_at = NOW()
            WHERE desbloqueos.estado = 'reembolsado'
            RETURNING id
        """, (user_id, pedido_id, fuente, suscripcion_id))
        if not d:
            db.conn.rollback()
            return {"ok": True, "ya": True, "estado": "conectando"}
        cur.execute("DELETE FROM conexiones WHERE desbloqueo_id = %s", (d["id"],))   # una devuelta antes
        cid = scalar(cur, "INSERT INTO conexiones (desbloqueo_id, user_id, pedido_id) VALUES (%s, %s, %s) RETURNING id",
                     (d["id"], user_id, pedido_id))
        db.conn.commit()
        disponibles = sus._saldos(cur, user_id)["disponibles"]
    _avisar_equipo(cid, u, pedido_id)
    return {"ok": True, "conexion_id": cid, "estado": "conectando", "disponibles": disponibles,
            "mensaje": "Listo: le pedimos permiso a quien hizo el pedido. Te avisamos en máximo 48 horas; "
                       "si no responde, te devolvemos la llave."}


def _avisar_equipo(cid: int, u: Dict[str, Any], pedido_id: int) -> None:
    from src.services import correo_service   # aquí: el MCP importa este módulo y no trae la librería de correo
    try:
        correo_service.enviar(correo_service.buzon_soporte(), f"Conexión #{cid}: {u.get('nombre') or 'Un agente'} quiere el pedido #{pedido_id}",
                              f"<p>{u.get('nombre')} pagó 1 llave por el pedido #{pedido_id}. Pídele permiso a quien lo hizo "
                              f"y resuélvelo en Admin › Conexiones antes de 48 h.</p>",
                              f"Conexión #{cid}: pedido #{pedido_id}. Resuélvela en Admin › Conexiones antes de 48 h.",
                              "conexion_nueva")
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ aviso conexión {cid}: {e}")


def pendientes() -> List[Dict[str, Any]]:
    with get_db() as db:
        return fetch_all(db.cursor, """
            SELECT c.id, c.estado, c.created_at, c.vence_at, c.pedido_id,
                   u.id AS agente_id, u.nombre AS agente_nombre, u.telefono AS agente_telefono,
                   pe.agente_nombre AS pide_nombre, pe.agente_telefono AS pide_telefono, pe.texto_pedido
            FROM conexiones c
            JOIN chat_users u ON u.id = c.user_id
            JOIN pedidos pe ON pe.id = c.pedido_id
            WHERE c.estado = 'pendiente'
            ORDER BY c.vence_at
        """)


def _cerrar(cur, c: Dict[str, Any], estado: str, admin: Optional[str], nota: Optional[str]) -> None:
    cur.execute("""UPDATE conexiones SET estado = %s, resuelta_at = NOW(), resuelta_por = %s, nota = %s
                   WHERE id = %s""", (estado, admin, nota, c["id"]))
    if estado == "aceptada":
        cur.execute("""UPDATE desbloqueos d SET contacto_telefono = pe.agente_telefono, contacto_nombre = pe.agente_nombre
                       FROM pedidos pe WHERE d.id = %s AND pe.id = %s""", (c["desbloqueo_id"], c["pedido_id"]))
    else:
        cur.execute("UPDATE desbloqueos SET estado = 'reembolsado' WHERE id = %s", (c["desbloqueo_id"],))


def _avisar_agente(cur, c: Dict[str, Any], estado: str) -> None:
    from src.services import correo_service
    u = fetch_one(cur, "SELECT nombre, email FROM chat_users WHERE id = %s", (c["user_id"],))
    if not u or not u.get("email"):
        return
    if estado == "aceptada":
        asunto = "Te conectamos: ya tienes el contacto"
        cuerpo = "Quien hizo el pedido aceptó hablar contigo. Su contacto ya está en Clientes › Contactos."
    else:
        asunto = "No pudimos conectarte: te devolvimos la llave"
        cuerpo = ("Quien hizo el pedido no aceptó" if estado == "rechazada" else "Quien hizo el pedido no respondió en 48 horas") + \
                 ", así que te devolvimos la llave."
    try:
        correo_service.enviar(u["email"], asunto, f"<p>{cuerpo}</p>", cuerpo, f"conexion_{estado}")
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ aviso al agente, conexión {c['id']}: {e}")


def resolver(conexion_id: int, aceptada: bool, admin: Optional[str] = None, nota: Optional[str] = None) -> Dict[str, Any]:
    estado = "aceptada" if aceptada else "rechazada"
    with get_db() as db:
        cur = db.cursor
        c = fetch_one(cur, "SELECT * FROM conexiones WHERE id = %s FOR UPDATE", (conexion_id,))
        if not c:
            raise ConexionError("no_encontrado", "Esa conexión no existe.")
        if c["estado"] != "pendiente":
            raise ConexionError("resuelta", f"Esa conexión ya quedó {c['estado']}.")
        _cerrar(cur, c, estado, admin, nota)
        db.conn.commit()
        _avisar_agente(cur, c, estado)
    return {"ok": True, "estado": estado}


def vencer() -> Dict[str, int]:
    """Worker: lo pendiente de más de 48 h queda sin_respuesta y la llave vuelve."""
    n = 0
    with get_db() as db:
        cur = db.cursor
        for c in fetch_all(cur, "SELECT * FROM conexiones WHERE estado = 'pendiente' AND vence_at < NOW() FOR UPDATE SKIP LOCKED"):
            _cerrar(cur, c, "sin_respuesta", "worker", None)
            db.conn.commit()
            _avisar_agente(cur, c, "sin_respuesta")
            n += 1
    return {"vencidas": n}


def estados(user_id: int, pedido_ids: List[int]) -> Dict[int, str]:
    ids = [int(i) for i in pedido_ids if i is not None]
    if not ids:
        return {}
    with get_db() as db:
        filas = fetch_all(db.cursor, """
            SELECT d.ref_id, d.contacto_telefono FROM desbloqueos d JOIN conexiones c ON c.desbloqueo_id = d.id
            WHERE d.user_id = %s AND d.tipo = 'pedido' AND d.estado = 'vigente' AND d.ref_id = ANY(%s)
        """, (user_id, ids))
    return {f["ref_id"]: ("conectado" if f["contacto_telefono"] else "conectando") for f in filas}
