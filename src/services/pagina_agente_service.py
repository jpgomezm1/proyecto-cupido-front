"""
La página pública del agente (getfynder.com/a/<slug>) y su marca en las piezas.

El agente elige su dirección, escribe una presentación corta, marca sus zonas y
sube su logo (y su foto). La página muestra sus inmuebles activos, que son los
que captó con su celular verificado, y un botón para escribirle por WhatsApp.
Solo se publica con el celular verificado: el número que sale es ese.

El logo también aparece en las piezas que el agente le envía a su cliente
(ficha, comparativa, reporte de zona), vía `agente_service.agente_publico`.
"""

import re
from typing import Any, Dict, List, Optional

from src.services.db import fetch_all, fetch_one, get_db

_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$")
_RESERVADOS = {"admin", "fynder", "chat", "api", "soporte", "ayuda", "login", "registro", "terminos",
               "agente", "agentes", "a", "www", "mapa", "zona", "ficha", "comparar", "compartir"}
_URL_IMG = re.compile(r"^https://[^\s]+$")


class PaginaError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def _sugerir_slug(nombre: Optional[str]) -> str:
    import unicodedata
    base = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:40]
    return base or "mi-pagina"


def _tel10(u: Dict[str, Any]) -> Optional[str]:
    if not u.get("telefono_verificado") or not u.get("telefono"):
        return None
    return re.sub(r"\D", "", u["telefono"])[-10:]


def mi_pagina(user_id: int) -> Dict[str, Any]:
    with get_db() as db:
        u = fetch_one(db.cursor, """
            SELECT id, nombre, telefono, telefono_verificado, pagina_slug, pagina_activa, pagina_bio,
                   pagina_zonas, logo_url, foto_url, marca_nombre
            FROM chat_users WHERE id = %s
        """, (user_id,))
    if not u:
        raise PaginaError("no_encontrado", "Usuario no encontrado.")
    return {
        "slug": u["pagina_slug"], "sugerido": _sugerir_slug(u["nombre"]), "activa": bool(u["pagina_activa"]),
        "bio": u["pagina_bio"], "zonas": list(u["pagina_zonas"] or []), "logo_url": u["logo_url"],
        "foto_url": u["foto_url"], "marca_nombre": u["marca_nombre"],
        "puede_publicar": bool(u["telefono_verificado"]),
        "ruta": f"/a/{u['pagina_slug']}" if u["pagina_slug"] else None,
    }


def guardar(user_id: int, datos: Dict[str, Any]) -> Dict[str, Any]:
    sets, vals = [], []
    if "slug" in datos:
        slug = (datos.get("slug") or "").strip().lower()
        if not _SLUG.match(slug) or slug in _RESERVADOS:
            raise PaginaError("slug_invalido", "La dirección debe tener de 3 a 40 letras, números o guiones.")
        with get_db() as db:
            otro = fetch_one(db.cursor, "SELECT id FROM chat_users WHERE LOWER(pagina_slug) = %s AND id <> %s",
                             (slug, user_id))
        if otro:
            raise PaginaError("slug_ocupado", "Esa dirección ya la tiene otro agente. Prueba otra.")
        sets.append("pagina_slug = %s"); vals.append(slug)
    if "bio" in datos:
        sets.append("pagina_bio = %s"); vals.append(((datos.get("bio") or "").strip()[:600]) or None)
    if "marca_nombre" in datos:
        sets.append("marca_nombre = %s"); vals.append(((datos.get("marca_nombre") or "").strip()[:80]) or None)
    if "zonas" in datos:
        zonas = [z.strip()[:40] for z in (datos.get("zonas") or []) if isinstance(z, str) and z.strip()][:8]
        sets.append("pagina_zonas = %s"); vals.append(zonas)
    for campo in ("logo_url", "foto_url"):
        if campo in datos:
            url = (datos.get(campo) or "").strip() or None
            if url and not _URL_IMG.match(url):
                raise PaginaError("imagen_invalida", "La imagen debe ser un enlace https.")
            sets.append(f"{campo} = %s"); vals.append(url)
    if "activa" in datos:
        activa = bool(datos.get("activa"))
        if activa:
            actual = mi_pagina(user_id)
            if not actual["puede_publicar"]:
                raise PaginaError("sin_celular", "Verifica tu celular para publicar tu página.")
            if not (datos.get("slug") or actual["slug"]):
                raise PaginaError("sin_slug", "Elige la dirección de tu página antes de publicarla.")
        sets.append("pagina_activa = %s"); vals.append(activa)
    if sets:
        with get_db() as db:
            db.cursor.execute(f"UPDATE chat_users SET {', '.join(sets)} WHERE id = %s", vals + [user_id])
            db.conn.commit()
    return mi_pagina(user_id)


def publica(slug: str) -> Dict[str, Any]:
    """Lo que ve cualquiera en /a/<slug>. Sin teléfonos de terceros: solo el del agente."""
    from src.services.clientes_service import propiedades_mini
    from src.services.mis_propiedades_service import _ES_DUENO
    with get_db() as db:
        u = fetch_one(db.cursor, """
            SELECT id, nombre, telefono, telefono_verificado, pagina_bio, pagina_zonas, logo_url, foto_url, marca_nombre
            FROM chat_users WHERE LOWER(pagina_slug) = %s AND pagina_activa AND activo
        """, ((slug or "").lower(),))
        if not u or not _tel10(u):
            raise PaginaError("no_encontrado", "Esta página no existe o no está publicada.")
        ids = [f["id"] for f in fetch_all(db.cursor, f"""
            SELECT id FROM propiedades WHERE activa AND {_ES_DUENO}
            ORDER BY fecha_actualizacion DESC NULLS LAST LIMIT 60
        """, (_tel10(u),))]
    minis = propiedades_mini(ids)
    inmuebles: List[Dict[str, Any]] = [minis[i] for i in ids if i in minis]
    tel = u["telefono"]
    return {
        "agente": {"id": u["id"], "nombre": u["nombre"], "bio": u["pagina_bio"], "marca_nombre": u["marca_nombre"],
                   "logo_url": u["logo_url"], "foto_url": u["foto_url"], "zonas": list(u["pagina_zonas"] or []),
                   "whatsapp": tel.replace("+", "") if tel else None, "telefono": tel},
        "inmuebles": inmuebles,
        "total": len(inmuebles),
    }
