"""
Juez con IA: califica cada par (pedido, inmueble) que aparezca en alguna corrida
y no tenga juicio todavía. Los juicios se guardan en data/judgments.jsonl y se
reutilizan, así comparar un motor nuevo solo juzga lo que no se había visto.

    venv/Scripts/python evals/search/judge.py base v3a

Escala (la de un agente que tiene que mandarle opciones a su cliente):
  3 encaja: cumple todo lo obligatorio y casi todas las preferencias
  2 buena opción: cumple lo obligatorio; falla alguna preferencia
  1 marginal: incumple algo obligatorio pero cerca (precio ≤ 15 % arriba,
    una habitación menos, zona vecina, tipo parecido)
  0 no sirve
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from common import DATA, agregar_jsonl, ficha_texto, fichas, leer_jsonl

MODELO = os.getenv("EVAL_JUEZ_MODELO", "claude-sonnet-4-6")

_HERRAMIENTA = {
    "name": "calificar",
    "description": "Califica cada inmueble candidato contra el pedido.",
    "input_schema": {
        "type": "object",
        "properties": {
            "calificaciones": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "grado": {"type": "integer", "enum": [0, 1, 2, 3]},
                        "incumple_obligatorio": {"type": "boolean"},
                        "razon": {"type": "string", "description": "Máximo 15 palabras."},
                    },
                    "required": ["id", "grado", "incumple_obligatorio", "razon"],
                },
            }
        },
        "required": ["calificaciones"],
    },
}

_SISTEMA = """Eres un agente inmobiliario senior de Medellín y el Valle de Aburrá. Un colega te \
pasa el pedido de su cliente y una lista de inmuebles candidatos. Califica cada candidato como si \
tuvieras que decidir si se lo mandas al cliente.

Escala:
3 = encaja: cumple todo lo obligatorio (tipo, presupuesto, zona, mínimos de habitaciones/área, \
exclusiones) y casi todas las preferencias.
2 = buena opción: cumple lo obligatorio; falla alguna preferencia.
1 = marginal: incumple algo obligatorio pero cerca (precio hasta 15 % sobre el presupuesto, una \
habitación menos, barrio vecino al pedido, tipo parecido).
0 = no sirve (otra zona, muy por fuera del presupuesto, otro tipo, arriendo cuando piden compra, \
una zona que el pedido excluye).

Reglas: el presupuesto "hasta X" es un techo; algo muy por debajo del presupuesto también puede \
no servir si el pedido apunta a otro segmento. Conoce la geografía: El Poblado, Envigado, \
Sabaneta, Laureles, Belén, Oriente (Rionegro, La Ceja, Llanogrande), etc. Si falta un dato en la \
ficha, no lo cuentes como incumplido salvo que sea crítico. Califica TODOS los ids."""


def _juzgar(cliente, query, cands):
    lista = "\n\n".join(f"[id {p['id']}] {ficha_texto(p)}" for p in cands)
    r = cliente.messages.create(
        model=MODELO, max_tokens=4000, system=_SISTEMA,
        tools=[_HERRAMIENTA], tool_choice={"type": "tool", "name": "calificar"},
        messages=[{"role": "user", "content": f"PEDIDO:\n{query}\n\nCANDIDATOS:\n{lista}"}],
    )
    bloque = next(b for b in r.content if b.type == "tool_use")
    return bloque.input["calificaciones"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corridas", nargs="+")
    ap.add_argument("--hilos", type=int, default=4)
    a = ap.parse_args()

    import anthropic
    cliente = anthropic.Anthropic()
    queries = {q["qid"]: q["query"] for q in leer_jsonl(DATA / "queries.jsonl")}
    ruta = DATA / "judgments.jsonl"
    hechos = {(j["qid"], j["id"]) for j in leer_jsonl(ruta)}

    pendientes = {}
    for nombre in a.corridas:
        for fila in leer_jsonl(DATA / "runs" / f"{nombre}.jsonl"):
            for pid in fila["ids"]:
                if pid is not None and (fila["qid"], pid) not in hechos:
                    pendientes.setdefault(fila["qid"], set()).add(pid)
    if not pendientes:
        print("Nada nuevo que juzgar.")
        return

    todas = fichas({p for ids in pendientes.values() for p in ids})
    print(f"Juzgando {sum(len(v) for v in pendientes.values())} pares en {len(pendientes)} pedidos con {MODELO}…")

    def uno(item):
        qid, ids = item
        cands = [todas[i] for i in sorted(ids) if i in todas]
        try:
            notas = _juzgar(cliente, queries[qid], cands)
        except Exception as e:  # noqa: BLE001
            print(f"  {qid}: error {e}", file=sys.stderr)
            return []
        validos = {p["id"] for p in cands}
        return [dict(n, qid=qid) for n in notas if n.get("id") in validos]

    with ThreadPoolExecutor(a.hilos) as pool:
        for notas in pool.map(uno, pendientes.items()):
            for n in notas:
                agregar_jsonl(ruta, n)
    print("Listo →", ruta)


if __name__ == "__main__":
    main()
