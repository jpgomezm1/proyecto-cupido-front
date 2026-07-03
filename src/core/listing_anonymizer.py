#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anonimizador de listings (titulo + descripcion).

Reescribe con IA (Claude) el titulo y la descripcion de una propiedad para que:
  - El texto sea 100% ORIGINAL y no coincida con el publicado en otros portales
    (Wasi/Lobbie/tu360/Fincaraiz, etc.), evitando que se rastree la propiedad
    y que se "salten" a Fynder en el negocio.
  - Se ELIMINEN identificadores unicos (nombre de edificio/conjunto, numero de
    unidad/apto, direccion exacta, telefonos, asesor/inmobiliaria, codigo de
    portal, URLs).
  - Se CONSERVEN los datos genericos veridicos (tipo, ciudad, zona, area,
    habitaciones, banos, parqueaderos, estrato, precio, amenidades).

Se usa en dos lugares:
  - scripts/anonymize_property_listings.py (migracion masiva de lo ya cargado).
  - db.insert_property() (cada captura nueva entra ya anonimizada -> no recurre).
"""

import os
import sys
import json
import time
from datetime import datetime

ANONIMIZADO_VERSION = 1
DEFAULT_MODEL = 'claude-haiku-4-5-20251001'  # rapido y economico para escala

_client = None


def _build_ssl_context():
    """Contexto SSL que confia en el almacen de certificados del SO.

    Necesario cuando hay un proxy corporativo que intercepta TLS y presenta una
    CA raiz que no esta en certifi (el caso de la maquina de desarrollo). En
    Windows tambien carga explicitamente los stores ROOT/CA.
    """
    import ssl
    ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
    except Exception:
        pass
    if sys.platform == 'win32':
        for store in ('ROOT', 'CA'):
            try:
                for cert, _enc, _trust in ssl.enum_certificates(store):
                    try:
                        ctx.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(cert))
                    except Exception:
                        pass
            except Exception:
                pass
    return ctx


def get_client():
    """Cliente Anthropic (singleton) con verificacion SSL del store del SO."""
    global _client
    if _client is None:
        import anthropic
        import httpx
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY no esta definida")
        _client = anthropic.Anthropic(
            api_key=api_key,
            http_client=httpx.Client(verify=_build_ssl_context()),
        )
    return _client


PROMPT_TEMPLATE = """Eres un redactor inmobiliario para el portal Fynder. Reescribe el TITULO y la DESCRIPCION de una propiedad de forma 100% ORIGINAL, para que el texto NO coincida con lo publicado en otros portales (Wasi, Lobbie, Fincaraiz, etc.) y NO se pueda rastrear la propiedad en otro lugar.

REGLAS OBLIGATORIAS:
1. Redaccion completamente nueva: no copies frases ni la estructura del texto original. Cambia vocabulario y orden de las ideas.
2. ELIMINA por completo cualquier identificador unico que permita encontrar la propiedad en otro portal:
   - Nombre propio del edificio, conjunto, unidad residencial, torre o proyecto (ej: "Avinon", "Castropol", "Torre Verde").
   - Numero de apartamento/casa/interior y el piso/nivel exacto.
   - Direccion o nomenclatura exacta (carrera/calle/numero).
   - Telefonos, correos, nombres de asesor o inmobiliaria, URLs y codigos de inmueble.
3. CONSERVA y usa solo datos genericos y veridicos provistos abajo (no inventes nada): tipo de inmueble, ciudad, zona/sector, area, habitaciones, banos, parqueaderos, estrato, precio, administracion y amenidades.
4. Ubicacion: menciona unicamente la zona/sector y la ciudad (ej: "El Poblado, Medellin"). Nunca el nombre del edificio ni la direccion.
5. Espanol neutro, tono profesional y atractivo. La descripcion debe tener 2 o 3 parrafos cortos.

FORMATO DE SALIDA: responde UNICAMENTE con un objeto JSON valido, sin markdown ni texto adicional:
{{"titulo": "<titulo nuevo, maximo ~70 caracteres>", "descripcion": "<descripcion nueva>"}}

DATOS VERIDICOS DE LA PROPIEDAD:
{datos}

TEXTO ORIGINAL (solo de referencia para entender la propiedad, PROHIBIDO copiarlo):
TITULO ORIGINAL: {titulo}
DESCRIPCION ORIGINAL: {descripcion}"""


def _fmt(v):
    return v if (v is not None and str(v).strip() != '') else None


def build_datos_block(prop):
    """Arma el bloque de datos veridicos genericos (sin identificadores)."""
    campos = [
        ('Tipo de inmueble', prop.get('tipo_propiedad')),
        ('Tipo de negocio', prop.get('tipo_negocio')),
        ('Ciudad', prop.get('ciudad')),
        ('Zona/sector', prop.get('zona')),
        ('Area construida (m2)', prop.get('area_construida')),
        ('Habitaciones', prop.get('habitaciones')),
        ('Banos', prop.get('banos')),
        ('Parqueaderos', prop.get('parqueaderos')),
        ('Estrato', prop.get('estrato')),
        ('Ano de construccion', prop.get('ano_construccion')),
        ('Precio', prop.get('precio_texto') or prop.get('precio')),
        ('Administracion', prop.get('administracion')),
        ('Amenidades internas', prop.get('amenidades_internas')),
        ('Amenidades externas', prop.get('amenidades_externas')),
    ]
    lines = [f"- {k}: {_fmt(v)}" for k, v in campos if _fmt(v) is not None]
    return '\n'.join(lines) if lines else '- (sin datos estructurados)'


def _strip_json(text):
    """Quita fences de markdown y extrae el objeto JSON."""
    t = text.strip()
    if t.startswith('```'):
        t = t[3:]
        if t.lower().startswith('json'):
            t = t[4:]
        t = t.strip().strip('`').strip()
    start = t.find('{')
    end = t.rfind('}')
    if start != -1 and end != -1 and end > start:
        t = t[start:end + 1]
    return t


def rewrite_listing(prop, model=DEFAULT_MODEL):
    """Llama a Claude y devuelve (titulo_nuevo, descripcion_nueva).

    Cualquiera de los dos puede ser None si la IA no devolvio un valor valido.
    Lanza excepcion si falla la llamada a la API (el caller decide que hacer).
    """
    datos = build_datos_block(prop)
    titulo = (prop.get('titulo') or '')[:500]
    descripcion = (prop.get('descripcion') or '')[:4000]

    prompt = PROMPT_TEMPLATE.format(datos=datos, titulo=titulo, descripcion=descripcion)

    client = get_client()
    start_time = time.time()
    message = client.messages.create(
        model=model,
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )

    # Tracking de costo (consistente con el resto del codebase)
    try:
        from src.core.ai_usage_tracker import get_ai_tracker
        get_ai_tracker().track_anthropic_response(
            model=model,
            usage_type='listing_anonymization',
            function_name='listing_anonymizer.rewrite_listing',
            response=message,
            start_time=start_time,
            context={'property_id': prop.get('id'), 'fuente': prop.get('fuente')},
        )
    except Exception:
        pass

    raw = message.content[0].text
    try:
        data = json.loads(_strip_json(raw))
    except Exception:
        return None, None

    nuevo_titulo = (data.get('titulo') or '').strip()
    nueva_desc = (data.get('descripcion') or '').strip()

    if not nuevo_titulo or len(nuevo_titulo) < 5:
        nuevo_titulo = None

    tenia_desc = bool(prop.get('descripcion') and len(prop['descripcion']) > 50)
    if not nueva_desc or len(nueva_desc) < 20:
        # Si la propiedad no tenia descripcion (ej: Lobbie) no la exigimos.
        nueva_desc = None if tenia_desc else (nueva_desc or None)

    return nuevo_titulo, nueva_desc


def apply_anonymization(prop, model=DEFAULT_MODEL):
    """Anonimiza un dict de propiedad EN SITIO (para el flujo de captura).

    - Respalda el texto crudo en titulo_original / descripcion_original.
    - Reemplaza titulo / descripcion por la version reescrita.
    - Marca anonimizado_version y anonimizado_at.

    Es defensivo: si ya viene anonimizado, si no hay texto, o si la IA falla,
    deja la propiedad utilizable (con el texto que tenga) y NO la marca, para
    que la migracion masiva pueda corregirla luego. Devuelve True si reescribio.
    """
    # Ya anonimizado aguas arriba -> no repetir.
    if prop.get('anonimizado_version'):
        return False

    tiene_titulo = bool(prop.get('titulo'))
    tiene_desc = bool(prop.get('descripcion'))
    if not tiene_titulo and not tiene_desc:
        return False

    try:
        nuevo_titulo, nueva_desc = rewrite_listing(prop, model)
    except Exception as e:
        print(f"[anonymizer] No se pudo anonimizar (se guarda texto original): {e}")
        return False

    if not nuevo_titulo and nueva_desc is None:
        print("[anonymizer] Respuesta IA invalida; se guarda texto original sin marcar")
        return False

    # Respaldo del original (solo si no existe ya)
    if not prop.get('titulo_original'):
        prop['titulo_original'] = prop.get('titulo')
    if not prop.get('descripcion_original'):
        prop['descripcion_original'] = prop.get('descripcion')

    if nuevo_titulo:
        prop['titulo'] = nuevo_titulo
    if nueva_desc is not None:
        prop['descripcion'] = nueva_desc
        prop['descripcion_length'] = len(nueva_desc)

    prop['anonimizado_version'] = ANONIMIZADO_VERSION
    prop['anonimizado_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return True
