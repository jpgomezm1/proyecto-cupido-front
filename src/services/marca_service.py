"""
"Tu marca" (migración 058, parte 6): tres cosas que hacen ver al agente como una
inmobiliaria. Los cupos salen de beneficios_service (Negocio, Cierre, "Tu marca").

1. MARCA PROPIA: al generar una pieza para el cliente (ficha, comparativa,
   reporte de zona, informe), si al agente le queda cupo del mes, el link se
   firma con "m" y la página se muestra solo con su marca, sin Fynder.
   `firmar(...)` consume el cupo (marca_usos).
2. QUIÉN VIO TU LINK: cada vez que un cliente abre una pieza firmada por el
   agente, `registrar_vista` suma la vista (piezas_vistas). Todos ven si se abrió;
   con cupo de links (o ilimitado con "Tu marca") ve cuántas veces y cuándo, y le
   llega un aviso por correo al instante (como mucho uno cada 6 h por pieza).
3. INFORME DE CAPTACIÓN: `generar_informe` arma el informe para el propietario
   (precio sugerido, rango, comparables y oferta/demanda de la zona) con los datos
   de ese momento, y lo devuelve como link firmado (/informe/<token>), listo para
   imprimir o guardar como PDF. Cupo mensual + informes_extra (Fyns).
"""

import json
from typing import Any, Dict, List, Optional

from src.services import beneficios_service
from src.services.db import fetch_all, fetch_one, get_db, scalar

TZ = "America/Bogota"
HORAS_ENTRE_AVISOS = 6
_MES = f"date_trunc('month', NOW() AT TIME ZONE '{TZ}') AT TIME ZONE '{TZ}'"
_LOCK_INFORMES = 7107


class MarcaError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


# ── 1. marca propia ─────────────────────────────────────────────────────────

def usos_mes_en(cur, user_id: int) -> Dict[str, int]:
    marca = scalar(cur, f"SELECT COUNT(*) FROM marca_usos WHERE user_id = %s AND created_at >= {_MES}", (user_id,)) or 0
    informes = scalar(cur, f"SELECT COUNT(*) FROM informes WHERE user_id = %s AND fuente = 'plan' AND created_at >= {_MES}",
                      (user_id,)) or 0
    links = scalar(cur, f"""SELECT COUNT(*) FROM piezas_vistas WHERE user_id = %s AND con_detalle
                            AND primera_vista >= {_MES}""", (user_id,)) or 0
    return {"marca_piezas": int(marca), "informes": int(informes), "links": int(links)}


def firmar(user_id: Optional[int], tipo: str, ref: str) -> bool:
    """¿Esta pieza sale con la marca del agente? Consume una del cupo del mes. Nunca lanza."""
    if not user_id:
        return False
    try:
        with get_db() as db:
            cur = db.cursor
            ben = beneficios_service.beneficios_en(cur, int(user_id))
            if ben["marca_piezas"] <= 0 or usos_mes_en(cur, int(user_id))["marca_piezas"] >= ben["marca_piezas"]:
                return False
            cur.execute("INSERT INTO marca_usos (user_id, tipo, ref) VALUES (%s, %s, %s)", (int(user_id), tipo, ref[:160]))
            db.conn.commit()
            return True
    except Exception as e:  # noqa: BLE001 — sin marca, la pieza sale igual con la de Fynder
        print(f"[MARCA] No se pudo firmar la pieza: {e}")
        return False


# ── 2. quién vio tu link ────────────────────────────────────────────────────

def registrar_vista(agente_id: Optional[int], tipo: str, clave: str, titulo: Optional[str] = None) -> None:
    """Una apertura de una pieza del agente (best-effort; nunca lanza)."""
    if not agente_id:
        return
    try:
        with get_db() as db:
            cur = db.cursor
            uid = int(agente_id)
            fila = fetch_one(cur, """
                INSERT INTO piezas_vistas (user_id, clave, tipo, titulo, vistas, primera_vista, ultima_vista)
                VALUES (%s, %s, %s, %s, 1, NOW(), NOW())
                ON CONFLICT (user_id, clave) DO UPDATE SET vistas = piezas_vistas.vistas + 1, ultima_vista = NOW(),
                    titulo = COALESCE(EXCLUDED.titulo, piezas_vistas.titulo)
                RETURNING id, con_detalle, avisado_at, vistas, titulo
            """, (uid, clave[:160], tipo, (titulo or "")[:200] or None))
            ben = beneficios_service.beneficios_en(cur, uid)
            con_detalle = fila["con_detalle"]
            if not con_detalle and ben["links"] > 0 and usos_mes_en(cur, uid)["links"] < ben["links"]:
                cur.execute("UPDATE piezas_vistas SET con_detalle = TRUE WHERE id = %s", (fila["id"],))
                con_detalle = True
            avisar = con_detalle and (fila["avisado_at"] is None or scalar(
                cur, f"SELECT %s < NOW() - INTERVAL '{HORAS_ENTRE_AVISOS} hours'", (fila["avisado_at"],)))
            if avisar:
                cur.execute("UPDATE piezas_vistas SET avisado_at = NOW() WHERE id = %s", (fila["id"],))
            db.conn.commit()
        if avisar:
            _avisar(uid, fila["titulo"] or "lo que le mandaste", fila["vistas"])
    except Exception as e:  # noqa: BLE001
        print(f"[MARCA] No se pudo registrar la vista: {e}")


def _avisar(user_id: int, titulo: str, vistas: int) -> None:
    from src.services import correo_service
    with get_db() as db:
        u = fetch_one(db.cursor, """SELECT nombre, COALESCE(NULLIF(TRIM(correo_personal), ''), email) AS destino
                                    FROM chat_users WHERE id = %s""", (user_id,))
    if u:
        correo_service.pieza_vista(u["nombre"], u["destino"], titulo, vistas)


def vistas(user_id: int, limite: int = 30) -> Dict[str, Any]:
    """Las piezas que compartió y si su cliente las abrió (con detalle si tiene el beneficio)."""
    with get_db() as db:
        cur = db.cursor
        filas = fetch_all(cur, """
            SELECT clave, tipo, titulo, vistas, primera_vista, ultima_vista, con_detalle FROM piezas_vistas
            WHERE user_id = %s ORDER BY ultima_vista DESC NULLS LAST LIMIT %s
        """, (user_id, limite))
        ben = beneficios_service.beneficios_en(cur, user_id)
        usos = usos_mes_en(cur, user_id)
    return {
        "cupo": {"total": ben["links"], "usados": usos["links"]},
        "piezas": [{
            "clave": f["clave"], "tipo": f["tipo"], "titulo": f["titulo"], "abierta": f["vistas"] > 0,
            "primera_vista": f["primera_vista"].isoformat() if f["primera_vista"] else None,
            # El detalle (cuántas veces y la última) solo con el beneficio.
            "vistas": f["vistas"] if f["con_detalle"] else None,
            "ultima_vista": f["ultima_vista"].isoformat() if f["con_detalle"] and f["ultima_vista"] else None,
            "con_detalle": f["con_detalle"],
        } for f in filas],
    }


# ── 3. informe de captación ─────────────────────────────────────────────────

def cupo_informes_en(cur, user_id: int) -> Dict[str, int]:
    ben = beneficios_service.beneficios_en(cur, user_id)
    usados = usos_mes_en(cur, user_id)["informes"]
    extra = int(scalar(cur, "SELECT COALESCE(SUM(cantidad), 0) FROM informes_extra WHERE user_id = %s", (user_id,)) or 0)
    gastados_extra = int(scalar(cur, "SELECT COUNT(*) FROM informes WHERE user_id = %s AND fuente = 'extra'", (user_id,)) or 0)
    del_plan = max(0, ben["informes"] - usados)
    return {"total": ben["informes"], "usados": usados, "del_plan": del_plan,
            "extra": max(0, extra - gastados_extra), "restantes": del_plan + max(0, extra - gastados_extra)}


def abonar_informes_en(cur, user_id: int, cantidad: int, referencia: str) -> None:
    cur.execute("INSERT INTO informes_extra (user_id, cantidad, referencia) VALUES (%s, %s, %s)",
                (user_id, cantidad, referencia))


def _datos_informe(cur, base: Dict[str, Any]) -> Dict[str, Any]:
    from src.services import market_service, property_service as ps
    est = ps.estimate_price(cur, ciudad=base.get("ciudad"), zona=base.get("zona"), tipo_propiedad=base.get("tipo"),
                            area_construida=base.get("area"), habitaciones=base.get("habitaciones"))
    comparables: List[Dict[str, Any]] = []
    if base.get("propiedad_id"):
        try:
            comp = ps.find_comparables(cur, base["propiedad_id"], limit=6)
            comparables = [{k: c.get(k) for k in ("titulo", "precio", "area_construida", "habitaciones", "zona", "precio_m2")}
                           for c in (comp.get("comparables") or [])][:6]
        except Exception as e:  # noqa: BLE001
            print(f"[INFORME] Sin comparables: {e}")
    try:
        balance = market_service.supply_demand_balance(cur, ciudad=base.get("ciudad"), zona=base.get("zona"),
                                                       tipo_propiedad=base.get("tipo"))
    except Exception as e:  # noqa: BLE001
        print(f"[INFORME] Sin balance de zona: {e}")
        balance = None
    return {"inmueble": base, "estimacion": est, "comparables": comparables, "zona": balance}


def generar_informe(user_id: int, propiedad_id: Optional[int] = None, datos: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Informe de captación para el propietario. `propiedad_id` (un inmueble de la red) o `datos`
    {ciudad, zona, tipo, area, habitaciones, direccion?} para uno que aún no está publicado."""
    from src.services import share_service
    from src.services.property_service import get_property
    with get_db() as db:
        cur = db.cursor
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK_INFORMES, user_id))
        cupo = cupo_informes_en(cur, user_id)
        if cupo["restantes"] <= 0:
            db.conn.rollback()
            if cupo["total"] == 0:
                raise MarcaError("sin_beneficio", "Los informes de captación vienen con Negocio (1 al mes), Cierre (3) y "
                                                  "Tu marca (10). También puedes canjear 60 Fyns por uno.")
            raise MarcaError("sin_cupo", f"Ya usaste tus {cupo['total']} informes de este mes. Suma más con Tu marca o con Fyns.")
        if propiedad_id:
            p = get_property(cur, propiedad_id)
            if not p:
                raise MarcaError("no_encontrada", "No encontré ese inmueble.")
            base = {"propiedad_id": p["id"], "titulo": p.get("titulo"), "ciudad": p.get("ciudad"), "zona": p.get("zona"),
                    "tipo": p.get("tipo_propiedad"), "area": float(p["area_construida"]) if p.get("area_construida") else None,
                    "habitaciones": p.get("habitaciones"), "precio_publicado": p.get("precio")}
        else:
            d = datos or {}
            if not (d.get("zona") or d.get("ciudad")) or not d.get("area") or not d.get("tipo"):
                raise MarcaError("datos", "Para el informe necesito la zona, el tipo de inmueble y el área.")
            base = {"propiedad_id": None, "titulo": d.get("titulo") or f"{d['tipo']} en {d.get('zona') or d.get('ciudad')}",
                    "ciudad": d.get("ciudad"), "zona": d.get("zona"), "tipo": d["tipo"], "area": float(d["area"]),
                    "habitaciones": d.get("habitaciones"), "direccion": d.get("direccion")}
        contenido = _datos_informe(cur, base)
        fuente = "plan" if cupo["del_plan"] > 0 else "extra"
        iid = scalar(cur, "INSERT INTO informes (user_id, propiedad_id, datos, fuente) VALUES (%s, %s, %s, %s) RETURNING id",
                     (user_id, base.get("propiedad_id"), json.dumps(contenido, default=str), fuente))
        db.conn.commit()
    marca = firmar(user_id, "informe", f"informe:{iid}")
    token = share_service.make_token("inf", [iid], user_id, marca=marca)
    return {"ok": True, "informe_id": iid, "link": f"{share_service._frontend_base()}/informe/{token}",
            "marca_propia": marca, "estimacion": contenido["estimacion"]}


def datos_informe_publico(informe_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as db:
        f = fetch_one(db.cursor, "SELECT datos, created_at FROM informes WHERE id = %s", (informe_id,))
    if not f:
        return None
    return {**f["datos"], "fecha": f["created_at"].isoformat()}
