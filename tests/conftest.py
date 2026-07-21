"""
Configuración compartida para los tests del MCP de Fynder.

- Inserta la raíz del proyecto en sys.path (imports `src.*`).
- Carga `.env` (DATABASE_URL, etc.).
- Fija un `FYNDER_MCP_SECRET` de test si no hay uno.
- Fixtures que consultan la BD real (solo lectura) y hacen skip si no hay
  conexión, para que la suite corra en cualquier entorno.
"""

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
except Exception:
    pass

os.environ.setdefault("FYNDER_MCP_SECRET", "pytest-secret")


def _db_ok() -> bool:
    if not os.getenv("DATABASE_URL"):
        return False
    try:
        from src.services.db import get_db
        with get_db() as db:
            db.cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _db_ok(), reason="Sin conexión a la base de datos")


@pytest.fixture(scope="session")
def sample_property_id():
    """Id de una propiedad activa real, para tests de lectura."""
    from src.services.db import get_db, fetch_one
    with get_db() as db:
        row = fetch_one(db.cursor, """
            SELECT id FROM propiedades
            WHERE activa = TRUE AND precio > 0 AND area_construida > 0
              AND ciudad ILIKE %s
            ORDER BY id LIMIT 1
        """, ("%medell%",))
    if not row:
        pytest.skip("No hay propiedades de prueba en la BD")
    return row["id"]
