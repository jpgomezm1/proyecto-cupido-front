"""
Arma el set de prueba con pedidos reales: el primer mensaje de conversaciones de
Findy de los últimos 6 meses, sin duplicados, de 25 a 1.500 caracteres.

    venv/Scripts/python evals/search/build_set.py --n 150
"""
import argparse
import random
import re
import unicodedata

from common import DATA, conexion, escribir_jsonl


def _clave(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if c.isalnum() or c.isspace())
    return re.sub(r"\s+", " ", t).strip()[:160]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--semilla", type=int, default=7)
    a = ap.parse_args()

    with conexion() as c, c.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (m.conversacion_id) m.id, m.conversacion_id, m.content, m.fecha_creacion
            FROM mensajes_conversacion m
            WHERE m.role = 'user' AND m.fecha_creacion > NOW() - INTERVAL '6 months'
            ORDER BY m.conversacion_id, m.fecha_creacion
        """)
        filas = cur.fetchall()

    vistos, candidatos = set(), []
    for f in filas:
        t = (f["content"] or "").strip()
        if not 25 <= len(t) <= 1500:
            continue
        if re.search(r"te comparto|https?://", t, re.I):  # compartidos o links, no son pedidos
            continue
        k = _clave(t)
        if k in vistos:
            continue
        vistos.add(k)
        candidatos.append({"qid": f"m{f['id']}", "query": t, "fecha": f["fecha_creacion"]})

    random.Random(a.semilla).shuffle(candidatos)
    elegidos = sorted(candidatos[: a.n], key=lambda r: r["qid"])
    escribir_jsonl(DATA / "queries.jsonl", elegidos)
    print(f"{len(candidatos)} pedidos únicos; set de prueba: {len(elegidos)} → {DATA / 'queries.jsonl'}")


if __name__ == "__main__":
    main()
