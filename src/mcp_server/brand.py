"""
Marca Fynder para las páginas HTML que sirve el servidor MCP (onboarding,
login OAuth, subir fotos). Sin build: un string de CSS y helpers de layout.

Mantener en sync con mvp-tu360/src/index.css (bloque `.dark`) y
mvp-tu360/src/config/brand.ts.
"""

import html
import os

LOGO = "https://storage.googleapis.com/cluvi/FYNDER/logo_blanco_fynder_final.png"
FINDY = "https://storage.googleapis.com/cluvi/FYNDER/emoji_fynder.png"
IRRELEVANT = "https://storage.googleapis.com/cluvi/nuevo_irre-removebg-preview.png"
WHATSAPP_VENTAS = "573183351733"


def frontend_url() -> str:
    return os.getenv("FYNDER_FRONTEND_URL", "https://fyndercol.netlify.app").rstrip("/")


def wa_link(texto: str = "") -> str:
    from urllib.parse import quote
    return f"https://wa.me/{WHATSAPP_VENTAS}" + (f"?text={quote(texto)}" if texto else "")


BRAND_CSS = """
:root{
  --bg:#0A0A0A; --surface-1:#0F0F0F; --surface-2:#141414; --surface-3:#1A1A1A;
  --border:#1F1F1F; --input:#2A2A2A;
  --text:#FAFAFA; --muted:#A3A3A3; --subtle:#6B6B6B;
  --brand:#2AE38C; --brand-hi:#5DFAAB; --brand-ink:#04120A; --brand-soft:rgba(42,227,140,.10);
  --danger:#FF5C5C;
  --radius-sm:8px; --radius-md:10px; --radius-lg:12px; --radius-xl:16px;
  color-scheme:dark;
}
*{ box-sizing:border-box; margin:0; padding:0; }
html,body{ background:var(--bg); color:var(--text); }
body{ font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; font-size:15px;
      line-height:1.55; min-height:100vh; -webkit-font-smoothing:antialiased;
      background-image:radial-gradient(ellipse 900px 520px at 50% -12%, rgba(42,227,140,.08), transparent 60%); }
a{ color:var(--brand); }
img{ max-width:100%; }
.wrap{ width:100%; max-width:720px; margin:0 auto; padding:0 20px; }
.wrap-sm{ width:100%; max-width:420px; margin:0 auto; padding:0 20px; }
.topbar{ display:flex; align-items:center; justify-content:space-between; padding:20px 0; }
.topbar .logo img{ height:26px; width:auto; display:block; }
.pill{ font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted);
       border:1px solid var(--border); border-radius:999px; padding:5px 11px; }
.card{ background:linear-gradient(180deg,var(--surface-1),var(--bg)); border:1px solid var(--border);
       border-radius:var(--radius-xl); padding:28px 24px; }
.eyebrow{ display:inline-flex; align-items:center; gap:8px; font-size:12px; font-weight:600;
          letter-spacing:.14em; text-transform:uppercase; color:var(--brand); }
h1{ font-size:28px; line-height:1.15; letter-spacing:-.02em; font-weight:800; }
h2{ font-size:18px; font-weight:700; letter-spacing:-.01em; }
.lead{ color:var(--muted); font-size:15.5px; }
.muted{ color:var(--muted); } .subtle{ color:var(--subtle); }
.btn{ display:inline-flex; align-items:center; justify-content:center; gap:8px; border:1px solid var(--border);
      background:var(--surface-2); color:var(--text); border-radius:var(--radius-md); padding:12px 18px;
      font:600 15px/1 inherit; font-family:inherit; cursor:pointer; text-decoration:none; transition:filter .15s, background .15s; }
.btn:hover{ background:var(--surface-3); }
.btn-primary{ background:linear-gradient(150deg,var(--brand-hi),var(--brand)); color:var(--brand-ink); border:none;
              box-shadow:0 10px 30px rgba(42,227,140,.22); }
.btn-primary:hover{ filter:brightness(1.06); background:linear-gradient(150deg,var(--brand-hi),var(--brand)); }
.btn-block{ width:100%; }
.btn:disabled{ opacity:.55; cursor:not-allowed; }
.field{ margin-top:16px; }
.field label{ display:block; font-size:13px; font-weight:600; color:var(--muted); margin-bottom:7px; }
.field input{ width:100%; padding:12px 14px; border-radius:var(--radius-md); border:1px solid var(--input);
              background:var(--surface-2); color:var(--text); font-size:16px; font-family:inherit; }
.field input:focus{ outline:none; border-color:var(--brand); box-shadow:0 0 0 4px rgba(42,227,140,.14); }
.pwd{ position:relative; } .pwd input{ padding-right:84px; }
.pwd button{ position:absolute; right:8px; top:50%; transform:translateY(-50%); background:none; border:none;
             color:var(--muted); font:600 12px inherit; font-family:inherit; cursor:pointer; padding:6px 8px; }
.chk{ display:flex; gap:10px; align-items:flex-start; margin-top:18px; font-size:14px; color:var(--muted); line-height:1.45; }
.chk input{ width:18px; height:18px; margin-top:2px; flex:none; accent-color:var(--brand); }
.alert-error{ background:rgba(255,92,92,.08); border:1px solid rgba(255,92,92,.35); color:#FFB4B4;
              border-radius:var(--radius-md); padding:11px 14px; font-size:14px; margin-top:16px; }
.codebox{ display:flex; align-items:center; gap:8px; background:var(--surface-2); border:1px solid var(--border);
          border-radius:var(--radius-md); padding:6px 6px 6px 12px; }
.codebox code{ flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
               font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:13.5px; color:var(--brand-hi); }
.codebox button{ flex:none; background:var(--brand); color:var(--brand-ink); border:none; border-radius:8px;
                 padding:8px 12px; font:700 12.5px inherit; font-family:inherit; cursor:pointer; }
.tabs{ display:flex; gap:6px; padding:4px; background:var(--surface-2); border:1px solid var(--border);
       border-radius:999px; width:max-content; max-width:100%; }
.tabs [role=tab]{ border:none; background:transparent; color:var(--muted); font:600 14px inherit; font-family:inherit;
                  padding:8px 16px; border-radius:999px; cursor:pointer; }
.tabs [role=tab][aria-selected=true]{ background:var(--brand); color:var(--brand-ink); }
.steps{ list-style:none; counter-reset:paso; display:grid; gap:12px; margin-top:16px; }
.steps li{ counter-increment:paso; display:grid; grid-template-columns:30px 1fr; gap:12px; align-items:start;
           background:var(--surface-1); border:1px solid var(--border); border-radius:var(--radius-lg); padding:14px; }
.steps li::before{ content:counter(paso); width:30px; height:30px; border-radius:50%; display:grid; place-items:center;
                   background:var(--brand-soft); color:var(--brand); font-weight:800; font-size:14px; }
.steps b{ color:var(--text); }
.foot{ text-align:center; color:var(--subtle); font-size:12.5px; margin:28px 0 24px; }
.dev{ display:flex; align-items:center; justify-content:center; gap:8px; margin-top:12px; }
.dev span{ font-size:12px; color:var(--subtle); } .dev img{ height:16px; width:auto; opacity:.6; }
.sr-only{ position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); border:0; }
.hidden{ display:none !important; }
:focus-visible{ outline:2px solid var(--brand); outline-offset:2px; }
@media (prefers-reduced-motion: reduce){ *{ animation:none !important; transition:none !important; } }
@media (max-width:480px){ h1{ font-size:24px; } .card{ padding:22px 18px; } }
"""


def header(pill: str = "") -> str:
    p = f'<span class="pill">{html.escape(pill)}</span>' if pill else ""
    return (f'<header class="topbar"><a class="logo" href="{frontend_url()}/" aria-label="Fynder">'
            f'<img src="{LOGO}" alt="Fynder"></a>{p}</header>')


def footer() -> str:
    return (f'<footer class="foot"><p>Fynder · Inteligencia inmobiliaria para agentes en Colombia · '
            f'<a href="{frontend_url()}/terminos">Términos</a></p>'
            f'<div class="dev"><span>Developed by</span><img src="{IRRELEVANT}" alt="irrelevant"></div></footer>')


def page(title: str, body: str, *, extra_css: str = "", scripts: str = "") -> str:
    """Documento HTML completo con la marca."""
    return f"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0A0A0A">
<title>{html.escape(title)}</title>
<link rel="icon" type="image/png" href="{FINDY}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{BRAND_CSS}{extra_css}</style></head>
<body>{body}{scripts}</body></html>"""
