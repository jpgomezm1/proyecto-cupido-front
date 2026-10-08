"""
Corre un motor de búsqueda sobre el set de prueba y guarda los 10 primeros de cada pedido.

    venv/Scripts/python evals/search/run.py --motor actual --nombre base
    venv/Scripts/python evals/search/run.py --motor v3 --nombre v3a

Cada motor es una función (query) -> {ids, criterios, tipo, ms}.
"""
import argparse
import time
from concurrent.futures import ThreadPoolExecutor

from common import DATA, escribir_jsonl, leer_jsonl, sin_tracking


def motor_actual():
    from src.core.search_agent import PropertySearchAgent, MODEL
    agente = PropertySearchAgent(model=MODEL)

    def buscar(query):
        r = agente.search(query=query, limit=10)
        return {
            "ids": [p.get("id") for p in (r.get("results") or [])][:10],
            "criterios": r.get("criteria"),
            "tipo": r.get("search_type") or r.get("error_type"),
        }
    return buscar


def motor_v3(reordenar=None):
    from src.services.busqueda import buscar as buscar_v3

    def buscar(query):
        r = buscar_v3(query, limite=10, reordenar=reordenar)
        return {"ids": [p["id"] for p in r["resultados"]][:10], "criterios": r.get("pedido"),
                "tipo": r.get("tipo")}
    return buscar


MOTORES = {"actual": motor_actual, "v3": motor_v3,
           "v3ia": lambda: motor_v3("ia"), "v3jev": lambda: motor_v3("jev")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--motor", choices=sorted(MOTORES), required=True)
    ap.add_argument("--nombre", required=True)
    ap.add_argument("--hilos", type=int, default=4)
    ap.add_argument("--limite", type=int, default=0, help="solo los primeros N pedidos")
    a = ap.parse_args()

    sin_tracking()
    queries = leer_jsonl(DATA / "queries.jsonl")
    if a.limite:
        queries = queries[: a.limite]
    buscar = MOTORES[a.motor]()

    def uno(q):
        t = time.time()
        try:
            r = buscar(q["query"])
        except Exception as e:  # noqa: BLE001 — una falla cuenta como cero resultados
            r = {"ids": [], "criterios": None, "tipo": f"error: {str(e)[:120]}"}
        r.update(qid=q["qid"], ms=round((time.time() - t) * 1000))
        return r

    with ThreadPoolExecutor(a.hilos) as pool:
        filas = list(pool.map(uno, queries))
    (DATA / "runs").mkdir(exist_ok=True)
    escribir_jsonl(DATA / "runs" / f"{a.nombre}.jsonl", filas)
    print(f"{len(filas)} pedidos → runs/{a.nombre}.jsonl")


if __name__ == "__main__":
    main()
