"""
Mi página se edita conversando con Findy: el agente escribe lo que quiere («hazla más
elegante», «agrega un banner para propietarios») y Claude responde con una lista de
operaciones sobre el borrador, que el editor aplica y se ven en la vista previa al instante.

- Las operaciones son pocas y cerradas (abajo); lo que no cuadra con la página actual se
  descarta aquí, antes de llegar al editor. Al guardar, `pagina_agente_service.normalizar`
  vuelve a validar todo.
- Las imágenes con IA nunca se generan solas: Claude propone una (`imagen`) y el agente la
  crea desde el chat, viendo cuánto cupo le queda.
- Controles para tocar (`controles`): ante un pedido abierto («cambia el color», «dame opciones
  de titular») Claude ofrece opciones en vez de decidir. Se devuelven como programa OpenUI (`ui`,
  pagina_ui.py) y tocar una aplica el cambio en el editor sin otra llamada a la IA.
- Cupo: el mismo contador diario de la IA de la página (`pagina_ia_service`, 30 al día).
"""

import json
import re
from typing import Any, Dict, List, Optional

from src.services import pagina_agente_service as pagina
from src.services import pagina_ia_service as ia
from src.services import pagina_ui
from src.services.pagina_imagenes_service import ESTILOS, FORMATOS

OPS = ("config", "agente", "bloque", "agregar", "quitar", "ocultar", "mostrar", "mover", "inicio")
CAMPOS_CONFIG = ("plantilla", "color", "fuente", "fondo", "esquinas", "tarjetas", "columnas", "oscurecer", "animaciones",
                 "titular", "subtitular", "mensaje_whatsapp", "portada_url", "destacados", "cifras", "testimonios",
                 "preguntas", "redes")
CAMPOS_AGENTE = ("bio", "zonas", "marca_nombre", "logo_url", "foto_url")
INICIOS = ("barrio", "lujo", "arriendos", "cero")
_RUTA = re.compile(r"^(datos|estilo)\.[a-z_]+(\.(\d+|\+)(\.[a-z_]+)?)?$")
_URL = re.compile(r"^https://\S+$")
MAX_TURNOS = 10
CONTROLES = ("paleta", "plantillas", "letras", "textos", "secciones")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

_ESQUEMA = {
    "type": "object",
    "properties": {
        "respuesta": {"type": "string", "description": "Lo que le dices al agente: 1 a 3 frases, qué hiciste o qué necesitas saber."},
        "operaciones": {"type": "array", "description": "Los cambios a la página, en orden. Vacía si solo preguntas o respondes.",
                        "items": {"type": "object", "properties": {
                            "op": {"type": "string", "enum": list(OPS)},
                            "campo": {"type": "string", "description": "Para config y agente: el campo. Si no aplica, vacío."},
                            "id": {"type": "string", "description": "Id del bloque (bloque, quitar, ocultar, mostrar, mover). Si no aplica, vacío."},
                            "ruta": {"type": "string", "description": "Para bloque: datos.titulo, datos.texto, datos.eyebrow, datos.items, datos.pasos, datos.boton, datos.imagen_url, datos.lado, datos.imagenes, datos.columnas, datos.url, estilo.fondo, estilo.espacio, estilo.imagen_url. Si no aplica, vacío."},
                            "tipo": {"type": "string", "description": "Para agregar: el tipo de bloque. Si no aplica, vacío."},
                            "despues": {"type": "string", "description": "Para agregar y mover: id del bloque después del cual va. Vacío = al final (agregar)."},
                            "valor_json": {"type": "string", "description": "El valor nuevo como JSON (\"texto\", 3, true, [..], {..}). Para agregar: {\"datos\": {...}, \"estilo\": {...}}. Si no aplica, vacío."},
                            "plantilla_inicio": {"type": "string", "description": "Para inicio: barrio, lujo, arriendos o cero. Si no aplica, vacío."},
                        }, "required": ["op", "campo", "id", "ruta", "tipo", "despues", "valor_json", "plantilla_inicio"]}},
        "sugerencias": {"type": "array", "items": {"type": "string"}, "description": "3 pedidos cortos (máx. 40 caracteres) que el agente podría hacer después."},
        "controles": {"type": "array", "description": "Opciones para que el agente elija tocando (máx. 2). Vacía si aplicaste el cambio directo.",
                      "items": {"type": "object", "properties": {
                          "tipo": {"type": "string", "enum": list(CONTROLES)},
                          "titulo": {"type": "string", "description": "La pregunta corta: «Elige un color», «¿Cuál titular te gusta?»"},
                          "opciones": {"type": "array", "items": {"type": "string"},
                                       "description": "paleta: 5 colores hex; plantillas: 3 ids; letras: 3 ids; textos: 3 alternativas; secciones: hasta 4 tipos para agregar."},
                          "op": {"type": "string", "description": "Solo textos: dónde va el texto elegido: config, agente o bloque. Si no aplica, vacío."},
                          "campo": {"type": "string", "description": "Solo textos con op config/agente: titular, subtitular, mensaje_whatsapp o bio. Si no aplica, vacío."},
                          "id": {"type": "string", "description": "Solo textos con op bloque: id de la sección. Si no aplica, vacío."},
                          "ruta": {"type": "string", "description": "Solo textos con op bloque: datos.titulo, datos.texto o datos.eyebrow. Si no aplica, vacío."},
                      }, "required": ["tipo", "titulo", "opciones", "op", "campo", "id", "ruta"]}},
        "imagen": {"type": "object", "description": "Proponer una imagen con IA (no se crea hasta que el agente la confirme).", "properties": {
            "proponer": {"type": "boolean"},
            "descripcion": {"type": "string", "description": "Escena concreta, máx. 30 palabras, sin texto ni personas."},
            "estilo": {"type": "string", "enum": list(ESTILOS)},
            "formato": {"type": "string", "enum": list(FORMATOS)},
            "id": {"type": "string", "description": "Bloque donde va: \"portada\" para el fondo de la portada, o \"nuevo\" para la sección que agregas en esta misma respuesta."},
            "ruta": {"type": "string", "description": "config.portada_url, datos.imagen_url, estilo.imagen_url o datos.imagenes.+"},
        }, "required": ["proponer", "descripcion", "estilo", "formato", "id", "ruta"]},
    },
    "required": ["respuesta", "operaciones", "sugerencias", "controles", "imagen"],
}

GUIA = f"""Eres Findy y editas la página web de un agente inmobiliario conversando con él. No hay botones: todo
lo que él pida lo haces tú con operaciones sobre la página. Habla corto y claro, tuteando, sin jerga técnica
(nada de «bloque», «JSON», «ruta»: di «sección», «la parte de arriba», etc.).

Cómo es la página:
- Una lista de secciones (bloques) con id. La portada va siempre primero y no se quita ni se mueve.
- Secciones de una sola vez (sus datos viven en la configuración general): sobre_mi (usa la bio), destacados (config.destacados,
  hasta 3 ids de inmuebles), cifras (config.cifras {{anos, vendidos, familias}}), inmuebles (salen solos), testimonios
  (config.testimonios [{{nombre, texto, detalle}}]), zonas (agente.zonas), preguntas (config.preguntas [{{p, r}}]),
  valorador, redes (config.redes {{instagram, facebook, tiktok, youtube, linkedin, web}}).
  Su título y antetítulo se cambian con op bloque, ruta datos.titulo / datos.eyebrow.
- Secciones que se repiten (datos propios): texto_imagen {{eyebrow, titulo, texto, imagen_url, lado: izq|der, boton}},
  banner {{titulo, texto, imagen_url, boton}}, galeria {{titulo, imagenes: [{{url, pie}}], columnas: 2|3|4}},
  video {{titulo, texto, url (YouTube, Vimeo o Instagram)}}, proceso {{titulo, pasos: [{{titulo, texto}}] máx. 6}},
  servicios {{titulo, items: [{{icono, titulo, texto}}] máx. 6, icono en {", ".join(pagina.ICONOS)}}}.
  boton = {{texto, accion: whatsapp|valorar|inmuebles|link, url si es link}}.
- Estilo de cada sección: estilo.fondo pagina|marca|oscuro|imagen (imagen requiere estilo.imagen_url), estilo.espacio compacto|normal|amplio.
- Configuración general (op config): plantilla {"|".join(pagina.PLANTILLAS)}; color hex (preferible uno de {", ".join(ia.PALETA)});
  fuente {"|".join(pagina.FUENTES)}; fondo {"|".join(pagina.FONDOS)}; esquinas {"|".join(pagina.ESQUINAS)};
  tarjetas {"|".join(pagina.TARJETAS)}; columnas 2|3; oscurecer 0–80; animaciones true|false; titular (máx. 90);
  subtitular (máx. 160); mensaje_whatsapp (máx. 160); portada_url.
- Del agente (op agente): bio (máx. 600, primera persona), zonas (lista, máx. 8), marca_nombre, logo_url, foto_url.
- op inicio: rearma las secciones con una plantilla de inicio (barrio, lujo, arriendos, cero) conservando lo escrito.

Reglas:
- Ante un pedido general («más elegante», «más moderna») cambia varias cosas coherentes a la vez (plantilla, fuente, color,
  fondo, títulos) y explica en una frase. No preguntes lo que puedes decidir tú.
- Ante un pedido abierto donde el gusto del agente manda («cambia el color», «otra letra», «otro titular», «qué sección
  agrego») NO decidas: ofrece `controles` para que elija tocando (paleta de 5 colores que combinen, 3 plantillas, 3 letras,
  3 textos alternativos o hasta 4 secciones) y no hagas operaciones sobre eso. Máximo 2 controles por respuesta.
- Nunca inventes cifras, años de experiencia, ventas, premios ni testimonios. Si piden testimonios o cifras, pídeselos.
- Cuando el agente señala una sección («esto»), se refiere a la sección seleccionada que te indico.
- Las imágenes con IA cuestan cupo: propónla en `imagen` (proponer=true) y dile que la confirme en el chat. Si es para una
  sección que agregas en esta misma respuesta, usa id «nuevo». No uses op para
  inventar URLs de imágenes: solo URLs que te dé el agente (adjuntas) o que ya estén en la página.
- Si el agente adjunta una imagen ([imagen adjunta: URL]) y no dice dónde va, decide por contexto (logo si parece logo,
  foto si es una persona, fondo de portada si es un espacio) o pregúntale.
- Para agregar una sección, escribe su contenido completo y bueno (nada de «Lorem ipsum»), con lo que sabes del agente.
- Dinero en millones («$450 millones»), sin emojis."""


class ChatPaginaError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def _parse(v: str) -> Any:
    if v is None or v == "":
        return None
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return v  # un texto suelto sin comillas también sirve como valor de texto


def _urls_ok(v: Any) -> bool:
    """Las URLs que vengan en un valor deben ser https (nada de javascript:, data:, http:)."""
    if isinstance(v, str):
        return not re.match(r"^\s*(javascript|data|http):", v, re.I) and (not v.startswith("http") or bool(_URL.match(v)))
    if isinstance(v, list):
        return all(_urls_ok(x) for x in v)
    if isinstance(v, dict):
        return all(_urls_ok(x) for x in v.values())
    return True


def validar(operaciones: List[Dict[str, Any]], bloques: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deja solo las operaciones que se pueden aplicar a esta página, con `valor` ya parseado."""
    ids = {b.get("id") for b in bloques}
    tipos = {b.get("id"): b.get("tipo") for b in bloques}
    out: List[Dict[str, Any]] = []
    for o in operaciones or []:
        if not isinstance(o, dict) or o.get("op") not in OPS:
            continue
        op, bid, valor = o["op"], (o.get("id") or "").strip(), _parse(o.get("valor_json") or "")
        if not _urls_ok(valor):
            continue
        if op == "config":
            if o.get("campo") in CAMPOS_CONFIG:
                out.append({"op": op, "campo": o["campo"], "valor": valor})
        elif op == "agente":
            if o.get("campo") in CAMPOS_AGENTE:
                out.append({"op": op, "campo": o["campo"], "valor": valor})
        elif op == "bloque":
            ruta = (o.get("ruta") or "").strip()
            if bid in ids and _RUTA.match(ruta) and not (tipos[bid] == "portada" and ruta.startswith("datos")):
                out.append({"op": op, "id": bid, "ruta": ruta, "valor": valor})
        elif op == "agregar":
            tipo = o.get("tipo")
            despues = (o.get("despues") or "").strip()
            if tipo in pagina.REPETIBLES + pagina.SECCIONES and (not despues or despues in ids):
                extra = valor if isinstance(valor, dict) else {}
                out.append({"op": op, "tipo": tipo, "despues": despues or None,
                            "datos": extra.get("datos") if isinstance(extra.get("datos"), dict) else {},
                            "estilo": extra.get("estilo") if isinstance(extra.get("estilo"), dict) else {}})
        elif op in ("quitar", "mover"):
            despues = (o.get("despues") or "").strip()
            if bid in ids and tipos[bid] != "portada" and (op == "quitar" or despues in ids):
                out.append({"op": op, "id": bid, **({"despues": despues} if op == "mover" else {})})
        elif op in ("ocultar", "mostrar"):
            if bid in ids:
                out.append({"op": op, "id": bid})
        elif op == "inicio":
            if o.get("plantilla_inicio") in INICIOS:
                out.append({"op": op, "plantilla_inicio": o["plantilla_inicio"]})
    return out


def controles(crudos: List[Dict[str, Any]], bloques: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Los controles para tocar, con opciones válidas (colores hex, ids existentes, destino aplicable)."""
    out: List[Dict[str, Any]] = []
    for c in crudos or []:
        if not isinstance(c, dict) or c.get("tipo") not in CONTROLES:
            continue
        t, titulo = c["tipo"], (c.get("titulo") or "").strip()[:80] or "Elige una opción"
        ops = [o.strip() for o in c.get("opciones") or [] if isinstance(o, str) and o.strip()]
        if t == "paleta":
            ops = [o.upper() for o in ops if _HEX.match(o)][:6]
        elif t == "plantillas":
            ops = [o for o in ops if o in pagina.PLANTILLAS][:4]
        elif t == "letras":
            ops = [o for o in ops if o in pagina.FUENTES][:4]
        elif t == "secciones":
            ops = [o for o in ops if o in pagina.REPETIBLES + pagina.SECCIONES][:4]
        else:  # textos
            ops = [o[:600] for o in ops][:4]
            destino = validar([{"op": c.get("op"), "campo": c.get("campo"), "id": c.get("id"), "ruta": c.get("ruta"),
                                "valor_json": json.dumps(ops[0] if ops else "")}], bloques)
            if not ops or not destino or destino[0]["op"] not in ("config", "agente", "bloque"):
                continue
            d = destino[0]
            out.append({"tipo": t, "titulo": titulo, "opciones": ops,
                        "destino": {k: d[k] for k in ("op", "campo", "id", "ruta") if k in d}})
            continue
        if len(ops) >= 2:
            out.append({"tipo": t, "titulo": titulo, "opciones": list(dict.fromkeys(ops))})
    return out[:2]


def _imagen(r: Dict[str, Any], ids: set, agrega: bool = False) -> Optional[Dict[str, Any]]:
    """La imagen que propone Claude, con un destino que exista. «nuevo» = la sección que agrega en la
    misma respuesta (el editor le pone el id al aplicarla)."""
    im = r.get("imagen") or {}
    if not im.get("proponer") or len((im.get("descripcion") or "").strip()) < 4:
        return None
    bid, ruta = (im.get("id") or "portada").strip(), (im.get("ruta") or "").strip()
    if agrega:
        ids = ids | {"nuevo"}
    if ruta == "config.portada_url" or bid == "portada":
        bid, ruta = "portada", "config.portada_url"
    elif bid not in ids or ruta not in ("datos.imagen_url", "estilo.imagen_url", "datos.imagenes.+"):
        bid, ruta = "portada", "config.portada_url"
    return {"descripcion": im["descripcion"].strip()[:400], "estilo": im.get("estilo") if im.get("estilo") in ESTILOS else "natural",
            "formato": im.get("formato") if im.get("formato") in FORMATOS else ("cuadrada" if ruta == "datos.imagenes.+" else "ancha"),
            "id": bid, "ruta": ruta}


def _pagina_para_prompt(b: Dict[str, Any]) -> str:
    c = b.get("config") or {}
    general = {k: c.get(k) for k in CAMPOS_CONFIG if k in c}
    secciones = [{"id": x.get("id"), "tipo": x.get("tipo"), "visible": x.get("visible", True),
                  "estilo": x.get("estilo"), "datos": x.get("datos")} for x in c.get("bloques") or []]
    agente = {"bio": b.get("bio"), "zonas": b.get("zonas"), "marca_nombre": b.get("marca_nombre"),
              "tiene_logo": bool(b.get("logo_url")), "tiene_foto": bool(b.get("foto_url"))}
    return json.dumps({"general": general, "agente": agente, "secciones": secciones}, ensure_ascii=False)[:14000]


def conversar(user_id: int, mensajes: List[Dict[str, Any]], borrador: Dict[str, Any],
              seleccionado: Optional[str] = None) -> Dict[str, Any]:
    turnos = [m for m in (mensajes or []) if isinstance(m, dict) and isinstance(m.get("texto"), str) and m["texto"].strip()]
    if not turnos or turnos[-1].get("rol") != "agente":
        raise ChatPaginaError("vacio", "Escríbeme qué quieres cambiar de tu página.")
    if not isinstance(borrador, dict) or not isinstance(borrador.get("config"), dict):
        raise ChatPaginaError("datos", "No llegó tu página. Recarga e intenta de nuevo.")
    ia._cupo(user_id)

    actual = pagina.mi_pagina(user_id)
    a = actual["vista"]["agente"]
    bloques = borrador["config"].get("bloques") or []
    sel = next((x for x in bloques if x.get("id") == seleccionado), None)
    historial = "\n".join(f"{'Agente' if m.get('rol') == 'agente' else 'Findy'}: {m['texto'].strip()[:1200]}"
                          for m in turnos[-MAX_TURNOS:])
    prompt = "\n\n".join(filter(None, [
        GUIA,
        f"El agente: {a['nombre']}" + (f" ({borrador.get('marca_nombre') or a.get('marca_nombre')})" if borrador.get("marca_nombre") or a.get("marca_nombre") else ""),
        "Sus inmuebles:\n" + ia._resumen_inventario(actual["vista"]["inmuebles"]),
        "La página como está ahora:\n" + _pagina_para_prompt(borrador),
        f"Sección seleccionada (a la que se refiere con «esto»): {json.dumps({'id': sel.get('id'), 'tipo': sel.get('tipo')}, ensure_ascii=False)}" if sel else None,
        "La conversación (responde al último mensaje del agente):\n" + historial,
    ]))
    r = ia._llamar(prompt, _ESQUEMA, "pagina_chat", max_tokens=4000)
    ids = {x.get("id") for x in bloques}
    operaciones = validar(r.get("operaciones") or [], bloques)
    respuesta = (r.get("respuesta") or "Listo.").strip()[:800]
    ctrls = controles(r.get("controles") or [], bloques)
    return {
        "respuesta": respuesta,
        "ui": pagina_ui.programa(respuesta, ctrls) if ctrls else None,
        "operaciones": operaciones,
        "sugerencias": [s.strip()[:60] for s in r.get("sugerencias") or [] if isinstance(s, str) and s.strip()][:3],
        "imagen": _imagen(r, ids, any(o["op"] == "agregar" for o in operaciones)),
        "quedan": ia._contar(user_id),
    }
