"""
Mejorar fotos de un inmueble con IA (OpenAI, modelo de imágenes configurable).

La edición corrige luz, color, nitidez y verticales, sin inventar ni quitar nada
del inmueble: un comprador que va a la visita tiene que encontrar lo mismo que vio.
El agente ve la foto mejorada al lado de la original y decide si la reemplaza.

Cupo mensual por agente (cada foto le cuesta a Fynder unos centavos de dólar):
FYNDER_FOTOS_IA_PLAN con plan activo (20) y FYNDER_FOTOS_IA_PRUEBA sin plan (3).
Solo sobre inmuebles que el agente captó (celular verificado).
"""

import base64
import os
import time
from typing import Any, Dict

import requests

from src.services import mis_propiedades_service as mp
from src.services.db import fetch_one, get_db, scalar

MODELO = os.getenv("FYNDER_MODELO_FOTOS", "gpt-image-1")
CALIDAD = os.getenv("FYNDER_FOTOS_IA_CALIDAD", "medium")
CUPO_PLAN = int(os.getenv("FYNDER_FOTOS_IA_PLAN", "20"))
CUPO_PRUEBA = int(os.getenv("FYNDER_FOTOS_IA_PRUEBA", "3"))

INSTRUCCION = (
    "Mejora esta fotografía inmobiliaria como lo haría un fotógrafo profesional de bienes raíces: "
    "corrige la exposición y el balance de blancos, recupera las sombras y las ventanas quemadas, "
    "endereza las líneas verticales y aumenta la nitidez. "
    "Conserva el color real de cada mueble, tela, piso y pared: aclara la escena con la luz, "
    "no cambiando los colores de los objetos (un sofá gris oscuro sigue siendo gris oscuro). "
    "NO agregues, quites, muevas ni cambies ningún objeto, mueble, material, acabado, ventana o elemento "
    "arquitectónico; no cambies la distribución ni el tamaño aparente de los espacios; no agregues personas, "
    "texto ni marcas de agua. La foto debe seguir mostrando exactamente el mismo inmueble."
)


class FotoError(Exception):
    def __init__(self, codigo: str, mensaje: str, status: int = 400):
        super().__init__(mensaje)
        self.codigo, self.mensaje, self.status = codigo, mensaje, status


def cupo(user_id: int) -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        con_plan = bool(scalar(cur, """
            SELECT 1 FROM suscripciones WHERE user_id = %s AND estado = 'activa' AND gracia_hasta > NOW() LIMIT 1
        """, (user_id,)))
        usadas = scalar(cur, """
            SELECT COUNT(*) FROM fotos_mejoradas
            WHERE user_id = %s AND url_mejorada IS NOT NULL
              AND created_at >= date_trunc('month', NOW() AT TIME ZONE 'America/Bogota') AT TIME ZONE 'America/Bogota'
        """, (user_id,)) or 0
    total = CUPO_PLAN if con_plan else CUPO_PRUEBA
    return {"total": total, "usadas": int(usadas), "restantes": max(0, total - int(usadas)), "con_plan": con_plan}


def mejorar(user_id: int, tel10: str, propiedad_id: int, url: str) -> Dict[str, Any]:
    """Genera la versión mejorada de una foto del inmueble (no la reemplaza todavía)."""
    from openai import OpenAI
    from src.services import storage_service as store

    with get_db() as db:
        p = mp._salida(mp._cargar(db.cursor, propiedad_id, tel10))
    if url not in (p["fotos"] or []):
        raise FotoError("no_encontrada", "Esa foto no está en el inmueble.", 404)
    c = cupo(user_id)
    if c["restantes"] <= 0:
        raise FotoError("sin_cupo", f"Ya usaste tus {c['total']} fotos mejoradas de este mes."
                        + ("" if c["con_plan"] else " Con un plan tienes más."), 402)
    if not os.getenv("OPENAI_API_KEY") or not store.storage_disponible():
        # Se revisa antes de llamar a la IA: no pagar una edición que no se podría guardar.
        raise FotoError("no_disponible", "La mejora de fotos no está disponible en este momento.", 503)

    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        original = r.content
        tipo = (r.headers.get("content-type") or "image/jpeg").split(";")[0]
    except Exception as e:  # noqa: BLE001
        raise FotoError("descarga", "No pude descargar esa foto. Intenta con otra.") from e
    ext = {"image/png": "png", "image/webp": "webp"}.get(tipo, "jpg")

    t0 = time.time()
    try:
        resp = OpenAI().images.edit(model=MODELO, image=(f"foto.{ext}", original, tipo), prompt=INSTRUCCION,
                                    quality=CALIDAD, size="auto", input_fidelity="high")
        datos = base64.b64decode(resp.data[0].b64_json)
    except Exception as e:  # noqa: BLE001
        with get_db() as db:
            db.cursor.execute("""
                INSERT INTO fotos_mejoradas (user_id, propiedad_id, url_original, modelo, error)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, propiedad_id, url, MODELO, str(e)[:500]))
            db.conn.commit()
        raise FotoError("ia", "La IA no pudo mejorar esta foto ahora. No se descontó de tu cupo.", 502) from e
    try:
        from src.core.ai_usage_tracker import get_ai_tracker
        uso = getattr(resp, "usage", None)
        get_ai_tracker().log_usage(provider="openai", model=MODELO, usage_type="image_edit",
                                   function_name="fotos_ia.mejorar",
                                   input_tokens=getattr(uso, "input_tokens", None),
                                   output_tokens=getattr(uso, "output_tokens", None),
                                   response_time_ms=int((time.time() - t0) * 1000),
                                   context={"propiedad_id": propiedad_id})
    except Exception:  # noqa: BLE001
        pass

    nueva = store.upload_image_bytes(datos, "image/png", prefix=f"listings/mejoradas/{propiedad_id}")
    with get_db() as db:
        db.cursor.execute("""
            INSERT INTO fotos_mejoradas (user_id, propiedad_id, url_original, url_mejorada, modelo)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (user_id, propiedad_id, url, nueva, MODELO))
        fid = db.cursor.fetchone()["id"]
        db.conn.commit()
    return {"id": fid, "url_original": url, "url_mejorada": nueva, "cupo": cupo(user_id)}


def aplicar(user_id: int, tel10: str, propiedad_id: int, mejora_id: int) -> Dict[str, Any]:
    """Reemplaza la foto original por la mejorada, en el mismo lugar del orden."""
    with get_db() as db:
        f = fetch_one(db.cursor, """
            SELECT * FROM fotos_mejoradas WHERE id = %s AND user_id = %s AND propiedad_id = %s AND url_mejorada IS NOT NULL
        """, (mejora_id, user_id, propiedad_id))
        if not f:
            raise FotoError("no_encontrada", "No encontré esa foto mejorada.", 404)
        p = mp._salida(mp._cargar(db.cursor, propiedad_id, tel10, bloquear=True))
        fotos = list(p["fotos"] or [])
        if f["url_original"] not in fotos:
            raise FotoError("no_encontrada", "La foto original ya no está en el inmueble.", 409)
        fotos[fotos.index(f["url_original"])] = f["url_mejorada"]
        db.cursor.execute("UPDATE fotos_mejoradas SET aplicada = TRUE WHERE id = %s", (mejora_id,))
        return mp._guardar_fotos(db, propiedad_id, tel10, fotos)
