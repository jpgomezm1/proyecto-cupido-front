"""
Registro de uso de las tools del MCP (tabla `mcp_tool_calls`, migración 039).

Se llama desde el wrapper central de tools (server.py), así toda tool —actual o
futura— queda medida. La escritura va a un hilo aparte para no sumar latencia a
la respuesta, y nunca rompe una tool: si la tabla no existe o la BD falla, se
avisa una vez en el log y se sigue.

Privacidad: solo se guardan los NOMBRES de los argumentos, nunca sus valores.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Optional

from src.services.db import get_db

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mcp-uso")
_aviso_emitido = False


def _insertar(tool: str, user_id: Optional[int], ok: bool, error: Optional[str],
              duracion_ms: int, argumentos: list) -> None:
    global _aviso_emitido
    try:
        with get_db() as db:
            db.cursor.execute("""
                INSERT INTO mcp_tool_calls (tool, user_id, ok, error, duracion_ms, argumentos)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (tool, user_id, ok, (error or None) and error[:120], duracion_ms, argumentos))
            db.conn.commit()
    except Exception as e:
        if not _aviso_emitido:
            _aviso_emitido = True
            logger.warning("No se pudo registrar uso del MCP (¿falta la migración 039?): %s", e)


def registrar(tool: str, user_id: Optional[int], duracion_ms: int,
              error: Optional[str] = None, argumentos: Iterable[str] = ()) -> None:
    """Encola el registro de una tool call. Nunca lanza."""
    try:
        _executor.submit(_insertar, tool, user_id, error is None, error,
                         int(duracion_ms), sorted(argumentos))
    except Exception:
        pass
