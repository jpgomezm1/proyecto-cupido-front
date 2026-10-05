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
- GET   /api/listings/<id>          -> el inmueble completo para editarlo (solo su dueño).
- PATCH /api/listings/<id>          -> edita título, descripción, precio, cifras, ubicación y amenidades.
- POST/PUT/DELETE /api/listings/<id>/fotos[/orden] -> agrega, ordena y quita fotos.

Dueño = teléfono VERIFICADO del usuario de chat igual al del captador. Lo que el
agente edita sobrevive a una recaptura desde Wasi/Lobbie (campos_editados).
"""

from flask import Blueprint, request, jsonify

from src.api.chat_auth import require_chat_auth
from src.services import storage_service as store
from src.services import listing_ai
from src.services import listing_service as lst
from src.services import mis_propiedades_service as mp
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
    # El inmueble queda a nombre del celular VERIFICADO: uno auto-declarado
    # permitiría publicar a nombre de otro agente (y el dueño no podría editarlo).
    if not _tel10_verificado(user):
        return jsonify({"success": False, "code": "telefono_no_verificado",
                        "error": "Verifica tu celular para publicar: el inmueble queda a tu nombre."}), 403
    telefono = user.get("telefono")
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
    10 dígitos) con el teléfono VERIFICADO del usuario de chat (un teléfono
    auto-declarado no da control). Queda marcado como editado por el agente. `precio_m2` lo recalcula el
    trigger `calcular_precio_m2` de la BD. Queda auditado en eventos_log con el
    precio anterior y el nuevo.
    """
    user = request.chat_user
    body = request.get_json(silent=True) or {}
    raw = body.get("precio")
    if isinstance(raw, bool) or raw is None or (isinstance(raw, str) and not raw.strip()):
        return jsonify({"success": False, "error": "Envía el nuevo 'precio' en COP"}), 400
    try:
        antes = mp.obtener(property_id, _tel10_verificado(user))
        res = mp.editar(property_id, _tel10_verificado(user), {"precio": raw}, user)
    except mp.EdicionError as e:
        return jsonify({"success": False, "error": e.mensaje, "campo": e.campo}), e.status
    except Exception as e:
        print(f"[listings] update precio error ({property_id}): {e}")
        return jsonify({"success": False, "error": "No se pudo actualizar el precio"}), 500
    return jsonify({"success": True, "data": {
        "id": res["id"],
        "slug": res["codigo"],
        "titulo": res["titulo"],
        "precio_anterior": antes["precio"],
        "precio": res["precio"],
        "precio_legible": format_cop(res["precio"]),
    }})


def _tel10_verificado(user) -> str:
    """Últimos 10 dígitos del teléfono VERIFICADO; '' si no está verificado."""
    if not user or not user.get("telefono_verificado"):
        return ""
    tel = normalize_phone(user.get("telefono"))
    return tel if tel and len(tel) == 10 else ""


def _respuesta_mp(fn, *args):
    user = request.chat_user
    try:
        return jsonify({"success": True, "data": fn(*args[:1], _tel10_verificado(user), *args[1:])})
    except mp.EdicionError as e:
        return jsonify({"success": False, "error": e.mensaje, "campo": e.campo}), e.status
    except Exception as e:
        print(f"[listings] {fn.__name__} error ({args[0] if args else '-'}): {e}")
        return jsonify({"success": False, "error": "No se pudo guardar. Intenta de nuevo."}), 500


@listings_bp.route("/<int:property_id>", methods=["GET"])
@require_chat_auth
def obtener_listing(property_id: int):
    """El inmueble completo para el editor de Mis propiedades (solo su dueño)."""
    return _respuesta_mp(mp.obtener, property_id)


@listings_bp.route("/<int:property_id>", methods=["PATCH"])
@require_chat_auth
def editar_listing(property_id: int):
    """
    Edita campos del inmueble. Body con cualquiera de: titulo, descripcion, precio,
    tipo_propiedad, tipo_negocio, ciudad, zona, direccion, area_construida,
    habitaciones, banos, parqueaderos, estrato, administracion,
    amenidades_internas[], amenidades_externas[].
    """
    user = request.chat_user
    try:
        res = mp.editar(property_id, _tel10_verificado(user), request.get_json(silent=True) or {}, user)
        return jsonify({"success": True, "data": res})
    except mp.EdicionError as e:
        return jsonify({"success": False, "error": e.mensaje, "campo": e.campo}), e.status
    except Exception as e:
        print(f"[listings] editar error ({property_id}): {e}")
        return jsonify({"success": False, "error": "No se pudo guardar. Intenta de nuevo."}), 500


@listings_bp.route("/<int:property_id>/fotos", methods=["POST"])
@require_chat_auth
def agregar_fotos_listing(property_id: int):
    """Body: { urls: [...] } ya subidas con /upload-image."""
    return _respuesta_mp(mp.agregar_fotos, property_id, (request.get_json(silent=True) or {}).get("urls") or [])


@listings_bp.route("/<int:property_id>/fotos/orden", methods=["PUT"])
@require_chat_auth
def ordenar_fotos_listing(property_id: int):
    """Body: { orden: [todas las urls en el nuevo orden] } (la primera es la portada)."""
    return _respuesta_mp(mp.ordenar_fotos, property_id, (request.get_json(silent=True) or {}).get("orden") or [])


@listings_bp.route("/<int:property_id>/fotos", methods=["DELETE"])
@require_chat_auth
def quitar_foto_listing(property_id: int):
    """Body: { url }."""
    return _respuesta_mp(mp.quitar_foto, property_id, (request.get_json(silent=True) or {}).get("url") or "")
