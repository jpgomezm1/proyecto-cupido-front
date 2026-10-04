"""
Link mágico para subir fotos de un listing (creado desde el MCP).

Al crear un listing conversando con la IA, se devuelve un link firmado. El agente
lo abre en el celular, arrastra/toma las fotos, y estas se suben a Supabase
Storage y se añaden a la propiedad. Así las fotos entran por web (natural) sin
pasar por el chat.

Rutas:
- GET  /subir-fotos?t=<token>   -> página con drag-drop (marca de brand.py).
- POST /listings/fotos          -> {token, imagenes:[dataURL...]} -> sube y anexa.
  (la página manda una foto por request para mostrar el estado de cada una).
"""

import html
import logging
from typing import Optional

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from src.mcp_server import brand

from src.services import listing_service as lst
from src.services import storage_service as store
from src.services.db import get_db, fetch_one
from src.services.textutils import build_share_link

MAX_FOTOS = 20

logger = logging.getLogger(__name__)


def _agente_id_por_telefono(cursor, owner_10: Optional[str]) -> Optional[int]:
    """Id del usuario (chat_users) dueño del celular del token, para atribuir el
    link de compartir (?a=). Best-effort: si no se encuentra, el link va sin ?a=."""
    digitos = "".join(ch for ch in str(owner_10 or "") if ch.isdigit())[-10:]
    if len(digitos) != 10:
        return None
    try:
        row = fetch_one(cursor,
            "SELECT id FROM chat_users WHERE RIGHT(regexp_replace(COALESCE(telefono,''), '[^0-9]', '', 'g'), 10) = %s "
            "ORDER BY id LIMIT 1", (digitos,))
        return int(row["id"]) if row and row.get("id") else None
    except Exception:
        logger.debug("No se pudo resolver el agente del token de fotos", exc_info=True)
        return None


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
    return HTMLResponse(_build_page(token, titulo, ya))


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
        agente_id = payload.get("uid") or _agente_id_por_telefono(db.cursor, payload.get("owner"))
    link_compartir = build_share_link(int(pid), (prop or {}).get("titulo"), agente_id)
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
# HTML de la página (marca compartida: brand.py). Compresión en el navegador,
# reordenar arrastrando (Pointer Events: mouse y touch) o con los botones ←/→,
# y subida foto por foto para mostrar el estado de cada una.
# ---------------------------------------------------------------------------

_CSS = """
.hero{ text-align:center; padding:18px 0 4px; }
.hero h1{ margin-top:10px; }
.prop{ display:inline-block; margin-top:12px; font-size:14px; color:var(--text); font-weight:600;
       background:var(--brand-soft); border:1px solid rgba(42,227,140,.22); border-radius:999px; padding:7px 16px; }
.prop small{ color:var(--muted); font-weight:500; }
.card{ margin-top:22px; }
.drop{ border:2px dashed var(--input); border-radius:var(--radius-xl); padding:34px 18px; text-align:center; cursor:pointer;
       background:var(--surface-2); display:block; transition:border-color .15s, background .15s; }
.drop:hover,.drop.over,.drop:focus-within{ border-color:var(--brand); background:var(--brand-soft); }
.drop .t{ font-weight:700; font-size:16px; color:var(--text); }
.drop .s{ color:var(--muted); font-size:13px; margin-top:5px; }
.drop input{ position:absolute; width:1px; height:1px; opacity:0; }
.count{ display:flex; align-items:center; justify-content:space-between; gap:10px; margin:18px 2px 8px; font-size:13px; }
.count .n{ color:var(--muted); font-weight:600; } .count .n b{ color:var(--brand); }
.linkbtn{ background:none; border:none; color:var(--brand); font:600 13px inherit; font-family:inherit; cursor:pointer; padding:4px; }
.ayuda{ font-size:12px; color:var(--muted); margin:0 2px 8px; }
.grid{ list-style:none; display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
.thumb{ position:relative; aspect-ratio:1; border-radius:var(--radius-lg); overflow:hidden; border:1px solid var(--input);
        background:var(--surface-2); }
.thumb img{ width:100%; height:100%; object-fit:cover; display:block; pointer-events:none; user-select:none; -webkit-user-drag:none; }
.thumb.arrastrando{ opacity:.35; }
.thumb.destino{ outline:2px solid var(--brand); outline-offset:-2px; }
.thumb .ctl{ position:absolute; display:grid; place-items:center; border:none; cursor:pointer; color:#fff;
             background:rgba(0,0,0,.66); font:700 13px/1 inherit; font-family:inherit; min-width:28px; height:28px; border-radius:8px; }
.thumb .ctl:hover{ background:var(--brand); color:var(--brand-ink); }
.thumb .ctl:disabled{ opacity:.35; cursor:default; background:rgba(0,0,0,.66); color:#fff; }
.thumb .mover{ top:5px; left:5px; padding:0 7px; cursor:grab; touch-action:none; gap:4px; }
.thumb .mover:active{ cursor:grabbing; }
.thumb .rm{ top:5px; right:5px; border-radius:50%; font-size:16px; }
.thumb .rm:hover{ background:var(--danger); color:#fff; }
.thumb .izq{ bottom:5px; left:5px; } .thumb .der{ bottom:5px; right:5px; }
.thumb .estrella{ bottom:5px; left:50%; transform:translateX(-50%); }
.thumb .portada{ position:absolute; bottom:7px; left:5px; font-size:10px; font-weight:700; text-transform:uppercase;
                 letter-spacing:.04em; border-radius:6px; padding:3px 6px; background:var(--brand); color:var(--brand-ink); }
.thumb .estado{ position:absolute; inset:0; display:grid; place-items:center; text-align:center; font-size:12px; font-weight:700;
                background:rgba(10,10,10,.62); color:#fff; padding:6px; }
.thumb .estado.ok{ background:rgba(4,18,10,.55); color:var(--brand-hi); }
.thumb .estado.err{ background:rgba(60,10,10,.7); color:#FFB4B4; }
.spin{ width:18px; height:18px; border:2px solid rgba(255,255,255,.3); border-top-color:#fff; border-radius:50%;
       animation:spin .7s linear infinite; margin:0 auto 4px; }
@keyframes spin{ to{ transform:rotate(360deg); } }
.barra{ height:6px; border-radius:999px; background:var(--surface-3); overflow:hidden; margin-top:16px; }
.barra div{ height:100%; width:0; background:var(--brand); transition:width .2s; }
.msg{ text-align:center; margin-top:12px; font-size:14px; color:var(--muted); min-height:1.2em; }
.msg.err{ color:#FFB4B4; } .msg.ok{ color:var(--brand); }
.done{ text-align:center; }
.ok-badge{ width:48px; height:48px; border-radius:50%; display:grid; place-items:center; font-size:24px; font-weight:800;
           background:var(--brand); color:var(--brand-ink); margin:0 auto 10px; }
.done .lead{ margin:8px 0 16px; }
.done .btn{ margin-top:14px; }
@media (max-width:400px){ .grid{ gap:8px; } .thumb .ctl{ min-width:26px; height:26px; } }
"""

_MAIN = """
<main>
  <div id="form">
    <section class="hero">
      <span class="eyebrow">Último paso</span>
      <h1>Súbele las fotos a tu propiedad</h1>
      <div class="prop">__TITULO__ &nbsp;·&nbsp; <small>__YA__ ya cargadas</small></div>
    </section>

    <div class="card">
      <label class="drop" id="drop" for="file">
        <div class="t">Toca para elegir fotos</div>
        <div class="s">o arrástralas aquí · JPG, PNG o WebP · hasta 20</div>
        <input type="file" id="file" accept="image/jpeg,image/png,image/webp" multiple>
      </label>

      <div class="count hidden" id="count">
        <span class="n" aria-live="polite"><b id="cn">0</b> foto(s) listas para subir</span>
        <button type="button" class="linkbtn" id="addmore">+ Agregar más</button>
      </div>
      <p class="ayuda hidden" id="ayuda">La primera es la portada (★ para elegir otra). Arrastra desde ⠿ o usa ← → para cambiar el orden.</p>
      <ul class="grid" id="grid" aria-label="Fotos para subir"></ul>

      <div class="barra hidden" id="barra" role="progressbar" aria-label="Progreso de la subida"
           aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div id="barra-in"></div></div>
      <button type="button" class="btn btn-primary btn-block" id="go" disabled style="margin-top:20px">Subir fotos</button>
      <p class="msg" id="msg" role="status" aria-live="polite"></p>
    </div>
  </div>

  <div class="card hidden" id="done-card" tabindex="-1">
    <div class="done">
      <div class="ok-badge" aria-hidden="true">✓</div>
      <h2>¡Propiedad publicada!</h2>
      <p class="lead">Ya aparece en Fynder. Este es tu link para compartirla con clientes:</p>
      <div class="codebox"><code id="share-url"></code>
        <button type="button" id="share-copy" aria-label="Copiar el link para compartir">Copiar</button></div>
      <a class="btn btn-block" id="share-open" href="#" target="_blank" rel="noopener noreferrer">Ver la propiedad</a>
    </div>
  </div>
</main>
"""

_SCRIPT = r"""<script>
const TOKEN = __TOKEN_JSON__;
const MAX = 20;
const $ = (id) => document.getElementById(id);
const drop = $('drop'), file = $('file'), grid = $('grid'), go = $('go'), msg = $('msg'),
      count = $('count'), cn = $('cn'), ayuda = $('ayuda'), barra = $('barra'), barraIn = $('barra-in');
// Cada foto: {id, src, estado: 'procesando'|'lista'|'subiendo'|'subida'|'error'}
let fotos = [];
let subiendo = false;
let sec = 0;

function setMsg(t, cls){ msg.textContent = t || ''; msg.className = 'msg' + (cls ? ' ' + cls : ''); }

function render(){
  grid.innerHTML = '';
  const pendientes = fotos.filter((f) => f.estado !== 'subida');
  fotos.forEach((f, i) => {
    const n = i + 1;
    const li = document.createElement('li');
    li.className = 'thumb'; li.dataset.i = i;
    const img = document.createElement('img');
    if (f.src) img.src = f.src;
    img.alt = 'Foto ' + n;
    li.appendChild(img);
    const editable = !subiendo && (f.estado === 'lista' || f.estado === 'error');
    if (editable){
      li.insertAdjacentHTML('beforeend',
        '<button type="button" class="ctl mover" data-acc="mover" aria-label="Arrastrar para mover la foto ' + n + '">⠿ ' + n + '</button>' +
        '<button type="button" class="ctl rm" data-acc="quitar" aria-label="Quitar la foto ' + n + '">×</button>' +
        (i === 0 ? '<span class="portada">Portada</span>'
                 : '<button type="button" class="ctl izq" data-acc="izq" aria-label="Mover la foto ' + n + ' a la izquierda">←</button>' +
                   '<button type="button" class="ctl estrella" data-acc="portada" aria-label="Usar la foto ' + n + ' como portada" title="Usar como portada">★</button>') +
        '<button type="button" class="ctl der" data-acc="der" aria-label="Mover la foto ' + n + ' a la derecha"' + (i === fotos.length - 1 ? ' disabled' : '') + '>→</button>');
    }
    const est = {procesando: '<div><div class="spin"></div>Preparando…</div>',
                 subiendo: '<div><div class="spin"></div>Subiendo…</div>',
                 subida: '✓ Subida',
                 error: 'No se pudo subir'}[f.estado];
    if (est){
      const d = document.createElement('div');
      d.className = 'estado' + (f.estado === 'subida' ? ' ok' : f.estado === 'error' ? ' err' : '');
      d.innerHTML = est;
      if (f.estado === 'error') d.style.pointerEvents = 'none';
      li.appendChild(d);
    }
    grid.appendChild(li);
  });
  cn.textContent = pendientes.length;
  count.classList.toggle('hidden', fotos.length === 0);
  ayuda.classList.toggle('hidden', fotos.length < 2 || subiendo);
  const listas = fotos.filter((f) => f.estado === 'lista' || f.estado === 'error').length;
  const procesando = fotos.some((f) => f.estado === 'procesando');
  go.disabled = subiendo || procesando || listas === 0;
  if (!subiendo) go.textContent = listas ? ('Subir ' + listas + ' foto' + (listas > 1 ? 's' : '')) : 'Subir fotos';
}

function mover(from, to){
  if (to < 0 || to >= fotos.length || from === to) return;
  const m = fotos.splice(from, 1)[0]; fotos.splice(to, 0, m); render();
}

grid.addEventListener('click', (e) => {
  const b = e.target.closest('[data-acc]'); if (!b || subiendo) return;
  const i = +b.closest('.thumb').dataset.i;
  const acc = b.dataset.acc;
  if (acc === 'quitar'){ fotos.splice(i, 1); render(); setMsg('Foto ' + (i + 1) + ' quitada.'); }
  else if (acc === 'izq'){ mover(i, i - 1); enfocar(i - 1, 'izq'); }
  else if (acc === 'der'){ mover(i, i + 1); enfocar(i + 1, 'der'); }
  else if (acc === 'portada'){ mover(i, 0); setMsg('La foto ' + (i + 1) + ' ahora es la portada.'); }
});
function enfocar(i, acc){
  const b = grid.querySelector('.thumb[data-i="' + i + '"] [data-acc="' + acc + '"]');
  if (b && !b.disabled) b.focus();
  else { const o = grid.querySelector('.thumb[data-i="' + i + '"] [data-acc]'); if (o) o.focus(); }
}

// Reordenar arrastrando desde ⠿ con Pointer Events (mouse, touch y lápiz).
let drag = null;
grid.addEventListener('pointerdown', (e) => {
  const h = e.target.closest('[data-acc="mover"]'); if (!h || subiendo) return;
  e.preventDefault();
  const li = h.closest('.thumb');
  drag = {from: +li.dataset.i, to: null, li: li, id: e.pointerId};
  h.setPointerCapture(e.pointerId);
  li.classList.add('arrastrando');
});
grid.addEventListener('pointermove', (e) => {
  if (!drag || e.pointerId !== drag.id) return;
  const el = document.elementFromPoint(e.clientX, e.clientY);
  const t = el && el.closest ? el.closest('.thumb') : null;
  grid.querySelectorAll('.destino').forEach((x) => x.classList.remove('destino'));
  if (t && t !== drag.li){ t.classList.add('destino'); drag.to = +t.dataset.i; } else drag.to = null;
});
function soltar(e){
  if (!drag || (e && e.pointerId !== drag.id)) return;
  const d = drag; drag = null;
  grid.querySelectorAll('.destino').forEach((x) => x.classList.remove('destino'));
  d.li.classList.remove('arrastrando');
  if (d.to !== null) mover(d.from, d.to);
}
grid.addEventListener('pointerup', soltar);
grid.addEventListener('pointercancel', soltar);

$('addmore').addEventListener('click', () => file.click());

function comprimir(fileObj){ return new Promise((res, rej) => { const img = new Image(); const rd = new FileReader();
  rd.onerror = rej; img.onerror = rej;
  rd.onload = (e) => { img.onload = () => { const max = 1600; let w = img.width, h = img.height;
    if (w > max || h > max){ if (w > h){ h = h * max / w; w = max; } else { w = w * max / h; h = max; } }
    const c = document.createElement('canvas'); c.width = w; c.height = h; c.getContext('2d').drawImage(img, 0, 0, w, h);
    res(c.toDataURL('image/jpeg', 0.8)); }; img.src = e.target.result; }; rd.readAsDataURL(fileObj); }); }

async function add(files){
  const arr = Array.from(files).filter((f) => f.type && f.type.startsWith('image/'));
  for (const f of arr){
    if (fotos.filter((x) => x.estado !== 'subida').length >= MAX){ setMsg('Máximo ' + MAX + ' fotos por vez.', 'err'); break; }
    const item = {id: ++sec, src: '', estado: 'procesando'};
    fotos.push(item); render();
    try { item.src = await comprimir(f); item.estado = 'lista'; }
    catch(_){ fotos.splice(fotos.indexOf(item), 1); setMsg('No pudimos leer una de las fotos.', 'err'); }
    render();
  }
}
file.addEventListener('change', async (e) => { const arr = Array.from(e.target.files); file.value = ''; await add(arr); });
drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
drop.addEventListener('dragleave', () => drop.classList.remove('over'));
drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); add(e.dataTransfer.files); });

function progreso(hechas, total){
  const p = total ? Math.round(hechas * 100 / total) : 0;
  barraIn.style.width = p + '%'; barra.setAttribute('aria-valuenow', p);
}

let shareUrl = '';
$('share-copy').addEventListener('click', () => {
  navigator.clipboard.writeText(shareUrl).then(() => { const b = $('share-copy'); b.textContent = '¡Copiado!'; setTimeout(() => b.textContent = 'Copiar', 1500); });
});

// Sube foto por foto (en el orden elegido) para mostrar el estado de cada una.
go.addEventListener('click', async () => {
  const cola = fotos.filter((f) => f.estado === 'lista' || f.estado === 'error');
  if (!cola.length) return;
  subiendo = true; go.disabled = true; go.textContent = 'Subiendo…';
  barra.classList.remove('hidden'); setMsg('');
  let hechas = 0, fallidas = 0, ultimo = null;
  progreso(0, cola.length);
  for (const f of cola){
    f.estado = 'subiendo'; render();
    setMsg('Subiendo foto ' + (hechas + 1) + ' de ' + cola.length + '…');
    try {
      const r = await fetch('/listings/fotos', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({token: TOKEN, imagenes: [f.src]})});
      const d = await r.json();
      if (d.ok){ f.estado = 'subida'; ultimo = d; }
      else { f.estado = 'error'; fallidas++; if (r.status === 401){ setMsg(d.error || 'El link expiró.', 'err'); } }
    } catch(_){ f.estado = 'error'; fallidas++; }
    hechas++; progreso(hechas, cola.length); render();
  }
  subiendo = false;
  if (fallidas){
    render();
    setMsg(fallidas + ' foto' + (fallidas > 1 ? 's' : '') + ' no se pudo subir. Toca “Subir” para reintentar.', 'err');
    go.textContent = 'Reintentar ' + fallidas;
    return;
  }
  fotos = []; render();
  if (ultimo && ultimo.link_compartir){
    shareUrl = ultimo.link_compartir;
    $('share-url').textContent = shareUrl;
    $('share-open').href = shareUrl;
    $('form').classList.add('hidden');
    const dc = $('done-card'); dc.classList.remove('hidden'); dc.focus();
    window.scrollTo({top: 0});
  } else {
    barra.classList.add('hidden');
    setMsg('✓ ' + cola.length + ' foto(s) subidas.', 'ok');
  }
});
render();
</script>"""


def _build_page(token: str, titulo: str, ya: int) -> str:
    import json
    body = ('<div class="wrap-sm">' + brand.header("Publicar")
            + _MAIN.replace("__TITULO__", titulo).replace("__YA__", str(ya))
            + brand.footer() + "</div>")
    # El token va como literal JSON (seguro dentro de <script>).
    token_js = json.dumps(token).replace("<", "\\u003c")
    return brand.page("Sube las fotos · Fynder", body, extra_css=_CSS,
                      scripts=_SCRIPT.replace("__TOKEN_JSON__", token_js))


def _expired_html() -> str:
    body = (f'<div class="wrap-sm">{brand.header("Publicar")}<main><div class="card" style="text-align:center">'
            '<h1 style="font-size:22px">El link de subida expiró</h1>'
            '<p class="lead" style="margin-top:10px">Pídele a tu asistente que te genere uno nuevo para esta propiedad.</p>'
            f'</div></main>{brand.footer()}</div>')
    return brand.page("Link expirado · Fynder", body)


_EXPIRED_HTML = _expired_html()
