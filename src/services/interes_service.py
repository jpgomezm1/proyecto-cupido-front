"""
Servicio de INTERÉS → embudo (Bloque A del plan de desarrollo).

`registrar_interes()` es el corazón de A3: convierte un "quiero ver el código X"
—venga del MCP (A1), del portal (UI) o de Matías en el admin (A4)— en UNA fila
trazable en `interacciones`, con la punta vendedora (captador) autollenada desde
la propiedad.

Este módulo NO comparte contactos con nadie: solo registra el interés. El envío
de PUNTAS a Hernán (A2) y la verificación de disponibilidad (B1) se orquestan
por encima. El campo `vendedor` que devuelve es para uso interno de esa
orquestación; NUNCA debe retornarse al agente comprador (regla de privacidad:
el contacto de la contraparte jamás se entrega — Hernán es el canal).
"""

import os
import re
from typing import Any, Dict, Optional

from src.services.db import get_db, fetch_one
from src.services.textutils import format_cop, build_share_link
from src.services.whatsapp_sender import enviar_whatsapp, WhatsAppSendError
from src.services.disponibilidad_service import verificar_disponibilidad

# Muchas propiedades scrapeadas traen el "nombre"/"asesor" del captador con basura
# del portal (labels, teléfono enmascarado, "Mostrar número"). Esto lo limpia para
# que las PUNTAS a Hernán (A2) se vean bien.
_LABEL_PREFIX = re.compile(
    r"^\s*(nombre|tel[ée]fono(\s+m[óo]vil)?|m[óo]vil|celular|whatsapp|correo|e-?mail|contacto)\s*:?\s*",
    re.IGNORECASE,
)
_SOLO_TELEFONO = re.compile(r"^[\d\+\*\-\(\)\s\.]{4,}$")


def _limpiar_texto_captador(raw: Optional[str]) -> Optional[str]:
    """Extrae un nombre/agencia legible de un texto de captador scrapeado y ruidoso."""
    if not raw:
        return None
    partes, vistos = [], set()
    for linea in str(raw).replace("\r", "\n").split("\n"):
        s = " ".join(linea.split()).strip()
        s = _LABEL_PREFIX.sub("", s).strip()
        if not s:
            continue
        low = s.lower()
        if ("mostrar" in low or "ver" in low) and ("número" in low or "numero" in low):
            continue
        if _SOLO_TELEFONO.match(s):  # línea que es solo teléfono/máscara
            continue
        if low in vistos:
            continue
        vistos.add(low)
        partes.append(s)
    if not partes:
        return None
    return " · ".join(partes)[:120]


class InteresError(Exception):
    """Error de negocio al registrar un interés (ref inválida, datos faltantes)."""


# Estados del pipeline (ver migración 035_interacciones_flujo.sql)
ESTADO_SELECCIONADO = "Seleccionado"
ESTADO_PUNTAS_ENVIADAS = "Puntas_Enviadas"
ESTADO_VISITA_AGENDADA = "Visita_Agendada"
ESTADO_CERRADO_OK = "Cerrado_Exitoso"
ESTADO_CERRADO_NO = "Cerrado_Sin_Resultado"

_ESTADOS_ABIERTOS = (ESTADO_SELECCIONADO, ESTADO_PUNTAS_ENVIADAS, ESTADO_VISITA_AGENDADA)

FUENTES_VALIDAS = {"MCP", "UI", "WhatsApp"}


def cargar_puntas(cur, propiedad_ref) -> Dict[str, Any]:
    """
    Resuelve la propiedad (por id numérico o `codigo_propiedad`) y arma sus dos
    puntas. La punta vendedora (captador) se autollena desde la propiedad.

    Devuelve {'propiedad': {...}, 'vendedor': {...}} o {'error': str}.
    El bloque 'vendedor' contiene el contacto del captador → uso interno (A2).
    """
    ref = str(propiedad_ref).strip()
    if ref.isdigit():
        where, param = "p.id = %s", int(ref)
    else:
        where, param = "p.codigo_propiedad = %s", ref

    row = fetch_one(cur, f"""
        SELECT
            p.id, p.codigo_propiedad, p.titulo, p.precio, p.zona, p.ciudad,
            p.url, p.activa, p.fuente,
            p.agente_captador_id, p.agente_captador_telefono,
            p.asesor, p.inmobiliaria, p.contacto_responsable,
            a.nombre AS captador_nombre, a.numero_whatsapp AS captador_whatsapp
        FROM propiedades p
        LEFT JOIN agentes a ON a.id = p.agente_captador_id
        WHERE {where}
    """, (param,))

    if not row:
        return {"error": f"No encontré la propiedad '{propiedad_ref}'."}

    tel_vendedor = row.get("agente_captador_telefono") or row.get("contacto_responsable")
    agente_id = row.get("agente_captador_id")
    nombre_registrado = row.get("captador_nombre")

    # Si el captador no está enlazado a `agentes` por id pero sí tenemos su
    # teléfono, intentamos resolverlo por teléfono (últimos 10 dígitos). Esto:
    #  (a) da un nombre registrado limpio, y (b) habilita el contador de cierre.
    if agente_id is None and tel_vendedor:
        a = fetch_one(cur, """
            SELECT id, nombre FROM agentes
            WHERE RIGHT(REGEXP_REPLACE(telefono, '[^0-9]', '', 'g'), 10)
                = RIGHT(REGEXP_REPLACE(%s, '[^0-9]', '', 'g'), 10)
            LIMIT 1
        """, (tel_vendedor,))
        if a:
            agente_id = a["id"]
            nombre_registrado = nombre_registrado or a.get("nombre")

    nombre = _limpiar_texto_captador(nombre_registrado) or _limpiar_texto_captador(row.get("asesor"))
    vendedor = {
        "agente_id": agente_id,
        "telefono": tel_vendedor,
        "nombre": nombre,
        "agencia": _limpiar_texto_captador(row.get("inmobiliaria")),
    }
    propiedad = {
        "id": row["id"],
        "codigo": row.get("codigo_propiedad"),
        "titulo": row.get("titulo"),
        "precio": int(row["precio"]) if row.get("precio") is not None else None,
        "precio_legible": format_cop(row.get("precio")),
        "zona": row.get("zona"),
        "ciudad": row.get("ciudad"),
        "url": row.get("url"),
        "activa": row.get("activa"),
        "fuente": row.get("fuente"),
    }
    return {"propiedad": propiedad, "vendedor": vendedor}


def registrar_interes(*, propiedad_ref, comprador_telefono: str,
                      comprador_id: Optional[int] = None,
                      cliente_ref: Optional[str] = None,
                      preguntas: Optional[str] = None,
                      fuente: str = "MCP",
                      pedido_id: Optional[int] = None,
                      solicitud_mercado_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Registra UN interés en `interacciones` (estado 'Seleccionado') y devuelve el
    registro con ambas puntas. Idempotente por (propiedad, comprador) mientras la
    interacción siga abierta: repetir la acción NO crea filas duplicadas.

    No envía nada ni comparte contactos. Es la base de A1/A4; encima se orquesta
    la verificación (B1) y el envío de PUNTAS (A2).
    """
    if fuente not in FUENTES_VALIDAS:
        raise InteresError(f"Fuente inválida: {fuente!r} (usa {sorted(FUENTES_VALIDAS)}).")
    if not comprador_telefono or not str(comprador_telefono).strip():
        raise InteresError("Falta el teléfono del agente comprador.")

    with get_db() as db:
        datos = cargar_puntas(db.cursor, propiedad_ref)
        if datos.get("error"):
            raise InteresError(datos["error"])
        prop = datos["propiedad"]
        vend = datos["vendedor"]

        # Resolver el agente_id del comprador por teléfono (FK opcional; mejora la
        # trazabilidad y los joins). Si no está en `agentes`, queda en null.
        if comprador_id is None and comprador_telefono:
            ac = fetch_one(db.cursor, """
                SELECT id FROM agentes
                WHERE RIGHT(REGEXP_REPLACE(telefono,'[^0-9]','','g'),10)
                    = RIGHT(REGEXP_REPLACE(%s,'[^0-9]','','g'),10) LIMIT 1
            """, (comprador_telefono,))
            if ac:
                comprador_id = ac["id"]

        # Idempotencia: si ya hay una interacción ABIERTA de este comprador sobre
        # esta propiedad, la reutilizamos (evita spamear a Hernán con duplicados).
        existente = fetch_one(db.cursor, f"""
            SELECT id, estado FROM interacciones
            WHERE propiedad_id = %s
              AND RIGHT(REGEXP_REPLACE(COALESCE(agente_comprador_telefono,''), '[^0-9]', '', 'g'), 10)
                  = RIGHT(REGEXP_REPLACE(%s, '[^0-9]', '', 'g'), 10)
              AND estado IN ({','.join(['%s'] * len(_ESTADOS_ABIERTOS))})
            ORDER BY id DESC LIMIT 1
        """, (prop["id"], comprador_telefono, *_ESTADOS_ABIERTOS))

        if existente:
            return {
                "ok": True,
                "ya_existia": True,
                "interaccion_id": existente["id"],
                "estado": existente["estado"],
                "propiedad": prop,
                "vendedor": vend,
                "preguntas": preguntas,
            }

        db.cursor.execute("""
            INSERT INTO interacciones (
                agente_comprador_id, agente_comprador_telefono,
                propiedad_id,
                agente_vendedor_id, agente_vendedor_telefono,
                estado, fuente, pedido_id, solicitud_mercado_id,
                cliente_ref, preguntas, tipo_propiedad_origen
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, fecha_seleccion
        """, (
            comprador_id, comprador_telefono,
            prop["id"],
            vend.get("agente_id"), vend.get("telefono"),
            ESTADO_SELECCIONADO, fuente, pedido_id, solicitud_mercado_id,
            cliente_ref, preguntas, prop.get("fuente"),
        ))
        r = db.cursor.fetchone()
        interaccion_id = r["id"]
        db.conn.commit()

        db.log_evento(
            tipo_evento="interes_registrado",
            agente_telefono=comprador_telefono,
            propiedad_id=prop["id"],
            interaccion_id=interaccion_id,
            solicitud_id=solicitud_mercado_id,
            datos_evento={"fuente": fuente, "pedido_id": pedido_id,
                          "cliente_ref": cliente_ref,
                          "tiene_preguntas": bool(preguntas)},
        )

    return {
        "ok": True,
        "ya_existia": False,
        "interaccion_id": interaccion_id,
        "estado": ESTADO_SELECCIONADO,
        "propiedad": prop,
        "vendedor": vend,   # uso interno (A2); NUNCA retornar al agente comprador
        "preguntas": preguntas,
    }


# =========================================================================
# A2 · Solicitud PUNTAS → UltraMSG a Hernán
# =========================================================================
# El mensaje lleva el contacto de AMBAS puntas porque su único destinatario es
# HERNÁN, que es el canal (Principio 2). Nunca se retorna a un agente.

def _partes(*xs) -> str:
    """Une con ' · ' los valores no vacíos (para líneas nombre/cel/agencia)."""
    return " · ".join(str(x).strip() for x in xs if x and str(x).strip())


def _punta_comprador(cur, inter: Dict[str, Any]) -> Dict[str, Any]:
    """Arma la punta compradora (agente que expresó interés) + flag Fynder."""
    tel = inter.get("agente_comprador_telefono")
    nombre = None
    if inter.get("agente_comprador_id"):
        a = fetch_one(cur, "SELECT nombre FROM agentes WHERE id=%s", (inter["agente_comprador_id"],))
        nombre = a.get("nombre") if a else None
    if not nombre and tel:
        a = fetch_one(cur, """
            SELECT nombre FROM agentes
            WHERE RIGHT(REGEXP_REPLACE(telefono,'[^0-9]','','g'),10)
                = RIGHT(REGEXP_REPLACE(%s,'[^0-9]','','g'),10) LIMIT 1
        """, (tel,))
        nombre = a.get("nombre") if a else None

    # ¿Es usuario Fynder activo? (tiene cuenta en chat_users)
    fynder_activo = False
    if tel:
        cu = fetch_one(cur, """
            SELECT 1 FROM chat_users
            WHERE activo = TRUE
              AND RIGHT(REGEXP_REPLACE(COALESCE(telefono,''),'[^0-9]','','g'),10)
                = RIGHT(REGEXP_REPLACE(%s,'[^0-9]','','g'),10) LIMIT 1
        """, (tel,))
        fynder_activo = bool(cu)

    return {
        "nombre": _limpiar_texto_captador(nombre) or "(agente sin nombre registrado)",
        "telefono": tel,
        "fynder_activo": fynder_activo,
    }


def _disponibilidad_texto(disp_estado: Optional[str]) -> str:
    if disp_estado == "disponible":
        return "✓ verificada (activa)"
    if disp_estado in ("404", "no_disponible"):
        return f"✗ NO disponible ({disp_estado})"
    return "⚠ por confirmar"


def construir_mensaje_puntas(*, interes_id, fecha, comprador, vendedor, propiedad,
                             link, disp_estado, preguntas=None, cliente_ref=None) -> str:
    """Arma el texto de las PUNTAS para Hernán (formato Anexo A del plan)."""
    flag = "✓ activo" if comprador.get("fynder_activo") else "✗ activar"
    lineas = [
        f"🔗 PUNTAS #{interes_id} · {fecha}".rstrip(),
        "",
        "🟢 PUNTA COMPRADORA (interesado)",
        f"   {_partes(comprador.get('nombre'), comprador.get('telefono'))}   [Fynder: {flag}]",
        "",
        "🔵 PUNTA VENDEDORA (captador)",
        f"   {_partes(vendedor.get('nombre'), vendedor.get('telefono'), vendedor.get('agencia'))}",
        "",
        f"🏠 Propiedad: código {propiedad.get('codigo') or propiedad.get('id')}",
        f"   {_partes(propiedad.get('zona'), propiedad.get('ciudad'), propiedad.get('precio_legible'))}",
    ]
    if link:
        lineas.append(f"   {link}")
    lineas.append(f"   Disponibilidad: {_disponibilidad_texto(disp_estado)}")
    if cliente_ref:
        lineas.append(f"👤 Cliente del comprador: {cliente_ref}")
    if preguntas and preguntas.strip():
        lineas.append(f"❓ Para el dueño (Balde 2): \"{preguntas.strip()}\"")
    else:
        lineas.append("🎯 Motivo: Visita")
    lineas.append("")
    lineas.append("👉 Contactar ambas puntas · confirmar con captador · agendar visita")
    return "\n".join(lineas)


def enviar_puntas(interaccion_id, disponibilidad: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Arma y envía las PUNTAS a Hernán por WhatsApp para una interacción ya
    registrada (A3). Marca la interacción como 'Puntas_Enviadas'. `disponibilidad`
    es el resultado de B1 (opcional); si no viene, usa lo guardado en la fila.

    PRIVACIDAD: el resultado NO incluye contactos — solo estado. El mensaje con
    ambas puntas viaja únicamente a Hernán (el canal).
    """
    destino = os.getenv("HERNAN_WHATSAPP")
    if not destino:
        return {"error": "config_faltante", "mensaje": "Falta HERNAN_WHATSAPP en el entorno."}

    with get_db() as db:
        inter = fetch_one(db.cursor,
            "SELECT * FROM interacciones WHERE id=%s", (interaccion_id,))
        if not inter:
            return {"error": "no_encontrada", "mensaje": f"Interacción {interaccion_id} no existe."}

        datos = cargar_puntas(db.cursor, inter["propiedad_id"])
        if datos.get("error"):
            return {"error": "propiedad_no_encontrada", "mensaje": datos["error"]}
        prop, vend = datos["propiedad"], datos["vendedor"]
        comprador = _punta_comprador(db.cursor, inter)

        disp_estado = (disponibilidad or {}).get("estado") or inter.get("disponibilidad_estado")
        fecha = (inter.get("fecha_seleccion") or "").strftime("%d/%m/%Y %H:%M") \
            if inter.get("fecha_seleccion") else ""
        link = build_share_link(prop["id"], prop.get("titulo"))

        mensaje = construir_mensaje_puntas(
            interes_id=inter["id"], fecha=fecha, comprador=comprador, vendedor=vend,
            propiedad=prop, link=link, disp_estado=disp_estado,
            preguntas=inter.get("preguntas"), cliente_ref=inter.get("cliente_ref"),
        )

        try:
            enviar_whatsapp(destino, mensaje)
        except WhatsAppSendError as e:
            return {"error": "envio_fallido", "mensaje": str(e)}

        db.cursor.execute("""
            UPDATE interacciones
            SET estado = %s,
                fecha_puntas_enviadas = NOW(),
                fecha_cambio_estado = NOW(),
                disponibilidad_estado = COALESCE(%s, disponibilidad_estado)
            WHERE id = %s
        """, (ESTADO_PUNTAS_ENVIADAS, disp_estado, interaccion_id))
        db.conn.commit()

        db.log_evento(
            tipo_evento="puntas_enviadas",
            agente_telefono=inter.get("agente_comprador_telefono"),
            propiedad_id=prop["id"],
            interaccion_id=interaccion_id,
            datos_evento={"disponibilidad": disp_estado, "destino": "hernan"},
        )

    return {
        "ok": True,
        "interaccion_id": interaccion_id,
        "estado": ESTADO_PUNTAS_ENVIADAS,
        "enviado_a_hernan": True,
        "disponibilidad": disp_estado,
    }


# =========================================================================
# A1/A4 · Orquestación: interés → verificar → PUNTAS
# =========================================================================

def orquestar_solicitud(*, propiedad_ref, comprador_telefono, comprador_id=None,
                        cliente_ref=None, preguntas=None, fuente="MCP",
                        pedido_id=None, solicitud_mercado_id=None,
                        verificar: bool = True, enviar: bool = True) -> Dict[str, Any]:
    """
    Flujo completo, reutilizado por A1 (tool MCP) y A4 (admin):
      1) registra el interés (A3, idempotente),
      2) verifica disponibilidad (B1); si el link está caído NO escala a Hernán,
      3) si está vivo, envía las PUNTAS a Hernán (A2).

    No retorna contactos: solo confirmación + código/título del inmueble.
    """
    try:
        reg = registrar_interes(
            propiedad_ref=propiedad_ref, comprador_telefono=comprador_telefono,
            comprador_id=comprador_id, cliente_ref=cliente_ref, preguntas=preguntas,
            fuente=fuente, pedido_id=pedido_id, solicitud_mercado_id=solicitud_mercado_id)
    except InteresError as e:
        return {"ok": False, "error": "no_registrado", "mensaje": str(e)}

    iid = reg["interaccion_id"]
    prop = reg["propiedad"]
    prop_min = {"codigo": prop.get("codigo"), "titulo": prop.get("titulo")}

    # Idempotencia: si ya estaba escalada, no re-enviamos.
    if reg.get("ya_existia") and reg.get("estado") in (ESTADO_PUNTAS_ENVIADAS, ESTADO_VISITA_AGENDADA):
        return {"ok": True, "interaccion_id": iid, "escalado": True, "ya_existia": True,
                "propiedad": prop_min,
                "mensaje": "Ya habíamos pasado esta solicitud a Hernán; está en curso."}

    disp = {"estado": None, "activo": True}
    if verificar:
        disp = verificar_disponibilidad(prop["id"])
        if disp.get("error"):
            disp = {"estado": "desconocido", "activo": True}

    # Inmueble caído → no molestar a Hernán, avisar al agente.
    if not disp.get("activo", True):
        with get_db() as db:
            db.cursor.execute(
                "UPDATE interacciones SET disponibilidad_estado=%s, fecha_cambio_estado=NOW() WHERE id=%s",
                (disp.get("estado"), iid))
            db.conn.commit()
        return {"ok": True, "interaccion_id": iid, "escalado": False,
                "disponibilidad": disp.get("estado"), "propiedad": prop_min,
                "mensaje": ("Ojo: el inmueble parece que ya no está publicado "
                            f"({disp.get('estado')}). No lo escalé a Hernán para no coordinar "
                            "una visita a algo caído; confirma con el captador o busquemos "
                            "alternativas.")}

    if not enviar:
        return {"ok": True, "interaccion_id": iid, "escalado": False,
                "disponibilidad": disp.get("estado"), "propiedad": prop_min,
                "mensaje": "Interés registrado (envío a Hernán diferido)."}

    env = enviar_puntas(iid, disponibilidad=disp)
    if env.get("error"):
        return {"ok": False, "interaccion_id": iid, "error": env.get("error"),
                "mensaje": env.get("mensaje", "No se pudo avisar a Hernán; intenta de nuevo."),
                "disponibilidad": disp.get("estado")}

    return {"ok": True, "interaccion_id": iid, "escalado": True,
            "disponibilidad": disp.get("estado"), "propiedad": prop_min,
            "mensaje": "Listo, Hernán de Fynder coordina la visita y te confirma."}
