"""
Lock de jobs que sobrevive al pooler de Neon.

`pg_try_advisory_lock` es de SESIÓN: con el pooler en modo transacción, el lock y
el unlock pueden caer en conexiones distintas del servidor y el lock queda tomado
para siempre (el job responde "omitido" en cada corrida). Aquí el lock es una
fila con vencimiento: se toma si está libre o vencido, se suelta al terminar, y si
el proceso muere se libera solo al vencer.
"""

from contextlib import contextmanager
from typing import Iterator

from src.services.db import get_db, scalar

_CREAR = """
    CREATE TABLE IF NOT EXISTS job_locks (
        nombre TEXT PRIMARY KEY,
        hasta TIMESTAMPTZ NOT NULL
    )
"""
_tabla_lista = False


def _asegurar_tabla(db) -> None:
    """Crea la tabla una vez por proceso. Dos jobs que la crean a la vez chocan en
    `pg_type` aun con IF NOT EXISTS; el que pierde la encuentra ya creada."""
    global _tabla_lista
    if _tabla_lista:
        return
    try:
        db.cursor.execute(_CREAR)
        db.conn.commit()
    except Exception:
        db.conn.rollback()
        db.cursor.execute("SELECT 1 FROM job_locks LIMIT 1")
    _tabla_lista = True


def tomar(nombre: str, minutos: int) -> bool:
    with get_db() as db:
        _asegurar_tabla(db)
        cur = db.cursor
        tomado = scalar(cur, """
            INSERT INTO job_locks (nombre, hasta) VALUES (%s, NOW() + make_interval(mins => %s))
            ON CONFLICT (nombre) DO UPDATE SET hasta = EXCLUDED.hasta
                WHERE job_locks.hasta < NOW()
            RETURNING 1
        """, (nombre, minutos))
        db.conn.commit()
    return bool(tomado)


def soltar(nombre: str) -> None:
    with get_db() as db:
        db.cursor.execute("UPDATE job_locks SET hasta = NOW() WHERE nombre = %s", (nombre,))
        db.conn.commit()


@contextmanager
def lock(nombre: str, minutos: int = 25) -> Iterator[bool]:
    """`with lock("alertas") as ok:` — `ok` es False si otra corrida lo tiene."""
    ok = tomar(nombre, minutos)
    try:
        yield ok
    finally:
        if ok:
            soltar(nombre)
