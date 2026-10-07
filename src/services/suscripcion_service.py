"""
Suscripciones y desbloqueo de contactos (modelo de negocio desde oct-2026).

Lo que se cobra es saber QUIÉN TIENE un inmueble (o quién hizo un pedido): el
contacto. Todo lo demás (búsqueda, análisis, reportes) es gratis con uso justo.

Llaves (los créditos; el saldo NUNCA se guarda: se deriva de las tablas, no puede desfasarse):
  - plan:  las llaves del periodo pagado vigente (incluye 5 días de gracia).
           No se acumulan: un periodo nuevo trae su propio cupo.
  - saldo: llaves que no vencen (prueba de 2 al verificar el teléfono,
           paquetes extra, ajustes) − desbloqueos cobrados contra ese saldo.
  Se consume primero el plan. Un reembolso marca el desbloqueo 'reembolsado' y
  la llave vuelve sola a su fuente.

Reglas de cobro (`desbloquear`):
  - Re-ver un desbloqueo vigente: gratis.
  - Inmueble/pedido propio (teléfono verificado): gratis.
  - Sin contacto usable o inmueble no disponible (verificado en vivo): no cobra.
  - Pedidos: solo si quien lo hizo tiene cuenta Fynder activa, con teléfono
    verificado y términos aceptados (habeas data, Ley 1581).
  - El cobro es una transacción corta con lock por usuario; el chequeo HTTP de
    disponibilidad (hasta 20 s) ocurre ANTES, sin lock ni conexión retenida.
"""

import os
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional, Set

from src.services import seguimiento_service
from src.services.db import get_db, fetch_one, fetch_all, scalar
from src.services.disponibilidad_service import verificar_disponibilidad
from src.services.interes_service import cargar_puntas, _limpiar_texto_captador
from src.services.redact import redact_phones
from src.services.textutils import normalize_phone

TZ = "America/Bogota"
TERMINOS_VERSION = "2026-10"
CREDITOS_PRUEBA = 2
DIAS_PERIODO = 30
DIAS_GRACIA = 5
DIAS_VIGENCIA_PEDIDO = 120  # = compradores_service.DIAS_PEDIDOS
DIAS_PARA_REPORTAR = 15

# Lock transaccional por usuario para el cobro: (clase, user_id).
_LOCK_COBRO = 7101

_SQL_PHONE10 = "RIGHT(REGEXP_REPLACE(COALESCE({col},''),'[^0-9]','','g'),10)"


def _limite(nombre: str, defecto: int) -> int:
    try:
        return int(os.getenv(nombre, str(defecto)))
    except ValueError:
        return defecto


def limite_busquedas_dia() -> int:
    return _limite("FYNDER_FAIR_USE_DIARIO", 100)


def limite_desbloqueos_dia() -> int:
    return _limite("FYNDER_DESBLOQUEOS_DIA", 25)


def limite_reembolsos_mes() -> int:
    return _limite("FYNDER_REEMBOLSOS_MES", 3)


def url_terminos() -> str:
    base = os.getenv("FYNDER_FRONTEND_URL", "https://fyndercol.netlify.app").rstrip("/")
    return f"{base}/terminos"


def instrucciones_pago() -> str:
    return os.getenv(
        "FYNDER_PAGO_INSTRUCCIONES",
        "Para activar o renovar tu plan, escríbenos por WhatsApp a Fynder: te "
        "enviamos los datos para la consignación y activamos tu plan apenas la "
        "confirmemos.")


class SuscripcionError(Exception):
    """Error de validación en operaciones de administración."""


def _error(codigo: str, mensaje: str, **extra) -> Dict[str, Any]:
    return {"ok": False, "error": codigo, "mensaje": mensaje, **extra}


# =========================================================================
# Contacto usable
# =========================================================================

def _telefonos_propios() -> Set[str]:
    """Números de Fynder/Hernán: nunca cuentan como contacto de un captador."""
    raw = os.getenv("FYNDER_TELEFONOS_PROPIOS", "")
    return {n for n in (normalize_phone(x) for x in raw.split(",")) if n}


def contacto_usable(tel: Optional[str]) -> Optional[str]:
    """
    Devuelve los 10 dígitos del teléfono si sirve para contactar a alguien, o
    None si no (vacío, enmascarado, id de grupo de WhatsApp, número corto o de
    dígitos repetidos, o un número propio de Fynder).
    """
    if not tel:
        return None
    raw = str(tel).strip()
    if "@g.us" in raw or "*" in raw or re.search(r"[xX]{2,}", raw):
        return None
    digitos = normalize_phone(raw)
    if not digitos or len(digitos) != 10:
        return None
    if len(set(digitos)) == 1:
        return None
    if not (digitos.startswith("3") or digitos.startswith("60")):
        return None
    if digitos in _telefonos_propios():
        return None
    return digitos


# =========================================================================
# Saldo
# =========================================================================

def _usuario(cur, user_id: int) -> Optional[Dict[str, Any]]:
    return fetch_one(cur, """
        SELECT id, nombre, email, telefono, activo, telefono_verificado,
               terminos_aceptados_at, terminos_version, origen, acceso_entregado
        FROM chat_users WHERE id = %s
    """, (user_id,))


def asegurar_prueba(cur, usuario: Dict[str, Any]) -> None:
    """
    Otorga las llaves de prueba (una sola vez por usuario y por teléfono) si
    el teléfono está verificado. Idempotente. El caller hace commit.
    """
    tel10 = normalize_phone(usuario.get("telefono"))
    if not usuario.get("telefono_verificado") or not tel10:
        return
    # Las cuentas precargadas comparten clave estándar y correo predecible: la
    # prueba solo se activa cuando Fynder ya le entregó el acceso al agente.
    if usuario.get("origen") == "provision" and not usuario.get("acceso_entregado"):
        return
    cur.execute("""
        INSERT INTO creditos_movimientos (user_id, tipo, cantidad, telefono_10, referencia, creado_por)
        VALUES (%s, 'prueba', %s, %s, 'Prueba al verificar teléfono', 'sistema')
        ON CONFLICT DO NOTHING
    """, (usuario["id"], CREDITOS_PRUEBA, tel10))


def _periodo_vigente(cur, user_id: int) -> Optional[Dict[str, Any]]:
    """El periodo pagado que aplica hoy (el más reciente, incluida la gracia)."""
    return fetch_one(cur, """
        SELECT s.*, p.nombre AS plan_nombre
        FROM suscripciones s JOIN planes p ON p.codigo = s.plan_codigo
        WHERE s.user_id = %s AND s.estado = 'activa'
          AND s.inicio <= NOW() AND NOW() < s.gracia_hasta
        ORDER BY s.inicio DESC LIMIT 1
    """, (user_id,))


def _saldos(cur, user_id: int) -> Dict[str, Any]:
    periodo = _periodo_vigente(cur, user_id)
    plan_usados = 0
    if periodo:
        plan_usados = scalar(cur, """
            SELECT COUNT(*) FROM desbloqueos
            WHERE suscripcion_id = %s AND fuente_credito = 'plan' AND estado = 'vigente'
        """, (periodo["id"],)) or 0
    abonos = scalar(cur, "SELECT COALESCE(SUM(cantidad), 0) FROM creditos_movimientos WHERE user_id = %s",
                    (user_id,)) or 0
    gastos = scalar(cur, """
        SELECT COUNT(*) FROM desbloqueos
        WHERE user_id = %s AND fuente_credito = 'saldo' AND estado = 'vigente'
    """, (user_id,)) or 0
    plan_incluidos = periodo["desbloqueos_incluidos"] if periodo else 0
    plan_disp = max(0, plan_incluidos - plan_usados)
    saldo = max(0, int(abonos) - int(gastos))
    return {
        "periodo": periodo,
        "plan_incluidos": plan_incluidos,
        "plan_disponibles": plan_disp,
        "saldo": saldo,
        "disponibles": plan_disp + saldo,
    }


def _reembolsos_este_mes(cur, user_id: int) -> int:
    return scalar(cur, f"""
        SELECT COUNT(*) FROM reportes_contacto
        WHERE user_id = %s AND reembolsado
          AND created_at >= date_trunc('month', NOW() AT TIME ZONE '{TZ}') AT TIME ZONE '{TZ}'
    """, (user_id,)) or 0


def planes_activos(cur) -> List[Dict[str, Any]]:
    return fetch_all(cur, """
        SELECT codigo, nombre, precio_cop, desbloqueos_mes
        FROM planes WHERE activo AND codigo <> 'prueba' ORDER BY orden
    """)


def estado(user_id: int) -> Dict[str, Any]:
    """Plan, saldo y condiciones del usuario (para `mi_plan` y la web)."""
    with get_db() as db:
        cur = db.cursor
        usuario = _usuario(cur, user_id)
        if not usuario:
            return _error("no_encontrado", "Usuario no encontrado.")
        asegurar_prueba(cur, usuario)
        db.conn.commit()
        s = _saldos(cur, user_id)
        periodo = s["periodo"]
        reembolsos = _reembolsos_este_mes(cur, user_id)
        planes = planes_activos(cur)

    plan = None
    if periodo:
        plan = {
            "codigo": periodo["plan_codigo"],
            "nombre": periodo["plan_nombre"],
            "vence": periodo["fin"].isoformat(),
            "gracia_hasta": periodo["gracia_hasta"].isoformat(),
            "en_gracia": bool(periodo["fin"] <= _ahora()),
        }
    return {
        "ok": True,
        "plan": plan,
        "plan_incluidos": s["plan_incluidos"],
        "plan_disponibles": s["plan_disponibles"],
        "saldo": s["saldo"],
        "disponibles": s["disponibles"],
        "telefono_verificado": bool(usuario.get("telefono_verificado")),
        "terminos_aceptados": usuario.get("terminos_aceptados_at") is not None,
        "reembolsos_restantes_mes": max(0, limite_reembolsos_mes() - reembolsos),
        "planes": planes,
        "instrucciones_pago": instrucciones_pago(),
        "pago_en_linea": _pago_en_linea(),
    }


def _pago_en_linea() -> bool:
    from src.services import pagos_service  # import diferido: pagos_service importa este módulo
    return pagos_service.habilitado()


def _ahora():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


# =========================================================================
# Resolución de lo que se desbloquea
# =========================================================================

def _resolver(cur, tipo: str, ref) -> Dict[str, Any]:
    """
    Devuelve {ref_id, contacto: {telefono, nombre, agencia}, titulo, codigo,
    activa?, pedido?} o {error, mensaje}.
    """
    if tipo == "propiedad":
        datos = cargar_puntas(cur, ref)
        if datos.get("error"):
            return {"error": "no_encontrada", "mensaje": datos["error"]}
        prop, vend = datos["propiedad"], datos["vendedor"]
        return {
            "ref_id": prop["id"],
            "codigo": prop.get("codigo"),
            "titulo": prop.get("titulo"),
            "activa": prop.get("activa"),
            "contacto": {"telefono": vend.get("telefono"), "nombre": vend.get("nombre"),
                         "agencia": vend.get("agencia")},
        }

    if tipo == "pedido":
        try:
            pedido_id = int(ref)
        except (TypeError, ValueError):
            return {"error": "no_encontrada", "mensaje": f"Pedido inválido: {ref}"}
        row = fetch_one(cur, """
            SELECT id, agente_telefono, agente_nombre, texto_pedido, fecha_captura, estado
            FROM pedidos WHERE id = %s
        """, (pedido_id,))
        if not row:
            return {"error": "no_encontrada", "mensaje": f"No encontré el pedido {pedido_id}."}
        texto = redact_phones(row.get("texto_pedido") or "", cut_signatures=True)
        return {
            "ref_id": row["id"],
            "codigo": f"pedido-{row['id']}",
            "titulo": (texto[:120] + "…") if len(texto) > 120 else texto,
            "fecha_captura": row.get("fecha_captura"),
            "contacto": {"telefono": row.get("agente_telefono"),
                         "nombre": _limpiar_texto_captador(row.get("agente_nombre")),
                         "agencia": None},
        }

    return {"error": "tipo_invalido", "mensaje": "tipo debe ser 'propiedad' o 'pedido'."}


def _pedido_desbloqueable(cur, tel10: str) -> bool:
    """El autor del pedido es usuario Fynder activo, verificado y con términos."""
    return bool(scalar(cur, f"""
        SELECT 1 FROM chat_users
        WHERE activo AND telefono_verificado AND terminos_aceptados_at IS NOT NULL
          AND {_SQL_PHONE10.format(col='telefono')} = %s
        LIMIT 1
    """, (tel10,)))


def _es_propio(usuario: Dict[str, Any], tel10: Optional[str]) -> bool:
    if not usuario.get("telefono_verificado") or not tel10:
        return False
    return normalize_phone(usuario.get("telefono")) == tel10


def _desbloqueo_existente(cur, user_id: int, tipo: str, ref_id: int) -> Optional[Dict[str, Any]]:
    return fetch_one(cur, """
        SELECT id, estado, fuente_credito, contacto_telefono, contacto_nombre, contacto_agencia
        FROM desbloqueos WHERE user_id = %s AND tipo = %s AND ref_id = %s
    """, (user_id, tipo, ref_id))


def _contacto_salida(contacto: Dict[str, Any]) -> Dict[str, Any]:
    return {"telefono": contacto.get("telefono"), "nombre": contacto.get("nombre"),
            "agencia": contacto.get("agencia")}


def _evaluar(cur, usuario: Dict[str, Any], tipo: str, ref) -> Dict[str, Any]:
    """
    Todo lo que se puede decidir sin HTTP ni cobro. Devuelve
    {r: resolución, existente, costo: 0|1, motivo_gratis} o un error.
    """
    r = _resolver(cur, tipo, ref)
    if r.get("error"):
        return _error(r["error"], r["mensaje"])

    existente = _desbloqueo_existente(cur, usuario["id"], tipo, r["ref_id"])
    if existente and existente["estado"] == "vigente":
        return {"r": r, "existente": existente, "costo": 0, "motivo_gratis": "ya_desbloqueado"}

    tel10 = contacto_usable(r["contacto"].get("telefono"))
    if not tel10:
        return _error("sin_contacto",
                      "Este inmueble no tiene un contacto válido cargado. No se cobra: "
                      "Fynder puede coordinar por ti con `solicitar_visita`.",
                      sugerencia="solicitar_visita")

    if _es_propio(usuario, tel10):
        return {"r": r, "existente": existente, "costo": 0, "motivo_gratis": "propia", "tel10": tel10}

    if tipo == "propiedad" and r.get("activa") is False:
        return _error("no_disponible", "Este inmueble ya no está disponible. No se cobra.")

    if tipo == "pedido":
        fecha = r.get("fecha_captura")
        if fecha and fecha < (_ahora().replace(tzinfo=None) - timedelta(days=DIAS_VIGENCIA_PEDIDO)):
            return _error("pedido_vencido",
                          f"Este pedido tiene más de {DIAS_VIGENCIA_PEDIDO} días; ya no se puede desbloquear.")
        if not _pedido_desbloqueable(cur, tel10):
            return _error("pedido_no_desbloqueable",
                          "Quien hizo este pedido todavía no es usuario de Fynder, así que su "
                          "contacto no se puede compartir. No se cobra: Fynder puede conectarte "
                          "con `solicitar_visita`.",
                          sugerencia="solicitar_visita")

    return {"r": r, "existente": existente, "costo": 1, "motivo_gratis": None, "tel10": tel10}


# =========================================================================
# Preview y desbloqueo
# =========================================================================

def preview_desbloqueo(user_id: int, tipo: str, ref) -> Dict[str, Any]:
    """Cuánto costaría desbloquear (sin HTTP ni cobro)."""
    with get_db() as db:
        cur = db.cursor
        usuario = _usuario(cur, user_id)
        if not usuario:
            return _error("no_encontrado", "Usuario no encontrado.")
        asegurar_prueba(cur, usuario)
        db.conn.commit()
        s = _saldos(cur, user_id)
        ev = _evaluar(cur, usuario, tipo, ref)
    if not ev.get("r"):
        return {**ev, "disponibles": s["disponibles"]}
    r = ev["r"]
    return {
        "ok": True,
        "preview": True,
        "tipo": tipo,
        "codigo": r.get("codigo"),
        "titulo": r.get("titulo"),
        "costo": ev["costo"],
        "motivo_gratis": ev["motivo_gratis"],
        "ya_desbloqueado": ev["motivo_gratis"] == "ya_desbloqueado",
        "disponibles": s["disponibles"],
        "terminos_aceptados": usuario.get("terminos_aceptados_at") is not None,
    }


def desbloquear(user_id: int, tipo: str, ref, canal: str = "mcp") -> Dict[str, Any]:
    """
    Desbloquea el contacto de un inmueble o pedido. Devuelve
      {ok, cobrado, fuente, ya_desbloqueado, desbloqueo_id, contacto{telefono,nombre,agencia},
       disponibilidad, disponibles_restantes, codigo, titulo}
    o {ok: False, error, mensaje, ...} con error en: no_encontrada, sin_contacto,
    no_disponible, sin_creditos, pedido_no_desbloqueable, pedido_vencido,
    terminos_pendientes, limite_diario, tipo_invalido.
    """
    # 1) Validaciones baratas, sin lock.
    with get_db() as db:
        cur = db.cursor
        usuario = _usuario(cur, user_id)
        if not usuario or not usuario.get("activo"):
            return _error("no_encontrado", "Usuario no encontrado o inactivo.")
        if usuario.get("terminos_aceptados_at") is None:
            return _error("terminos_pendientes",
                          "Antes de usar tu primera llave debes aceptar los términos de Fynder.")
        hoy = scalar(cur, f"""
            SELECT COUNT(*) FROM desbloqueos
            WHERE user_id = %s AND (created_at AT TIME ZONE '{TZ}')::date = (NOW() AT TIME ZONE '{TZ}')::date
        """, (user_id,)) or 0
        if hoy >= limite_desbloqueos_dia():
            return _error("limite_diario",
                          f"Llegaste al máximo de {limite_desbloqueos_dia()} llaves por día.")
        asegurar_prueba(cur, usuario)
        db.conn.commit()

        ev = _evaluar(cur, usuario, tipo, ref)
        if not ev.get("r"):
            return ev
        r = ev["r"]

        # Re-ver un desbloqueo vigente: gratis, contacto actual (o la copia si ya no sirve).
        if ev["motivo_gratis"] == "ya_desbloqueado":
            ex = ev["existente"]
            contacto = r["contacto"] if contacto_usable(r["contacto"].get("telefono")) else {
                "telefono": ex["contacto_telefono"], "nombre": ex["contacto_nombre"],
                "agencia": ex["contacto_agencia"]}
            s = _saldos(cur, user_id)
            return _exito(ex["id"], r, contacto, cobrado=False, fuente=ex["fuente_credito"],
                          ya=True, disponibilidad=None, disponibles=s["disponibles"])

        # Chequeo rápido de saldo: evita el HTTP si de todas formas no alcanza.
        if ev["costo"] and _saldos(cur, user_id)["disponibles"] <= 0:
            return _sin_creditos(cur, user_id)

    # 2) Disponibilidad en vivo (solo inmuebles cobrables), sin conexión retenida.
    disponibilidad = None
    if tipo == "propiedad" and ev["costo"]:
        disp = verificar_disponibilidad(r["ref_id"])
        if disp.get("error"):
            disp = {"estado": "desconocido", "activo": True}
        if disp.get("estado") in ("404", "no_disponible"):
            return _error("no_disponible",
                          "Verifiqué el inmueble y ya no está publicado. No se cobra; "
                          "lo marqué como no disponible.")
        disponibilidad = {"estado": disp.get("estado"), "verificado_en": disp.get("verificado_en")}

    # 3) Cobro: transacción corta con lock por usuario.
    with get_db() as db:
        cur = db.cursor
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK_COBRO, user_id))
        if ev["costo"]:
            s = _saldos(cur, user_id)
            if s["plan_disponibles"] > 0:
                fuente, suscripcion_id = "plan", s["periodo"]["id"]
            elif s["saldo"] > 0:
                fuente, suscripcion_id = "saldo", None
            else:
                db.conn.rollback()
                return _sin_creditos(cur, user_id)
        else:
            fuente, suscripcion_id = "gratis", None

        c = r["contacto"]
        cur.execute("""
            INSERT INTO desbloqueos (user_id, tipo, ref_id, fuente_credito, suscripcion_id,
                                     motivo_gratis, contacto_telefono, contacto_nombre,
                                     contacto_agencia, disponibilidad_estado, canal)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, tipo, ref_id) DO UPDATE SET
                estado = 'vigente', fuente_credito = EXCLUDED.fuente_credito,
                suscripcion_id = EXCLUDED.suscripcion_id, motivo_gratis = EXCLUDED.motivo_gratis,
                contacto_telefono = EXCLUDED.contacto_telefono,
                contacto_nombre = EXCLUDED.contacto_nombre,
                contacto_agencia = EXCLUDED.contacto_agencia,
                disponibilidad_estado = EXCLUDED.disponibilidad_estado,
                canal = EXCLUDED.canal, created_at = NOW()
            WHERE desbloqueos.estado = 'reembolsado'
            RETURNING id
        """, (user_id, tipo, r["ref_id"], fuente, suscripcion_id, ev["motivo_gratis"],
              c.get("telefono"), c.get("nombre"), c.get("agencia"),
              (disponibilidad or {}).get("estado"), canal))
        fila = cur.fetchone()
        db.conn.commit()
        s = _saldos(cur, user_id)

    if not fila:
        # Otro request lo desbloqueó al mismo tiempo: no se cobra dos veces.
        return _exito(None, r, c, cobrado=False, fuente=None, ya=True,
                      disponibilidad=disponibilidad, disponibles=s["disponibles"])
    return _exito(fila["id"], r, c, cobrado=fuente != "gratis", fuente=fuente, ya=False,
                  disponibilidad=disponibilidad, disponibles=s["disponibles"])


def _exito(desbloqueo_id, r, contacto, *, cobrado, fuente, ya, disponibilidad, disponibles):
    return {
        "ok": True,
        "desbloqueo_id": desbloqueo_id,
        "codigo": r.get("codigo"),
        "titulo": r.get("titulo"),
        "cobrado": cobrado,
        "fuente": fuente,
        "ya_desbloqueado": ya,
        "contacto": _contacto_salida(contacto),
        "disponibilidad": disponibilidad,
        "disponibles_restantes": disponibles,
    }


def _sin_creditos(cur, user_id: int) -> Dict[str, Any]:
    return _error("sin_creditos",
                  "No te quedan llaves. Puedes activar o mejorar tu plan, o comprar un "
                  "paquete extra de llaves.",
                  planes=planes_activos(cur), instrucciones_pago=instrucciones_pago(),
                  disponibles=0)


# =========================================================================
# Consulta de desbloqueos
# =========================================================================

def ids_desbloqueados(user_id: int, tipo: str, ref_ids: List[int]) -> Set[int]:
    ids = [int(i) for i in ref_ids if i is not None]
    if not ids:
        return set()
    with get_db() as db:
        rows = fetch_all(db.cursor, """
            SELECT ref_id FROM desbloqueos
            WHERE user_id = %s AND tipo = %s AND estado = 'vigente' AND ref_id = ANY(%s)
        """, (user_id, tipo, ids))
    return {r["ref_id"] for r in rows}


def listar_desbloqueos(user_id: int, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 50), 200))
    with get_db() as db:
        rows = fetch_all(db.cursor, """
            SELECT d.id, d.tipo, d.ref_id, d.fuente_credito, d.motivo_gratis, d.estado,
                   d.contacto_telefono, d.contacto_nombre, d.contacto_agencia, d.created_at,
                   p.codigo_propiedad, p.titulo, p.zona, p.ciudad,
                   p.imagen_principal, p.precio, p.tipo_propiedad, p.area_construida,
                   p.habitaciones, p.banos, p.activa,
                   pe.texto_pedido, pe.presupuesto_estimado,
                   r.id AS reporte_id, r.reembolsado,
                   s.estado AS seg_estado, s.nota AS seg_nota, s.recordatorio AS seg_recordatorio,
                   s.updated_at AS seg_updated_at
            FROM desbloqueos d
            LEFT JOIN propiedades p ON d.tipo = 'propiedad' AND p.id = d.ref_id
            LEFT JOIN pedidos pe ON d.tipo = 'pedido' AND pe.id = d.ref_id
            LEFT JOIN reportes_contacto r ON r.desbloqueo_id = d.id
            LEFT JOIN contacto_seguimiento s ON s.desbloqueo_id = d.id
            WHERE d.user_id = %s
            ORDER BY d.created_at DESC
            LIMIT %s OFFSET %s
        """, (user_id, limit, int(offset or 0)))
        total = scalar(db.cursor, "SELECT COUNT(*) FROM desbloqueos WHERE user_id = %s", (user_id,))
    items = []
    for d in rows:
        items.append({
            "desbloqueo_id": d["id"],
            "tipo": d["tipo"],
            "ref_id": d["ref_id"],
            "codigo": d.get("codigo_propiedad") or (f"pedido-{d['ref_id']}" if d["tipo"] == "pedido" else None),
            "titulo": d.get("titulo"),
            "zona": d.get("zona"),
            "ciudad": d.get("ciudad"),
            "estado": d["estado"],
            "cobrado": d["fuente_credito"] != "gratis",
            "fecha": d["created_at"].isoformat() if d.get("created_at") else None,
            "reportado": d.get("reporte_id") is not None,
            "contacto": {"telefono": d.get("contacto_telefono"), "nombre": d.get("contacto_nombre"),
                         "agencia": d.get("contacto_agencia")},
            # Para mostrar el contacto con su inmueble o su pedido (sin datos de contacto)
            "inmueble": {
                "imagen": d.get("imagen_principal"),
                "precio": int(d["precio"]) if d.get("precio") else None,
                "tipo": d.get("tipo_propiedad"),
                "area": float(d["area_construida"]) if d.get("area_construida") else None,
                "habitaciones": d.get("habitaciones"),
                "banos": d.get("banos"),
                "activa": d.get("activa"),
            } if d["tipo"] == "propiedad" else None,
            "pedido": {
                "texto": d.get("texto_pedido"),
                "presupuesto": int(d["presupuesto_estimado"]) if d.get("presupuesto_estimado") else None,
            } if d["tipo"] == "pedido" else None,
            "seguimiento": seguimiento_service.salida(d),
        })
    return {"ok": True, "total": total or 0, "items": items}


# =========================================================================
# Reportes / reembolsos
# =========================================================================

MOTIVOS_REPORTE = {"numero_equivocado", "no_contesta", "no_es_el_agente", "ya_no_disponible", "otro"}


def reportar_invalido(user_id: int, desbloqueo_id: int, motivo: str,
                      detalle: Optional[str] = None) -> Dict[str, Any]:
    """
    Reporta un contacto desbloqueado que no sirve. Si el usuario no ha pasado su
    tope mensual de reembolsos, el crédito se devuelve en el acto; si no, el
    reporte queda para revisión del admin.
    """
    if motivo not in MOTIVOS_REPORTE:
        return _error("motivo_invalido", f"Motivo inválido. Usa uno de: {sorted(MOTIVOS_REPORTE)}.")
    with get_db() as db:
        cur = db.cursor
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK_COBRO, user_id))
        d = fetch_one(cur, """
            SELECT id, tipo, ref_id, estado, fuente_credito, created_at FROM desbloqueos
            WHERE id = %s AND user_id = %s
        """, (desbloqueo_id, user_id))
        if not d:
            return _error("no_encontrado", "No encontré ese contacto desbloqueado.")
        if d["fuente_credito"] == "gratis":
            return _error("no_cobrado", "Ese contacto no te costó ninguna llave; no hay nada que devolver.")
        if d["estado"] != "vigente":
            return _error("ya_reembolsado", "La llave de ese contacto ya te fue devuelta.")
        if scalar(cur, "SELECT 1 FROM reportes_contacto WHERE desbloqueo_id = %s", (desbloqueo_id,)):
            return _error("ya_reportado", "Ya reportaste ese contacto; lo estamos revisando.")
        if d["created_at"] < _ahora() - timedelta(days=DIAS_PARA_REPORTAR):
            return _error("fuera_de_plazo",
                          f"Los contactos se pueden reportar hasta {DIAS_PARA_REPORTAR} días después de desbloquearlos.")

        reembolsar = _reembolsos_este_mes(cur, user_id) < limite_reembolsos_mes()
        cur.execute("""
            INSERT INTO reportes_contacto (desbloqueo_id, user_id, motivo, detalle, reembolsado,
                                           resuelto_at, resolucion)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (desbloqueo_id, user_id, motivo, detalle, reembolsar,
              _ahora() if reembolsar else None, "Reembolso automático" if reembolsar else None))
        if reembolsar:
            cur.execute("UPDATE desbloqueos SET estado = 'reembolsado' WHERE id = %s", (desbloqueo_id,))
        if d["tipo"] == "propiedad" and motivo == "ya_no_disponible":
            # Que la revalidación lo revise primero.
            cur.execute("UPDATE propiedades SET fecha_ultima_validacion = NULL WHERE id = %s", (d["ref_id"],))
        db.conn.commit()

    if reembolsar:
        return {"ok": True, "reembolsado": True,
                "mensaje": "Gracias por avisar. Te devolvimos la llave y vamos a revisar ese contacto."}
    return {"ok": True, "reembolsado": False,
            "mensaje": "Gracias por avisar. Ya usaste las devoluciones automáticas de llaves de este mes; "
                       "el equipo de Fynder revisa tu reporte y te responde."}


# =========================================================================
# Términos y uso justo
# =========================================================================

def aceptar_terminos(user_id: int, version: str = TERMINOS_VERSION) -> Dict[str, Any]:
    with get_db() as db:
        db.cursor.execute("""
            UPDATE chat_users SET terminos_aceptados_at = NOW(), terminos_version = %s
            WHERE id = %s RETURNING terminos_aceptados_at
        """, (version, user_id))
        row = db.cursor.fetchone()
        db.conn.commit()
    if not row:
        return _error("no_encontrado", "Usuario no encontrado.")
    return {"ok": True, "terminos_version": version,
            "terminos_aceptados_at": row["terminos_aceptados_at"].isoformat()}


def registrar_busqueda(user_id: int) -> Dict[str, Any]:
    """Suma una búsqueda al uso justo del día. {permitido, usadas, limite}."""
    with get_db() as db:
        usadas = scalar(db.cursor, f"""
            INSERT INTO uso_diario (user_id, fecha, busquedas)
            VALUES (%s, (NOW() AT TIME ZONE '{TZ}')::date, 1)
            ON CONFLICT (user_id, fecha) DO UPDATE SET busquedas = uso_diario.busquedas + 1
            RETURNING busquedas
        """, (user_id,))
        db.conn.commit()
    limite = limite_busquedas_dia()
    return {"permitido": usadas <= limite, "usadas": usadas, "limite": limite}


# =========================================================================
# Administración
# =========================================================================

def activar_plan(user_id: int, plan_codigo: str, referencia_pago: Optional[str] = None,
                 notas: Optional[str] = None, admin: Optional[str] = None) -> Dict[str, Any]:
    """
    Registra un periodo pagado de 30 días (+5 de gracia). Si el usuario renueva
    antes de que termine su gracia, el periodo nuevo arranca al `fin` del
    anterior (pagar tarde no regala días).
    """
    with get_db() as db:
        res = activar_plan_en(db.cursor, user_id, plan_codigo, referencia_pago, notas, admin)
        db.conn.commit()
    return res


def activar_plan_en(cur, user_id: int, plan_codigo: str, referencia_pago: Optional[str] = None,
                    notas: Optional[str] = None, admin: Optional[str] = None,
                    precio_cop: Optional[int] = None) -> Dict[str, Any]:
    """`activar_plan` dentro de una transacción del caller (no hace commit).
    `precio_cop` registra lo realmente pagado (si no, el precio del plan hoy)."""
    plan = fetch_one(cur, "SELECT * FROM planes WHERE codigo = %s AND activo", (plan_codigo,))
    if not plan or plan_codigo == "prueba":
        raise SuscripcionError(f"Plan inválido: {plan_codigo}")
    if not _usuario(cur, user_id):
        raise SuscripcionError(f"Usuario {user_id} no existe")
    cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK_COBRO, user_id))
    previo = fetch_one(cur, """
        SELECT fin, gracia_hasta FROM suscripciones
        WHERE user_id = %s AND estado = 'activa' AND gracia_hasta > NOW()
        ORDER BY inicio DESC LIMIT 1
    """, (user_id,))
    inicio = max(_ahora(), previo["fin"]) if previo else _ahora()
    fin = inicio + timedelta(days=DIAS_PERIODO)
    cur.execute("""
        INSERT INTO suscripciones (user_id, plan_codigo, desbloqueos_incluidos, precio_cop,
                                   inicio, fin, gracia_hasta, referencia_pago, notas, activada_por)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, inicio, fin, gracia_hasta
    """, (user_id, plan_codigo, plan["desbloqueos_mes"],
          plan["precio_cop"] if precio_cop is None else precio_cop, inicio, fin,
          fin + timedelta(days=DIAS_GRACIA), referencia_pago, notas, admin))
    row = cur.fetchone()
    return {"ok": True, "suscripcion_id": row["id"], "plan": plan_codigo,
            "inicio": row["inicio"].isoformat(), "fin": row["fin"].isoformat(),
            "gracia_hasta": row["gracia_hasta"].isoformat()}


def cancelar_suscripcion(suscripcion_id: int) -> Dict[str, Any]:
    with get_db() as db:
        db.cursor.execute("UPDATE suscripciones SET estado = 'cancelada' WHERE id = %s RETURNING id",
                          (suscripcion_id,))
        ok = db.cursor.fetchone() is not None
        db.conn.commit()
    return {"ok": ok}


def agregar_creditos(user_id: int, cantidad: int, tipo: str = "extra",
                     referencia: Optional[str] = None, admin: Optional[str] = None) -> Dict[str, Any]:
    if tipo not in ("extra", "ajuste"):
        raise SuscripcionError("tipo debe ser 'extra' o 'ajuste'")
    cantidad = int(cantidad)
    if cantidad == 0 or (tipo == "extra" and cantidad < 0):
        raise SuscripcionError("Cantidad inválida")
    with get_db() as db:
        if not _usuario(db.cursor, user_id):
            raise SuscripcionError(f"Usuario {user_id} no existe")
        db.cursor.execute("""
            INSERT INTO creditos_movimientos (user_id, tipo, cantidad, referencia, creado_por)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (user_id, tipo, cantidad, referencia, admin))
        mov = db.cursor.fetchone()["id"]
        db.conn.commit()
    return {"ok": True, "movimiento_id": mov}


def verificar_telefono(user_id: int, verificado: bool = True) -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        cur.execute("""
            UPDATE chat_users SET telefono_verificado = %s,
                   telefono_verificado_at = CASE WHEN %s THEN NOW() ELSE NULL END
            WHERE id = %s RETURNING id
        """, (verificado, verificado, user_id))
        if not cur.fetchone():
            raise SuscripcionError(f"Usuario {user_id} no existe")
        if verificado:
            asegurar_prueba(cur, _usuario(cur, user_id))
        db.conn.commit()
    return {"ok": True, "telefono_verificado": verificado}


def actualizar_plan(codigo: str, **campos) -> Dict[str, Any]:
    permitidos = {"nombre", "precio_cop", "desbloqueos_mes", "activo"}
    sets = {k: v for k, v in campos.items() if k in permitidos and v is not None}
    if not sets:
        raise SuscripcionError("Nada que actualizar")
    asignaciones = ", ".join(f"{k} = %s" for k in sets)
    with get_db() as db:
        db.cursor.execute(f"""
            UPDATE planes SET {asignaciones}, updated_at = NOW() WHERE codigo = %s RETURNING *
        """, (*sets.values(), codigo))
        row = db.cursor.fetchone()
        db.conn.commit()
    if not row:
        raise SuscripcionError(f"Plan {codigo} no existe")
    return {"ok": True, "plan": dict(row)}


def listar_planes() -> List[Dict[str, Any]]:
    with get_db() as db:
        return fetch_all(db.cursor, "SELECT * FROM planes ORDER BY orden")


_FILTROS = {
    "vigentes": "s.id IS NOT NULL AND NOW() < s.fin",
    "gracia": "s.id IS NOT NULL AND s.fin <= NOW() AND NOW() < s.gracia_hasta",
    "vencidas": "s.id IS NOT NULL AND s.gracia_hasta <= NOW()",
    "sin_plan": "s.id IS NULL",
    "todas": "TRUE",
}


def listar_suscripciones(filtro: str = "todas", q: Optional[str] = None,
                         limit: int = 300) -> List[Dict[str, Any]]:
    """Usuarios con su último periodo y saldo (para el admin)."""
    where = _FILTROS.get(filtro, "TRUE")
    params: List[Any] = []
    if q:
        where += " AND (u.nombre ILIKE %s OR u.email ILIKE %s OR u.telefono ILIKE %s)"
        params += [f"%{q}%"] * 3
    with get_db() as db:
        rows = fetch_all(db.cursor, f"""
            SELECT u.id, u.nombre, u.email, u.telefono, u.activo, u.telefono_verificado,
                   u.terminos_aceptados_at, u.origen,
                   s.id AS suscripcion_id, s.plan_codigo, s.inicio, s.fin, s.gracia_hasta,
                   s.desbloqueos_incluidos,
                   (SELECT COUNT(*) FROM desbloqueos d
                     WHERE d.suscripcion_id = s.id AND d.fuente_credito = 'plan'
                       AND d.estado = 'vigente') AS plan_usados,
                   (SELECT COALESCE(SUM(c.cantidad), 0) FROM creditos_movimientos c
                     WHERE c.user_id = u.id)
                   - (SELECT COUNT(*) FROM desbloqueos d
                       WHERE d.user_id = u.id AND d.fuente_credito = 'saldo'
                         AND d.estado = 'vigente') AS saldo,
                   (SELECT COUNT(*) FROM desbloqueos d WHERE d.user_id = u.id) AS total_desbloqueos
            FROM chat_users u
            LEFT JOIN LATERAL (
                SELECT * FROM suscripciones s
                WHERE s.user_id = u.id AND s.estado = 'activa'
                ORDER BY s.inicio DESC LIMIT 1
            ) s ON TRUE
            WHERE {where}
            ORDER BY s.fin DESC NULLS LAST, u.nombre
            LIMIT %s
        """, (*params, int(limit)))
    for r in rows:
        for k in ("inicio", "fin", "gracia_hasta", "terminos_aceptados_at"):
            if r.get(k):
                r[k] = r[k].isoformat()
    return rows


def detalle_usuario(user_id: int) -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        periodos = fetch_all(cur, """
            SELECT * FROM suscripciones WHERE user_id = %s ORDER BY inicio DESC
        """, (user_id,))
        movimientos = fetch_all(cur, """
            SELECT * FROM creditos_movimientos WHERE user_id = %s ORDER BY created_at DESC
        """, (user_id,))
        reportes = fetch_all(cur, """
            SELECT * FROM reportes_contacto WHERE user_id = %s ORDER BY created_at DESC
        """, (user_id,))
    return {"estado": estado(user_id), "periodos": periodos, "movimientos": movimientos,
            "desbloqueos": listar_desbloqueos(user_id, limit=200)["items"], "reportes": reportes}


def listar_reportes(pendientes: bool = True) -> List[Dict[str, Any]]:
    with get_db() as db:
        return fetch_all(db.cursor, f"""
            SELECT r.*, d.tipo, d.ref_id, d.contacto_telefono, d.contacto_nombre,
                   u.nombre AS usuario_nombre, u.email AS usuario_email,
                   p.codigo_propiedad
            FROM reportes_contacto r
            JOIN desbloqueos d ON d.id = r.desbloqueo_id
            JOIN chat_users u ON u.id = r.user_id
            LEFT JOIN propiedades p ON d.tipo = 'propiedad' AND p.id = d.ref_id
            {"WHERE r.resuelto_at IS NULL" if pendientes else ""}
            ORDER BY r.created_at DESC LIMIT 300
        """)


def resolver_reporte(reporte_id: int, reembolsar: bool, resolucion: Optional[str] = None) -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        rep = fetch_one(cur, "SELECT * FROM reportes_contacto WHERE id = %s", (reporte_id,))
        if not rep:
            raise SuscripcionError(f"Reporte {reporte_id} no existe")
        cur.execute("""
            UPDATE reportes_contacto
            SET reembolsado = reembolsado OR %s, resuelto_at = NOW(), resolucion = %s
            WHERE id = %s
        """, (reembolsar, resolucion, reporte_id))
        if reembolsar:
            cur.execute("UPDATE desbloqueos SET estado = 'reembolsado' WHERE id = %s",
                        (rep["desbloqueo_id"],))
        db.conn.commit()
    return {"ok": True, "reembolsado": reembolsar}
