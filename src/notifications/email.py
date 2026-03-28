"""
Notificaciones por correo para Deals usando Resend
"""

import os
import resend
from typing import Optional


def _ensure_api_key():
    if not resend.api_key:
        resend.api_key = os.getenv("RESEND_API_KEY", "")
    if not resend.api_key:
        print("[EMAIL WARNING] RESEND_API_KEY no configurada")
        return False
    return True

RECIPIENTS = ["jpgomez@stayirrelevant.com", "hdrios321@gmail.com"]
FROM_EMAIL = "Fynder <deals@updates.stayirrelevant.com>"

STAGE_LABELS = {
    "lead": "Lead",
    "contactado": "Contactado",
    "visita_agendada": "Visita Agendada",
    "visita_realizada": "Visita Realizada",
    "negociando": "Negociando",
    "documentacion": "Documentacion",
    "cierre": "Cierre",
    "ganado": "Ganado",
    "perdido": "Perdido",
}

MATIAS_STAGES = ["lead", "contactado", "visita_agendada"]


def _base_template(content: str, accent_color: str = "#2AE38C") -> str:
    return f"""
    <div style="font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 520px; margin: 0 auto; background: #ffffff;">
        <div style="border-top: 4px solid {accent_color}; padding: 32px 28px;">
            <div style="margin-bottom: 24px;">
                <img src="https://storage.googleapis.com/cluvi/FYNDER/logo_negro_fynder_final.png" alt="Fynder" style="height: 28px; width: auto;" />
            </div>
            {content}
            <div style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb;">
                <p style="font-size: 11px; color: #9ca3af; margin: 0;">Fynder — Find Better. Move Faster.</p>
            </div>
        </div>
    </div>
    """


def _format_price(amount) -> str:
    try:
        num = float(amount)
        if num >= 1_000_000:
            m = num / 1_000_000
            return f"${m:,.1f}M COP" if m % 1 else f"${m:,.0f}M COP"
        return f"${num:,.0f} COP"
    except:
        return "N/A"


def _info_row(label: str, value: str, color: str = "#111827") -> str:
    return f"""
    <tr>
        <td style="padding: 6px 0; font-size: 12px; color: #6b7280; width: 120px; vertical-align: top;">{label}</td>
        <td style="padding: 6px 0; font-size: 13px; color: {color}; font-weight: 500;">{value}</td>
    </tr>
    """


def send_deal_created_email(
    deal_code: str,
    contact_name: str,
    contact_phone: str,
    property_title: str = "",
    property_price: float = 0,
):
    try:
        if not _ensure_api_key(): return
        content = f"""
        <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 12px; padding: 16px; margin-bottom: 20px;">
            <p style="margin: 0; font-size: 11px; color: #16a34a; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">Nuevo Deal</p>
            <p style="margin: 4px 0 0; font-size: 20px; font-weight: 700; color: #111827; font-family: monospace;">{deal_code}</p>
        </div>
        <table style="width: 100%; border-collapse: collapse;">
            {_info_row("Comprador", contact_name)}
            {_info_row("Telefono", contact_phone)}
            {_info_row("Propiedad", property_title or "N/A")}
            {_info_row("Precio", _format_price(property_price))}
            {_info_row("Estado", "Contactado", "#2AE38C")}
        </table>
        """

        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": RECIPIENTS,
            "subject": f"Nuevo Deal: {deal_code}",
            "html": _base_template(content),
        })
        print(f"[EMAIL] Deal creado: {deal_code} — enviado a {len(RECIPIENTS)} destinatarios")
    except Exception as e:
        print(f"[EMAIL ERROR] send_deal_created_email: {e}")


def send_deal_stage_changed_email(
    deal_code: str,
    contact_name: str,
    previous_stage: str,
    new_stage: str,
    property_title: str = "",
):
    try:
        if not _ensure_api_key(): return
        prev_label = STAGE_LABELS.get(previous_stage, previous_stage)
        new_label = STAGE_LABELS.get(new_stage, new_stage)
        responsable = "Matias" if new_stage in MATIAS_STAGES else "Hernan"

        content = f"""
        <div style="background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 12px; padding: 16px; margin-bottom: 20px;">
            <p style="margin: 0; font-size: 11px; color: #2563eb; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">Cambio de etapa</p>
            <p style="margin: 4px 0 0; font-size: 18px; font-weight: 700; color: #111827; font-family: monospace;">{deal_code}</p>
        </div>
        <div style="background: #f9fafb; border-radius: 8px; padding: 14px; margin-bottom: 16px; text-align: center;">
            <span style="font-size: 13px; color: #6b7280;">{prev_label}</span>
            <span style="font-size: 16px; color: #2563eb; margin: 0 12px;">→</span>
            <span style="font-size: 14px; font-weight: 700; color: #2563eb;">{new_label}</span>
        </div>
        <table style="width: 100%; border-collapse: collapse;">
            {_info_row("Comprador", contact_name)}
            {_info_row("Propiedad", property_title or "N/A")}
            {_info_row("Responsable", responsable, "#7c3aed" if responsable == "Hernan" else "#ea580c")}
        </table>
        """

        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": RECIPIENTS,
            "subject": f"Deal {deal_code} → {new_label}",
            "html": _base_template(content, "#3b82f6"),
        })
        print(f"[EMAIL] Stage changed: {deal_code} {prev_label} → {new_label}")
    except Exception as e:
        print(f"[EMAIL ERROR] send_deal_stage_changed_email: {e}")


def send_deal_won_email(
    deal_code: str,
    contact_name: str,
    property_title: str = "",
    sale_price: float = 0,
    commission: float = 0,
    commission_pct: float = 0,
):
    try:
        if not _ensure_api_key(): return
        content = f"""
        <div style="background: #f0fdf4; border: 1px solid #86efac; border-radius: 12px; padding: 20px; margin-bottom: 20px; text-align: center;">
            <div style="font-size: 40px; margin-bottom: 8px;">🏆</div>
            <p style="margin: 0; font-size: 11px; color: #16a34a; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">Deal Ganado</p>
            <p style="margin: 4px 0 0; font-size: 22px; font-weight: 800; color: #111827; font-family: monospace;">{deal_code}</p>
        </div>
        <div style="background: #ecfdf5; border-radius: 8px; padding: 16px; margin-bottom: 16px; text-align: center;">
            <p style="margin: 0; font-size: 12px; color: #059669;">Comision ganada</p>
            <p style="margin: 4px 0 0; font-size: 28px; font-weight: 800; color: #047857;">{_format_price(commission)}</p>
            <p style="margin: 4px 0 0; font-size: 11px; color: #6b7280;">{commission_pct}% de {_format_price(sale_price)}</p>
        </div>
        <table style="width: 100%; border-collapse: collapse;">
            {_info_row("Comprador", contact_name)}
            {_info_row("Propiedad", property_title or "N/A")}
            {_info_row("Precio venta", _format_price(sale_price))}
        </table>
        """

        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": RECIPIENTS,
            "subject": f"DEAL GANADO: {deal_code} — {_format_price(commission)}",
            "html": _base_template(content, "#059669"),
        })
        print(f"[EMAIL] Deal ganado: {deal_code} — comision {_format_price(commission)}")
    except Exception as e:
        print(f"[EMAIL ERROR] send_deal_won_email: {e}")


def send_deal_lost_email(
    deal_code: str,
    contact_name: str,
    property_title: str = "",
    reason: str = "",
):
    try:
        if not _ensure_api_key(): return
        content = f"""
        <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 12px; padding: 16px; margin-bottom: 20px;">
            <p style="margin: 0; font-size: 11px; color: #dc2626; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">Deal Perdido</p>
            <p style="margin: 4px 0 0; font-size: 18px; font-weight: 700; color: #111827; font-family: monospace;">{deal_code}</p>
        </div>
        <table style="width: 100%; border-collapse: collapse;">
            {_info_row("Comprador", contact_name)}
            {_info_row("Propiedad", property_title or "N/A")}
            {_info_row("Motivo", reason or "No especificado", "#dc2626")}
        </table>
        """

        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": RECIPIENTS,
            "subject": f"Deal perdido: {deal_code}",
            "html": _base_template(content, "#dc2626"),
        })
        print(f"[EMAIL] Deal perdido: {deal_code}")
    except Exception as e:
        print(f"[EMAIL ERROR] send_deal_lost_email: {e}")
