"""
Servidor MCP de Fynder.

Expone la inteligencia inmobiliaria de Fynder (búsqueda, estadísticas de zona,
oferta/demanda, comparativas y diagnóstico de rotación) como herramientas que
Claude puede llamar en nombre de un agente autenticado.

- `server.py`      : instancia FastMCP + registro de tools.
- `identity_context.py` : resolución del agente autenticado (bearer token).
- `run_stdio.py`   : entrypoint local (Claude Desktop, stdio).
- `run_http.py`    : entrypoint remoto (Streamable HTTP, para Claude.ai).

Solo para usuarios con acceso al chat (agentes). Nunca para el admin.
"""
