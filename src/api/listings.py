"""
API Blueprint para creación de listings nativos de Fynder (camino WEB).

El portal de Fynder (React) usa estos endpoints para que el agente publique una
propiedad con fotos y autocompletado por IA. Protegido con la auth de chat
(el agente logueado).

Endpoints:
- POST /api/listings/upload-image  -> sube una imagen a Supabase, devuelve URL.
- POST /api/listings/autocomplete  -> IA (tokens de Fynder): título, descripción,
                                       amenidades y precio sugerido.
- POST /api/listings               -> crea el listing.
- PATCH /api/listings/<id>/precio  -> el agente cambia el precio de un inmueble suyo.
"""

from flask import Blueprint, request, jsonify

from src.api.chat_auth import require_chat_auth
from src.services import storage_service as store
from src.services import listing_ai
from src.services import listing_service as lst
from src.services.db import get_db
from src.services.textutils import normalize_phone, format_cop

# Rango sano de precio en COP: evita errores de digitación (ej. "600" en vez de
# 600 millones). Cubre arriendos bajos y ventas de lujo.
_PRECIO_MIN = 100_000
_PRECIO_MAX = 100_000_000_000

listings_bp = Blueprint("listings", __name__, url_prefix="/api/listings")


@listings_bp.route("/upload-image", methods=["POST"])
@require_chat_auth
def upload_image():
    """Sube una imagen (data URL o archivo) a Supabase y devuelve la URL pública."""
    try:
        # Soporta multipart (archivo) o JSON con data URL.
        if request.files.get("file"):
            f = request.files["file"]
            data = f.read()
            ct = f.mimetype or "image/jpeg"
            url = store.upload_image_bytes(data, ct, prefix="listings/web")
        else:
            body = request.get_json(silent=True) or {}
            data_url = body.get("data_url") or body.get("image")
            if not data_url:
                return jsonify({"success": False, "error": "Envía 'data_url' o un archivo 'file'"}), 400
            url = store.upload_image_data_url(data_url, prefix="listings/web")
        return jsonify({"success": True, "data": {"url": url}})
    except store.StorageError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        print(f"[listings] upload-image error: {e}")
        return jsonify({"success": False, "error": "No se pudo subir la imagen"}), 500


@listings_bp.route("/autocomplete", methods=["POST"])
@require_chat_auth
def autocomplete():
    """Autocompletar con IA (tokens de Fynder): título, descripción, amenidades, precio."""
    body = request.get_json(silent=True) or {}
    datos = body.get("datos") or {}
    image_urls = body.get("imagenes_urls") or []
    try:
        result = listing_ai.autocompletar(datos, image_urls)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        print(f"[listings] autocomplete error: {e}")
        return jsonify({"success": False, "error": "No se pudo autocompletar"}), 500


@listings_bp.route("", methods=["POST"])
@listings_bp.route("/", methods=["POST"])
@require_chat_auth
def create_listing():
    """Crea el listing nativo de Fynder para el agente autenticado."""
    user = request.chat_user
    telefono = user.get("telefono")
    if not telefono:
        return jsonify({"success": False,
                        "error": "Tu usuario no tiene teléfono asociado; no se puede asignar la propiedad."}), 400
    body = request.get_json(silent=True) or {}
    try:
        res = lst.crear_listing(telefono, body,
                                agente_nombre=user.get("nombre"),
                                agente_user_id=user.get("id"))
        return jsonify({"success": True, "data": res})
    except lst.ListingError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        print(f"[listings] create error: {e}")
        return jsonify({"success": False, "error": "No se pudo crear el listing"}), 500


@listings_bp.route("/<int:property_id>/precio", methods=["PATCH"])
@require_chat_auth
def update_precio(property_id: int):
    """
    El agente autenticado cambia el precio de un inmueble que él captó.

    Body: { "precio": 650000000 }

    Solo aplica sobre propiedades cuyo `agente_captador_telefono` coincide (últimos
    10 dígitos) con el teléfono del usuario de chat. `precio_m2` lo recalcula el
    trigger `calcular_precio_m2` de la BD. Queda auditado en eventos_log con el
    precio anterior y el nuevo.
    """
    user = request.chat_user
    owner_10 = normalize_phone(user.get("telefono"))
    if not owner_10 or len(owner_10) != 10:
        return jsonify({"success": False,
                        "error": "Tu usuario no tiene teléfono asociado; no se puede validar la propiedad."}), 400

    body = request.get_json(silent=True) or {}
    raw = body.get("precio")
    if isinstance(raw, bool) or raw is None or (isinstance(raw, str) and not raw.strip()):
        return jsonify({"success": False, "error": "Envía el nuevo 'precio' en COP"}), 400
    try:
        nuevo = int(float(raw))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "El precio debe ser un número (en COP)"}), 400
    if nuevo < _PRECIO_MIN or nuevo > _PRECIO_MAX:
        return jsonify({"success": False,
                        "error": f"Precio fuera de rango ({format_cop(_PRECIO_MIN)} a {format_cop(_PRECIO_MAX)}). "
                                 "Revisa que esté escrito completo, en pesos."}), 400

    own_clause = "RIGHT(REGEXP_REPLACE(agente_captador_telefono, '[^0-9]', '', 'g'), 10) = %s"
    try:
        with get_db() as db:
            # Bloquea la fila para leer el precio anterior de forma consistente.
            db.cursor.execute(f"""
                SELECT id, precio FROM propiedades
                WHERE id = %s AND agente_captador_telefono IS NOT NULL AND {own_clause}
                FOR UPDATE
            """, (property_id, owner_10))
            actual = db.cursor.fetchone()
            if not actual:
                db.conn.rollback()
                return jsonify({"success": False,
                                "error": "La propiedad no existe o no está a tu nombre."}), 404

            anterior = actual["precio"]
            db.cursor.execute(f"""
                UPDATE propiedades SET precio = %s, fecha_actualizacion = NOW()
                WHERE id = %s AND {own_clause}
                RETURNING id, codigo_propiedad AS slug, titulo, precio, precio_m2
            """, (nuevo, property_id, owner_10))
            row = db.cursor.fetchone()
            if not row:
                db.conn.rollback()
                return jsonify({"success": False,
                                "error": "La propiedad no existe o no está a tu nombre."}), 404
            db.conn.commit()

            try:
                db.log_evento(
                    tipo_evento="agent_price_update",
                    agente_telefono=user.get("telefono"),
                    propiedad_id=property_id,
                    datos_evento={"origen": "chat_mis_propiedades", "chat_user_id": user.get("id"),
                                  "precio_anterior": anterior, "precio_nuevo": nuevo},
                )
            except Exception as e:
                print(f"[listings] no se pudo auditar cambio de precio {property_id}: {e}")

        return jsonify({"success": True, "data": {
            "id": row["id"],
            "slug": row["slug"],
            "titulo": row["titulo"],
            "precio_anterior": anterior,
            "precio": row["precio"],
            "precio_legible": format_cop(row["precio"]),
            "precio_m2": float(row["precio_m2"]) if row.get("precio_m2") is not None else None,
        }})
    except Exception as e:
        print(f"[listings] update precio error ({property_id}): {e}")
        return jsonify({"success": False, "error": "No se pudo actualizar el precio"}), 500
