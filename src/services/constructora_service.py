"""
Servicio del portal B2B de constructoras (Bloque E3).

Auth propio (login con email/clave, bcrypt vía pgcrypto en la base), resolución
de sesión por token, y consultas scoped a la constructora (inventario y leads).
Todo lo que devuelve al portal va SIN contacto de agentes (regla de privacidad):
el texto del pedido se entrega redactado.
"""

import secrets
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.services.db import get_db, fetch_one, fetch_all
from src.services.textutils import format_cop, build_share_link, FRONTEND_URL

SESSION_DAYS = 30
_TIPO_NEGOCIO = {"Venta", "Arriendo"}


class ConstructoraError(Exception):
    """Error de validación en el portal de la constructora."""


# =========================================================================
# AUTH
# =========================================================================

def login(email: str, password: str) -> Optional[Dict[str, Any]]:
    """Valida credenciales y crea una sesión. Devuelve token + datos, o None."""
    with get_db() as db:
        row = fetch_one(db.cursor, """
            SELECT u.id AS user_id, u.constructora_id, u.nombre, u.email,
                   c.nombre AS constructora_nombre
            FROM constructora_users u
            JOIN constructoras c ON c.id = u.constructora_id
            WHERE lower(u.email) = lower(%s) AND u.activo = TRUE AND c.activa = TRUE
              AND u.password_hash = crypt(%s, u.password_hash)
        """, (email, password))
        if not row:
            return None

        token = secrets.token_urlsafe(48)
        db.cursor.execute("""
            INSERT INTO constructora_sessions (user_id, token, fecha_expiracion)
            VALUES (%s, %s, NOW() + make_interval(days => %s))
        """, (row["user_id"], token, SESSION_DAYS))
        db.cursor.execute("UPDATE constructora_users SET ultimo_acceso = NOW() WHERE id = %s",
                          (row["user_id"],))
        db.conn.commit()

    return {"token": token, "constructora_id": row["constructora_id"],
            "constructora_nombre": row["constructora_nombre"],
            "nombre": row["nombre"], "email": row["email"]}


def resolve(token: str) -> Optional[Dict[str, Any]]:
    """Resuelve una sesión activa a su contexto de constructora, o None."""
    if not token:
        return None
    with get_db() as db:
        row = fetch_one(db.cursor, """
            SELECT s.id AS session_id, u.id AS user_id, u.constructora_id, u.nombre, u.email,
                   c.nombre AS constructora_nombre
            FROM constructora_sessions s
            JOIN constructora_users u ON u.id = s.user_id
            JOIN constructoras c ON c.id = u.constructora_id
            WHERE s.token = %s AND s.activa = TRUE AND u.activo = TRUE AND c.activa = TRUE
              AND (s.fecha_expiracion IS NULL OR s.fecha_expiracion > NOW())
        """, (token,))
        if row:
            db.cursor.execute("UPDATE constructora_sessions SET ultimo_uso = NOW() WHERE id = %s",
                              (row["session_id"],))
            db.conn.commit()
    return dict(row) if row else None


def logout(token: str) -> None:
    """Revoca una sesión."""
    if not token:
        return
    with get_db() as db:
        db.cursor.execute("UPDATE constructora_sessions SET activa = FALSE WHERE token = %s", (token,))
        db.conn.commit()


# =========================================================================
# INVENTARIO (E3.2) — crear inmuebles de la constructora (3 métodos comparten
# este core). Se guardan con fuente='Constructora' y constructora_id, activos.
# =========================================================================

def _num(data: Dict[str, Any], campo: str, etiqueta: str, entero: bool = False):
    v = data.get(campo)
    if v is None or (isinstance(v, str) and not v.strip()):
        raise ConstructoraError(f"Falta {etiqueta} (campo '{campo}').")
    try:
        v = int(float(v)) if entero else float(v)
    except (TypeError, ValueError):
        raise ConstructoraError(f"{etiqueta} debe ser un número (campo '{campo}').")
    if v <= 0:
        raise ConstructoraError(f"{etiqueta} debe ser mayor a 0 (campo '{campo}').")
    return v


def _opt_int(data: Dict[str, Any], campo: str):
    v = data.get(campo)
    if v is None or (isinstance(v, str) and not str(v).strip()):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _build_property_data(constructora: Dict[str, Any], data: Dict[str, Any],
                         origen_url: Optional[str] = None) -> Dict[str, Any]:
    precio = _num(data, "precio", "el precio", entero=True)
    area = _num(data, "area_construida", "el área en m²")
    tipo = data.get("tipo_propiedad")
    if not tipo or not str(tipo).strip():
        raise ConstructoraError("Falta el tipo de propiedad (campo 'tipo_propiedad').")
    if not (data.get("ciudad") or data.get("zona")):
        raise ConstructoraError("Falta la ubicación: al menos ciudad o zona.")
    tipo_negocio = (data.get("tipo_negocio") or "Venta").strip().title()
    if tipo_negocio not in _TIPO_NEGOCIO:
        raise ConstructoraError(f"tipo_negocio inválido; usa {sorted(_TIPO_NEGOCIO)}.")

    imgs: List[str] = [u for u in (data.get("imagenes_urls") or []) if u]
    codigo = f"CONS-{uuid.uuid4().hex[:16]}"
    url = origen_url or f"{FRONTEND_URL}/propiedad/{codigo}"
    descripcion = (data.get("descripcion") or "").strip() or None

    return {
        "codigo_propiedad": codigo,
        "fuente": "Constructora",
        "url": url,
        "titulo": (data.get("titulo") or "").strip() or None,
        "precio": precio,
        "precio_texto": format_cop(precio),
        "tipo_propiedad": str(tipo).strip(),
        "tipo_negocio": tipo_negocio,
        "estado": "Disponible",
        "pais": data.get("pais") or "Colombia",
        "ciudad": data.get("ciudad"),
        "zona": data.get("zona"),
        "direccion_completa": data.get("direccion_completa") or data.get("direccion"),
        "area_construida": area,
        "habitaciones": _opt_int(data, "habitaciones"),
        "banos": _opt_int(data, "banos"),
        "parqueaderos": _opt_int(data, "parqueaderos"),
        "estrato": _opt_int(data, "estrato"),
        "administracion": _opt_int(data, "administracion"),
        "descripcion": descripcion,
        "descripcion_length": len(descripcion) if descripcion else None,
        "imagenes_urls": "|".join(imgs) if imgs else None,
        "total_imagenes": len(imgs) or None,
        "imagen_principal": imgs[0] if imgs else None,
        "origen": "Constructora_Portal",
        "inmobiliaria": constructora.get("constructora_nombre"),
        "constructora_id": constructora["constructora_id"],
        # Inventario nativo B2B: no anonimizar.
        "anonimizado_version": 1,
        "fecha_extraccion": datetime.now(),
    }


def crear_inmueble(constructora: Dict[str, Any], data: Dict[str, Any],
                   origen_url: Optional[str] = None) -> Dict[str, Any]:
    """Crea UN inmueble de la constructora (activo). Devuelve id + resumen."""
    pd = _build_property_data(constructora, data, origen_url=origen_url)
    with get_db() as db:
        pid = db.insert_property(pd)  # hace commit internamente
        if not pid:
            raise ConstructoraError("No se pudo guardar el inmueble. Intenta de nuevo.")
    return {
        "ok": True, "id": pid, "codigo_propiedad": pd["codigo_propiedad"],
        "titulo": pd["titulo"], "precio_legible": format_cop(pd["precio"]),
        "link_compartir": build_share_link(pid, pd["titulo"]),
    }


def crear_inmuebles_bulk(constructora: Dict[str, Any],
                         items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Crea varios inmuebles (CSV/Excel). Reporta creados y errores por fila."""
    creados, errores = [], []
    for i, item in enumerate(items, start=1):
        try:
            res = crear_inmueble(constructora, item)
            creados.append(res["id"])
        except ConstructoraError as e:
            errores.append({"fila": i, "error": str(e)})
        except Exception as e:  # defensivo: una fila mala no tumba el lote
            errores.append({"fila": i, "error": f"Error inesperado: {e}"})
    return {"ok": True, "creados": len(creados), "ids": creados,
            "errores": errores, "total_recibidos": len(items)}


def _scraper_para(url: str):
    u = (url or "").lower()
    if "wasi" in u:
        from src.scrapers.wasi import WasiScraper
        return WasiScraper(verbose=False, enable_ai_enrichment=False)  # sin IA → sin tokens
    if "lobbie" in u or "lobie" in u:
        from src.scrapers.lobbie import LobbieScraper
        return LobbieScraper(verbose=False)
    if "tu360" in u:
        from src.scrapers.tu360 import Tu360Scraper
        return Tu360Scraper(verbose=False)
    return None


def crear_desde_link(constructora: Dict[str, Any], url: str) -> Dict[str, Any]:
    """Scrapea un link (Wasi/Lobbie/Tu360) y crea el inmueble con constructora_id."""
    if not url or not str(url).startswith("http"):
        raise ConstructoraError("URL inválida.")
    sc = _scraper_para(url)
    if not sc:
        raise ConstructoraError("No reconozco el portal del link (Wasi, Lobbie o Tu360).")
    datos = sc.extract_property_data(url)
    if not datos:
        raise ConstructoraError("No pude extraer datos del link. Verifica que la publicación exista.")
    d = datos.get("datos_normalizados") if isinstance(datos, dict) and datos.get("datos_normalizados") else datos

    mapped = {
        "titulo": d.get("titulo"),
        "precio": d.get("precio"),
        "area_construida": d.get("area_construida") or d.get("area") or d.get("area_privada"),
        "tipo_propiedad": d.get("tipo_propiedad") or d.get("tipo"),
        "ciudad": d.get("ciudad"),
        "zona": d.get("zona"),
        "direccion_completa": d.get("direccion_completa") or d.get("direccion"),
        "habitaciones": d.get("habitaciones"),
        "banos": d.get("banos"),
        "parqueaderos": d.get("parqueaderos"),
        "estrato": d.get("estrato"),
        "administracion": d.get("administracion"),
        "descripcion": d.get("descripcion"),
        "imagenes_urls": d.get("imagenes_urls") or [],
        "tipo_negocio": d.get("tipo_negocio") or "Venta",
    }
    return crear_inmueble(constructora, mapped, origen_url=url)


_ESTADOS_LEAD = {"nuevo", "aceptado", "rechazado"}


def listar_leads(constructora_id: int, estado: Optional[str] = None,
                 limit: int = 100) -> List[Dict[str, Any]]:
    """
    Leads de la constructora: pedido (demanda) ↔ inmueble (su inventario), con
    score y estado. El texto del pedido va REDACTADO (sin contacto de agentes).
    """
    from src.services.redact import redact_phones

    params: List[Any] = [constructora_id]
    filtro_estado = ""
    if estado and estado in _ESTADOS_LEAD:
        filtro_estado = "AND l.estado = %s"
        params.append(estado)
    params.append(limit)

    with get_db() as db:
        rows = fetch_all(db.cursor, f"""
            SELECT l.id AS lead_id, l.score, l.calidad, l.razon, l.estado, l.created_at,
                   pe.id AS pedido_id, pe.texto_pedido, pe.presupuesto_estimado, pe.fecha_captura,
                   p.id AS propiedad_id, p.codigo_propiedad, p.titulo, p.precio,
                   p.zona, p.ciudad, p.habitaciones, p.area_construida
            FROM leads l
            JOIN pedidos pe ON pe.id = l.pedido_id
            JOIN propiedades p ON p.id = l.propiedad_id
            WHERE l.constructora_id = %s {filtro_estado}
            ORDER BY (l.estado = 'nuevo') DESC, l.score DESC
            LIMIT %s
        """, tuple(params))

    out = []
    for r in rows:
        out.append({
            "lead_id": r["lead_id"], "score": r["score"], "calidad": r["calidad"],
            "razon": r["razon"], "estado": r["estado"], "created_at": r["created_at"],
            "pedido": {
                "id": r["pedido_id"],
                # PRIVACIDAD: se redacta el contacto del agente del texto del pedido.
                "texto": redact_phones(r.get("texto_pedido") or "", cut_signatures=True),
                "presupuesto_legible": format_cop(r.get("presupuesto_estimado")),
                "fecha": r.get("fecha_captura"),
            },
            "inmueble": {
                "id": r["propiedad_id"], "codigo": r["codigo_propiedad"], "titulo": r["titulo"],
                "precio_legible": format_cop(r.get("precio")), "zona": r.get("zona"),
                "ciudad": r.get("ciudad"), "habitaciones": r.get("habitaciones"),
                "area_construida": float(r["area_construida"]) if r.get("area_construida") else None,
            },
        })
    return out


def actualizar_estado_lead(constructora_id: int, lead_id: int, estado: str) -> Dict[str, Any]:
    """La constructora acepta/rechaza un lead SUYO. Scoped por constructora_id."""
    if estado not in _ESTADOS_LEAD:
        raise ConstructoraError(f"Estado inválido; usa {sorted(_ESTADOS_LEAD)}.")
    with get_db() as db:
        db.cursor.execute("""
            UPDATE leads SET estado = %s, updated_at = NOW()
            WHERE id = %s AND constructora_id = %s
            RETURNING id, estado
        """, (estado, lead_id, constructora_id))
        row = db.cursor.fetchone()
        if not row:
            db.conn.rollback()
            raise ConstructoraError("Lead no encontrado o no pertenece a tu constructora.")
        db.conn.commit()
    return {"ok": True, "lead_id": row["id"], "estado": row["estado"]}


def resumen_leads(constructora_id: int) -> Dict[str, Any]:
    """Contadores para el dashboard (nuevos / aceptados / rechazados / total)."""
    with get_db() as db:
        row = fetch_one(db.cursor, """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE estado='nuevo') AS nuevos,
                   COUNT(*) FILTER (WHERE estado='aceptado') AS aceptados,
                   COUNT(*) FILTER (WHERE estado='rechazado') AS rechazados
            FROM leads WHERE constructora_id = %s
        """, (constructora_id,))
    return dict(row) if row else {"total": 0, "nuevos": 0, "aceptados": 0, "rechazados": 0}


def listar_inventario(constructora_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    """Lista el inventario de la constructora (lo más nuevo primero)."""
    with get_db() as db:
        rows = fetch_all(db.cursor, """
            SELECT id, codigo_propiedad, titulo, precio, tipo_propiedad, tipo_negocio,
                   ciudad, zona, habitaciones, banos, area_construida, total_imagenes,
                   activa, fecha_creacion
            FROM propiedades
            WHERE constructora_id = %s
            ORDER BY fecha_creacion DESC LIMIT %s
        """, (constructora_id, limit))
    return [{**r, "precio_legible": format_cop(r.get("precio"))} for r in rows]
