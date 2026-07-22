"""
Entrypoint remoto del MCP de Fynder (Streamable HTTP, para Claude.ai / Desktop).

Expone un ASGI `app` que sirve:
- El endpoint MCP protegido por OAuth 2.1 en `/mcp`.
- Los endpoints OAuth del protocolo (metadata, /authorize, /token, /register,
  /revoke) que el SDK monta automáticamente al configurar `auth`.
- El login de Fynder (`/oauth/login`) al que redirige el authorize.
- El onboarding self-service (`/`, `/connect/token`).

Deploy (app/proceso separado; ver Procfile.mcp):
    web: uvicorn src.mcp_server.run_http:app --host 0.0.0.0 --port $PORT

Requiere en el entorno: DATABASE_URL, ANTHROPIC_API_KEY (búsqueda), y
MCP_PUBLIC_URL apuntando a la URL pública (para que las URLs OAuth sean válidas).
"""

from src.mcp_server.server import mcp
from src.mcp_server.onboarding import onboarding_routes
from src.mcp_server.oauth_login import oauth_login_routes
from src.mcp_server.listing_upload import listing_upload_routes
from src.mcp_server.share_pages import share_pages_routes


def build_app():
    # streamable_http_app() ya incluye los endpoints OAuth (por tener auth
    # configurado) y protege /mcp con validación de token del SDK. Agregamos las
    # rutas públicas propias (login de Fynder + onboarding) a la misma app.
    app = mcp.streamable_http_app()
    app.router.routes.extend(oauth_login_routes())
    app.router.routes.extend(onboarding_routes())
    app.router.routes.extend(listing_upload_routes())
    app.router.routes.extend(share_pages_routes())
    return app


app = build_app()
