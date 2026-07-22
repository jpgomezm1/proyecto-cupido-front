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
"""

from flask import Blueprint, request, jsonify

from src.api.chat_auth import require_chat_auth
from src.services import storage_service as store
from src.services import listing_ai
from src.services import listing_service as lst

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
