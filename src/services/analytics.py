"""
Eventos de uso hacia PostHog desde el servidor (lo que la web no ve: el MCP y
los pagos confirmados por Wompi).

- Solo se envía desde Heroku (variable DYNO) o con POSTHOG_ENABLED=1; en local
  y en los tests no sale nada.
- El agente va como "agente-<id>", el mismo distinct_id que usa la web, sin
  correo, nombre ni teléfono (Ley 1581). Nunca se mandan argumentos de las tools.
- Envío en un hilo aparte con timeout corto: nunca demora ni rompe la petición.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

import requests

_KEY = os.getenv("POSTHOG_KEY", "phc_mRjjUmQpSFcrbbhXqDqZgCWiAd9g5Rqwh2oxswmByWvX")  # clave pública del proyecto
_HOST = os.getenv("POSTHOG_HOST", "https://us.i.posthog.com").rstrip("/")
_ACTIVO = bool(_KEY) and (os.getenv("POSTHOG_ENABLED") == "1" or (bool(os.getenv("DYNO")) and os.getenv("POSTHOG_ENABLED") != "0"))

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="posthog")


def _enviar(evento: str, distinct_id: str, props: Dict[str, Any]) -> None:
    try:
        requests.post(f"{_HOST}/i/v0/e/", json={
            "api_key": _KEY, "event": evento, "distinct_id": distinct_id,
            "properties": {**props, "$lib": "fynder-backend"},
        }, timeout=4)
    except Exception:  # noqa: BLE001
        pass


def capturar(evento: str, user_id: Optional[int], props: Optional[Dict[str, Any]] = None) -> None:
    """Encola un evento. Sin agente identificado no se envía (no hay a quién atribuirlo)."""
    if not _ACTIVO or not user_id:
        return
    try:
        _executor.submit(_enviar, evento, f"agente-{int(user_id)}", dict(props or {}))
    except Exception:  # noqa: BLE001
        pass
