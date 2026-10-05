"""
Edición de inmuebles por su DUEÑO (Mis propiedades en la web).

Dueño = el usuario del chat cuyo teléfono VERIFICADO coincide (últimos 10
dígitos) con `agente_captador_telefono`. Un teléfono auto-declarado no da
control sobre inventario ajeno (regla del sistema).

Cada campo que el agente edita queda en `propiedades.campos_editados`: si el
inmueble vino de Wasi/Lobbie y se vuelve a capturar, el upsert respeta esos
campos (db/database.py). Las fotos se marcan como editadas al tocarlas.

Sin Flask: la API (listings) lo usa; las validaciones devuelven EdicionError
con el campo para mostrarlo junto al input.
"""
from typing import Any, Dict, List, Optional

from src.services.db import fetch_one, get_db
from src.services.textutils import split_image_urls

PRECIO_MIN = 100_000
PRECIO_MAX = 100_000_000_000

TIPOS = {"Apartamento", "Apartaestudio", "Casa", "Casa campestre", "Penthouse", "Lote",
         "Local", "Oficina", "Bodega", "Finca", "Consultorio", "Dúplex"}

# campo -> (tipo, min, max)
_NUMEROS = {
    "precio": (int, PRECIO_MIN, PRECIO_MAX),
    "administracion": (int, 0, 50_000_000),
    "area_construida": (float, 5, 100_000),
    "habitaciones": (int, 0, 50),
    "banos": (int, 0, 50),
    "parqueaderos": (int, 0, 50),
    "estrato": (int, 1, 6),
}
_TEXTOS = {  # campo api -> (columna, largo máximo)
    "titulo": ("titulo", 160),
    "descripcion": ("descripcion", 8000),
    "tipo_propiedad": ("tipo_propiedad", 60),
    "tipo_negocio": ("tipo_negocio", 20),
    "ciudad": ("ciudad", 80),
    "zona": ("zona", 120),
    "direccion": ("direccion_completa", 240),
}
_LISTAS = {"amenidades_internas", "amenidades_externas"}
_FOTOS = ["imagenes_urls", "imagen_principal", "total_imagenes"]

_COLUMNAS = """
    id, codigo_propiedad, titulo, descripcion, precio, tipo_propiedad, tipo_negocio, ciudad, zona,
    direccion_completa, area_construida, habitaciones, banos, parqueaderos, estrato, administracion,
    amenidades_internas, amenidades_externas, imagenes_urls, imagen_principal, fuente, url, activa,
    campos_editados, editado_por_agente_at, fecha_actualizacion
"""
_ES_DUENO = "RIGHT(REGEXP_REPLACE(COALESCE(agente_captador_telefono,''), '[^0-9]', '', 'g'), 10) = %s"


class EdicionError(Exception):
    def __init__(self, mensaje: str, campo: Optional[str] = None, status: int = 400):
        super().__init__(mensaje)
        self.mensaje, self.campo, self.status = mensaje, campo, status


def _lista(v) -> List[str]:
    if not v:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v).split("|") if x.strip()]


def _origen(fuente: Optional[str]) -> str:
    f = (fuente or "").lower()
    if "wasi" in f:
        return "wasi"
    if "lobbie" in f:
        return "lobbie"
    if f in ("fynder", "propia"):
        return "fynder"
    return "otro"


def _salida(row: Dict[str, Any]) -> Dict[str, Any]:
    num = lambda v, t=int: (t(v) if v is not None else None)  # noqa: E731
    return {
        "id": row["id"],
        "codigo": row.get("codigo_propiedad"),
        "share_slug": row.get("codigo_propiedad") or str(row["id"]),
        "titulo": row.get("titulo"),
        "descripcion": row.get("descripcion"),
        "precio": num(row.get("precio")),
        "tipo_propiedad": row.get("tipo_propiedad"),
        "tipo_negocio": row.get("tipo_negocio"),
        "ciudad": row.get("ciudad"),
        "zona": row.get("zona"),
        "direccion": row.get("direccion_completa"),
        "area_construida": num(row.get("area_construida"), float),
        "habitaciones": num(row.get("habitaciones")),
        "banos": num(row.get("banos")),
        "parqueaderos": num(row.get("parqueaderos")),
        "estrato": num(row.get("estrato")),
        "administracion": num(row.get("administracion")),
        "amenidades_internas": _lista(row.get("amenidades_internas")),
        "amenidades_externas": _lista(row.get("amenidades_externas")),
        "fotos": split_image_urls(row.get("imagenes_urls")),
        "fuente": row.get("fuente"),
        "origen": _origen(row.get("fuente")),
        "url_original": row.get("url"),
        "activa": bool(row.get("activa")),
        "campos_editados": list(row.get("campos_editados") or []),
        "editado_por_agente_at": row["editado_por_agente_at"].isoformat() if row.get("editado_por_agente_at") else None,
        "fecha_actualizacion": row["fecha_actualizacion"].isoformat() if row.get("fecha_actualizacion") else None,
    }


def _cargar(cur, property_id: int, tel10: str, bloquear: bool = False) -> Dict[str, Any]:
    if not tel10:
        raise EdicionError("Verifica tu celular para editar tus inmuebles.", status=403)
    row = fetch_one(cur, f"SELECT {_COLUMNAS} FROM propiedades WHERE id = %s AND {_ES_DUENO}"
                         f"{' FOR UPDATE' if bloquear else ''}", (property_id, tel10))
    if not row:
        raise EdicionError("Este inmueble no existe o no está a tu nombre.", status=404)
    return row


def obtener(property_id: int, tel10: str) -> Dict[str, Any]:
    with get_db() as db:
        return _salida(_cargar(db.cursor, property_id, tel10))


def validar(cambios: Dict[str, Any]) -> Dict[str, Any]:
    """Valida y normaliza el body del PATCH -> {columna: valor}. Ignora claves desconocidas."""
    sets: Dict[str, Any] = {}
    for campo, valor in (cambios or {}).items():
        if campo in _NUMEROS:
            tipo, lo, hi = _NUMEROS[campo]
            if valor is None or (isinstance(valor, str) and not valor.strip()):
                if campo in ("precio",):
                    raise EdicionError("El precio no puede quedar vacío.", campo)
                sets[campo] = None
                continue
            if isinstance(valor, bool):
                raise EdicionError("Debe ser un número.", campo)
            try:
                if isinstance(valor, str):
                    # enteros: "650.000.000" -> 650000000; área: "86,5" -> 86.5
                    texto = "".join(ch for ch in valor if ch.isdigit()) if tipo is int else valor.strip().replace(",", ".")
                    v = tipo(float(texto))
                else:
                    v = tipo(float(valor))
            except (TypeError, ValueError):
                raise EdicionError("Debe ser un número.", campo)
            if v < lo or v > hi:
                if campo == "precio":
                    raise EdicionError("Revisa el precio: escríbelo completo, en pesos (ej. 650.000.000).", campo)
                raise EdicionError(f"Debe estar entre {lo} y {hi}.", campo)
            sets[campo] = v
        elif campo in _TEXTOS:
            columna, largo = _TEXTOS[campo]
            v = (str(valor).strip() if valor is not None else "") or None
            if v and len(v) > largo:
                raise EdicionError(f"Máximo {largo} caracteres.", campo)
            if campo == "titulo" and not v:
                raise EdicionError("El título no puede quedar vacío.", campo)
            if campo == "tipo_negocio" and v and v not in ("Venta", "Arriendo"):
                raise EdicionError("Elige Venta o Arriendo.", campo)
            if campo == "tipo_propiedad" and v and v not in TIPOS:
                raise EdicionError("Elige un tipo de inmueble de la lista.", campo)
            sets[columna] = v
        elif campo in _LISTAS:
            items = _lista(valor)
            if len(items) > 60:
                raise EdicionError("Máximo 60 amenidades.", campo)
            sets[campo] = "|".join(dict.fromkeys(i[:80] for i in items)) or None
    if not sets:
        raise EdicionError("No hay cambios para guardar.")
    return sets


def editar(property_id: int, tel10: str, cambios: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    sets = validar(cambios)
    with get_db() as db:
        antes = _cargar(db.cursor, property_id, tel10, bloquear=True)
        cols = list(sets.keys())
        asignaciones = [f"{c} = %s" for c in cols]
        params: List[Any] = [sets[c] for c in cols]
        if "descripcion" in sets:
            asignaciones.append("descripcion_length = %s")
            params.append(len(sets["descripcion"]) if sets["descripcion"] else None)
        if _LISTAS & set(cols):
            asignaciones.append("""total_amenidades =
                COALESCE(array_length(string_to_array(NULLIF(COALESCE(%s, amenidades_internas), ''), '|'), 1), 0)
              + COALESCE(array_length(string_to_array(NULLIF(COALESCE(%s, amenidades_externas), ''), '|'), 1), 0)""")
            params.extend([sets.get("amenidades_internas"), sets.get("amenidades_externas")])
        asignaciones.append("campos_editados = (SELECT ARRAY(SELECT DISTINCT unnest(campos_editados || %s::text[])))")
        params.append(cols)
        asignaciones += ["editado_por_agente_at = NOW()", "fecha_actualizacion = NOW()"]
        db.cursor.execute(
            f"UPDATE propiedades SET {', '.join(asignaciones)} WHERE id = %s AND {_ES_DUENO}",
            params + [property_id, tel10])
        db.conn.commit()
        despues = _cargar(db.cursor, property_id, tel10)
        try:
            db.log_evento(
                tipo_evento="agent_property_edit", agente_telefono=user.get("telefono"),
                propiedad_id=property_id,
                datos_evento={"origen": "chat_mis_propiedades", "chat_user_id": user.get("id"),
                              "campos": cols,
                              "precio_anterior": antes.get("precio") if "precio" in cols else None,
                              "precio_nuevo": sets.get("precio")},
            )
        except Exception as e:  # noqa: BLE001 — la auditoría no tumba la edición
            print(f"[mis-propiedades] no se pudo auditar {property_id}: {e}")
        return _salida(despues)


def _guardar_fotos(db, property_id: int, tel10: str, urls: List[str]) -> Dict[str, Any]:
    db.cursor.execute(f"""
        UPDATE propiedades
        SET imagenes_urls = %s, imagen_principal = %s, total_imagenes = %s,
            campos_editados = (SELECT ARRAY(SELECT DISTINCT unnest(campos_editados || %s::text[]))),
            editado_por_agente_at = NOW(), fecha_actualizacion = NOW()
        WHERE id = %s AND {_ES_DUENO}
    """, ("|".join(urls) or None, urls[0] if urls else None, len(urls), _FOTOS, property_id, tel10))
    db.conn.commit()
    return _salida(_cargar(db.cursor, property_id, tel10))


def agregar_fotos(property_id: int, tel10: str, urls: List[str]) -> Dict[str, Any]:
    nuevas = [u.strip() for u in (urls or []) if isinstance(u, str) and u.strip().startswith("https://")]
    if not nuevas:
        raise EdicionError("Sube al menos una foto.")
    with get_db() as db:
        row = _cargar(db.cursor, property_id, tel10, bloquear=True)
        actuales = split_image_urls(row.get("imagenes_urls"))
        combinadas = actuales + [u for u in nuevas if u not in actuales]
        if len(combinadas) > 60:
            raise EdicionError("Máximo 60 fotos por inmueble.")
        return _guardar_fotos(db, property_id, tel10, combinadas)


def ordenar_fotos(property_id: int, tel10: str, orden: List[str]) -> Dict[str, Any]:
    with get_db() as db:
        row = _cargar(db.cursor, property_id, tel10, bloquear=True)
        actuales = split_image_urls(row.get("imagenes_urls"))
        if sorted(orden or []) != sorted(actuales):
            raise EdicionError("El orden debe incluir cada foto una sola vez. Recarga e intenta de nuevo.")
        return _guardar_fotos(db, property_id, tel10, list(orden))


def quitar_foto(property_id: int, tel10: str, url: str) -> Dict[str, Any]:
    with get_db() as db:
        row = _cargar(db.cursor, property_id, tel10, bloquear=True)
        actuales = split_image_urls(row.get("imagenes_urls"))
        if url not in actuales:
            raise EdicionError("Esa foto ya no está en el inmueble.")
        return _guardar_fotos(db, property_id, tel10, [u for u in actuales if u != url])
