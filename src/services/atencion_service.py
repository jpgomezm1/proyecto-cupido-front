"""
«Qué necesita atención hoy» (portada del admin): lo pendiente de todas las pantallas en una
sola lista, con el número y a dónde ir. Solo lectura, sin IA. Cada revisión es independiente:
si una falla (p. ej. falta una tabla), las demás salen igual.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from src.services.db import get_db, scalar

BOGOTA = timezone(timedelta(hours=-5))


def _item(clave: str, titulo: str, n: int, detalle: str, url: str, tono: str = "atencion") -> Dict[str, Any]:
    return {"clave": clave, "titulo": titulo, "n": n, "detalle": detalle, "url": url, "tono": tono}


def _pagos(cur) -> Optional[Dict[str, Any]]:
    n = scalar(cur, "SELECT COUNT(*) FROM pagos WHERE estado = 'pendiente' AND created_at < NOW() - INTERVAL '1 hour'") or 0
    return _item("pagos", "Pagos pendientes", n, "Llevan más de una hora sin confirmarse en Wompi.", "/admin/pagos") if n else None


def _renovaciones(cur) -> Optional[Dict[str, Any]]:
    n = scalar(cur, """
        SELECT COUNT(*) FROM suscripciones s
        WHERE s.estado = 'activa' AND s.plan_codigo <> 'prueba'
          AND ((s.fin BETWEEN NOW() AND NOW() + INTERVAL '7 days') OR (s.fin <= NOW() AND COALESCE(s.gracia_hasta, s.fin) > NOW()))
          AND NOT EXISTS (SELECT 1 FROM suscripciones s2 WHERE s2.user_id = s.user_id AND s2.inicio > s.inicio)
    """) or 0
    return _item("renovaciones", "Planes por vencer o en gracia", n, "Escríbeles antes de que se pierdan.",
                 "/admin/crecimiento") if n else None


def _reportes(cur) -> Optional[Dict[str, Any]]:
    n = scalar(cur, "SELECT COUNT(*) FROM reportes_contacto WHERE resuelto_at IS NULL") or 0
    return _item("reportes", "Contactos reportados sin resolver", n, "Un agente dice que un contacto no sirve.",
                 "/admin/contactos", "mal") if n else None


def _soporte(cur) -> Optional[Dict[str, Any]]:
    n = scalar(cur, "SELECT COUNT(*) FROM soporte_solicitudes WHERE COALESCE(estado, 'abierta') NOT IN ('resuelta', 'resuelto', 'cerrada', 'cerrado')") or 0
    return _item("soporte", "Soporte sin responder", n, "Solicitudes de agentes abiertas.", "/admin/soporte", "mal") if n else None


def _feedback(cur) -> Optional[Dict[str, Any]]:
    n = scalar(cur, "SELECT COUNT(*) FROM feedback WHERE estado = 'nuevo'") or 0
    return _item("feedback", "Feedback nuevo", n, "Sin revisar.", "/admin/feedback", "info") if n else None


def _visitas(cur) -> Optional[Dict[str, Any]]:
    n = scalar(cur, """
        SELECT COUNT(*) FROM interacciones
        WHERE COALESCE(activa, TRUE) AND fecha_seleccion > NOW() - INTERVAL '30 days'
    """) or 0
    return _item("visitas", "Visitas por coordinar", n, "El equipo de Fynder coordina por el agente.", "/admin/visitas") if n else None


def _vitrina(cur) -> Optional[Dict[str, Any]]:
    n = scalar(cur, "SELECT COUNT(*) FROM vitrina_candidatos WHERE estado = 'pendiente'") or 0
    # Se publica los lunes: solo apremia de viernes a lunes.
    dia = datetime.now(BOGOTA).weekday()
    if not n or dia not in (4, 5, 6, 0):
        return None
    return _item("vitrina", "Vitrina por aprobar", n, "Candidatos para la Vitrina del lunes.", "/admin/vitrina", "info")


def _captura(cur) -> Optional[Dict[str, Any]]:
    ultima = scalar(cur, "SELECT MAX(fecha_evento) FROM eventos_log WHERE tipo_evento = 'Propiedad_Captada'")
    if not ultima:
        return _item("captura", "La captura no ha registrado inmuebles", 0, "Revisa UltraMSG, el webhook y el worker.",
                     "/admin/salud", "mal")
    horas = (datetime.utcnow() - ultima).total_seconds() / 3600  # fecha_evento: UTC sin zona
    # Como la alarma del worker (captura_salud): de lunes a sábado de 8 a 20 avisa a las 6 h;
    # de noche y el domingo es normal que no entre nada, así que solo pasadas 14 h.
    local = datetime.now(BOGOTA)
    en_horario = local.weekday() < 6 and 8 <= local.hour < 20
    if horas < (6 if en_horario else 14):
        return None
    return _item("captura", f"Sin capturas hace {horas:.0f} h", round(horas),
                 "No entra inventario de los grupos. Revisa UltraMSG, el webhook y el worker.", "/admin/salud", "mal")


def _frescura(cur) -> Optional[Dict[str, Any]]:
    total = scalar(cur, "SELECT COUNT(*) FROM propiedades WHERE activa") or 0
    viejos = scalar(cur, """
        SELECT COUNT(*) FROM propiedades
        WHERE activa AND (fecha_ultima_validacion IS NULL OR fecha_ultima_validacion < NOW() - INTERVAL '8 days')
    """) or 0
    if not total or viejos / total < 0.1:
        return None
    return _item("frescura", "Inventario sin verificar", viejos,
                 f"{round(viejos / total * 100)} % de los activos lleva más de 8 días sin verificarse.", "/admin/verificacion")


REVISIONES: List[Callable] = [_captura, _reportes, _soporte, _pagos, _renovaciones, _visitas, _frescura, _vitrina, _feedback]


def hoy() -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    errores: List[str] = []
    with get_db() as db:
        for revisar in REVISIONES:
            try:
                r = revisar(db.cursor)
                if r:
                    items.append(r)
            except Exception as e:  # noqa: BLE001 — una revisión rota no tumba las demás
                db.conn.rollback()
                errores.append(f"{revisar.__name__.strip('_')}: {str(e)[:120]}")
    orden = {"mal": 0, "atencion": 1, "info": 2}
    items.sort(key=lambda i: orden.get(i["tono"], 3))
    return {"items": items, "errores": errores}
