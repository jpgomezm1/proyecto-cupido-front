"""
Control de acceso de la API Flask y blindaje de contactos.

El contacto de quien tiene un inmueble (o de quien hizo un pedido) es lo que
Fynder cobra (suscripción + desbloqueos). Por eso:
  - Las respuestas para usuarios NO admin pasan por `sin_contacto()`.
  - Los blueprints de administración exigen el JWT del admin (`proteger_admin`).

Un mismo header `Authorization: Bearer <token>` puede traer el JWT del admin o el
token opaco de un usuario del chat; `admin_actual()` nunca lanza error, solo dice
si el token es de un admin.
"""

import os
from functools import wraps
from typing import Any, Iterable, Optional

from flask import g, jsonify, request

from src.services.redact import redact_phones

# Claves que identifican o permiten contactar a un agente, o que llevan al
# portal de origen (donde el contacto es visible).
CAMPOS_CONTACTO = {
    "owner_phone", "owner_name", "source_url", "source_group", "url",
    "asesor", "inmobiliaria", "telefono", "contacto_responsable",
    "agente_captador_telefono", "agente_captador_id", "agente_telefono", "agente_nombre",
    "captador_nombre", "captador_whatsapp", "whatsapp", "celular", "email",
    "url_original", "link_original", "enlace_original",
}


def _bearer() -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    return auth[7:].strip() if auth.startswith("Bearer ") else None


def admin_actual() -> Optional[dict]:
    """Payload del JWT del admin si el request lo trae y es válido; si no, None."""
    if "admin_actual" in g:
        return g.admin_actual
    payload = None
    token = _bearer()
    if token and token.count(".") == 2:  # los tokens del chat no son JWT
        try:
            from src.api.auth import decode_token, AUTHORIZED_USERS
            data = decode_token(token)
            if data.get("email") in AUTHORIZED_USERS:
                payload = data
        except Exception:
            payload = None
    g.admin_actual = payload
    return payload


def es_admin() -> bool:
    return admin_actual() is not None


def usuario_chat() -> Optional[dict]:
    """El chat_user del request (token opaco), o None. Cacheado por request."""
    if "usuario_chat" in g:
        return g.usuario_chat
    user = None
    if _bearer() and not es_admin():
        from src.api.chat_auth import get_current_user
        user = get_current_user()
    g.usuario_chat = user
    return user


def sin_contacto(obj: Any) -> Any:
    """Copia de `obj` sin campos de contacto/origen y con teléfonos redactados."""
    if isinstance(obj, dict):
        return {k: sin_contacto(v) for k, v in obj.items()
                if not (isinstance(k, str) and k.lower() in CAMPOS_CONTACTO)}
    if isinstance(obj, (list, tuple)):
        return [sin_contacto(x) for x in obj]
    if isinstance(obj, str):
        return redact_phones(obj)
    return obj


def para_cliente(obj: Any) -> Any:
    """Lo que ve quien llama: completo para el admin, sin contactos para el resto."""
    return obj if es_admin() else sin_contacto(obj)


def _no_autorizado():
    return jsonify({"success": False, "error": "No autorizado", "code": "UNAUTHORIZED"}), 401


def requiere_admin_o_chat(f):
    """Admin, o usuario del chat autenticado (queda en `request.chat_user`)."""
    @wraps(f)
    def decorada(*args, **kwargs):
        if not es_admin():
            user = usuario_chat()
            if not user:
                return _no_autorizado()
            request.chat_user = user
        return f(*args, **kwargs)
    return decorada


def _guard_enforce() -> bool:
    return os.getenv("ADMIN_GUARD_ENFORCE", "true").strip().lower() != "false"


def proteger_admin(bp, publicos: Iterable[str] = ()) -> None:
    """
    Exige el JWT del admin en TODO el blueprint, salvo los endpoints listados en
    `publicos` (nombres de función de la vista). Con ADMIN_GUARD_ENFORCE=false
    solo deja constancia en el log (para detectar páginas que no mandan token).
    """
    publicos = set(publicos)

    @bp.before_request
    def _guard():
        if request.method == "OPTIONS":
            return None
        endpoint = (request.endpoint or "").split(".")[-1]
        if endpoint in publicos or es_admin():
            return None
        if _guard_enforce():
            return _no_autorizado()
        print(f"[ADMIN_GUARD] acceso sin token admin: {request.method} {request.path}")
        return None


def uso_justo(f):
    """
    Cuenta el request contra el tope diario de búsquedas con IA del usuario del
    chat (el admin no tiene tope). Va DESPUÉS del decorador de autenticación.
    """
    @wraps(f)
    def decorada(*args, **kwargs):
        user = getattr(request, "chat_user", None)
        if user and not es_admin():
            from src.services.suscripcion_service import registrar_busqueda
            uso = registrar_busqueda(user["id"])
            if not uso["permitido"]:
                return jsonify({
                    "success": False, "code": "LIMITE_DIARIO",
                    "error": f"Llegaste al uso justo diario ({uso['limite']} búsquedas con IA). "
                             "Se renueva mañana.",
                }), 429
        return f(*args, **kwargs)
    return decorada
