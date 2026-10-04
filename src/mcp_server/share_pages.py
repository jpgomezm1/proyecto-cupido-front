"""
Links heredados de comparativa y ficha (/comparar?t=, /ficha?t=).

Antes se renderizaban aquí; hoy los genera y muestra la app de React
(`{FRONTEND}/comparar/{t}` y `{FRONTEND}/ficha/{t}`, que también registra la
vista). Estas rutas solo redirigen (301) para que los links viejos sigan
funcionando con el mismo token.
"""

from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

from src.mcp_server import brand


def _redirect(request: Request, ruta: str) -> RedirectResponse:
    token = request.query_params.get("t", "").strip()
    destino = f"{brand.frontend_url()}/{ruta}/{quote(token, safe='')}" if token else f"{brand.frontend_url()}/"
    return RedirectResponse(url=destino, status_code=301)


async def comparar_page(request: Request) -> RedirectResponse:
    return _redirect(request, "comparar")


async def ficha_page(request: Request) -> RedirectResponse:
    return _redirect(request, "ficha")


def share_pages_routes():
    return [
        Route("/comparar", comparar_page, methods=["GET"]),
        Route("/ficha", ficha_page, methods=["GET"]),
    ]
