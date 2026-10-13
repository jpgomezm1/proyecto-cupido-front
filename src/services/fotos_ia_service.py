"""
Mejorar fotos de un inmueble con IA (OpenAI, modelo de imágenes configurable).

La edición corrige luz, color, nitidez y verticales, sin inventar ni quitar nada
del inmueble: un comprador que va a la visita tiene que encontrar lo mismo que vio.
El agente ve la foto mejorada al lado de la original y decide si la reemplaza.

Cupo (cada foto le cuesta a Fynder ~USD 0,10–0,13; migración 056):
  - plan: `planes.fotos_ia` fotos por periodo pagado (copiado en
    `suscripciones.fotos_ia_incluidas` al activarlo);
  - prueba: sin plan, el cupo de `planes.fotos_ia` del plan 'prueba', una sola vez;
  - extra: paquetes de fotos comprados (`fotos_ia_movimientos`), no vencen.
Se gasta primero el del plan (o la prueba) y luego el extra. La foto se reserva
antes de llamar a la IA (dos clics a la vez no se saltan el cupo) y, si la IA
falla, no se descuenta. Tope diario anti-abuso: FYNDER_FOTOS_IA_DIA (40).
Solo sobre inmuebles que el agente captó (celular verificado).
"""

import base64
import os
import time
from typing import Any, Dict, Optional

import requests

from src.services import mis_propiedades_service as mp
from src.services import suscripcion_service
from src.services.db import fetch_one, get_db, scalar

MODELO = os.getenv("FYNDER_MODELO_FOTOS", "gpt-image-1")
CALIDAD = os.getenv("FYNDER_FOTOS_IA_CALIDAD", "medium")
LIMITE_DIA = int(os.getenv("FYNDER_FOTOS_IA_DIA", "40"))
_LOCK_FOTOS = 7102

# Una foto cuenta si salió bien o si está en curso (reservada hace menos de 10 min).
_CUENTA = "(url_mejorada IS NOT NULL OR (error IS NULL AND created_at > NOW() - INTERVAL '10 minutes'))"

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


def _cupo(cur, user_id: int) -> Dict[str, Any]:
    periodo = suscripcion_service._periodo_vigente(cur, user_id)
    if periodo:
        incluidas = periodo.get("fotos_ia_incluidas")
        if incluidas is None:
            incluidas = scalar(cur, "SELECT fotos_ia FROM planes WHERE codigo = %s", (periodo["plan_codigo"],))
        usadas = scalar(cur, f"""
            SELECT COUNT(*) FROM fotos_mejoradas
            WHERE user_id = %s AND fuente = 'plan' AND created_at >= %s AND {_CUENTA}
        """, (user_id, periodo["inicio"]))
        fuente, renueva = "plan", periodo["fin"]
    else:
        incluidas = scalar(cur, "SELECT fotos_ia FROM planes WHERE codigo = 'prueba'")
        usadas = scalar(cur, f"""
            SELECT COUNT(*) FROM fotos_mejoradas WHERE user_id = %s AND fuente = 'prueba' AND {_CUENTA}
        """, (user_id,))
        fuente, renueva = "prueba", None
    compradas = scalar(cur, "SELECT COALESCE(SUM(cantidad), 0) FROM fotos_ia_movimientos WHERE user_id = %s",
                       (user_id,)) or 0
    gastadas = scalar(cur, f"""
        SELECT COUNT(*) FROM fotos_mejoradas WHERE user_id = %s AND fuente = 'extra' AND {_CUENTA}
    """, (user_id,)) or 0
    hoy = scalar(cur, f"""
        SELECT COUNT(*) FROM fotos_mejoradas
        WHERE user_id = %s AND {_CUENTA}
          AND created_at >= date_trunc('day', NOW() AT TIME ZONE 'America/Bogota') AT TIME ZONE 'America/Bogota'
    """, (user_id,)) or 0
    incluidas, usadas = int(incluidas or 0), int(usadas or 0)
    del_plan = max(0, incluidas - usadas)
    extra = max(0, int(compradas) - int(gastadas))
    return {
        "fuente": fuente,                 # 'plan' o 'prueba': de dónde sale la próxima antes del extra
        "con_plan": fuente == "plan",
        "total": incluidas,               # del plan este periodo (o de la prueba)
        "usadas": usadas,
        "del_plan": del_plan,
        "extra": extra,                   # compradas, sin vencimiento
        "restantes": del_plan + extra,
        "renueva": renueva.isoformat() if renueva else None,
        "hoy": int(hoy),
        "limite_dia": LIMITE_DIA,
    }


def cupo(user_id: int) -> Dict[str, Any]:
    with get_db() as db:
        return _cupo(db.cursor, user_id)


def _sin_cupo(c: Dict[str, Any]) -> FotoError:
    if c["con_plan"]:
        msg = (f"Ya usaste las {c['total']} fotos con IA de tu plan en este periodo. "
               "Compra un paquete de fotos para seguir; tu cupo se renueva con el plan.")
    else:
        msg = (f"Ya usaste tus {c['total']} fotos con IA de prueba. "
               "Activa un plan (trae fotos cada mes) o compra un paquete de fotos.")
    return FotoError("sin_cupo", msg, 402)


def _reservar(user_id: int, propiedad_id: int, url: str) -> Dict[str, Any]:
    """Toma una foto del cupo (bajo lock por agente) y deja la fila 'en curso'."""
    with get_db() as db:
        cur = db.cursor
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK_FOTOS, user_id))
        c = _cupo(cur, user_id)
        if c["hoy"] >= LIMITE_DIA:
            db.conn.rollback()
            raise FotoError("limite_dia", f"Llegaste al máximo de {LIMITE_DIA} fotos con IA por día. "
                            "Sigue mañana; tu cupo no se pierde.", 429)
        fuente = c["fuente"] if c["del_plan"] > 0 else "extra" if c["extra"] > 0 else None
        if not fuente:
            db.conn.rollback()
            raise _sin_cupo(c)
        fid = scalar(cur, """
            INSERT INTO fotos_mejoradas (user_id, propiedad_id, url_original, modelo, fuente)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (user_id, propiedad_id, url, MODELO, fuente))
        db.conn.commit()
    return {"id": fid, "fuente": fuente}


def _fallo(fid: int, error: str) -> None:
    """La foto no salió: se libera del cupo."""
    with get_db() as db:
        db.cursor.execute("UPDATE fotos_mejoradas SET error = %s WHERE id = %s", (error[:500], fid))
        db.conn.commit()


def abonar_en(cur, user_id: int, plan_codigo: str, referencia: str, admin: Optional[str] = None) -> Dict[str, Any]:
    """Suma un paquete de fotos comprado (no vence). Dentro de la transacción del caller."""
    plan = fetch_one(cur, "SELECT * FROM planes WHERE codigo = %s", (plan_codigo,))
    if not plan or plan.get("tipo") != "fotos" or not plan.get("fotos_ia"):
        raise FotoError("invalido", f"Paquete de fotos inválido: {plan_codigo}")
    movimiento_id = scalar(cur, """
        INSERT INTO fotos_ia_movimientos (user_id, cantidad, referencia, creado_por)
        VALUES (%s, %s, %s, %s) RETURNING id
    """, (user_id, plan["fotos_ia"], referencia, admin))
    return {"ok": True, "movimiento_id": movimiento_id, "fotos": plan["fotos_ia"]}


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
        raise _sin_cupo(c)
    if not os.getenv("OPENAI_API_KEY") or not store.storage_disponible():
        # Se revisa antes de llamar a la IA: no pagar una edición que no se podría guardar.
        raise FotoError("no_disponible", "La mejora de fotos no está disponible en este momento.", 503)

    try:
        from src.services import url_segura  # la URL de la foto la pudo poner el agente
        r = url_segura.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        original = r.content
        tipo = (r.headers.get("content-type") or "image/jpeg").split(";")[0]
    except Exception as e:  # noqa: BLE001
        raise FotoError("descarga", "No pude descargar esa foto. Intenta con otra.") from e
    ext = {"image/png": "png", "image/webp": "webp"}.get(tipo, "jpg")

    fid = _reservar(user_id, propiedad_id, url)["id"]
    t0 = time.time()
    try:
        resp = OpenAI().images.edit(model=MODELO, image=(f"foto.{ext}", original, tipo), prompt=INSTRUCCION,
                                    quality=CALIDAD, size="auto", input_fidelity="high")
        datos = base64.b64decode(resp.data[0].b64_json)
    except Exception as e:  # noqa: BLE001
        _fallo(fid, str(e))
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

    try:
        nueva = store.upload_image_bytes(datos, "image/png", prefix=f"listings/mejoradas/{propiedad_id}")
    except Exception as e:  # noqa: BLE001
        _fallo(fid, f"storage: {e}")
        raise FotoError("no_disponible", "No pude guardar la foto mejorada. No se descontó de tu cupo.", 503) from e
    with get_db() as db:
        db.cursor.execute("UPDATE fotos_mejoradas SET url_mejorada = %s WHERE id = %s", (nueva, fid))
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
