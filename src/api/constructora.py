"""
API del portal B2B de constructoras (Bloque E3).

Auth propio por token bearer. `require_constructora` resuelve la sesión y deja
el contexto en `g.constructora` (con `constructora_id`), de modo que cada
endpoint queda scoped a SU constructora. Endpoints de inventario y leads se
agregan sobre esta base (E3.2 / E3.3).
"""

from functools import wraps

from flask import Blueprint, request, jsonify, g

from src.services import constructora_service as cs

constructora_bp = Blueprint('constructora', __name__, url_prefix='/api/constructora')


def require_constructora(f):
    """Exige un token de constructora válido; deja el contexto en g.constructora."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get('Authorization', '') or ''
        token = auth[7:].strip() if auth.startswith('Bearer ') else None
        if not token:
            return jsonify({'success': False, 'error': 'no_autenticado'}), 401
        ctx = cs.resolve(token)
        if not ctx:
            return jsonify({'success': False, 'error': 'sesion_invalida'}), 401
        g.constructora = ctx
        g.constructora_token = token
        return f(*args, **kwargs)
    return wrapper


@constructora_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''
    if not email or not password:
        return jsonify({'success': False, 'error': 'email y password requeridos'}), 400
    res = cs.login(email, password)
    if not res:
        return jsonify({'success': False, 'error': 'Credenciales inválidas'}), 401
    return jsonify({'success': True, 'data': res})


@constructora_bp.route('/logout', methods=['POST'])
@require_constructora
def logout():
    cs.logout(g.constructora_token)
    return jsonify({'success': True})


@constructora_bp.route('/me', methods=['GET'])
@require_constructora
def me():
    ctx = dict(g.constructora)
    ctx.pop('session_id', None)
    return jsonify({'success': True, 'data': ctx})


# =========================================================================
# INVENTARIO (E3.2) — carga por formulario / CSV / link, y listado.
# =========================================================================

@constructora_bp.route('/inventario', methods=['GET'])
@require_constructora
def inventario_list():
    items = cs.listar_inventario(g.constructora['constructora_id'])
    return jsonify({'success': True, 'data': {'total': len(items), 'inmuebles': items}})


@constructora_bp.route('/inventario', methods=['POST'])
@require_constructora
def inventario_create():
    """Alta manual (un inmueble) vía formulario."""
    data = request.get_json(silent=True) or {}
    try:
        res = cs.crear_inmueble(g.constructora, data)
        return jsonify({'success': True, 'data': res}), 201
    except cs.ConstructoraError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@constructora_bp.route('/inventario/scrape', methods=['POST'])
@require_constructora
def inventario_scrape():
    """Alta desde un link de portal (Wasi/Lobbie/Tu360)."""
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    try:
        res = cs.crear_desde_link(g.constructora, url)
        return jsonify({'success': True, 'data': res}), 201
    except cs.ConstructoraError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@constructora_bp.route('/inventario/bulk', methods=['POST'])
@require_constructora
def inventario_bulk():
    """Carga masiva: archivo CSV (multipart 'file') o JSON {items:[...]}."""
    import csv
    import io
    items = []
    f = request.files.get('file')
    if f:
        content = f.read().decode('utf-8-sig', errors='replace')
        items = [dict(row) for row in csv.DictReader(io.StringIO(content))]
    else:
        data = request.get_json(silent=True) or {}
        items = data.get('items') or []
    if not items:
        return jsonify({'success': False,
                        'error': 'No se recibieron inmuebles (archivo CSV o items).'}), 400
    res = cs.crear_inmuebles_bulk(g.constructora, items)
    return jsonify({'success': True, 'data': res})


# =========================================================================
# LEADS (E3.3) — la constructora ve sus matches (pedido↔inmueble) y acepta/rechaza.
# =========================================================================

@constructora_bp.route('/leads', methods=['GET'])
@require_constructora
def leads_list():
    estado = request.args.get('estado')  # nuevo | aceptado | rechazado (opcional)
    cid = g.constructora['constructora_id']
    leads = cs.listar_leads(cid, estado=estado)
    return jsonify({'success': True, 'data': {
        'resumen': cs.resumen_leads(cid),
        'total': len(leads),
        'leads': leads,
    }})


@constructora_bp.route('/leads/<int:lead_id>/estado', methods=['PATCH'])
@require_constructora
def lead_set_estado(lead_id):
    data = request.get_json(silent=True) or {}
    estado = (data.get('estado') or '').strip()
    try:
        res = cs.actualizar_estado_lead(g.constructora['constructora_id'], lead_id, estado)
        return jsonify({'success': True, 'data': res})
    except cs.ConstructoraError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
