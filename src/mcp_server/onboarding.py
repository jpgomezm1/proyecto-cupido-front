"""
Onboarding self-service del MCP de Fynder (páginas servidas por la app remota).

Rutas:
- GET  /            -> página 0-técnica: qué es, qué puedes preguntar, y el
                       formulario para obtener el "código de acceso".
- POST /connect/token -> crea/reutiliza usuario y emite el token (JSON).
- GET  /salud       -> healthcheck simple.

Pensado para agentes inmobiliarios sin conocimientos técnicos: lenguaje simple,
pasos cortos, botones de copiar. Diseño alineado a la identidad de Fynder
(negro #0A0A0A, verde #2AE38C, tipografías Inter / Playfair Display / JetBrains Mono).
"""

import os

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from src.services.mcp_signup_service import self_register, SignupError


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


async def home(request: Request) -> HTMLResponse:
    require_code = bool(os.getenv("MCP_SIGNUP_CODE"))
    return HTMLResponse(_PAGE.replace("__REQUIRE_CODE__", "true" if require_code else "false"))


def onboarding_routes():
    return [
        Route("/", home, methods=["GET"]),
        Route("/connect", home, methods=["GET"]),
        Route("/connect/token", token_endpoint, methods=["POST"]),
        Route("/salud", health, methods=["GET"]),
    ]


# ---------------------------------------------------------------------------
# Página HTML (self-contained salvo Google Fonts). Identidad Fynder.
# ---------------------------------------------------------------------------

_PAGE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fynder para tu IA · Conecta tu asistente</title>
<meta name="description" content="Conecta Fynder a tu asistente de IA y conviértelo en un experto inmobiliario. Sin nada técnico.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Playfair+Display:ital,wght@0,600;0,700;1,600&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0A0A0A; --bg-1:#0F0F0F; --bg-2:#141414; --bg-3:#1A1A1A;
    --border:#1F1F1F; --border-hi:#2A2A2A;
    --white:#FAFAFA; --text:#E5E5E5; --text-2:#A3A3A3; --text-3:#6B6B6B; --text-4:#4A4A4A;
    --green:#2AE38C; --green-d:#1FC97A; --green-l:#5DFAAB;
    --green-soft:rgba(42,227,140,.10); --green-glow:rgba(42,227,140,.30);
    --red:#FF5C5C; --yellow:#F5C842; --blue:#5B9CFF; --purple:#B47BFF; --orange:#FF914D;
    --r:18px;
  }
  *{ margin:0; padding:0; box-sizing:border-box; }
  html{ font-size:16px; scroll-behavior:smooth; }
  body{
    font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    background:var(--bg); color:var(--text); line-height:1.6;
    -webkit-font-smoothing:antialiased; position:relative; min-height:100vh; overflow-x:hidden;
  }
  body::before{ content:''; position:fixed; inset:0; z-index:0; pointer-events:none;
    background:
      radial-gradient(ellipse 1100px 720px at 15% -5%, rgba(42,227,140,.06), transparent 60%),
      radial-gradient(ellipse 900px 640px at 90% 10%, rgba(91,156,255,.035), transparent 60%),
      radial-gradient(ellipse 900px 700px at 50% 115%, rgba(180,123,255,.03), transparent 60%); }
  body::after{ content:''; position:fixed; inset:0; z-index:0; pointer-events:none; opacity:.02;
    background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
    background-size:256px 256px; }
  ::selection{ background:var(--green-soft); color:var(--green); }
  .wrap{ position:relative; z-index:2; max-width:940px; margin:0 auto; padding:0 22px 96px; }

  /* Top bar */
  .topbar{ display:flex; align-items:center; justify-content:space-between; padding:26px 2px 8px; }
  .brand{ display:flex; align-items:center; gap:11px; }
  .mark{ width:34px; height:34px; border-radius:9px; display:grid; place-items:center;
    background:linear-gradient(150deg,var(--green),var(--green-d)); box-shadow:0 6px 22px rgba(42,227,140,.28); }
  .mark svg{ width:19px; height:19px; display:block; }
  .brand b{ font-weight:800; letter-spacing:-.02em; font-size:19px; color:var(--white); }
  .brand b span{ color:var(--green); }
  .pill{ font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:var(--text-3);
    border:1px solid var(--border-hi); border-radius:999px; padding:6px 12px; font-weight:600; }

  /* Hero */
  .hero{ text-align:center; padding:58px 0 12px; }
  .eyebrow{ display:inline-flex; align-items:center; gap:8px; font-size:12px; letter-spacing:.24em;
    text-transform:uppercase; color:var(--green); font-weight:700; margin-bottom:20px; }
  .eyebrow::before,.eyebrow::after{ content:''; width:26px; height:1px; background:linear-gradient(90deg,transparent,var(--green)); }
  .eyebrow::after{ background:linear-gradient(90deg,var(--green),transparent); }
  h1{ font-family:'Playfair Display',serif; font-weight:700; font-size:clamp(34px,6vw,58px);
    line-height:1.05; letter-spacing:-.015em; color:var(--white); }
  h1 em{ font-style:italic; background:linear-gradient(90deg,var(--green-l),var(--green));
    -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }
  .lead{ color:var(--text-2); font-size:clamp(16px,2.4vw,19px); max-width:600px; margin:22px auto 0; }
  .hero-note{ margin-top:16px; font-size:14px; color:var(--text-3); }
  .hero-note b{ color:var(--green); font-weight:600; }

  /* Section */
  .section{ margin-top:56px; }
  .kicker{ font-size:12px; letter-spacing:.2em; text-transform:uppercase; color:var(--text-3);
    font-weight:700; margin-bottom:16px; display:flex; align-items:center; gap:10px; }
  .kicker::before{ content:''; width:22px; height:2px; border-radius:2px; background:var(--green); }

  /* Ask tiles */
  .tiles{ display:grid; grid-template-columns:repeat(2,1fr); gap:14px; }
  .tile{ border:1px solid var(--border); border-radius:var(--r); padding:18px 18px 20px; position:relative;
    overflow:hidden; transition:transform .18s ease, border-color .18s ease; }
  .tile:hover{ transform:translateY(-3px); border-color:var(--border-hi); }
  .tile .ic{ width:38px; height:38px; border-radius:10px; display:grid; place-items:center; font-size:19px; margin-bottom:12px; }
  .tile p{ color:var(--white); font-weight:600; font-size:15.5px; line-height:1.4; }
  .tile small{ color:var(--text-3); font-size:12.5px; display:block; margin-top:6px; font-weight:500; }
  .t-green{ background:linear-gradient(150deg,rgba(42,227,140,.09),transparent 70%); }
  .t-green .ic{ background:rgba(42,227,140,.13); }
  .t-blue{ background:linear-gradient(150deg,rgba(91,156,255,.09),transparent 70%); }
  .t-blue .ic{ background:rgba(91,156,255,.13); }
  .t-purple{ background:linear-gradient(150deg,rgba(180,123,255,.09),transparent 70%); }
  .t-purple .ic{ background:rgba(180,123,255,.13); }
  .t-orange{ background:linear-gradient(150deg,rgba(255,145,77,.09),transparent 70%); }
  .t-orange .ic{ background:rgba(255,145,77,.13); }
  .t-yellow{ background:linear-gradient(150deg,rgba(245,200,66,.09),transparent 70%); }
  .t-yellow .ic{ background:rgba(245,200,66,.13); }
  .t-red{ background:linear-gradient(150deg,rgba(255,92,92,.08),transparent 70%); }
  .t-red .ic{ background:rgba(255,92,92,.12); }

  /* Card */
  .card{ background:linear-gradient(180deg,var(--bg-1),var(--bg)); border:1px solid var(--border);
    border-radius:22px; padding:30px; }
  .step-h{ display:flex; align-items:center; gap:14px; margin-bottom:6px; }
  .step-n{ width:34px; height:34px; border-radius:50%; flex:0 0 auto; display:grid; place-items:center;
    font-weight:800; font-size:15px; color:#04120a; background:linear-gradient(150deg,var(--green),var(--green-d)); }
  .step-h h2{ font-size:21px; font-weight:700; color:var(--white); letter-spacing:-.01em; }
  .sub{ color:var(--text-2); font-size:14.5px; margin:2px 0 8px 48px; }

  form{ margin-top:8px; }
  label{ display:block; font-size:13px; color:var(--text-2); margin:18px 0 8px; font-weight:600; }
  label .opt{ color:var(--text-3); font-weight:500; }
  input{ width:100%; padding:14px 15px; border-radius:13px; border:1px solid var(--border-hi);
    background:var(--bg-2); color:var(--white); font-size:16px; font-family:inherit; transition:border-color .15s, box-shadow .15s; }
  input::placeholder{ color:var(--text-4); }
  input:focus{ outline:none; border-color:var(--green); box-shadow:0 0 0 4px rgba(42,227,140,.12); }

  .btn{ cursor:pointer; border:none; font-family:inherit; font-weight:700; border-radius:13px; transition:transform .12s, box-shadow .2s, opacity .2s; }
  .btn-primary{ width:100%; margin-top:24px; padding:16px; font-size:16px; color:#04120a;
    background:linear-gradient(150deg,var(--green-l),var(--green)); box-shadow:0 10px 30px rgba(42,227,140,.25); }
  .btn-primary:hover{ transform:translateY(-2px); box-shadow:0 14px 40px rgba(42,227,140,.38); }
  .btn-primary:disabled{ opacity:.55; transform:none; cursor:default; box-shadow:none; }
  .btn-copy{ background:var(--bg-3); color:var(--text); border:1px solid var(--border-hi); padding:9px 15px; font-size:13px; }
  .btn-copy:hover{ border-color:var(--green); color:var(--green); }

  .error{ display:none; margin-top:16px; background:rgba(255,92,92,.08); border:1px solid rgba(255,92,92,.35);
    color:#ffb4bd; padding:13px 15px; border-radius:12px; font-size:14px; }
  .hidden{ display:none; }

  /* Success */
  .exito{ text-align:center; }
  .badge-ok{ width:64px; height:64px; border-radius:50%; margin:0 auto 8px; display:grid; place-items:center;
    background:radial-gradient(circle,var(--green-soft),transparent 70%); }
  .badge-ok div{ width:46px; height:46px; border-radius:50%; display:grid; place-items:center; font-size:24px;
    background:linear-gradient(150deg,var(--green),var(--green-d)); color:#04120a; box-shadow:0 8px 26px rgba(42,227,140,.4); }
  .exito h2{ font-family:'Playfair Display',serif; font-size:28px; color:var(--white); font-weight:700; margin-top:8px; }
  .codebox{ display:flex; gap:10px; align-items:center; background:#050b08; border:1px solid rgba(42,227,140,.35);
    border-radius:14px; padding:14px 15px; margin-top:12px; box-shadow:inset 0 0 30px rgba(42,227,140,.05); }
  .codebox code{ font-family:'JetBrains Mono',monospace; font-size:13.5px; word-break:break-all;
    color:var(--green-l); flex:1; text-align:left; }
  .tabs{ display:flex; gap:8px; margin:8px 0 16px; }
  .tab{ flex:1; background:var(--bg-2); border:1px solid var(--border-hi); color:var(--text-2);
    padding:11px; border-radius:11px; font-size:14px; font-weight:600; cursor:pointer; transition:.15s; }
  .tab.on{ color:#04120a; background:linear-gradient(150deg,var(--green),var(--green-d)); border-color:transparent; }
  ol.pasos{ list-style:none; text-align:left; }
  ol.pasos li{ display:flex; gap:13px; padding:13px 0; border-bottom:1px solid var(--border); color:var(--text); font-size:15px; }
  ol.pasos li:last-child{ border-bottom:none; }
  ol.pasos li b{ color:var(--white); }
  .dot{ flex:0 0 auto; width:24px; height:24px; border-radius:50%; background:var(--green-soft); color:var(--green);
    font-size:12.5px; font-weight:700; display:grid; place-items:center; margin-top:1px; }

  .foot{ text-align:center; color:var(--text-3); font-size:13px; margin-top:52px; line-height:1.7; }
  .foot b{ color:var(--text-2); font-weight:600; }
  a{ color:var(--green); text-decoration:none; }

  @media (max-width:640px){
    .tiles{ grid-template-columns:1fr; }
    .card{ padding:22px; }
    .sub{ margin-left:0; }
  }
</style>
</head>
<body>
<div class="wrap">

  <div class="topbar">
    <div class="brand">
      <div class="mark"><svg viewBox="0 0 24 24" fill="none"><path d="M12 2C7.9 2 4.5 5.4 4.5 9.5c0 5 7.5 12.5 7.5 12.5s7.5-7.5 7.5-12.5C19.5 5.4 16.1 2 12 2z" fill="#04120a"/><circle cx="12" cy="9.5" r="3" fill="#2AE38C"/></svg></div>
      <b>Fy<span>nder</span></b>
    </div>
    <div class="pill">Para agentes</div>
  </div>

  <div class="hero">
    <div class="eyebrow">Fynder + Inteligencia Artificial</div>
    <h1>Convierte tu IA en un<br><em>experto inmobiliario</em></h1>
    <p class="lead">Conecta Fynder a tu asistente —como Claude— y pregúntale en español
      sobre precios, demanda, comparativas y por qué una propiedad no se vende.
      Te responde con datos reales del mercado.</p>
    <p class="hero-note">⏱️ Toma <b>menos de 2 minutos</b> · sin nada técnico</p>
  </div>

  <div class="section">
    <div class="kicker">Lo que le puedes preguntar</div>
    <div class="tiles">
      <div class="tile t-green"><div class="ic">📉</div><p>¿Por qué no se me vende este apartamento?</p><small>Diagnóstico de rotación</small></div>
      <div class="tile t-blue"><div class="ic">💰</div><p>¿Cómo está el precio por m² en El Poblado?</p><small>Precios de la zona</small></div>
      <div class="tile t-purple"><div class="ic">⚖️</div><p>Compárame estas 3 propiedades</p><small>Comparativa lado a lado</small></div>
      <div class="tile t-orange"><div class="ic">🔥</div><p>¿Está caliente o fría la zona de Laureles?</p><small>Oferta vs. demanda</small></div>
      <div class="tile t-yellow"><div class="ic">🙋</div><p>¿Quién está buscando algo como esto?</p><small>Compradores potenciales</small></div>
      <div class="tile t-red"><div class="ic">🏷️</div><p>¿A cuánto capto un apto de 80m² en Sabaneta?</p><small>Precio sugerido</small></div>
    </div>
  </div>

  <div class="section" id="form-card">
    <div class="card">
      <div class="step-h"><div class="step-n">1</div><h2>Obtén tu código de acceso</h2></div>
      <p class="sub">Es tu llave personal para conectar Fynder. Guárdala: es solo tuya.</p>
      <form onsubmit="return false">
        <label>Tu nombre completo</label>
        <input id="nombre" placeholder="Ej: Lina Roldán" autocomplete="name">
        <label>Tu correo electrónico</label>
        <input id="email" type="email" placeholder="tucorreo@ejemplo.com" autocomplete="email">
        <label>Tu celular <span class="opt">· opcional, para ver “mis propiedades”</span></label>
        <input id="telefono" placeholder="Ej: 3122655340" inputmode="tel">
        <div id="code-field" class="hidden">
          <label>Código de invitación</label>
          <input id="invite" placeholder="Te lo entrega Fynder">
        </div>
        <button class="btn btn-primary" id="btn">Obtener mi código de acceso →</button>
        <div class="error" id="error"></div>
      </form>
    </div>
  </div>

  <div class="section hidden" id="exito">
    <div class="card exito">
      <div class="badge-ok"><div>✓</div></div>
      <h2>¡Listo, <span id="saludo"></span>!</h2>
      <p class="sub" style="margin-left:0">Este es tu código de acceso. <b style="color:var(--white)">Cópialo ahora</b>: no se vuelve a mostrar.</p>
      <div class="codebox"><code id="token"></code>
        <button class="btn btn-copy" onclick="copiar('token',this)">Copiar</button></div>

      <div class="step-h" style="margin-top:30px"><div class="step-n">2</div><h2>Conéctalo a tu IA</h2></div>
      <div class="tabs">
        <div class="tab on" id="tab-web" onclick="verTab('web')">Claude web / app</div>
        <div class="tab" id="tab-desk" onclick="verTab('desk')">Claude Desktop</div>
      </div>

      <div id="pane-web">
        <ol class="pasos">
          <li><span class="dot">1</span><span>Abre Claude y entra a <b>Configuración → Conectores</b>.</span></li>
          <li><span class="dot">2</span><span>Toca <b>“Agregar conector personalizado”</b>.</span></li>
          <li><span class="dot">3</span><span>Pega esta dirección de Fynder:
            <div class="codebox"><code id="url-web"></code>
              <button class="btn btn-copy" onclick="copiar('url-web',this)">Copiar</button></div></span></li>
          <li><span class="dot">4</span><span>Cuando te pida autorizarte, pega tu <b>código de acceso</b> de arriba.</span></li>
          <li><span class="dot">5</span><span>¡Guarda y listo! Ya puedes preguntarle sobre tus propiedades. 🎉</span></li>
        </ol>
      </div>
      <div id="pane-desk" class="hidden">
        <ol class="pasos">
          <li><span class="dot">1</span><span>Abre <b>Claude Desktop → Configuración → Conectores → Agregar</b>.</span></li>
          <li><span class="dot">2</span><span>Pega la misma dirección de Fynder:
            <div class="codebox"><code id="url-desk"></code>
              <button class="btn btn-copy" onclick="copiar('url-desk',this)">Copiar</button></div></span></li>
          <li><span class="dot">3</span><span>Ingresa tu <b>código de acceso</b> cuando lo solicite.</span></li>
          <li><span class="dot">4</span><span>Guarda y empieza a preguntar. 🎉</span></li>
        </ol>
      </div>
      <p class="sub" style="margin-left:0; margin-top:18px">¿Perdiste el código? Vuelve a esta página con el mismo correo y genera uno nuevo.</p>
    </div>
  </div>

  <div class="foot">
    <b>Fynder</b> · Tu inteligencia inmobiliaria, ahora dentro de tu IA.<br>
    ¿Dudas para conectarte? Escríbenos y te ayudamos.
  </div>
</div>

<script>
const REQUIRE_CODE = __REQUIRE_CODE__;
if (REQUIRE_CODE) document.getElementById('code-field').classList.remove('hidden');

function copiar(id, btn){
  const t = document.getElementById(id).innerText;
  navigator.clipboard.writeText(t).then(()=>{ const o=btn.innerText; btn.innerText='¡Copiado!'; setTimeout(()=>btn.innerText=o,1500); });
}
function verTab(w){
  document.getElementById('tab-web').classList.toggle('on', w==='web');
  document.getElementById('tab-desk').classList.toggle('on', w==='desk');
  document.getElementById('pane-web').classList.toggle('hidden', w!=='web');
  document.getElementById('pane-desk').classList.toggle('hidden', w!=='desk');
}

const btn = document.getElementById('btn');
btn.addEventListener('click', async () => {
  const err = document.getElementById('error'); err.style.display='none';
  const payload = {
    nombre: document.getElementById('nombre').value.trim(),
    email: document.getElementById('email').value.trim(),
    telefono: document.getElementById('telefono').value.trim(),
    invite_code: REQUIRE_CODE ? document.getElementById('invite').value.trim() : null,
  };
  if(!payload.nombre || !payload.email){ err.innerText='Escribe tu nombre y tu correo.'; err.style.display='block'; return; }
  btn.disabled=true; btn.innerText='Generando tu código...';
  try{
    const r = await fetch('/connect/token', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    const data = await r.json();
    if(!data.ok){ err.innerText = data.error || 'No pudimos generar tu código.'; err.style.display='block'; btn.disabled=false; btn.innerText='Obtener mi código de acceso →'; return; }
    document.getElementById('token').innerText = data.token;
    document.getElementById('url-web').innerText = data.mcp_url;
    document.getElementById('url-desk').innerText = data.mcp_url;
    document.getElementById('saludo').innerText = (data.nombre.split(' ')[0] || '');
    document.getElementById('form-card').classList.add('hidden');
    const ex = document.getElementById('exito'); ex.classList.remove('hidden');
    ex.scrollIntoView({behavior:'smooth', block:'start'});
  }catch(e){
    err.innerText='Hubo un problema de conexión. Intenta de nuevo.'; err.style.display='block';
    btn.disabled=false; btn.innerText='Obtener mi código de acceso →';
  }
});
</script>
</body>
</html>
"""
