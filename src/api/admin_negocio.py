"""
API del admin para el modelo actual (suscripción + llaves). Solo lectura.

    GET /api/admin/negocio/resumen?dias=30      → ingresos, planes, llaves, MCP, adopción
    GET /api/admin/negocio/pagos?estado=&limite= → pagos (Wompi y manuales)
    GET /api/admin/negocio/contactos?canal=&limite= → contactos abiertos (desbloqueos)
    GET /api/admin/negocio/mcp?dias=30          → uso del MCP por herramienta y por agente
    GET /api/admin/negocio/verificacion         → salud de la verificación de links
    GET /api/admin/negocio/visitas?abiertas=1   → cola de "solicitar visita"
    GET /api/admin/negocio/soporte              → solicitudes de soporte
    GET /api/admin/negocio/tablero?dias=30      → tablero de uso (base de Fynder)
    GET /api/admin/negocio/tablero/posthog      → tablero de uso (PostHog)

Protegido con el JWT del admin (`proteger_admin` en main.py): trae datos de
contacto de agentes, que es lo que Fynder cobra.
"""

import traceback
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from src.services.db import fetch_all, fetch_one, get_db

admin_negocio_bp = Blueprint('admin_negocio', __name__, url_prefix='/api/admin/negocio')


def _ok(data):
    return jsonify({"success": True, "data": data})


def _fallo(e: Exception, contexto: str):
    print(f"❌ Error en admin_negocio/{contexto}: {e}")
    traceback.print_exc()
    return jsonify({"success": False, "error": "Error en el servidor"}), 500


def _int(nombre: str, defecto: int, minimo: int = 1, maximo: int = 365) -> int:
    try:
        return max(minimo, min(maximo, int(request.args.get(nombre, defecto))))
    except (TypeError, ValueError):
        return defecto


def _iso(fila: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in fila.items()}


@admin_negocio_bp.route('/resumen', methods=['GET'])
def resumen():
    dias = _int('dias', 30)
    try:
        with get_db() as db:
            cur = db.cursor
            desde = "NOW() - (%s * INTERVAL '1 day')"
            pagos = fetch_one(cur, f"""
                SELECT COALESCE(SUM(monto_cop) FILTER (WHERE estado = 'aprobado'), 0) AS ingresos,
                       COUNT(*) FILTER (WHERE estado = 'aprobado') AS aprobados,
                       COUNT(*) FILTER (WHERE estado = 'pendiente') AS pendientes,
                       COUNT(*) FILTER (WHERE estado IN ('rechazado', 'error', 'anulado')) AS fallidos
                FROM pagos WHERE created_at > {desde}
            """, (dias,))
            planes = fetch_all(cur, """
                SELECT s.plan_codigo AS codigo, p.nombre, COUNT(*) AS activos, COALESCE(SUM(s.precio_cop), 0) AS mrr
                FROM suscripciones s LEFT JOIN planes p ON p.codigo = s.plan_codigo
                WHERE s.estado = 'activa' AND COALESCE(s.gracia_hasta, s.fin) > NOW()
                GROUP BY 1, 2 ORDER BY 3 DESC
            """)
            agentes = fetch_one(cur, """
                SELECT COUNT(*) AS registrados,
                       COUNT(*) FILTER (WHERE telefono_verificado) AS verificados,
                       COUNT(*) FILTER (WHERE terminos_aceptados_at IS NOT NULL) AS con_terminos,
                       COUNT(*) FILTER (WHERE ultimo_login > NOW() - INTERVAL '7 days') AS activos_7d
                FROM chat_users WHERE activo
            """)
            contactos = fetch_one(cur, f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE fuente_credito <> 'gratis') AS con_llave,
                       COUNT(*) FILTER (WHERE canal = 'web') AS web,
                       COUNT(*) FILTER (WHERE canal = 'mcp') AS mcp,
                       COUNT(DISTINCT user_id) AS agentes
                FROM desbloqueos WHERE created_at > {desde}
            """, (dias,))
            reportes = fetch_one(cur, f"""
                SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE reembolsado) AS reembolsados,
                       COUNT(*) FILTER (WHERE resuelto_at IS NULL) AS pendientes
                FROM reportes_contacto WHERE created_at > {desde}
            """, (dias,))
            mcp = fetch_one(cur, f"""
                SELECT COUNT(*) AS llamadas, COUNT(*) FILTER (WHERE NOT ok) AS errores,
                       COUNT(DISTINCT user_id) AS agentes
                FROM mcp_tool_calls WHERE created_at > {desde}
            """, (dias,))
            busquedas = fetch_one(cur, f"""
                SELECT COALESCE(SUM(busquedas), 0) AS total, COUNT(DISTINCT user_id) AS agentes
                FROM uso_diario WHERE fecha > (NOW() - (%s * INTERVAL '1 day'))::date
            """, (dias,))
            adopcion = fetch_one(cur, f"""
                SELECT (SELECT COUNT(*) FROM clientes_agente WHERE estado = 'activo') AS clientes_activos,
                       (SELECT COUNT(DISTINCT user_id) FROM clientes_agente) AS agentes_con_clientes,
                       (SELECT COUNT(*) FROM alertas WHERE created_at > {desde}) AS alertas,
                       (SELECT COUNT(*) FROM correos_enviados WHERE created_at > {desde}) AS correos,
                       (SELECT COUNT(*) FROM fotos_mejoradas WHERE url_mejorada IS NOT NULL AND created_at > {desde}) AS fotos_ia,
                       (SELECT COUNT(*) FROM fotos_mejoradas WHERE aplicada AND created_at > {desde}) AS fotos_ia_aplicadas,
                       (SELECT COUNT(*) FROM cambios_precio WHERE created_at > {desde}) AS cambios_precio,
                       (SELECT COUNT(*) FROM cambios_precio WHERE aplicado AND created_at > {desde}) AS cambios_precio_aplicados
            """, (dias,) * 6)
        return _ok({
            "dias": dias,
            "pagos": pagos, "planes": planes, "agentes": agentes, "contactos": contactos,
            "reportes": reportes, "mcp": mcp, "busquedas": busquedas, "adopcion": adopcion,
            "mrr": sum(int(p["mrr"] or 0) for p in planes),
        })
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'resumen')


@admin_negocio_bp.route('/pagos', methods=['GET'])
def pagos():
    limite = _int('limite', 100, maximo=500)
    estado = request.args.get('estado')
    try:
        with get_db() as db:
            filas = fetch_all(db.cursor, """
                SELECT pg.id, pg.referencia, pg.estado, pg.pasarela, pg.metodo, pg.monto_cop,
                       pg.plan_codigo, pl.nombre AS plan_nombre, pl.tipo AS plan_tipo,
                       pg.transaccion_id, pg.created_at, pg.updated_at,
                       u.id AS user_id, u.nombre AS agente, u.email
                FROM pagos pg
                LEFT JOIN chat_users u ON u.id = pg.user_id
                LEFT JOIN planes pl ON pl.codigo = pg.plan_codigo
                WHERE (%s::text IS NULL OR pg.estado = %s)
                ORDER BY pg.created_at DESC LIMIT %s
            """, (estado, estado, limite))
        return _ok([_iso(f) for f in filas])
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'pagos')


@admin_negocio_bp.route('/contactos', methods=['GET'])
def contactos():
    limite = _int('limite', 100, maximo=500)
    canal = request.args.get('canal')
    try:
        with get_db() as db:
            filas = fetch_all(db.cursor, """
                SELECT d.id, d.tipo, d.ref_id, d.canal, d.estado, d.fuente_credito, d.motivo_gratis,
                       d.disponibilidad_estado, d.contacto_nombre, d.contacto_agencia, d.created_at,
                       u.id AS user_id, u.nombre AS agente, u.email,
                       COALESCE(p.codigo_propiedad, 'pedido-' || d.ref_id::text) AS codigo,
                       COALESCE(p.titulo, LEFT(pe.texto_pedido, 120)) AS titulo,
                       r.id AS reporte_id, r.motivo AS reporte_motivo, r.reembolsado
                FROM desbloqueos d
                LEFT JOIN chat_users u ON u.id = d.user_id
                LEFT JOIN propiedades p ON d.tipo = 'propiedad' AND p.id = d.ref_id
                LEFT JOIN pedidos pe ON d.tipo = 'pedido' AND pe.id = d.ref_id
                LEFT JOIN reportes_contacto r ON r.desbloqueo_id = d.id
                WHERE (%s::text IS NULL OR d.canal = %s)
                ORDER BY d.created_at DESC LIMIT %s
            """, (canal, canal, limite))
        return _ok([_iso(f) for f in filas])
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'contactos')


@admin_negocio_bp.route('/mcp', methods=['GET'])
def mcp():
    dias = _int('dias', 30)
    try:
        with get_db() as db:
            cur = db.cursor
            por_tool = fetch_all(cur, """
                SELECT tool, COUNT(*) AS llamadas, COUNT(*) FILTER (WHERE NOT ok) AS errores,
                       ROUND(AVG(duracion_ms)) AS ms_promedio, COUNT(DISTINCT user_id) AS agentes
                FROM mcp_tool_calls WHERE created_at > NOW() - (%s * INTERVAL '1 day')
                GROUP BY tool ORDER BY llamadas DESC
            """, (dias,))
            por_agente = fetch_all(cur, """
                SELECT u.id AS user_id, u.nombre AS agente, u.email, COUNT(*) AS llamadas,
                       COUNT(*) FILTER (WHERE NOT m.ok) AS errores, MAX(m.created_at) AS ultimo_uso
                FROM mcp_tool_calls m LEFT JOIN chat_users u ON u.id = m.user_id
                WHERE m.created_at > NOW() - (%s * INTERVAL '1 day')
                GROUP BY 1, 2, 3 ORDER BY llamadas DESC LIMIT 50
            """, (dias,))
            errores = fetch_all(cur, """
                SELECT m.tool, LEFT(m.error, 300) AS error, m.created_at, u.nombre AS agente
                FROM mcp_tool_calls m LEFT JOIN chat_users u ON u.id = m.user_id
                WHERE NOT m.ok AND m.created_at > NOW() - (%s * INTERVAL '1 day')
                ORDER BY m.created_at DESC LIMIT 30
            """, (dias,))
            por_dia = fetch_all(cur, """
                SELECT created_at::date AS dia, COUNT(*) AS llamadas, COUNT(DISTINCT user_id) AS agentes
                FROM mcp_tool_calls WHERE created_at > NOW() - (%s * INTERVAL '1 day')
                GROUP BY 1 ORDER BY 1
            """, (dias,))
        return _ok({"dias": dias, "por_tool": por_tool, "por_agente": [_iso(f) for f in por_agente],
                    "errores": [_iso(f) for f in errores], "por_dia": [_iso(f) for f in por_dia]})
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'mcp')


@admin_negocio_bp.route('/verificacion', methods=['GET'])
def verificacion():
    try:
        from src.services.disponibilidad_service import salud
        return _ok(salud(_int('dias_sla', 8, maximo=60)))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'verificacion')


@admin_negocio_bp.route('/visitas', methods=['GET'])
def visitas():
    """Pedidos de "solicitar visita": el equipo de Fynder coordina por el agente."""
    abiertas = request.args.get('abiertas', '1') in ('1', 'true')
    try:
        with get_db() as db:
            filas = fetch_all(db.cursor, """
                SELECT i.id, i.estado, i.fuente, i.fecha_seleccion, i.fecha_cambio_estado,
                       i.fecha_puntas_enviadas, i.disponibilidad_estado, i.cliente_ref, i.preguntas,
                       i.notas_estado, i.agente_comprador_telefono, i.agente_vendedor_telefono,
                       u.nombre AS agente_comprador,
                       p.id AS propiedad_id, p.codigo_propiedad AS codigo, p.titulo, p.precio, p.zona, p.ciudad
                FROM interacciones i
                LEFT JOIN propiedades p ON p.id = i.propiedad_id
                LEFT JOIN chat_users u ON RIGHT(REGEXP_REPLACE(COALESCE(u.telefono,''), '[^0-9]', '', 'g'), 10)
                                       = RIGHT(REGEXP_REPLACE(COALESCE(i.agente_comprador_telefono,''), '[^0-9]', '', 'g'), 10)
                                      AND u.telefono IS NOT NULL
                WHERE (NOT %s OR COALESCE(i.activa, TRUE))
                ORDER BY i.fecha_seleccion DESC NULLS LAST LIMIT 200
            """, (abiertas,))
        return _ok([_iso(f) for f in filas])
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'visitas')


@admin_negocio_bp.route('/soporte', methods=['GET'])
def soporte():
    try:
        with get_db() as db:
            filas = fetch_all(db.cursor, """
                SELECT s.id, s.categoria, s.asunto, s.mensaje, s.estado, s.created_at,
                       u.id AS user_id, u.nombre AS agente, u.email
                FROM soporte_solicitudes s LEFT JOIN chat_users u ON u.id = s.user_id
                ORDER BY s.created_at DESC LIMIT 200
            """)
        return _ok([_iso(f) for f in filas])
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'soporte')


@admin_negocio_bp.route('/celulares', methods=['GET'])
def celulares():
    """Agentes que pidieron código en los últimos 14 días y siguen sin verificar: el
    respaldo cuando el WhatsApp de Fynder no envía. Se verifica solo si el agente
    escribió desde ESE número."""
    try:
        with get_db() as db:
            filas = fetch_all(db.cursor, """
                SELECT u.id AS user_id, u.nombre, u.email, u.telefono,
                       MAX(c.created_at) AS pidio_at, COUNT(*) AS codigos,
                       EXISTS (SELECT 1 FROM chat_users o WHERE o.id <> u.id AND o.activo
                                 AND o.telefono_verificado AND o.telefono = u.telefono) AS en_otra_cuenta
                FROM codigos_telefono c JOIN chat_users u ON u.id = c.user_id
                WHERE c.created_at > NOW() - INTERVAL '14 days'
                  AND u.activo AND NOT COALESCE(u.telefono_verificado, FALSE)
                GROUP BY u.id ORDER BY MAX(c.created_at) DESC LIMIT 200
            """)
        return _ok([_iso(f) for f in filas])
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'celulares')


@admin_negocio_bp.route('/tablero', methods=['GET'])
def tablero():
    """Actividad, agentes activos, embudo del negocio y retención (base de Fynder)."""
    try:
        from src.services.tablero_service import sistema
        return _ok(sistema(_int('dias', 30, minimo=7, maximo=180)))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'tablero')


@admin_negocio_bp.route('/tablero/posthog', methods=['GET'])
def tablero_posthog():
    """Embudo de la web, páginas y web vs MCP (PostHog; {configurado: false} sin llave)."""
    try:
        from src.services.tablero_service import posthog
        return _ok(posthog(_int('dias', 30, minimo=7, maximo=180)))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'tablero_posthog')


@admin_negocio_bp.route('/vitrina/candidatos', methods=['GET'])
def vitrina_candidatos():
    """Cola de la Vitrina: lo que Findy propone esta semana (pendiente de revisión)."""
    from src.services import vitrina_service
    try:
        return _ok(vitrina_service.candidatos(request.args.get('estado', 'pendiente')))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'vitrina_candidatos')


@admin_negocio_bp.route('/vitrina/candidatos/<int:candidato_id>', methods=['POST'])
def vitrina_revisar(candidato_id):
    """{aprobar: bool}: entra (o no) a la próxima Vitrina."""
    from src.services import vitrina_service
    try:
        datos = request.get_json(silent=True) or {}
        return _ok(vitrina_service.revisar(candidato_id, datos.get('aprobar') is True, admin="admin"))
    except vitrina_service.VitrinaError as e:
        return jsonify({"success": False, "error": e.mensaje}), 400
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'vitrina_revisar')


# ---------------------------------------------------------------------------
# Observatorio del mercado y barrios normalizados
# ---------------------------------------------------------------------------

@admin_negocio_bp.route('/observatorio', methods=['GET'])
def observatorio():
    """Precio por m², tiempo en el mercado, oferta vs demanda y características (observatorio_service)."""
    from src.services import observatorio_service
    try:
        tipo = request.args.get('tipo', 'apartamento')
        return _ok(observatorio_service.calcular(request.args.get('municipio') or None,
                                                 None if tipo == 'todos' else tipo))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'observatorio')


@admin_negocio_bp.route('/comunas/geojson', methods=['GET'])
def comunas_geojson():
    try:
        return _ok(barrios_service.geojson_comunas())
    except Exception as e:
        return _fallo(e, 'comunas_geojson')


@admin_negocio_bp.route('/barrios/geojson', methods=['GET'])
def barrios_geojson():
    from src.services import barrios_service
    try:
        return _ok(barrios_service.geojson_barrios())
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'barrios_geojson')


@admin_negocio_bp.route('/barrios', methods=['GET'])
def barrios_resumen():
    """Cobertura del catálogo y los alias dudosos que hay que revisar."""
    from src.services import barrios_service
    try:
        return _ok({**barrios_service.resumen(), "revisar": barrios_service.por_revisar()})
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'barrios')


@admin_negocio_bp.route('/barrios/buscar', methods=['GET'])
def barrios_buscar():
    from src.services import barrios_service
    try:
        return _ok(barrios_service.buscar(request.args.get('q', '')))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'barrios_buscar')


@admin_negocio_bp.route('/barrios/alias/<int:alias_id>', methods=['POST'])
def barrios_alias(alias_id):
    """{barrio_id: int | null}: confirma o corrige un alias (null = no es un lugar)."""
    from src.services import barrios_service
    try:
        datos = request.get_json(silent=True) or {}
        return _ok(barrios_service.revisar_alias(alias_id, datos.get('barrio_id')))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'barrios_alias')


# ── Crecimiento: embudo por canal, cohortes e ingresos (crecimiento_service) ──

@admin_negocio_bp.route('/crecimiento/embudo', methods=['GET'])
def crecimiento_embudo():
    from src.services import crecimiento_service as cs
    try:
        return _ok(cs.embudo(_int('dias', 90, maximo=3650)))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'crecimiento_embudo')


@admin_negocio_bp.route('/crecimiento/cohortes', methods=['GET'])
def crecimiento_cohortes():
    from src.services import crecimiento_service as cs
    try:
        return _ok(cs.cohortes(_int('semanas', 10, maximo=52)))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'crecimiento_cohortes')


@admin_negocio_bp.route('/crecimiento/ingresos', methods=['GET'])
def crecimiento_ingresos():
    from src.services import crecimiento_service as cs
    try:
        return _ok(cs.ingresos(_int('meses', 6, maximo=24)))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'crecimiento_ingresos')


# ── Economía, rentabilidad y lo que necesita atención (economia_service, atencion_service) ──

@admin_negocio_bp.route('/economia', methods=['GET'])
def economia():
    from src.services import economia_service as ec
    try:
        return _ok(ec.llaves_y_fyns())
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'economia')


@admin_negocio_bp.route('/rentabilidad', methods=['GET'])
def rentabilidad():
    from src.services import economia_service as ec
    try:
        return _ok(ec.rentabilidad(_int('dias', 30)))
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'rentabilidad')


@admin_negocio_bp.route('/atencion', methods=['GET'])
def atencion():
    from src.services import atencion_service
    try:
        return _ok(atencion_service.hoy())
    except Exception as e:  # noqa: BLE001
        return _fallo(e, 'atencion')


# ── Índice Fynder mensual (indice_service) ──────────────────────────────────

def _indice(fn, contexto: str):
    from src.services import indice_service
    try:
        return _ok(fn(indice_service))
    except indice_service.IndiceError as e:
        return jsonify({"success": False, "code": e.codigo, "error": e.mensaje}), 400
    except Exception as e:  # noqa: BLE001
        return _fallo(e, contexto)


@admin_negocio_bp.route('/indice', methods=['GET'])
def indice_ediciones():
    return _indice(lambda s: s.ediciones_admin(), 'indice_ediciones')


@admin_negocio_bp.route('/indice/<mes>', methods=['GET'])
def indice_edicion(mes):
    return _indice(lambda s: {**s.edicion(mes, publico=False), "nota_de_prensa": s.nota_de_prensa(mes)}, 'indice_edicion')


@admin_negocio_bp.route('/indice/<mes>/calcular', methods=['POST'])
def indice_calcular(mes):
    return _indice(lambda s: s.calcular(mes), 'indice_calcular')


@admin_negocio_bp.route('/indice/<mes>/publicar', methods=['POST'])
def indice_publicar(mes):
    from src.api.access import admin_actual
    d = request.get_json(silent=True) or {}
    return _indice(lambda s: s.publicar(mes, d.get('titular'), (admin_actual() or {}).get('email')), 'indice_publicar')


@admin_negocio_bp.route('/indice/<mes>/despublicar', methods=['POST'])
def indice_despublicar(mes):
    return _indice(lambda s: s.despublicar(mes), 'indice_despublicar')
