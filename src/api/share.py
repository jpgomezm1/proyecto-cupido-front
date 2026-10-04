"""
API pública para las piezas compartibles con el CLIENTE final (comparativa y
brochure). El portal de Fynder (React) las renderiza consumiendo estos
endpoints. Sin auth (el token firmado es la credencial); NUNCA exponen datos de
contacto del captador. Si el token trae `a` (agente que comparte), se agrega
`data["agente"]` con su contacto público SOLO si su teléfono está verificado.
"""

from flask import Blueprint, jsonify

from src.services import share_service as sh
from src.services import documento_service as doc
from src.services.agente_service import agente_publico

share_bp = Blueprint("share_public", __name__, url_prefix="/api/share")


@share_bp.route("/documento/<share_id>", methods=["GET"])
def documento(share_id):
    data = doc.get_documento(share_id)
    if data.get("error"):
        return jsonify({"success": False, "error": data["error"]}), 404
    return jsonify({"success": True, "data": data})


@share_bp.route("/comparativa/<path:token>", methods=["GET"])
def comparativa(token):
    try:
        payload = sh.verify_token(token)
    except sh.ShareError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    if payload.get("k") != "cmp":
        return jsonify({"success": False, "error": "Link inválido"}), 400
    a = payload.get("a")
    data = sh.datos_comparativa(payload.get("ids", []), a)
    if data.get("error"):
        return jsonify({"success": False, "error": data["error"]}), 404
    data["agente"] = agente_publico(a) if a else None
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
    a = payload.get("a")
    data = sh.datos_brochure(ids[0], a) if ids else {"error": "vacío"}
    if data.get("error"):
        return jsonify({"success": False, "error": data["error"]}), 404
    data["agente"] = agente_publico(a) if a else None
    sh.registrar_vista("brochure", ids)
    return jsonify({"success": True, "data": data})


@share_bp.route("/zona/<path:token>", methods=["GET"])
def zona(token):
    try:
        payload = sh.verify_token(token)
    except sh.ShareError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    if payload.get("k") != "zona":
        return jsonify({"success": False, "error": "Link inválido"}), 400
    data = sh.datos_reporte_zona(payload.get("ciudad"), payload.get("zona"), payload.get("tipo"))
    if data.get("error"):
        return jsonify({"success": False, "error": data["error"]}), 404
    a = payload.get("a")
    data["agente"] = agente_publico(a) if a else None
    return jsonify({"success": True, "data": data})
