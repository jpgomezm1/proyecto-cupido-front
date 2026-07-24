"""
Envío liviano de WhatsApp por UltraMSG.

Espeja `WhatsAppBot.send_message` pero sin instanciar el bot completo (que arrastra
dependencias pesadas). Lo usan servicios que solo necesitan mandar un mensaje
—p. ej. las PUNTAS a Hernán (A2)— desde el proceso MCP.
"""

import os
from typing import Any, Dict

import requests

_TIMEOUT = 20  # segundos


class WhatsAppSendError(Exception):
    """Falla al enviar un WhatsApp por UltraMSG (config faltante o error de red)."""


def enviar_whatsapp(to: str, body: str) -> Dict[str, Any]:
    """
    Envía un mensaje de texto por UltraMSG. `to` en formato internacional (+57...).
    Devuelve la respuesta JSON de UltraMSG, o lanza WhatsAppSendError.
    """
    instance_id = os.getenv("ULTRAMSG_INSTANCE_ID")
    token = os.getenv("ULTRAMSG_TOKEN")
    if not instance_id or not token:
        raise WhatsAppSendError("Faltan credenciales de UltraMSG (ULTRAMSG_INSTANCE_ID / ULTRAMSG_TOKEN).")
    if not to:
        raise WhatsAppSendError("Falta el destinatario (to).")

    url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
    try:
        resp = requests.post(url, data={"token": token, "to": to, "body": body}, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        raise WhatsAppSendError(f"Error enviando WhatsApp: {e}") from e
