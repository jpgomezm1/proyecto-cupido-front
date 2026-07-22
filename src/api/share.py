"""
API pública para las piezas compartibles con el CLIENTE final (comparativa y
brochure). El portal de Fynder (React) las renderiza consumiendo estos
endpoints. Sin auth (el token firmado es la credencial); NUNCA exponen datos de
contacto de agentes.
"""

from flask import Blueprint, jsonify

from src.services import share_service as sh

share_bp = Blueprint("share_public", __name__, url_prefix="/api/share")


@share_bp.route("/comparativa/<path:token>", methods=["GET"])
def comparativa(token):
    try:
        payload = sh.verify_token(token)
    except sh.ShareError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    if payload.get("k") != "cmp":
        return jsonify({"success": False, "error": "Link inválido"}), 400
    data = sh.datos_comparativa(payload.get("ids", []))
    if data.get("error"):
        return jsonify({"success": False, "error": data["error"]}), 404
    sh.registrar_vista("comparativa", payload.get("ids", []))
    return jsonify({"success": True, "data": data})


@share_bp.route("/ficha/<path:token>", methods=["GET"])
def ficha(token):
    try:
        payload = sh.verify_token(token)
    except sh.ShareError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    if payload.get("k") != "fic":
        return jsonify({"success": False, "error": "Link inválido"}), 400
    ids = payload.get("ids", [])
    data = sh.datos_brochure(ids[0]) if ids else {"error": "vacío"}
    if data.get("error"):
        return jsonify({"success": False, "error": data["error"]}), 404
    sh.registrar_vista("brochure", ids)
    return jsonify({"success": True, "data": data})
