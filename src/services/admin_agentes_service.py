"""
Gestión de agentes desde el admin: crear cuentas (normales, demo o de regalo),
activar planes pagados por fuera de Wompi, dar llaves, regenerar la clave y la
ficha completa de un agente.

Reglas:
- Un pago manual (transferencia, efectivo, otro) se registra también en `pagos`
  con pasarela 'manual' y estado 'aprobado', para que los ingresos del admin
  (Negocio, Pagos) lo cuenten. Un regalo o una demo NO es ingreso: el periodo
  queda con precio 0 y no genera pago.
- Toda acción queda en `auditoria_admin` con el email del admin.
- La clave nueva se devuelve una sola vez y no queda guardada en claro.
"""

import json
import uuid
from typing import Any, Dict, Optional

from src.services.acquisition_service import clave_nueva
from src.services.auditoria import registrar
from src.services.db import fetch_all, fetch_one, get_db, scalar
from src.services import suscripcion_service as svc
from src.utils.phone import normalize_colombia_phone

FORMAS_PAGADAS = {"transferencia", "efectivo", "otro"}
FORMAS_GRATIS = {"regalo", "demo"}
TIPOS_CUENTA = {"normal", "demo", "regalo"}


class AgenteError(Exception):
    pass


def _registrar_pago_manual(cur, user_id: int, plan_codigo: str, monto: int, forma: str,
                           referencia: Optional[str], suscripcion_id: Optional[int],
                           movimiento_id: Optional[int], admin: Optional[str]) -> int:
    cur.execute("""
        INSERT INTO pagos (referencia, user_id, plan_codigo, monto_cop, pasarela, estado, metodo,
                           suscripcion_id, movimiento_id, detalle)
        VALUES (%s, %s, %s, %s, 'manual', 'aprobado', %s, %s, %s, %s) RETURNING id
    """, (f"MAN-{uuid.uuid4().hex[:12]}", user_id, plan_codigo, int(monto), forma.upper(),
          suscripcion_id, movimiento_id,
          json.dumps({"referencia_externa": referencia, "registrado_por": admin})))
    return cur.fetchone()["id"]


def _precio_plan(cur, codigo: str) -> int:
    return int(scalar(cur, "SELECT precio_cop FROM planes WHERE codigo = %s", (codigo,)) or 0)


def activar_plan(user_id: int, plan_codigo: str, forma: str, referencia: Optional[str] = None,
                 monto_cop: Optional[int] = None, notas: Optional[str] = None,
                 admin: Optional[str] = None) -> Dict[str, Any]:
    """Activa un plan mensual o vende/regala llaves sueltas (plan tipo 'paquete')."""
    forma = (forma or "").lower()
    if forma not in FORMAS_PAGADAS | FORMAS_GRATIS:
        raise AgenteError("Forma de pago inválida")
    if forma in FORMAS_PAGADAS and not (referencia or "").strip():
        raise AgenteError("Escribe la referencia del pago (número de la transferencia o recibo)")
    with get_db() as db:
        cur = db.cursor
        plan = fetch_one(cur, "SELECT * FROM planes WHERE codigo = %s AND activo", (plan_codigo,))
        if not plan:
            raise AgenteError("Plan inválido")
        pagado = forma in FORMAS_PAGADAS
        monto = int(monto_cop) if monto_cop not in (None, "") else _precio_plan(cur, plan_codigo)
        ref = (referencia or "").strip() or None
        nota = notas or ("Regalo" if forma == "regalo" else "Demo" if forma == "demo" else f"Pago {forma}")
        try:
            if plan.get("tipo") == "paquete":
                res = svc.abonar_paquete_en(cur, user_id, plan_codigo, ref or nota, admin)
                sus_id, mov_id = None, res["movimiento_id"]
            elif plan.get("tipo") == "fotos":
                from src.services import fotos_ia_service
                res = fotos_ia_service.abonar_en(cur, user_id, plan_codigo, ref or nota, admin)
                sus_id, mov_id = None, None
            elif plan.get("tipo") == "complemento":
                from src.services import beneficios_service
                res = beneficios_service.activar_complemento_en(cur, user_id, plan_codigo, ref or nota, admin,
                                                                precio_cop=monto if pagado else 0)
                sus_id, mov_id = None, None
            else:
                res = svc.activar_plan_en(cur, user_id, plan_codigo, ref, nota, admin,
                                          precio_cop=monto if pagado else 0)
                sus_id, mov_id = res["suscripcion_id"], None
        except svc.SuscripcionError as e:
            raise AgenteError(str(e)) from e
        pago_id = _registrar_pago_manual(cur, user_id, plan_codigo, monto, forma, ref, sus_id, mov_id, admin) \
            if pagado else None
        db.conn.commit()
    registrar("plan_activado" if pagado else "plan_regalado", user_id,
              {"plan": plan_codigo, "forma": forma, "monto": monto if pagado else 0, "referencia": ref})
    return {**res, "pago_id": pago_id, "forma": forma}


def dar_llaves(user_id: int, cantidad: int, motivo: str, referencia: Optional[str] = None,
               monto_cop: Optional[int] = None, admin: Optional[str] = None) -> Dict[str, Any]:
    """motivo: regalo (gratis) · venta (pago manual, va a ingresos) · ajuste (puede ser negativo)."""
    motivo = (motivo or "").lower()
    cantidad = int(cantidad or 0)
    if motivo not in ("regalo", "venta", "ajuste"):
        raise AgenteError("Motivo inválido")
    if motivo == "venta":
        if cantidad <= 0:
            raise AgenteError("Cantidad inválida")
        if not (referencia or "").strip():
            raise AgenteError("Escribe la referencia del pago")
    tipo = "ajuste" if motivo == "ajuste" else "extra"
    ref = f"{motivo.capitalize()}" + (f" · {referencia.strip()}" if (referencia or "").strip() else "")
    try:
        res = svc.agregar_creditos(user_id, cantidad, tipo, ref, admin)
    except svc.SuscripcionError as e:
        raise AgenteError(str(e)) from e
    pago_id = None
    if motivo == "venta":
        with get_db() as db:
            llave = fetch_one(db.cursor, "SELECT codigo, precio_cop FROM planes WHERE tipo = 'paquete' ORDER BY precio_cop LIMIT 1")
            if llave:
                monto = int(monto_cop) if monto_cop not in (None, "") else int(llave["precio_cop"]) * cantidad
                pago_id = _registrar_pago_manual(db.cursor, user_id, llave["codigo"], monto, "transferencia",
                                                 referencia, None, res["movimiento_id"], admin)
                db.conn.commit()
    registrar(f"llaves_{motivo}", user_id, {"cantidad": cantidad, "referencia": referencia})
    return {**res, "pago_id": pago_id}


def crear_agente(datos: Dict[str, Any], admin: Optional[str] = None) -> Dict[str, Any]:
    """Crea una cuenta lista para usar. tipo: normal · demo · regalo.
    Opcional: plan inicial (con su forma de pago) y llaves de regalo."""
    tipo = (datos.get("tipo") or "normal").lower()
    if tipo not in TIPOS_CUENTA:
        raise AgenteError("Tipo de cuenta inválido")
    nombre = (datos.get("nombre") or "").strip() or ("Cuenta demo" if tipo == "demo" else "")
    if not nombre:
        raise AgenteError("Escribe el nombre del agente")
    email = (datos.get("email") or "").strip().lower()
    if not email:
        if tipo != "demo":
            raise AgenteError("Escribe el correo del agente")
        email = f"demo-{uuid.uuid4().hex[:6]}@getfynder.com"
    telefono = normalize_colombia_phone(datos.get("telefono")) if datos.get("telefono") else None
    if datos.get("telefono") and not telefono:
        raise AgenteError("El celular no es válido (ej: 300 123 4567)")
    verificar = bool(datos.get("verificar_telefono")) and telefono is not None
    password = clave_nueva()

    with get_db() as db:
        cur = db.cursor
        if scalar(cur, "SELECT 1 FROM chat_users WHERE lower(email) = %s", (email,)):
            raise AgenteError(f"Ya existe una cuenta con {email}")
        if telefono and scalar(cur, """
            SELECT 1 FROM chat_users
            WHERE RIGHT(REGEXP_REPLACE(COALESCE(telefono,''),'[^0-9]','','g'),10) = RIGHT(%s, 10)
        """, (telefono,)):
            raise AgenteError("Ese celular ya es de otra cuenta")
        cur.execute("""
            INSERT INTO chat_users (email, nombre, password_hash, telefono, activo, origen,
                                    telefono_verificado, telefono_verificado_at)
            VALUES (%s, %s, crypt(%s, gen_salt('bf')), %s, TRUE, %s, %s, CASE WHEN %s THEN NOW() END)
            RETURNING id
        """, (email, nombre, password, telefono, f"admin_{tipo}", verificar, verificar))
        user_id = cur.fetchone()["id"]
        if verificar:
            svc.asegurar_prueba(cur, svc._usuario(cur, user_id))
        db.conn.commit()

    registrar("agente_creado", user_id, {"tipo": tipo, "email": email, "telefono_verificado": verificar})
    resultado: Dict[str, Any] = {"id": user_id, "email": email, "nombre": nombre, "password": password,
                                 "tipo": tipo, "telefono_verificado": verificar}

    plan = (datos.get("plan_codigo") or "").strip()
    if plan:
        forma = (datos.get("forma_pago") or ("demo" if tipo == "demo" else "regalo" if tipo == "regalo" else "")).lower()
        resultado["plan"] = activar_plan(user_id, plan, forma, datos.get("referencia"), datos.get("monto_cop"),
                                         admin=admin)
    llaves = int(datos.get("llaves_regalo") or 0)
    if llaves > 0:
        resultado["llaves"] = dar_llaves(user_id, llaves, "regalo",
                                         "Cuenta demo" if tipo == "demo" else "Bienvenida", admin=admin)
    return resultado


def nueva_clave(user_id: int) -> Dict[str, Any]:
    password = clave_nueva()
    with get_db() as db:
        db.cursor.execute("UPDATE chat_users SET password_hash = crypt(%s, gen_salt('bf')) WHERE id = %s RETURNING email, nombre",
                          (password, user_id))
        row = db.cursor.fetchone()
        if not row:
            raise AgenteError("Agente no encontrado")
        db.cursor.execute("UPDATE chat_user_sessions SET activa = FALSE WHERE user_id = %s", (user_id,))
        db.conn.commit()
    registrar("clave_regenerada", user_id)
    return {"email": row["email"], "nombre": row["nombre"], "password": password}


def ficha(user_id: int) -> Dict[str, Any]:
    """Todo lo de un agente en un solo lugar."""
    with get_db() as db:
        cur = db.cursor
        u = fetch_one(cur, """
            SELECT id, nombre, email, telefono, activo, telefono_verificado, telefono_verificado_at,
                   terminos_aceptados_at, origen, acceso_entregado, fecha_creacion, ultimo_login,
                   pagina_slug, pagina_activa
            FROM chat_users WHERE id = %s
        """, (user_id,))
        if not u:
            raise AgenteError("Agente no encontrado")
        tel10 = "".join(c for c in (u.get("telefono") or "") if c.isdigit())[-10:] or None
        uso = fetch_one(cur, """
            SELECT (SELECT COUNT(*) FROM mcp_tool_calls WHERE user_id = %s AND created_at > NOW() - INTERVAL '30 days') AS mcp_30d,
                   (SELECT MAX(created_at) FROM mcp_tool_calls WHERE user_id = %s) AS mcp_ultimo,
                   (SELECT COALESCE(SUM(busquedas), 0) FROM uso_diario WHERE user_id = %s AND fecha > (NOW() - INTERVAL '30 days')::date) AS busquedas_30d,
                   (SELECT COUNT(*) FROM conversaciones_busqueda WHERE user_id = %s) AS conversaciones,
                   (SELECT COUNT(*) FROM clientes_agente WHERE user_id = %s AND estado = 'activo') AS clientes,
                   (SELECT COUNT(*) FROM chat_user_sessions WHERE user_id = %s AND activa) AS sesiones_activas
        """, (user_id,) * 6)
        inmuebles = scalar(cur, """
            SELECT COUNT(*) FROM propiedades
            WHERE activa AND RIGHT(REGEXP_REPLACE(COALESCE(agente_captador_telefono,''),'[^0-9]','','g'),10) = %s
        """, (tel10,)) if tel10 and u.get("telefono_verificado") else 0
        pagos = fetch_all(cur, """
            SELECT id, referencia, estado, pasarela, metodo, monto_cop, plan_codigo, created_at
            FROM pagos WHERE user_id = %s ORDER BY created_at DESC LIMIT 30
        """, (user_id,))
        try:
            auditoria = fetch_all(cur, """
                SELECT accion, admin_email, detalle, created_at FROM auditoria_admin
                WHERE user_id = %s ORDER BY created_at DESC LIMIT 30
            """, (user_id,))
        except Exception:  # noqa: BLE001 — sin la migración 053
            db.conn.rollback()
            auditoria = []
    iso = lambda r: {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}  # noqa: E731
    return {
        "agente": iso(u),
        "plan": svc.estado(user_id),
        "detalle": svc.detalle_usuario(user_id),
        "uso": {**iso(uso), "inmuebles_activos": int(inmuebles or 0)},
        "pagos": [iso(p) for p in pagos],
        "auditoria": [iso(a) for a in auditoria],
    }
