"""
Piezas compartibles con el CLIENTE FINAL: comparativa de inmuebles y brochure.

Genera links firmados (stateless) que abren una página visual —bonita, con
branding Fynder— pensada para que el agente se la mande a su cliente por
WhatsApp. NUNCA expone datos de contacto de agentes (es para el cliente final).

- Tokens HMAC que codifican los IDs de las propiedades (no expiran pronto).
- `datos_comparativa` / `datos_brochure`: proyección limpia para renderizar.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, List, Optional

from src.services.db import get_db, fetch_one, fetch_all
from src.services.property_service import get_property
from src.services.textutils import format_cop, split_image_urls

_TTL = 60 * 60 * 24 * 365  # 1 año


class ShareError(Exception):
    pass


def _secret() -> bytes:
    s = os.getenv("FYNDER_MCP_SECRET") or os.getenv("JWT_SECRET")
    if not s:
        raise ShareError("Falta FYNDER_MCP_SECRET en el entorno")
    return s.encode("utf-8")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: Dict[str, Any]) -> str:
    payload = {**payload, "exp": int(time.time()) + _TTL}
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def make_token(kind: str, ids: List[int]) -> str:
    return _sign({"k": kind, "ids": [int(i) for i in ids]})


def make_token_zona(ciudad, zona, tipo) -> str:
    return _sign({"k": "zona", "ciudad": ciudad, "zona": zona, "tipo": tipo})


def verify_token(token: str) -> Dict[str, Any]:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        raise ShareError("Link inválido")
    expected = _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise ShareError("Link inválido (firma)")
    payload = json.loads(_b64d(body))
    if payload.get("exp", 0) < int(time.time()):
        raise ShareError("El link expiró")
    return payload


def _frontend_base() -> str:
    return os.getenv("FYNDER_FRONTEND_URL", "https://fyndercol.netlify.app").rstrip("/")


def link_comparativa(ids: List[int]) -> str:
    # Link elegante con el dominio de Fynder (la página vive en el portal React).
    return f"{_frontend_base()}/comparar/{make_token('cmp', ids)}"


def link_brochure(property_id: int) -> str:
    return f"{_frontend_base()}/ficha/{make_token('fic', [property_id])}"


def link_reporte_zona(ciudad, zona, tipo) -> str:
    return f"{_frontend_base()}/zona/{make_token_zona(ciudad, zona, tipo)}"


# --------------------------------------------------------------------------
# Datos limpios para renderizar (SIN info de agente).
# --------------------------------------------------------------------------

def _prop_limpia(cur, pid: int) -> Optional[Dict[str, Any]]:
    """Proyección visual de una propiedad para el cliente final."""
    p = get_property(cur, pid)
    if not p:
        return None
    from src.services.textutils import build_share_link
    return {
        "id": p["id"],
        "slug": p.get("slug"),
        "link_detalle": build_share_link(p["id"], p.get("titulo")),  # detalle en el portal de Fynder
        "titulo": p.get("titulo") or "Propiedad",
        "precio": p.get("precio"),
        "precio_legible": p.get("precio_legible"),
        "ciudad": p.get("ciudad"),
        "zona": p.get("zona"),
        "tipo": p.get("tipo_propiedad"),
        "area": p.get("area_construida"),
        "precio_m2": p.get("precio_m2"),
        "habitaciones": p.get("habitaciones"),
        "banos": p.get("banos"),
        "parqueaderos": p.get("parqueaderos"),
        "estrato": p.get("estrato"),
        "ano": p.get("ano_construccion"),
        "administracion": p.get("administracion"),
        "amenidades": [a.strip() for a in
                       ((p.get("amenidades_internas") or "") + "|" + (p.get("amenidades_externas") or "")).split("|")
                       if a.strip()],
        "descripcion": p.get("descripcion_ai") or p.get("descripcion"),
        "imagenes": p.get("imagenes_urls") or ([p["imagen_principal"]] if p.get("imagen_principal") else []),
        "imagen_principal": p.get("imagen_principal"),
    }


def datos_comparativa(ids: List[int]) -> Dict[str, Any]:
    with get_db() as db:
        props = [x for x in (_prop_limpia(db.cursor, i) for i in ids) if x]
    if not props:
        return {"error": "No se encontraron las propiedades"}

    # Veredictos simples (para destacar en la UI).
    con_m2 = [p for p in props if p.get("precio_m2")]
    mejor_valor = min(con_m2, key=lambda p: p["precio_m2"])["id"] if con_m2 else None
    con_precio = [p for p in props if p.get("precio")]
    mas_economica = min(con_precio, key=lambda p: p["precio"])["id"] if con_precio else None
    con_area = [p for p in props if p.get("area")]
    mas_amplia = max(con_area, key=lambda p: p["area"])["id"] if con_area else None

    return {
        "propiedades": props,
        "veredicto": {"mejor_valor": mejor_valor, "mas_economica": mas_economica, "mas_amplia": mas_amplia},
    }


def datos_brochure(property_id: int) -> Dict[str, Any]:
    with get_db() as db:
        p = _prop_limpia(db.cursor, property_id)
    if not p:
        return {"error": "Propiedad no encontrada"}
    return {"propiedad": p}


def datos_reporte_zona(ciudad, zona, tipo) -> Dict[str, Any]:
    """
    Reporte de mercado COMPLETO de una zona para MANDARLE A UN DUEÑO (captación).
    Traducido a lenguaje de propietario, no de estadístico.
    """
    from src.services.market_service import supply_demand_balance, segmentos_precio
    from src.services.textutils import accent_insensitive_expr, like_param
    with get_db() as db:
        bal = supply_demand_balance(db.cursor, ciudad, zona, tipo, "Venta")
        segmentos = segmentos_precio(db.cursor, ciudad, zona, tipo)
        # Muestra de coordenadas válidas (dentro de Colombia) para el mapa.
        term = like_param(zona or ciudad or "")
        puntos = fetch_all(db.cursor, f"""
            SELECT latitud, longitud, precio
            FROM propiedades p
            WHERE p.activa AND p.tipo_negocio='Venta' AND p.precio > 0
              AND {accent_insensitive_expr('p.tipo_propiedad')} LIKE %s
              AND ({accent_insensitive_expr('p.ciudad')} LIKE %s OR {accent_insensitive_expr('p.zona')} LIKE %s)
              AND p.latitud BETWEEN 1 AND 13 AND p.longitud BETWEEN -80 AND -66
            LIMIT 400
        """, (like_param(tipo), term, term))

    of = bal.get("detalle_oferta", {})
    dem = bal.get("detalle_demanda", {})
    precio = of.get("precio", {})
    inventario = bal.get("oferta_inventario", 0)
    demanda = bal.get("demanda_total", 0)
    dias = of.get("dias_inventario_promedio")
    clas = bal.get("clasificacion")
    mix = of.get("mix_habitaciones", [])

    if clas == "caliente":
        lectura = ("Es momento de VENDEDOR: hay bastantes más compradores buscando que "
                   "propiedades en venta. Buen momento para poner tu inmueble en el mercado.")
    elif clas == "equilibrado":
        lectura = ("El mercado está equilibrado, con buena demanda. Con el precio y la "
                   "presentación correctos, tu propiedad se puede mover bien.")
    elif clas == "frio":
        lectura = ("Hay bastante oferta en la zona; para destacar es clave un buen precio y "
                   "una presentación impecable. Ahí es donde te acompañamos.")
    else:
        lectura = "Analicemos juntos el mejor momento y precio para tu propiedad."

    lugar = " · ".join([x for x in [zona, ciudad] if x]) or (ciudad or "la zona")

    # Recomendaciones accionables generadas con la data.
    recos = []
    huecos = [s for s in segmentos if s["hueco"] and s["oferta"] > 0]
    if huecos:
        h = max(huecos, key=lambda s: s["demanda"] - s["oferta"])
        recos.append(f"En el rango {h['rango']} hay {h['demanda']} compradores buscando y solo "
                     f"{h['oferta']} en venta: si tu propiedad entra ahí, tienes ventaja.")
    if dias and dias > 100:
        recos.append(f"El inventario tarda ~{round(dias)} días en venderse en promedio. Un precio bien "
                     f"puesto desde el inicio acorta ese tiempo notablemente.")
    fotos = of.get("fotos_promedio")
    if fotos:
        recos.append(f"Los avisos de la zona traen ~{round(fotos)} fotos. Una buena presentación "
                     f"(fotos, video, descripción) hace que tu propiedad destaque.")
    pres_med = dem.get("presupuesto_pedidos_mediana")
    if pres_med:
        recos.append(f"El comprador típico de la zona maneja un presupuesto cercano a "
                     f"{format_cop(pres_med)}. Ubicar tu precio cerca de ahí amplía tu pool de compradores.")

    hab_labels = {0: "Estudios", 1: "1 hab", 2: "2 hab", 3: "3 hab", 4: "4 hab", 5: "5+ hab"}
    mix_out = [{"label": hab_labels.get(m["habitaciones"], f'{m["habitaciones"]} hab'),
                "cantidad": m["cantidad"]} for m in mix if m.get("cantidad")]

    # Puntos del mapa + centro (promedio).
    mapa = [{"lat": float(p["latitud"]), "lng": float(p["longitud"]),
             "precio": int(p["precio"]) if p["precio"] else None} for p in puntos]
    centro = None
    if mapa:
        centro = {"lat": sum(p["lat"] for p in mapa) / len(mapa),
                  "lng": sum(p["lng"] for p in mapa) / len(mapa)}

    return {
        "lugar": lugar, "ciudad": ciudad, "zona": zona, "tipo": tipo or "propiedad",
        "resumen": {
            "en_venta": inventario,
            "compradores_buscando": demanda,
            "clasificacion": clas,
            "precio_tipico": precio.get("mediana_legible"),
            "precio_min": format_cop(precio.get("p25")) if precio.get("p25") else None,
            "precio_max": format_cop(precio.get("p75")) if precio.get("p75") else None,
            "precio_m2": format_cop(of.get("precio_m2_mediana")) if of.get("precio_m2_mediana") else None,
            "dias_en_venta_promedio": round(dias) if dias else None,
            "fotos_promedio": round(fotos) if fotos else None,
            "area_promedio": round(of.get("area_promedio")) if of.get("area_promedio") else None,
        },
        "distribucion_precio": {
            "min": format_cop(precio.get("min")), "p25": format_cop(precio.get("p25")),
            "mediana": format_cop(precio.get("mediana")), "p75": format_cop(precio.get("p75")),
            "max": format_cop(precio.get("max")),
        } if precio.get("mediana") else None,
        "demanda": {
            "compradores": demanda,
            "presupuesto_tipico": format_cop(pres_med) if pres_med else None,
            "presupuesto_promedio": format_cop(dem.get("presupuesto_pedidos_promedio")) if dem.get("presupuesto_pedidos_promedio") else None,
        },
        "segmentos_precio": segmentos,
        "mix_oferta": mix_out,
        "recomendaciones": recos,
        "lectura": lectura,
        "mapa": {"centro": centro, "puntos": mapa} if mapa else None,
        "baja_confianza": of.get("baja_confianza", False),
    }


def registrar_vista(kind: str, ids: List[int], visitor: Optional[str] = None) -> None:
    """Registra la apertura de una pieza compartible en share_events (best-effort)."""
    try:
        with get_db() as db:
            for pid in ids:
                db.cursor.execute("""
                    INSERT INTO share_events (event_type, property_id, share_type, property_count, visitor_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                """, (f"{kind}_viewed", pid, "cliente", len(ids), visitor))
            db.conn.commit()
    except Exception:
        pass
