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

_BASE_STYLE = """
  :root{ --bg:#0A0A0A; --bg-2:#141414; --border:#2A2A2A; --white:#FAFAFA;
         --text:#E5E5E5; --text-2:#A3A3A3; --text-3:#6B6B6B; --green:#2AE38C; --green-d:#1FC97A; }
  *{ box-sizing:border-box; margin:0; padding:0; }
  body{ font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        background:var(--bg); color:var(--text); min-height:100vh; display:grid; place-items:center; padding:20px;
        background-image:radial-gradient(ellipse 900px 600px at 50% -10%, rgba(42,227,140,.07), transparent 60%); }
  .card{ width:100%; max-width:400px; background:linear-gradient(180deg,#0F0F0F,#0A0A0A);
         border:1px solid #1F1F1F; border-radius:22px; padding:34px 30px; }
  .brand{ display:flex; align-items:center; gap:10px; justify-content:center; margin-bottom:6px; }
  .mark{ width:34px; height:34px; border-radius:9px; display:grid; place-items:center;
         background:linear-gradient(150deg,var(--green),var(--green-d)); }
  .mark svg{ width:19px; height:19px; }
  .brand b{ font-weight:800; font-size:19px; color:var(--white); letter-spacing:-.02em; }
  .brand b span{ color:var(--green); }
  h1{ text-align:center; font-size:20px; color:var(--white); margin-top:16px; font-weight:700; }
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
  .foot{ text-align:center; color:var(--text-3); font-size:12.5px; margin-top:20px; line-height:1.6; }
  .lock{ display:inline-flex; align-items:center; gap:6px; color:var(--green); font-size:12px; font-weight:600;
         justify-content:center; width:100%; margin-top:4px; }
"""

_MARK_SVG = ('<div class="mark"><svg viewBox="0 0 24 24" fill="none">'
             '<path d="M12 2C7.9 2 4.5 5.4 4.5 9.5c0 5 7.5 12.5 7.5 12.5s7.5-7.5 7.5-12.5C19.5 5.4 16.1 2 12 2z" fill="#04120a"/>'
             '<circle cx="12" cy="9.5" r="3" fill="#2AE38C"/></svg></div>')

_LOGIN_HTML = f"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Iniciar sesión · Fynder</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{_BASE_STYLE}</style></head>
<body>
  <form class="card" method="post" action="/oauth/login">
    <div class="brand">{_MARK_SVG}<b>Fy<span>nder</span></b></div>
    <h1>Conecta tu IA con Fynder</h1>
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
  </form>
</body></html>"""

_EXPIRED_HTML = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Enlace expirado · Fynder</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>{_BASE_STYLE}</style></head>
<body><div class="card" style="text-align:center">
  <div class="brand">{_MARK_SVG}<b>Fy<span>nder</span></b></div>
  <h1>El enlace de conexión expiró</h1>
  <p class="sub">Vuelve a tu asistente de IA e intenta agregar el conector de Fynder de nuevo.</p>
</div></body></html>"""
