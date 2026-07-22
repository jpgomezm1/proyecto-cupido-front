"""
Páginas compartibles con el cliente final: comparativa y brochure de inmuebles.

Renderizadas server-side (HTML directo, sin auth) a partir de un token firmado.
Diseño con identidad Fynder, pensadas para verse en el celular del cliente.
Registran la apertura en share_events (tracking).
"""

import html
from typing import Any, Dict, List

from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

from src.services import share_service as sh

FYNDER_LOGO = "https://storage.googleapis.com/cluvi/FYNDER/logo_blanco_fynder_final.png"
FINDY = "https://storage.googleapis.com/cluvi/FYNDER/emoji_fynder.png"
IRRELEVANT = "https://storage.googleapis.com/cluvi/nuevo_irre-removebg-preview.png"


# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------

async def comparar_page(request: Request) -> HTMLResponse:
    token = request.query_params.get("t", "")
    try:
        payload = sh.verify_token(token)
    except sh.ShareError:
        return HTMLResponse(_expired(), status_code=400)
    if payload.get("k") != "cmp":
        return HTMLResponse(_expired(), status_code=400)
    ids = payload.get("ids", [])
    data = sh.datos_comparativa(ids)
    if data.get("error"):
        return HTMLResponse(_expired(), status_code=404)
    sh.registrar_vista("comparativa", ids, request.headers.get("x-forwarded-for"))
    return HTMLResponse(_render_comparativa(data))


async def ficha_page(request: Request) -> HTMLResponse:
    token = request.query_params.get("t", "")
    try:
        payload = sh.verify_token(token)
    except sh.ShareError:
        return HTMLResponse(_expired(), status_code=400)
    if payload.get("k") != "fic":
        return HTMLResponse(_expired(), status_code=400)
    ids = payload.get("ids", [])
    data = sh.datos_brochure(ids[0]) if ids else {"error": 1}
    if data.get("error"):
        return HTMLResponse(_expired(), status_code=404)
    sh.registrar_vista("brochure", ids, request.headers.get("x-forwarded-for"))
    return HTMLResponse(_render_brochure(data))


def share_pages_routes():
    return [
        Route("/comparar", comparar_page, methods=["GET"]),
        Route("/ficha", ficha_page, methods=["GET"]),
    ]


# --------------------------------------------------------------------------
# Estilos (identidad Fynder)
# --------------------------------------------------------------------------

_STYLE = """
  :root{ --bg:#0A0A0A; --bg-1:#0F0F0F; --bg-2:#141414; --border:#1F1F1F; --border-hi:#2A2A2A;
         --white:#FAFAFA; --text:#E5E5E5; --text-2:#A3A3A3; --text-3:#6B6B6B; --text-4:#4A4A4A;
         --green:#2AE38C; --green-d:#1FC97A; --green-l:#5DFAAB; --blue:#5B9CFF; --purple:#B47BFF; --yellow:#F5C842; }
  *{ box-sizing:border-box; margin:0; padding:0; }
  body{ font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:var(--bg);
        color:var(--text); -webkit-font-smoothing:antialiased; min-height:100vh;
        background-image:radial-gradient(ellipse 900px 620px at 50% -8%, rgba(42,227,140,.07), transparent 60%); }
  .wrap{ max-width:1000px; margin:0 auto; padding:0 18px 60px; }
  .top{ display:flex; align-items:center; justify-content:space-between; padding:20px 2px 6px; }
  .brand{ display:flex; align-items:center; gap:10px; }
  .brand img.logo{ height:24px; }
  .findy{ position:relative; }
  .findy img{ height:32px; width:32px; object-fit:contain; }
  .findy .dot{ position:absolute; bottom:1px; right:1px; width:8px; height:8px; border-radius:50%; background:var(--green); border:2px solid var(--bg); }
  .pill{ font-size:10.5px; letter-spacing:.14em; text-transform:uppercase; color:var(--text-3);
         border:1px solid var(--border-hi); border-radius:999px; padding:5px 11px; font-weight:600; }
  h1{ font-size:26px; color:var(--white); font-weight:800; letter-spacing:-.02em; margin-top:22px; }
  .lead{ color:var(--text-2); font-size:15px; margin-top:6px; }

  /* Comparativa */
  .cmp{ display:grid; gap:14px; margin-top:22px; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); }
  .col{ background:linear-gradient(180deg,var(--bg-1),var(--bg)); border:1px solid var(--border); border-radius:20px; overflow:hidden; }
  .col .ph{ aspect-ratio:16/11; background:var(--bg-2); position:relative; }
  .col .ph img{ width:100%; height:100%; object-fit:cover; }
  .col .badges{ position:absolute; top:8px; left:8px; display:flex; flex-direction:column; gap:5px; }
  .badge{ font-size:10.5px; font-weight:700; text-transform:uppercase; letter-spacing:.03em; border-radius:7px; padding:3px 8px; }
  .b-green{ background:var(--green); color:#04120a; } .b-blue{ background:var(--blue); color:#04120a; } .b-purple{ background:var(--purple); color:#04120a; }
  .col .body{ padding:16px; }
  .col .price{ font-size:21px; font-weight:800; color:var(--white); }
  .col .m2{ font-size:12.5px; color:var(--green); font-weight:600; margin-top:2px; }
  .col .tt{ font-size:14px; color:var(--text); margin-top:8px; font-weight:600; line-height:1.3; }
  .col .loc{ font-size:12.5px; color:var(--text-3); margin-top:3px; }
  .specs{ display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:14px; }
  .spec{ background:var(--bg-2); border:1px solid var(--border); border-radius:10px; padding:8px 10px; }
  .spec .k{ font-size:10.5px; color:var(--text-3); text-transform:uppercase; letter-spacing:.04em; }
  .spec .v{ font-size:14px; color:var(--white); font-weight:700; margin-top:1px; }
  .amen{ margin-top:14px; display:flex; flex-wrap:wrap; gap:6px; }
  .amen span{ font-size:11px; color:var(--text-2); background:var(--bg-2); border:1px solid var(--border); border-radius:999px; padding:3px 9px; }

  /* Brochure */
  .hero{ margin-top:20px; border-radius:24px; overflow:hidden; border:1px solid var(--border); position:relative; }
  .hero img{ width:100%; aspect-ratio:16/9; object-fit:cover; display:block; }
  .hero .grad{ position:absolute; inset:0; background:linear-gradient(0deg,rgba(0,0,0,.85),transparent 55%); }
  .hero .info{ position:absolute; left:0; right:0; bottom:0; padding:22px; }
  .hero .price{ font-size:30px; font-weight:800; color:#fff; }
  .hero .tt{ font-size:17px; color:#fff; font-weight:600; margin-top:4px; }
  .hero .loc{ font-size:13px; color:rgba(255,255,255,.8); margin-top:2px; }
  .kpis{ display:grid; grid-template-columns:repeat(auto-fit,minmax(90px,1fr)); gap:10px; margin-top:16px; }
  .kpi{ background:linear-gradient(180deg,var(--bg-1),var(--bg)); border:1px solid var(--border); border-radius:14px; padding:14px 10px; text-align:center; }
  .kpi .v{ font-size:20px; font-weight:800; color:var(--green); } .kpi .k{ font-size:11px; color:var(--text-3); margin-top:2px; }
  .sec{ margin-top:26px; } .sec h2{ font-size:15px; color:var(--white); font-weight:700; margin-bottom:10px; }
  .desc{ color:var(--text-2); font-size:14.5px; line-height:1.7; white-space:pre-line; }
  .gal{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-top:8px; }
  .gal img{ width:100%; aspect-ratio:1; object-fit:cover; border-radius:12px; border:1px solid var(--border); }

  .foot{ display:flex; align-items:center; justify-content:center; gap:8px; margin-top:40px; padding-top:22px; border-top:1px solid #161616;
         color:var(--text-4); font-size:12px; } .foot img{ height:15px; opacity:.6; }
  .powered{ text-align:center; color:var(--text-3); font-size:12.5px; margin-top:14px; }
  .powered b{ color:var(--green); }
"""


def _head(title: str) -> str:
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{html.escape(title)}</title>'
            f'<link rel="icon" type="image/png" href="{FINDY}">'
            f'<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            f'<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">'
            f'<style>{_STYLE}</style></head><body><div class="wrap">')


def _topbar(pill: str) -> str:
    return (f'<div class="top"><div class="brand">'
            f'<span class="findy"><img src="{FINDY}" alt="Findy"><span class="dot"></span></span>'
            f'<img class="logo" src="{FYNDER_LOGO}" alt="Fynder"></div>'
            f'<div class="pill">{html.escape(pill)}</div></div>')


def _foot() -> str:
    return (f'<div class="powered">Presentado con <b>Fynder</b> · tu asesor inmobiliario</div>'
            f'<div class="foot"><span>Developed by</span><img src="{IRRELEVANT}" alt="irrelevant"></div>'
            f'</div></body></html>')


def _esc(v) -> str:
    return html.escape(str(v)) if v is not None else ""


def _spec(k: str, v) -> str:
    if v is None or v == "":
        return ""
    return f'<div class="spec"><div class="k">{_esc(k)}</div><div class="v">{_esc(v)}</div></div>'


def _img(url, cls: str = "") -> str:
    if not url:
        return ""
    c = f' class="{cls}"' if cls else ""
    return f'<img{c} src="{_esc(url)}">'


def _render_comparativa(data: Dict[str, Any]) -> str:
    props: List[Dict[str, Any]] = data["propiedades"]
    ver = data["veredicto"]
    n = len(props)
    cols = []
    for p in props:
        badges = ""
        if p["id"] == ver.get("mejor_valor"):
            badges += '<span class="badge b-green">Mejor valor</span>'
        if p["id"] == ver.get("mas_economica"):
            badges += '<span class="badge b-blue">Más económica</span>'
        if p["id"] == ver.get("mas_amplia"):
            badges += '<span class="badge b-purple">Más amplia</span>'
        img = p.get("imagen_principal") or (p["imagenes"][0] if p.get("imagenes") else "")
        m2 = f'{sh.format_cop(p["precio_m2"])}/m²' if p.get("precio_m2") else ""
        specs = "".join([
            _spec("Área", f'{p["area"]:.0f} m²' if p.get("area") else None),
            _spec("Habitaciones", p.get("habitaciones")),
            _spec("Baños", p.get("banos")),
            _spec("Parqueaderos", p.get("parqueaderos")),
            _spec("Estrato", p.get("estrato")),
            _spec("Precio/m²", m2 or None),
        ])
        amen = "".join(f'<span>{_esc(a)}</span>' for a in (p.get("amenidades") or [])[:6])
        amen_html = f'<div class="amen">{amen}</div>' if amen else ""
        m2_html = f'<div class="m2">{m2}</div>' if m2 else ""
        sep = " · " if (p.get("zona") and p.get("ciudad")) else ""
        loc = f'{_esc(p.get("zona") or "")}{sep}{_esc(p.get("ciudad") or "")}'
        cols.append(
            '<div class="col"><div class="ph">'
            + _img(img)
            + f'<div class="badges">{badges}</div></div>'
            + f'<div class="body"><div class="price">{_esc(p.get("precio_legible"))}</div>'
            + m2_html
            + f'<div class="tt">{_esc(p.get("titulo"))}</div>'
            + f'<div class="loc">{loc}</div>'
            + f'<div class="specs">{specs}</div>{amen_html}</div></div>')
    return (_head("Comparativa de propiedades · Fynder")
            + _topbar("Comparativa")
            + f'<h1>Comparativa de {n} propiedades</h1>'
            + '<p class="lead">Mira las opciones lado a lado y elige la que más te convenga.</p>'
            + f'<div class="cmp">{"".join(cols)}</div>'
            + _foot())


def _render_brochure(data: Dict[str, Any]) -> str:
    p = data["propiedad"]
    img = p.get("imagen_principal") or (p["imagenes"][0] if p.get("imagenes") else "")
    kpis = "".join([
        f'<div class="kpi"><div class="v">{p["area"]:.0f}</div><div class="k">m²</div></div>' if p.get("area") else "",
        f'<div class="kpi"><div class="v">{_esc(p["habitaciones"])}</div><div class="k">Habitaciones</div></div>' if p.get("habitaciones") else "",
        f'<div class="kpi"><div class="v">{_esc(p["banos"])}</div><div class="k">Baños</div></div>' if p.get("banos") else "",
        f'<div class="kpi"><div class="v">{_esc(p["parqueaderos"])}</div><div class="k">Parqueaderos</div></div>' if p.get("parqueaderos") else "",
        f'<div class="kpi"><div class="v">{_esc(p["estrato"])}</div><div class="k">Estrato</div></div>' if p.get("estrato") else "",
    ])
    amen = "".join(f'<span>{_esc(a)}</span>' for a in (p.get("amenidades") or []))
    amen_html = f'<div class="sec"><h2>Amenidades</h2><div class="amen">{amen}</div></div>' if amen else ""
    desc_html = f'<div class="sec"><h2>Descripción</h2><div class="desc">{_esc(p.get("descripcion"))}</div></div>' if p.get("descripcion") else ""
    galeria = [u for u in (p.get("imagenes") or []) if u][1:10]
    gal_html = ('<div class="sec"><h2>Galería</h2><div class="gal">'
                + "".join(_img(u) for u in galeria) + "</div></div>") if galeria else ""
    sep = " · " if (p.get("zona") and p.get("ciudad")) else ""
    loc = f'{_esc(p.get("zona") or "")}{sep}{_esc(p.get("ciudad") or "")}'
    return (_head(f'{p.get("titulo") or "Propiedad"} · Fynder')
            + _topbar("Ficha")
            + f'<div class="hero">{_img(img)}<div class="grad"></div>'
            + f'<div class="info"><div class="price">{_esc(p.get("precio_legible"))}</div>'
            + f'<div class="tt">{_esc(p.get("titulo"))}</div>'
            + f'<div class="loc">{loc}</div></div></div>'
            + f'<div class="kpis">{kpis}</div>'
            + desc_html + amen_html + gal_html
            + _foot())


def _expired() -> str:
    return (_head("Link no disponible · Fynder") + _topbar("Fynder")
            + '<h1>Este link no está disponible</h1>'
            + '<p class="lead">Puede que haya expirado o el enlace esté incompleto. Pídele a tu asesor uno nuevo.</p>'
            + _foot())
