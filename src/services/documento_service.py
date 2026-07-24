"""
Documentos de cierre: BORRADOR de promesa de compraventa (Colombia).

Asistente de borrador: el agente/LLM aporta los datos de las partes y los
términos; el inmueble se toma de Fynder. Se genera un documento estructurado
con las cláusulas típicas, claramente marcado como BORRADOR que debe revisar un
abogado/notaría. Fynder NO da asesoría legal.

Guarda el documento en `documentos_generados` (datos sensibles) y expone un
share_id largo y aleatorio para verlo/imprimir.
"""

import secrets
from datetime import datetime
from typing import Any, Dict, Optional

from src.services.db import get_db, fetch_one
from src.services.property_service import get_property
from src.services.textutils import format_cop, normalize_phone

DISCLAIMER = ("BORRADOR generado con Fynder como apoyo. NO constituye asesoría "
              "legal ni un documento definitivo. Debe ser revisado y ajustado por "
              "un abogado y/o la notaría antes de firmarse. Verifique la matrícula "
              "inmobiliaria, linderos y el estado jurídico del inmueble.")

_VACIO = "_______________________"


def _v(x, dinero=False):
    if x is None or (isinstance(x, str) and not x.strip()):
        return _VACIO
    if dinero:
        try:
            return format_cop(float(x))
        except (TypeError, ValueError):
            return str(x)
    return str(x)


def crear_promesa(property_id, agente_telefono: str, comprador: Dict[str, Any],
                  vendedor: Dict[str, Any], terminos: Dict[str, Any],
                  agente_nombre: Optional[str] = None) -> Dict[str, Any]:
    """
    Crea un borrador de promesa de compraventa y lo guarda. Devuelve el link.
    `comprador`/`vendedor`: {nombre, cedula, domicilio}. `terminos`: precio_total,
    arras, cuota_inicial, forma_pago, plazo_escrituracion_dias, notaria,
    matricula_inmobiliaria, fecha_entrega, ciudad_firma.
    """
    with get_db() as db:
        p = get_property(db.cursor, property_id)
        if not p:
            return {"error": "Propiedad no encontrada"}

        snapshot = {
            "id": p["id"], "titulo": p.get("titulo"),
            "tipo": p.get("tipo_propiedad"), "ciudad": p.get("ciudad"), "zona": p.get("zona"),
            "direccion": p.get("direccion"), "area": p.get("area_construida"),
            "habitaciones": p.get("habitaciones"), "banos": p.get("banos"),
            "parqueaderos": p.get("parqueaderos"), "estrato": p.get("estrato"),
            "precio_lista": p.get("precio"),
        }
        datos = {
            "comprador": comprador or {}, "vendedor": vendedor or {},
            "terminos": terminos or {}, "inmueble": snapshot,
            "agente_nombre": agente_nombre,
        }

        share_id = secrets.token_urlsafe(24)
        db.cursor.execute("""
            INSERT INTO documentos_generados (share_id, tipo, propiedad_id, agente_telefono, datos)
            VALUES (%s, 'promesa_compraventa', %s, %s, %s)
        """, (share_id, p["id"], agente_telefono, __import__("json").dumps(datos, ensure_ascii=False, default=str)))
        db.conn.commit()

        # D1 · Señal PASIVA de cierre (Capa 2 anti-salto): generar la promesa es
        # evidencia de que el negocio se está cerrando dentro de Fynder. Solo
        # dejamos el evento; NO cerramos ninguna interacción automáticamente (no
        # sabemos con certeza cuál corresponde y una atribución errónea es peor).
        db.log_evento(
            tipo_evento="promesa_compraventa_generada",
            agente_telefono=agente_telefono,
            propiedad_id=p["id"],
            datos_evento={
                "senal": "cierre",
                "share_id": share_id,
                "comprador": (comprador or {}).get("nombre"),
                "vendedor": (vendedor or {}).get("nombre"),
                "precio": (terminos or {}).get("precio_total") or p.get("precio"),
            },
        )

    import os
    base = os.getenv("FYNDER_FRONTEND_URL", "https://fyndercol.netlify.app").rstrip("/")
    return {
        "ok": True,
        "share_id": share_id,
        "link": f"{base}/documento/{share_id}",
        "mensaje": "Borrador de promesa de compraventa listo. Ábrelo, revísalo con un abogado y descárgalo en PDF (Imprimir → Guardar como PDF).",
        "disclaimer": DISCLAIMER,
    }


def get_documento(share_id: str) -> Dict[str, Any]:
    """Recupera un documento para renderizarlo (para el frontend)."""
    with get_db() as db:
        row = fetch_one(db.cursor,
            "SELECT tipo, datos, created_at FROM documentos_generados WHERE share_id=%s", (share_id,))
    if not row:
        return {"error": "Documento no encontrado"}
    datos = row["datos"] if isinstance(row["datos"], dict) else __import__("json").loads(row["datos"])
    if row["tipo"] == "promesa_compraventa":
        return {"tipo": row["tipo"], "documento": _render_promesa(datos, row.get("created_at"))}
    return {"error": "Tipo de documento no soportado"}


def _render_promesa(d: Dict[str, Any], created_at) -> Dict[str, Any]:
    """Arma el contenido estructurado de la promesa (título, cláusulas, campos)."""
    c = d.get("comprador", {})
    v = d.get("vendedor", {})
    t = d.get("terminos", {})
    inm = d.get("inmueble", {})

    _MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
              "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    fecha = (f"{created_at.day} de {_MESES[created_at.month - 1]} de {created_at.year}"
             if created_at else _VACIO)
    ciudad_firma = _v(t.get("ciudad_firma") or inm.get("ciudad"))

    dir_inmueble = _v(inm.get("direccion") or (f"{inm.get('zona') or ''}, {inm.get('ciudad') or ''}".strip(", ")))
    area = f'{inm.get("area"):.0f} m²' if inm.get("area") else _VACIO

    precio = t.get("precio_total") or inm.get("precio_lista")

    clausulas = [
        ("PRIMERA — OBJETO", (
            f"EL PROMITENTE VENDEDOR promete vender y EL PROMITENTE COMPRADOR promete comprar el "
            f"inmueble ubicado en {dir_inmueble}, de tipo {_v(inm.get('tipo'))}, con un área aproximada "
            f"de {area}, identificado con MATRÍCULA INMOBILIARIA No. {_v(t.get('matricula_inmobiliaria'))}, "
            f"con sus anexidades, usos, costumbres y servidumbres.")),
        ("SEGUNDA — PRECIO", (
            f"El precio total de la compraventa es la suma de {_v(precio, dinero=True)}, que EL PROMITENTE "
            f"COMPRADOR pagará así: a título de arras/parte del precio {_v(t.get('arras'), dinero=True)} "
            f"a la firma de esta promesa; cuota inicial {_v(t.get('cuota_inicial'), dinero=True)}; y el saldo "
            f"según la siguiente forma de pago: {_v(t.get('forma_pago'))}.")),
        ("TERCERA — ESCRITURACIÓN", (
            f"La escritura pública de compraventa se otorgará en la Notaría {_v(t.get('notaria'))} de "
            f"{ciudad_firma}, dentro de los {_v(t.get('plazo_escrituracion_dias'))} días siguientes a la "
            f"firma de esta promesa.")),
        ("CUARTA — ENTREGA", (
            f"EL PROMITENTE VENDEDOR entregará el inmueble a EL PROMITENTE COMPRADOR el "
            f"{_v(t.get('fecha_entrega'))}, a paz y salvo por todo concepto (servicios públicos, "
            f"administración e impuestos).")),
        ("QUINTA — SANEAMIENTO", (
            "EL PROMITENTE VENDEDOR declara que el inmueble se encuentra libre de gravámenes, embargos, "
            "pleitos pendientes, condiciones resolutorias y limitaciones de dominio, y se obliga al "
            "saneamiento de ley.")),
        ("SEXTA — CLÁUSULA PENAL", (
            "La parte que incumpla las obligaciones de esta promesa pagará a la otra, a título de cláusula "
            f"penal, la suma de {_v(t.get('clausula_penal'), dinero=True)}, sin perjuicio del cumplimiento "
            "de la obligación principal.")),
        ("SÉPTIMA — GASTOS", (
            "Los gastos de escrituración se pagarán por partes iguales; los impuestos de retención y "
            "beneficencia por EL PROMITENTE VENDEDOR, y los de registro por EL PROMITENTE COMPRADOR, "
            "salvo acuerdo distinto de las partes.")),
    ]

    partes = {
        "vendedor": {"rol": "PROMITENTE VENDEDOR", "nombre": _v(v.get("nombre")),
                     "cedula": _v(v.get("cedula")), "domicilio": _v(v.get("domicilio"))},
        "comprador": {"rol": "PROMITENTE COMPRADOR", "nombre": _v(c.get("nombre")),
                      "cedula": _v(c.get("cedula")), "domicilio": _v(c.get("domicilio"))},
    }

    return {
        "titulo": "PROMESA DE COMPRAVENTA",
        "encabezado": (
            f"En la ciudad de {ciudad_firma}, a {fecha}, entre los suscritos: por una parte "
            f"{partes['vendedor']['nombre']}, identificado(a) con cédula de ciudadanía No. "
            f"{partes['vendedor']['cedula']}, domiciliado(a) en {partes['vendedor']['domicilio']}, quien "
            f"obra como PROMITENTE VENDEDOR; y por la otra {partes['comprador']['nombre']}, "
            f"identificado(a) con cédula No. {partes['comprador']['cedula']}, domiciliado(a) en "
            f"{partes['comprador']['domicilio']}, quien obra como PROMITENTE COMPRADOR, hemos acordado "
            f"celebrar la presente PROMESA DE COMPRAVENTA, que se regirá por las siguientes cláusulas:"),
        "clausulas": [{"titulo": ti, "texto": tx} for ti, tx in clausulas],
        "partes": partes,
        "ciudad_firma": ciudad_firma,
        "fecha": fecha,
        "disclaimer": DISCLAIMER,
        "campos_faltantes": _faltantes(t, c, v),
    }


def _faltantes(t, c, v):
    """Lista de datos que el agente aún debe completar (para que el LLM los pida)."""
    faltan = []
    checks = [
        (t.get("matricula_inmobiliaria"), "matrícula inmobiliaria del inmueble"),
        (c.get("nombre"), "nombre del comprador"), (c.get("cedula"), "cédula del comprador"),
        (v.get("nombre"), "nombre del vendedor"), (v.get("cedula"), "cédula del vendedor"),
        (t.get("precio_total"), "precio total acordado"),
        (t.get("forma_pago"), "forma de pago"),
        (t.get("notaria"), "notaría"),
    ]
    for val, etiqueta in checks:
        if val is None or (isinstance(val, str) and not val.strip()):
            faltan.append(etiqueta)
    return faltan
