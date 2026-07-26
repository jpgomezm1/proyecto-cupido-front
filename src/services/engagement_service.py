"""
Servicio de interés real (termómetro), sobre `share_events`.

Los agentes no pueden ver qué tanto se mira/comparte una propiedad. Esta señal
—vistas, clics, clics a WhatsApp/teléfono— es un funnel de interés REAL que
distingue "no la ven" (problema de exposición) de "la ven pero no llaman"
(problema de precio o presentación).

Eventos: share_viewed, property_clicked, whatsapp_clicked, phone_clicked.
"""

from typing import Any, Dict, List, Optional

from src.services.db import get_db, fetch_one, fetch_all
from src.services.property_service import get_property


def _interes_de_propiedad(cur, property_id: int, dias: int) -> Dict[str, Any]:
    """Cuenta el funnel de interés de una propiedad en los últimos `dias`."""
    row = fetch_one(cur, """
        SELECT
            COUNT(*) FILTER (WHERE event_type IN ('share_viewed','property_clicked')) AS vistas,
            COUNT(*) FILTER (WHERE event_type = 'property_clicked')                    AS clics,
            COUNT(*) FILTER (WHERE event_type = 'whatsapp_clicked')                    AS whatsapp,
            COUNT(*) FILTER (WHERE event_type = 'phone_clicked')                       AS telefono,
            COUNT(DISTINCT visitor_id)                                                 AS visitantes_unicos
        FROM share_events
        WHERE property_id = %s
          AND created_at > NOW() - make_interval(days => %s)
    """, (property_id, dias)) or {}
    return {
        "vistas": int(row.get("vistas") or 0),
        "clics": int(row.get("clics") or 0),
        "contactos_whatsapp": int(row.get("whatsapp") or 0),
        "contactos_telefono": int(row.get("telefono") or 0),
        "visitantes_unicos": int(row.get("visitantes_unicos") or 0),
    }


def _lectura(f: Dict[str, Any]) -> Dict[str, str]:
    """Traduce el funnel a un diagnóstico en lenguaje de agente."""
    vistas = f["vistas"]
    contactos = f["contactos_whatsapp"] + f["contactos_telefono"]
    if vistas == 0:
        return {"estado": "sin_exposicion",
                "lectura": "Nadie la está viendo. El problema no es la propiedad, es que no está circulando: compártela más (grupos, base de clientes, redes)."}
    if contactos == 0 and vistas >= 15:
        return {"estado": "mira_pero_no_contacta",
                "lectura": f"La han visto {vistas} veces pero 0 la contactan. Eso NO es exposición, es precio o presentación: revisa el precio y las fotos."}
    if contactos == 0:
        return {"estado": "poca_data",
                "lectura": f"Solo {vistas} vistas todavía; muy poca data para concluir. Dale más difusión unos días."}
    tasa = round(contactos / vistas * 100)
    return {"estado": "convirtiendo",
            "lectura": f"Buena señal: {contactos} contacto(s) de {vistas} vistas ({tasa}% de conversión). Hay interés real; haz seguimiento a esos leads."}


def termometro_de_interes(cur, property_id, dias: int = 30) -> Dict[str, Any]:
    """Funnel de interés de una propiedad + diagnóstico accionable."""
    base = get_property(cur, property_id)
    if not base:
        return {"error": f"Propiedad {property_id} no encontrada"}
    funnel = _interes_de_propiedad(cur, base["id"], dias)
    return {
        "propiedad": {"id": base["id"], "slug": base["slug"], "titulo": base["titulo"],
                      "precio_legible": base["precio_legible"], "zona": base["zona"],
                      "link_compartir": base.get("link_compartir")},
        "ventana_dias": dias,
        "interes": funnel,
        **_lectura(funnel),
    }


def mis_listings_calientes(cur, telefono_10: str, dias: int = 30, limit: int = 20) -> Dict[str, Any]:
    """
    Rankea las propiedades del agente por interés real (vistas + contactos) en la
    ventana. Muestra cuáles jalan y cuáles están muertas.
    """
    if not telefono_10:
        return {"total": 0, "listings": [], "sin_scope": True}

    rows = fetch_all(cur, """
        SELECT
            p.id, p.codigo_propiedad AS slug, p.titulo, p.precio, p.zona,
            COUNT(*) FILTER (WHERE e.event_type IN ('share_viewed','property_clicked')) AS vistas,
            COUNT(*) FILTER (WHERE e.event_type IN ('whatsapp_clicked','phone_clicked')) AS contactos
        FROM propiedades p
        LEFT JOIN share_events e
               ON e.property_id = p.id
              AND e.created_at > NOW() - make_interval(days => %s)
        WHERE p.activa = TRUE
          AND RIGHT(REGEXP_REPLACE(p.agente_captador_telefono, '[^0-9]', '', 'g'), 10) = %s
        GROUP BY p.id, p.codigo_propiedad, p.titulo, p.precio, p.zona
        ORDER BY vistas DESC, contactos DESC
        LIMIT %s
    """, (dias, telefono_10, limit))

    from src.services.textutils import format_cop
    listings = [{
        "id": r["id"], "slug": r["slug"], "titulo": r["titulo"],
        "precio_legible": format_cop(r["precio"]), "zona": r["zona"],
        "vistas": int(r["vistas"] or 0), "contactos": int(r["contactos"] or 0),
    } for r in rows]

    calientes = [l for l in listings if l["contactos"] > 0]
    frias = [l for l in listings if l["vistas"] == 0]
    return {
        "ventana_dias": dias,
        "total": len(listings),
        "resumen": {
            "con_contactos": len(calientes),
            "sin_ninguna_vista": len(frias),
        },
        "listings": listings,
    }


# ---- wrappers públicos ----
def termometro_public(property_id, dias=30):
    with get_db() as db:
        return termometro_de_interes(db.cursor, property_id, dias)


def mis_calientes_public(telefono_10, dias=30, limit=20):
    with get_db() as db:
        return mis_listings_calientes(db.cursor, telefono_10, dias, limit)
