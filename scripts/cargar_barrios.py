#!/usr/bin/env python3
"""
Carga el catálogo de barrios (migración 059) y, si se le pasa, los polígonos oficiales.

    python scripts/cargar_barrios.py                      # catálogo + alias desde data/barrios/mapeo_ia.json
    python scripts/cargar_barrios.py --geojson data/geo/barrios_medellin.geojson
    python scripts/cargar_barrios.py --asignar            # asigna barrio a todo el inventario y los pedidos

Idempotente: vuelve a correr sin duplicar (los alias revisados por el admin no se tocan).
El mapeo lo produjo una sola corrida de Claude Haiku sobre las ~2.100 formas en que los
agentes escriben las zonas (ver barrios_service.py).
"""
import argparse
import io
import json
import os
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(RAIZ, ".env"))

from src.services import barrios_service as bs  # noqa: E402
from src.services.db import fetch_one, get_db  # noqa: E402

MAPEO = os.path.join(RAIZ, "data", "barrios", "mapeo_ia.json")


# La forma correcta de escribir cada municipio (la IA a veces escribe "Itaguí" e "Itagüí").
MUNICIPIOS = {"medellin": "Medellín", "itagui": "Itagüí", "envigado": "Envigado", "sabaneta": "Sabaneta", "bello": "Bello",
              "la estrella": "La Estrella", "caldas": "Caldas", "copacabana": "Copacabana", "girardota": "Girardota",
              "barbosa": "Barbosa", "rionegro": "Rionegro", "el retiro": "El Retiro", "la ceja": "La Ceja", "guarne": "Guarne",
              "marinilla": "Marinilla", "el carmen de viboral": "El Carmen de Viboral", "el santuario": "El Santuario",
              "la union": "La Unión", "san antonio de pereira": "Rionegro", "santa fe de antioquia": "Santa Fe de Antioquia",
              "sopetran": "Sopetrán", "san jeronimo": "San Jerónimo", "guatape": "Guatapé", "el penol": "El Peñol"}


def _municipios_canonicos(mapeo) -> dict:
    """clave → forma más usada (con tildes), con las conocidas primero."""
    from collections import Counter
    votos: dict = {}
    for v in mapeo.values():
        m = (v.get("municipio") or "").strip()
        if m:
            votos.setdefault(bs.clave(m), Counter())[m] += int(v.get("c") or 1)
    return {k: MUNICIPIOS.get(k) or c.most_common(1)[0][0] for k, c in votos.items()}


def cargar_catalogo() -> None:
    mapeo = json.load(open(MAPEO, encoding="utf-8"))
    canon = _municipios_canonicos(mapeo)
    for v in mapeo.values():
        if v.get("municipio"):
            v["municipio"] = canon.get(bs.clave(v["municipio"]), v["municipio"])
    from psycopg2.extras import execute_values
    # 1) Barrios únicos (municipio, nombre canónico) → un solo INSERT por lotes.
    barrios = {}
    for v in mapeo.values():
        if v["tipo"] in ("barrio", "sector", "vereda") and v.get("barrio") and v.get("municipio"):
            k = (bs.clave(v["municipio"]), bs.clave(v["barrio"]))
            if k not in barrios:
                barrios[k] = (v["municipio"], k[0], v.get("comuna"), v["barrio"].strip(), k[1], v["tipo"])
    with get_db() as db:
        cur = db.cursor
        ids = {}
        filas = list(barrios.values())
        for i in range(0, len(filas), 500):
            res = execute_values(cur, """
                INSERT INTO barrios (municipio, municipio_clave, comuna, nombre, clave, tipo) VALUES %s
                ON CONFLICT (municipio_clave, clave) DO UPDATE SET comuna = COALESCE(barrios.comuna, EXCLUDED.comuna)
                RETURNING id, municipio_clave, clave
            """, filas[i:i + 500], fetch=True)
            ids.update({(r["municipio_clave"], r["clave"]): r["id"] for r in res})
        # 2) Alias: cada forma de escribirlo, y el nombre canónico como alias de sí mismo.
        alias = {}
        for llave, v in mapeo.items():
            mun_origen, a = llave.split("|", 1)
            bid = None
            if v["tipo"] in ("barrio", "sector", "vereda") and v.get("barrio") and v.get("municipio"):
                bid = ids.get((bs.clave(v["municipio"]), bs.clave(v["barrio"])))
            alias[(bs.clave(mun_origen), a)] = (bs.clave(mun_origen), a, bid, v.get("municipio"), v["tipo"],
                                                 float(v.get("confianza") or 0.5), int(v.get("c") or 0))
        for (mc, k), bid in ids.items():
            municipio = next(b[0] for b in barrios.values() if (b[1], b[4]) == (mc, k))
            alias.setdefault((mc, k), (mc, k, bid, municipio, barrios[(mc, k)][5], 0.95, 0))
        filas = list(alias.values())
        for i in range(0, len(filas), 1000):
            execute_values(cur, """
                INSERT INTO barrio_alias (municipio_clave, alias_clave, barrio_id, municipio, tipo, confianza, usos) VALUES %s
                ON CONFLICT (municipio_clave, alias_clave) DO UPDATE SET
                    barrio_id = CASE WHEN barrio_alias.revisado THEN barrio_alias.barrio_id ELSE EXCLUDED.barrio_id END,
                    municipio = EXCLUDED.municipio, usos = EXCLUDED.usos,
                    confianza = CASE WHEN barrio_alias.revisado THEN barrio_alias.confianza ELSE EXCLUDED.confianza END
            """, filas[i:i + 1000])
        db.conn.commit()
    print(f"Catálogo: {len(ids)} barrios, {len(alias)} alias")


def _centro(geo):
    xs, ys = [], []
    polys = geo["coordinates"] if geo["type"] == "MultiPolygon" else [geo["coordinates"]]
    for poly in polys:
        for x, y in poly[0]:
            xs.append(x)
            ys.append(y)
    return (sum(ys) / len(ys), sum(xs) / len(xs)) if xs else (None, None)


def cargar_poligonos(ruta: str, municipio: str = "Medellín") -> None:
    """Polígonos oficiales (GeoJSON de GeoMedellín, WGS84): actualiza o crea cada barrio."""
    gj = json.load(open(ruta, encoding="utf-8"))
    mc = bs.clave(municipio)
    act = nuevos = 0
    with get_db() as db:
        cur = db.cursor
        for f in gj.get("features", []):
            pr = {k.upper(): v for k, v in (f.get("properties") or {}).items()}
            nombre = (pr.get("NOMBRE") or pr.get("NOMBRE_BARRIO") or "").strip()
            if not nombre or not f.get("geometry"):
                continue
            comuna = pr.get("NOMBRE_COMUNA") or pr.get("COMUNA")
            codigo = str(pr.get("CODIGO") or "")
            if comuna and codigo[:2].isdigit() and not str(comuna)[:2].isdigit():
                comuna = f"{int(codigo[:2])} - {str(comuna).title()}"
            tipo = "vereda" if str(pr.get("INDICADOR_UR") or "").upper().startswith("R") else "barrio"
            lat, lng = _centro(f["geometry"])
            k = bs.clave(nombre)
            ya = fetch_one(cur, "SELECT id FROM barrios WHERE municipio_clave = %s AND clave = %s", (mc, k))
            if ya:
                cur.execute("""UPDATE barrios SET geojson = %s, lat = %s, lng = %s, comuna = COALESCE(%s, comuna),
                               fuente = 'oficial', tipo = CASE WHEN tipo = 'sector' THEN tipo ELSE %s END WHERE id = %s""",
                            (json.dumps(f["geometry"]), lat, lng, comuna, tipo, ya["id"]))
                act += 1
            else:
                cur.execute("""INSERT INTO barrios (municipio, municipio_clave, comuna, nombre, clave, tipo, lat, lng, geojson, fuente)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'oficial') RETURNING id""",
                            (municipio, mc, comuna, nombre.title(), k, tipo, lat, lng, json.dumps(f["geometry"])))
                bid = cur.fetchone()["id"]
                cur.execute("""INSERT INTO barrio_alias (municipio_clave, alias_clave, barrio_id, municipio, tipo, confianza, fuente, revisado)
                               VALUES (%s, %s, %s, %s, %s, 1.0, 'oficial', TRUE) ON CONFLICT DO NOTHING""",
                            (mc, k, bid, municipio, tipo))
                nuevos += 1
        db.conn.commit()
        # Los barrios y sectores sin polígono (nombres de agentes) toman la comuna del
        # barrio oficial donde cae su centro: corrige comunas que la IA asignó mal.
        cat = bs.catalogo(cur, recargar=True)
        corregidas = 0
        for b in list(cat.barrios.values()):
            if b["municipio_clave"] == mc and not b.get("geojson") and b.get("lat") is not None:
                bid = cat.por_poligono(b["lat"], b["lng"])
                comuna = cat.barrios[bid]["comuna"] if bid else None
                if comuna and comuna != b["comuna"]:
                    cur.execute("UPDATE barrios SET comuna = %s WHERE id = %s", (comuna, b["id"]))
                    corregidas += 1
        db.conn.commit()
    print(f"Polígonos: {act} barrios actualizados, {nuevos} barrios oficiales nuevos, {corregidas} comunas corregidas")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--geojson")
    ap.add_argument("--municipio", default="Medellín")
    ap.add_argument("--asignar", action="store_true")
    a = ap.parse_args()
    if a.geojson:
        cargar_poligonos(a.geojson, a.municipio)
    elif not a.asignar:
        cargar_catalogo()
    if a.asignar:
        print("Asignación:", bs.reasignar_todo())
