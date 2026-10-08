"""
Métricas de cada corrida sobre el set de prueba.

    venv/Scripts/python evals/search/report.py base v3a

  P@5        de los 5 primeros, cuántos sirven (grado ≥ 2); sin resultados cuenta 0
  nDCG@10    calidad del orden, contra el mejor orden posible con todo lo juzgado
  cero       % de pedidos sin ningún resultado
  incumple@5 % de los 5 primeros que incumplen algo obligatorio
  latencia   mediana y p90 en segundos
"""
import argparse
import math
import statistics

from common import DATA, fichas, leer_jsonl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corridas", nargs="+")
    a = ap.parse_args()

    juicios = {(j["qid"], j["id"]): j for j in leer_jsonl(DATA / "judgments.jsonl")}
    por_query = {}
    for (qid, _), j in juicios.items():
        por_query.setdefault(qid, []).append(j["grado"])

    print(f"{'corrida':12} {'n':>4} {'P@5':>6} {'nDCG@10':>8} {'cero':>6} {'incumple@5':>11} "
          f"{'inactivos':>10} {'p50 s':>6} {'p90 s':>6} {'sin juicio':>11}")
    for nombre in a.corridas:
        filas = leer_jsonl(DATA / "runs" / f"{nombre}.jsonl")
        activos = {i: p.get("activa") for i, p in fichas({i for f in filas for i in f["ids"] if i}).items()}
        p5, ndcg, cero, inc, inact, sinj, total5, ms = [], [], 0, 0, 0, 0, 0, []
        for f in filas:
            ms.append(f["ms"] / 1000)
            ids = [i for i in f["ids"] if i is not None]
            if not ids:
                cero += 1
            g = []
            for i in ids[:10]:
                j = juicios.get((f["qid"], i))
                if j is None:
                    sinj += 1
                g.append(j["grado"] if j else 0)
            top5 = ids[:5]
            p5.append(sum(1 for x in g[:5] if x >= 2) / 5)
            for i in top5:
                total5 += 1
                j = juicios.get((f["qid"], i))
                inc += bool(j and j["incumple_obligatorio"])
                inact += activos.get(i) is False
            ideal = sorted(por_query.get(f["qid"], []), reverse=True)[:10]
            dcg = sum((2 ** x - 1) / math.log2(k + 2) for k, x in enumerate(g))
            idcg = sum((2 ** x - 1) / math.log2(k + 2) for k, x in enumerate(ideal))
            ndcg.append(dcg / idcg if idcg else 0.0)
        n = len(filas)
        p90 = statistics.quantiles(ms, n=10)[-1] if len(ms) > 1 else ms[0]
        print(f"{nombre:12} {n:>4} {statistics.mean(p5):>6.3f} {statistics.mean(ndcg):>8.3f} "
              f"{100 * cero / n:>5.1f}% {100 * inc / max(1, total5):>10.1f}% "
              f"{100 * inact / max(1, total5):>9.1f}% {statistics.median(ms):>6.1f} {p90:>6.1f} {sinj:>11}")


if __name__ == "__main__":
    main()
