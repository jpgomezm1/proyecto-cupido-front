"""
Página de login de Fynder para el flujo OAuth del MCP.

Cuando Claude manda al usuario a /authorize, el provider lo redirige aquí. El
agente inicia sesión con su correo y clave de Fynder (los mismos del portal), y
al validar se emite el authorization code y se lo devuelve a Claude.

Rutas:
- GET  /oauth/login?rid=...  -> formulario de login.
- POST /oauth/login          -> valida credenciales y redirige de vuelta a Claude.
"""

import html
import time
from typing import Optional

import anyio

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route

from src.mcp_server import brand

from src.mcp_server.oauth_provider import (
    load_pending, authenticate_chat_user, complete_login,
)


def _page(rid: str, error: str = "", email: str = "") -> str:
    return _render_login(rid, error, email, _destino(load_pending(rid)))


async def login_get(request: Request) -> HTMLResponse:
    rid = request.query_params.get("rid", "")
    if not rid or not load_pending(rid):
        return HTMLResponse(_EXPIRED_HTML, status_code=400)
    return HTMLResponse(_page(rid))


# Destinos conocidos de la conexión (redirect_uri). Cualquiera puede registrar un
# cliente OAuth, así que la página dice A QUIÉN se le da acceso y advierte si no es
# Claude, ChatGPT o una app local (Claude Code, Cursor).
_DESTINOS = {
    "claude.ai": "Claude", "claude.com": "Claude", "anthropic.com": "Claude",
    "chatgpt.com": "ChatGPT", "openai.com": "ChatGPT",
}


def _destino(pending: Optional[dict]) -> dict:
    from urllib.parse import urlsplit
    host = (urlsplit((pending or {}).get("redirect_uri") or "").hostname or "").lower()
    nombre = ((pending or {}).get("client_name") or "").strip()[:60]
    if host in ("localhost", "127.0.0.1", "::1"):
        return {"host": "esta computadora", "nombre": nombre or "Una app en tu computadora", "conocido": True}
    for dominio, app in _DESTINOS.items():
        if host == dominio or host.endswith("." + dominio):
            return {"host": host, "nombre": app, "conocido": True}
    return {"host": host or "desconocido", "nombre": nombre or "Una aplicación", "conocido": False}


# Intentos fallidos por IP y por correo (en memoria, por proceso): frena la
# fuerza bruta de claves, que aquí no tenía ningún límite.
_FALLOS: dict = {}
_VENTANA_S = 15 * 60
_MAX_POR_IP = 20
_MAX_POR_CORREO = 8


def _bloqueado(*claves: str) -> bool:
    ahora = time.time()
    for k in claves:
        _FALLOS[k] = [t for t in _FALLOS.get(k, []) if ahora - t < _VENTANA_S]
    return (len(_FALLOS.get(claves[0], [])) >= _MAX_POR_IP
            or any(len(_FALLOS.get(k, [])) >= _MAX_POR_CORREO for k in claves[1:]))


def _fallo(*claves: str) -> None:
    for k in claves:
        _FALLOS.setdefault(k, []).append(time.time())
    if len(_FALLOS) > 5000:  # no crecer sin límite
        _FALLOS.clear()


def _ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    return "ip:" + (xff.split(",")[-1].strip() if xff else (request.client.host if request.client else "?"))


async def login_post(request: Request):
    form = await request.form()
    rid = (form.get("rid") or "").strip()
    email = (form.get("email") or "").strip()
    password = form.get("password") or ""

    if not rid or not load_pending(rid):
        return HTMLResponse(_EXPIRED_HTML, status_code=400)

    claves = (_ip(request), "correo:" + email.lower())
    if _bloqueado(*claves):
        return HTMLResponse(_page(rid, "Demasiados intentos. Espera 15 minutos e inténtalo de nuevo.", email),
                            status_code=429)
    user = authenticate_chat_user(email, password)
    if not user:
        _fallo(*claves)
        return HTMLResponse(_page(rid, "Correo o clave incorrectos.", email), status_code=401)
    if not form.get("acepta_terminos"):
        return HTMLResponse(_page(rid, "Para conectar Fynder debes aceptar los términos.", email), status_code=400)
    from src.services.suscripcion_service import aceptar_terminos
    await anyio.to_thread.run_sync(aceptar_terminos, user["id"])

    redirect_url = complete_login(rid, user["id"])
    if not redirect_url:
        return HTMLResponse(_EXPIRED_HTML, status_code=400)
    return RedirectResponse(url=redirect_url, status_code=302)


def oauth_login_routes():
    return [
        Route("/oauth/login", login_get, methods=["GET"]),
        Route("/oauth/login", login_post, methods=["POST"]),
    ]


# ---------------------------------------------------------------------------
# HTML (marca compartida: brand.py).
# ---------------------------------------------------------------------------

_CSS = """
body{ display:flex; flex-direction:column; }
main{ flex:1; display:flex; align-items:center; padding:12px 0 8px; }
.findy{ display:flex; justify-content:center; margin-bottom:12px; }
.findy img{ height:56px; width:56px; object-fit:contain; }
.card h1{ text-align:center; font-size:22px; }
.card .lead{ text-align:center; font-size:14.5px; margin-top:6px; }
.olvido{ text-align:center; font-size:13.5px; margin-top:14px; }
.destino{ text-align:center; font-size:14px; margin:14px 0 4px; }
.destino span{ color:var(--muted); }
.seguro{ text-align:center; color:var(--muted); font-size:12.5px; margin-top:16px; line-height:1.55; }
"""

_WA_CLAVE = brand.wa_link("Hola, olvidé mi clave de Fynder y necesito recuperarla.")

_LOGIN_BODY = """
<div class="wrap-sm">__HEADER__
<main>
  <form class="card" method="post" action="/oauth/login" style="width:100%">
    <div class="findy"><img src="__FINDY__" alt="Findy, el asistente de Fynder"></div>
    <h1>Conecta Fynder con tu IA</h1>
    <p class="lead">Inicia sesión con tu cuenta de Fynder para autorizar la conexión.</p>
    __DESTINO__
    __ERROR__
    <input type="hidden" name="rid" value="__RID__">
    <div class="field"><label for="email">Correo electrónico</label>
      <input id="email" name="email" type="email" value="__EMAIL__" placeholder="tucorreo@ejemplo.com"
             autocomplete="email" required autofocus __DESCRIBED__></div>
    <div class="field"><label for="password">Clave</label>
      <div class="pwd">
        <input id="password" name="password" type="password" placeholder="••••••••"
               autocomplete="current-password" required __DESCRIBED__>
        <button type="button" id="ver-clave" aria-controls="password" aria-pressed="false">Mostrar</button>
      </div></div>
    <label class="chk" for="acepta_terminos"><input type="checkbox" id="acepta_terminos" name="acepta_terminos" value="1" required>
      <span>Acepto los <a href="__URL_TERMINOS__" target="_blank" rel="noopener">términos de uso y el tratamiento de mis datos</a> de Fynder</span></label>
    <button type="submit" class="btn btn-primary btn-block" style="margin-top:20px">Iniciar sesión y autorizar</button>
    <p class="olvido">¿Olvidaste tu clave? <a href="__WA_CLAVE__" target="_blank" rel="noopener noreferrer">Escríbenos por WhatsApp</a></p>
    <p class="seguro">Conexión segura. Al autorizar, tu asistente de IA podrá consultar Fynder en tu nombre.
      Puedes revocar el acceso cuando quieras.</p>
  </form>
</main>
__FOOTER__</div>
"""

_SCRIPT = """<script>
(function(){
  var b = document.getElementById('ver-clave'), i = document.getElementById('password');
  if (!b || !i) return;
  b.addEventListener('click', function(){
    var ver = i.type === 'password';
    i.type = ver ? 'text' : 'password';
    b.textContent = ver ? 'Ocultar' : 'Mostrar';
    b.setAttribute('aria-pressed', ver ? 'true' : 'false');
    i.focus();
  });
})();
</script>"""


def _render_login(rid: str, error: str = "", email: str = "", destino: Optional[dict] = None) -> str:
    from src.services.suscripcion_service import url_terminos
    err_html = (f'<div class="alert-error" id="login-error" role="alert">{html.escape(error)}</div>'
                if error else "")
    d = destino or {"nombre": "Una aplicación", "host": "desconocido", "conocido": False}
    destino_html = (
        f'<p class="destino"><b>{html.escape(d["nombre"])}</b> quiere acceder a tu cuenta de Fynder'
        f' <span>({html.escape(d["host"])})</span></p>')
    if not d["conocido"]:
        destino_html += ('<div class="alert-error" role="alert">Esta conexión no es de Claude ni de ChatGPT. '
                         'Autorízala solo si tú mismo agregaste esta aplicación; si alguien te mandó este '
                         'enlace, ciérralo.</div>')
    body = (_LOGIN_BODY
            .replace("__HEADER__", brand.header())
            .replace("__FOOTER__", brand.footer())
            .replace("__FINDY__", brand.FINDY)
            .replace("__WA_CLAVE__", html.escape(_WA_CLAVE))
            .replace("__URL_TERMINOS__", html.escape(url_terminos()))
            .replace("__DESCRIBED__", 'aria-describedby="login-error" aria-invalid="true"' if error else "")
            .replace("__ERROR__", err_html)
            .replace("__DESTINO__", destino_html)
            # valores del usuario al final, para que no se reinterpreten como placeholders
            .replace("__EMAIL__", html.escape(email))
            .replace("__RID__", html.escape(rid)))
    return brand.page("Iniciar sesión · Fynder", body, extra_css=_CSS, scripts=_SCRIPT)


def _expired_html() -> str:
    body = (f'<div class="wrap-sm">{brand.header()}<main><div class="card" style="text-align:center;width:100%">'
            f'<div class="findy"><img src="{brand.FINDY}" alt="Findy, el asistente de Fynder"></div>'
            '<h1>El enlace de conexión expiró</h1>'
            '<p class="lead">Vuelve a tu asistente de IA e intenta agregar el conector de Fynder de nuevo.</p>'
            f'<p class="olvido">¿Necesitas ayuda? <a href="{html.escape(brand.wa_link("Hola, necesito ayuda para conectar Fynder a mi IA."))}" '
            'target="_blank" rel="noopener noreferrer">Escríbenos por WhatsApp</a></p>'
            f'</div></main>{brand.footer()}</div>')
    return brand.page("Enlace expirado · Fynder", body, extra_css=_CSS)


_EXPIRED_HTML = _expired_html()
