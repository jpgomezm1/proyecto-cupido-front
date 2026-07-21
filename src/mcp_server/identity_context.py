"""
Resolución del agente autenticado para el servidor MCP, independiente del
transporte.

- En **stdio / local** (Claude Desktop): el token se lee de la variable de
  entorno `FYNDER_MCP_TOKEN`.
- En **HTTP remoto** (Claude.ai): un middleware ASGI coloca el bearer token del
  header `Authorization` en el contextvar antes de ejecutar la tool.

Las tools llaman `require_agent()`; si no hay un agente válido, se lanza
`AuthError`, que el servidor convierte en un error claro para el usuario.
"""

import contextvars
import os
from typing import Optional

from src.services.identity_service import AgentIdentity, resolve_agent, resolve_agent_by_id

# Token del request en curso (lo setea el middleware HTTP; en stdio se lee del env).
_current_token: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "fynder_mcp_token", default=None
)

# Cache simple token->identidad para no golpear la BD en cada tool call del mismo
# request. Se limpia por token; suficiente para el ciclo de vida de un request.
_identity_cache: dict = {}


class AuthError(Exception):
    """El request no trae un token válido de un agente con acceso a Fynder."""


def set_current_token(token: Optional[str]) -> contextvars.Token:
    """Setea el token del request en curso (usado por el middleware HTTP)."""
    return _current_token.set(token)


def reset_current_token(cv_token: contextvars.Token) -> None:
    _current_token.reset(cv_token)


def _active_token() -> Optional[str]:
    token = _current_token.get()
    if token:
        return token
    # Fallback stdio/local.
    return os.getenv("FYNDER_MCP_TOKEN")


def _agent_from_oauth_context() -> Optional[AgentIdentity]:
    """Identidad desde el contexto de auth OAuth del SDK (transporte HTTP remoto).

    El access token OAuth trae `subject` = user_id del chat_user. El SDK valida
    el token (via load_access_token) y expone el AccessToken en el contexto.
    """
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token
    except Exception:
        return None
    at = get_access_token()
    if not at or not getattr(at, "subject", None):
        return None
    cache_key = f"sub:{at.subject}"
    if cache_key in _identity_cache:
        return _identity_cache[cache_key]
    agent = resolve_agent_by_id(at.subject)
    if agent is not None:
        _identity_cache[cache_key] = agent
    return agent


def current_agent() -> Optional[AgentIdentity]:
    """Devuelve el agente autenticado del request, o None si no hay identidad."""
    # 1) OAuth (Claude remoto): identidad validada por el SDK.
    agent = _agent_from_oauth_context()
    if agent is not None:
        return agent
    # 2) Bearer token directo / stdio local (FYNDER_MCP_TOKEN).
    token = _active_token()
    if not token:
        return None
    if token in _identity_cache:
        return _identity_cache[token]
    agent = resolve_agent(token)
    if agent is not None:
        _identity_cache[token] = agent
    return agent


def require_agent() -> AgentIdentity:
    """Como `current_agent` pero lanza `AuthError` si no hay agente válido."""
    agent = current_agent()
    if agent is None:
        raise AuthError(
            "No autorizado: se requiere un token válido de un agente con acceso a "
            "Fynder. Configura tu conector con el token que te entregó Fynder."
        )
    return agent


def clear_identity_cache() -> None:
    _identity_cache.clear()
