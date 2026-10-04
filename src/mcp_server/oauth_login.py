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

import anyio

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route

from src.mcp_server import brand

from src.mcp_server.oauth_provider import (
    load_pending, authenticate_chat_user, complete_login,
)


def _page(rid: str, error: str = "", email: str = "") -> str:
    return _render_login(rid, error, email)


async def login_get(request: Request) -> HTMLResponse:
    rid = request.query_params.get("rid", "")
    if not rid or not load_pending(rid):
        return HTMLResponse(_EXPIRED_HTML, status_code=400)
    return HTMLResponse(_page(rid))


async def login_post(request: Request):
    form = await request.form()
    rid = (form.get("rid") or "").strip()
    email = (form.get("email") or "").strip()
    password = form.get("password") or ""

    if not rid or not load_pending(rid):
        return HTMLResponse(_EXPIRED_HTML, status_code=400)

    user = authenticate_chat_user(email, password)
    if not user:
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


def _render_login(rid: str, error: str = "", email: str = "") -> str:
    from src.services.suscripcion_service import url_terminos
    err_html = (f'<div class="alert-error" id="login-error" role="alert">{html.escape(error)}</div>'
                if error else "")
    body = (_LOGIN_BODY
            .replace("__HEADER__", brand.header())
            .replace("__FOOTER__", brand.footer())
            .replace("__FINDY__", brand.FINDY)
            .replace("__WA_CLAVE__", html.escape(_WA_CLAVE))
            .replace("__URL_TERMINOS__", html.escape(url_terminos()))
            .replace("__DESCRIBED__", 'aria-describedby="login-error" aria-invalid="true"' if error else "")
            .replace("__ERROR__", err_html)
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
