"""
Verificación de disponibilidad on-demand (Bloque B del plan de desarrollo).

Re-scrapea (HTTP) el link original de una propiedad para saber si sigue viva
ANTES de escalar a Hernán (no tiene sentido desgastarlo con un inmueble que ya
salió del mercado). Consumido por A1 (tool MCP) y A4 (admin).

Este módulo es la ÚNICA fuente de verdad del chequeo de URLs: el batch nocturno
(`scripts/validate_property_urls.py`) importa `check_url` desde aquí.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests

from src.services.db import get_db, fetch_one

REQUEST_TIMEOUT = 20  # segundos
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Patrones en el HTML que indican que la propiedad ya no existe. Los portales
# devuelven HTTP 200 pero muestran estos mensajes en el contenido.
CONTENT_NOT_FOUND_PATTERNS = [
    "no se encontró inmueble",
    "no se encontro inmueble",
    "inmueble no encontrado",
    "propiedad no encontrada",
    "esta propiedad ya no está disponible",
    "esta propiedad ya no esta disponible",
    "no encontramos la propiedad",
    "property not found",
    "this property is no longer available",
    "el inmueble que buscas ya no está disponible",
    "el inmueble que buscas ya no esta disponible",
    "este inmueble ya no se encuentra disponible",
    "publicación no disponible",
    "publicacion no disponible",
]

# Wasi a veces redirige al home cuando no existe.
WASI_REDIRECT_PATTERNS = ["wasi.co/es", "wasi.co/en"]


def build_session() -> requests.Session:
    """Sesión HTTP con el User-Agent estándar (compartida por batch y on-demand)."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def check_url(session, url, fuente) -> Tuple[bool, str, Optional[int]]:
    """
    Verifica si una URL sigue activa.
    Approach principal: leer el contenido HTML y buscar patrones de "no encontrada"
    (los portales devuelven HTTP 200 aun cuando la propiedad ya no existe).
    Conservador: ante error temporal (5xx/403/timeout) NO desactiva.
    Returns: (is_active: bool, reason: str, status_code: int|None)
    """
    if not url or not url.startswith("http"):
        return True, "sin_url", None

    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        status = response.status_code
        final_url = response.url

        if status == 410:
            return False, "410_gone", status
        if status == 404:
            return False, "404", status
        if status >= 500:
            return True, f"server_error_{status}", status
        if status == 403:
            return True, "forbidden_skip", status

        if 200 <= status < 400:
            content_lower = response.text[:8000].lower()
            for pattern in CONTENT_NOT_FOUND_PATTERNS:
                if pattern in content_lower:
                    return False, f"content_not_found: {pattern}", status
            if fuente and "wasi" in fuente.lower():
                for pattern in WASI_REDIRECT_PATTERNS:
                    if pattern in final_url.lower() and "info.wasi.co" not in final_url.lower():
                        return False, "wasi_redirect_home", status
            return True, "ok", status

        return True, f"unknown_{status}", status

    except requests.exceptions.Timeout:
        return True, "timeout_skip", None
    except requests.exceptions.ConnectionError:
        return True, "connection_error_skip", None
    except requests.exceptions.TooManyRedirects:
        return False, "too_many_redirects", None
    except Exception as e:  # noqa: BLE001 — conservador: cualquier error raro = no desactivar
        return True, f"error: {str(e)[:50]}", None


def _estado_desde_reason(is_active: bool, reason: str) -> str:
    """Traduce el `reason` técnico a un estado de negocio legible."""
    if is_active:
        return "disponible" if reason.startswith("ok") else "desconocido"
    if reason in ("404", "410_gone"):
        return "404"
    if reason.startswith("content_not_found") or reason in ("wasi_redirect_home", "too_many_redirects"):
        return "no_disponible"
    return "desconocido"


def verificar_disponibilidad(propiedad_id, actualizar: bool = True) -> Dict[str, Any]:
    """
    Verifica una propiedad puntual y (por defecto) persiste el resultado.

    Devuelve:
      {
        propiedad_id, activo: bool,
        estado: 'disponible' | '404' | 'no_disponible' | 'desconocido',
        status_code, motivo, verificado_en (ISO)
      }

    Semántica de escritura (conservadora, igual que el batch):
      - Muerta (404/410/contenido) → activa=FALSE, +1 fallo, sella fecha.
      - Viva → sella fecha y resetea el contador de fallos (no reactiva a la fuerza).
      - Temporal/desconocida (5xx/403/timeout/sin_url) → solo sella la fecha.
    """
    with get_db() as db:
        prop = fetch_one(db.cursor,
            "SELECT id, url, fuente, activa FROM propiedades WHERE id = %s", (propiedad_id,))
        if not prop:
            return {"error": f"Propiedad {propiedad_id} no encontrada"}

        is_active, reason, status = check_url(build_session(), prop["url"], prop["fuente"])
        estado = _estado_desde_reason(is_active, reason)

        if actualizar:
            if not is_active:
                db.cursor.execute("""
                    UPDATE propiedades
                    SET activa = FALSE,
                        fecha_ultima_validacion = NOW(),
                        validaciones_fallidas_consecutivas = COALESCE(validaciones_fallidas_consecutivas, 0) + 1,
                        fecha_actualizacion = NOW()
                    WHERE id = %s
                """, (prop["id"],))
            elif estado == "disponible":
                db.cursor.execute("""
                    UPDATE propiedades
                    SET fecha_ultima_validacion = NOW(),
                        validaciones_fallidas_consecutivas = 0
                    WHERE id = %s
                """, (prop["id"],))
            else:  # temporal / desconocida: solo dejamos constancia del intento
                db.cursor.execute(
                    "UPDATE propiedades SET fecha_ultima_validacion = NOW() WHERE id = %s",
                    (prop["id"],))
            db.conn.commit()

    return {
        "propiedad_id": prop["id"],
        "activo": is_active,
        "estado": estado,
        "status_code": status,
        "motivo": reason,
        "verificado_en": datetime.now(timezone.utc).isoformat(),
    }
