"""
Helpers de acceso a datos para la capa de servicios.

Envuelven `DatabaseManager` (psycopg2 + RealDictCursor sobre Neon) con una API
mínima y consistente. Read-only por defecto: el context manager hace rollback
ante excepción y NO hace commit; las escrituras hacen `db.conn.commit()`
explícito.
"""

from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Sequence

from src.db.database import DatabaseManager


@contextmanager
def get_db():
    """
    Entrega un `DatabaseManager` conectado dentro de un `with`.

    - Rollback automático si el bloque lanza una excepción.
    - Cierre garantizado de la conexión al salir.
    - No hace commit: para escrituras, el caller debe llamar `db.conn.commit()`.
    """
    db = DatabaseManager()
    if not db.connect():
        raise RuntimeError("No se pudo establecer conexión con la base de datos")
    try:
        yield db
    except Exception:
        try:
            if db.conn:
                db.conn.rollback()
        except Exception:
            pass
        raise
    finally:
        db.disconnect()


def fetch_all(cur, sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    """Ejecuta una consulta y devuelve todas las filas como dicts planos."""
    cur.execute(sql, params or ())
    return [dict(row) for row in cur.fetchall()]


def fetch_one(cur, sql: str, params: Optional[Sequence[Any]] = None) -> Optional[Dict[str, Any]]:
    """Ejecuta una consulta y devuelve la primera fila como dict, o None."""
    cur.execute(sql, params or ())
    row = cur.fetchone()
    return dict(row) if row else None


def scalar(cur, sql: str, params: Optional[Sequence[Any]] = None) -> Any:
    """Ejecuta una consulta que devuelve un único valor y lo retorna."""
    cur.execute(sql, params or ())
    row = cur.fetchone()
    if not row:
        return None
    # RealDictCursor -> tomar el primer valor del dict
    return next(iter(dict(row).values()), None)
