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
    data["marca_propia"] = bool(payload.get("m")) and bool(data["agente"])
    sh.registrar_vista("comparativa", payload.get("ids", []))
    _vista(a, "comparativa", "cmp:" + ",".join(str(i) for i in payload.get("ids", [])), "la comparativa")
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
    data["marca_propia"] = bool(payload.get("m")) and bool(data["agente"])
    sh.registrar_vista("brochure", ids)
    _vista(a, "ficha", f"fic:{ids[0]}", (data.get("propiedad") or data).get("titulo") if isinstance(data, dict) else None)
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
    data["marca_propia"] = bool(payload.get("m")) and bool(data["agente"])
    _vista(a, "zona", f"zona:{payload.get('ciudad')}:{payload.get('zona')}:{payload.get('tipo')}",
           f"el reporte de {payload.get('zona') or payload.get('ciudad') or 'la zona'}")
    return jsonify({"success": True, "data": data})


@share_bp.route("/informe/<path:token>", methods=["GET"])
def informe(token):
    """Informe de captación (marca_service) para el propietario."""
    from src.services import marca_service
    try:
        payload = sh.verify_token(token)
    except sh.ShareError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    if payload.get("k") != "inf" or not payload.get("ids"):
        return jsonify({"success": False, "error": "Link inválido"}), 400
    data = marca_service.datos_informe_publico(payload["ids"][0])
    if not data:
        return jsonify({"success": False, "error": "Este informe ya no existe"}), 404
    a = payload.get("a")
    data["agente"] = agente_publico(a) if a else None
    data["marca_propia"] = bool(payload.get("m")) and bool(data["agente"])
    _vista(a, "informe", f"inf:{payload['ids'][0]}", "el informe de captación")
    return jsonify({"success": True, "data": data})


def _vista(agente_id, tipo: str, clave: str, titulo=None) -> None:
    """Quién vio tu link: la apertura queda a nombre del agente que compartió."""
    from src.services import marca_service
    marca_service.registrar_vista(agente_id, tipo, clave, titulo)
