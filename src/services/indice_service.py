"""
Índice Fynder mensual (migración 064; benchmark Idealista en negocio/estrategia/benchmark-idealista.md).

Una foto del mercado al cierre de cada mes, por zona (las comunas de Medellín y cada municipio):
cuántos inmuebles hay en venta, el precio por m² de los apartamentos (mediana y donde se mueve la
mayoría), cuántos llegaron, cuántos se dieron de baja y cuántos pedidos de clientes hubo. Es lo
que Fynder sabe y un portal no publica: la demanda.

Reglas: son precios de publicación (no de cierre); una zona con menos de 15 inmuebles en venta no
se publica; la variación sale contra la edición anterior (no hay historia confiable antes de
oct-2026, cuando empezó a registrarse la fecha de baja). Sin IA.

Flujo: el worker calcula el mes que cerró (`cerrar_mes_si_falta`, borrador); el admin lo revisa,
le pone titular y lo publica; /indice muestra solo lo publicado.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.services import facetas
from src.services.db import fetch_all, fetch_one, get_db, scalar

BOGOTA = timezone(timedelta(hours=-5))
MIN_ACTIVOS = 15
# El m² de una zona solo sale con 30 apartamentos: con menos, unos pocos proyectos nuevos la mueven
# (oct-2026: Guayabal con 18, casi todos obra nueva, salía más caro que El Poblado).
MIN_APTOS = 30
TOTAL = "Total"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]


class IndiceError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def _mes(valor: Any) -> date:
    """'2026-10', '2026-10-01' o date → primer día del mes."""
    if isinstance(valor, date):
        return valor.replace(day=1)
    try:
        a, m = str(valor)[:7].split("-")
        return date(int(a), int(m), 1)
    except (ValueError, AttributeError):
        raise IndiceError("mes_invalido", "El mes va como AAAA-MM.")


def _siguiente(m: date) -> date:
    return date(m.year + (m.month == 12), m.month % 12 + 1, 1)


def nombre_mes(m: date) -> str:
    return f"{MESES[m.month - 1]} de {m.year}"


# La zona de un inmueble o un pedido: la comuna si es Medellín, si no el municipio.
_MUNI = "COALESCE(b.municipio, pb.municipio)"
_ZONA = f"CASE WHEN {_MUNI} = 'Medellín' AND b.comuna IS NOT NULL THEN b.comuna ELSE {_MUNI} END"
# m² de apartamentos sin basura (áreas o precios imposibles).
_M2_OK = "x.area BETWEEN 25 AND 400 AND p.precio / x.area BETWEEN 1000000 AND 40000000"


def _calcular_filas(cur, mes: date) -> List[Dict[str, Any]]:
    ini, fin = mes, _siguiente(mes)
    # GROUPING(...) = 1 marca la fila del total (todas las zonas).
    stock = fetch_all(cur, f"""
        SELECT CASE WHEN GROUPING(t.zona) = 1 THEN NULL ELSE t.zona END AS zona, t.municipio,
               GROUPING(t.zona) AS es_total, COUNT(*) AS activos,
               COUNT(*) FILTER (WHERE t.apto) AS aptos,
               percentile_cont(0.25) WITHIN GROUP (ORDER BY t.m2) FILTER (WHERE t.apto) AS m2_p25,
               percentile_cont(0.50) WITHIN GROUP (ORDER BY t.m2) FILTER (WHERE t.apto) AS m2_mediana,
               percentile_cont(0.75) WITHIN GROUP (ORDER BY t.m2) FILTER (WHERE t.apto) AS m2_p75
        FROM (
            SELECT {_ZONA} AS zona, {_MUNI} AS municipio, p.precio / NULLIF(x.area, 0) AS m2,
                   (x.tipo ILIKE 'apartamento' AND {_M2_OK}) AS apto
            FROM propiedades p {facetas.JOIN}
            WHERE p.activa AND p.tipo_negocio = 'Venta' AND p.precio > 0 AND {_MUNI} IS NOT NULL
        ) t
        GROUP BY GROUPING SETS ((t.zona, t.municipio), ())
    """)
    nuevos = fetch_all(cur, f"""
        SELECT CASE WHEN GROUPING(t.zona) = 1 THEN NULL ELSE t.zona END AS zona, COUNT(*) AS n
        FROM (SELECT {_ZONA} AS zona FROM propiedades p {facetas.JOIN}
              WHERE p.tipo_negocio = 'Venta' AND p.fecha_creacion >= %s AND p.fecha_creacion < %s
                AND {_MUNI} IS NOT NULL) t
        GROUP BY GROUPING SETS ((t.zona), ())
    """, (ini, fin))
    salieron = fetch_all(cur, f"""
        SELECT CASE WHEN GROUPING(t.zona) = 1 THEN NULL ELSE t.zona END AS zona, COUNT(DISTINCT t.id) AS n
        FROM (SELECT p.id, {_ZONA} AS zona
              FROM verificaciones_disponibilidad v JOIN propiedades p ON p.id = v.propiedad_id {facetas.JOIN}
              WHERE v.veredicto = 'muerto' AND v.created_at >= %s AND v.created_at < %s
                AND p.tipo_negocio = 'Venta' AND {_MUNI} IS NOT NULL) t
        GROUP BY GROUPING SETS ((t.zona), ())
    """, (ini, fin))
    pedidos = fetch_all(cur, """
        SELECT CASE WHEN GROUPING(t.zona) = 1 THEN NULL ELSE t.zona END AS zona, COUNT(DISTINCT t.id) AS n
        FROM (SELECT pe.id, CASE WHEN b.municipio = 'Medellín' AND b.comuna IS NOT NULL THEN b.comuna ELSE b.municipio END AS zona
              FROM pedidos pe CROSS JOIN LATERAL unnest(pe.barrio_ids) AS bid JOIN barrios b ON b.id = bid
              WHERE pe.fecha_captura >= %s AND pe.fecha_captura < %s) t
        GROUP BY GROUPING SETS ((t.zona), ())
    """, (ini, fin))

    def por_zona(filas):
        return {(f["zona"] or TOTAL): int(f["n"] or 0) for f in filas}
    n_nuevos, n_salieron, n_pedidos = por_zona(nuevos), por_zona(salieron), por_zona(pedidos)

    filas = []
    for s in stock:
        zona = TOTAL if s["es_total"] else s["zona"]
        # Medellín sin comuna (barrio sin asignar) cuenta en el total, pero no es una zona.
        if not zona or (zona == "Medellín" and s["municipio"] == "Medellín"):
            continue
        nivel = "total" if zona == TOTAL else ("comuna" if s["municipio"] == "Medellín" and zona != "Medellín" else "municipio")
        filas.append({
            "zona": zona, "nivel": nivel, "municipio": None if zona == TOTAL else s["municipio"],
            "activos": int(s["activos"]), "aptos": int(s["aptos"]),
            "m2_p25": round(s["m2_p25"]) if s["m2_p25"] else None,
            "m2_mediana": round(s["m2_mediana"]) if s["m2_mediana"] else None,
            "m2_p75": round(s["m2_p75"]) if s["m2_p75"] else None,
            "nuevos": n_nuevos.get(zona, 0), "salieron": n_salieron.get(zona, 0), "pedidos": n_pedidos.get(zona, 0),
            "suficiente": int(s["activos"]) >= MIN_ACTIVOS,
        })
    return filas


def calcular(mes: Any) -> Dict[str, Any]:
    """Calcula (o recalcula) la edición de un mes como borrador. Una publicada no se toca."""
    m = _mes(mes)
    hoy = datetime.now(BOGOTA).date()
    if m > hoy:
        raise IndiceError("mes_futuro", "Ese mes todavía no empieza.")
    with get_db() as db:
        cur = db.cursor
        ed = fetch_one(cur, "SELECT estado FROM indice_ediciones WHERE mes = %s", (m,))
        if ed and ed["estado"] == "publicado":
            raise IndiceError("publicado", "Esa edición ya está publicada; no se recalcula.")
        filas = _calcular_filas(cur, m)
        previas = {f["zona"]: f for f in fetch_all(cur, """
            SELECT zona, m2_mediana, suficiente FROM indice_mensual
            WHERE mes = (SELECT MAX(mes) FROM indice_ediciones WHERE mes < %s)
        """, (m,))}
        cur.execute("""
            INSERT INTO indice_ediciones (mes) VALUES (%s)
            ON CONFLICT (mes) DO UPDATE SET calculado_at = NOW()
        """, (m,))
        cur.execute("DELETE FROM indice_mensual WHERE mes = %s", (m,))
        for f in filas:
            p = previas.get(f["zona"])
            var = None
            if p and p["suficiente"] and f["suficiente"] and p["m2_mediana"] and f["m2_mediana"]:
                var = round((float(f["m2_mediana"]) / float(p["m2_mediana"]) - 1) * 100, 2)
            cur.execute("""
                INSERT INTO indice_mensual (mes, zona, nivel, municipio, activos, aptos, m2_p25, m2_mediana, m2_p75,
                                            var_m2_pct, nuevos, salieron, pedidos, suficiente)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (m, f["zona"], f["nivel"], f["municipio"], f["activos"], f["aptos"], f["m2_p25"], f["m2_mediana"],
                  f["m2_p75"], var, f["nuevos"], f["salieron"], f["pedidos"], f["suficiente"]))
        db.conn.commit()
    return edicion(m, publico=False)


def cerrar_mes_si_falta() -> Optional[Dict[str, Any]]:
    """Para el worker: el día 1 o 2, calcula el mes que acaba de cerrar si todavía no existe."""
    hoy = datetime.now(BOGOTA).date()
    if hoy.day > 2:
        return None
    anterior = (hoy.replace(day=1) - timedelta(days=1)).replace(day=1)
    with get_db() as db:
        if scalar(db.cursor, "SELECT 1 FROM indice_ediciones WHERE mes = %s", (anterior,)):
            return None
    r = calcular(anterior)
    return {"mes": anterior.isoformat(), "zonas": len(r["zonas"])}


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def _destacados(zonas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Lo que va en el titular: lo más caro, lo más demandado, lo que más subió y bajó."""
    con_m2 = [z for z in zonas if z["m2_mediana"] and z["aptos"] >= MIN_APTOS]
    con_var = [z for z in con_m2 if z["var_m2_pct"] is not None]
    demanda = sorted((z for z in zonas if z["activos"] and z["pedidos"]), key=lambda z: z["pedidos"] / z["activos"], reverse=True)

    def mini(z):
        return {k: z[k] for k in ("zona", "m2_mediana", "var_m2_pct", "pedidos", "activos")} if z else None
    return {
        "mas_caras": [mini(z) for z in sorted(con_m2, key=lambda z: z["m2_mediana"], reverse=True)[:3]],
        "mas_baratas": [mini(z) for z in sorted(con_m2, key=lambda z: z["m2_mediana"])[:3]],
        "mas_demanda": [{**mini(z), "pedidos_por_100": round(z["pedidos"] * 100 / z["activos"], 1)} for z in demanda[:3]],
        "subieron": [mini(z) for z in sorted(con_var, key=lambda z: z["var_m2_pct"], reverse=True)[:3] if z["var_m2_pct"] > 0],
        "bajaron": [mini(z) for z in sorted(con_var, key=lambda z: z["var_m2_pct"])[:3] if z["var_m2_pct"] < 0],
    }


def _fila(f: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "zona": f["zona"], "nivel": f["nivel"], "municipio": f["municipio"],
        "activos": f["activos"], "aptos": f["aptos"],
        "m2_p25": int(f["m2_p25"]) if f["m2_p25"] else None,
        "m2_mediana": int(f["m2_mediana"]) if f["m2_mediana"] else None,
        "m2_p75": int(f["m2_p75"]) if f["m2_p75"] else None,
        "var_m2_pct": float(f["var_m2_pct"]) if f["var_m2_pct"] is not None else None,
        "nuevos": f["nuevos"], "salieron": f["salieron"], "pedidos": f["pedidos"], "suficiente": f["suficiente"],
    }


def edicion(mes: Any, publico: bool = True) -> Dict[str, Any]:
    m = _mes(mes)
    with get_db() as db:
        cur = db.cursor
        ed = fetch_one(cur, "SELECT * FROM indice_ediciones WHERE mes = %s", (m,))
        if not ed or (publico and ed["estado"] != "publicado"):
            raise IndiceError("no_encontrado", "Esa edición del índice no existe o no está publicada.")
        filas = [_fila(f) for f in fetch_all(cur, """
            SELECT * FROM indice_mensual WHERE mes = %s ORDER BY nivel = 'total' DESC, activos DESC
        """, (m,))]
    total = next((f for f in filas if f["nivel"] == "total"), None)
    zonas = [f for f in filas if f["nivel"] != "total" and (f["suficiente"] or not publico)]
    return {
        "mes": m.isoformat()[:7], "nombre": nombre_mes(m), "estado": ed["estado"], "titular": ed["titular"],
        "calculado_at": ed["calculado_at"].isoformat(),
        "publicado_at": ed["publicado_at"].isoformat() if ed["publicado_at"] else None,
        "total": total, "zonas": zonas, "destacados": _destacados([z for z in zonas if z["suficiente"]]),
        "min_activos": MIN_ACTIVOS, "min_aptos": MIN_APTOS,
    }


def publicadas() -> List[Dict[str, Any]]:
    with get_db() as db:
        filas = fetch_all(db.cursor, "SELECT mes, titular FROM indice_ediciones WHERE estado = 'publicado' ORDER BY mes DESC")
    return [{"mes": f["mes"].isoformat()[:7], "nombre": nombre_mes(f["mes"]), "titular": f["titular"]} for f in filas]


def ultima_publicada() -> Dict[str, Any]:
    ed = publicadas()
    if not ed:
        raise IndiceError("no_encontrado", "Todavía no hay ediciones publicadas del índice.")
    return {**edicion(ed[0]["mes"]), "ediciones": ed}


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

def ediciones_admin() -> List[Dict[str, Any]]:
    with get_db() as db:
        filas = fetch_all(db.cursor, """
            SELECT e.mes, e.estado, e.titular, e.calculado_at, e.publicado_at, e.publicado_por,
                   (SELECT COUNT(*) FROM indice_mensual i WHERE i.mes = e.mes AND i.suficiente AND i.nivel <> 'total') AS zonas
            FROM indice_ediciones e ORDER BY e.mes DESC
        """)
    return [{"mes": f["mes"].isoformat()[:7], "nombre": nombre_mes(f["mes"]), "estado": f["estado"], "titular": f["titular"],
             "calculado_at": f["calculado_at"].isoformat(),
             "publicado_at": f["publicado_at"].isoformat() if f["publicado_at"] else None,
             "publicado_por": f["publicado_por"], "zonas": int(f["zonas"])} for f in filas]


def publicar(mes: Any, titular: Optional[str], admin: Optional[str]) -> Dict[str, Any]:
    m = _mes(mes)
    titular = (titular or "").strip()[:200] or None
    if not titular:
        raise IndiceError("sin_titular", "Escribe el titular de la edición antes de publicarla.")
    with get_db() as db:
        cur = db.cursor
        cur.execute("""
            UPDATE indice_ediciones SET estado = 'publicado', titular = %s, publicado_at = NOW(), publicado_por = %s
            WHERE mes = %s RETURNING mes
        """, (titular, admin, m))
        if not cur.fetchone():
            raise IndiceError("no_encontrado", "Esa edición no existe: calcúlala primero.")
        db.conn.commit()
    return edicion(m, publico=False)


def despublicar(mes: Any) -> Dict[str, Any]:
    m = _mes(mes)
    with get_db() as db:
        db.cursor.execute("UPDATE indice_ediciones SET estado = 'borrador', publicado_at = NULL WHERE mes = %s", (m,))
        db.conn.commit()
    return edicion(m, publico=False)


def _millones(v: Optional[float]) -> str:
    if not v:
        return "—"
    m = v / 1_000_000
    return (f"{m:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")) + " millones"


def _miles(n: Optional[int]) -> str:
    return f"{int(n or 0):,}".replace(",", ".")


def _pct(v: float) -> str:
    return f"{v:.1f}".replace(".", ",") + " %"


def _zona_legible(z: str) -> str:
    """«11 - Laureles-Estadio» → «Laureles-Estadio (comuna 11)»."""
    if " - " in z and z.split(" - ")[0].strip().isdigit():
        n, nombre = z.split(" - ", 1)
        return f"{nombre.strip()} (comuna {n.strip()})"
    return z


def nota_de_prensa(mes: Any) -> str:
    """Borrador de la nota para medios, con las cifras de la edición (sin IA). El admin la ajusta."""
    e = edicion(mes, publico=False)
    t, d = e["total"] or {}, e["destacados"]
    lineas = [
        f"{e['titular'] or 'Índice Fynder de ' + e['nombre']}",
        "",
        f"Medellín, {datetime.now(BOGOTA).day} de {MESES[datetime.now(BOGOTA).month - 1]} de {datetime.now(BOGOTA).year}. "
        f"El metro cuadrado de los apartamentos en venta en el Valle de Aburrá y el Oriente antioqueño se publicó en "
        f"{e['nombre']} a una mediana de ${_millones(t.get('m2_mediana'))}, según el Índice Fynder, que siguió "
        f"{_miles(t.get('activos'))} inmuebles en venta y {_miles(t.get('pedidos'))} pedidos de clientes en el mes.",
    ]
    if t.get("var_m2_pct") is not None:
        lineas.append(f"Frente al mes anterior, la mediana {'subió' if t['var_m2_pct'] >= 0 else 'bajó'} "
                      f"{_pct(abs(t['var_m2_pct']))}.")
    if d["mas_caras"]:
        lineas.append("Las zonas con el metro cuadrado más alto: " + "; ".join(
            f"{_zona_legible(z['zona'])}, ${_millones(z['m2_mediana'])}" for z in d["mas_caras"]) + ".")
    if d["mas_demanda"]:
        lineas.append("Donde más clientes buscan frente a lo que hay en venta: " + "; ".join(
            f"{_zona_legible(z['zona'])}, {str(z['pedidos_por_100']).replace('.', ',')} pedidos por cada 100 inmuebles"
            for z in d["mas_demanda"]) + ".")
    if d["subieron"] or d["bajaron"]:
        partes = []
        if d["subieron"]:
            partes.append("subió más en " + ", ".join(f"{_zona_legible(z['zona'])} (+{_pct(z['var_m2_pct'])})" for z in d["subieron"]))
        if d["bajaron"]:
            partes.append("bajó más en " + ", ".join(f"{_zona_legible(z['zona'])} (−{_pct(abs(z['var_m2_pct']))})" for z in d["bajaron"]))
        lineas.append("El precio por metro cuadrado " + "; y ".join(partes) + ".")
    lineas += [
        "",
        f"Cómo se calcula: precios de publicación (no de cierre) de los inmuebles en venta que Fynder sigue y verifica a "
        f"diario en portales y grupos de agentes; mediana del precio por m² de los apartamentos (en zonas con "
        f"{MIN_APTOS} o más); solo zonas con {MIN_ACTIVOS} o más inmuebles en venta. Los pedidos son búsquedas de clientes que los agentes comparten en Fynder.",
        "",
        "Sobre Fynder: plataforma de inteligencia inmobiliaria para agentes en Colombia. Inventario, demanda y "
        "búsqueda con IA desde WhatsApp, Claude y ChatGPT. getfynder.com/indice",
    ]
    return "\n".join(lineas)
