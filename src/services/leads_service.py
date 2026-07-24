"""
Motor de asignación de leads (Bloque E del plan).

Cruza un pedido de demanda contra el inventario y puntúa cada inmueble candidato
(E1) con un índice de calidad legible (E2). Base de los matches de agentes y del
tablero B2B de constructoras (E3).

INTERRUPTOR (requisito del negocio): el motor se prende/apaga con la variable de
entorno `LEAD_ENGINE_ENABLED` (default APAGADO). Cuando está apagado,
`asignar_leads` es un no-op inmediato: no consulta la base ni gasta recursos.

TOKENS: el scoring es 100% determinístico — NO usa IA, así que no consume tokens
de Anthropic ni con el motor encendido. (Queda espacio para una capa de
explicación con IA en el futuro, que iría detrás de su propio flag.)
"""

import json
import os
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.services.db import get_db, fetch_one, fetch_all
from src.services.textutils import format_cop

_TRUE = {"1", "true", "yes", "on", "si", "sí"}


def motor_activo() -> bool:
    """True si el motor de leads está encendido (LEAD_ENGINE_ENABLED)."""
    return (os.getenv("LEAD_ENGINE_ENABLED", "false") or "").strip().lower() in _TRUE


def _norm(s: Optional[str]) -> str:
    """Minúsculas + sin acentos, para comparar texto de forma robusta."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def puntuar_lead(pedido: Dict[str, Any], prop: Dict[str, Any]) -> Dict[str, Any]:
    """
    Puntúa (0..100) qué tan bien encaja un inmueble con un pedido. Determinístico.
    Factores: presupuesto (encaje precio↔presupuesto), zona/ciudad, tipo,
    habitaciones y recencia del pedido. Devuelve score, calidad 1..10, razón y el
    desglose de factores.
    """
    texto = _norm(pedido.get("texto_pedido"))
    presupuesto = pedido.get("presupuesto_estimado")
    precio = prop.get("precio")
    f: Dict[str, int] = {}

    # 1) Encaje de presupuesto (lo más determinante).
    if presupuesto and precio:
        ratio = precio / presupuesto
        f["presupuesto"] = 40 if ratio <= 1.0 else 25 if ratio <= 1.1 else 10 if ratio <= 1.2 else 0
    else:
        f["presupuesto"] = 15  # neutral cuando no hay presupuesto declarado

    # 2) Zona (o al menos ciudad) mencionada en el texto del pedido.
    zona, ciudad = _norm(prop.get("zona")), _norm(prop.get("ciudad"))
    f["zona"] = 25 if (zona and zona in texto) else 10 if (ciudad and ciudad in texto) else 0

    # 3) Tipo de inmueble mencionado.
    tp = _norm(prop.get("tipo_propiedad"))
    f["tipo"] = 10 if (tp and tp in texto) else 0

    # 4) Habitaciones: buscar "N hab/alcoba/cuarto/dormitorio" en el texto.
    f["habitaciones"] = 0
    hab = prop.get("habitaciones")
    if hab:
        pedidos_hab = [int(x) for x in re.findall(r"(\d+)\s*(?:hab|alcoba|habitac|cuarto|dormitor)", texto)]
        if pedidos_hab:
            if hab in pedidos_hab:
                f["habitaciones"] = 15
            elif any(abs(hab - h) == 1 for h in pedidos_hab):
                f["habitaciones"] = 8

    # 5) Recencia del pedido.
    f["recencia"] = 0
    fecha = pedido.get("fecha_captura")
    if isinstance(fecha, datetime):
        dias = (datetime.now() - fecha).days
        f["recencia"] = 10 if dias <= 7 else 5 if dias <= 30 else 0

    score = max(0, min(100, sum(f.values())))
    calidad = max(1, min(10, round(score / 10)))
    return {"score": score, "calidad": calidad, "factores": f,
            "razon": _razon(f, prop, presupuesto, precio)}


def _razon(f: Dict[str, int], prop: Dict[str, Any], presupuesto, precio) -> str:
    """Explicación legible del match, en lenguaje de negocio."""
    partes: List[str] = []
    p = f.get("presupuesto", 0)
    if p >= 40:
        partes.append("dentro del presupuesto")
    elif p >= 25:
        partes.append("apenas por encima del presupuesto")
    elif p >= 10:
        partes.append("algo por encima del presupuesto")
    elif precio and presupuesto:
        partes.append("por encima del presupuesto")

    if f.get("zona") == 25:
        partes.append(f"en la zona buscada ({prop.get('zona')})")
    elif f.get("zona") == 10:
        partes.append(f"en la ciudad buscada ({prop.get('ciudad')})")
    if f.get("tipo"):
        partes.append(f"del tipo pedido ({prop.get('tipo_propiedad')})")
    if f.get("habitaciones") == 15:
        partes.append("con las habitaciones exactas")
    elif f.get("habitaciones") == 8:
        partes.append("con habitaciones cercanas")
    if f.get("recencia", 0) >= 10:
        partes.append("pedido muy reciente")

    return ("Coincide: " + ", ".join(partes) + ".") if partes else "Coincidencia débil."


def asignar_leads(pedido_id, limit: int = 10, persistir: bool = True,
                  pool: int = 300) -> Dict[str, Any]:
    """
    E1 — Dado un pedido, devuelve los N inmuebles candidatos con score y razón, y
    (por defecto) los persiste en `leads`. Corre SOLO si el motor está encendido;
    si está apagado devuelve un no-op inmediato (sin tocar la base).
    """
    if not motor_activo():
        return {"activo": False, "motivo": "motor_apagado", "pedido_id": pedido_id,
                "mensaje": "El motor de leads está apagado (LEAD_ENGINE_ENABLED). "
                           "No se consultó la base ni se gastaron recursos.",
                "candidatos": []}

    with get_db() as db:
        pedido = fetch_one(db.cursor, """
            SELECT id, texto_pedido, presupuesto_estimado, fecha_captura, agente_telefono
            FROM pedidos WHERE id = %s
        """, (pedido_id,))
        if not pedido:
            return {"activo": True, "error": f"Pedido {pedido_id} no existe", "candidatos": []}

        presupuesto = pedido.get("presupuesto_estimado")
        if presupuesto:
            rows = fetch_all(db.cursor, """
                SELECT id, codigo_propiedad, titulo, precio, zona, ciudad,
                       tipo_propiedad, habitaciones, constructora_id
                FROM propiedades
                WHERE activa = TRUE AND precio IS NOT NULL
                  AND precio BETWEEN %s AND %s
                ORDER BY id DESC LIMIT %s
            """, (int(presupuesto * 0.5), int(presupuesto * 1.2), pool))
        else:
            rows = fetch_all(db.cursor, """
                SELECT id, codigo_propiedad, titulo, precio, zona, ciudad,
                       tipo_propiedad, habitaciones, constructora_id
                FROM propiedades
                WHERE activa = TRUE AND precio IS NOT NULL
                ORDER BY fecha_creacion DESC LIMIT %s
            """, (pool,))

        puntuados = []
        for prop in rows:
            s = puntuar_lead(pedido, prop)
            if s["score"] > 0:
                puntuados.append((prop, s))
        puntuados.sort(key=lambda x: x[1]["score"], reverse=True)
        top = puntuados[:limit]

        if persistir and top:
            for prop, s in top:
                db.cursor.execute("""
                    INSERT INTO leads (pedido_id, propiedad_id, score, calidad, razon, factores,
                                       fuente, estado, constructora_id)
                    VALUES (%s, %s, %s, %s, %s, %s, 'motor', 'nuevo', %s)
                    ON CONFLICT (pedido_id, propiedad_id) DO UPDATE
                    SET score = EXCLUDED.score, calidad = EXCLUDED.calidad,
                        razon = EXCLUDED.razon, factores = EXCLUDED.factores,
                        constructora_id = EXCLUDED.constructora_id, updated_at = NOW()
                """, (pedido["id"], prop["id"], s["score"], s["calidad"], s["razon"],
                      json.dumps(s["factores"]), prop.get("constructora_id")))
            db.conn.commit()

    candidatos = [{
        "propiedad_id": prop["id"], "codigo": prop.get("codigo_propiedad"),
        "titulo": prop.get("titulo"), "precio_legible": format_cop(prop.get("precio")),
        "zona": prop.get("zona"), "ciudad": prop.get("ciudad"),
        "score": s["score"], "calidad": s["calidad"], "razon": s["razon"],
    } for prop, s in top]

    return {"activo": True, "pedido_id": pedido["id"], "total": len(candidatos),
            "candidatos": candidatos}
