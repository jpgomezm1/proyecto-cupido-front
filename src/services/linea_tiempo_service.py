"""
La historia de un agente en un solo hilo, para su ficha en el admin: cómo llegó, cuándo
verificó, qué buscó, qué contactos abrió, qué pagó, qué le escribió ventas, qué pidió a
soporte y lo que hizo el equipo con su cuenta. Solo lectura, del más reciente al más viejo.

Sin contactos de terceros: de un desbloqueo sale el inmueble, no el teléfono abierto.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List

from src.services.db import fetch_all, fetch_one, get_db

_TEL10 = "RIGHT(REGEXP_REPLACE(COALESCE({c},''),'[^0-9]','','g'),10)"

# (tipo, SQL que devuelve fecha, titulo, detalle). %(u)s = user_id, %(t)s = sus 10 dígitos.
_FUENTES = [
    ("cuenta", """SELECT fecha_creacion AS fecha, 'Creó su cuenta' AS titulo,
                         CASE WHEN origen = 'provision' THEN 'Cuenta precargada (red)' ELSE NULL END AS detalle
                  FROM chat_users WHERE id = %(u)s"""),
    ("cuenta", """SELECT created_at, 'Se registró', 'Llegó desde: ' || COALESCE(props->>'desde', 'directo')
                  FROM eventos_uso WHERE user_id = %(u)s AND evento = 'cuenta_creada'"""),
    ("cuenta", """SELECT acceso_entregado_at, 'Recibió su acceso', NULL FROM chat_users
                  WHERE id = %(u)s AND acceso_entregado_at IS NOT NULL"""),
    ("cuenta", """SELECT telefono_verificado_at, 'Verificó su celular', NULL FROM chat_users
                  WHERE id = %(u)s AND telefono_verificado_at IS NOT NULL"""),
    ("cuenta", """SELECT terminos_aceptados_at, 'Aceptó los términos', terminos_version FROM chat_users
                  WHERE id = %(u)s AND terminos_aceptados_at IS NOT NULL"""),
    ("cuenta", """SELECT onboarding_at, 'Terminó la bienvenida', NULL FROM chat_users
                  WHERE id = %(u)s AND onboarding_at IS NOT NULL"""),
    ("uso", """SELECT fecha_creacion, 'Buscó con Findy', nombre FROM conversaciones_busqueda
               WHERE user_id = %(u)s ORDER BY fecha_creacion DESC LIMIT 40"""),
    ("uso", """SELECT MIN(created_at), 'Conectó su IA', 'Primera consulta desde Claude o ChatGPT'
               FROM mcp_tool_calls WHERE user_id = %(u)s HAVING COUNT(*) > 0"""),
    ("uso", """SELECT DATE_TRUNC('day', created_at) + INTERVAL '12 hours', 'Usó su IA',
                      COUNT(*) || ' consultas (' || STRING_AGG(DISTINCT tool, ', ') || ')'
               FROM mcp_tool_calls WHERE user_id = %(u)s GROUP BY DATE_TRUNC('day', created_at)
               ORDER BY 1 DESC LIMIT 20"""),
    ("uso", """SELECT created_at, 'Creó un cliente', nombre FROM clientes_agente WHERE user_id = %(u)s"""),
    ("uso", """SELECT e.fecha_evento, 'Publicó un inmueble', p.titulo FROM eventos_log e
               LEFT JOIN propiedades p ON p.id = e.propiedad_id
               WHERE e.tipo_evento = 'listing_creado_fynder' AND e.datos_evento->>'user_id' = %(us)s"""),
    ("contacto", """SELECT d.created_at,
                           CASE WHEN d.estado = 'reembolsado' THEN 'Abrió un contacto (reembolsado)' ELSE 'Abrió un contacto' END,
                           COALESCE(p.titulo, 'Pedido de compra') || ' · ' || d.fuente_credito || ' · ' || COALESCE(d.canal, 'web')
                    FROM desbloqueos d LEFT JOIN propiedades p ON d.tipo = 'propiedad' AND p.id = d.ref_id
                    WHERE d.user_id = %(u)s"""),
    ("contacto", """SELECT created_at, 'Reportó un contacto', motivo || CASE WHEN reembolsado THEN ' · le devolvimos la llave' ELSE '' END
                    FROM reportes_contacto WHERE user_id = %(u)s"""),
    ("dinero", """SELECT p.created_at, CASE p.estado WHEN 'aprobado' THEN 'Pagó' ELSE 'Pago ' || p.estado END,
                         COALESCE(pl.nombre, p.plan_codigo) || ' · $' || REPLACE(TO_CHAR(p.monto_cop, 'FM999,999,999'), ',', '.')
                  FROM pagos p LEFT JOIN planes pl ON pl.codigo = p.plan_codigo WHERE p.user_id = %(u)s"""),
    ("dinero", """SELECT s.inicio, 'Plan ' || COALESCE(pl.nombre, s.plan_codigo),
                         s.desbloqueos_incluidos || ' llaves · hasta ' || TO_CHAR(s.fin, 'DD-MM-YYYY')
                         || CASE WHEN COALESCE(s.bono_lanzamiento, 0) > 0 THEN ' · doble de lanzamiento' ELSE '' END
                  FROM suscripciones s LEFT JOIN planes pl ON pl.codigo = s.plan_codigo WHERE s.user_id = %(u)s"""),
    ("dinero", """SELECT created_at,
                         CASE tipo WHEN 'prueba' THEN 'Recibió llaves de prueba' WHEN 'premio' THEN 'Ganó llaves'
                                   WHEN 'extra' THEN 'Recibió llaves' ELSE 'Ajuste de llaves' END,
                         cantidad || ' · ' || COALESCE(referencia, '')
                  FROM creditos_movimientos WHERE user_id = %(u)s"""),
    ("dinero", """SELECT created_at, 'Canjeó Fyns', (-cantidad) || ' Fyns · ' || COALESCE(referencia, '')
                  FROM fyns_movimientos WHERE user_id = %(u)s AND cantidad < 0"""),
    ("ventas", """SELECT creado_at, 'Ventas: ' || tipo, LEFT(COALESCE(detalle::text, ''), 160)
                  FROM ventas_eventos WHERE %(t)s <> '' AND telefono_10 = %(t)s"""),
    ("soporte", """SELECT created_at, 'Pidió soporte', COALESCE(asunto, categoria) FROM soporte_solicitudes WHERE user_id = %(u)s"""),
    ("soporte", """SELECT fecha_creacion, 'Mandó feedback', COALESCE(ai_titulo, LEFT(contenido, 120)) FROM feedback WHERE user_id = %(u)s"""),
    ("equipo", """SELECT created_at, 'Equipo: ' || accion, admin_email FROM auditoria_admin WHERE user_id = %(u)s"""),
    ("correo", """SELECT created_at, 'Le enviamos un correo', tipo FROM correos_enviados WHERE user_id = %(u)s"""),
]


def de(user_id: int, limite: int = 200) -> Dict[str, Any]:
    eventos: List[Dict[str, Any]] = []
    errores: List[str] = []
    with get_db() as db:
        cur = db.cursor
        u = fetch_one(cur, f"SELECT telefono, {_TEL10.format(c='telefono')} AS t FROM chat_users WHERE id = %s", (user_id,))
        if not u:
            return {"eventos": [], "errores": ["no existe"]}
        params = {"u": user_id, "us": str(user_id), "t": u["t"] or ""}
        for tipo, sql in _FUENTES:
            try:
                # Nombres explícitos: un NULL o un texto fijo sin alias salen como «?column?»
                # repetido y el cursor de diccionarios los junta en uno.
                for f in fetch_all(cur, f"SELECT * FROM ({sql}) AS x(fecha, titulo, detalle)", params):
                    vals = [f["fecha"], f["titulo"], f["detalle"]]
                    if vals[0] is None:
                        continue
                    fecha = vals[0]
                    if not isinstance(fecha, datetime):  # una fecha sin hora
                        fecha = datetime(fecha.year, fecha.month, fecha.day, 12)
                    # Unas columnas son timestamptz y otras UTC sin zona: todo a UTC para ordenar.
                    fecha = fecha.replace(tzinfo=timezone.utc) if fecha.tzinfo is None else fecha.astimezone(timezone.utc)
                    eventos.append({"tipo": tipo, "fecha": fecha.isoformat(), "titulo": vals[1],
                                    "detalle": (str(vals[2]).strip(" ·") or None) if vals[2] is not None else None})
            except Exception as e:  # noqa: BLE001 — una fuente rota no tumba la línea de tiempo
                db.conn.rollback()
                errores.append(f"{tipo}: {str(e)[:100]}")
    eventos.sort(key=lambda e: e["fecha"], reverse=True)
    return {"eventos": eventos[:limite], "total": len(eventos), "errores": errores}
