"""
Correos transaccionales de Fynder para el agente (Resend), con la marca.

Momentos:
  - bienvenida            al crear la cuenta en la web
  - pago_aprobado         el plan quedó activo (comprobante con llaves y vencimiento)
  - pago_rechazado        el pago no pasó (no se cobró nada; reintentar)
  - plan_por_vencer       3 días antes del fin del periodo (job diario del worker)
  - plan_vencido          al entrar en los días de gracia (job diario del worker)
  - cuenta_eliminada      confirmación de que la cuenta se cerró
  - soporte_recibido      al agente: recibimos tu mensaje
  - soporte_nuevo         al equipo: llegó un mensaje de soporte
  - activación (job del worker, una vez por agente):
      act_verifica          ~1 día después de registrarse sin verificar el celular
      act_primera_busqueda  verificado hace 2+ días y aún no ha buscado nada
      act_llaves_esperando  busca pero en 5+ días no ha abierto ningún contacto
      act_sin_llaves        gastó sus llaves y no tiene plan

Diseño: HTML de tablas con estilos en línea (Gmail, Outlook, Apple Mail), sin
WebP (los íconos van en PNG en {FRONTEND}/email/). Cada correo trae su versión
en texto plano.

El envío nunca rompe el flujo que lo dispara: corre en un hilo aparte y, si
Resend falla o no hay llave, solo queda en el log. Los correos programados se
registran en `correos_enviados` para no repetirse.

Config (env): RESEND_API_KEY, FYNDER_EMAIL_FROM (remitente; por defecto el
dominio verificado de irrelevant), FYNDER_SOPORTE_EMAIL (buzón del equipo),
FYNDER_FRONTEND_URL.
"""

import html
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import resend

from src.services.db import get_db, fetch_all

TINTA = "#0B100E"
MENTA = "#2AE38C"
MENTA_CLARA = "#5DFAAB"
CORAL = "#FF7A59"
ORO = "#F5B820"
FONDO = "#F4F3EE"
TEXTO = "#1A1A1A"
SUAVE = "#6B6B6B"
FUENTE = "'Poppins','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif"

ICONO_PLAN = {"basico": "visita", "medio": "negocio", "pro": "cierre"}
METODO = {"CARD": "Tarjeta", "PSE": "PSE", "NEQUI": "Nequi", "BANCOLOMBIA_TRANSFER": "Bancolombia",
          "BANCOLOMBIA_QR": "QR Bancolombia", "DAVIPLATA": "Daviplata"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


# ---------------------------------------------------------------------------
# Config y utilidades
# ---------------------------------------------------------------------------

def _frontend() -> str:
    return os.getenv("FYNDER_FRONTEND_URL", "https://getfynder.com").rstrip("/")


def _dominios_relleno() -> set:
    """Dominios de las cuentas precargadas (correos inventados): nunca se les escribe."""
    return {d.strip().lower() for d in os.getenv("CORREO_DOMINIOS_RELLENO", "fynder.co,fynder.com").split(",") if d.strip()}


def destinatario_real(email: Optional[str]) -> bool:
    email = (email or "").strip().lower()
    if "@" not in email or email.endswith(".invalid"):
        return False
    return email.rsplit("@", 1)[1] not in _dominios_relleno()


def _remitente() -> str:
    return os.getenv("FYNDER_EMAIL_FROM", "Fynder <hola@updates.stayirrelevant.com>")


def buzon_soporte() -> str:
    return os.getenv("FYNDER_SOPORTE_EMAIL", "jpgomez@stayirrelevant.com")


def _img(nombre: str) -> str:
    return f"{_frontend()}/email/{nombre}.png"


def _e(texto: Any) -> str:
    return html.escape(str(texto if texto is not None else ""))


def _primer_nombre(nombre: Optional[str]) -> str:
    return (nombre or "").strip().split(" ")[0] or "agente"


def _pesos(n: Any) -> str:
    try:
        return "$" + f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def _fecha(valor: Any) -> str:
    if not valor:
        return "—"
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return valor
    return f"{valor.day} de {MESES[valor.month - 1]} de {valor.year}"


def _llaves(n: Any) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "llaves"
    return f"{n} {'llave' if n == 1 else 'llaves'}"


# ---------------------------------------------------------------------------
# Plantilla
# ---------------------------------------------------------------------------

def _boton(texto: str, url: str, fondo: str = MENTA, color: str = TINTA) -> str:
    return f"""
<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 auto;">
  <tr><td align="center" bgcolor="{fondo}" style="border-radius:12px;">
    <a href="{_e(url)}" target="_blank" style="display:inline-block;padding:14px 26px;font-family:{FUENTE};font-size:15px;font-weight:600;color:{color};text-decoration:none;border-radius:12px;">{_e(texto)}</a>
  </td></tr>
</table>"""


def _filas(datos: List[Tuple[str, str]]) -> str:
    """Tabla clave → valor (comprobantes, detalles)."""
    filas = "".join(f"""
    <tr>
      <td style="padding:10px 0;border-bottom:1px solid #EEECE6;font-family:{FUENTE};font-size:14px;color:{SUAVE};">{_e(k)}</td>
      <td align="right" style="padding:10px 0;border-bottom:1px solid #EEECE6;font-family:{FUENTE};font-size:14px;font-weight:600;color:{TEXTO};">{v}</td>
    </tr>""" for k, v in datos)
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{filas}</table>'


def _pasos(items: List[Tuple[str, str, str]]) -> str:
    """Lista con ícono: (imagen, título, texto)."""
    filas = "".join(f"""
    <tr>
      <td width="52" valign="top" style="padding:10px 14px 10px 0;"><img src="{_img(img)}" width="44" height="44" alt="" style="display:block;border:0;" /></td>
      <td valign="top" style="padding:10px 0;font-family:{FUENTE};">
        <div style="font-size:15px;font-weight:600;color:{TEXTO};">{_e(t)}</div>
        <div style="font-size:14px;line-height:1.5;color:{SUAVE};margin-top:2px;">{_e(d)}</div>
      </td>
    </tr>""" for img, t, d in items)
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{filas}</table>'


def _parrafo(texto_html: str) -> str:
    return f'<p style="margin:0 0 14px;font-family:{FUENTE};font-size:15px;line-height:1.6;color:{TEXTO};">{texto_html}</p>'


def _layout(*, preheader: str, icono: str, eyebrow: str, titulo: str, intro: str,
            cuerpo: str = "", cta: Optional[Tuple[str, str]] = None, acento: str = MENTA_CLARA) -> str:
    """Correo completo: logo, héroe en tinta con el ícono, cuerpo blanco y pie."""
    boton = f'<div style="padding:8px 0 4px;">{_boton(*cta)}</div>' if cta else ""
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>{_e(titulo)}</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;600&family=Inter:wght@400;600&display=swap" rel="stylesheet">
</head>
<body style="margin:0;padding:0;background:{FONDO};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{_e(preheader)}&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{FONDO}">
<tr><td align="center" style="padding:28px 12px;">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;">
    <tr><td style="padding:0 6px 18px;"><img src="{_img('logo-negro')}" height="22" alt="Fynder" style="display:block;border:0;height:22px;width:auto;" /></td></tr>
    <tr><td bgcolor="{TINTA}" style="border-radius:24px 24px 0 0;padding:36px 32px 30px;background:{TINTA};background-image:radial-gradient(circle at 50% 0%,rgba(93,250,171,0.22),rgba(11,16,14,0) 60%);" align="center">
      <img src="{_img(icono)}" width="96" height="96" alt="" style="display:block;border:0;margin:0 auto 18px;" />
      <div style="font-family:{FUENTE};font-size:11px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:{acento};">{_e(eyebrow)}</div>
      <h1 style="margin:10px 0 0;font-family:{FUENTE};font-size:28px;line-height:1.15;font-weight:600;color:#FFFFFF;">{_e(titulo)}</h1>
      <p style="margin:12px auto 0;max-width:440px;font-family:{FUENTE};font-size:15px;line-height:1.6;color:#B9C2BD;">{intro}</p>
    </td></tr>
    <tr><td bgcolor="#FFFFFF" style="border-radius:0 0 24px 24px;padding:28px 32px 32px;">
      {cuerpo}
      {boton}
    </td></tr>
    <tr><td align="center" style="padding:22px 16px 0;font-family:{FUENTE};font-size:12px;line-height:1.6;color:{SUAVE};">
      ¿Dudas? Responde este correo o escríbenos desde <a href="{_frontend()}/chat/cuenta/ayuda" style="color:{TEXTO};">Ayuda</a>.<br>
      Fynder · Medellín, Colombia · <a href="{_frontend()}/terminos" style="color:{SUAVE};">Términos y datos</a><br>
      <span style="color:#A3A3A3;">Recibes este correo porque tienes una cuenta en Fynder.</span>
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


# ---------------------------------------------------------------------------
# Envío
# ---------------------------------------------------------------------------

def _enviar_ya(para: str, asunto: str, html_: str, texto: str, etiqueta: str,
               responder_a: Optional[str] = None) -> bool:
    resend.api_key = resend.api_key or os.getenv("RESEND_API_KEY", "")
    if not resend.api_key or not destinatario_real(para):
        print(f"[CORREO] Omitido {etiqueta}: sin RESEND_API_KEY o sin destinatario real")
        return False
    try:
        params: Dict[str, Any] = {"from": _remitente(), "to": [para], "subject": asunto, "html": html_,
                                  "text": texto, "reply_to": responder_a or buzon_soporte(),
                                  "tags": [{"name": "tipo", "value": etiqueta}]}
        resend.Emails.send(params)
        print(f"[CORREO] {etiqueta} enviado")
        return True
    except Exception as e:  # noqa: BLE001 — un correo nunca rompe el flujo
        print(f"[CORREO] Error enviando {etiqueta}: {e}")
        return False


def enviar(para: str, asunto: str, html_: str, texto: str, etiqueta: str,
           responder_a: Optional[str] = None, esperar: bool = False) -> None:
    """Envía en segundo plano (o en línea con `esperar`, para jobs y pruebas)."""
    if esperar:
        _enviar_ya(para, asunto, html_, texto, etiqueta, responder_a)
        return
    threading.Thread(target=_enviar_ya, args=(para, asunto, html_, texto, etiqueta, responder_a),
                     daemon=True).start()


# ---------------------------------------------------------------------------
# Correos
# ---------------------------------------------------------------------------

def bienvenida(nombre: str, email: str, **kw) -> None:
    n = _primer_nombre(nombre)
    cuerpo = _parrafo(f"Hola {_e(n)}, ya tienes tu cuenta. Fynder cruza lo que capta y lo que busca la red de "
                      "agentes y te muestra el negocio que encaja: el comprador para tu inmueble y el inmueble para tu cliente.") + \
        _pasos([
            ("verificado", "1. Verifica tu celular", "Te llega un código por WhatsApp y recibes 2 llaves de prueba para abrir contactos."),
            ("findy-busca", "2. Pregúntale a Findy", "Escribe lo que busca tu cliente, como se lo dirías a un colega."),
            ("llave", "3. Abre el contacto con una llave", "Hablas directo con quien tiene el inmueble o el cliente."),
        ])
    html_ = _layout(preheader="Tu cuenta está lista. Verifica tu celular y estrena 2 llaves.",
                    icono="findy-saludo", eyebrow="Bienvenido a Fynder", titulo=f"¡Hola, {n}! Ya eres parte de la red",
                    intro="El negocio que buscas ya existe. Encuéntralo antes que los demás.",
                    cuerpo=cuerpo, cta=("Entrar a Fynder", f"{_frontend()}/chat/bienvenida"))
    texto = (f"¡Hola, {n}! Tu cuenta de Fynder está lista.\n\n"
             "1. Verifica tu celular y recibe 2 llaves de prueba.\n2. Pregúntale a Findy lo que busca tu cliente.\n"
             f"3. Abre el contacto con una llave.\n\nEntra: {_frontend()}/chat/bienvenida")
    enviar(email, f"Bienvenido a Fynder, {n} 🔑", html_, texto, "bienvenida", **kw)


def pago_aprobado(nombre: str, email: str, pago: Dict[str, Any], **kw) -> None:
    if pago.get("tipo") == "paquete":
        return llave_comprada(nombre, email, pago, **kw)
    if pago.get("tipo") == "fotos":
        return fotos_compradas(nombre, email, pago, **kw)
    n = _primer_nombre(nombre)
    plan = pago.get("plan_nombre") or "tu plan"
    llaves = _llaves(pago.get("llaves"))
    cuerpo = _parrafo(f"{_e(n)}, recibimos tu pago y tu plan <b>{_e(plan)}</b> ya está activo. "
                      f"Tienes <b>{_e(llaves)}</b> para abrir contactos hasta el <b>{_e(_fecha(pago.get('vence')))}</b>.") + \
        f'<div style="margin:18px 0 22px;padding:18px 20px;border:1px dashed #DAD7CE;border-radius:16px;">' \
        f'<div style="font-family:{FUENTE};font-size:11px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:{SUAVE};margin-bottom:6px;">Comprobante</div>' + \
        _filas([("Plan", f"{_e(plan)} · {_e(llaves)}"), ("Valor", _e(_pesos(pago.get("monto_cop")))),
                ("Medio de pago", _e(METODO.get(pago.get("metodo") or "", pago.get("metodo") or "—"))),
                ("Fecha", _e(_fecha(pago.get("creado")))), ("Activo hasta", _e(_fecha(pago.get("vence")))),
                ("Referencia", f'<span style="font-family:monospace;font-size:13px;">{_e(pago.get("referencia"))}</span>')]) + \
        "</div>" + _parrafo('<span style="color:#6B6B6B;font-size:13px;">Procesado por Wompi (Bancolombia). '
                            "Fynder no ve ni guarda los datos de tu tarjeta.</span>")
    html_ = _layout(preheader=f"Tu plan {plan} está activo: {llaves} para abrir contactos.",
                    icono=ICONO_PLAN.get(pago.get("plan") or "", "llave"), eyebrow="Pago aprobado",
                    titulo=f"Tu plan {plan} está activo", intro=f"Tienes {_e(llaves)} listas para usar.",
                    cuerpo=cuerpo, cta=("Usar mis llaves", f"{_frontend()}/chat/mercado"))
    texto = (f"{n}, tu plan {plan} está activo: {llaves} hasta el {_fecha(pago.get('vence'))}.\n"
             f"Valor: {_pesos(pago.get('monto_cop'))} · Ref. {pago.get('referencia')}\n\n{_frontend()}/chat/mercado")
    enviar(email, f"✅ Tu plan {plan} está activo", html_, texto, "pago_aprobado", **kw)


def fotos_compradas(nombre: str, email: str, pago: Dict[str, Any], **kw) -> None:
    """Paquete de fotos con IA: se suman al cupo y no vencen."""
    n = _primer_nombre(nombre)
    fotos = f"{pago.get('fotos') or ''} fotos con IA".strip()
    comprobante = (
        f'<div style="margin:18px 0 22px;padding:18px 20px;border:1px dashed #DAD7CE;border-radius:16px;">'
        f'<div style="font-family:{FUENTE};font-size:11px;font-weight:600;letter-spacing:2px;text-transform:uppercase;'
        f'color:{SUAVE};margin-bottom:6px;">Comprobante</div>'
        + _filas([("Compra", _e(fotos)), ("Valor", _e(_pesos(pago.get("monto_cop")))),
                  ("Medio de pago", _e(METODO.get(pago.get("metodo") or "", pago.get("metodo") or "—"))),
                  ("Fecha", _e(_fecha(pago.get("creado")))),
                  ("Referencia", f'<span style="font-family:monospace;font-size:13px;">{_e(pago.get("referencia"))}</span>')])
        + "</div>"
    )
    cuerpo = (
        _parrafo(f"{_e(n)}, recibimos tu pago: <b>{_e(fotos)}</b> más para dejar las fotos de tus inmuebles "
                 "como de fotógrafo profesional. Se usan después del cupo de tu plan y no vencen.")
        + comprobante
        + _parrafo('<span style="color:#6B6B6B;font-size:13px;">Procesado por Wompi (Bancolombia). '
                   "Fynder no ve ni guarda los datos de tu tarjeta.</span>")
    )
    html_ = _layout(preheader=f"{fotos} más en tu cupo. No vencen.", icono="findy-celebra", eyebrow="Pago aprobado",
                    titulo="Tus fotos con IA están listas", intro=f"Tienes {_e(fotos)} más.",
                    cuerpo=cuerpo, cta=("Mejorar mis fotos", f"{_frontend()}/chat/mis-propiedades"))
    texto = (f"{n}, tu compra está lista: {fotos} más (no vencen).\n"
             f"Valor: {_pesos(pago.get('monto_cop'))} · Ref. {pago.get('referencia')}\n\n{_frontend()}/chat/mis-propiedades")
    enviar(email, "✅ Tus fotos con IA están listas", html_, texto, "pago_aprobado", **kw)


def llave_comprada(nombre: str, email: str, pago: Dict[str, Any], **kw) -> None:
    """Compra de llaves sueltas: se suman al saldo y no vencen."""
    n = _primer_nombre(nombre)
    llaves = _llaves(pago.get("llaves"))
    comprobante = (
        f'<div style="margin:18px 0 22px;padding:18px 20px;border:1px dashed #DAD7CE;border-radius:16px;">'
        f'<div style="font-family:{FUENTE};font-size:11px;font-weight:600;letter-spacing:2px;text-transform:uppercase;'
        f'color:{SUAVE};margin-bottom:6px;">Comprobante</div>'
        + _filas([("Compra", _e(llaves)), ("Valor", _e(_pesos(pago.get("monto_cop")))),
                  ("Medio de pago", _e(METODO.get(pago.get("metodo") or "", pago.get("metodo") or "—"))),
                  ("Fecha", _e(_fecha(pago.get("creado")))),
                  ("Referencia", f'<span style="font-family:monospace;font-size:13px;">{_e(pago.get("referencia"))}</span>')])
        + "</div>"
    )
    cuerpo = (
        _parrafo(f"{_e(n)}, recibimos tu pago: <b>{_e(llaves)}</b> más en tu saldo, listas para abrir "
                 "un contacto. Las llaves sueltas no vencen.")
        + comprobante
        + _parrafo('<span style="color:#6B6B6B;font-size:13px;">Procesado por Wompi (Bancolombia). '
                   "Fynder no ve ni guarda los datos de tu tarjeta.</span>")
    )
    html_ = _layout(preheader=f"{llaves} más en tu saldo. No vencen.", icono="llave", eyebrow="Pago aprobado",
                    titulo="Tu llave ya está lista", intro=f"Tienes {_e(llaves)} más para abrir contactos.",
                    cuerpo=cuerpo, cta=("Usar mi llave", f"{_frontend()}/chat/mercado"))
    texto = (f"{n}, tu compra está lista: {llaves} más en tu saldo (no vencen).\n"
             f"Valor: {_pesos(pago.get('monto_cop'))} · Ref. {pago.get('referencia')}\n\n{_frontend()}/chat/mercado")
    enviar(email, "✅ Tu llave ya está lista", html_, texto, "pago_aprobado", **kw)


def resumen_alertas(nombre: str, email: str, alertas: List[Dict[str, Any]], **kw) -> None:
    """Lo nuevo para los clientes del agente y los cambios de precio de lo que guardó."""
    n = _primer_nombre(nombre)
    nuevos = [a for a in alertas if a["tipo"] == "nuevo_inmueble"]
    precios = [a for a in alertas if a["tipo"] != "nuevo_inmueble"]

    def tarjeta(a: Dict[str, Any]) -> str:
        p = a.get("propiedad") or {}
        url = f"{_frontend()}/chat/mercado?p={p.get('slug') or p.get('id')}"
        foto = (f'<img src="{_e(p["imagen_principal"])}" width="88" height="66" alt="" '
                f'style="display:block;border:0;border-radius:10px;object-fit:cover;" />') if p.get("imagen_principal") else ""
        color = "#088650" if a["tipo"] == "baja_precio" else TEXTO
        return (f'<tr><td width="100" valign="top" style="padding:12px 12px 12px 0;"><a href="{_e(url)}">{foto}</a></td>'
                f'<td valign="top" style="padding:12px 0;font-family:{FUENTE};border-bottom:1px solid #EEECE6;">'
                f'<a href="{_e(url)}" style="font-size:15px;font-weight:600;color:{color};text-decoration:none;">{_e(a["titulo"])}</a>'
                f'<div style="font-size:13px;line-height:1.5;color:{SUAVE};margin-top:3px;">{_e(a["detalle"])}</div>'
                f'</td></tr>')

    def bloque(titulo: str, items: List[Dict[str, Any]]) -> str:
        if not items:
            return ""
        filas = "".join(tarjeta(a) for a in items[:8])
        mas = (f'<div style="font-family:{FUENTE};font-size:13px;color:{SUAVE};padding-top:8px;">'
               f'Y {len(items) - 8} más en la app.</div>') if len(items) > 8 else ""
        return (f'<div style="font-family:{FUENTE};font-size:11px;font-weight:600;letter-spacing:2px;text-transform:uppercase;'
                f'color:{SUAVE};margin:18px 0 4px;">{_e(titulo)}</div>'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{filas}</table>{mas}')

    clientes = sorted({a["cliente"]["nombre"] for a in nuevos if a.get("cliente")})
    para = (", ".join(clientes[:3]) + (" y otros" if len(clientes) > 3 else "")) if clientes else ""
    if nuevos:
        intro = f"Entraron {len(nuevos)} {'inmueble' if len(nuevos) == 1 else 'inmuebles'} para {_e(para)}."
    else:
        intro = f"{len(precios)} {'cambio' if len(precios) == 1 else 'cambios'} de precio en lo que guardaste."
    cuerpo = (_parrafo(f"{_e(n)}, esto es lo nuevo desde tu último resumen.")
              + bloque("Para tus clientes", nuevos) + bloque("Cambios de precio", precios)
              + _parrafo('<span style="color:#6B6B6B;font-size:12px;">Puedes apagar estos correos en Mi cuenta → Perfil.</span>'))
    html_ = _layout(preheader=intro, icono="findy-busca", eyebrow="Alertas de Fynder",
                    titulo="Novedades para tus clientes" if nuevos else "Cambios de precio",
                    intro=intro, cuerpo=cuerpo, cta=("Verlas en Fynder", f"{_frontend()}/chat/clientes"))
    lineas = [f"- {a['titulo']} ({a['detalle']})" for a in alertas[:16]]
    texto = f"{n}, esto es lo nuevo en Fynder:\n\n" + "\n".join(lineas) + f"\n\n{_frontend()}/chat/clientes"
    if nuevos:
        asunto = f"🏠 {len(nuevos)} {'opción nueva' if len(nuevos) == 1 else 'opciones nuevas'} para tus clientes"
    else:
        asunto = f"💲 {len(precios)} {'cambio' if len(precios) == 1 else 'cambios'} de precio en lo que guardaste"
    enviar(email, asunto, html_, texto, "resumen_alertas", **kw)


def pago_rechazado(nombre: str, email: str, pago: Dict[str, Any], **kw) -> None:
    n = _primer_nombre(nombre)
    plan = pago.get("plan_nombre") or "tu plan"
    if pago.get("tipo") == "paquete":
        plan = "Llave suelta"
    cuerpo = _parrafo(f"{_e(n)}, el pago de <b>{_e(plan)}</b> por {_e(_pesos(pago.get('monto_cop')))} no se completó "
                      "y <b>no se te cobró nada</b>. Suele pasar por fondos o cupo, o porque el banco pidió una confirmación.") + \
        _pasos([("findy-piensa", "Prueba otro medio", "PSE, Nequi, otra tarjeta o el botón Bancolombia."),
                ("renovacion", "Confirma en tu banco", "Algunos bancos piden autorizar compras en línea.")])
    html_ = _layout(preheader="No se te cobró nada. Puedes intentarlo de nuevo con otro medio.",
                    icono="findy-piensa", eyebrow="Pago no completado", titulo="No se pudo completar tu pago",
                    intro="No se te cobró nada.", acento=CORAL, cuerpo=cuerpo,
                    cta=("Intentar de nuevo", f"{_frontend()}/chat/cuenta/plan#planes"))
    texto = (f"{n}, el pago de {plan} no se completó y no se te cobró nada.\n"
             f"Intenta de nuevo: {_frontend()}/chat/cuenta/plan")
    enviar(email, f"Tu pago de {plan} no se completó", html_, texto, "pago_rechazado", **kw)


def plan_por_vencer(nombre: str, email: str, plan: str, vence: Any, llaves_restantes: int, **kw) -> None:
    n = _primer_nombre(nombre)
    cuerpo = _parrafo(f"{_e(n)}, tu plan <b>{_e(plan)}</b> vence el <b>{_e(_fecha(vence))}</b>. "
                      + (f"Aún tienes <b>{_e(_llaves(llaves_restantes))}</b> por usar este mes. " if llaves_restantes else "")
                      + "Renuévalo antes y el periodo nuevo arranca cuando termine el actual: no pierdes días.")
    html_ = _layout(preheader=f"Tu plan {plan} vence el {_fecha(vence)}. Renuévalo y no pierdes días.",
                    icono="renovacion", eyebrow="Tu plan vence pronto", titulo=f"Tu plan {plan} vence en 3 días",
                    intro="Renuévalo en un minuto con PSE, Nequi o tarjeta.", acento=ORO, cuerpo=cuerpo,
                    cta=("Renovar mi plan", f"{_frontend()}/chat/cuenta/plan#planes"))
    texto = f"{n}, tu plan {plan} vence el {_fecha(vence)}. Renuévalo: {_frontend()}/chat/cuenta/plan"
    enviar(email, f"Tu plan {plan} vence el {_fecha(vence)}", html_, texto, "plan_por_vencer", **kw)


def plan_vencido(nombre: str, email: str, plan: str, gracia_hasta: Any, **kw) -> None:
    n = _primer_nombre(nombre)
    cuerpo = _parrafo(f"{_e(n)}, tu plan <b>{_e(plan)}</b> terminó. Tienes hasta el <b>{_e(_fecha(gracia_hasta))}</b> "
                      "para renovarlo sin perder el mes. Buscar y analizar sigue siendo gratis.")
    html_ = _layout(preheader=f"Renueva antes del {_fecha(gracia_hasta)} y no pierdes el mes.",
                    icono="findy-piensa", eyebrow="Tu plan venció", titulo="Tus llaves del mes se acabaron",
                    intro=f"Renueva antes del {_e(_fecha(gracia_hasta))}.", acento=CORAL, cuerpo=cuerpo,
                    cta=("Renovar mi plan", f"{_frontend()}/chat/cuenta/plan#planes"))
    texto = f"{n}, tu plan {plan} venció. Renueva antes del {_fecha(gracia_hasta)}: {_frontend()}/chat/cuenta/plan"
    enviar(email, f"Tu plan {plan} venció: renueva antes del {_fecha(gracia_hasta)}", html_, texto, "plan_vencido", **kw)


def cuenta_eliminada(nombre: str, email: str, **kw) -> None:
    n = _primer_nombre(nombre)
    cuerpo = _parrafo(f"{_e(n)}, cerramos tu cuenta de Fynder como lo pediste. Ya no puedes entrar con este correo, "
                      "tus sesiones y la conexión con tu IA quedaron cerradas, y borramos tus datos personales "
                      "(nombre, correo y celular) según la Ley 1581 de 2012.") + \
        _parrafo('<span style="color:#6B6B6B;">Guardamos solo el registro contable de los pagos que hiciste, '
                 "como exige la ley. Si no fuiste tú quien lo pidió, responde este correo de inmediato.</span>")
    html_ = _layout(preheader="Tu cuenta de Fynder quedó cerrada.", icono="findy-piensa",
                    eyebrow="Cuenta cerrada", titulo="Tu cuenta quedó cerrada",
                    intro="Gracias por haber sido parte de Fynder. Si algún día vuelves, aquí estaremos.",
                    cuerpo=cuerpo, cta=("Conocer Fynder", _frontend()))
    texto = (f"{n}, cerramos tu cuenta de Fynder y borramos tus datos personales. "
             "Si no fuiste tú, responde este correo de inmediato.")
    enviar(email, "Tu cuenta de Fynder quedó cerrada", html_, texto, "cuenta_eliminada", **kw)


CATEGORIAS_SOPORTE = {"pago": "Pagos y planes", "contacto": "Un contacto o una llave", "cuenta": "Mi cuenta",
                      "ia": "Conexión con mi IA", "inmueble": "Mis inmuebles", "otro": "Otro tema"}


def soporte_recibido(nombre: str, email: str, ticket: int, categoria: str, asunto: str, mensaje: str, **kw) -> None:
    n = _primer_nombre(nombre)
    cuerpo = _parrafo(f"{_e(n)}, recibimos tu mensaje y te respondemos por este correo, normalmente el mismo día hábil.") + \
        f'<div style="margin:16px 0;padding:18px 20px;background:{FONDO};border-radius:16px;">' + \
        _filas([("Caso", f"#{ticket}"), ("Tema", _e(CATEGORIAS_SOPORTE.get(categoria, categoria))), ("Asunto", _e(asunto))]) + \
        f'<p style="margin:14px 0 0;font-family:{FUENTE};font-size:14px;line-height:1.6;color:{SUAVE};white-space:pre-line;">{_e(mensaje)}</p></div>'
    html_ = _layout(preheader=f"Caso #{ticket}: te respondemos por este correo.", icono="soporte",
                    eyebrow=f"Caso #{ticket}", titulo="Recibimos tu mensaje",
                    intro="Un humano del equipo de Fynder lo está leyendo.", cuerpo=cuerpo)
    texto = f"{n}, recibimos tu mensaje (caso #{ticket}): {asunto}. Te respondemos por este correo."
    enviar(email, f"Recibimos tu mensaje · Caso #{ticket}", html_, texto, "soporte_recibido", **kw)


def soporte_nuevo(ticket: int, usuario: Dict[str, Any], categoria: str, asunto: str, mensaje: str, **kw) -> None:
    cuerpo = _filas([("Agente", _e(usuario.get("nombre"))), ("Correo", _e(usuario.get("email"))),
                     ("Celular", _e(usuario.get("telefono") or "—")),
                     ("Verificado", "Sí" if usuario.get("telefono_verificado") else "No"),
                     ("Tema", _e(CATEGORIAS_SOPORTE.get(categoria, categoria))), ("Asunto", _e(asunto))]) + \
        f'<p style="margin:18px 0 0;font-family:{FUENTE};font-size:15px;line-height:1.6;color:{TEXTO};white-space:pre-line;">{_e(mensaje)}</p>'
    html_ = _layout(preheader=f"{usuario.get('nombre')}: {asunto}", icono="soporte", eyebrow=f"Soporte · caso #{ticket}",
                    titulo=asunto[:80], intro="Responde este correo para contestarle directo al agente.", cuerpo=cuerpo)
    texto = f"Caso #{ticket} de {usuario.get('nombre')} <{usuario.get('email')}>\n{asunto}\n\n{mensaje}"
    enviar(buzon_soporte(), f"[Soporte #{ticket}] {asunto}", html_, texto, "soporte_nuevo",
           responder_a=usuario.get("email"), **kw)


# ---------------------------------------------------------------------------
# Activación: llevar al agente nuevo a su primer contacto
# ---------------------------------------------------------------------------

def act_verifica(nombre: str, email: str, **kw) -> None:
    n = _primer_nombre(nombre)
    url = f"{_frontend()}/chat/verificar"
    cuerpo = _parrafo(f"{_e(n)}, tu cuenta está lista pero falta un paso: verificar tu celular. "
                      "Es lo que te da tus <b>2 llaves de prueba</b> y lo que hace que tus inmuebles aparezcan como tuyos.") + \
        _pasos([
            ("verificado", "Toma menos de un minuto", "Te llega un código por WhatsApp y lo escribes en Fynder."),
            ("llave", "Estrenas 2 llaves", "Con cada una abres el contacto de quien tiene un inmueble o de un comprador."),
        ]) + \
        _parrafo('<span style="color:#6B6B6B;font-size:13px;">¿No te llega el código? En la misma pantalla hay un botón '
                 "para escribirnos por WhatsApp desde tu celular y lo verificamos.</span>")
    html_ = _layout(preheader="Verifica tu celular y recibe 2 llaves de prueba.", icono="verificado",
                    eyebrow="Te falta un paso", titulo="Verifica tu celular y estrena 2 llaves",
                    intro="Sin verificar no puedes abrir contactos.", cuerpo=cuerpo, cta=("Verificar mi celular", url))
    texto = f"{n}, verifica tu celular en Fynder y recibe 2 llaves de prueba para abrir contactos.\n\n{url}"
    enviar(email, f"{n}, te faltan tus 2 llaves de prueba", html_, texto, "act_verifica", **kw)


_EJEMPLOS = [
    "Apartamento en Laureles, 3 alcobas, hasta 650 millones",
    "Casa en Envigado con patio, hasta 900 millones",
    "¿Quién está buscando un apartamento como el que tengo en El Poblado?",
]


def act_primera_busqueda(nombre: str, email: str, llaves: int, **kw) -> None:
    n = _primer_nombre(nombre)
    base = f"{_frontend()}/chat/findy"
    ejemplos = "".join(
        f'<tr><td style="padding:6px 0;"><a href="{_e(base + "?q=" + quote(t))}" target="_blank" '
        f'style="display:block;padding:12px 16px;border:1px solid #E6E3DA;border-radius:12px;font-family:{FUENTE};'
        f'font-size:14px;color:{TEXTO};text-decoration:none;">🔎 {_e(t)}</a></td></tr>'
        for t in _EJEMPLOS)
    cuerpo = _parrafo(f"{_e(n)}, pruébalo con lo que busca uno de tus clientes. Escríbele a Findy como se lo dirías "
                      "a un colega y te muestra lo que encaja en la red, con el precio comparado contra la zona.") + \
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:6px 0 16px;">{ejemplos}</table>' + \
        (_parrafo(f"Y tienes <b>{_e(_llaves(llaves))}</b> para abrir el contacto del que te guste.") if llaves else "") + \
        _parrafo('<span style="color:#6B6B6B;font-size:13px;">Buscar y analizar es gratis. '
                 "Si usas Claude o ChatGPT, también puedes conectar Fynder ahí, en “Conecta tu IA”.</span>")
    html_ = _layout(preheader="Escribe lo que busca tu cliente y mira qué hay en la red.", icono="findy-busca",
                    eyebrow="Tu primera búsqueda", titulo="¿Qué está buscando tu cliente?",
                    intro="Findy cruza su pedido con más de 6.500 inmuebles de la red.", cuerpo=cuerpo,
                    cta=("Buscar con Findy", base))
    texto = (f"{n}, escríbele a Findy lo que busca tu cliente, por ejemplo: \"{_EJEMPLOS[0]}\".\n"
             + (f"Tienes {_llaves(llaves)} para abrir contactos.\n" if llaves else "") + f"\n{base}")
    enviar(email, f"{n}, ¿qué busca tu cliente? Pruébalo con Findy", html_, texto, "act_primera_busqueda", **kw)


def act_llaves_esperando(nombre: str, email: str, llaves: int, **kw) -> None:
    n = _primer_nombre(nombre)
    url = f"{_frontend()}/chat/mercado"
    cuerpo = _parrafo(f"{_e(n)}, ya buscaste en Fynder, pero aún no abres ningún contacto. Tienes "
                      f"<b>{_e(_llaves(llaves))}</b> esperando.") + \
        _pasos([
            ("llave", "Una llave = un contacto", "Hablas directo con quien tiene el inmueble o con el comprador."),
            ("verificado", "Solo se gasta si sirve", "Si el inmueble ya no está o el número no sirve, la llave vuelve a ti."),
        ])
    html_ = _layout(preheader=f"Tienes {_llaves(llaves)} sin usar. Abre tu primer contacto.", icono="llave",
                    eyebrow="Tus llaves te esperan", titulo=f"Tienes {_llaves(llaves)} sin usar",
                    intro="Abre el contacto del inmueble que le sirve a tu cliente.", cuerpo=cuerpo,
                    cta=("Ver el inventario", url))
    texto = f"{n}, tienes {_llaves(llaves)} sin usar en Fynder. Abre tu primer contacto: {url}"
    enviar(email, f"{n}, tienes {_llaves(llaves)} esperando", html_, texto, "act_llaves_esperando", **kw)


def act_sin_llaves(nombre: str, email: str, **kw) -> None:
    n = _primer_nombre(nombre)
    url = f"{_frontend()}/chat/cuenta/plan#planes"
    planes = [(ICONO_PLAN.get(p["codigo"], "llave"), p["nombre"], f"{p['desbloqueos_mes']} llaves al mes · {_pesos(p['precio_cop'])}")
              for p in _planes_mensuales()]
    cuerpo = _parrafo(f"{_e(n)}, usaste todas tus llaves. Buscar y analizar sigue siendo gratis; para abrir más "
                      "contactos elige un plan o compra una llave suelta.") + \
        (_pasos(planes) if planes else "") + \
        _parrafo('<span style="color:#6B6B6B;font-size:13px;">No se renueva solo: cada mes decides si sigues.</span>')
    html_ = _layout(preheader="Elige un plan o una llave suelta para seguir abriendo contactos.", icono="findy-piensa",
                    eyebrow="Te quedaste sin llaves", titulo="Sigue abriendo contactos",
                    intro="Activa un plan en un minuto.", acento=ORO, cuerpo=cuerpo, cta=("Ver planes", url))
    texto = f"{n}, usaste todas tus llaves de Fynder. Elige un plan para seguir abriendo contactos: {url}"
    enviar(email, f"{n}, te quedaste sin llaves", html_, texto, "act_sin_llaves", **kw)


def _planes_mensuales() -> List[Dict[str, Any]]:
    """Planes a la venta, con el precio de hoy (no copiado en el correo)."""
    try:
        with get_db() as db:
            return fetch_all(db.cursor, """
                SELECT codigo, nombre, desbloqueos_mes, precio_cop FROM planes
                WHERE activo AND codigo <> 'prueba' AND COALESCE(tipo, 'suscripcion') = 'suscripcion' ORDER BY orden
            """)
    except Exception as e:  # noqa: BLE001
        print(f"[CORREO] No se pudieron leer los planes: {e}")
        return []


# Cuentas reales (no precargadas sin entregar), con la dirección a la que sí se puede escribir.
_CANDIDATOS_ACTIVACION = """
    SELECT u.id, u.nombre, COALESCE(NULLIF(TRIM(u.correo_personal), ''), u.email) AS destino,
           GREATEST(u.fecha_creacion, u.telefono_verificado_at, u.acceso_entregado_at) AS desde,
           COALESCE(u.telefono_verificado, FALSE) AS verificado,
           (COALESCE(u.total_busquedas, 0) > 0
              OR EXISTS (SELECT 1 FROM mcp_tool_calls m WHERE m.user_id = u.id)) AS busco,
           (SELECT COUNT(*) FROM desbloqueos d WHERE d.user_id = u.id) AS contactos,
           (SELECT MAX(d.created_at) FROM desbloqueos d WHERE d.user_id = u.id) AS ultimo_contacto
    FROM chat_users u
    WHERE u.activo AND u.eliminada_at IS NULL
      AND (u.origen IS DISTINCT FROM 'provision' OR u.acceso_entregado)
      AND GREATEST(u.fecha_creacion, u.telefono_verificado_at, u.acceso_entregado_at) > NOW() - INTERVAL '45 days'
"""

TOPE_ACTIVACION = 60  # por corrida: un error de segmento nunca se vuelve un envío masivo


def momento_activacion(u: Dict[str, Any], ahora: datetime, disponibles: int, con_plan: bool) -> Optional[str]:
    """Qué correo de activación le toca a este agente hoy (o None)."""
    desde = u.get("desde")
    if not desde:
        return None
    edad = ahora - desde
    if not u.get("verificado"):
        return "act_verifica" if timedelta(hours=20) <= edad <= timedelta(days=7) else None
    if not u.get("contactos"):
        if not u.get("busco") and timedelta(days=2) <= edad <= timedelta(days=14):
            return "act_primera_busqueda"
        if u.get("busco") and disponibles > 0 and timedelta(days=5) <= edad <= timedelta(days=21):
            return "act_llaves_esperando"
        return None
    ultimo = u.get("ultimo_contacto")
    if disponibles == 0 and not con_plan and ultimo and ahora - ultimo <= timedelta(days=14):
        return "act_sin_llaves"
    return None


def recordatorios_activacion() -> Dict[str, int]:
    """Un correo por momento y por agente (registrado en `correos_enviados`)."""
    from src.services import suscripcion_service
    enviados: Dict[str, int] = {}
    with get_db() as db:
        cur = db.cursor
        ahora = fetch_all(cur, "SELECT NOW() AS t")[0]["t"]
        for u in fetch_all(cur, _CANDIDATOS_ACTIVACION):
            if sum(enviados.values()) >= TOPE_ACTIVACION:
                break
            if not destinatario_real(u["destino"]):
                continue
            saldos = suscripcion_service._saldos(cur, u["id"])
            disponibles = int(saldos["disponibles"])
            momento = momento_activacion(u, ahora, disponibles, bool(saldos["periodo"]))
            if not momento or not _marcar(cur, momento, str(u["id"]), u["id"]):
                continue
            db.conn.commit()
            if momento == "act_verifica":
                act_verifica(u["nombre"], u["destino"], esperar=True)
            elif momento == "act_primera_busqueda":
                act_primera_busqueda(u["nombre"], u["destino"], disponibles, esperar=True)
            elif momento == "act_llaves_esperando":
                act_llaves_esperando(u["nombre"], u["destino"], disponibles, esperar=True)
            else:
                act_sin_llaves(u["nombre"], u["destino"], esperar=True)
            enviados[momento] = enviados.get(momento, 0) + 1
        db.conn.commit()
    return enviados


# ---------------------------------------------------------------------------
# Recordatorios programados (worker, una vez al día)
# ---------------------------------------------------------------------------

def _marcar(cur, tipo: str, ref: str, user_id: int) -> bool:
    """True si este correo aún no se había enviado (y lo deja registrado)."""
    cur.execute("""
        INSERT INTO correos_enviados (tipo, ref, user_id) VALUES (%s, %s, %s)
        ON CONFLICT (tipo, ref) DO NOTHING RETURNING id
    """, (tipo, ref, user_id))
    return cur.fetchone() is not None


def recordatorios_plan() -> Dict[str, int]:
    """Plan por vencer (≤3 días) y plan vencido (en gracia), una vez por periodo y sin
    avisar si el agente ya renovó (tiene un periodo que arranca después)."""
    enviados = {"por_vencer": 0, "vencido": 0}
    with get_db() as db:
        cur = db.cursor
        filas = fetch_all(cur, """
            SELECT s.id, s.user_id, s.fin, s.gracia_hasta, s.desbloqueos_incluidos, p.nombre AS plan,
                   u.nombre, u.email,
                   (SELECT COUNT(*) FROM desbloqueos d WHERE d.suscripcion_id = s.id
                      AND d.fuente_credito = 'plan' AND d.estado = 'vigente') AS usadas,
                   CASE WHEN s.fin > NOW() THEN 'por_vencer' ELSE 'vencido' END AS momento
            FROM suscripciones s
            JOIN planes p ON p.codigo = s.plan_codigo
            JOIN chat_users u ON u.id = s.user_id AND u.activo
            WHERE s.estado = 'activa'
              AND ((s.fin > NOW() AND s.fin <= NOW() + INTERVAL '3 days')
                   OR (s.fin <= NOW() AND s.gracia_hasta > NOW()))
              AND NOT EXISTS (SELECT 1 FROM suscripciones s2 WHERE s2.user_id = s.user_id
                              AND s2.estado = 'activa' AND s2.inicio >= s.fin)
        """)
        for f in filas:
            if not _marcar(cur, f"plan_{f['momento']}", str(f["id"]), f["user_id"]):
                continue
            db.conn.commit()
            if f["momento"] == "por_vencer":
                plan_por_vencer(f["nombre"], f["email"], f["plan"], f["fin"],
                                max(0, int(f["desbloqueos_incluidos"]) - int(f["usadas"] or 0)), esperar=True)
            else:
                plan_vencido(f["nombre"], f["email"], f["plan"], f["gracia_hasta"], esperar=True)
            enviados[f["momento"]] += 1
        db.conn.commit()
    return enviados
