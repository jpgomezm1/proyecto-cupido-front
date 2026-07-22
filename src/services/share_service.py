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

from src.services.db import get_db, fetch_one
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


def make_token(kind: str, ids: List[int]) -> str:
    payload = {"k": kind, "ids": [int(i) for i in ids], "exp": int(time.time()) + _TTL}
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64e(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


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


def _public_base() -> str:
    return os.getenv("MCP_PUBLIC_URL", "http://localhost:8767").rstrip("/")


def link_comparativa(ids: List[int]) -> str:
    return f"{_public_base()}/comparar?t={make_token('cmp', ids)}"


def link_brochure(property_id: int) -> str:
    return f"{_public_base()}/ficha?t={make_token('fic', [property_id])}"


# --------------------------------------------------------------------------
# Datos limpios para renderizar (SIN info de agente).
# --------------------------------------------------------------------------

def _prop_limpia(cur, pid: int) -> Optional[Dict[str, Any]]:
    """Proyección visual de una propiedad para el cliente final."""
    p = get_property(cur, pid)
    if not p:
        return None
    return {
        "id": p["id"],
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
