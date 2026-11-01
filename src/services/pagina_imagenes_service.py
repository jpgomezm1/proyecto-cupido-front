"""
Imágenes con IA para Mi página (migración 071): el fondo de la portada, banners, texto con
imagen y galería. Las genera gpt-image-2 a partir de lo que describe el agente, con reglas
fijas (fotográfica, arquitectura e interiores de Colombia, sin texto, logos ni marcas de agua).

Cupo (cada imagen le cuesta a Fynder ~USD 0,05):
  - plan: `planes.imagenes_pagina` por periodo pagado;
  - prueba: sin plan, el cupo del plan 'prueba', una sola vez;
  - extra: canjes de Fyns y regalos (`pagina_imagenes_movimientos`), no vencen.
Se gasta primero el del plan (o la prueba) y luego el extra. La imagen se reserva bajo lock
antes de llamar a la IA y, si la IA o el guardado fallan, no se descuenta. Tope diario
anti-abuso: FYNDER_IMAGENES_PAGINA_DIA (20).

Biblioteca: `pagina_imagenes` guarda las generadas y las que sube el agente (`subida`, sin cupo)
para volver a usarlas en otro bloque.
"""

import base64
import os
import re
import time
from typing import Any, Dict, List, Optional

from src.services import suscripcion_service
from src.services.db import fetch_all, get_db, scalar

MODELO = os.getenv("FYNDER_MODELO_IMAGENES_PAGINA", os.getenv("FYNDER_MODELO_FOTOS", "gpt-image-2"))
CALIDAD = os.getenv("FYNDER_IMAGENES_PAGINA_CALIDAD", "medium")
LIMITE_DIA = int(os.getenv("FYNDER_IMAGENES_PAGINA_DIA", "20"))
_LOCK = 7104
_URL = re.compile(r"^https://[^\s]+$")

FORMATOS = {"ancha": "1536x1024", "cuadrada": "1024x1024", "vertical": "1024x1536"}
ESTILOS = {
    "natural": "luz natural de día, colores reales y cálidos",
    "atardecer": "luz dorada de atardecer, cielo cálido",
    "noche": "escena nocturna con luces cálidas encendidas, cielo azul profundo",
    "minimal": "estética minimalista y luminosa, pocos objetos, tonos claros",
    "lujo": "estética de revista de lujo, materiales nobles, iluminación cuidada",
    "tropical": "vegetación tropical abundante, verdes intensos, luz suave",
}
REGLAS = (
    "Fotografía profesional, realista y de alta calidad para la página web de un agente inmobiliario en Colombia "
    "(Medellín y el Valle de Aburrá si no se dice otra ciudad). Arquitectura, interiores, barrios o paisajes creíbles "
    "de Colombia. Composición amplia con espacio limpio para poner texto encima. "
    "Sin texto, letras, números, logos, marcas de agua ni carteles legibles. Sin personas reconocibles en primer plano."
)

# Una imagen cuenta si salió bien o si está en curso (reservada hace menos de 10 min).
_CUENTA = "(url IS NOT NULL OR (error IS NULL AND created_at > NOW() - INTERVAL '10 minutes'))"


class ImagenError(Exception):
    def __init__(self, codigo: str, mensaje: str, status: int = 400):
        super().__init__(mensaje)
        self.codigo, self.mensaje, self.status = codigo, mensaje, status


def instruccion(descripcion: str, estilo: Optional[str]) -> str:
    return f"{REGLAS}\nEscena: {descripcion.strip()}\nEstilo: {ESTILOS.get(estilo or '', ESTILOS['natural'])}."


def _cupo(cur, user_id: int) -> Dict[str, Any]:
    periodo = suscripcion_service._periodo_vigente(cur, user_id)
    if periodo:
        incluidas = scalar(cur, "SELECT imagenes_pagina FROM planes WHERE codigo = %s", (periodo["plan_codigo"],))
        usadas = scalar(cur, f"""
            SELECT COUNT(*) FROM pagina_imagenes
            WHERE user_id = %s AND fuente = 'plan' AND created_at >= %s AND {_CUENTA}
        """, (user_id, periodo["inicio"]))
        fuente, renueva = "plan", periodo["fin"]
    else:
        incluidas = scalar(cur, "SELECT imagenes_pagina FROM planes WHERE codigo = 'prueba'")
        usadas = scalar(cur, f"SELECT COUNT(*) FROM pagina_imagenes WHERE user_id = %s AND fuente = 'prueba' AND {_CUENTA}",
                        (user_id,))
        fuente, renueva = "prueba", None
    compradas = scalar(cur, "SELECT COALESCE(SUM(cantidad), 0) FROM pagina_imagenes_movimientos WHERE user_id = %s",
                       (user_id,)) or 0
    gastadas = scalar(cur, f"SELECT COUNT(*) FROM pagina_imagenes WHERE user_id = %s AND fuente = 'extra' AND {_CUENTA}",
                      (user_id,)) or 0
    hoy = scalar(cur, f"""
        SELECT COUNT(*) FROM pagina_imagenes
        WHERE user_id = %s AND fuente <> 'subida' AND {_CUENTA}
          AND created_at >= date_trunc('day', NOW() AT TIME ZONE 'America/Bogota') AT TIME ZONE 'America/Bogota'
    """, (user_id,)) or 0
    return calcular(fuente, int(incluidas or 0), int(usadas or 0), int(compradas), int(gastadas), int(hoy), renueva)


def calcular(fuente: str, incluidas: int, usadas: int, compradas: int, gastadas: int, hoy: int, renueva=None) -> Dict[str, Any]:
    del_plan = max(0, incluidas - usadas)
    extra = max(0, compradas - gastadas)
    return {
        "fuente": fuente, "con_plan": fuente == "plan", "total": incluidas, "usadas": usadas,
        "del_plan": del_plan, "extra": extra, "restantes": del_plan + extra,
        "renueva": renueva.isoformat() if renueva else None, "hoy": hoy, "limite_dia": LIMITE_DIA,
    }


def cupo(user_id: int) -> Dict[str, Any]:
    with get_db() as db:
        return _cupo(db.cursor, user_id)


def _sin_cupo(c: Dict[str, Any]) -> ImagenError:
    if c["con_plan"]:
        msg = (f"Ya usaste las {c['total']} imágenes con IA de tu plan en este periodo. "
               "Canjea Fyns por 5 más; tu cupo se renueva con el plan.")
    else:
        msg = (f"Ya usaste tus {c['total']} imágenes con IA de prueba. "
               "Activa un plan (trae imágenes cada mes) o canjea Fyns por 5 más.")
    return ImagenError("sin_cupo", msg, 402)


def _reservar(user_id: int, descripcion: str, estilo: str, formato: str) -> int:
    with get_db() as db:
        cur = db.cursor
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK, user_id))
        c = _cupo(cur, user_id)
        if c["hoy"] >= LIMITE_DIA:
            db.conn.rollback()
            raise ImagenError("limite_dia", f"Llegaste al máximo de {LIMITE_DIA} imágenes por día. "
                              "Sigue mañana; tu cupo no se pierde.", 429)
        fuente = c["fuente"] if c["del_plan"] > 0 else "extra" if c["extra"] > 0 else None
        if not fuente:
            db.conn.rollback()
            raise _sin_cupo(c)
        iid = scalar(cur, """
            INSERT INTO pagina_imagenes (user_id, fuente, descripcion, estilo, formato, modelo)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """, (user_id, fuente, descripcion, estilo, formato, MODELO))
        db.conn.commit()
    return iid


def _fallo(iid: int, error: str) -> None:
    with get_db() as db:
        db.cursor.execute("UPDATE pagina_imagenes SET error = %s WHERE id = %s", (error[:500], iid))
        db.conn.commit()


def generar(user_id: int, descripcion: str, estilo: Optional[str] = None, formato: Optional[str] = None) -> Dict[str, Any]:
    from openai import OpenAI
    from src.services import storage_service as store

    descripcion = (descripcion or "").strip()[:400]
    if len(descripcion) < 4:
        raise ImagenError("datos", "Cuéntame qué quieres ver en la imagen (por ejemplo: «terraza con vista a Medellín al atardecer»).")
    estilo = estilo if estilo in ESTILOS else "natural"
    formato = formato if formato in FORMATOS else "ancha"
    c = cupo(user_id)
    if c["restantes"] <= 0:
        raise _sin_cupo(c)
    if not os.getenv("OPENAI_API_KEY") or not store.storage_disponible():
        # Se revisa antes de pagar: no generar una imagen que no se podría guardar.
        raise ImagenError("no_disponible", "Las imágenes con IA no están disponibles en este momento.", 503)

    iid = _reservar(user_id, descripcion, estilo, formato)
    t0 = time.time()
    try:
        resp = OpenAI().images.generate(model=MODELO, prompt=instruccion(descripcion, estilo),
                                        size=FORMATOS[formato], quality=CALIDAD)
        datos = base64.b64decode(resp.data[0].b64_json)
    except Exception as e:  # noqa: BLE001
        _fallo(iid, str(e))
        raise ImagenError("ia", "La IA no pudo crear la imagen ahora. No se descontó de tu cupo.", 502) from e
    try:
        from src.core.ai_usage_tracker import get_ai_tracker
        uso = getattr(resp, "usage", None)
        get_ai_tracker().log_usage(provider="openai", model=MODELO, usage_type="image_generation",
                                   function_name="pagina_imagenes.generar",
                                   input_tokens=getattr(uso, "input_tokens", None),
                                   output_tokens=getattr(uso, "output_tokens", None),
                                   response_time_ms=int((time.time() - t0) * 1000),
                                   context={"user_id": user_id, "formato": formato})
    except Exception:  # noqa: BLE001
        pass
    try:
        url = store.upload_image_bytes(datos, "image/png", prefix=f"paginas/{user_id}/ia")
    except Exception as e:  # noqa: BLE001
        _fallo(iid, f"storage: {e}")
        raise ImagenError("no_disponible", "No pude guardar la imagen. No se descontó de tu cupo.", 503) from e
    with get_db() as db:
        db.cursor.execute("UPDATE pagina_imagenes SET url = %s WHERE id = %s", (url, iid))
        db.conn.commit()
    return {"id": iid, "url": url, "cupo": cupo(user_id)}


def registrar_subida(user_id: int, url: str) -> Dict[str, Any]:
    """Una imagen que el agente subió queda en su biblioteca (no gasta cupo)."""
    url = (url or "").strip()
    if not _URL.match(url) or len(url) > 500:
        raise ImagenError("datos", "La imagen debe ser un enlace https.")
    with get_db() as db:
        existe = scalar(db.cursor, "SELECT id FROM pagina_imagenes WHERE user_id = %s AND url = %s", (user_id, url))
        iid = existe or scalar(db.cursor, """
            INSERT INTO pagina_imagenes (user_id, fuente, url) VALUES (%s, 'subida', %s) RETURNING id
        """, (user_id, url))
        db.conn.commit()
    return {"id": iid, "url": url}


def biblioteca(user_id: int, limite: int = 60) -> Dict[str, Any]:
    with get_db() as db:
        filas = fetch_all(db.cursor, """
            SELECT id, url, fuente, descripcion, formato, created_at FROM pagina_imagenes
            WHERE user_id = %s AND url IS NOT NULL ORDER BY created_at DESC LIMIT %s
        """, (user_id, limite))
        c = _cupo(db.cursor, user_id)
    imagenes: List[Dict[str, Any]] = [
        {"id": f["id"], "url": f["url"], "con_ia": f["fuente"] != "subida", "descripcion": f["descripcion"],
         "formato": f["formato"], "fecha": f["created_at"].isoformat()} for f in filas]
    return {"imagenes": imagenes, "cupo": c, "estilos": list(ESTILOS), "formatos": list(FORMATOS)}


def abonar_en(cur, user_id: int, cantidad: int, referencia: str, creado_por: str = "fyns") -> None:
    cur.execute("""
        INSERT INTO pagina_imagenes_movimientos (user_id, cantidad, referencia, creado_por) VALUES (%s, %s, %s, %s)
    """, (user_id, cantidad, referencia, creado_por))


def sugerir(user_id: int, para: Optional[str] = None, pista: Optional[str] = None) -> Dict[str, Any]:
    """Una descripción lista para generar, a partir de las zonas, la marca y el bloque. Gasta un uso
    de la IA de textos de la página (10 al día), no del cupo de imágenes."""
    from src.services import pagina_ia_service as ia
    from src.services.db import fetch_one
    ia._cupo(user_id)
    with get_db() as db:
        u = fetch_one(db.cursor, "SELECT nombre, marca_nombre, pagina_zonas FROM chat_users WHERE id = %s", (user_id,))
    zonas = ", ".join((u or {}).get("pagina_zonas") or []) or "Medellín"
    prompt = (f"Propón 3 descripciones cortas (máximo 18 palabras cada una) de una fotografía para la página web de "
              f"un agente inmobiliario que trabaja en {zonas}. La imagen va en: {para or 'la portada'}. "
              f"{('Lo que pidió el agente: ' + pista.strip()[:200]) if pista and pista.strip() else ''}\n"
              "Escenas concretas y reales de esas zonas o de interiores típicos (balcones, terrazas, salas, "
              "vistas de la ciudad, calles arborizadas). Sin personas ni texto. Elige el estilo que mejor le va a cada una.")
    esquema = {"type": "object", "properties": {"opciones": {"type": "array", "items": {
        "type": "object", "properties": {"descripcion": {"type": "string"}, "estilo": {"type": "string", "enum": list(ESTILOS)}},
        "required": ["descripcion", "estilo"]}}}, "required": ["opciones"]}
    r = ia._llamar(prompt, esquema, "imagen_sugerir", max_tokens=600)
    quedan = ia._contar(user_id)
    return {"opciones": [o for o in r.get("opciones", []) if o.get("descripcion")][:3], "quedan": quedan}
