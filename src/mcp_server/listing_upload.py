"""
Link mágico para subir fotos de un listing (creado desde el MCP).

Al crear un listing conversando con la IA, se devuelve un link firmado. El agente
lo abre en el celular, arrastra/toma las fotos, y estas se suben a Supabase
Storage y se añaden a la propiedad. Así las fotos entran por web (natural) sin
pasar por el chat.

Rutas:
- GET  /subir-fotos?t=<token>   -> página con drag-drop (branding Fynder).
- POST /listings/fotos          -> {token, imagenes:[dataURL...]} -> sube y anexa.
"""

import html

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from src.services import listing_service as lst
from src.services import storage_service as store
from src.services.db import get_db, fetch_one
from src.services.textutils import build_share_link

FYNDER_LOGO = "https://storage.googleapis.com/cluvi/FYNDER/logo_blanco_fynder_final.png"
IRRELEVANT_LOGO = "https://storage.googleapis.com/cluvi/nuevo_irre-removebg-preview.png"
MAX_FOTOS = 20


async def upload_page(request: Request) -> HTMLResponse:
    token = request.query_params.get("t", "")
    try:
        payload = lst.verify_photo_token(token)
    except lst.ListingError:
        return HTMLResponse(_EXPIRED_HTML, status_code=400)

    # Datos de la propiedad para el encabezado.
    with get_db() as db:
        prop = fetch_one(db.cursor,
            "SELECT titulo, precio, ciudad, zona, total_imagenes FROM propiedades WHERE id=%s",
            (payload["pid"],))
    titulo = html.escape((prop or {}).get("titulo") or "Tu propiedad")
    ya = int((prop or {}).get("total_imagenes") or 0)
    page = (_PAGE.replace("__STYLE__", _STYLE)
                 .replace("__MARK__", _MARK)
                 .replace("__FYNDER_LOGO__", FYNDER_LOGO)
                 .replace("__IRRELEVANT_LOGO__", IRRELEVANT_LOGO)
                 .replace("__TOKEN__", html.escape(token))
                 .replace("__TITULO__", titulo)
                 .replace("__YA__", str(ya)))
    return HTMLResponse(page)


async def upload_endpoint(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Solicitud inválida"}, status_code=400)

    token = body.get("token", "")
    imagenes = body.get("imagenes") or []
    try:
        payload = lst.verify_photo_token(token)
    except lst.ListingError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=401)

    if not imagenes:
        return JSONResponse({"ok": False, "error": "No enviaste fotos"}, status_code=400)
    if len(imagenes) > MAX_FOTOS:
        return JSONResponse({"ok": False, "error": f"Máximo {MAX_FOTOS} fotos por vez"}, status_code=400)

    pid = payload["pid"]
    urls = []
    errores = 0
    for data_url in imagenes:
        try:
            url = store.upload_image_data_url(data_url, prefix=f"listings/{pid}")
            urls.append(url)
        except Exception:
            errores += 1

    if not urls:
        return JSONResponse({"ok": False, "error": "No se pudo subir ninguna foto. Revisa el formato (JPG/PNG)."},
                            status_code=500)

    res = lst.agregar_fotos(int(pid), urls)

    # Link de Fynder para compartir la propiedad (ya publicada).
    with get_db() as db:
        prop = fetch_one(db.cursor, "SELECT titulo, activa FROM propiedades WHERE id=%s", (int(pid),))
    link_compartir = build_share_link(int(pid), (prop or {}).get("titulo"))
    publicada = bool((prop or {}).get("activa"))

    return JSONResponse({"ok": True, "subidas": len(urls), "errores": errores,
                         "total_imagenes": res["total_imagenes"],
                         "publicada": publicada,
                         "link_compartir": link_compartir})


def listing_upload_routes():
    return [
        Route("/subir-fotos", upload_page, methods=["GET"]),
        Route("/listings/fotos", upload_endpoint, methods=["POST"]),
    ]


# ---------------------------------------------------------------------------
# HTML de la página (identidad Fynder, drag-drop, compresión en el navegador).
# ---------------------------------------------------------------------------

_STYLE = """
  :root{ --bg:#0A0A0A; --bg-1:#0F0F0F; --bg-2:#141414; --border:#1F1F1F; --border-hi:#2A2A2A;
         --white:#FAFAFA; --text:#E5E5E5; --text-2:#A3A3A3; --text-3:#6B6B6B; --text-4:#4A4A4A;
         --green:#2AE38C; --green-d:#1FC97A; --green-l:#5DFAAB; }
  *{ box-sizing:border-box; margin:0; padding:0; }
  html{ scroll-behavior:smooth; }
  body{ font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:var(--bg);
        color:var(--text); min-height:100vh; padding:0 18px 48px; -webkit-font-smoothing:antialiased;
        background-image:radial-gradient(ellipse 900px 620px at 50% -8%, rgba(42,227,140,.08), transparent 60%),
                         radial-gradient(ellipse 700px 500px at 90% 100%, rgba(91,156,255,.03), transparent 60%); }
  .wrap{ width:100%; max-width:560px; margin:0 auto; }
  .top{ display:flex; align-items:center; justify-content:space-between; padding:22px 2px 4px; }
  .brand{ display:flex; align-items:center; gap:10px; }
  .brand img.logo{ height:24px; }
  .findy{ position:relative; }
  .findy img{ height:34px; width:34px; object-fit:contain; }
  .findy .dot{ position:absolute; bottom:1px; right:1px; width:9px; height:9px; border-radius:50%;
               background:var(--green); border:2px solid var(--bg); }
  .pill{ font-size:10.5px; letter-spacing:.14em; text-transform:uppercase; color:var(--text-3);
         border:1px solid var(--border-hi); border-radius:999px; padding:5px 11px; font-weight:600; }

  .hero{ text-align:center; padding:30px 0 4px; }
  .hero .kicker{ display:inline-flex; align-items:center; gap:7px; font-size:11px; letter-spacing:.2em;
                 text-transform:uppercase; color:var(--green); font-weight:700; margin-bottom:14px; }
  h1{ font-size:26px; color:var(--white); font-weight:800; letter-spacing:-.02em; line-height:1.15; }
  .prop{ display:inline-block; margin-top:12px; font-size:14px; color:var(--white); font-weight:600;
         background:linear-gradient(150deg,rgba(42,227,140,.10),transparent 80%);
         border:1px solid rgba(42,227,140,.22); border-radius:999px; padding:7px 16px; }
  .prop small{ color:var(--text-3); font-weight:500; }

  .card{ background:linear-gradient(180deg,var(--bg-1),var(--bg)); border:1px solid var(--border);
         border-radius:24px; padding:22px; margin-top:24px; }

  .drop{ border:2px dashed var(--border-hi); border-radius:18px; padding:40px 18px; text-align:center; cursor:pointer;
         transition:border-color .18s, background .18s, transform .1s; background:var(--bg-2); display:block; }
  .drop:hover,.drop.over{ border-color:var(--green); background:rgba(42,227,140,.06); }
  .drop.over{ transform:scale(1.01); }
  .drop .ic{ width:56px; height:56px; margin:0 auto 12px; border-radius:16px; display:grid; place-items:center;
             font-size:26px; background:rgba(42,227,140,.12); }
  .drop .t{ color:var(--white); font-weight:700; font-size:16px; }
  .drop .s{ color:var(--text-3); font-size:13px; margin-top:5px; }
  input[type=file]{ display:none; }

  .count{ display:flex; align-items:center; justify-content:space-between; margin:18px 2px 10px; }
  .count .n{ font-size:13px; color:var(--text-2); font-weight:600; }
  .count .n b{ color:var(--green); }
  .count .add{ font-size:13px; color:var(--green); font-weight:600; cursor:pointer; }

  .grid{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
  .thumb{ position:relative; aspect-ratio:1; border-radius:14px; overflow:hidden; border:1px solid var(--border-hi);
          animation:pop .2s ease; }
  @keyframes pop{ from{ opacity:0; transform:scale(.9);} to{ opacity:1; transform:scale(1);} }
  .thumb img{ width:100%; height:100%; object-fit:cover; }
  .thumb .cover{ position:absolute; bottom:5px; left:5px; font-size:9.5px; font-weight:700; text-transform:uppercase;
                 letter-spacing:.05em; color:#04120a; background:var(--green); border-radius:6px; padding:2px 7px; }
  .thumb .rm{ position:absolute; top:5px; right:5px; background:rgba(0,0,0,.65); backdrop-filter:blur(4px);
              color:#fff; border:none; border-radius:50%; width:24px; height:24px; cursor:pointer; font-size:14px;
              display:grid; place-items:center; line-height:1; }
  .thumb .rm:hover{ background:#ff5c5c; }

  button.go{ width:100%; margin-top:22px; padding:16px; border:none; border-radius:15px; cursor:pointer;
             font-weight:700; font-size:16px; color:#04120a; font-family:inherit; transition:transform .12s, box-shadow .2s;
             background:linear-gradient(150deg,var(--green-l),var(--green)); box-shadow:0 12px 34px rgba(42,227,140,.28);
             display:flex; align-items:center; justify-content:center; gap:8px; }
  button.go:hover:not(:disabled){ transform:translateY(-2px); box-shadow:0 16px 42px rgba(42,227,140,.4); }
  button.go:disabled{ opacity:.4; cursor:default; box-shadow:none; }
  .spinner{ width:16px; height:16px; border:2px solid rgba(4,18,10,.3); border-top-color:#04120a; border-radius:50%;
            animation:spin .7s linear infinite; }
  @keyframes spin{ to{ transform:rotate(360deg);} }
  .msg{ text-align:center; margin-top:14px; font-size:14px; }
  .ok{ color:var(--green); } .err{ color:#ff8b95; }

  .done{ text-align:center; padding:8px 4px; animation:pop .3s ease; }
  .done-badge{ width:64px; height:64px; margin:0 auto 6px; border-radius:50%; display:grid; place-items:center;
               background:radial-gradient(circle,rgba(42,227,140,.16),transparent 70%); }
  .done-badge div{ width:46px; height:46px; border-radius:50%; display:grid; place-items:center; font-size:24px;
                   background:linear-gradient(150deg,var(--green),var(--green-d)); box-shadow:0 8px 26px rgba(42,227,140,.4); }
  .done h2{ color:var(--white); font-size:22px; font-weight:800; margin-top:6px; }
  .done-sub{ color:var(--text-2); font-size:14.5px; margin:8px 0 16px; }
  .sharebox{ display:flex; gap:8px; align-items:center; background:#050b08; border:1px solid rgba(42,227,140,.35);
             border-radius:14px; padding:13px 14px; box-shadow:inset 0 0 30px rgba(42,227,140,.05); }
  .sharebox code{ flex:1; color:var(--green-l); font-size:12.5px; word-break:break-all; text-align:left; font-family:'JetBrains Mono',monospace; }
  .sharebox button{ flex:0 0 auto; background:linear-gradient(150deg,var(--green-l),var(--green)); color:#04120a;
                    border:none; border-radius:10px; padding:9px 15px; font-weight:700; font-size:13px; cursor:pointer; }

  .dev{ display:flex; align-items:center; justify-content:center; gap:8px; margin-top:28px; padding-top:20px;
        border-top:1px solid #161616; }
  .dev span{ color:var(--text-4); font-size:12px; } .dev img{ height:16px; opacity:.55; transition:opacity .2s; }
  .dev:hover img{ opacity:1; }
  .hidden{ display:none; }
"""

_MARK = ('<span class="findy"><img src="https://storage.googleapis.com/cluvi/FYNDER/emoji_fynder.png" alt="Findy">'
         '<span class="dot"></span></span>')

_PAGE = """<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sube las fotos · Fynder</title>
<link rel="icon" type="image/png" href="https://storage.googleapis.com/cluvi/FYNDER/emoji_fynder.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
<style>__STYLE__</style></head>
<body>
  <div class="wrap">
    <div class="top">
      <div class="brand">__MARK__<img class="logo" src="__FYNDER_LOGO__" alt="Fynder"></div>
      <div class="pill">Publicar</div>
    </div>

    <div id="form">
      <div class="hero">
        <div class="kicker">✦ Último paso</div>
        <h1>Súbele las fotos<br>a tu propiedad</h1>
        <div class="prop">__TITULO__ &nbsp;·&nbsp; <small>__YA__ ya cargadas</small></div>
      </div>

      <div class="card">
        <label class="drop" id="drop">
          <div class="ic">📷</div>
          <div class="t">Toca para elegir fotos</div>
          <div class="s">o arrástralas aquí · JPG o PNG · hasta 20</div>
          <input type="file" id="file" accept="image/jpeg,image/png,image/webp" multiple>
        </label>

        <div class="count hidden" id="count">
          <span class="n"><b id="cn">0</b> foto(s) listas para subir</span>
          <span class="add" id="addmore">+ Agregar más</span>
        </div>
        <div class="grid" id="grid"></div>

        <button class="go" id="go" disabled>Subir fotos</button>
        <div class="msg" id="msg"></div>
      </div>
    </div>

    <div class="card hidden" id="done-card">
      <div class="done" id="done">
        <div class="done-badge"><div>✓</div></div>
        <h2>¡Propiedad publicada!</h2>
        <p class="done-sub">Ya aparece en Fynder. Este es tu link para compartirla con clientes:</p>
        <div class="sharebox"><code id="share-url"></code>
          <button id="share-copy" onclick="copiarShare()">Copiar</button></div>
      </div>
    </div>

    <div class="dev"><span>Developed by</span><img src="__IRRELEVANT_LOGO__" alt="irrelevant"></div>
  </div>
<script>
const TOKEN="__TOKEN__";
const drop=document.getElementById('drop'), file=document.getElementById('file'),
      grid=document.getElementById('grid'), go=document.getElementById('go'), msg=document.getElementById('msg'),
      count=document.getElementById('count'), cn=document.getElementById('cn');
let fotos=[];

function render(){ grid.innerHTML='';
  fotos.forEach((f,i)=>{ const d=document.createElement('div'); d.className='thumb';
    const cover = i===0 ? '<span class="cover">Portada</span>' : '';
    d.innerHTML='<img src="'+f+'">'+cover+'<button class="rm" onclick="quitar('+i+')">\\u00d7</button>'; grid.appendChild(d); });
  cn.textContent=fotos.length; count.classList.toggle('hidden', fotos.length===0);
  go.disabled = fotos.length===0;
  go.innerHTML = fotos.length? ('Subir '+fotos.length+' foto'+(fotos.length>1?'s':'')) : 'Subir fotos'; }
window.quitar=(i)=>{ fotos.splice(i,1); render(); };
document.getElementById('addmore').addEventListener('click', ()=> file.click());

function comprimir(fileObj){ return new Promise(res=>{ const img=new Image(); const rd=new FileReader();
  rd.onload=e=>{ img.onload=()=>{ const max=1600; let w=img.width, h=img.height;
    if(w>max||h>max){ if(w>h){h=h*max/w; w=max;} else {w=w*max/h; h=max;} }
    const c=document.createElement('canvas'); c.width=w; c.height=h; c.getContext('2d').drawImage(img,0,0,w,h);
    res(c.toDataURL('image/jpeg',0.8)); }; img.src=e.target.result; }; rd.readAsDataURL(fileObj); }); }

async function add(files){ for(const f of files){ if(!f.type.startsWith('image/')) continue;
  if(fotos.length>=20){ msg.innerHTML='<span class="err">M\\u00e1ximo 20 fotos.</span>'; break; }
  fotos.push(await comprimir(f)); } render(); }

file.addEventListener('change', e=>{ add(e.target.files); file.value=''; });
drop.addEventListener('dragover', e=>{ e.preventDefault(); drop.classList.add('over'); });
drop.addEventListener('dragleave', ()=> drop.classList.remove('over'));
drop.addEventListener('drop', e=>{ e.preventDefault(); drop.classList.remove('over'); add(e.dataTransfer.files); });

let shareUrl='';
window.copiarShare=()=>{ navigator.clipboard.writeText(shareUrl); const b=document.getElementById('share-copy'); b.textContent='\\u00a1Copiado!'; setTimeout(()=>b.textContent='Copiar',1500); };

go.addEventListener('click', async ()=>{ go.disabled=true; go.innerHTML='<span class="spinner"></span> Subiendo...'; msg.textContent='';
  try{ const r=await fetch('/listings/fotos',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({token:TOKEN, imagenes:fotos})});
    const d=await r.json();
    if(d.ok){
      if(d.link_compartir){ shareUrl=d.link_compartir; document.getElementById('share-url').textContent=d.link_compartir;
        document.getElementById('form').classList.add('hidden');
        document.getElementById('done-card').classList.remove('hidden');
        window.scrollTo({top:0,behavior:'smooth'}); }
      else { msg.innerHTML='<span class="ok">\\u2705 '+d.subidas+' foto(s) subidas.</span>'; fotos=[]; render(); }
    }
    else{ msg.innerHTML='<span class="err">'+(d.error||'No se pudo subir.')+'</span>'; go.disabled=false; go.textContent='Reintentar'; }
  }catch(e){ msg.innerHTML='<span class="err">Error de conexi\\u00f3n. Intenta de nuevo.</span>'; go.disabled=false; go.textContent='Reintentar'; }
});
</script>
</body></html>"""

_EXPIRED_HTML = ("""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Link expirado · Fynder</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>__STYLE__</style></head>
<body><div class="wrap"><div class="top"><div class="brand">__MARK__<img class="logo" src="__FYNDER_LOGO__" alt="Fynder"></div></div>
<div class="card" style="text-align:center; margin-top:40px"><h1 style="font-size:20px">El link de subida expiró</h1>
<p class="done-sub" style="margin-top:10px">Pídele a tu asistente que te genere uno nuevo para esta propiedad.</p></div></div></body></html>"""
    .replace("__STYLE__", _STYLE).replace("__MARK__", _MARK).replace("__FYNDER_LOGO__", FYNDER_LOGO))
