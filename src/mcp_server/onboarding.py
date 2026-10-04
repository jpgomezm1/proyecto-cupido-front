"""
Onboarding self-service del MCP de Fynder (páginas servidas por la app remota).

Rutas:
- GET  /, /connect  -> página 0-técnica: cómo conectar Fynder a Claude o ChatGPT
                       (conector personalizado + login OAuth con la cuenta de
                       Fynder). El "código de acceso" para otros clientes (Claude
                       Code, Cursor…) queda en una sección plegada.
- POST /connect/token -> crea/reutiliza usuario y emite el token (JSON).
- GET  /salud       -> healthcheck simple.

Pensado para agentes inmobiliarios sin conocimientos técnicos: lenguaje simple,
pasos cortos, botones de copiar. Marca compartida en src/mcp_server/brand.py.
"""

import html
import os

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from src.mcp_server import brand
from src.services.mcp_signup_service import self_register, SignupError

# Ícono del servidor/conector: Claude busca el favicon en la raíz al agregar el
# MCP. Se sirve el logo de Findy para que el conector muestre esa imagen.
FINDY_ICON = brand.FINDY


def _public_url(request: Request) -> str:
    """URL pública base del MCP (para armar la dirección de conexión)."""
    env = os.getenv("MCP_PUBLIC_URL")
    if env:
        return env.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


async def token_endpoint(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Solicitud inválida."}, status_code=400)

    try:
        result = self_register(
            nombre=body.get("nombre", ""),
            email=body.get("email", ""),
            telefono=body.get("telefono") or None,
            invite_code=body.get("invite_code") or None,
            acepta_terminos=bool(body.get("acepta_terminos")),
        )
    except SignupError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception:
        return JSONResponse(
            {"ok": False, "error": "No pudimos generar tu código. Intenta de nuevo en un momento."},
            status_code=500,
        )

    result["mcp_url"] = _public_url(request) + "/mcp"
    return JSONResponse(result)


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "fynder-mcp"})


async def favicon(request: Request) -> RedirectResponse:
    """Ícono del conector/servidor: redirige al logo de Findy."""
    return RedirectResponse(url=FINDY_ICON, status_code=302)


def _resumen_planes() -> str:
    """'desde $50.000 al mes' con el plan más barato (o un texto neutro)."""
    try:
        from src.services.db import get_db
        from src.services.suscripcion_service import planes_activos
        with get_db() as db:
            planes = planes_activos(db.cursor)
        if planes:
            p = min(planes, key=lambda x: x["precio_cop"])
            return f"planes desde ${p['precio_cop']:,.0f}".replace(",", ".") + " al mes"
    except Exception:
        pass
    return "planes mensuales"


async def home(request: Request) -> HTMLResponse:
    from src.services.suscripcion_service import url_terminos
    require_code = bool(os.getenv("MCP_SIGNUP_CODE"))
    page = (_PAGE.replace("__REQUIRE_CODE__", "true" if require_code else "false")
            .replace("__URL_TERMINOS__", html.escape(url_terminos()))
            .replace("__PLANES__", html.escape(_resumen_planes()))
            .replace("__MCP_URL__", html.escape(_public_url(request) + "/mcp")))
    return HTMLResponse(page)


def onboarding_routes():
    return [
        Route("/", home, methods=["GET"]),
        Route("/connect", home, methods=["GET"]),
        Route("/connect/token", token_endpoint, methods=["POST"]),
        Route("/salud", health, methods=["GET"]),
        Route("/favicon.ico", favicon, methods=["GET"]),
        Route("/icon.png", favicon, methods=["GET"]),
    ]




# ---------------------------------------------------------------------------
# Página HTML (marca compartida: brand.py). Placeholders que llena home():
# __REQUIRE_CODE__, __URL_TERMINOS__, __PLANES__, __MCP_URL__.
# ---------------------------------------------------------------------------

_CSS = """
.hero{ padding:28px 0 8px; }
.hero h1{ margin-top:12px; font-size:34px; }
.hero .lead{ margin-top:12px; }
.section{ margin-top:28px; }
.addr-label{ font-size:13px; font-weight:600; color:var(--muted); }
.codebox{ margin-top:8px; }
.abrir{ display:inline-block; margin-top:14px; font-weight:600; font-size:14px; text-decoration:none; }
.abrir:hover{ text-decoration:underline; }
.ejemplos{ list-style:none; display:grid; gap:8px; margin-top:12px; }
.ejemplos li{ color:var(--text); font-size:14.5px; padding:10px 14px; border:1px solid var(--border);
              border-radius:var(--radius-md); background:var(--surface-1); }
.cuenta{ display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:14px; }
.cuenta p{ flex:1 1 260px; }
details.otros{ margin-top:28px; border:1px solid var(--border); border-radius:var(--radius-xl); background:var(--surface-1); }
details.otros > summary{ cursor:pointer; list-style:none; padding:18px 20px; font-weight:600; display:flex;
                         align-items:center; justify-content:space-between; gap:12px; }
details.otros > summary::-webkit-details-marker{ display:none; }
details.otros > summary::after{ content:"+"; color:var(--muted); font-size:20px; line-height:1; }
details.otros[open] > summary::after{ content:"\\2212"; }
details.otros .inner{ padding:0 20px 22px; }
.opt{ color:var(--subtle); font-weight:500; }
.chk a{ color:var(--brand); }
.ok-badge{ width:44px; height:44px; border-radius:50%; display:grid; place-items:center; font-size:22px; font-weight:800;
           background:var(--brand); color:var(--brand-ink); margin-bottom:10px; }
@media (max-width:480px){ .hero h1{ font-size:28px; } }
"""

_WA_CUENTA = brand.wa_link("Hola, quiero mi cuenta de Fynder (con los 2 desbloqueos de prueba).")
_WA_AYUDA = brand.wa_link("Hola, necesito ayuda para conectar Fynder a mi IA.")

_MAIN = """
<main id="contenido">
  <section class="hero">
    <span class="eyebrow">Fynder + tu IA</span>
    <h1>Lleva a Findy a tu IA</h1>
    <p class="lead">Conecta Fynder a Claude o ChatGPT y pregúntale en español por precios, demanda,
      comparativas o por qué una propiedad no se vende. Buscar y analizar es <b>gratis</b>. El contacto
      de quien tiene un inmueble se desbloquea con tu plan: <b>2 desbloqueos de prueba</b> al verificar
      tu celular y __PLANES__.</p>
  </section>

  <section class="section card" aria-labelledby="conectar-titulo">
    <h2 id="conectar-titulo">Conéctalo en 2 minutos</h2>
    <p class="addr-label" id="mcp-label" style="margin-top:14px">Dirección de Fynder para tu IA</p>
    <div class="codebox"><code id="mcp-url" aria-labelledby="mcp-label">__MCP_URL__</code>
      <button type="button" data-copiar="mcp-url" aria-label="Copiar la dirección de Fynder">Copiar</button></div>

    <div class="tabs" role="tablist" aria-label="Elige tu IA" style="margin-top:20px">
      <button type="button" role="tab" id="tab-claude" aria-selected="true" aria-controls="panel-claude" tabindex="0">Claude</button>
      <button type="button" role="tab" id="tab-chatgpt" aria-selected="false" aria-controls="panel-chatgpt" tabindex="-1">ChatGPT</button>
    </div>

    <div role="tabpanel" id="panel-claude" aria-labelledby="tab-claude" tabindex="0">
      <ol class="steps">
        <li><div><b>Abre los conectores de Claude</b><br><span class="muted">En claude.ai o en la app:
          Configuración → Conectores → Agregar conector personalizado.</span></div></li>
        <li><div><b>Pega la dirección de Fynder</b><br><span class="muted">Ponle de nombre «Fynder», pega
          la dirección de arriba y toca Agregar.</span></div></li>
        <li><div><b>Inicia sesión con tu cuenta de Fynder</b><br><span class="muted">Toca Conectar y entra
          con tu correo y tu clave de Fynder. Listo: pregúntale a Claude.</span></div></li>
      </ol>
      <a class="abrir" href="https://claude.ai/settings/connectors" target="_blank" rel="noopener noreferrer">Abrir Claude →</a>
    </div>

    <div class="hidden" role="tabpanel" id="panel-chatgpt" aria-labelledby="tab-chatgpt" tabindex="0">
      <ol class="steps">
        <li><div><b>Activa el modo desarrollador</b><br><span class="muted">En ChatGPT: Configuración →
          Aplicaciones y conectores → Configuración avanzada → Modo desarrollador.</span></div></li>
        <li><div><b>Crea el conector de Fynder</b><br><span class="muted">Toca Crear, ponle de nombre
          «Fynder», pega la dirección de arriba y elige autenticación OAuth.</span></div></li>
        <li><div><b>Inicia sesión con tu cuenta de Fynder</b><br><span class="muted">Entra con tu correo y
          tu clave de Fynder, y actívalo en el chat desde el menú +.</span></div></li>
      </ol>
      <a class="abrir" href="https://chatgpt.com/#settings/Connectors" target="_blank" rel="noopener noreferrer">Abrir ChatGPT →</a>
    </div>
  </section>

  <section class="section card cuenta" aria-labelledby="cuenta-titulo">
    <p><b id="cuenta-titulo">¿No tienes cuenta? Pídela por WhatsApp</b><br><span class="muted">Te la
      creamos con tu correo y clave, e incluye 2 desbloqueos de prueba.</span></p>
    <a class="btn btn-primary" href="__WA_CUENTA__" target="_blank" rel="noopener noreferrer">Pedir mi cuenta</a>
  </section>

  <section class="section" aria-labelledby="ejemplos-titulo">
    <h2 id="ejemplos-titulo">Pregúntale cosas como</h2>
    <ul class="ejemplos">
      <li>¿Por qué no se me vende este apartamento?</li>
      <li>¿Cómo está el precio por m² en El Poblado?</li>
      <li>Compárame estas 3 propiedades para mi cliente.</li>
      <li>¿A cuánto capto un apto de 80 m² en Sabaneta?</li>
    </ul>
  </section>

  <details class="otros" id="otros">
    <summary>Otros clientes (Claude Code, Cursor…) — código de acceso</summary>
    <div class="inner">
      <div id="form-card">
        <p class="muted">Si tu cliente de IA no permite iniciar sesión con tu cuenta, genera un código de
          acceso personal y úsalo como token. Es solo tuyo: guárdalo.</p>
        <form id="form-token" novalidate>
          <div class="field"><label for="nombre">Tu nombre completo</label>
            <input id="nombre" name="nombre" placeholder="Ej: Lina Roldán" autocomplete="name" required aria-describedby="error"></div>
          <div class="field"><label for="email">Tu correo electrónico</label>
            <input id="email" name="email" type="email" placeholder="tucorreo@ejemplo.com" autocomplete="email" required aria-describedby="error"></div>
          <div class="field"><label for="telefono">Tu celular <span class="opt">· Fynder lo verifica para darte tus 2 desbloqueos de prueba y mostrarte “mis propiedades”</span></label>
            <input id="telefono" name="telefono" placeholder="Ej: 3122655340" inputmode="tel" autocomplete="tel"></div>
          <div class="field hidden" id="code-field"><label for="invite">Código de invitación</label>
            <input id="invite" name="invite" placeholder="Te lo entrega Fynder" aria-describedby="error"></div>
          <label class="chk" for="terminos"><input type="checkbox" id="terminos" name="acepta_terminos" aria-describedby="error">
            <span>Acepto los <a href="__URL_TERMINOS__" target="_blank" rel="noopener">términos de uso y el tratamiento de mis datos</a> de Fynder</span></label>
          <div class="alert-error hidden" id="error" role="alert"></div>
          <button type="submit" class="btn btn-primary btn-block" id="btn" style="margin-top:20px">Obtener mi código de acceso</button>
        </form>
      </div>

      <div class="hidden" id="exito" tabindex="-1">
        <div class="ok-badge" aria-hidden="true">✓</div>
        <h2>¡Listo, <span id="saludo"></span>!</h2>
        <p class="muted" style="margin-top:6px">Este es tu código de acceso. <b>Cópialo ahora</b>: no se vuelve a mostrar.</p>
        <div class="codebox"><code id="token"></code><button type="button" data-copiar="token" aria-label="Copiar el código de acceso">Copiar</button></div>
        <p class="addr-label" style="margin-top:16px">Dirección del servidor</p>
        <div class="codebox"><code id="url-token"></code><button type="button" data-copiar="url-token" aria-label="Copiar la dirección del servidor">Copiar</button></div>
        <ol class="steps">
          <li><div>En tu cliente (Claude Code, Cursor u otro) agrega un servidor MCP remoto con la dirección de arriba.</div></li>
          <li><div>Cuando te pida autorización, usa tu <b>código de acceso</b> como token.</div></li>
        </ol>
        <p class="muted" style="margin-top:14px">¿Perdiste el código? Vuelve a esta página con el mismo correo y genera uno nuevo.</p>
      </div>
    </div>
  </details>

  <p class="muted" style="margin-top:24px; text-align:center">¿Dudas para conectarte?
    <a href="__WA_AYUDA__" target="_blank" rel="noopener noreferrer">Escríbenos por WhatsApp</a> y te ayudamos.</p>
</main>
"""

_SCRIPT = r"""<script>
const REQUIRE_CODE = __REQUIRE_CODE__;
if (REQUIRE_CODE) document.getElementById('code-field').classList.remove('hidden');

document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-copiar]'); if (!b) return;
  const t = document.getElementById(b.dataset.copiar).innerText;
  navigator.clipboard.writeText(t).then(() => {
    const o = b.innerText; b.innerText = '¡Copiado!'; setTimeout(() => b.innerText = o, 1500);
  });
});

// Pestañas accesibles (Claude / ChatGPT): clic, flechas, Inicio y Fin.
const tabs = Array.from(document.querySelectorAll('[role=tab]'));
function elegir(tab, foco){
  tabs.forEach((t) => {
    const on = t === tab;
    t.setAttribute('aria-selected', on ? 'true' : 'false');
    t.tabIndex = on ? 0 : -1;
    document.getElementById(t.getAttribute('aria-controls')).classList.toggle('hidden', !on);
  });
  if (foco) tab.focus();
}
tabs.forEach((t, i) => {
  t.addEventListener('click', () => elegir(t, false));
  t.addEventListener('keydown', (e) => {
    let j = null;
    if (e.key === 'ArrowRight') j = (i + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') j = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') j = 0;
    else if (e.key === 'End') j = tabs.length - 1;
    if (j !== null){ e.preventDefault(); elegir(tabs[j], true); }
  });
});

// Código de acceso (otros clientes): mismo payload de siempre a /connect/token.
const form = document.getElementById('form-token');
const btn = document.getElementById('btn');
const err = document.getElementById('error');
const TXT_BTN = 'Obtener mi código de acceso';
function mostrarError(msg, campo){
  err.innerText = msg; err.classList.remove('hidden');
  if (campo){ campo.setAttribute('aria-invalid', 'true'); campo.focus(); }
}
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  err.classList.add('hidden');
  form.querySelectorAll('[aria-invalid]').forEach((el) => el.removeAttribute('aria-invalid'));
  const payload = {
    nombre: document.getElementById('nombre').value.trim(),
    email: document.getElementById('email').value.trim(),
    telefono: document.getElementById('telefono').value.trim(),
    invite_code: REQUIRE_CODE ? document.getElementById('invite').value.trim() : null,
    acepta_terminos: document.getElementById('terminos').checked,
  };
  if (!payload.nombre){ mostrarError('Escribe tu nombre y tu correo.', document.getElementById('nombre')); return; }
  if (!payload.email){ mostrarError('Escribe tu nombre y tu correo.', document.getElementById('email')); return; }
  if (!payload.acepta_terminos){ mostrarError('Para continuar, acepta los términos de Fynder.', document.getElementById('terminos')); return; }
  btn.disabled = true; btn.innerText = 'Generando tu código…';
  try{
    const r = await fetch('/connect/token', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    const data = await r.json();
    if (!data.ok){ mostrarError(data.error || 'No pudimos generar tu código.'); btn.disabled = false; btn.innerText = TXT_BTN; return; }
    document.getElementById('token').innerText = data.token;
    document.getElementById('url-token').innerText = data.mcp_url;
    document.getElementById('saludo').innerText = ((data.nombre || '').split(' ')[0] || '');
    document.getElementById('form-card').classList.add('hidden');
    const ex = document.getElementById('exito'); ex.classList.remove('hidden'); ex.focus();
  }catch(_){
    mostrarError('Hubo un problema de conexión. Intenta de nuevo.');
    btn.disabled = false; btn.innerText = TXT_BTN;
  }
});
if (location.hash === '#otros') document.getElementById('otros').open = true;
</script>"""


def _build_page() -> str:
    body = ('<div class="wrap">' + brand.header("Para agentes")
            + _MAIN.replace("__WA_CUENTA__", html.escape(_WA_CUENTA)).replace("__WA_AYUDA__", html.escape(_WA_AYUDA))
            + brand.footer() + "</div>")
    return brand.page("Conecta Fynder a tu IA · Fynder", body, extra_css=_CSS, scripts=_SCRIPT)


_PAGE = _build_page()
