"""
Reordenamiento con Jev (TypeSafe AI): un modelo que no genera texto sino que
responde preguntas tipadas con probabilidades calibradas. Por cada uno de los
mejores candidatos le preguntamos qué tan bien encaja con el pedido (escala de
4 niveles, la misma del juez) y, por cada característica obligatoria o deseable
que la ficha no confirma, si el inmueble la tiene.

Es mucho más barato y rápido que reordenar con un LLM: ~$0,042 por millón de
tokens de entrada, salida gratis, 70–500 ms por llamada, en paralelo.
Requiere TYPESAFE_API_KEY; sin llave (o si falla) devuelve el orden recibido.
"""

import asyncio
import json
import os
from typing import Any, Dict, List

MODELO_JEV = os.getenv("FYNDER_MODELO_JEV", "jev-1.13.0")
N_CANDIDATOS = int(os.getenv("FYNDER_JEV_CANDIDATOS", "25"))
PESO_JEV = float(os.getenv("FYNDER_JEV_PESO", "0.65"))

_NIVELES = [
    "No sirve: otra zona, muy fuera del presupuesto, otro tipo o una zona excluida",
    "Marginal: incumple algo obligatorio pero cerca (precio hasta 15 % arriba, una habitación menos, barrio vecino)",
    "Buena opción: cumple lo obligatorio y falla alguna preferencia",
    "Encaja: cumple lo obligatorio y casi todas las preferencias",
]


def _estado(texto: str, ped: Dict[str, Any], r: Dict[str, Any]) -> Dict[str, Any]:
    from src.services.busqueda import _ficha_corta
    pedido = {k: v for k, v in ped.items() if not k.startswith("_") and v not in (None, [], "")}
    return {"pedido_del_agente": texto[:1500], "pedido_estructurado": json.dumps(pedido, ensure_ascii=False),
            "inmueble": _ficha_corta(r["_p"])}


def _preguntas(ped: Dict[str, Any], r: Dict[str, Any]):
    from typesafe_sdk import Noul, Score
    from src.services.busqueda import _ETIQUETAS_CARACT
    qs = {"encaje": Score(
        instructions="¿Qué tan bien encaja el `inmueble` con el pedido del cliente, para un agente "
                     "inmobiliario de Medellín que decide si se lo envía?",
        criteria=_NIVELES)}
    tiene = set(r["_p"].get("caracteristicas") or [])
    pedidas = list(ped.get("obligatorias") or []) + [d["caracteristica"] for d in ped.get("deseables") or []]
    for c in pedidas[:4]:
        if c not in tiene:
            qs[f"c_{c}"] = Noul(instructions=f"Según la ficha, ¿el inmueble tiene {_ETIQUETAS_CARACT.get(c, c)}?")
    return qs


async def _todos(texto, ped, top):
    from typesafe_sdk import AsyncTypeSafeClient
    async with AsyncTypeSafeClient(model=MODELO_JEV, timeout=8) as cliente:
        async def uno(r):
            try:
                return await cliente.system_one(state=_estado(texto, ped, r), questions=_preguntas(ped, r))
            except Exception:  # noqa: BLE001 — ese candidato conserva su puntaje
                return None
        return await asyncio.gather(*(uno(r) for r in top))


def reordenar_jev(texto: str, ped: Dict[str, Any], resultados: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not os.getenv("TYPESAFE_API_KEY") or len(resultados) < 2:
        return resultados
    top = resultados[:N_CANDIDATOS]
    try:
        respuestas = asyncio.run(_todos(texto, ped, top))
    except Exception:  # noqa: BLE001
        return resultados
    from src.services.busqueda import _ETIQUETAS_CARACT
    for r, resp in zip(top, respuestas):
        if resp is None:
            continue
        enc = resp.scores["encaje"].score  # promedio ponderado por probabilidad, 0..3
        r["grado_jev"] = round(float(enc), 2)
        for k, a in (resp.nouls or {}).items():
            if k.startswith("c_") and a.noul >= 0.7:
                r.setdefault("cumple", []).append(_ETIQUETAS_CARACT.get(k[2:], k[2:]) + " (probable)")
        r["score_final"] = round(100 * (PESO_JEV * enc / 3 + (1 - PESO_JEV) * r["score"] / 100), 1)
    top.sort(key=lambda x: x.get("score_final", x["score"]), reverse=True)
    return top + resultados[N_CANDIDATOS:]
