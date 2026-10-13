"""
API de clientes del agente y alertas de cruce (agente autenticado).

    GET    /api/chat/clientes?estado=activo
    POST   /api/chat/clientes                                 {nombre, telefono?, proposito?, plazo?, notas?, descripcion?, perfil?}
    GET    /api/chat/clientes/<id>                            → cliente + búsquedas + selección + alertas
    PATCH  /api/chat/clientes/<id>                            (descripcion = texto que Findy suma al perfil)
    DELETE /api/chat/clientes/<id>                            → lo pasa a 'cerrado'
    POST   /api/chat/clientes/<id>/buscar                     {limite?}
    POST   /api/chat/clientes/<id>/inmuebles                  {propiedad_id, estado?, nota?}
    PATCH  /api/chat/clientes/<id>/inmuebles/<propiedad_id>   {estado?, nota?}
    DELETE /api/chat/clientes/<id>/inmuebles/<propiedad_id>
    POST   /api/chat/clientes/<id>/perfil-desde-busqueda      {conversation_id}

    GET    /api/chat/alertas?no_leidas=1&limite=30
    GET    /api/chat/alertas/resumen
    POST   /api/chat/alertas/leer                             {ids? | todas?}
    GET|PUT /api/chat/alertas/preferencias                    {correo}

La lógica vive en `clientes_service.py` y `alertas_service.py`. El teléfono del
cliente es del agente: estas respuestas no pasan por `sin_contacto`, y las
propiedades que traen ya vienen sin contactos ni link de origen.
"""

import traceback

from flask import Blueprint, jsonify, request

from src.api.chat_auth import require_chat_auth
from src.services import alertas_service, clientes_service as svc

clientes_bp = Blueprint('clientes', __name__, url_prefix='/api/chat')


def _ok(data):
    return jsonify({"success": True, "data": data})


def _manejar(fn, contexto: str):
    try:
        return fn()
    except svc.ClienteError as e:
        estado = 404 if e.codigo == "no_encontrado" else 400
        return jsonify({"success": False, "error": e.mensaje, "code": e.codigo}), estado
    except Exception as e:
        print(f"❌ Error en clientes/{contexto}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


def _uid() -> int:
    return request.chat_user['id']


def _json() -> dict:
    return request.get_json(silent=True) or {}


@clientes_bp.route('/clientes', methods=['GET'])
@require_chat_auth
def listar():
    return _manejar(lambda: _ok(svc.listar(_uid(), request.args.get('estado'))), 'listar')


@clientes_bp.route('/clientes', methods=['POST'])
@require_chat_auth
def crear():
    return _manejar(lambda: _ok(svc.crear(_uid(), _json())), 'crear')


@clientes_bp.route('/clientes/<int:cliente_id>', methods=['GET'])
@require_chat_auth
def obtener(cliente_id):
    return _manejar(lambda: _ok(svc.obtener(_uid(), cliente_id)), 'obtener')


@clientes_bp.route('/clientes/<int:cliente_id>', methods=['PATCH'])
@require_chat_auth
def actualizar(cliente_id):
    return _manejar(lambda: _ok(svc.actualizar(_uid(), cliente_id, _json())), 'actualizar')


@clientes_bp.route('/clientes/<int:cliente_id>', methods=['DELETE'])
@require_chat_auth
def archivar(cliente_id):
    return _manejar(lambda: _ok(svc.archivar(_uid(), cliente_id)), 'archivar')


@clientes_bp.route('/clientes/<int:cliente_id>/compartir', methods=['POST'])
@require_chat_auth
def compartir(cliente_id):
    """{activo: bool}: publica (o retira) el pedido del cliente en la red de Fynder."""
    from src.services import red_service
    try:
        activo = _json().get('activo', True) is not False
        return _ok(red_service.compartir_pedido(_uid(), cliente_id, activo=activo, canal="web"))
    except red_service.RedError as e:
        estado = 404 if e.codigo == "no_encontrado" else 400
        return jsonify({"success": False, "error": e.mensaje, "code": e.codigo}), estado
    except Exception as e:
        print(f"❌ Error en clientes/compartir: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


def _encargo(fn, contexto: str):
    from src.services import encargos_service as enc
    try:
        return _ok(fn(enc))
    except enc.EncargoError as e:
        estado = 404 if e.codigo == "no_encontrado" else 400
        return jsonify({"success": False, "error": e.mensaje, "code": e.codigo}), estado
    except Exception as e:
        print(f"❌ Error en encargos/{contexto}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error en el servidor"}), 500


@clientes_bp.route('/encargos', methods=['GET'])
@require_chat_auth
def encargos_listar():
    """Encargos de Findy, su cupo y las presentaciones de Findy Conecta (recibidas y enviadas)."""
    return _encargo(lambda enc: enc.listar(_uid()), 'listar')


@clientes_bp.route('/encargos/resumen', methods=['GET'])
@require_chat_auth
def encargos_resumen():
    """Para el Inicio: opciones nuevas de sus encargos y presentaciones por responder."""
    return _encargo(lambda enc: enc.resumen_inicio(_uid()), 'resumen')


@clientes_bp.route('/encargos', methods=['POST'])
@require_chat_auth
def encargos_crear():
    """{tipo: buscar_inmueble|buscar_comprador, cliente_id?, propiedad_id?}"""
    d = _json()
    return _encargo(lambda enc: enc.crear(_uid(), d.get('tipo'), d.get('cliente_id'), d.get('propiedad_id'), canal="web"),
                    'crear')


@clientes_bp.route('/encargos/<int:encargo_id>', methods=['GET'])
@require_chat_auth
def encargos_detalle(encargo_id):
    def f(enc):
        r = enc.detalle(_uid(), encargo_id)
        enc.marcar_vistos(_uid(), encargo_id)
        return r
    return _encargo(f, 'detalle')


@clientes_bp.route('/encargos/<int:encargo_id>', methods=['DELETE'])
@require_chat_auth
def encargos_cerrar(encargo_id):
    return _encargo(lambda enc: enc.cerrar(_uid(), encargo_id), 'cerrar')


@clientes_bp.route('/encargos/opciones/<int:match_id>/descartar', methods=['POST'])
@require_chat_auth
def encargos_descartar(match_id):
    return _encargo(lambda enc: (enc.descartar_match(_uid(), match_id), {"ok": True})[1], 'descartar')


@clientes_bp.route('/encargos/opciones/<int:match_id>/presentacion', methods=['POST'])
@require_chat_auth
def encargos_presentacion(match_id):
    return _encargo(lambda enc: enc.pedir_presentacion(_uid(), match_id, _json().get('mensaje')), 'presentacion')


@clientes_bp.route('/presentaciones/<int:presentacion_id>/responder', methods=['POST'])
@require_chat_auth
def presentaciones_responder(presentacion_id):
    """{aceptar: bool}"""
    return _encargo(lambda enc: enc.responder(_uid(), presentacion_id, _json().get('aceptar') is True), 'responder')


@clientes_bp.route('/clientes/<int:cliente_id>/buscar', methods=['POST'])
@require_chat_auth
def buscar(cliente_id):
    return _manejar(lambda: _ok(svc.buscar(_uid(), cliente_id, _json().get('limite') or 12)), 'buscar')


@clientes_bp.route('/clientes/<int:cliente_id>/inmuebles', methods=['POST'])
@require_chat_auth
def guardar_inmueble(cliente_id):
    d = _json()
    if not d.get('propiedad_id'):
        return jsonify({"success": False, "error": "Falta propiedad_id"}), 400
    return _manejar(lambda: _ok(svc.guardar_inmueble(_uid(), cliente_id, int(d['propiedad_id']),
                                                     d.get('estado'), d.get('nota'))), 'guardar_inmueble')


@clientes_bp.route('/clientes/<int:cliente_id>/inmuebles/<int:propiedad_id>', methods=['PATCH'])
@require_chat_auth
def actualizar_inmueble(cliente_id, propiedad_id):
    return _manejar(lambda: _ok(svc.actualizar_inmueble(_uid(), cliente_id, propiedad_id, _json())),
                    'actualizar_inmueble')


@clientes_bp.route('/clientes/<int:cliente_id>/inmuebles/<int:propiedad_id>', methods=['DELETE'])
@require_chat_auth
def quitar_inmueble(cliente_id, propiedad_id):
    return _manejar(lambda: _ok(svc.quitar_inmueble(_uid(), cliente_id, propiedad_id)), 'quitar_inmueble')


@clientes_bp.route('/clientes/<int:cliente_id>/perfil-desde-busqueda', methods=['POST'])
@require_chat_auth
def perfil_desde_busqueda(cliente_id):
    conv = _json().get('conversation_id')
    if not conv:
        return jsonify({"success": False, "error": "Falta conversation_id"}), 400
    return _manejar(lambda: _ok(svc.perfil_desde_busqueda(_uid(), cliente_id, int(conv))), 'perfil_desde_busqueda')


# ── alertas ────────────────────────────────────────────────────────────────

@clientes_bp.route('/alertas', methods=['GET'])
@require_chat_auth
def alertas():
    no_leidas = request.args.get('no_leidas') in ('1', 'true')
    limite = request.args.get('limite', 30, type=int)
    return _manejar(lambda: _ok(alertas_service.listar(_uid(), no_leidas=no_leidas, limite=limite)), 'alertas')


@clientes_bp.route('/alertas/resumen', methods=['GET'])
@require_chat_auth
def alertas_resumen():
    return _manejar(lambda: _ok(alertas_service.resumen(_uid())), 'alertas_resumen')


@clientes_bp.route('/alertas/leer', methods=['POST'])
@require_chat_auth
def alertas_leer():
    d = _json()
    return _manejar(lambda: _ok(alertas_service.marcar_leidas(_uid(), d.get('ids'), bool(d.get('todas')))),
                    'alertas_leer')


@clientes_bp.route('/alertas/preferencias', methods=['GET', 'PUT'])
@require_chat_auth
def alertas_preferencias():
    correo = _json().get('correo') if request.method == 'PUT' else None
    return _manejar(lambda: _ok(alertas_service.preferencias(_uid(), correo)), 'alertas_preferencias')
