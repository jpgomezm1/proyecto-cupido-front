"""
Storage de imágenes de propiedades: Neon Object Storage (compatible con S3).

Todo vive en Neon: la base de datos y los archivos. Las fotos van a un bucket
público de lectura (`fynder-propiedades`) de la rama de producción, y la URL
pública se guarda en `propiedades.imagenes_urls`.

Requiere en el entorno (Neon Console → Connect → Storage):
  AWS_ENDPOINT_URL_S3     https://<branch>.storage.<...>.aws.neon.tech
  AWS_ACCESS_KEY_ID       credencial con scope storage:write
  AWS_SECRET_ACCESS_KEY
  AWS_REGION              us-east-1 (default)
  STORAGE_BUCKET          fynder-propiedades (default)
"""

import base64
import os
import uuid
from typing import Optional

import httpx

_MIME_EXT = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}

_cliente = None


class StorageError(Exception):
    pass


def _cfg():
    endpoint = os.getenv("AWS_ENDPOINT_URL_S3")
    if not endpoint or not os.getenv("AWS_ACCESS_KEY_ID") or not os.getenv("AWS_SECRET_ACCESS_KEY"):
        raise StorageError("Falta configurar el storage (AWS_ENDPOINT_URL_S3 y la credencial de Neon)")
    return endpoint.rstrip("/"), os.getenv("STORAGE_BUCKET", "fynder-propiedades")


def _s3():
    """Cliente S3 contra Neon (se crea una vez; boto3 se importa solo aquí)."""
    global _cliente
    if _cliente is None:
        import boto3
        from botocore.config import Config
        endpoint, _ = _cfg()
        _cliente = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            config=Config(s3={"addressing_style": "path"}, connect_timeout=10, read_timeout=30,
                          retries={"max_attempts": 2}),
        )
    return _cliente


def _public_url(base: str, bucket: str, path: str) -> str:
    return f"{base}/{bucket}/{path}"


def upload_image_bytes(data: bytes, content_type: str, prefix: str = "listings") -> str:
    """
    Sube una imagen (bytes) al bucket y devuelve su URL pública.
    `prefix` organiza las carpetas (ej. 'listings/<codigo>').
    """
    if not data:
        raise StorageError("Imagen vacía")
    if content_type == "image/jpg":
        content_type = "image/jpeg"
    if content_type not in _MIME_EXT:
        raise StorageError(f"Tipo de imagen no soportado: {content_type}")
    if len(data) > 10 * 1024 * 1024:
        raise StorageError("La imagen supera el límite de 10 MB")

    base, bucket = _cfg()
    path = f"{prefix.strip('/')}/{uuid.uuid4().hex}.{_MIME_EXT[content_type]}"
    try:
        _s3().put_object(Bucket=bucket, Key=path, Body=data, ContentType=content_type,
                         CacheControl="public, max-age=31536000, immutable")
    except StorageError:
        raise
    except Exception as e:
        print(f"[storage] fallo al subir {path}: {e}")
        raise StorageError("No se pudo guardar la foto. Intenta de nuevo.")
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
    pública en el storage, o None si falla la descarga.
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
    return bool(os.getenv("AWS_ENDPOINT_URL_S3") and os.getenv("AWS_ACCESS_KEY_ID")
                and os.getenv("AWS_SECRET_ACCESS_KEY"))
