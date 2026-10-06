"""
Seguimiento de los contactos desbloqueados (módulo Contactos): en qué va el
negocio con cada contacto, una nota y un recordatorio para volver a escribirle.
Solo el agente que desbloqueó el contacto puede verlo o cambiarlo.
"""
from datetime import date
from typing import Any, Dict, Optional

from src.services.db import fetch_one, get_db

ESTADOS = ("por_contactar", "contactado", "visita", "negociando", "cerrado", "descartado")
NOTA_MAX = 2000

_NO_DADO = object()


def _error(codigo: str, mensaje: str) -> Dict[str, Any]:
    return {"ok": False, "error": codigo, "mensaje": mensaje}


def salida(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Seguimiento listo para la API (sin registro = por contactar)."""
    if not row or not row.get("seg_estado"):
        return {"estado": "por_contactar", "nota": None, "recordatorio": None, "actualizado": None}
    return {
        "estado": row["seg_estado"],
        "nota": row.get("seg_nota"),
        "recordatorio": row["seg_recordatorio"].isoformat() if row.get("seg_recordatorio") else None,
        "actualizado": row["seg_updated_at"].isoformat() if row.get("seg_updated_at") else None,
    }


def validar(estado: Any = _NO_DADO, nota: Any = _NO_DADO, recordatorio: Any = _NO_DADO) -> Dict[str, Any]:
    """Valida los cambios; devuelve {campo: valor} o {"error": mensaje}."""
    sets: Dict[str, Any] = {}
    if estado is not _NO_DADO:
        if estado not in ESTADOS:
            return {"error": f"Estado inválido. Usa uno de: {', '.join(ESTADOS)}."}
        sets["estado"] = estado
    if nota is not _NO_DADO:
        texto = (nota or "").strip() if isinstance(nota, str) or nota is None else None
        if texto is None:
            return {"error": "La nota debe ser texto."}
        if len(texto) > NOTA_MAX:
            return {"error": f"La nota puede tener máximo {NOTA_MAX} caracteres."}
        sets["nota"] = texto or None
    if recordatorio is not _NO_DADO:
        if recordatorio in (None, ""):
            sets["recordatorio"] = None
        else:
            try:
                sets["recordatorio"] = date.fromisoformat(str(recordatorio)[:10])
            except ValueError:
                return {"error": "La fecha del recordatorio no es válida (AAAA-MM-DD)."}
    if not sets:
        return {"error": "No hay cambios."}
    return sets


def actualizar(user_id: int, desbloqueo_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    cambios = validar(**{k: data[k] for k in ("estado", "nota", "recordatorio") if k in data})
    if "error" in cambios:
        return _error("invalido", cambios["error"])
    with get_db() as db:
        cur = db.cursor
        d = fetch_one(cur, "SELECT id FROM desbloqueos WHERE id = %s AND user_id = %s", (desbloqueo_id, user_id))
        if not d:
            return _error("no_encontrado", "No encontré ese contacto.")
        cols = list(cambios.keys())
        sets_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
        if "estado" in cambios:
            sets_sql += ", estado_at = NOW()"
        cur.execute(
            f"""
            INSERT INTO contacto_seguimiento (desbloqueo_id, user_id, {", ".join(cols)})
            VALUES (%s, %s, {", ".join(["%s"] * len(cols))})
            ON CONFLICT (desbloqueo_id) DO UPDATE SET {sets_sql}, updated_at = NOW()
            RETURNING estado AS seg_estado, nota AS seg_nota, recordatorio AS seg_recordatorio,
                      updated_at AS seg_updated_at
            """,
            (desbloqueo_id, user_id, *[cambios[c] for c in cols]),
        )
        row = cur.fetchone()
        db.conn.commit()
    return {"ok": True, "desbloqueo_id": desbloqueo_id, "seguimiento": salida(dict(row))}
