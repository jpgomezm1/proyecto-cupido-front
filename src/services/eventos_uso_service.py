"""
Eventos de uso de la interfaz del agente guardados en la base de Fynder (tabla
`eventos_uso`, migración 054). Son los mismos que van a PostHog; aquí sirven
para el tablero del admin sin depender de una llave de lectura de PostHog.

Solo nombres conocidos, propiedades cortas (sin datos personales) y como máximo
30 por envío. Nunca lanza: medir no puede romper la app.
"""

import json
from typing import Any, Dict, List

from src.services.db import get_db

EVENTOS = {
    "pagina_vista", "findy_busqueda", "inmueble_abierto", "contacto_vista_previa", "contacto_abierto",
    "contacto_no_abierto", "guardado", "cliente_creado", "inmueble_publicado", "pago_iniciado",
    # Del servidor (oct-2026): los pasos del embudo que la interfaz no ve completos.
    "cuenta_creada", "celular_verificado",
}
# De dónde llegó una cuenta nueva (?desde= en el registro).
ORIGENES_REGISTRO = {"compartido", "landing", "pagina_agente", "informe", "instagram"}
_MAX_LOTE = 30


def _props(p: Any) -> Dict[str, Any]:
    if not isinstance(p, dict):
        return {}
    limpio = {}
    for k, v in list(p.items())[:10]:
        if isinstance(v, bool) or isinstance(v, (int, float)):
            limpio[str(k)[:40]] = v
        elif isinstance(v, str):
            limpio[str(k)[:40]] = v[:80]
    return limpio


def registrar(user_id: int, eventos: List[Dict[str, Any]]) -> int:
    filas = []
    for e in (eventos or [])[:_MAX_LOTE]:
        if not isinstance(e, dict) or e.get("evento") not in EVENTOS:
            continue
        ruta = str(e.get("ruta") or "")[:120] or None
        filas.append((user_id, e["evento"], ruta, json.dumps(_props(e.get("props")))))
    if not filas:
        return 0
    try:
        with get_db() as db:
            db.cursor.executemany(
                "INSERT INTO eventos_uso (user_id, evento, ruta, props) VALUES (%s, %s, %s, %s)", filas)
            db.conn.commit()
    except Exception as e:  # noqa: BLE001 — sin la migración 054 no se rompe nada
        print(f"[eventos_uso] no se pudieron guardar: {e}")
        return 0
    return len(filas)


def registrar_uno(user_id: int, evento: str, props: Dict[str, Any] = None) -> None:
    """Un evento del servidor (cuenta creada, celular verificado). Nunca lanza."""
    registrar(user_id, [{"evento": evento, "props": props or {}}])
