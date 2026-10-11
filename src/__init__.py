"""
Paquete del backend de Fynder.

Al importarse fija límites de tiempo por defecto para los clientes de IA: sin
ellos el SDK espera hasta 10 minutos con reintentos, y una caída de Anthropic u
OpenAI dejaba colgados los procesos web (Heroku corta a los 30 s, pero el
worker seguía ocupado). Quien pase su propio `timeout`/`max_retries` lo conserva.
"""


def _limitar_clientes_ia() -> None:
    import functools
    import os

    def _envolver(clase, timeout: float, reintentos: int) -> None:
        original = clase.__init__
        if getattr(original, "_fynder_timeout", False):
            return

        @functools.wraps(original)
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("timeout", timeout)
            kwargs.setdefault("max_retries", reintentos)
            original(self, *args, **kwargs)

        __init__._fynder_timeout = True  # type: ignore[attr-defined]
        clase.__init__ = __init__

    try:
        import anthropic
        _envolver(anthropic.Anthropic, float(os.getenv("FYNDER_IA_TIMEOUT", "50")), 1)
    except Exception:  # noqa: BLE001 — sin el SDK no hay nada que limitar
        pass
    try:
        import openai
        _envolver(openai.OpenAI, float(os.getenv("FYNDER_OPENAI_TIMEOUT", "90")), 1)
    except Exception:  # noqa: BLE001
        pass


_limitar_clientes_ia()
