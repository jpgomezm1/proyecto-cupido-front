"""
Creación de listings NATIVOS de Fynder (fuente='Fynder').

El agente crea una propiedad directamente en Fynder (no scrapeada de Wasi/Lobbie),
con fotos subidas a Supabase Storage y campos autocompletados por IA. Toda la
escritura pasa por el único punto de verdad: `DatabaseManager.insert_property`.

Campos que el agente PONE a mano (la IA no puede saberlos): precio, área,
ubicación, habitaciones/baños/parqueaderos, estrato.
Campos que la IA AUTOCOMPLETA: título, descripción, amenidades, tipo/estilo,
precio sugerido. (El orquestador de IA vive en `listing_ai.py`.)
"""

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.services.db import get_db, fetch_one
from src.services.textutils import (
    normalize_phone, build_share_link, FRONTEND_URL, format_cop, split_image_urls,
)

# Tipos de negocio válidos. Igual que el resto del sistema, los arriendos se
# guardan pero no aparecen en búsquedas de venta.
_TIPO_NEGOCIO = {"Venta", "Arriendo"}


class ListingError(Exception):
    """Error de validación al crear un listing."""


def _requerido(data: Dict[str, Any], campo: str, etiqueta: str):
    v = data.get(campo)
    if v is None or (isinstance(v, str) and not v.strip()):
        raise ListingError(f"Falta {etiqueta} (campo '{campo}'), que el agente debe ingresar.")
    return v


def crear_listing(agente_telefono: str, data: Dict[str, Any],
                  agente_nombre: Optional[str] = None,
                  agente_user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Crea un listing nativo de Fynder y lo guarda en Neon.

    `data` acepta: precio, area_construida, ciudad, zona, direccion_completa,
    tipo_propiedad, habitaciones, banos, parqueaderos, estrato, piso,
    ano_construccion, administracion, titulo, descripcion, amenidades_internas,
    amenidades_externas, imagenes_urls (list), tipo_negocio, latitud, longitud.

    Obligatorios (el agente los ingresa): precio, area_construida, tipo_propiedad,
    y al menos ciudad o zona (ubicación).
    """
    tel10 = normalize_phone(agente_telefono)
    if not tel10:
        raise ListingError("El agente no tiene un teléfono válido para asociar la propiedad.")

    # --- Validación de obligatorios (lo que la IA no puede inventar) ---
    precio = _requerido(data, "precio", "el precio")
    try:
        precio = int(precio)
        if precio <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ListingError("El precio debe ser un número positivo en pesos (ej. 600000000).")

    area = _requerido(data, "area_construida", "el área en m²")
    try:
        area = float(area)
        if area <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise ListingError("El área debe ser un número positivo en m².")

    tipo_propiedad = _requerido(data, "tipo_propiedad", "el tipo de propiedad")
    if not (data.get("ciudad") or data.get("zona")):
        raise ListingError("Falta la ubicación: ingresa al menos la ciudad o la zona.")

    tipo_negocio = data.get("tipo_negocio") or "Venta"
    if tipo_negocio not in _TIPO_NEGOCIO:
        raise ListingError(f"tipo_negocio inválido; usa {_TIPO_NEGOCIO}.")

    # --- Imágenes ---
    imgs: List[str] = [u for u in (data.get("imagenes_urls") or []) if u]
    imagenes_str = "|".join(imgs) if imgs else None

    # --- Amenidades ---
    amen_int = data.get("amenidades_internas")
    amen_ext = data.get("amenidades_externas")
    total_amen = 0
    for a in (amen_int, amen_ext):
        if a:
            total_amen += len([x for x in str(a).split("|") if x.strip()])

    descripcion = (data.get("descripcion") or "").strip() or None
    titulo = (data.get("titulo") or "").strip() or None

    codigo = f"FYNDER-{uuid.uuid4().hex[:16]}"
    # url NOT NULL: auto-referencia estable (el link compartible real usa el id).
    url = f"{FRONTEND_URL}/propiedad/{codigo}"

    property_data = {
        "codigo_propiedad": codigo,
        "fuente": "Fynder",                      # listing NATIVO
        "url": url,
        "titulo": titulo,
        "precio": precio,
        "precio_texto": format_cop(precio),
        "tipo_propiedad": tipo_propiedad,
        "tipo_negocio": tipo_negocio,
        "estado": "Disponible",
        "ciudad": data.get("ciudad"),
        "zona": data.get("zona"),
        "departamento": data.get("departamento"),
        "pais": data.get("pais") or "Colombia",
        "direccion_completa": data.get("direccion_completa"),
        "latitud": data.get("latitud"),
        "longitud": data.get("longitud"),
        "ubicacion_aproximada": data.get("ubicacion_aproximada", True),
        "area_construida": area,
        "habitaciones": data.get("habitaciones"),
        "banos": data.get("banos"),
        "parqueaderos": data.get("parqueaderos"),
        "estrato": data.get("estrato"),
        "piso": data.get("piso"),
        "ano_construccion": data.get("ano_construccion"),
        "administracion": data.get("administracion"),
        "amenidades_internas": amen_int,
        "amenidades_externas": amen_ext,
        "total_amenidades": total_amen or None,
        "descripcion": descripcion,
        "descripcion_length": len(descripcion) if descripcion else None,
        "imagenes_urls": imagenes_str,
        "total_imagenes": len(imgs) or None,
        "imagen_principal": imgs[0] if imgs else None,
        "fecha_extraccion": datetime.now(),
        # Ownership: el agente que lo crea es el captador.
        "agente_captador_telefono": agente_telefono,
        "origen": "Fynder_App",
        "asesor": agente_nombre,
        "telefono": agente_telefono,
        "inmobiliaria": "Fynder",
        # Listing nativo: NO anonimizar (no hay portal de origen que ocultar).
        # anonimizado_version es INTEGER; un valor truthy hace que insert_property
        # se salte la anonimización.
        "anonimizado_version": 1,
    }

    # Sin fotos => BORRADOR (activa=false): no aparece en búsquedas hasta que
    # tenga al menos una foto. Se publica solo al subir fotos (ver agregar_fotos).
    es_borrador = len(imgs) == 0

    with get_db() as db:
        prop_id = db.insert_property(property_data)
        if not prop_id:
            raise ListingError("No se pudo guardar la propiedad. Intenta de nuevo.")
        if es_borrador:
            db.cursor.execute("UPDATE propiedades SET activa = FALSE WHERE id = %s", (prop_id,))
        db.conn.commit()
        try:
            db.log_evento(
                tipo_evento="listing_creado_fynder",
                agente_telefono=agente_telefono,
                propiedad_id=prop_id,
                datos_evento={"codigo": codigo, "precio": precio, "origen": "Fynder_App",
                              "imagenes": len(imgs), "borrador": es_borrador},
            )
        except Exception:
            pass

    if es_borrador:
        mensaje = ("Borrador creado con el título, la descripción y los datos. Para PUBLICARLO "
                   "(que aparezca en búsquedas y sea compartible) FALTAN LAS FOTOS: pásale al "
                   "agente el link de subir fotos. En cuanto suba al menos una, se publica solo.")
    else:
        mensaje = "¡Listing publicado en Fynder! Ya aparece en tu inventario y es compartible."

    return {
        "ok": True,
        "id": prop_id,
        "codigo_propiedad": codigo,
        "titulo": titulo,
        "precio_legible": format_cop(precio),
        "total_imagenes": len(imgs),
        "estado_publicacion": "borrador_pendiente_fotos" if es_borrador else "publicado",
        "requiere_fotos": es_borrador,
        "link_compartir": build_share_link(prop_id, titulo, agente_user_id),
        "link_subir_fotos": link_subir_fotos(prop_id, tel10),
        "mensaje": mensaje,
    }


# =========================================================================
# Link mágico para subir fotos (el agente lo abre en el celular).
# =========================================================================
# Las fotos no viajan bien por un tool call del MCP (son binarios grandes). En
# su lugar, al crear el listing se devuelve un link firmado; el agente lo abre y
# arrastra las fotos, que se suben a Supabase y se añaden a la propiedad.

_PHOTO_TTL = 60 * 60 * 24 * 14  # 14 días


def _secret() -> bytes:
    s = os.getenv("FYNDER_MCP_SECRET") or os.getenv("JWT_SECRET")
    if not s:
        raise ListingError("Falta FYNDER_MCP_SECRET en el entorno.")
    return s.encode("utf-8")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def build_photo_token(property_id: int, owner_10: str) -> str:
    payload = {"pid": int(property_id), "owner": owner_10, "exp": int(time.time()) + _PHOTO_TTL}
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_photo_token(token: str) -> Dict[str, Any]:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        raise ListingError("Link de subida inválido")
    expected = _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise ListingError("Link de subida inválido (firma)")
    payload = json.loads(_b64d(body))
    if payload.get("exp", 0) < int(time.time()):
        raise ListingError("El link de subida expiró; genera uno nuevo desde tu asistente.")
    return payload


def link_subir_fotos(property_id: int, owner_10: str) -> str:
    """URL pública del link mágico para subir fotos de un listing."""
    base = os.getenv("MCP_PUBLIC_URL", "http://localhost:8767").rstrip("/")
    return f"{base}/subir-fotos?t={build_photo_token(property_id, owner_10)}"


def agregar_fotos(property_id: int, nuevas_urls: List[str]) -> Dict[str, Any]:
    """
    Añade URLs de imágenes (ya subidas a Supabase) a una propiedad: las anexa a
    imagenes_urls, actualiza total_imagenes y fija imagen_principal si estaba vacía.
    """
    if not nuevas_urls:
        return {"ok": True, "total_imagenes": 0, "agregadas": 0}
    with get_db() as db:
        row = fetch_one(db.cursor,
            "SELECT imagenes_urls, imagen_principal, activa, fuente FROM propiedades WHERE id=%s",
            (property_id,))
        if not row:
            raise ListingError("Propiedad no encontrada")
        actuales = split_image_urls(row.get("imagenes_urls"))
        combinadas = actuales + [u for u in nuevas_urls if u and u not in actuales]
        principal = row.get("imagen_principal") or (combinadas[0] if combinadas else None)
        db.cursor.execute("""
            UPDATE propiedades
            SET imagenes_urls = %s, total_imagenes = %s, imagen_principal = %s,
                fecha_actualizacion = NOW()
            WHERE id = %s
        """, ("|".join(combinadas), len(combinadas), principal, property_id))

        # Auto-publicar: si era un borrador de Fynder (sin fotos) y ahora tiene
        # al menos una, se publica solo.
        publicado_ahora = False
        if not row.get("activa") and row.get("fuente") == "Fynder" and combinadas:
            db.cursor.execute("UPDATE propiedades SET activa = TRUE WHERE id = %s", (property_id,))
            publicado_ahora = True
        db.conn.commit()

    return {"ok": True, "total_imagenes": len(combinadas),
            "agregadas": len(combinadas) - len(actuales),
            "publicado_ahora": publicado_ahora}


def listar_fotos(property_id: int) -> Dict[str, Any]:
    """Devuelve las fotos de una propiedad numeradas (1-indexed), para ordenar."""
    with get_db() as db:
        row = fetch_one(db.cursor,
            "SELECT titulo, imagenes_urls FROM propiedades WHERE id=%s", (property_id,))
    if not row:
        return {"error": "Propiedad no encontrada"}
    urls = split_image_urls(row.get("imagenes_urls"))
    return {
        "propiedad_id": property_id,
        "titulo": row.get("titulo"),
        "total": len(urls),
        "fotos": [{"posicion": i + 1, "url": u} for i, u in enumerate(urls)],
    }


def reordenar_fotos(property_id: int, nuevo_orden: List[int]) -> Dict[str, Any]:
    """
    Reordena las fotos de una propiedad. `nuevo_orden` es la lista de POSICIONES
    actuales (1-indexed) en el orden deseado. Ej: [3,1,2] -> la foto que estaba
    de tercera queda de portada. La primera del nuevo orden es la portada.
    """
    with get_db() as db:
        row = fetch_one(db.cursor,
            "SELECT imagenes_urls FROM propiedades WHERE id=%s", (property_id,))
        if not row:
            raise ListingError("Propiedad no encontrada")
        urls = split_image_urls(row.get("imagenes_urls"))
        n = len(urls)
        if n == 0:
            raise ListingError("La propiedad no tiene fotos para ordenar")

        # Validar: debe ser una permutación completa de 1..n.
        try:
            orden = [int(x) for x in nuevo_orden]
        except (TypeError, ValueError):
            raise ListingError("El orden debe ser una lista de números de posición")
        if sorted(orden) != list(range(1, n + 1)):
            raise ListingError(
                f"El orden debe incluir cada foto exactamente una vez (posiciones 1 a {n}). "
                f"Recibí: {orden}")

        reordenadas = [urls[i - 1] for i in orden]
        db.cursor.execute("""
            UPDATE propiedades
            SET imagenes_urls = %s, imagen_principal = %s, fecha_actualizacion = NOW()
            WHERE id = %s
        """, ("|".join(reordenadas), reordenadas[0], property_id))
        db.conn.commit()

    return {"ok": True, "total": n,
            "portada": reordenadas[0],
            "nuevo_orden": [{"posicion": i + 1, "url": u} for i, u in enumerate(reordenadas)],
            "mensaje": "Fotos reordenadas. La primera es ahora la portada de la propiedad."}
