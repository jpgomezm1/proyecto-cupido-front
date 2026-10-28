"""
Las respuestas de Findy como programas OpenUI, armados aquí con los datos (sin IA).

Búsqueda, compradores y el pre-análisis se pintan con los mismos componentes que el modo
Análisis (mvp-tu360/src/lib/openui/): una sola estética. El programa va en
`search_response.ui`; las filas completas (inmuebles, pedidos) se quedan en `search_response`
y los componentes las leen del contexto del mensaje por id, así que aquí no se copian datos
del inmueble ni contactos.

OpenUI Lang: `nombre = Componente(arg1, arg2…)`, argumentos POSICIONALES en el orden de
esquemas.ts; strings entre comillas dobles con escapes; objetos `{clave: valor}`.
"""

import json
import re
from typing import Any, Dict, List, Optional


def _v(x: Any) -> str:
    """Un valor de Python en OpenUI Lang."""
    if x is None:
        return "null"
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, (int, float)):
        return str(int(x)) if float(x).is_integer() else str(round(float(x), 2))
    if isinstance(x, str):
        return json.dumps(x, ensure_ascii=False)
    if isinstance(x, (list, tuple)):
        return "[" + ", ".join(_v(i) for i in x) + "]"
    if isinstance(x, dict):
        return "{" + ", ".join(f"{k}: {_v(v)}" for k, v in x.items() if v is not None) + "}"
    return json.dumps(str(x), ensure_ascii=False)


def _llamada(componente: str, *args: Any) -> str:
    # Los opcionales del final que vienen en None se omiten (OpenUI permite cortar la cola).
    args_l = list(args)
    while args_l and args_l[-1] is None:
        args_l.pop()
    return f"{componente}({', '.join(_v(a) for a in args_l)})"


def _programa(bloques: List[str]) -> str:
    """root primero (para el streaming) y luego cada bloque con su nombre."""
    nombres = [f"b{i}" for i in range(len(bloques))]
    lineas = [f"root = Respuesta([{', '.join(nombres)}])"]
    lineas += [f"{n} = {b}" for n, b in zip(nombres, bloques)]
    return "\n".join(lineas)


def _millones(v: Optional[float]) -> Optional[str]:
    if not v:
        return None
    m = float(v) / 1e6
    return f"${m:,.0f} M".replace(",", ".") if m >= 10 else f"${m:.1f} M".replace(".", ",")


# ─────────────────────────────────────────────────────────────────────────────
# Búsqueda de inmuebles
# ─────────────────────────────────────────────────────────────────────────────

def _siguientes_busqueda(criteria: Dict[str, Any], total: int) -> List[str]:
    ped = criteria.get("pedido_v3") or {}
    out = []
    if total > 5:
        out.append("Déjame solo las 5 mejores")
    if ped.get("presupuesto_max"):
        out.append(f"Súbele el presupuesto a {_millones(ped['presupuesto_max'] * 1.1)}")
    if ped.get("ubicaciones"):
        out.append("Busca también en zonas cercanas")
    return out[:3]


def _sin_dato(results: List[Dict[str, Any]]) -> List[str]:
    """Lo que pidió el agente y casi ninguna publicación trae (el piso, en Medellín, nunca viene):
    mejor decirlo una vez que dejar un «?» sin explicación en cada tarjeta."""
    if not results:
        return []
    cuenta: Dict[str, List[int]] = {}
    for r in results:
        for q in r.get("requisitos") or []:
            texto = q.get("texto") or ""
            # «3+ hab», «piso 4+», «balcón»: se agrupan por lo que se pide, no por el número
            clave = "piso" if texto.startswith(("piso", "hasta piso")) else texto
            par = cuenta.setdefault(clave, [0, 0])
            par[0] += 1
            par[1] += q.get("estado") == "duda"
    return [k for k, (n, dudas) in cuenta.items() if n >= 3 and dudas / n >= 0.8]


def programa_busqueda(mensaje: str, criteria: Dict[str, Any], results: List[Dict[str, Any]],
                      search_response: Dict[str, Any]) -> str:
    bloques = [_llamada("Texto", mensaje)]
    chips = criteria.get("chips") or []
    if chips:
        bloques.append(_llamada("Entendi", chips))
    if search_response.get("relaxation_applied"):
        bloques.append(_llamada("Aviso", "No encontré exactamente lo que pediste: estas son las opciones más cercanas.", "info"))
    faltan = _sin_dato(results)
    if faltan:
        lista = " ni ".join(faltan) if len(faltan) <= 2 else ", ".join(faltan[:-1]) + " ni " + faltan[-1]
        bloques.append(_llamada("Aviso", f"Las publicaciones casi nunca dicen {'el ' if faltan == ['piso'] else ''}"
                                         f"{lista}: los marqué con «?». Confírmalo con quien tiene el inmueble antes "
                                         f"de mostrárselo a tu cliente.", "info"))
    ids = [r["id"] for r in results if r.get("id")][:10]
    if ids:
        titulo = f"{len(ids)} {'inmueble' if len(ids) == 1 else 'inmuebles'} para tu cliente"
        comparar = search_response.get("comparar")
        bloques.append(_llamada("Inmuebles", titulo, ids, comparar) if comparar else _llamada("Inmuebles", titulo, ids))
    elif search_response.get("search_type") != "no_es_busqueda":
        bloques.append(_llamada("Siguientes", ["Busca también en zonas cercanas", "Súbele el presupuesto un 10 %"]))
        return _programa(bloques)
    sig = _siguientes_busqueda(criteria, len(ids))
    if sig:
        bloques.append(_llamada("Siguientes", sig))
    return _programa(bloques)


# ─────────────────────────────────────────────────────────────────────────────
# Tengo un inmueble: quién lo busca
# ─────────────────────────────────────────────────────────────────────────────

_ESPECIFICACIONES = (("area_m2", "{:.0f} m²"), ("habitaciones", "{} hab"), ("banos", "{} baños"), ("parqueaderos", "{} parq"))


def _tu_inmueble(p: Dict[str, Any]) -> str:
    titulo = p.get("titulo") or " en ".join(x for x in [(p.get("tipo") or "Inmueble").capitalize(), p.get("zona")] if x)
    specs = [f.format(p[k]) for k, f in _ESPECIFICACIONES if p.get(k)]
    origen = {"wasi": "De Wasi", "lobbie": "De Lobbie", "fynder": "En Fynder", "texto": "Descrito por ti"}.get(p.get("origen"))
    return _llamada("TuInmueble", titulo, p.get("precio_legible"), specs or None, origen)


def _item_comprador(c: Dict[str, Any]) -> Dict[str, Any]:
    return {"resumen": c["busca"], "presupuesto": c.get("presupuesto_legible"), "encaje": c.get("score"),
            "pedido": c["pedido_id"], "nivel": c.get("nivel"), "hace": c.get("hace") or None,
            "porque": c.get("porque") or None, "accion": c.get("accion")}


def _contexto_compradores(ctx: Optional[Dict[str, Any]]) -> List[str]:
    """Lo que piden quienes encajan (barras) y un aviso con el presupuesto típico y cómo pagan."""
    if not ctx or not ctx.get("pedidos"):
        return []
    n = ctx["pedidos"]
    bloques = []
    if ctx.get("pide"):
        bloques.append(_llamada("Barras", "Lo que más piden quienes encajan con tu inmueble",
                                [{"etiqueta": p["texto"].capitalize(), "valor": p["n"],
                                  "texto": f"{p['n']} de {n}"} for p in ctx["pide"]],
                                "Úsalo al presentarlo: si lo tiene, dilo de primero"))
    partes = []
    if ctx.get("presupuesto_mediana"):
        partes.append(f"la mitad tiene presupuesto de hasta {_millones(ctx['presupuesto_mediana'])}")
    if ctx.get("pagan_contado"):
        partes.append(f"{ctx['pagan_contado']} pagan de contado")
    if ctx.get("con_credito"):
        partes.append(f"{ctx['con_credito']} con crédito")
    if partes:
        bloques.append(_llamada("Aviso", "De los que encajan: " + ", ".join(partes) + ".", "info"))
    return bloques


def programa_compradores(mensaje: str, propiedad: Optional[Dict[str, Any]], compradores: List[Dict[str, Any]],
                         conteos: Optional[Dict[str, int]], total: int,
                         contexto: Optional[Dict[str, Any]] = None) -> str:
    bloques = [_llamada("Texto", mensaje)]
    if propiedad:
        bloques.append(_tu_inmueble(propiedad))
    if not compradores:
        bloques.append(_llamada("Siguientes", ["¿A cuánto lo capto?", "¿Cómo está la zona?"]))
        return _programa(bloques)
    conteos = conteos or {}
    bloques.append(_llamada("Cifras", [
        {"valor": f"{total}", "etiqueta": "pedidos encajan", "detalle": "en los últimos 4 meses"},
        {"valor": f"{conteos.get('recientes', 0)}", "etiqueta": "del último mes"},
        {"valor": f"{conteos.get('perfecto', 0)}", "etiqueta": "encajan perfecto"},
    ]))
    bloques += _contexto_compradores(contexto)
    top = [c for c in compradores if c.get("grupo") == "top"]
    vale = [c for c in compradores if c.get("grupo") == "vale_la_pena"][:12]
    bloques.append(_llamada("Compradores", f"Empieza por {'este' if len(top) == 1 else f'estos {len(top)}'}",
                            [_item_comprador(c) for c in top]))
    if vale:
        bloques.append(_llamada("Compradores", "Otro que vale la pena" if len(vale) == 1 else f"Otros {len(vale)} que valen la pena",
                                [_item_comprador(c) for c in vale], True))
    if all(c.get("accion") == "conectar" for c in top + vale):
        bloques.append(_llamada("Aviso", "Quienes hicieron estos pedidos todavía no están en Fynder: toca "
                                         "«Te conectamos» y el equipo de Fynder te pone en contacto.", "info"))
    precio = (propiedad or {}).get("precio")
    sig = []
    if precio:
        sig.append(f"¿Y si lo bajo a {_millones(precio * 0.93)}?")
    sig += ["¿A cuánto lo capto?", "¿Cómo está la zona?"]
    bloques.append(_llamada("Siguientes", sig[:3]))
    return _programa(bloques)


# ─────────────────────────────────────────────────────────────────────────────
# Pregunta de mercado: lo que se sabe gratis + «Analizarlo a fondo»
# ─────────────────────────────────────────────────────────────────────────────

def _espejo_precios(zona: str, rangos: List[Dict[str, Any]]) -> Optional[str]:
    """Oferta contra demanda por rango de precio (datos reales, sin IA) con el rango donde más compradores
    hay por inmueble en venta. Solo los rangos con algo de oferta o de demanda."""
    filas = [r for r in rangos or [] if (r.get("oferta") or 0) + (r.get("demanda") or 0) > 0]
    if len(filas) < 2:
        return None
    con_oferta = [r for r in filas if (r.get("oferta") or 0) >= 5] or filas
    mejor = max(con_oferta, key=lambda r: (r.get("demanda") or 0) / max(r.get("oferta") or 0, 1))
    etiqueta = lambda t: re.sub(r"(\d)M\b", r"\1 M", t)  # noqa: E731 — «$500M» → «$500 M»
    rango = etiqueta(mejor["rango"])
    titulo = (f"En {zona} hay más compradores que apartamentos en venta en el rango {rango}"
              if (mejor.get("demanda") or 0) > (mejor.get("oferta") or 0)
              else f"En {zona}, el rango con más compradores por apartamento: {rango}")
    return _llamada("Espejo", titulo,
                    "En venta", "Compradores",
                    [{"etiqueta": etiqueta(r["rango"]), "izq": r.get("oferta") or 0, "der": r.get("demanda") or 0} for r in filas],
                    "En venta hoy contra pedidos de los últimos 90 días, por presupuesto")


def programa_preanalisis(pregunta: str, zona: Optional[str], balance: Optional[Dict[str, Any]],
                         rangos: Optional[List[Dict[str, Any]]] = None) -> str:
    bloques = []
    oferta = (balance or {}).get("oferta_inventario") or 0
    if zona and oferta:
        det = balance.get("detalle_oferta") or {}
        estado = {"caliente": "está caliente: hay más compradores que oferta",
                  "equilibrado": "está equilibrada",
                  "frio": "está fría: sobra oferta"}.get(balance.get("clasificacion"), "")
        bloques.append(_llamada("Texto", f"**{zona} {estado}** en apartamentos. Esto es lo que Fynder ve hoy; si quieres "
                                         f"el análisis completo (precio, comparables, dónde está el hueco), pídemelo abajo."))
        cifras = [{"valor": f"{oferta}", "etiqueta": "apartamentos en venta hoy"},
                  {"valor": f"{balance.get('demanda_total', 0)}", "etiqueta": "compradores", "detalle": "últimos 90 días"}]
        if det.get("precio_m2_mediana"):
            cifras.append({"valor": f"${det['precio_m2_mediana'] / 1e6:.1f} M".replace(".", ","), "etiqueta": "el m² de apartamento"})
        if det.get("dias_inventario_promedio"):
            cifras.append({"valor": f"{round(det['dias_inventario_promedio'])} días", "etiqueta": "en venta, en promedio"})
        bloques.append(_llamada("Cifras", cifras))
        espejo = _espejo_precios(zona, rangos or [])
        if espejo:
            bloques.append(espejo)
    else:
        bloques.append(_llamada("Texto", "Esta pregunta necesita un análisis de mercado: Findy cruza oferta, "
                                         "demanda y precios y te responde con gráficas."))
    bloques.append(_llamada("AnalizarAFondo", pregunta))
    return _programa(bloques)
