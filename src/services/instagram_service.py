"""
Instagram de Fynder (migración 061): Buffer → instagram_posts → correo.

Copia del módulo de Órbita (@mr_irrelevant.ai). Las publicaciones se programan en
Buffer desde la fábrica de contenidos (carpeta `instagram/` del workspace); aquí solo se
LEE Buffer para que el admin muestre la parrilla, el perfil y las métricas.

  sincronizar()       lo corre el worker 2 veces al día (7 a. m. y 7 p. m. de Bogotá):
                      guarda cada publicación y manda un correo por cada una que se
                      publicó o falló desde la corrida anterior. Es el ÚNICO que llama a
                      Buffer: no lo subas de frecuencia sin mirar el tope diario de su API
                      (~2 llamadas por corrida, una por página de 50 posts).
  posts()             lo guardado, con la forma que pinta el admin.
  seguidores()        los seguidores anotados a mano y la meta (Buffer no da el total).

Config (env): BUFFER_API_KEY (obligatoria), BUFFER_ORG_ID, INSTAGRAM_BUFFER_CHANNEL_ID
(el canal de Instagram de Fynder en Buffer), INSTAGRAM_AVISOS_CORREO (separados por coma),
INSTAGRAM_PERFIL (el usuario, sin @). Nunca se loguea la llave.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from src.services.db import fetch_all, get_db, scalar

URL = "https://api.buffer.com"
MAX_PAGINAS = 20            # seguro contra un cursor que no avance: 20 × 50 = 1.000 posts
META_POR_DEFECTO = 1000
TZ = timezone(timedelta(hours=-5))   # Bogotá, sin horario de verano

_QUERY = """
  query($o: OrganizationId!, $after: String, $c: [ChannelId!]) {
    posts(first: 50, after: $after, input: { organizationId: $o, filter: { channelIds: $c }, sort: [{ field: dueAt, direction: asc }] }) {
      edges { node {
        id status dueAt sentAt externalLink text metricsUpdatedAt
        error { message }
        metrics { type name value unit }
        assets { thumbnail source }
        metadata { __typename ... on InstagramPostMetadata { type } }
      } }
      pageInfo { hasNextPage endCursor }
    }
  }
"""

# `type` de Buffer → clave de las métricas. Lo que no está aquí se ignora.
_ALIAS = {
    "postcount": "postCount", "reach": "reach", "impressions": "impressions", "views": "views",
    "reactions": "likes", "likes": "likes", "comments": "comments", "saves": "saves", "shares": "shares",
    "follows": "follows", "engagementrate": "engagementRate", "totaltimewatched": "totalTimeWatched",
    "averagetimewatched": "averageTimeWatched",
}


def perfil() -> str:
    return os.getenv("INSTAGRAM_PERFIL", "fynder.co").lstrip("@")


def configurado() -> bool:
    return bool(os.getenv("BUFFER_API_KEY") and os.getenv("BUFFER_ORG_ID") and os.getenv("INSTAGRAM_BUFFER_CHANNEL_ID"))


# ── lógica pura (espejo de lib/instagram/puro.ts y avisos-puro.ts de Órbita) ──

def normalizar_metricas(lista: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, float]]:
    """La lista {type, value, unit} de Buffer → un objeto. None si Buffer no trajo métricas.
    Si llegan `reactions` y `likes`, manda `reactions`. La tasa de interacción queda en %."""
    if lista is None:
        return None
    m: Dict[str, float] = {}
    hay_reactions = any(str(x.get("type", "")).lower() == "reactions" and x.get("value") is not None for x in lista)
    for x in lista:
        v = x.get("value")
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        tipo = str(x.get("type", "")).lower()
        clave = _ALIAS.get(tipo)
        if not clave or (tipo == "likes" and hay_reactions):
            continue
        if clave == "engagementRate" and "percent" not in str(x.get("unit") or "").lower() and v <= 1:
            v *= 100
        m[clave] = v
    return m


def _normalizar(n: Dict[str, Any]) -> Dict[str, Any]:
    t = (n.get("metadata") or {}).get("type")
    assets = n.get("assets") or []
    return {
        "id": n["id"],
        "estado": n.get("status"),
        "dueAt": n.get("dueAt"),
        "sentAt": n.get("sentAt"),
        "link": n.get("externalLink"),
        "texto": n.get("text") or "",
        "metricasAt": n.get("metricsUpdatedAt"),
        "error": (n.get("error") or {}).get("message"),
        "metricas": normalizar_metricas(n.get("metrics")),
        "miniaturas": [a["thumbnail"] for a in assets if a.get("thumbnail")],
        "imagenes": [x for x in ((a.get("source") if a.get("source") and not re.search(r"\.(mp4|mov)(\?|$)", a["source"], re.I)
                                  else a.get("thumbnail")) for a in assets) if x],
        "tipo": t if t in ("post", "story", "reel") else None,
    }


def _ts(iso: Optional[str]) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _clave_texto(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip().lower())[:80]


def sin_errores_reintentados(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Un fallo que Buffer reintentó y publicó (mismo tipo, mismo comienzo de texto, publicado
    hasta 24 h después) no se pinta, no cuenta como fallido y no se avisa."""
    publicados = [p for p in posts if p["estado"] == "sent"]
    out = []
    for x in posts:
        if x["estado"] != "error" or not (x.get("texto") or "").strip():
            out.append(x)
            continue
        t = _ts(x.get("dueAt"))
        resuelto = any(
            y.get("tipo") == x.get("tipo") and _clave_texto(y.get("texto") or "") == _clave_texto(x["texto"])
            and t - 3600 <= _ts(y.get("sentAt") or y.get("dueAt")) <= t + 24 * 3600
            for y in publicados)
        if not resuelto:
            out.append(x)
    return out


def por_avisar(posts: List[Dict[str, Any]], previos: Dict[str, Optional[str]], primera_vez: bool) -> List[Dict[str, Any]]:
    """Cada publicación que pasó a `sent` o a `error`, una sola vez por estado. La primera
    sincronización no avisa nada: siembra lo que ya estaba."""
    if primera_vez:
        return []
    out = []
    for p in posts:
        ya = previos.get(p["id"])
        if p["estado"] == "sent" and ya != "sent":
            out.append({"post": p, "motivo": "publicado"})
        elif p["estado"] == "error" and ya not in ("error", "sent"):
            out.append({"post": p, "motivo": "fallo"})
    return sorted(out, key=lambda a: a["post"].get("sentAt") or a["post"].get("dueAt") or "")


def tipo_legible(tipo: Optional[str], n: int) -> str:
    if tipo == "story":
        return "Historia"
    if tipo == "reel":
        return "Reel"
    return f"Carrusel · {n}" if n > 1 else "Post"


def primeras_lineas(texto: str, n: int = 2, maximo: int = 160) -> str:
    lineas = " · ".join([l.strip() for l in texto.split("\n") if l.strip()][:n])
    return lineas if len(lineas) <= maximo else lineas[:maximo - 1].rstrip() + "…"


# ── Buffer ───────────────────────────────────────────────────────────────────

def listar_posts() -> Dict[str, Any]:
    """Todos los posts del canal, paginando. Nunca lanza: {ok, posts} o {ok: False, mensaje}."""
    llave, org, canal = os.getenv("BUFFER_API_KEY"), os.getenv("BUFFER_ORG_ID"), os.getenv("INSTAGRAM_BUFFER_CHANNEL_ID")
    if not (llave and org and canal):
        return {"ok": False, "mensaje": "Faltan BUFFER_API_KEY, BUFFER_ORG_ID o INSTAGRAM_BUFFER_CHANNEL_ID"}
    posts: List[Dict[str, Any]] = []
    after = None
    try:
        for _ in range(MAX_PAGINAS):
            r = requests.post(URL, timeout=30, headers={"Authorization": f"Bearer {llave}", "Content-Type": "application/json"},
                              json={"query": _QUERY, "variables": {"o": org, "after": after, "c": [canal]}})
            if r.status_code != 200:
                return {"ok": False, "mensaje": f"Buffer respondió {r.status_code}"}
            j = r.json()
            if j.get("errors"):
                return {"ok": False, "mensaje": " · ".join(e.get("message", "") for e in j["errors"])}
            p = (j.get("data") or {}).get("posts")
            if not p:
                return {"ok": False, "mensaje": "Buffer no devolvió posts"}
            posts += [_normalizar(e["node"]) for e in p["edges"]]
            info = p["pageInfo"]
            if not info.get("hasNextPage") or not info.get("endCursor") or info["endCursor"] == after:
                break
            after = info["endCursor"]
    except requests.RequestException as e:
        return {"ok": False, "mensaje": f"No se pudo llamar a Buffer: {type(e).__name__}"}
    return {"ok": True, "posts": posts}


# ── sincronizar ──────────────────────────────────────────────────────────────

def _destinos() -> List[str]:
    return [s.strip() for s in os.getenv("INSTAGRAM_AVISOS_CORREO", "").split(",") if s.strip()]


def _admin_url() -> str:
    return os.getenv("FYNDER_FRONTEND_URL", "https://getfynder.com").rstrip("/") + "/admin/instagram"


def _hora(iso: str) -> str:
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre"]
    h = d.hour % 12 or 12
    return f"{dias[d.weekday()]} {d.day} de {meses[d.month - 1]}, {h}:{d.minute:02d} {'p. m.' if d.hour >= 12 else 'a. m.'}"


def _correo(a: Dict[str, Any], siguiente: Optional[Dict[str, Any]]) -> Dict[str, str]:
    import html as H
    p = a["post"]
    que = tipo_legible(p.get("tipo"), len(p["miniaturas"]))
    cuando = p.get("sentAt") or p.get("dueAt")
    linea = primeras_lineas(p["texto"], 1, 70) if p["texto"] else ""
    publicado = a["motivo"] == "publicado"
    asunto = (f"✅ Publicado en Instagram · {que}{f' · {linea}' if linea else ''}" if publicado
              else f"⚠️ Falló una publicación de Instagram · {que}")
    titulo = f"Ya está en Instagram: {que.lower()}" if publicado else f"No se pudo publicar: {que.lower()}"
    color = "#0b8f52" if publicado else "#e11d48"
    historia = p.get("tipo") == "story"
    imgs = "".join(
        f'<img src="{H.escape(src)}" alt="" width="{110 if historia else 120 if len(p["miniaturas"]) > 1 else 240}" '
        f'style="border-radius:10px;margin:0 6px 6px 0;vertical-align:top">' for src in p["miniaturas"][:4])
    sig = (f"{tipo_legible(siguiente.get('tipo'), len(siguiente['miniaturas']))} · {_hora(siguiente['dueAt'])}"
           if siguiente and siguiente.get("dueAt") else None)
    cuerpo = H.escape(primeras_lineas(p["texto"], 4, 400)) if p["texto"] else ""
    html_ = f"""<!doctype html><html><body style="margin:0;background:#f4f4f1;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#111">
<div style="max-width:560px;margin:0 auto;padding:24px 16px">
  <div style="font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#0b8f52;font-weight:700">Instagram · @{H.escape(perfil())}</div>
  <h1 style="margin:8px 0 4px;font-size:24px;line-height:1.2">{H.escape(titulo)}</h1>
  <div style="font-size:14px;color:#6b6b66">{H.escape(_hora(cuando)) if cuando else ""} <span style="display:inline-block;margin-left:6px;padding:2px 8px;border-radius:999px;background:{color};color:#fff;font-size:12px;font-weight:600">{"Publicado" if publicado else "Con error"}</span></div>
  <div style="margin:18px 0;background:#fff;border:1px solid #e6e6e0;border-radius:16px;padding:14px">
    <div>{imgs}</div>
    {f'<p style="margin:10px 0 0;font-size:14px;line-height:1.5;white-space:pre-line">{cuerpo}</p>' if cuerpo else ""}
    {"" if publicado else f'<p style="margin:10px 0 0;font-size:14px;color:#e11d48"><b>Buffer dice:</b> {H.escape(p.get("error") or "sin mensaje")}</p>'}
  </div>
  <div>
    {f'<a href="{H.escape(p["link"])}" style="display:inline-block;margin:0 8px 8px 0;padding:10px 16px;border-radius:10px;background:#2AE38C;color:#04120a;text-decoration:none;font-weight:600;font-size:14px">Verlo en Instagram</a>' if publicado and p.get("link") else ""}
    <a href="{H.escape(_admin_url())}" style="display:inline-block;margin:0 8px 8px 0;padding:10px 16px;border-radius:10px;border:1px solid #0b8f52;color:#0b8f52;text-decoration:none;font-weight:600;font-size:14px">Ver la parrilla en el admin</a>
  </div>
  {f'<p style="margin:16px 0 0;font-size:13px;color:#6b6b66">Lo siguiente que sale: <b style="color:#111">{H.escape(sig)}</b></p>' if sig else ""}
  <p style="margin:24px 0 0;font-size:12px;color:#9a9a94">Aviso automático de Fynder · se revisa Buffer a las 7:00 a. m. y 7:00 p. m.</p>
</div></body></html>"""
    texto = "\n".join(x for x in [
        titulo, _hora(cuando) if cuando else "", f"\n{primeras_lineas(p['texto'], 4, 400)}" if p["texto"] else "",
        "" if publicado else f"\nBuffer dice: {p.get('error') or 'sin mensaje'}",
        f"\nVerlo en Instagram: {p['link']}" if publicado and p.get("link") else "",
        f"Ver la parrilla en el admin: {_admin_url()}", f"\nLo siguiente que sale: {sig}" if sig else "",
    ] if x)
    return {"asunto": asunto, "html": html_, "texto": texto}


def _es_proxima(p: Dict[str, Any]) -> bool:
    return p["estado"] in ("scheduled", "sending", "needs_approval") or (p["estado"] == "draft" and bool(p.get("dueAt")))


def sincronizar() -> Dict[str, Any]:
    """Buffer → instagram_posts → correos. Nunca lanza."""
    try:
        r = listar_posts()
        if not r["ok"]:
            return {"ok": False, "error": r["mensaje"]}
        posts = r["posts"]
        with get_db() as db:
            cur = db.cursor
            previos = {f["buffer_id"]: f["avisado_estado"] for f in
                       fetch_all(cur, "SELECT buffer_id, avisado_estado FROM instagram_posts")}
            primera_vez = not previos
            for p in posts:
                sembrar = primera_vez and p["estado"] in ("sent", "error")
                cur.execute("""
                    INSERT INTO instagram_posts (buffer_id, tipo, estado, due_at, sent_at, link, texto, miniaturas, imagenes,
                                                 n_imagenes, metricas, metricas_at, error, sincronizado_at, avisado_at, avisado_estado)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s, %s, NOW(),
                            CASE WHEN %s THEN NOW() END, CASE WHEN %s THEN %s END)
                    ON CONFLICT (buffer_id) DO UPDATE SET
                        tipo = EXCLUDED.tipo, estado = EXCLUDED.estado, due_at = EXCLUDED.due_at, sent_at = EXCLUDED.sent_at,
                        link = EXCLUDED.link, texto = EXCLUDED.texto, miniaturas = EXCLUDED.miniaturas,
                        imagenes = EXCLUDED.imagenes, n_imagenes = EXCLUDED.n_imagenes, metricas = EXCLUDED.metricas,
                        metricas_at = EXCLUDED.metricas_at, error = EXCLUDED.error, sincronizado_at = NOW()
                """, (p["id"], p["tipo"], p["estado"], p["dueAt"], p["sentAt"], p["link"], p["texto"],
                      json.dumps(p["miniaturas"]), json.dumps(p["imagenes"]), len(p["miniaturas"]),
                      json.dumps(p["metricas"]) if p["metricas"] is not None else None, p["metricasAt"], p["error"],
                      sembrar, sembrar, p["estado"]))
            # Lo que se borró en Buffer sale también de aquí. Nunca si Buffer devolvió cero: huele a error.
            if posts:
                cur.execute("DELETE FROM instagram_posts WHERE NOT (buffer_id = ANY(%s))", ([p["id"] for p in posts],))
            db.conn.commit()

        lista = por_avisar(sin_errores_reintentados(posts), previos, primera_vez)
        proximas = sorted([p for p in posts if _es_proxima(p)], key=lambda p: p.get("dueAt") or "")
        siguiente = proximas[0] if proximas else None
        enviados = 0
        destinos = _destinos()
        if destinos and lista and os.getenv("RESEND_API_KEY"):
            import resend
            from src.services.correo_service import _remitente as remitente
            resend.api_key = os.getenv("RESEND_API_KEY")
            for a in lista:
                c = _correo(a, siguiente)
                try:
                    resend.Emails.send({"from": remitente(), "to": destinos, "subject": c["asunto"],
                                        "html": c["html"], "text": c["texto"]})
                except Exception as e:  # noqa: BLE001 — sale en la siguiente corrida
                    print(f"[INSTAGRAM] correo {a['post']['id']}: {type(e).__name__}")
                    continue
                with get_db() as db:
                    db.cursor.execute("UPDATE instagram_posts SET avisado_at = NOW(), avisado_estado = %s WHERE buffer_id = %s",
                                      (a["post"]["estado"], a["post"]["id"]))
                    db.conn.commit()
                enviados += 1
        return {"ok": True, "posts": len(posts), "avisos": enviados, "sembrado": primera_vez}
    except Exception as e:  # noqa: BLE001
        print(f"[INSTAGRAM] sincronizar: {e}")
        return {"ok": False, "error": str(e)}


# ── lo que lee el admin ──────────────────────────────────────────────────────

def _iso(v) -> Optional[str]:
    return v.isoformat() if v else None


def posts() -> List[Dict[str, Any]]:
    with get_db() as db:
        filas = fetch_all(db.cursor, "SELECT * FROM instagram_posts ORDER BY due_at NULLS LAST")
    salida = [{
        "id": f["buffer_id"], "estado": f["estado"], "dueAt": _iso(f["due_at"]), "sentAt": _iso(f["sent_at"]),
        "link": f["link"], "texto": f["texto"] or "", "metricasAt": _iso(f["metricas_at"]), "error": f["error"],
        "metricas": f["metricas"], "miniaturas": f["miniaturas"] or [],
        "imagenes": f["imagenes"] or f["miniaturas"] or [],
        "tipo": f["tipo"] if f["tipo"] in ("post", "story", "reel") else None,
    } for f in filas]
    return sin_errores_reintentados(salida)


def ultima_sincronizacion() -> Optional[str]:
    with get_db() as db:
        return _iso(scalar(db.cursor, "SELECT MAX(sincronizado_at) FROM instagram_posts"))


def seguidores() -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        registros = [{"fecha": f["fecha"].isoformat(), "n": f["n"]} for f in
                     fetch_all(cur, "SELECT fecha, n FROM instagram_seguidores ORDER BY fecha DESC LIMIT 200")][::-1]
        meta = scalar(cur, "SELECT valor FROM instagram_config WHERE clave = 'meta_seguidores'")
    try:
        meta = int(meta) if meta and int(meta) > 0 else META_POR_DEFECTO
    except ValueError:
        meta = META_POR_DEFECTO
    return {"registros": registros, "meta": meta}


def anotar_seguidores(n: int, meta: Optional[int] = None, admin: Optional[str] = None) -> Dict[str, Any]:
    """Los seguidores de hoy (Bogotá). Uno por día: el último del día manda."""
    hoy = datetime.now(TZ).date()
    with get_db() as db:
        cur = db.cursor
        cur.execute("""
            INSERT INTO instagram_seguidores (fecha, n, creado_por) VALUES (%s, %s, %s)
            ON CONFLICT (fecha) DO UPDATE SET n = EXCLUDED.n, creado_por = EXCLUDED.creado_por, creado_at = NOW()
        """, (hoy, n, admin))
        if meta and meta > 0:
            cur.execute("""
                INSERT INTO instagram_config (clave, valor) VALUES ('meta_seguidores', %s)
                ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado_at = NOW()
            """, (str(meta),))
        db.conn.commit()
    return {"ok": True}


def estado() -> Dict[str, Any]:
    """Todo lo que pinta /admin/instagram en una sola respuesta (cero llamadas a Buffer)."""
    return {"posts": posts(), "sincronizado": ultima_sincronizacion(), "seguidores": seguidores(),
            "configurado": configurado(), "perfil": perfil()}
