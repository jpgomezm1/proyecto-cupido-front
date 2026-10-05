"""
Búsqueda inversa: dado un INMUEBLE, qué PEDIDOS de compradores encajan mejor.

1. `resolver_inmueble(entrada)` entiende lo que pegó el agente: un link de
   Wasi/Lobbie (se lee con el scraper, sin guardarlo), un link o código de
   Fynder, o una descripción en texto (Claude la vuelve ficha).
2. `puntuar(ficha, criterios)` compara la ficha con los criterios estructurados
   de un pedido (pedidos.criterios, ver pedidos_ia) y devuelve un puntaje 0-100
   con razones legibles (✓ zona, ✗ pide balcón...). Algunas cosas descartan:
   otro tipo de inmueble, venta vs arriendo, zona excluida, muy por encima del
   presupuesto, algo que el comprador "no acepta".
3. `buscar_compradores(ficha)` puntúa los pedidos recientes y devuelve los
   mejores, con `desbloqueable` (mismas reglas que el cobro) y sin contactos.

Sin Flask: lo usan la API (Findy) y el MCP (find_buyers_for_property).
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from src.services.db import get_db, fetch_all
from src.services.redact import redact_phones
from src.services.textutils import format_cop, strip_accents

DIAS_PEDIDOS = 120          # ventana de pedidos que se consideran (= vigencia de desbloqueo)
PUNTAJE_MINIMO = 60

# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------

_RUIDO = {"el", "la", "los", "las", "de", "del", "sector", "barrio", "zona", "san", "santa"}


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", strip_accents(s or "").lower()).strip()


def _tokens(s: Optional[str]) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", _norm(s)) if t not in _RUIDO and len(t) > 2}


def _misma_zona(a: Optional[str], b: Optional[str]) -> bool:
    """'El Poblado' ~ 'poblado'; 'Loma de las Brujas' ~ 'Las Brujas'; 'Laureles Estadio' ~ 'Laureles'."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb and (ta <= tb or tb <= ta))


_FAMILIA_TIPO = {
    "apartamento": "apto", "apartaestudio": "apto", "penthouse": "apto", "duplex": "apto",
    "casa": "casa", "casa campestre": "campestre", "finca": "campestre",
    "lote": "lote", "local": "comercial", "oficina": "comercial", "consultorio": "comercial", "bodega": "bodega",
}


def _familia(tipo: Optional[str]) -> Optional[str]:
    t = _norm(tipo)
    if not t:
        return None
    for clave, fam in _FAMILIA_TIPO.items():
        if clave in t:
            return fam
    if "apto" in t or "aparta" in t or "estudio" in t:
        return "apto"
    return t


# ---------------------------------------------------------------------------
# 1 · Resolver el inmueble
# ---------------------------------------------------------------------------

_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_CODIGO = re.compile(r"(?:c[oó]d(?:igo)?\.?|#|ref\.?)\s*:?\s*([A-Za-z0-9-]{3,})", re.I)
_DOMINIOS_FYNDER = ("getfynder.com", "fyndercol.netlify.app", "fynder")


def es_entrada_de_inmueble(texto: str) -> bool:
    """¿El mensaje trae un link? (los links siempre son 'tengo este inmueble')."""
    return bool(_URL.search(texto or ""))


def _primera_imagen(urls) -> Optional[str]:
    if isinstance(urls, list):
        return urls[0] if urls else None
    if isinstance(urls, str) and urls.strip():
        return re.split(r"[,\s|]+", urls.strip())[0] or None
    return None


def _ficha_desde_propiedad(p: Dict[str, Any], origen: str = "fynder") -> Dict[str, Any]:
    amen = []
    for campo in ("amenidades_internas", "amenidades_externas"):
        v = p.get(campo)
        if isinstance(v, str):
            amen += [x.strip().lower() for x in re.split(r"[,;|]", v) if x.strip()]
        elif isinstance(v, list):
            amen += [str(x).strip().lower() for x in v if x]
    return {
        "origen": origen,
        "id": p.get("id"),
        "share_slug": p.get("slug") or (str(p["id"]) if p.get("id") else None),
        "titulo": p.get("titulo"),
        "tipo": p.get("tipo_propiedad"),
        "negocio": _norm(p.get("tipo_negocio")) or None,
        "ciudad": p.get("ciudad"),
        "zona": p.get("zona"),
        "precio": int(p["precio"]) if p.get("precio") else None,
        "habitaciones": p.get("habitaciones"),
        "banos": p.get("banos"),
        "parqueaderos": p.get("parqueaderos"),
        "area_m2": float(p["area_construida"]) if p.get("area_construida") else (
            float(p["area_m2"]) if p.get("area_m2") else None),
        "amenidades": amen,
        "texto": " ".join(str(p.get(k) or "") for k in ("titulo", "descripcion", "descripcion_ai")),
        "imagen": p.get("imagen_principal") or _primera_imagen(p.get("imagenes_urls")),
        "url_origen": p.get("url") or p.get("url_original"),
    }


def _desde_fynder(cur, ref: str) -> Optional[Dict[str, Any]]:
    from src.services.property_service import get_property
    ref = ref.strip().strip("/")
    candidatos = [ref]
    m = re.match(r"^(\d+)", ref)  # /compartir/8387626-apartamento-... -> 8387626
    if m:
        candidatos.append(m.group(1))
    from src.services.db import scalar
    for c in candidatos:
        p = get_property(cur, c)  # número -> id interno; texto -> código
        if p:
            return p
        if c.isdigit():  # los links y códigos que ven los agentes usan codigo_propiedad
            pid = scalar(cur, "SELECT id FROM propiedades WHERE codigo_propiedad = %s LIMIT 1", (c,))
            if pid:
                return get_property(cur, pid)
    return None


def _scrape(url: str) -> Tuple[Optional[Dict[str, Any]], str]:
    host = _norm(url)
    if "lobbie" in host:
        from src.scrapers.lobbie import LobbieScraper
        return LobbieScraper().extract_property_data(url), "lobbie"
    from src.scrapers.wasi import WasiScraper  # Wasi también vive en dominios propios de las agencias
    return WasiScraper().extract_property_data(url), "wasi"


def resolver_inmueble(cur, entrada: str) -> Dict[str, Any]:
    """
    Devuelve {"ficha": {...}} o {"error_type": ..., "mensaje_error": ...}.
    error_type: propiedad_no_encontrada | link_no_soportado | datos_insuficientes | ai_unavailable
    """
    entrada = (entrada or "").strip()
    url = _URL.search(entrada)

    if url:
        enlace = url.group(0).rstrip(").,;")
        if any(d in enlace.lower() for d in _DOMINIOS_FYNDER):
            ruta = re.sub(r"^https?://[^/]+", "", enlace).split("?")[0]
            ref = ruta.rstrip("/").split("/")[-1]
            p = _desde_fynder(cur, ref)
            if not p:
                return {"error_type": "propiedad_no_encontrada",
                        "mensaje_error": "No encontré ese inmueble en Fynder. Revisa que el link esté completo."}
            return {"ficha": _ficha_desde_propiedad(p, "fynder")}
        try:
            datos, origen = _scrape(enlace)
        except Exception as e:  # noqa: BLE001
            print(f"[COMPRADORES] scraper falló para {enlace}: {type(e).__name__}: {str(e)[:160]}")
            datos, origen = None, "wasi"
        if not datos or not (datos.get("precio") or datos.get("zona") or datos.get("ciudad")):
            return {"error_type": "link_no_soportado",
                    "mensaje_error": "No pude leer ese link. Por ahora leo links de Wasi y Lobbie; "
                                     "también puedes describirme el inmueble."}
        ficha = _ficha_desde_propiedad({**datos, "url": enlace}, origen)
        ficha["url_origen"] = enlace
        return {"ficha": ficha}

    # Código de Fynder ("código 4521", "#4521") o solo el número
    cod = _CODIGO.search(entrada)
    solo = entrada if re.fullmatch(r"[A-Za-z0-9-]{3,20}", entrada) and any(ch.isdigit() for ch in entrada) else None
    if cod or solo:
        p = _desde_fynder(cur, (cod.group(1) if cod else solo))
        if p:
            return {"ficha": _ficha_desde_propiedad(p, "fynder")}
        if solo:
            return {"error_type": "propiedad_no_encontrada",
                    "mensaje_error": f"No encontré el código {solo} en Fynder."}

    # Descripción en texto -> ficha con IA
    try:
        from src.services.pedidos_ia import ficha_desde_texto
        f = ficha_desde_texto(entrada)
    except Exception as e:  # noqa: BLE001
        print(f"[COMPRADORES] ficha_desde_texto falló: {type(e).__name__}: {str(e)[:160]}")
        return {"error_type": "ai_unavailable", "mensaje_error": None}
    if not (f.get("precio") or f.get("zona") or f.get("ciudad")):
        return {"error_type": "datos_insuficientes",
                "mensaje_error": "Me falta al menos la zona o el precio del inmueble para buscarle compradores."}
    return {"ficha": {
        "origen": "texto", "id": None, "share_slug": None, "titulo": None,
        "tipo": f.get("tipo"), "negocio": f.get("negocio"), "ciudad": f.get("ciudad"), "zona": f.get("zona"),
        "precio": f.get("precio"), "habitaciones": f.get("habitaciones"), "banos": f.get("banos"),
        "parqueaderos": f.get("parqueaderos"), "area_m2": f.get("area_m2"),
        "amenidades": [a.lower() for a in (f.get("amenidades") or [])], "texto": entrada,
        "imagen": None, "url_origen": None,
    }}


def ficha_publica(ficha: Dict[str, Any]) -> Dict[str, Any]:
    """Lo que se devuelve al frontend (sin el texto crudo)."""
    pub = {k: ficha.get(k) for k in ("origen", "id", "share_slug", "titulo", "tipo", "negocio", "ciudad",
                                       "zona", "precio", "habitaciones", "banos", "parqueaderos",
                                       "area_m2", "imagen", "url_origen")}
    pub["precio_legible"] = format_cop(ficha["precio"]) if ficha.get("precio") else None
    return pub


# ---------------------------------------------------------------------------
# 2 · Puntaje inmueble <-> pedido
# ---------------------------------------------------------------------------

def _tiene(ficha: Dict[str, Any], requisito: str) -> Optional[bool]:
    """True si la ficha lo menciona; None si no hay cómo saberlo (por confirmar)."""
    r = _norm(requisito)
    if not r:
        return None
    pool = " ".join([_norm(a) for a in ficha.get("amenidades") or []] + [_norm(ficha.get("texto"))])
    if not pool.strip():
        return None
    raiz = r[:-1] if len(r) > 5 else r  # balcon/balcones
    return True if raiz in pool else None


_SINGULAR = {"habitaciones": "habitación", "baños": "baño", "parqueaderos": "parqueadero"}


def puntuar(ficha: Dict[str, Any], c: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]], bool]:
    """Devuelve (puntaje 0-100, razones, descartado)."""
    razones: List[Dict[str, Any]] = []
    puntos = 0.0
    posibles = 0.0

    def razon(criterio, ok, texto):
        razones.append({"criterio": criterio, "ok": ok, "texto": texto})

    # Venta vs arriendo
    neg_p, neg_f = c.get("negocio"), _norm(ficha.get("negocio"))
    if neg_p and neg_f and neg_p not in neg_f:
        return 0, [], True

    # Tipo (descarta si es de otra familia)
    tipos = c.get("tipos") or []
    fam_f = _familia(ficha.get("tipo"))
    if tipos and fam_f:
        if fam_f not in {_familia(t) for t in tipos}:
            return 0, [], True
        puntos += 10
        razon("tipo", True, (ficha.get("tipo") or tipos[0]).capitalize())
    posibles += 10

    # Exclusiones explícitas ("NO dúplex")
    for ex in c.get("excluye") or []:
        if _tiene(ficha, ex) or _norm(ex) in _norm(ficha.get("tipo")):
            return 0, [], True

    # Zona (30)
    zona_f, ciudad_f = ficha.get("zona"), ficha.get("ciudad")
    for z in c.get("zonas_excluidas") or []:
        if _misma_zona(z, zona_f):
            return 0, [], True
    zonas, ciudades = c.get("zonas") or [], c.get("ciudades") or []
    posibles += 30
    if zonas and any(_misma_zona(z, zona_f) or _misma_zona(z, ciudad_f) for z in zonas):
        puntos += 30
        razon("zona", True, zona_f or ciudad_f)
    elif not zonas and ciudades and any(_misma_zona(cc, ciudad_f) for cc in ciudades):
        # Solo pidió la ciudad: cumple, aunque menos preciso que un barrio
        puntos += 22
        razon("zona", True, ciudad_f)
    elif zonas or ciudades:
        # Pidió barrios y ninguno coincide (aunque sea la misma ciudad): no cumple
        razon("zona", False, f"Busca en {', '.join((zonas or ciudades)[:2])}")
    else:
        puntos += 12

    # Presupuesto (25)
    precio, pmax, pmin = ficha.get("precio"), c.get("presupuesto_max"), c.get("presupuesto_min")
    posibles += 25
    if precio and pmax:
        if precio > pmax * 1.3:
            return 0, [], True
        if precio <= pmax * 1.05 and (not pmin or precio >= pmin * 0.75):
            puntos += 25 if precio >= pmax * 0.6 else 15
            razon("presupuesto", True, f"Hasta {format_cop(pmax)}")
        elif precio <= pmax * 1.15:
            puntos += 12
            razon("presupuesto", None, f"Un poco por encima: hasta {format_cop(pmax)}")
        else:
            razon("presupuesto", False, f"Hasta {format_cop(pmax)}")
    elif pmax:
        razon("presupuesto", None, f"Hasta {format_cop(pmax)}")
        puntos += 8
    else:
        puntos += 10

    # Habitaciones (12), baños (5), área (8), parqueaderos (5)
    def minimo(campo_p, campo_f, peso, etiqueta):
        nonlocal puntos, posibles
        criterio = campo_f  # habitaciones | banos | parqueaderos
        req, val = c.get(campo_p), ficha.get(campo_f)
        if not req:
            return
        posibles += peso
        if val is None:
            razon(criterio, None, f"Pide {req}+ {etiqueta}")
            puntos += peso * 0.4
        elif val >= req:
            puntos += peso
            razon(criterio, True, f"{val} {_SINGULAR.get(etiqueta, etiqueta) if val == 1 else etiqueta}")
        elif val == req - 1:
            puntos += peso * 0.3
            razon(criterio, False, f"Pide {req}+ {etiqueta}")
        else:
            razon(criterio, False, f"Pide {req}+ {etiqueta}")

    minimo("habitaciones_min", "habitaciones", 12, "habitaciones")
    minimo("banos_min", "banos", 5, "baños")
    minimo("parqueaderos_min", "parqueaderos", 5, "parqueaderos")

    area, amin, amax = ficha.get("area_m2"), c.get("area_min"), c.get("area_max")
    if amin or amax:
        posibles += 8
        if area is None:
            puntos += 3
            razon("area", None, f"Pide {int(amin or 0)}–{int(amax) if amax else '+'} m²")
        elif (not amin or area >= amin * 0.92) and (not amax or area <= amax * 1.1):
            puntos += 8
            razon("area", True, f"{int(area)} m²")
        else:
            razon("area", False, f"Pide {int(amin) if amin else ''}{'–' + str(int(amax)) if amax else '+'} m²".replace("Pide –", "Pide hasta "))

    # Exigencias (8)
    exig = c.get("exigencias") or []
    if exig:
        posibles += 8
        cumplidas = 0
        for e in exig[:5]:
            t = _tiene(ficha, e)
            if t:
                cumplidas += 1
            razon("exigencias", t, e)
        puntos += 8 * (cumplidas / min(len(exig), 5)) if exig else 0

    puntaje = int(round(100 * puntos / posibles)) if posibles else 0
    # La zona y el presupuesto mandan: sin zona no pasa de 55
    if any(r["criterio"] == "zona" and r["ok"] is False for r in razones):
        puntaje = min(puntaje, 55)
    return max(0, min(100, puntaje)), razones, False


# ---------------------------------------------------------------------------
# 3 · Buscar compradores
# ---------------------------------------------------------------------------

_SQL_DESBLOQUEABLE = f"""
    (p.fecha_captura > NOW() - INTERVAL '{DIAS_PEDIDOS} days' AND EXISTS (
        SELECT 1 FROM chat_users u
        WHERE u.activo AND u.telefono_verificado AND u.terminos_aceptados_at IS NOT NULL
          AND RIGHT(REGEXP_REPLACE(COALESCE(u.telefono,''),'[^0-9]','','g'),10)
            = RIGHT(REGEXP_REPLACE(COALESCE(p.agente_telefono,''),'[^0-9]','','g'),10)
    ))
"""


def buscar_compradores(cur, ficha: Dict[str, Any], user_id: Optional[int] = None,
                       dias: int = DIAS_PEDIDOS, limit: int = 15) -> Dict[str, Any]:
    precio = ficha.get("precio")
    condiciones = ["p.criterios IS NOT NULL", "p.fecha_captura > NOW() - make_interval(days => %s)"]
    params: List[Any] = [dias]
    if precio:
        # Prefiltro barato: presupuesto desconocido o que alcance (techo 1.3x ya lo descarta puntuar)
        condiciones.append("(NULLIF(p.criterios->>'presupuesto_max','') IS NULL "
                           "OR (p.criterios->>'presupuesto_max')::numeric >= %s)")
        params.append(int(precio / 1.3))
    filas = fetch_all(cur, f"""
        SELECT p.id, p.texto_pedido, p.presupuesto_estimado, p.fecha_captura, p.criterios,
               {_SQL_DESBLOQUEABLE} AS desbloqueable
        FROM pedidos p
        WHERE {' AND '.join(condiciones)}
    """, params)

    candidatos = []
    for f in filas:
        crit = f["criterios"] if isinstance(f["criterios"], dict) else {}
        puntaje, razones, descartado = puntuar(ficha, crit)
        if descartado or puntaje < PUNTAJE_MINIMO:
            continue
        candidatos.append((puntaje, f, razones, crit))
    candidatos.sort(key=lambda x: (-x[0], -(x[1]["fecha_captura"].timestamp() if x[1].get("fecha_captura") else 0)))
    top = candidatos[:limit]

    vistos = set()
    if user_id and top:
        from src.services import suscripcion_service as suscripciones
        vistos = suscripciones.ids_desbloqueados(user_id, "pedido", [t[1]["id"] for t in top])

    compradores = []
    for puntaje, f, razones, crit in top:
        pmax = crit.get("presupuesto_max") or f.get("presupuesto_estimado")
        compradores.append({
            "pedido_id": f["id"],
            "busca": redact_phones(f["texto_pedido"] or "", cut_signatures=True),
            "score": puntaje,
            "razones": razones,
            "presupuesto_estimado": int(pmax) if pmax else None,
            "presupuesto_legible": format_cop(pmax) if pmax else None,
            "fecha": f["fecha_captura"].isoformat() if f.get("fecha_captura") else None,
            "desbloqueable": bool(f.get("desbloqueable")),
            "contacto_desbloqueado": f["id"] in vistos,
        })
    return {"total_found": len(candidatos), "compradores": compradores}


def buscar_compradores_public(entrada: str, user_id: Optional[int] = None, limit: int = 15) -> Dict[str, Any]:
    """Atajo para quien no tiene cursor (MCP): resuelve + busca."""
    with get_db() as db:
        r = resolver_inmueble(db.cursor, entrada)
        if "ficha" not in r:
            return {"modo": "compradores", "propiedad": None, "total_found": 0, "compradores": [], **r}
        res = buscar_compradores(db.cursor, r["ficha"], user_id, limit=limit)
        return {"modo": "compradores", "propiedad": ficha_publica(r["ficha"]), **res,
                "error_type": None, "mensaje_error": None}
