"""
El modo Análisis de Findy en el chat web (migración 062, `findy_analisis`).

  GET  /api/analisis/cupo                       → el medidor: cuántos análisis quedan
  POST /api/analisis/conversaciones/<id>        → {"content": "..."}; responde en streaming (SSE)

El streaming manda eventos `data: {json}`: `estado` (qué herramienta usa), `texto`
(la respuesta a medida que llega), `fin` (el mensaje guardado y el cupo nuevo) o
`error`. El análisis se reserva del cupo antes de llamar a la IA y, si falla, no se
descuenta. Interruptor: FYNDER_ANALISIS=1 (apagado responde 404).
"""

import json
import os
import traceback

from flask import Blueprint, Response, jsonify, request, stream_with_context

from src.api.chat_auth import require_chat_auth
from src.services import analisis_service as cupos
from src.services import findy_analisis
from src.services.db import fetch_all, fetch_one, get_db

analisis_bp = Blueprint("analisis", __name__, url_prefix="/api/analisis")


def _activo() -> bool:
    return os.getenv("FYNDER_ANALISIS", "0").lower() in ("1", "true", "si", "sí")


def _sse(evento: dict) -> str:
    return f"data: {json.dumps(evento, ensure_ascii=False, default=str)}\n\n"


@analisis_bp.route("/cupo", methods=["GET"])
@require_chat_auth
def cupo():
    if not _activo():
        return jsonify({"success": False, "error": "no_disponible"}), 404
    return jsonify({"success": True, "data": cupos.cupo(request.chat_user["id"])})


@analisis_bp.route("/conversaciones/<int:conversation_id>", methods=["POST"])
@require_chat_auth
def analizar(conversation_id):
    if not _activo():
        return jsonify({"success": False, "error": "no_disponible"}), 404
    pregunta = ((request.get_json(silent=True) or {}).get("content") or "").strip()
    if not pregunta:
        return jsonify({"success": False, "error": "El mensaje no puede estar vacío"}), 400
    if len(pregunta) > 2000:
        return jsonify({"success": False, "error": "La pregunta es muy larga (máximo 2.000 caracteres)."}), 400
    user = dict(request.chat_user)

    with get_db() as db:
        conv = fetch_one(db.cursor, """
            SELECT id, nombre FROM conversaciones_busqueda WHERE id = %s AND activa = TRUE AND user_id = %s
        """, (conversation_id, user["id"]))
        if not conv:
            return jsonify({"success": False, "error": "Conversación no encontrada"}), 404
        historial = fetch_all(db.cursor, """
            SELECT role, content FROM mensajes_conversacion
            WHERE conversacion_id = %s ORDER BY fecha_creacion DESC LIMIT 6
        """, (conversation_id,))[::-1]

    try:
        reserva = cupos.reservar(user["id"], conversation_id, pregunta, findy_analisis.MODELO)
    except cupos.AnalisisError as e:
        return jsonify({"success": False, "code": e.codigo, "error": e.mensaje, "cupo": cupos.cupo(user["id"])}), e.status

    def eventos():
        yield _sse({"tipo": "estado", "texto": "Pensando…"})
        fin = None
        try:
            for ev in findy_analisis.analizar(user, pregunta, historial):
                if ev["tipo"] == "fin":
                    fin = ev
                else:
                    yield _sse(ev)
            if not fin or not fin["contenido"]:
                raise RuntimeError("respuesta vacía")
        except Exception as e:  # noqa: BLE001 — se libera el cupo y se avisa al agente
            traceback.print_exc()
            cupos.fallo(reserva["id"], f"{type(e).__name__}: {e}", (fin or {}).get("uso", {}).get("costo_usd"))
            yield _sse({"tipo": "error", "error": "Findy no pudo terminar el análisis. No se descontó de tu cupo; "
                                                  "intenta de nuevo en un momento."})
            return

        uso = fin["uso"]
        cupos.terminar(reserva["id"], fin["herramientas"], uso["entrada"], uso["salida"],
                       uso["cache_lectura"] + uso["cache_escritura"], uso["costo_usd"])
        respuesta = {"modo": "analisis", "analisis_id": reserva["id"], "herramientas": fin["herramientas"],
                     "criteria": {}, "results": [], "total_found": 0, "elapsed_ms": uso["ms"]}
        with get_db() as db:
            cur = db.cursor
            u = fetch_one(cur, """
                INSERT INTO mensajes_conversacion (conversacion_id, role, content) VALUES (%s, 'user', %s)
                RETURNING id, fecha_creacion
            """, (conversation_id, pregunta))
            a = fetch_one(cur, """
                INSERT INTO mensajes_conversacion (conversacion_id, role, content, total_resultados,
                                                   tiempo_respuesta_ms, search_response)
                VALUES (%s, 'assistant', %s, 0, %s, %s) RETURNING id, fecha_creacion
            """, (conversation_id, fin["contenido"], uso["ms"], json.dumps(respuesta)))
            if conv["nombre"] in (None, "", "Nueva Conversación"):
                cur.execute("UPDATE conversaciones_busqueda SET nombre = %s WHERE id = %s",
                            (pregunta[:60], conversation_id))
            cur.execute("UPDATE conversaciones_busqueda SET fecha_actualizacion = NOW() WHERE id = %s",
                        (conversation_id,))
            db.conn.commit()
        yield _sse({
            "tipo": "fin",
            "user_message": {"id": u["id"], "role": "user", "content": pregunta,
                             "fecha_creacion": u["fecha_creacion"].isoformat()},
            "assistant_message": {"id": a["id"], "role": "assistant", "content": fin["contenido"],
                                  "fecha_creacion": a["fecha_creacion"].isoformat(), "search_response": respuesta},
            "cupo": cupos.cupo(user["id"]),
        })

    return Response(stream_with_context(eventos()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
