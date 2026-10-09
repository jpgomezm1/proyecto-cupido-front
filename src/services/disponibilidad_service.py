"""
Verificación de disponibilidad de propiedades (re-scrape del link original).

Tres usos:
  - On-demand: antes de cobrar un desbloqueo de contacto (suscripcion_service) o
    de escalar una visita a Hernán (interes_service).
  - Revalidación continua (`revalidar_lote`), que corre en el worker cada 30 min
    y recorre todo el inventario activo en ~7 días (acuerdo de frescura ≤ 8 días).
  - Reporte y rescate manual (`scripts/validate_property_urls.py`, skill
    /validate-links).

Este módulo es la ÚNICA fuente de verdad del chequeo de URLs.

Cada portal tiene su detector, porque cada uno avisa distinto que un inmueble ya
no está:
  - Wasi responde 200 con "No se encontró inmueble" (o redirige al home).
  - Lobbie responde 404 de verdad.
  - Pulppo (portal de Tu360) siempre responde 200 con la ficha completa; el
    estado real va en el JSON de Next.js: `property.status.last` = 'published'
    o 'cancelled' (con `reasonToFinish`, p. ej. "Otro asesor la concretó").
Cada detector exige evidencia positiva para decir "vivo"; si la página no se
parece a ninguna de las dos cosas, el veredicto es "incierto" y no se toca nada.

Veredictos y efectos:
  - muerto   → activa = FALSE, desactivada_por = 'validador', sella la validación.
  - vivo     → sella la validación; si el validador la había bajado, la reactiva.
  - incierto → solo sella el intento (timeout, 403, 5xx, página irreconocible).
`fecha_ultima_validacion` (lo que ve el agente como "verificada hace N días")
solo cambia con un veredicto concluyente; la rotación usa `fecha_ultimo_intento`.
Cada veredicto queda en `verificaciones_disponibilidad`.

Fotos: un inmueble puede seguir publicado con las fotos que guardamos ya
borradas en el portal (el portal las cambia cuando el agente edita el aviso).
Si la portada guardada da 404/410, se reemplazan por las que la publicación
muestra hoy (solo Wasi: en Lobbie la galería no viene en el HTML), salvo que el
dueño las haya editado en Fynder.
Queda en `verificaciones_disponibilidad.cambio` como 'fotos_renovadas' o
'fotos_rotas' (sin reemplazo posible).
"""

import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from src.services.db import get_db, fetch_one, fetch_all, scalar

REQUEST_TIMEOUT = 20  # segundos
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Mensajes de "ya no existe" que muestran los portales con HTTP 200.
CONTENT_NOT_FOUND_PATTERNS = [
    "no se encontró inmueble",
    "no se encontro inmueble",
    "inmueble no encontrado",
    "propiedad no encontrada",
    "esta propiedad ya no está disponible",
    "esta propiedad ya no esta disponible",
    "no encontramos la propiedad",
    "property not found",
    "this property is no longer available",
    "el inmueble que buscas ya no está disponible",
    "el inmueble que buscas ya no esta disponible",
    "este inmueble ya no se encuentra disponible",
    "publicación no disponible",
    "publicacion no disponible",
]

# Páginas propias de Fynder: no hay portal de origen que revisar.
_HOSTS_PROPIOS = ("fyndercol.netlify.app", "getfynder.com")
_SQL_SIN_PROPIOS = "url !~* '(fyndercol\\.netlify\\.app|getfynder\\.com)'"

# Estados de Pulppo que significan que el inmueble ya no se comercializa.
_PULPPO_TERMINADO = {"cancelled", "completed", "finished", "sold", "rented", "closed", "archived", "expired"}

VIVO, MUERTO, INCIERTO = "vivo", "muerto", "incierto"


@dataclass
class Veredicto:
    veredicto: str          # vivo | muerto | incierto
    motivo: str
    status: Optional[int]
    portal: str
    precio: Optional[int] = None   # precio que muestra hoy el portal (si se pudo leer)
    fotos: Optional[List[str]] = None  # fotos que muestra hoy el portal (solo Wasi)
    fotos_rotas: bool = False          # la portada que guardamos ya no existe


# Motivos de "incierto" que vienen de la red, no de la página: vale la pena reintentar.
MOTIVOS_DE_RED = ("timeout", "error_de_conexion")


def build_session() -> requests.Session:
    """Sesión HTTP con el User-Agent estándar."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def portal_de(url: Optional[str]) -> str:
    host = (urlparse(url or "").netloc or "").lower()
    if host.endswith("wasi.co"):
        return "wasi"
    if host.endswith("lobbieapp.com"):
        return "lobbie"
    if "pulppo" in host:
        return "pulppo"
    if any(host.endswith(h) for h in _HOSTS_PROPIOS):
        return "propio"
    return "generico"


def _no_encontrado(html: str) -> Optional[str]:
    bajo = html.lower()
    return next((p for p in CONTENT_NOT_FOUND_PATTERNS if p in bajo), None)


# ── Detectores por portal: (status, url_final, html) → (veredicto, motivo) ──

def _wasi(status: int, final_url: str, html: str) -> Tuple[str, str]:
    patron = _no_encontrado(html)
    if patron:
        return MUERTO, f"wasi: {patron}"
    ruta = urlparse(final_url).path.strip("/").lower()
    if ruta in ("", "es", "en"):
        return MUERTO, "wasi: redirige al home"
    # Evidencia positiva: la galería y el encabezado de la ficha.
    if "fotorama" in html or "firstHeading" in html:
        return VIVO, "wasi: ficha publicada"
    return INCIERTO, "wasi: página irreconocible"


def _lobbie(status: int, final_url: str, html: str) -> Tuple[str, str]:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    titulo = (m.group(1).strip() if m else "").lower()
    if titulo and titulo != "lobbie":
        return VIVO, "lobbie: ficha publicada"
    patron = _no_encontrado(html)
    if patron:
        return MUERTO, f"lobbie: {patron}"
    return INCIERTO, "lobbie: página irreconocible"


def _pulppo(status: int, final_url: str, html: str) -> Tuple[str, str]:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return INCIERTO, "pulppo: sin datos de la ficha"
    try:
        prop = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("property")
    except (ValueError, AttributeError):
        return INCIERTO, "pulppo: datos ilegibles"
    if not prop:
        return MUERTO, "pulppo: ficha inexistente"
    estado = prop.get("status") or {}
    ultimo = (estado.get("last") or "").lower() if isinstance(estado, dict) else ""
    if ultimo == "published":
        return VIVO, "pulppo: publicada"
    if ultimo in _PULPPO_TERMINADO:
        razon = estado.get("reasonToFinish")
        return MUERTO, f"pulppo: {ultimo}" + (f" ({razon})" if razon else "")
    return INCIERTO, f"pulppo: estado '{ultimo or 'sin estado'}'"


def _generico(status: int, final_url: str, html: str) -> Tuple[str, str]:
    patron = _no_encontrado(html)
    if patron:
        return MUERTO, f"contenido: {patron}"
    return VIVO, "ok"


_DETECTORES = {"wasi": _wasi, "lobbie": _lobbie, "pulppo": _pulppo, "generico": _generico}


# ── Precio publicado hoy en el portal ──────────────────────────────────────

def _entero(texto: Optional[str]) -> Optional[int]:
    digitos = re.sub(r"[^\d]", "", texto or "")
    return int(digitos) if digitos else None


def leer_precio(portal: str, html: str) -> Optional[int]:
    """Precio de venta que muestra la ficha. None si no se reconoce (nunca adivina)."""
    try:
        if portal == "wasi":
            m = re.search(r'<p[^>]*class="[^"]*\bpr1\b[^"]*"[^>]*>(.*?)</p>', html, re.S)
            return _entero(re.sub(r"<[^>]+>", "", m.group(1))) if m else None
        if portal == "lobbie":
            m = re.search(r'class="[^"]*share-hero-overlay__price[^"]*"[^>]*>(.*?)<', html, re.S)
            return _entero(m.group(1)) if m else None
        if portal == "pulppo":
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
            if not m:
                return None
            listing = (json.loads(m.group(1)).get("props", {}).get("pageProps", {})
                       .get("property") or {}).get("listing") or {}
            precio = (listing.get("price") or {}).get("price") if isinstance(listing.get("price"), dict) else None
            if (listing.get("price") or {}).get("currency", "COP") != "COP":
                return None
            return int(precio) if precio else None
    except (ValueError, AttributeError, TypeError):
        return None
    return None


def leer_fotos(portal: str, html: str) -> Optional[List[str]]:
    """Fotos que muestra hoy la publicación, con el mismo extractor del scraper.
    None si el portal no se reconoce o el entorno no tiene el scraper (el MCP)."""
    if portal != "wasi":
        return None
    try:
        from types import SimpleNamespace
        from bs4 import BeautifulSoup
        from src.scrapers.wasi import WasiScraper
        datos = WasiScraper._extract_images(SimpleNamespace(log=lambda _m: None),
                                            BeautifulSoup(html, "html.parser"))
    except Exception:  # noqa: BLE001 — leer fotos nunca tumba la verificación
        return None
    from src.services.textutils import split_image_urls
    return split_image_urls(datos.get("imagenes_urls")) or None


def foto_rota(session, url: Optional[str]) -> bool:
    """True solo si el servidor de la foto dice que ya no existe (404/410).
    Un 403 o un timeout no cuentan: puede ser antihotlinking o la red."""
    if not url or not url.startswith("http"):
        return False
    try:
        r = session.get(url, timeout=10, stream=True)
        r.close()
        return r.status_code in (404, 410)
    except Exception:  # noqa: BLE001
        return False


def _revisar_portada(session, v: Veredicto, imagenes_urls: Optional[str]) -> None:
    """Marca `v.fotos_rotas` si la publicación sigue viva pero su portada guardada no."""
    if v.veredicto != VIVO or not imagenes_urls:
        return
    from src.services.textutils import split_image_urls
    guardadas = split_image_urls(imagenes_urls)
    if guardadas and portal_de(guardadas[0]) != "propio" and foto_rota(session, guardadas[0]):
        v.fotos_rotas = True


def diagnosticar(session, url: Optional[str]) -> Veredicto:
    """Visita el link original y decide si el inmueble sigue publicado."""
    portal = portal_de(url)
    if not url or not url.startswith("http"):
        return Veredicto(INCIERTO, "sin_url", None, portal)
    if portal == "propio":
        return Veredicto(INCIERTO, "sin_portal_de_origen", None, portal)

    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except requests.exceptions.Timeout:
        return Veredicto(INCIERTO, "timeout", None, portal)
    except requests.exceptions.ConnectionError:
        return Veredicto(INCIERTO, "error_de_conexion", None, portal)
    except requests.exceptions.TooManyRedirects:
        return Veredicto(MUERTO, "demasiadas_redirecciones", None, portal)
    except Exception as e:  # noqa: BLE001 — conservador: lo raro no desactiva
        return Veredicto(INCIERTO, f"error: {str(e)[:60]}", None, portal)

    status = r.status_code
    if status in (404, 410):
        return Veredicto(MUERTO, f"http_{status}", status, portal)
    if status >= 400:
        return Veredicto(INCIERTO, f"http_{status}", status, portal)
    veredicto, motivo = _DETECTORES[portal](status, r.url, r.text)
    precio = leer_precio(portal, r.text) if veredicto == VIVO else None
    fotos = leer_fotos(portal, r.text) if veredicto == VIVO else None
    return Veredicto(veredicto, motivo, status, portal, precio, fotos)


def check_url(session, url, fuente=None) -> Tuple[bool, str, Optional[int]]:
    """Compatibilidad: (sigue_activa, motivo, status). Lo incierto cuenta como activa."""
    v = diagnosticar(session, url)
    return v.veredicto != MUERTO, v.motivo, v.status


def _estado(v: Veredicto) -> str:
    """Estado de negocio que consumen cobro, visitas y admin."""
    if v.veredicto == VIVO:
        return "disponible"
    if v.veredicto == MUERTO:
        return "404" if v.motivo in ("http_404", "http_410") else "no_disponible"
    return "desconocido"


def _persistir(cur, propiedad_id: int, v: Veredicto, origen: str) -> Optional[str]:
    """Aplica el veredicto. Devuelve el cambio hecho ('desactivada' / 'reactivada') o None."""
    if v.veredicto == MUERTO:
        cur.execute("""
            UPDATE propiedades p
            SET activa = FALSE,
                desactivada_por = CASE WHEN p.activa THEN 'validador' ELSE p.desactivada_por END,
                fecha_actualizacion = CASE WHEN p.activa THEN NOW() ELSE p.fecha_actualizacion END,
                validaciones_fallidas_consecutivas = COALESCE(p.validaciones_fallidas_consecutivas, 0) + 1,
                fecha_ultima_validacion = NOW(), fecha_ultimo_intento = NOW(),
                disponibilidad_motivo = %s
            FROM (SELECT activa FROM propiedades WHERE id = %s FOR UPDATE) antes
            WHERE p.id = %s
            RETURNING antes.activa AS antes
        """, (v.motivo, propiedad_id, propiedad_id))
        row = cur.fetchone()
        cambio = "desactivada" if row and row["antes"] else None
    elif v.veredicto == VIVO:
        cur.execute("""
            UPDATE propiedades p
            SET activa = p.activa OR COALESCE(p.desactivada_por = 'validador', FALSE),
                fecha_actualizacion = CASE WHEN NOT p.activa AND p.desactivada_por = 'validador'
                                           THEN NOW() ELSE p.fecha_actualizacion END,
                desactivada_por = CASE WHEN p.desactivada_por = 'validador' THEN NULL ELSE p.desactivada_por END,
                validaciones_fallidas_consecutivas = 0,
                fecha_ultima_validacion = NOW(), fecha_ultimo_intento = NOW(),
                disponibilidad_motivo = %s
            FROM (SELECT activa FROM propiedades WHERE id = %s FOR UPDATE) antes
            WHERE p.id = %s
            RETURNING antes.activa AS antes, p.activa AS ahora
        """, (v.motivo, propiedad_id, propiedad_id))
        row = cur.fetchone()
        cambio = "reactivada" if row and not row["antes"] and row["ahora"] else None
    else:
        cambio = None
        cur.execute("""
            UPDATE propiedades SET fecha_ultimo_intento = NOW(), disponibilidad_motivo = %s
            WHERE id = %s
        """, (v.motivo, propiedad_id))

    if v.veredicto == VIVO and v.fotos_rotas:
        cambio = cambio or _renovar_fotos(cur, propiedad_id, v.fotos)

    cur.execute("""
        INSERT INTO verificaciones_disponibilidad
            (propiedad_id, veredicto, motivo, status_code, portal, origen, cambio)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (propiedad_id, v.veredicto, v.motivo, v.status, v.portal, origen, cambio))
    if v.veredicto == VIVO and v.precio:
        _registrar_precio(cur, propiedad_id, v.precio, origen)
    return cambio


_CAMPOS_FOTOS = ["imagenes_urls", "imagen_principal", "total_imagenes"]


def _renovar_fotos(cur, propiedad_id: int, fotos: Optional[List[str]]) -> str:
    """Reemplaza las fotos rotas por las de la publicación. Si el dueño editó las
    fotos en Fynder, o el portal no dejó leerlas, solo se registra."""
    if not fotos:
        return "fotos_rotas"
    cur.execute("""
        UPDATE propiedades SET imagenes_urls = %s, imagen_principal = %s, total_imagenes = %s
        WHERE id = %s AND NOT (COALESCE(campos_editados, '{}') && %s::text[])
    """, ("|".join(fotos), fotos[0], len(fotos), propiedad_id, _CAMPOS_FOTOS))
    return "fotos_renovadas" if cur.rowcount else "fotos_rotas"


def _registrar_precio(cur, propiedad_id: int, precio_web: int, origen: str) -> Optional[Dict[str, Any]]:
    """
    Si el portal muestra otro precio, lo registra en `cambios_precio` y lo aplica.
    No se aplica (pero queda registrado) si el dueño editó el precio en Fynder o
    si el salto es absurdo (menos de la mitad o más del doble: casi siempre un
    error de digitación en el portal).
    """
    fila = fetch_one(cur, "SELECT precio, campos_editados FROM propiedades WHERE id = %s", (propiedad_id,))
    if not fila or not fila["precio"]:
        return None
    actual = int(fila["precio"])
    if actual == precio_web:
        return None
    ya = fetch_one(cur, """
        SELECT 1 FROM cambios_precio
        WHERE propiedad_id = %s AND precio_nuevo = %s AND NOT aplicado AND created_at > NOW() - INTERVAL '30 days'
    """, (propiedad_id, precio_web))
    if ya:
        return None  # ya sabemos que este precio no se aplica; no repetir el registro
    motivo = None
    if "precio" in (fila["campos_editados"] or []):
        motivo = "editado_por_agente"
    elif not (0.5 <= precio_web / actual <= 2.0):
        motivo = "sospechoso"
    cur.execute("""
        INSERT INTO cambios_precio (propiedad_id, precio_anterior, precio_nuevo, aplicado, motivo, origen)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (propiedad_id, actual, precio_web, motivo is None, motivo, origen))
    if motivo is None:
        texto = "$" + f"{precio_web:,.0f}".replace(",", ".")
        cur.execute("""
            UPDATE propiedades SET precio = %s, precio_texto = %s, fecha_actualizacion = NOW() WHERE id = %s
        """, (precio_web, texto, propiedad_id))
    return {"precio_anterior": actual, "precio_nuevo": precio_web, "aplicado": motivo is None}


def verificar_disponibilidad(propiedad_id, actualizar: bool = True, origen: str = "on_demand") -> Dict[str, Any]:
    """
    Verifica una propiedad puntual y (por defecto) persiste el resultado.

    Devuelve:
      {
        propiedad_id, activo: bool,
        estado: 'disponible' | '404' | 'no_disponible' | 'desconocido',
        status_code, motivo, verificado_en (ISO)
      }
    """
    # 1) Lectura corta; 2) HTTP sin conexión retenida; 3) escritura corta.
    with get_db() as db:
        prop = fetch_one(db.cursor, "SELECT id, url, imagenes_urls FROM propiedades WHERE id = %s", (propiedad_id,))
    if not prop:
        return {"error": f"Propiedad {propiedad_id} no encontrada"}

    sesion = build_session()
    v = diagnosticar(sesion, prop["url"])
    if v.veredicto == INCIERTO and (v.motivo in MOTIVOS_DE_RED or (v.status or 0) >= 500):
        v = diagnosticar(sesion, prop["url"])  # un reintento: el portal a veces tarda
    if actualizar:
        _revisar_portada(sesion, v, prop["imagenes_urls"])

    precio_antes = None
    if actualizar:
        with get_db() as db:
            antes = fetch_one(db.cursor, "SELECT precio FROM propiedades WHERE id = %s", (prop["id"],))
            precio_antes = int(antes["precio"]) if antes and antes["precio"] else None
            _persistir(db.cursor, prop["id"], v, origen)
            db.conn.commit()

    cambio_precio = None
    if v.precio and precio_antes and v.precio != precio_antes:
        cambio_precio = {"precio_anterior": precio_antes, "precio_nuevo": v.precio}
    return {
        "propiedad_id": prop["id"],
        "activo": v.veredicto != MUERTO,
        "estado": _estado(v),
        "status_code": v.status,
        "motivo": v.motivo,
        "de_red": v.veredicto == INCIERTO and (v.motivo in MOTIVOS_DE_RED or (v.status or 0) >= 500),
        "precio_portal": v.precio,
        "cambio_precio": cambio_precio,
        "verificado_en": datetime.now(timezone.utc).isoformat(),
    }


# =========================================================================
# Revalidación continua (worker)
# =========================================================================

# Lock de sesión para que solo una instancia del worker revalide a la vez.
_LOCK_REVALIDACION = 7102

# De cada lote, esta fracción revisa inmuebles que el validador bajó hace más de
# una semana, por si volvieron a publicarse (p. ej. "comercialización suspendida
# temporalmente" en Pulppo).
_FRACCION_RESCATE = 0.1


# Ponerse al día: si hay inmuebles sin revisar dentro del plazo (nunca revisados
# o con el último intento vencido), el lote crece para alcanzarlos en
# _DIAS_PARA_ALCANZAR días, sin pasar de _TOPE_LOTE por corrida (para no
# saturar los portales). Al quedar al día vuelve solo al ritmo normal.
_DIAS_PARA_ALCANZAR = 2
_TOPE_LOTE = 60


def tamano_lote(activas: int, dias_objetivo: int, intervalo_min: int, atrasadas: int = 0) -> int:
    """Cuántas propiedades revisar por corrida para cubrir todas en `dias_objetivo`
    y, si hay atrasadas, alcanzarlas en `_DIAS_PARA_ALCANZAR` días."""
    intervalo = max(1, intervalo_min)
    corridas = max(1, (dias_objetivo * 24 * 60) // intervalo)
    normal = max(1, math.ceil(activas / corridas))
    corridas_alcance = max(1, (_DIAS_PARA_ALCANZAR * 24 * 60) // intervalo)
    alcance = math.ceil(atrasadas / corridas_alcance)
    return max(normal, min(alcance, _TOPE_LOTE))


def _diagnosticar_fila(prop: Dict[str, Any]) -> Tuple[int, Veredicto]:
    sesion = build_session()
    v = diagnosticar(sesion, prop["url"])
    _revisar_portada(sesion, v, prop.get("imagenes_urls"))
    return prop["id"], v


def revalidar_lote(n: Optional[int] = None, hilos: int = 4, url_regex: Optional[str] = None) -> Dict[str, Any]:
    """
    Revisa las `n` propiedades activas con el intento más viejo (las nunca
    revisadas primero), más un 10 % de las que el validador bajó, por si
    volvieron. Si `n` es None, lo calcula para recorrer todo el inventario
    activo en REVALIDACION_DIAS_OBJETIVO días. `url_regex` limita el lote a un
    portal (p. ej. después de arreglar su detector).

    Devuelve {revisadas, desactivadas, reactivadas, inciertas} o {omitido: True}
    si otra instancia ya está corriendo.
    """
    dias = int(os.getenv("REVALIDACION_DIAS_OBJETIVO", "7"))
    intervalo = int(os.getenv("REVALIDACION_INTERVALO_MIN", "30"))

    with get_db() as db:
        # Lock de sesión: se libera al final (o si la conexión se cierra).
        if not scalar(db.cursor, "SELECT pg_try_advisory_lock(%s)", (_LOCK_REVALIDACION,)):
            return {"omitido": True}
        try:
            if n is None:
                cuenta = fetch_one(db.cursor, f"""
                    SELECT COUNT(*) AS activas,
                           COUNT(*) FILTER (WHERE {_SQL_SIN_PROPIOS} AND (fecha_ultimo_intento IS NULL
                               OR fecha_ultimo_intento < NOW() - (%s * INTERVAL '1 day'))) AS atrasadas
                    FROM propiedades WHERE activa
                """, (dias,))
                n = tamano_lote(cuenta["activas"], dias, intervalo, cuenta["atrasadas"])
            props: List[Dict[str, Any]] = fetch_all(db.cursor, f"""
                SELECT id, url, imagenes_urls FROM propiedades
                WHERE activa AND url IS NOT NULL AND url <> '' AND {_SQL_SIN_PROPIOS}
                  AND url ~* %s
                ORDER BY fecha_ultimo_intento NULLS FIRST, id
                LIMIT %s
            """, (url_regex or ".", n))
            props += fetch_all(db.cursor, f"""
                SELECT id, url, imagenes_urls FROM propiedades
                WHERE NOT activa AND desactivada_por = 'validador'
                  AND url IS NOT NULL AND url <> '' AND {_SQL_SIN_PROPIOS}
                  AND COALESCE(fecha_ultimo_intento, fecha_ultima_validacion) < NOW() - INTERVAL '7 days'
                  AND url ~* %s
                ORDER BY COALESCE(fecha_ultimo_intento, fecha_ultima_validacion), id
                LIMIT %s
            """, (url_regex or ".", max(1, int(n * _FRACCION_RESCATE))))
            db.conn.commit()

            with ThreadPoolExecutor(max_workers=hilos) as pool:
                resultados = list(pool.map(_diagnosticar_fila, props))

            cuenta = {"desactivada": 0, "reactivada": 0, "fotos_renovadas": 0, "fotos_rotas": 0}
            inciertas = 0
            for pid, v in resultados:
                cambio = _persistir(db.cursor, pid, v, "worker")
                if cambio:
                    cuenta[cambio] += 1
                inciertas += v.veredicto == INCIERTO
            db.conn.commit()
        finally:
            db.cursor.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_REVALIDACION,))
            db.conn.commit()

    return {"revisadas": len(props), "desactivadas": cuenta["desactivada"],
            "reactivadas": cuenta["reactivada"], "inciertas": inciertas,
            "fotos_renovadas": cuenta["fotos_renovadas"], "fotos_rotas": cuenta["fotos_rotas"]}


# =========================================================================
# Salud del inventario (skill /validate-links, admin)
# =========================================================================

def salud(dias_sla: int = 8) -> Dict[str, Any]:
    """Frescura por portal y lo que hizo el validador en los últimos 7 días."""
    with get_db() as db:
        por_portal = fetch_all(db.cursor, f"""
            SELECT CASE
                     WHEN url ~* 'wasi\\.co' THEN 'wasi'
                     WHEN url ~* 'lobbieapp\\.com' THEN 'lobbie'
                     WHEN url ~* 'pulppo' THEN 'pulppo'
                     WHEN url ~* '(fyndercol\\.netlify\\.app|getfynder\\.com)' THEN 'propio'
                     ELSE 'generico' END AS portal,
                   COUNT(*) AS activas,
                   COUNT(*) FILTER (WHERE fecha_ultima_validacion > NOW() - INTERVAL '{int(dias_sla)} days') AS frescas,
                   COUNT(*) FILTER (WHERE fecha_ultimo_intento IS NULL) AS nunca_revisadas
            FROM propiedades WHERE activa
            GROUP BY 1 ORDER BY 2 DESC
        """)
        semana = fetch_all(db.cursor, """
            SELECT portal, veredicto, COUNT(*) AS n,
                   COUNT(*) FILTER (WHERE cambio = 'desactivada') AS desactivadas,
                   COUNT(*) FILTER (WHERE cambio = 'reactivada') AS reactivadas
            FROM verificaciones_disponibilidad
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY 1, 2 ORDER BY 1, 2
        """)
        motivos_inciertos = fetch_all(db.cursor, """
            SELECT portal, motivo, COUNT(*) AS n
            FROM verificaciones_disponibilidad
            WHERE created_at > NOW() - INTERVAL '7 days' AND veredicto = 'incierto'
            GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 10
        """)
    total = sum(r["activas"] for r in por_portal) or 0
    frescas = sum(r["frescas"] for r in por_portal) or 0
    return {
        "activas": total,
        "frescas": frescas,
        "pct_sla": round(100 * frescas / total, 1) if total else None,
        "por_portal": por_portal,
        "ultima_semana": semana,
        "inciertos_frecuentes": motivos_inciertos,
    }
