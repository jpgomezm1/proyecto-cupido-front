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

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route

from src.mcp_server.oauth_provider import (
    load_pending, authenticate_chat_user, complete_login,
)


def _page(rid: str, error: str = "") -> str:
    err_html = (
        f'<div class="error">{html.escape(error)}</div>' if error else ''
    )
    return _LOGIN_HTML.replace("__RID__", html.escape(rid)).replace("__ERROR__", err_html)


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
        return HTMLResponse(_page(rid, "Correo o contraseña incorrectos."), status_code=401)

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
# HTML (identidad Fynder: negro / verde / Inter).
# ---------------------------------------------------------------------------

FYNDER_LOGO = "https://storage.googleapis.com/cluvi/FYNDER/logo_blanco_fynder_final.png"
FINDY_AVATAR = "https://storage.googleapis.com/cluvi/FYNDER/emoji_fynder.png"
IRRELEVANT_LOGO = "https://storage.googleapis.com/cluvi/nuevo_irre-removebg-preview.png"

_BASE_STYLE = """
  :root{ --bg:#0A0A0A; --bg-2:#141414; --border:#2A2A2A; --white:#FAFAFA;
         --text:#E5E5E5; --text-2:#A3A3A3; --text-3:#6B6B6B; --green:#2AE38C; --green-d:#1FC97A; }
  *{ box-sizing:border-box; margin:0; padding:0; }
  body{ font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        background:var(--bg); color:var(--text); min-height:100vh; display:grid; place-items:center; padding:20px;
        background-image:radial-gradient(ellipse 900px 600px at 50% -10%, rgba(42,227,140,.07), transparent 60%); }
  .card{ width:100%; max-width:410px; background:linear-gradient(180deg,#0F0F0F,#0A0A0A);
         border:1px solid #1F1F1F; border-radius:22px; padding:34px 30px 26px; }
  .logo{ display:flex; justify-content:center; margin-bottom:22px; }
  .logo img{ height:30px; width:auto; }
  .findy{ display:flex; flex-direction:column; align-items:center; gap:10px; margin-bottom:4px; }
  .findy-badge{ position:relative; }
  .findy-badge img{ height:56px; width:56px; object-fit:contain; }
  .findy-badge .dot{ position:absolute; bottom:2px; right:2px; width:12px; height:12px; border-radius:50%;
         background:var(--green); border:2px solid #0A0A0A; }
  h1{ text-align:center; font-size:20px; color:var(--white); margin-top:14px; font-weight:700; }
  p.sub{ text-align:center; color:var(--text-2); font-size:14px; margin-top:6px; margin-bottom:22px; }
  label{ display:block; font-size:13px; color:var(--text-2); margin:14px 0 7px; font-weight:600; }
  input{ width:100%; padding:13px 14px; border-radius:12px; border:1px solid var(--border);
         background:var(--bg-2); color:var(--white); font-size:16px; }
  input:focus{ outline:none; border-color:var(--green); box-shadow:0 0 0 4px rgba(42,227,140,.12); }
  button{ width:100%; margin-top:22px; padding:14px; border:none; border-radius:12px; cursor:pointer;
          font-weight:700; font-size:16px; color:#04120a; font-family:inherit;
          background:linear-gradient(150deg,#5DFAAB,var(--green)); box-shadow:0 10px 30px rgba(42,227,140,.25); }
  .error{ background:rgba(255,92,92,.08); border:1px solid rgba(255,92,92,.35); color:#ffb4bd;
          padding:11px 14px; border-radius:11px; font-size:14px; margin-top:16px; text-align:center; }
  .foot{ text-align:center; color:var(--text-3); font-size:12.5px; margin-top:18px; line-height:1.6; }
  .lock{ display:inline-flex; align-items:center; gap:6px; color:var(--green); font-size:12px; font-weight:600;
         justify-content:center; width:100%; margin-top:4px; }
  .dev{ display:flex; align-items:center; justify-content:center; gap:8px; margin-top:24px;
        padding-top:20px; border-top:1px solid #1A1A1A; }
  .dev span{ color:var(--text-4,#4A4A4A); font-size:12px; }
  .dev img{ height:18px; width:auto; opacity:.6; transition:opacity .2s; }
  .dev:hover img{ opacity:1; }
"""

_DEV_BY = (f'<div class="dev"><span>Developed by</span>'
           f'<img src="{IRRELEVANT_LOGO}" alt="irrelevant"></div>')

_LOGIN_HTML = f"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Iniciar sesión · Fynder</title>
<link rel="icon" type="image/png" href="{FINDY_AVATAR}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{_BASE_STYLE}</style></head>
<body>
  <form class="card" method="post" action="/oauth/login">
    <div class="logo"><img src="{FYNDER_LOGO}" alt="Fynder"></div>
    <div class="findy">
      <div class="findy-badge"><img src="{FINDY_AVATAR}" alt="Findy"><span class="dot"></span></div>
    </div>
    <h1>Conecta a Findy con tu IA</h1>
    <p class="sub">Inicia sesión con tu cuenta de Fynder para autorizar la conexión.</p>
    __ERROR__
    <input type="hidden" name="rid" value="__RID__">
    <label>Correo electrónico</label>
    <input name="email" type="email" placeholder="tucorreo@fynder.com" autocomplete="email" required autofocus>
    <label>Contraseña</label>
    <input name="password" type="password" placeholder="••••••••" autocomplete="current-password" required>
    <button type="submit">Iniciar sesión y autorizar</button>
    <div class="lock">🔒 Conexión segura · solo autorizas el acceso a tus datos</div>
    <div class="foot">Al autorizar, tu asistente de IA podrá consultar Fynder en tu nombre.<br>Puedes revocar el acceso cuando quieras.</div>
    {_DEV_BY}
  </form>
</body></html>"""

_EXPIRED_HTML = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Enlace expirado · Fynder</title>
<link rel="icon" type="image/png" href="{FINDY_AVATAR}">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>{_BASE_STYLE}</style></head>
<body><div class="card" style="text-align:center">
  <div class="logo"><img src="{FYNDER_LOGO}" alt="Fynder"></div>
  <h1>El enlace de conexión expiró</h1>
  <p class="sub">Vuelve a tu asistente de IA e intenta agregar el conector de Fynder de nuevo.</p>
  {_DEV_BY}
</div></body></html>"""
