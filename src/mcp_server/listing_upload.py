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
    return JSONResponse({"ok": True, "subidas": len(urls), "errores": errores,
                         "total_imagenes": res["total_imagenes"]})


def listing_upload_routes():
    return [
        Route("/subir-fotos", upload_page, methods=["GET"]),
        Route("/listings/fotos", upload_endpoint, methods=["POST"]),
    ]


# ---------------------------------------------------------------------------
# HTML de la página (identidad Fynder, drag-drop, compresión en el navegador).
# ---------------------------------------------------------------------------

_STYLE = """
  :root{ --bg:#0A0A0A; --bg-2:#141414; --border:#2A2A2A; --white:#FAFAFA; --text:#E5E5E5;
         --text-2:#A3A3A3; --text-3:#6B6B6B; --green:#2AE38C; --green-d:#1FC97A; }
  *{ box-sizing:border-box; margin:0; padding:0; }
  body{ font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:var(--bg);
        color:var(--text); min-height:100vh; padding:20px; display:flex; flex-direction:column; align-items:center;
        background-image:radial-gradient(ellipse 900px 600px at 50% -10%, rgba(42,227,140,.07), transparent 60%); }
  .wrap{ width:100%; max-width:520px; }
  .top{ display:flex; justify-content:center; padding:8px 0 18px; }
  .top img{ height:26px; }
  .card{ background:linear-gradient(180deg,#0F0F0F,#0A0A0A); border:1px solid #1F1F1F; border-radius:22px; padding:26px 22px; }
  h1{ font-size:20px; color:var(--white); font-weight:700; text-align:center; }
  .sub{ color:var(--text-2); font-size:14px; text-align:center; margin:6px 0 20px; }
  .prop{ color:var(--green); font-weight:600; }
  .drop{ border:2px dashed var(--border); border-radius:16px; padding:34px 16px; text-align:center; cursor:pointer;
         transition:.15s; background:var(--bg-2); }
  .drop:hover,.drop.over{ border-color:var(--green); background:rgba(42,227,140,.05); }
  .drop .ic{ font-size:34px; }
  .drop p{ color:var(--text-2); font-size:14px; margin-top:8px; }
  .drop b{ color:var(--green); }
  input[type=file]{ display:none; }
  .grid{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-top:16px; }
  .thumb{ position:relative; aspect-ratio:1; border-radius:10px; overflow:hidden; border:1px solid var(--border); }
  .thumb img{ width:100%; height:100%; object-fit:cover; }
  .thumb .rm{ position:absolute; top:3px; right:3px; background:rgba(0,0,0,.6); color:#fff; border:none;
              border-radius:50%; width:22px; height:22px; cursor:pointer; font-size:13px; }
  button.go{ width:100%; margin-top:20px; padding:15px; border:none; border-radius:13px; cursor:pointer;
             font-weight:700; font-size:16px; color:#04120a; font-family:inherit;
             background:linear-gradient(150deg,#5DFAAB,var(--green)); box-shadow:0 10px 30px rgba(42,227,140,.25); }
  button.go:disabled{ opacity:.5; cursor:default; box-shadow:none; }
  .msg{ text-align:center; margin-top:14px; font-size:14px; }
  .ok{ color:var(--green); } .err{ color:#ff8b95; }
  .dev{ display:flex; align-items:center; justify-content:center; gap:8px; margin-top:22px; }
  .dev span{ color:#4A4A4A; font-size:12px; } .dev img{ height:16px; opacity:.6; }
"""

_PAGE = """<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sube las fotos · Fynder</title>
<link rel="icon" type="image/png" href="https://storage.googleapis.com/cluvi/FYNDER/emoji_fynder.png">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>__STYLE__</style></head>
<body>
  <div class="wrap">
    <div class="top"><img src="__FYNDER_LOGO__" alt="Fynder"></div>
    <div class="card">
      <h1>📸 Sube las fotos</h1>
      <p class="sub"><span class="prop">__TITULO__</span><br>Ya tiene __YA__ foto(s). Agrega las que quieras.</p>
      <label class="drop" id="drop">
        <div class="ic">📷</div>
        <p><b>Toca para elegir fotos</b><br>o arrástralas aquí (JPG/PNG)</p>
        <input type="file" id="file" accept="image/jpeg,image/png,image/webp" multiple>
      </label>
      <div class="grid" id="grid"></div>
      <button class="go" id="go" disabled>Subir fotos</button>
      <div class="msg" id="msg"></div>
    </div>
    <div class="dev"><span>Developed by</span><img src="__IRRELEVANT_LOGO__" alt="irrelevant"></div>
  </div>
<script>
const TOKEN="__TOKEN__";
const drop=document.getElementById('drop'), file=document.getElementById('file'),
      grid=document.getElementById('grid'), go=document.getElementById('go'), msg=document.getElementById('msg');
let fotos=[];

function render(){ grid.innerHTML=''; fotos.forEach((f,i)=>{ const d=document.createElement('div'); d.className='thumb';
  d.innerHTML='<img src="'+f+'"><button class="rm" onclick="quitar('+i+')">\\u00d7</button>'; grid.appendChild(d); });
  go.disabled = fotos.length===0; go.textContent = fotos.length? ('Subir '+fotos.length+' foto(s)'):'Subir fotos'; }
window.quitar=(i)=>{ fotos.splice(i,1); render(); };

function comprimir(fileObj){ return new Promise(res=>{ const img=new Image(); const rd=new FileReader();
  rd.onload=e=>{ img.onload=()=>{ const max=1600; let w=img.width, h=img.height;
    if(w>max||h>max){ if(w>h){h=h*max/w; w=max;} else {w=w*max/h; h=max;} }
    const c=document.createElement('canvas'); c.width=w; c.height=h; c.getContext('2d').drawImage(img,0,0,w,h);
    res(c.toDataURL('image/jpeg',0.8)); }; img.src=e.target.result; }; rd.readAsDataURL(fileObj); }); }

async function add(files){ for(const f of files){ if(!f.type.startsWith('image/')) continue;
  if(fotos.length>=20){ msg.innerHTML='<span class="err">M\\u00e1ximo 20 fotos.</span>'; break; }
  fotos.push(await comprimir(f)); } render(); }

file.addEventListener('change', e=> add(e.target.files));
drop.addEventListener('dragover', e=>{ e.preventDefault(); drop.classList.add('over'); });
drop.addEventListener('dragleave', ()=> drop.classList.remove('over'));
drop.addEventListener('drop', e=>{ e.preventDefault(); drop.classList.remove('over'); add(e.dataTransfer.files); });

go.addEventListener('click', async ()=>{ go.disabled=true; go.textContent='Subiendo...'; msg.textContent='';
  try{ const r=await fetch('/listings/fotos',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({token:TOKEN, imagenes:fotos})});
    const d=await r.json();
    if(d.ok){ msg.innerHTML='<span class="ok">\\u2705 \\u00a1Listo! '+d.subidas+' foto(s) subidas. Tu propiedad ya tiene '+d.total_imagenes+'.</span>';
      fotos=[]; render(); go.textContent='Subir m\\u00e1s'; }
    else{ msg.innerHTML='<span class="err">'+(d.error||'No se pudo subir.')+'</span>'; go.disabled=false; go.textContent='Reintentar'; }
  }catch(e){ msg.innerHTML='<span class="err">Error de conexi\\u00f3n. Intenta de nuevo.</span>'; go.disabled=false; go.textContent='Reintentar'; }
});
</script>
</body></html>"""

_EXPIRED_HTML = ("""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Link expirado · Fynder</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>__STYLE__</style></head>
<body><div class="wrap"><div class="top"><img src="__FYNDER_LOGO__" alt="Fynder"></div>
<div class="card" style="text-align:center"><h1>El link de subida expiró</h1>
<p class="sub">Pídele a tu asistente que te genere uno nuevo para esta propiedad.</p></div></div></body></html>"""
    .replace("__STYLE__", _STYLE).replace("__FYNDER_LOGO__", FYNDER_LOGO))
