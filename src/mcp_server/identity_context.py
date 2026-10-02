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

# Identidad ya resuelta para la tool call en curso. La fija el wrapper central de
# tools (`bind_agent`) y vive solo durante esa llamada: no hay caché global, así
# que un token revocado o un cambio de teléfono se reflejan de inmediato.
_bound_agent: contextvars.ContextVar[Optional[AgentIdentity]] = contextvars.ContextVar(
    "fynder_mcp_agent", default=None
)


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
    return resolve_agent_by_id(at.subject)


def current_agent() -> Optional[AgentIdentity]:
    """Devuelve el agente autenticado del request, o None si no hay identidad."""
    # 0) Ya resuelto para esta tool call (ver bind_agent).
    bound = _bound_agent.get()
    if bound is not None:
        return bound
    # 1) OAuth (Claude remoto): identidad validada por el SDK.
    agent = _agent_from_oauth_context()
    if agent is not None:
        return agent
    # 2) Bearer token directo / stdio local (FYNDER_MCP_TOKEN).
    token = _active_token()
    if not token:
        return None
    return resolve_agent(token)


def require_agent() -> AgentIdentity:
    """Como `current_agent` pero lanza `AuthError` si no hay agente válido."""
    agent = current_agent()
    if agent is None:
        raise AuthError(
            "No autorizado: se requiere un token válido de un agente con acceso a "
            "Fynder. Configura tu conector con el token que te entregó Fynder."
        )
    return agent


def bind_agent(agent: AgentIdentity) -> contextvars.Token:
    """Fija la identidad para el resto de la tool call en curso."""
    return _bound_agent.set(agent)


def unbind_agent(cv_token: contextvars.Token) -> None:
    _bound_agent.reset(cv_token)
