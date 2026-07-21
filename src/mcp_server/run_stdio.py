"""
Entrypoint local del MCP de Fynder (transporte stdio, para Claude Desktop).

Uso:
    FYNDER_MCP_TOKEN=<token-del-agente> \
    python -m src.mcp_server.run_stdio

El token identifica al agente (una sesión válida en `chat_user_sessions`).
Para desarrollo local se puede emitir con `scripts/mcp_issue_token.py`.
"""

from src.mcp_server.server import mcp


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
