"""
Barrios normalizados (migración 059): a qué barrio del catálogo pertenece cada
inmueble y cada pedido.

El catálogo (`barrios`) y sus alias (`barrio_alias`) salen de ordenar con IA, una
sola vez, las ~2.100 formas en que los agentes escriben las zonas
(`scripts/cargar_barrios.py` + data/barrios/mapeo_ia.json); el admin revisa los
dudosos. Para asignar un barrio a un inmueble se prueba, en orden:

  1. polígono oficial: sus coordenadas exactas caen dentro de un barrio con geojson.
  2. texto: su zona o el barrio de su ficha es un alias conocido (en su municipio
     o en cualquiera). Variantes ("Sector Laureles", "Urb. Calasanz") se limpian.
  3. título: el título nombra un barrio del catálogo de su municipio.
  4. coordenadas: el centro de barrio más cercano (≤ 1,5 km, mismo municipio).
Cada asignación guarda su fuente y su confianza, para que el Observatorio filtre.
Va en `propiedad_barrio` (no en propiedades: su trigger cambiaría fecha_actualizacion).

Sin IA en el día a día: todo es diccionario y geometría. Lo corre el worker cada
30 min para lo nuevo (`asignar_pendientes`) y una vez para todo (`reasignar_todo`).
"""

import json
import math
import re
import threading
import time
import unicodedata
from difflib import get_close_matches
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.services.db import fetch_all, get_db

_PREFIJOS = re.compile(r"^(sector|barrio|urbanizacion|urb|conjunto|unidad|edificio|zona|loma de|vereda)\s+")
_RADIO_KM = 1.5
_TTL = 15 * 60


def clave(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def _km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    dy = (a[0] - b[0]) * 111.0
    dx = (a[1] - b[1]) * 111.0 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def _en_poligono(lat: float, lng: float, geo: Dict[str, Any]) -> bool:
    """Punto en (multi)polígono GeoJSON (ray casting, coordenadas [lng, lat])."""
    polys = geo.get("coordinates") or []
    if geo.get("type") == "Polygon":
        polys = [polys]
    for poly in polys:
        if not poly:
            continue
        dentro = False
        anillo = poly[0]
        j = len(anillo) - 1
        for i in range(len(anillo)):
            xi, yi = anillo[i][0], anillo[i][1]
            xj, yj = anillo[j][0], anillo[j][1]
            if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
                dentro = not dentro
            j = i
        if dentro:
            return True
    return False


class Catalogo:
    """Catálogo en memoria (se recarga cada 15 min)."""

    def __init__(self, cur):
        self.barrios = {b["id"]: b for b in fetch_all(cur, "SELECT id, municipio, municipio_clave, comuna, nombre, clave, tipo, lat, lng, geojson FROM barrios")}
        self.alias: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for a in fetch_all(cur, "SELECT municipio_clave, alias_clave, barrio_id, municipio, tipo, confianza FROM barrio_alias"):
            self.alias[(a["municipio_clave"], a["alias_clave"])] = a
        self.por_municipio: Dict[str, List[Dict[str, Any]]] = {}
        for b in self.barrios.values():
            self.por_municipio.setdefault(b["municipio_clave"], []).append(b)
        # Para buscar en títulos: nombres de 5+ letras, el más largo primero ("loma de los bernal" antes que "bernal").
        self.nombres_titulo: Dict[str, List[Tuple[str, int]]] = {}
        for (m, a), v in self.alias.items():
            if v["barrio_id"] and len(a) >= 5 and v["confianza"] >= 0.7:
                mun = self.barrios[v["barrio_id"]]["municipio_clave"]
                self.nombres_titulo.setdefault(mun, []).append((a, v["barrio_id"]))
        for lista in self.nombres_titulo.values():
            lista.sort(key=lambda x: -len(x[0]))
        # Recuadro de cada polígono: descarta rápido los barrios que no pueden contener el punto.
        self.cajas: List[Tuple[float, float, float, float, int]] = []
        for b in self.barrios.values():
            if b.get("geojson") and b["tipo"] != "sector":
                xs, ys = [], []
                polys = b["geojson"].get("coordinates") or []
                for poly in ([polys] if b["geojson"].get("type") == "Polygon" else polys):
                    for x, y in (poly[0] if poly else []):
                        xs.append(x)
                        ys.append(y)
                if xs:
                    self.cajas.append((min(ys), max(ys), min(xs), max(xs), b["id"]))
        self.creado = time.time()

    def municipio_de(self, texto: Optional[str]) -> Optional[str]:
        """Municipio canónico de un texto de ciudad (corrige 'El Poblado' → Medellín)."""
        k = clave(texto)
        if not k:
            return None
        a = self.alias.get(("", k)) or next((v for (m, x), v in self.alias.items() if x == k and v["tipo"] == "municipio"), None)
        if a and a.get("municipio"):
            return a["municipio"]
        for b in self.barrios.values():
            if b["municipio_clave"] == k:
                return b["municipio"]
        return None

    def por_texto(self, texto: Optional[str], municipio: Optional[str]) -> Optional[Tuple[int, float]]:
        k = clave(texto)
        if not k:
            return None
        mun = clave(municipio)
        for cand in (k, _PREFIJOS.sub("", k)):
            for m in (mun, ""):
                a = self.alias.get((m, cand))
                if a:
                    return (a["barrio_id"], float(a["confianza"])) if a["barrio_id"] else None
        # Parecido (errores de digitación) dentro del municipio.
        claves = [x for (m, x), v in self.alias.items() if v["barrio_id"] and m in (mun, "")]
        cerca = get_close_matches(k, claves, n=1, cutoff=0.9)
        if cerca:
            a = self.alias.get((mun, cerca[0])) or self.alias.get(("", cerca[0]))
            return (a["barrio_id"], float(a["confianza"]) * 0.85) if a else None
        return None

    def por_titulo(self, titulo: Optional[str], municipio: Optional[str]) -> Optional[Tuple[int, float]]:
        t = f" {clave(titulo)} "
        if not t.strip():
            return None
        for a, bid in self.nombres_titulo.get(clave(municipio), []):
            if f" {a} " in t:
                return bid, 0.75
        return None

    def por_poligono(self, lat: float, lng: float) -> Optional[int]:
        for y0, y1, x0, x1, bid in self.cajas:
            if y0 <= lat <= y1 and x0 <= lng <= x1 and _en_poligono(lat, lng, self.barrios[bid]["geojson"]):
                return bid
        return None

    def mas_cercano(self, lat: float, lng: float, municipio: Optional[str]) -> Optional[Tuple[int, float]]:
        mejor, dist = None, _RADIO_KM
        for b in self.por_municipio.get(clave(municipio), []):
            if b["lat"] is None or b["tipo"] == "sector":
                continue
            d = _km((lat, lng), (b["lat"], b["lng"]))
            if d < dist:
                mejor, dist = b["id"], d
        return (mejor, round(0.6 - 0.2 * dist / _RADIO_KM, 2)) if mejor else None


_CAT: Optional[Catalogo] = None
_LOCK = threading.Lock()


def catalogo(cur=None, recargar: bool = False) -> Catalogo:
    global _CAT
    with _LOCK:
        if recargar or _CAT is None or time.time() - _CAT.creado > _TTL:
            if cur is None:
                with get_db() as db:
                    _CAT = Catalogo(db.cursor)
            else:
                _CAT = Catalogo(cur)
        return _CAT


def asignar(p: Dict[str, Any], cat: Catalogo) -> Dict[str, Any]:
    """Barrio de un inmueble: {barrio_id, municipio, fuente, confianza} (barrio_id puede ser None)."""
    municipio = cat.municipio_de(p.get("ciudad_ficha") or p.get("ciudad")) or (p.get("ciudad") or None)
    lat, lng = p.get("latitud"), p.get("longitud")
    exactas = lat is not None and lng is not None and p.get("ubicacion_aproximada") is False
    if exactas:
        bid = cat.por_poligono(float(lat), float(lng))
        if bid:
            return {"barrio_id": bid, "municipio": cat.barrios[bid]["municipio"], "fuente": "poligono", "confianza": 0.95}
    for texto in (p.get("barrio_ficha"), p.get("zona")):
        r = cat.por_texto(texto, municipio)
        if r:
            b = cat.barrios[r[0]]
            return {"barrio_id": r[0], "municipio": b["municipio"], "fuente": "texto", "confianza": r[1]}
    r = cat.por_titulo(p.get("titulo"), municipio)
    if r:
        return {"barrio_id": r[0], "municipio": municipio, "fuente": "titulo", "confianza": r[1]}
    if lat is not None and lng is not None:
        bid = cat.por_poligono(float(lat), float(lng)) if not exactas else None
        if bid:
            return {"barrio_id": bid, "municipio": cat.barrios[bid]["municipio"], "fuente": "poligono", "confianza": 0.6}
        r = cat.mas_cercano(float(lat), float(lng), municipio)
        if r:
            return {"barrio_id": r[0], "municipio": municipio, "fuente": "coordenadas", "confianza": r[1]}
    return {"barrio_id": None, "municipio": municipio, "fuente": None, "confianza": None}


_SQL_INMUEBLES = """
    SELECT p.id, p.ciudad, p.zona, p.titulo, p.latitud, p.longitud, p.ubicacion_aproximada,
           f.barrio AS barrio_ficha, f.ciudad AS ciudad_ficha
    FROM propiedades p LEFT JOIN propiedades_ficha f ON f.propiedad_id = p.id
"""


def _guardar(cur, filas: Iterable[Dict[str, Any]], cat: Catalogo) -> Dict[str, int]:
    """Asigna y guarda por lotes (un UPDATE por cada 1.000 inmuebles, no uno por inmueble)."""
    from psycopg2.extras import execute_values
    cuenta: Dict[str, int] = {}
    valores = []
    for p in filas:
        a = asignar(p, cat)
        valores.append((p["id"], a["barrio_id"], (a["municipio"] or None) and str(a["municipio"])[:60], a["fuente"], a["confianza"]))
        cuenta[a["fuente"] or "sin_barrio"] = cuenta.get(a["fuente"] or "sin_barrio", 0) + 1
    for i in range(0, len(valores), 1000):
        execute_values(cur, """
            INSERT INTO propiedad_barrio (propiedad_id, barrio_id, municipio, fuente, confianza) VALUES %s
            ON CONFLICT (propiedad_id) DO UPDATE SET barrio_id = EXCLUDED.barrio_id, municipio = EXCLUDED.municipio,
                fuente = EXCLUDED.fuente, confianza = EXCLUDED.confianza, asignado_at = NOW()
        """, valores[i:i + 1000], template="(%s::int, %s::int, %s::varchar, %s::varchar, %s::real)")
    return cuenta


def calcular_centros(cur) -> int:
    """Centro de cada barrio = mediana de las coordenadas de sus inmuebles asignados por texto
    (los que no tienen polígono oficial). Descarta puntos a más de 3 km de la mediana."""
    filas = fetch_all(cur, """
        SELECT pb.barrio_id, p.latitud, p.longitud FROM propiedad_barrio pb JOIN propiedades p ON p.id = pb.propiedad_id
        WHERE pb.barrio_id IS NOT NULL AND pb.fuente IN ('texto', 'poligono') AND p.latitud IS NOT NULL
    """)
    puntos: Dict[int, List[Tuple[float, float]]] = {}
    for f in filas:
        puntos.setdefault(f["barrio_id"], []).append((float(f["latitud"]), float(f["longitud"])))
    from psycopg2.extras import execute_values
    valores = []
    for bid, ps in puntos.items():
        if len(ps) < 2:
            continue
        c = (median(p[0] for p in ps), median(p[1] for p in ps))
        buenos = [p for p in ps if _km(c, p) <= 3]
        if len(buenos) >= 2:
            valores.append((bid, median(p[0] for p in buenos), median(p[1] for p in buenos)))
    if valores:
        execute_values(cur, """
            UPDATE barrios AS b SET lat = v.lat, lng = v.lng FROM (VALUES %s) AS v(id, lat, lng)
            WHERE b.id = v.id AND b.geojson IS NULL
        """, valores, template="(%s::int, %s::float8, %s::float8)")
    return len(valores)


def reasignar_todo() -> Dict[str, int]:
    """Asigna barrio a todo el inventario: primero por texto (para calcular los centros) y luego todo."""
    with get_db() as db:
        cur = db.cursor
        cat = catalogo(cur, recargar=True)
        filas = fetch_all(cur, _SQL_INMUEBLES)
        _guardar(cur, filas, cat)
        db.conn.commit()
        calcular_centros(cur)
        db.conn.commit()
        cat = catalogo(cur, recargar=True)
        cuenta = _guardar(cur, filas, cat)
        db.conn.commit()
    cuenta["pedidos"] = asignar_pedidos(todos=True)
    return cuenta


def asignar_pendientes(limite: int = 2000) -> Dict[str, int]:
    """Worker: inmuebles y pedidos que aún no tienen barrio evaluado."""
    with get_db() as db:
        cur = db.cursor
        filas = fetch_all(cur, _SQL_INMUEBLES + """
            WHERE NOT EXISTS (SELECT 1 FROM propiedad_barrio pb WHERE pb.propiedad_id = p.id) ORDER BY p.id LIMIT %s
        """, (limite,))
        cuenta = _guardar(cur, filas, catalogo(cur)) if filas else {}
        db.conn.commit()
    cuenta["pedidos"] = asignar_pedidos()
    return cuenta


def barrios_de_pedido(criterios: Dict[str, Any], cat: Catalogo) -> List[int]:
    """Los barrios del catálogo que pide un pedido (sus zonas, en sus ciudades)."""
    ciudades = criterios.get("ciudades") or [None]
    ids: List[int] = []
    for z in criterios.get("zonas") or []:
        for c in ciudades:
            r = cat.por_texto(z, c)
            if r and r[0] not in ids:
                ids.append(r[0])
                break
    return ids


def asignar_pedidos(todos: bool = False, limite: int = 3000) -> int:
    with get_db() as db:
        cur = db.cursor
        cat = catalogo(cur)
        filas = fetch_all(cur, f"""
            SELECT id, criterios FROM pedidos WHERE criterios IS NOT NULL {'' if todos else 'AND barrio_at IS NULL'}
            ORDER BY id DESC LIMIT %s
        """, (limite if not todos else 1_000_000,))
        from psycopg2.extras import execute_values
        valores = [(f["id"], barrios_de_pedido(f["criterios"] if isinstance(f["criterios"], dict) else {}, cat)) for f in filas]
        for i in range(0, len(valores), 1000):
            execute_values(cur, """
                UPDATE pedidos AS p SET barrio_ids = v.ids, barrio_at = NOW()
                FROM (VALUES %s) AS v(id, ids) WHERE p.id = v.id
            """, valores[i:i + 1000], template="(%s::int, %s::int[])")
        db.conn.commit()
    return len(filas)


# ── Revisión del admin ─────────────────────────────────────────────────────

def por_revisar(limite: int = 100) -> List[Dict[str, Any]]:
    """Alias dudosos (confianza baja, sin revisar), los más usados primero."""
    with get_db() as db:
        return fetch_all(db.cursor, """
            SELECT a.id, a.municipio_clave, a.alias_clave, a.tipo, a.confianza, a.usos, a.barrio_id,
                   b.nombre AS barrio, b.municipio, b.comuna
            FROM barrio_alias a LEFT JOIN barrios b ON b.id = a.barrio_id
            WHERE NOT a.revisado AND (a.confianza < 0.8 OR a.barrio_id IS NULL)
            ORDER BY a.usos DESC, a.confianza LIMIT %s
        """, (limite,))


def revisar_alias(alias_id: int, barrio_id: Optional[int]) -> Dict[str, Any]:
    """El admin confirma (o cambia) el barrio de un alias; barrio_id None = no es un lugar."""
    with get_db() as db:
        db.cursor.execute("""
            UPDATE barrio_alias SET barrio_id = %s, revisado = TRUE, confianza = 1.0, fuente = 'manual',
                   tipo = CASE WHEN %s IS NULL THEN 'no_es_lugar' ELSE tipo END WHERE id = %s
        """, (barrio_id, barrio_id, alias_id))
        # Los inmuebles asignados por texto o título se reasignan en la próxima corrida.
        db.cursor.execute("DELETE FROM propiedad_barrio WHERE fuente IN ('texto', 'titulo', 'coordenadas')")
        db.conn.commit()
    catalogo(recargar=True)
    return {"ok": True}


def resumen() -> Dict[str, Any]:
    with get_db() as db:
        c = db.cursor
        return {
            "barrios": fetch_all(c, "SELECT COUNT(*) AS n FROM barrios")[0]["n"],
            "con_poligono": fetch_all(c, "SELECT COUNT(*) AS n FROM barrios WHERE geojson IS NOT NULL")[0]["n"],
            "alias": fetch_all(c, "SELECT COUNT(*) AS n FROM barrio_alias")[0]["n"],
            "por_revisar": fetch_all(c, "SELECT COUNT(*) AS n FROM barrio_alias WHERE NOT revisado AND (confianza < 0.8 OR barrio_id IS NULL)")[0]["n"],
            "cobertura": fetch_all(c, """
                SELECT COALESCE(pb.fuente, 'sin_barrio') AS fuente, COUNT(*) AS n,
                       COUNT(*) FILTER (WHERE p.activa) AS activas
                FROM propiedades p LEFT JOIN propiedad_barrio pb ON pb.propiedad_id = p.id GROUP BY 1 ORDER BY 2 DESC"""),
        }


def buscar(q: str, limite: int = 20) -> List[Dict[str, Any]]:
    """Para el selector del admin: barrios del catálogo que coinciden con el texto."""
    k = f"%{clave(q)}%"
    with get_db() as db:
        return fetch_all(db.cursor, """
            SELECT id, nombre, municipio, comuna, tipo FROM barrios WHERE clave LIKE %s OR municipio_clave LIKE %s
            ORDER BY tipo, nombre LIMIT %s
        """, (k, k, limite))


def geojson_barrios() -> Dict[str, Any]:
    """Los barrios con polígono oficial, como FeatureCollection (para el mapa del Observatorio)."""
    with get_db() as db:
        filas = fetch_all(db.cursor, "SELECT id, nombre, municipio, comuna, geojson FROM barrios WHERE geojson IS NOT NULL")
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": f["id"], "geometry": f["geojson"],
         "properties": {"id": f["id"], "nombre": f["nombre"], "municipio": f["municipio"], "comuna": f["comuna"]}}
        for f in filas]}


def _json(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False)
