"""
Helpers de acceso a datos para la capa de servicios, con POOL de conexiones.

Antes cada `get_db()` abría una conexión nueva a Neon (handshake SSL ~200-400ms).
Como una sola tool del MCP valida token + resuelve identidad + hace varias
consultas, se acumulaban 5-6 conexiones nuevas por llamada => lento.

Ahora se usa un pool (`ThreadedConnectionPool`): las conexiones se reutilizan
tibias, eliminando el costo de reconexión repetida. Se sigue entregando un
`DatabaseManager` (para conservar `log_evento` y el resto de métodos), pero con
una conexión prestada del pool que se devuelve —no se cierra— al salir.

Read-only por defecto: al devolver la conexión se hace rollback (limpia
cualquier transacción implícita); las escrituras deben hacer `db.conn.commit()`.
"""

import os
import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Sequence

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor

from src.db.database import DatabaseManager

_pool: Optional[pg_pool.ThreadedConnectionPool] = None
_pool_lock = threading.Lock()


def _get_pool() -> pg_pool.ThreadedConnectionPool:
    """Crea (una vez) y devuelve el pool de conexiones."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                dsn = os.getenv("DATABASE_URL")
                if not dsn:
                    raise RuntimeError("DATABASE_URL no está definida")
                maxconn = int(os.getenv("FYNDER_DB_POOL_MAX", "4"))
                _pool = pg_pool.ThreadedConnectionPool(
                    minconn=1, maxconn=maxconn, dsn=dsn,
                    cursor_factory=RealDictCursor,
                )
    return _pool


def _healthy(conn) -> bool:
    """Verifica que una conexión prestada siga viva (Neon cierra las ociosas)."""
    if conn.closed:
        return False
    try:
        conn.rollback()  # limpia estado previo
        with conn.cursor() as c:
            c.execute("SELECT 1")
            c.fetchone()
        return True
    except Exception:
        return False


def _borrow():
    """Toma una conexión sana del pool, reemplazando las muertas (hasta 3 intentos)."""
    p = _get_pool()
    last_err = None
    for _ in range(3):
        conn = p.getconn()
        if _healthy(conn):
            return conn
        # Conexión muerta: descartarla del pool y reintentar.
        try:
            p.putconn(conn, close=True)
        except Exception as e:
            last_err = e
    # Fallback: conexión directa si el pool no da una sana.
    if last_err:
        pass
    return psycopg2.connect(os.getenv("DATABASE_URL"), cursor_factory=RealDictCursor)


@contextmanager
def get_db():
    """
    Entrega un `DatabaseManager` con una conexión prestada del pool.

    - Rollback automático ante excepción.
    - Al salir devuelve la conexión al pool (no la cierra).
    - No hace commit: para escrituras, el caller llama `db.conn.commit()`.
    """
    p = _get_pool()
    conn = _borrow()

    db = DatabaseManager()
    db.conn = conn
    db.cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        yield db
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            db.cursor.close()
        except Exception:
            pass
        try:
            conn.rollback()  # deja la conexión limpia para el siguiente uso
        except Exception:
            pass
        # Devolver al pool; si vino por fallback directo, cerrarla.
        try:
            p.putconn(conn)
        except (KeyError, pg_pool.PoolError):
            try:
                conn.close()
            except Exception:
                pass


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
    return next(iter(dict(row).values()), None)
