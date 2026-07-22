"""
Storage de imágenes de propiedades (Supabase Storage).

Importante: la base de datos sigue siendo Neon. Supabase se usa ÚNICAMENTE como
almacén de archivos (bucket `fynder-propiedades`); las URLs públicas que devuelve
se guardan en Neon (`propiedades.imagenes_urls`).

Requiere en el entorno:
  SUPABASE_URL          https://<ref>.supabase.co
  SUPABASE_SERVICE_KEY  secret key del proyecto
  SUPABASE_BUCKET       fynder-propiedades (default)
"""

import base64
import os
import uuid
from typing import List, Optional

import httpx

_MIME_EXT = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}


class StorageError(Exception):
    pass


def _cfg():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    bucket = os.getenv("SUPABASE_BUCKET", "fynder-propiedades")
    if not url or not key:
        raise StorageError("Falta SUPABASE_URL o SUPABASE_SERVICE_KEY en el entorno")
    return url.rstrip("/"), key, bucket


def _public_url(base: str, bucket: str, path: str) -> str:
    return f"{base}/storage/v1/object/public/{bucket}/{path}"


def upload_image_bytes(data: bytes, content_type: str, prefix: str = "listings") -> str:
    """
    Sube una imagen (bytes) al bucket y devuelve su URL pública.
    `prefix` organiza las carpetas (ej. 'listings/<codigo>').
    """
    if not data:
        raise StorageError("Imagen vacía")
    if content_type not in _MIME_EXT:
        raise StorageError(f"Tipo de imagen no soportado: {content_type}")
    if len(data) > 10 * 1024 * 1024:
        raise StorageError("La imagen supera el límite de 10 MB")

    base, key, bucket = _cfg()
    ext = _MIME_EXT[content_type]
    path = f"{prefix.strip('/')}/{uuid.uuid4().hex}.{ext}"
    headers = {
        "Authorization": f"Bearer {key}", "apikey": key,
        "Content-Type": content_type, "x-upsert": "true",
    }
    try:
        resp = httpx.post(f"{base}/storage/v1/object/{bucket}/{path}",
                          headers=headers, content=data, timeout=30)
    except Exception as e:
        raise StorageError(f"No se pudo conectar al storage: {e}")
    if resp.status_code not in (200, 201):
        raise StorageError(f"Fallo al subir imagen ({resp.status_code}): {resp.text[:150]}")
    return _public_url(base, bucket, path)


def upload_image_data_url(data_url: str, prefix: str = "listings") -> str:
    """
    Sube una imagen en formato data URL (data:image/jpeg;base64,....) — el formato
    que produce el navegador — y devuelve la URL pública.
    """
    if not data_url or "," not in data_url:
        raise StorageError("data URL inválida")
    header, b64 = data_url.split(",", 1)
    # header: "data:image/jpeg;base64"
    content_type = "image/jpeg"
    if header.startswith("data:") and ";" in header:
        content_type = header[5:].split(";", 1)[0] or content_type
    try:
        raw = base64.b64decode(b64)
    except Exception:
        raise StorageError("No se pudo decodificar la imagen base64")
    return upload_image_bytes(raw, content_type, prefix)


def upload_from_url(src_url: str, prefix: str = "listings") -> Optional[str]:
    """
    Descarga una imagen desde una URL pública y la sube al bucket (para el flujo
    del MCP, donde el agente pasa links de fotos ya online). Devuelve la URL
    pública en Supabase, o None si falla la descarga.
    """
    try:
        r = httpx.get(src_url, timeout=30, follow_redirects=True)
        if r.status_code != 200:
            return None
        ct = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if ct not in _MIME_EXT:
            ct = "image/jpeg"
        return upload_image_bytes(r.content, ct, prefix)
    except Exception:
        return None


def storage_disponible() -> bool:
    """True si hay credenciales de storage configuradas."""
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY"))
