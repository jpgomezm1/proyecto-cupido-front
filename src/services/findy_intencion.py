"""
Una sola barra en Findy: qué quiere el agente con su mensaje.

  propiedades  busca inmuebles para un cliente («apto en Laureles, 3 hab, hasta 600»)
  compradores  tiene un inmueble y quiere saber quién lo busca (un link, «tengo un apto en…»)
  analisis     pregunta por el mercado («¿cómo está Belén?», «¿a cuánto capto…?», «compara…»)

Primero reglas (gratis y al instante); si no deciden, un mensaje corto que sigue la
conversación hereda el modo anterior; si tampoco, Haiku con un enum (< US$0,001).
Si la IA falla, se busca inmuebles: es lo que Findy hacía siempre.
"""

import re
import unicodedata
from typing import Optional, Tuple

MODOS = ("propiedades", "compradores", "analisis")

_URL = re.compile(r"https?://\S+", re.I)
_CODIGO = re.compile(r"(?:\bcod(?:igo)?\.?|#|\bref\.?)\s*:?\s*[a-z0-9-]*\d[a-z0-9-]*", re.I)

_TIPO = r"(apto|apartamento|apartaestudio|aparta ?estudio|casa|inmueble|propiedad|local|lote|finca|oficina|bodega|penthouse|duplex|consultorio)"

# Quién busca lo que tengo (manda sobre todo, salvo un link)
_COMPRADORES_FUERTE = re.compile(
    r"quien (lo |la |me lo |me la )?(busca|compra|necesita)|compradores? (para|de) |"
    r"a quien (se lo |se la |le )?(ofrezco|vendo|muestro)|busc\w* compradores?|tengo (un |una )?comprador", re.I)

# Preguntas de mercado
_ANALISIS = re.compile(
    r"\bcomo (esta|va|anda|se mueve)\b|a cuanto (lo |la )?(capto|vendo|pongo|publico|ofrezco|arriendo)|"
    r"cuanto (vale|cuesta|valen)\b.*\b(m2|metro|zona|barrio|sector)|precio (del|por) (m2|metro)|\bm2\b.*\b(zona|barrio)|"
    r"metro cuadrado|donde (capto|captar|conviene|me conviene|hay mas)|\bcompar(a|o|ar|ame|alo|ala)\b|"
    r"por que no se (vende|arrienda|mueve)|oferta (y|vs|contra) (la )?demanda|\bdemanda\b|cuanto se (demora|tarda)|"
    r"\bmercado\b|rentabilidad|valoriza|tendencia|\bvale la pena\b|\bconviene\b|\bdiagnostic", re.I)

# Tengo un inmueble (para moverlo)
_TENGO = re.compile(
    rf"\b(tengo|tenemos|capte|me (dieron|entregaron|encargaron)|estoy vendiendo|quiero vender|necesito vender|"
    rf"tengo para la venta|tengo en venta|mi)\b(\s+\w+){{0,3}}?\s+{_TIPO}\b", re.I)

# Busco para un cliente
_PROPIEDADES = re.compile(
    r"\b(busco|buscamos|necesito|necesita|requiero|cliente|clienta|muestrame|ensename|consigueme|pedido|"
    r"solicito|se busca|hay (algo|algun|alguna|apto))\b", re.I)


def _plano(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def por_reglas(texto: str, modo_previo: Optional[str] = None) -> Tuple[Optional[str], str]:
    """(modo o None si las reglas no deciden, por qué)."""
    t = _plano(texto).strip()
    if not t:
        return modo_previo or "propiedades", "vacio"
    if _URL.search(texto or "") or _CODIGO.search(t):
        return "compradores", "link_o_codigo"
    if _COMPRADORES_FUERTE.search(t):
        return "compradores", "quien_busca"
    cliente = re.search(r"\b(cliente|clienta)\b", t)
    if _ANALISIS.search(t) and not (cliente and re.search(r"\bbusc", t)):
        return "analisis", "pregunta_de_mercado"
    if _TENGO.search(t) and not cliente:
        return "compradores", "tengo_inmueble"
    if _PROPIEDADES.search(t):
        return "propiedades", "busco"
    # Sigue la conversación: «¿y si lo bajo a 590?», «solo las 5 mejores», «quita el ascensor»
    if modo_previo in MODOS and len(t) <= 140:
        return modo_previo, "sigue_conversacion"
    return None, "sin_senal"


_HERRAMIENTA = {
    "name": "intencion",
    "description": "Qué quiere el agente inmobiliario con su mensaje.",
    "input_schema": {"type": "object", "properties": {"modo": {"type": "string", "enum": list(MODOS)}},
                     "required": ["modo"]},
}
_SISTEMA = ("Clasificas el mensaje de un agente inmobiliario en Colombia. propiedades: busca inmuebles para un "
            "cliente. compradores: tiene un inmueble (lo describe o pega un link) y quiere saber quién lo compra. "
            "analisis: pregunta por el mercado, precios, zonas, comparaciones o por qué algo no se vende.")


def _con_ia(texto: str, modo_previo: Optional[str]) -> Optional[str]:
    try:
        import anthropic
        from src.services.busqueda import MODELO
        contenido = (f"Modo anterior de la conversación: {modo_previo}\n\n" if modo_previo else "") + texto[:1500]
        r = anthropic.Anthropic().messages.create(
            model=MODELO, max_tokens=50, system=_SISTEMA, tools=[_HERRAMIENTA],
            tool_choice={"type": "tool", "name": "intencion"}, messages=[{"role": "user", "content": contenido}])
        modo = next(b for b in r.content if b.type == "tool_use").input.get("modo")
        return modo if modo in MODOS else None
    except Exception as e:  # noqa: BLE001 — sin IA, se busca inmuebles
        print(f"[INTENCION] la IA no respondió: {type(e).__name__}: {str(e)[:120]}")
        return None


def clasificar(texto: str, modo_previo: Optional[str] = None) -> Tuple[str, str]:
    """(modo, por qué). `modo_previo`: el de la última respuesta de la conversación."""
    previo = "analisis" if modo_previo == "preanalisis" else modo_previo
    modo, razon = por_reglas(texto, previo)
    if modo:
        return modo, razon
    modo = _con_ia(texto, previo)
    return (modo, "ia") if modo else ("propiedades", "por_defecto")
