"""
Utilidades del set de prueba del buscador.

Todo corre contra la base del .env en MODO SOLO LECTURA (PGOPTIONS hace que
cualquier escritura falle) y sin registrar uso de IA en ai_usage_log. Los datos
(pedidos reales, corridas y juicios) van en evals/search/data/, fuera de git:
pueden traer nombres y teléfonos.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).resolve().parent / "data"
DATA.mkdir(exist_ok=True)

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

# EVAL_RAMA_HOST=<host de una rama de Neon> cambia solo el host del DATABASE_URL
# (misma credencial). Sin rama, todo es de solo lectura contra la base del .env;
# en una rama se puede escribir (p. ej. para enriquecer fichas).
_RAMA = os.getenv("EVAL_RAMA_HOST")
if _RAMA:
    from urllib.parse import urlsplit, urlunsplit
    _p = urlsplit(os.environ["DATABASE_URL"])
    _cred, _, _hp = _p.netloc.rpartition("@")
    _port = (":" + _hp.split(":")[1]) if ":" in _hp else ""
    os.environ["DATABASE_URL"] = urlunsplit((_p.scheme, f"{_cred}@{_RAMA}{_port}", _p.path, _p.query, _p.fragment))
    assert _RAMA in os.environ["DATABASE_URL"]
    print("BD: rama", _RAMA, flush=True)
else:
    os.environ["PGOPTIONS"] = "-c default_transaction_read_only=on"


def sin_tracking() -> None:
    """Las corridas de evaluación no cuentan como uso real de IA."""
    from src.core import ai_usage_tracker
    ai_usage_tracker.AIUsageTracker.log_usage = lambda self, *a, **k: None


def leer_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def escribir_jsonl(path: Path, filas) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in filas:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def agregar_jsonl(path: Path, fila) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(fila, ensure_ascii=False, default=str) + "\n")


def conexion():
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=RealDictCursor)


CAMPOS_FICHA = """
    id, tipo_propiedad, tipo_negocio, precio, zona, ciudad, barrio_normalizado,
    area_construida, habitaciones, banos, parqueaderos, piso, estrato, administracion,
    ano_construccion, amenidades_destacadas, amenidades_internas, amenidades_externas,
    caracteristicas_adicionales, titulo, descripcion, descripcion_ai, activa
"""


def fichas(ids) -> dict:
    """Ficha compacta de cada inmueble (lo que ve el juez)."""
    ids = [int(i) for i in ids]
    if not ids:
        return {}
    with conexion() as c, c.cursor() as cur:
        cur.execute(f"SELECT {CAMPOS_FICHA} FROM propiedades WHERE id = ANY(%s)", (ids,))
        return {r["id"]: r for r in cur.fetchall()}


def ficha_texto(p: dict) -> str:
    def m(v):
        return f"${v / 1e6:,.0f} millones".replace(",", ".") if v else "?"
    partes = [
        f"{p.get('tipo_propiedad') or '?'} en {p.get('tipo_negocio') or 'venta'}",
        f"precio {m(p.get('precio'))}",
        f"zona {p.get('barrio_normalizado') or p.get('zona') or '?'}, {p.get('ciudad') or '?'}",
        f"{p.get('area_construida') or '?'} m2",
        f"{p.get('habitaciones') or '?'} hab, {p.get('banos') or '?'} baños, {p.get('parqueaderos') or 0} parq",
    ]
    for k, etq in (("piso", "piso"), ("estrato", "estrato"), ("ano_construccion", "año"),
                   ("administracion", "admin")):
        if p.get(k):
            partes.append(f"{etq} {p[k]}")
    amen = [p.get(k) for k in ("amenidades_destacadas", "amenidades_internas", "amenidades_externas",
                               "caracteristicas_adicionales")]
    amen = "; ".join(str(a) for a in amen if a)
    desc = (p.get("descripcion_ai") or p.get("descripcion") or "").replace("\n", " ")
    return " · ".join(partes) + (f"\nAmenidades: {amen[:400]}" if amen else "") + \
        (f"\nTítulo: {p.get('titulo') or ''}\nDescripción: {desc[:700]}" if desc or p.get("titulo") else "")
