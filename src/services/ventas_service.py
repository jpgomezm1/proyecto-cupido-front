"""
Ventas (lanzamiento, nov-2026; migración 060): la lista de agentes a los que
Fynder les escribe por su línea de WhatsApp de ventas.

Esa línea es SOLO outbound: presentar Fynder y conseguir una reunión de 15
minutos. No manda nada del producto. El mensaje lleva un gancho con los datos
del propio agente (sin contactos de nadie):

  inmueble  "tu apartamento en Laureles de $620 millones: 14 compradores buscan algo así"
  pedido    "buscas apartamento en Belén hasta $450 millones: entraron 6 que encajan"
  hernan    seguimiento después del audio de Hernán
  general   cuánto inventario y cuántos pedidos tiene Fynder

Primer contacto con una persona detrás, en tandas pequeñas, pidiendo permiso y
con salida en una palabra (Ley 1581 y política de WhatsApp): quien dice que no
queda 'excluido' y no vuelve a salir en la lista.

  sembrar()            agrega los celulares de inmuebles y pedidos y sincroniza estados
  calcular_ganchos()   arma el gancho de los pendientes (sin IA; lo corre el script)
  listar() / hoy()     el tablero del admin
"""

import hashlib
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from src.services.db import fetch_all, fetch_one, get_db, scalar
from src.services import suscripcion_service as suscripciones

ESTADOS = ("pendiente", "enviado", "respondio", "reunion", "demo_hecha", "fundador", "pago", "no_interesa", "excluido")
FUENTES = ("capturado", "hernan", "pauta", "referido", "otro")
CERRADOS = ("fundador", "pago", "no_interesa", "excluido")
UMBRAL = 70                 # mismo puntaje que las alertas y los encargos
MINIMO_GANCHO = 3           # con menos de 3 coincidencias el gancho no impresiona: mensaje general
DIAS_INMUEBLES_NUEVOS = 14
TOPE_DIARIO = 40            # mensajes en frío por día (cuidar la reputación del número)

_TEL = "RIGHT(REGEXP_REPLACE(COALESCE({c}, ''), '[^0-9]', '', 'g'), 10)"


class VentasError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


# ── sembrar ──────────────────────────────────────────────────────────────────

def sembrar() -> Dict[str, int]:
    """Agrega a la lista los celulares de quienes publicaron inmuebles o pedidos, refresca
    sus números, los liga a su cuenta y marca fundador/pago. No toca notas ni el estado
    comercial (salvo para marcar quién ya es fundador o paga)."""
    propios = list(suscripciones._telefonos_propios())
    with get_db() as db:
        cur = db.cursor
        cur.execute(f"""
            WITH tel AS (
                SELECT {_TEL.format(c="COALESCE(p.telefono, p.agente_captador_telefono)")} AS t,
                       'inm' AS o, p.activa, p.fecha_creacion::timestamptz AS f,
                       NULLIF(TRIM(p.inmobiliaria), '') AS inmob, NULL::text AS nombre
                FROM propiedades p
                UNION ALL
                SELECT {_TEL.format(c="agente_telefono")}, 'ped', NULL, fecha_captura::timestamptz,
                       NULL, NULLIF(TRIM(agente_nombre), '')
                FROM pedidos
            ), agg AS (
                SELECT t,
                       COUNT(*) FILTER (WHERE o = 'inm' AND activa) AS inm,
                       COUNT(*) FILTER (WHERE o = 'ped' AND f > NOW() - INTERVAL '90 days') AS ped,
                       MAX(f) AS ult, MAX(inmob) AS inmob, MAX(nombre) AS nombre
                FROM tel WHERE t ~ '^3[0-9]{{9}}$' AND NOT (t = ANY(%s))
                GROUP BY t
            )
            INSERT INTO ventas_agentes (telefono_10, nombre, inmobiliaria, inmuebles_activos, pedidos_90d, ultima_actividad)
            SELECT t, nombre, inmob, inm, ped, ult FROM agg
            ON CONFLICT (telefono_10) DO UPDATE SET
                nombre = COALESCE(ventas_agentes.nombre, EXCLUDED.nombre),
                inmobiliaria = COALESCE(ventas_agentes.inmobiliaria, EXCLUDED.inmobiliaria),
                inmuebles_activos = EXCLUDED.inmuebles_activos,
                pedidos_90d = EXCLUDED.pedidos_90d,
                ultima_actividad = GREATEST(ventas_agentes.ultima_actividad, EXCLUDED.ultima_actividad),
                actualizado_at = NOW()
        """, (propios,))
        nuevos_o_tocados = cur.rowcount
        # Cuenta en Fynder: liga la cuenta y prefiere su nombre real.
        cur.execute(f"""
            UPDATE ventas_agentes v SET user_id = u.id,
                   nombre = COALESCE(NULLIF(TRIM(u.nombre), ''), v.nombre), actualizado_at = NOW()
            FROM chat_users u
            WHERE {_TEL.format(c="u.telefono")} = v.telefono_10 AND v.user_id IS DISTINCT FROM u.id
        """)
        ligados = cur.rowcount
        cur.execute("""
            UPDATE ventas_agentes v SET estado = 'fundador', actualizado_at = NOW()
            WHERE v.user_id IS NOT NULL AND v.estado NOT IN ('fundador', 'excluido')
              AND EXISTS (SELECT 1 FROM suscripciones s WHERE s.user_id = v.user_id AND s.plan_codigo = 'fundador')
        """)
        cur.execute("""
            UPDATE ventas_agentes v SET estado = 'pago', actualizado_at = NOW()
            WHERE v.user_id IS NOT NULL AND v.estado NOT IN ('pago', 'fundador', 'excluido')
              AND EXISTS (SELECT 1 FROM suscripciones s WHERE s.user_id = v.user_id AND s.precio_cop > 0
                                                         AND s.plan_codigo <> 'fundador')
        """)
        # Equipo de Fynder y cuentas de prueba: fuera de la lista (no se les escribe).
        cur.execute(r"""
            UPDATE ventas_agentes v SET estado = 'excluido', notas = COALESCE(v.notas, 'Equipo o cuenta de prueba'),
                   actualizado_at = NOW()
            FROM chat_users u
            WHERE u.id = v.user_id AND v.estado = 'pendiente'
              AND (u.email ILIKE '%@stayirrelevant.com' OR u.origen = 'prueba_ui'
                   OR u.nombre ~* '^(test|prueba|agente de prueba)\M')
        """)
        _priorizar(cur)
        total = scalar(cur, "SELECT COUNT(*) FROM ventas_agentes")
        db.conn.commit()
    return {"total": total, "actualizados": nuevos_o_tocados, "ligados_a_cuenta": ligados}


def _priorizar(cur) -> None:
    """Primero la red de Hernán, después los activos de los últimos 60 días y los de más movimiento."""
    cur.execute("""
        UPDATE ventas_agentes SET prioridad =
              CASE WHEN fuente = 'hernan' THEN 1000 WHEN fuente IN ('referido', 'pauta') THEN 500 ELSE 0 END
            + CASE WHEN ultima_actividad > NOW() - INTERVAL '60 days' THEN 100 ELSE 0 END
            + CASE WHEN inmuebles_activos > 0 THEN 30 ELSE 0 END
            + CASE WHEN pedidos_90d > 0 THEN 20 ELSE 0 END
            + LEAST(inmuebles_activos + pedidos_90d, 20)
            + CASE WHEN (gancho->>'n')::int >= 3 THEN 15 ELSE 0 END
        WHERE estado = 'pendiente'
    """)


def agregar(filas: List[Dict[str, Any]], fuente: str, admin: Optional[str] = None) -> Dict[str, int]:
    """Agrega una lista a mano (p. ej. los 30 de Hernán). Si el agente ya estaba, le cambia la
    fuente (y con eso la prioridad) pero respeta su estado."""
    if fuente not in FUENTES:
        raise VentasError("invalido", "Fuente inválida.")
    from src.services.textutils import normalize_phone
    agregados = invalidos = 0
    with get_db() as db:
        cur = db.cursor
        for f in filas:
            tel = normalize_phone(str(f.get("telefono") or ""))
            if not tel or len(tel) != 10 or not tel.startswith("3"):
                invalidos += 1
                continue
            nombre = (f.get("nombre") or "").strip() or None
            cur.execute("""
                INSERT INTO ventas_agentes (telefono_10, nombre, fuente) VALUES (%s, %s, %s)
                ON CONFLICT (telefono_10) DO UPDATE SET fuente = EXCLUDED.fuente,
                    nombre = COALESCE(EXCLUDED.nombre, ventas_agentes.nombre), actualizado_at = NOW()
            """, (tel, nombre, fuente))
            _evento(cur, tel, "agregado", f"Fuente: {fuente}", admin)
            agregados += 1
        _priorizar(cur)
        db.conn.commit()
    sembrar()   # liga cuentas y refresca números de los recién agregados
    return {"agregados": agregados, "invalidos": invalidos}


# ── ganchos (sin IA) ─────────────────────────────────────────────────────────

def _millones(v) -> Optional[str]:
    if not v:
        return None
    m = float(v) / 1_000_000
    if m >= 1000:
        return f"${m / 1000:.1f} mil millones".replace(".0 ", " ").replace(".", ",")
    return f"${m:,.0f} millones".replace(",", ".")


def _contexto(cur) -> Dict[str, Any]:
    """Lo que se carga una sola vez por corrida: inventario reciente y pedidos vigentes."""
    from src.services import compradores_service as comp
    filas = fetch_all(cur, f"""
        SELECT p.id, p.titulo, p.tipo_propiedad, p.tipo_negocio, p.ciudad, p.zona, p.precio, p.habitaciones,
               p.banos, p.parqueaderos, p.area_construida, p.amenidades_internas, p.amenidades_externas,
               LEFT(p.descripcion, 600) AS descripcion,
               {_TEL.format(c="COALESCE(p.telefono, p.agente_captador_telefono)")} AS dueno_tel
        FROM propiedades p
        WHERE p.activa AND p.fecha_creacion > NOW() - INTERVAL '{DIAS_INMUEBLES_NUEVOS} days'
    """)
    # Los mismos pedidos que mira compradores_service.buscar_compradores.
    pedidos = fetch_all(cur, f"""
        SELECT id, criterios, {_TEL.format(c="agente_telefono")} AS tel FROM pedidos
        WHERE criterios IS NOT NULL AND estado <> 'retirado'
          AND fecha_captura > NOW() - make_interval(days => %s)
    """, (comp.DIAS_PEDIDOS,))
    pedidos = [p for p in pedidos if isinstance(p["criterios"], dict)]
    for p in pedidos:   # prefiltro barato, como en las alertas: familia de tipo
        p["familias"] = {comp._familia(x) for x in p["criterios"].get("tipos") or []} - {None}
    return {"inventario": [(f, comp._ficha_desde_propiedad(f)) for f in filas], "pedidos": pedidos}


def _resumen_pedido(crit: Dict[str, Any]) -> Optional[str]:
    tipos = [t for t in crit.get("tipos") or [] if t]
    zonas = [z for z in crit.get("zonas") or [] if z][:2]
    ciudades = [c for c in crit.get("ciudades") or [] if c][:1]
    if not tipos:
        return None
    s = tipos[0].lower()
    if crit.get("habitaciones_min"):
        s += f" de {crit['habitaciones_min']} habitaciones"
    lugar = " o ".join(zonas) or (ciudades[0] if ciudades else None)
    if lugar:
        s += f" en {lugar}"
    tope = _millones(crit.get("presupuesto_max"))
    if tope:
        s += f" hasta {tope}"
    return s


def _gancho_inmueble(cur, tel: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """El inmueble del agente (de sus 6 más recientes) con más compradores que encajan."""
    from src.services import compradores_service as comp
    props = fetch_all(cur, f"""
        SELECT p.*, b.nombre AS barrio
        FROM propiedades p
        LEFT JOIN propiedad_barrio pb ON pb.propiedad_id = p.id
        LEFT JOIN barrios b ON b.id = pb.barrio_id
        WHERE p.activa AND p.precio > 0
          AND {_TEL.format(c="COALESCE(p.telefono, p.agente_captador_telefono)")} = %s
        ORDER BY p.fecha_creacion DESC LIMIT 6
    """, (tel,))
    mejor = None
    for p in props:
        ficha = comp._ficha_desde_propiedad(p)
        precio = ficha.get("precio")
        familia = comp._familia(ficha.get("tipo"))
        n = 0
        for ped in ctx["pedidos"]:
            if ped["tel"] == tel or (familia and ped["familias"] and familia not in ped["familias"]):
                continue
            tope = ped["criterios"].get("presupuesto_max")
            if precio and tope and precio > float(tope) * 1.3:
                continue
            puntaje, _r, descartado = comp.puntuar(ficha, ped["criterios"])
            if not descartado and puntaje >= UMBRAL:
                n += 1
        if not mejor or n > mejor["n"]:
            mejor = {"tipo": "inmueble", "n": n, "propiedad_id": p["id"],
                     "tipo_inmueble": (p.get("tipo_propiedad") or "inmueble").lower(),
                     "zona": p.get("barrio") or p.get("zona") or p.get("ciudad"),
                     "precio": int(p["precio"]) if p.get("precio") else None}
    return mejor


def _gancho_pedido(cur, tel: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from src.services import compradores_service as comp
    ped = fetch_one(cur, f"""
        SELECT id, criterios FROM pedidos
        WHERE criterios IS NOT NULL AND fecha_captura > NOW() - INTERVAL '60 days'
          AND {_TEL.format(c="agente_telefono")} = %s
        ORDER BY fecha_captura DESC LIMIT 1
    """, (tel,))
    if not ped or not isinstance(ped["criterios"], dict):
        return None
    crit = ped["criterios"]
    busca = _resumen_pedido(crit)
    if not busca:
        return None
    n = 0
    for p, ficha in ctx["inventario"]:
        if p["dueno_tel"] == tel:
            continue
        puntaje, _r, descartado = comp.puntuar(ficha, crit)
        if not descartado and puntaje >= UMBRAL:
            n += 1
    return {"tipo": "pedido", "n": n, "pedido_id": ped["id"], "busca": busca, "dias": DIAS_INMUEBLES_NUEVOS}


def calcular_gancho(cur, tel: str, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    a = fetch_one(cur, "SELECT fuente, inmuebles_activos FROM ventas_agentes WHERE telefono_10 = %s", (tel,))
    if a and a["fuente"] == "hernan":
        g = {"tipo": "hernan"}
    else:
        ctx = ctx or _contexto(cur)
        inm = _gancho_inmueble(cur, tel, ctx)
        ped = _gancho_pedido(cur, tel, ctx)
        candidatos = [x for x in (inm, ped) if x and x["n"] >= MINIMO_GANCHO]
        if candidatos:
            g = max(candidatos, key=lambda x: x["n"])
        elif a and (a["inmuebles_activos"] or 0) >= 5:
            g = {"tipo": "inventario", "n": int(a["inmuebles_activos"])}
        else:
            g = {"tipo": "general"}
    cur.execute("UPDATE ventas_agentes SET gancho = %s::jsonb, gancho_at = NOW() WHERE telefono_10 = %s",
                (_json(g), tel))
    return g


def _json(d) -> str:
    import json
    return json.dumps(d, ensure_ascii=False)


def calcular_ganchos(limite: int = 1000, solo_sin_gancho: bool = True, log=print) -> Dict[str, int]:
    """Gancho de los agentes pendientes, de mayor a menor prioridad. Sin IA: puntaje del buscador."""
    with get_db() as db:
        cur = db.cursor
        tels = [r["telefono_10"] for r in fetch_all(cur, f"""
            SELECT telefono_10 FROM ventas_agentes
            WHERE estado = 'pendiente' {"AND gancho IS NULL" if solo_sin_gancho else ""}
            ORDER BY prioridad DESC, ultima_actividad DESC NULLS LAST LIMIT %s
        """, (limite,))]
        ctx = _contexto(cur)
        tipos: Dict[str, int] = {}
        for i, tel in enumerate(tels, 1):
            g = calcular_gancho(cur, tel, ctx)
            tipos[g["tipo"]] = tipos.get(g["tipo"], 0) + 1
            if i % 25 == 0:
                db.conn.commit()
                log(f"  {i}/{len(tels)} {tipos}")
        _priorizar(cur)
        db.conn.commit()
    return {"procesados": len(tels), **tipos}


# ── el mensaje ───────────────────────────────────────────────────────────────

_NO_NOMBRES = {"inmobiliaria", "inmuebles", "asesor", "asesora", "agente", "bienes", "raices", "raíces", "finca",
               "grupo", "dueño", "dueña", "dueno", "propietario", "propietaria", "test", "prueba", "admin",
               "fynder", "venta", "ventas", "arriendo", "arriendos", "inversiones", "constructora", "señor", "señora",
               "don", "doña", "sra", "ing", "arq", "dra", "comprador", "compradora", "cliente", "vendedor",
               "vendedora", "contacto", "info"}


def _primer_nombre(nombre: Optional[str]) -> Optional[str]:
    if not nombre:
        return None
    for tok in re.split(r"[\s,.|/-]+", nombre.strip()):
        if tok.isalpha() and len(tok) >= 3 and tok.lower() not in _NO_NOMBRES:
            return tok.capitalize()
    return None


def _variante(tel: str, n: int) -> int:
    return int(hashlib.md5(tel.encode()).hexdigest(), 16) % n


SALIDA = "Si prefieres que no te escriba, me dices y listo."


def mensaje(a: Dict[str, Any], remitente: str, cifras: Dict[str, int]) -> str:
    """Primer mensaje para la línea de ventas. Objetivo: una llamada de 15 minutos."""
    nombre = _primer_nombre(a.get("nombre"))
    hola = f"Hola {nombre}" if nombre else "Hola"
    yo = f"soy {remitente}, de Fynder" if remitente else "te escribo de Fynder"
    # La red de Hernán siempre recibe el seguimiento de su audio, aunque antes tuviera otro gancho.
    g = {"tipo": "hernan"} if a.get("fuente") == "hernan" else (a.get("gancho") or {"tipo": "general"})
    tel = a["telefono_10"]

    if g["tipo"] == "hernan":
        return (f"{hola}, {yo}. Hernán te contó de lo que estamos haciendo con los inmuebles y los pedidos "
                f"que circulan entre agentes de Medellín. ¿Te muestro en una llamada de 15 minutos cómo te sirve? "
                f"Dime qué día y hora te quedan bien.")

    if g["tipo"] == "inmueble":
        que = f"tu {g['tipo_inmueble']}" + (f" en {g['zona']}" if g.get("zona") else "")
        precio = _millones(g.get("precio"))
        n = g["n"]
        v = [
            f"{hola}, {yo}. Vi {que}{f' de {precio}' if precio else ''} que circula en los grupos de agentes. "
            f"Cruzamos los pedidos de compradores que se mueven en Medellín y hay {n} que buscan algo así. "
            f"¿Te muestro quiénes son en una llamada de 15 minutos esta semana? {SALIDA}",
            f"{hola}, ¿cómo vas? Te escribe {remitente or 'el equipo'} de Fynder. Organizamos todo lo que se publica "
            f"en los grupos de agentes de Medellín, y {que}{f' ({precio})' if precio else ''} encaja con {n} pedidos "
            f"de compradores activos. ¿Tienes 15 minutos para mostrarte cómo llegarles? {SALIDA}",
            f"{hola}, {yo}. Hay {n} compradores buscando algo como {que}{f' de {precio}' if precio else ''}, "
            f"según los pedidos que circulan entre agentes. Me gustaría mostrarte en una llamada corta cómo Fynder "
            f"te los cruza todos los días. "
            f"¿Qué día te queda bien? {SALIDA}",
        ]
        return v[_variante(tel, len(v))]

    if g["tipo"] == "pedido":
        n = g["n"]
        v = [
            f"{hola}, {yo}. Vi que estás buscando {g['busca']} para un cliente. En las últimas dos semanas "
            f"entraron {n} inmuebles que encajan con lo que pide. ¿Te los muestro en una llamada de 15 minutos? {SALIDA}",
            f"{hola}, ¿cómo vas? Te escribe {remitente or 'el equipo'} de Fynder. Tu pedido de {g['busca']} encaja con "
            f"{n} inmuebles que entraron a la red estos días. ¿Te muestro cuáles son y cómo te los avisamos solos? "
            f"Son 15 minutos. {SALIDA}",
        ]
        return v[_variante(tel, len(v))]

    inm, ped = _mas_de(cifras.get("inmuebles", 0)), _mas_de(cifras.get("pedidos", 0))
    if g["tipo"] == "inventario":
        return (f"{hola}, {yo}. Vi que tienes {g['n']} inmuebles publicados en los grupos de agentes. "
                f"En Fynder organizamos todo lo que se publica ahí (más de {inm} inmuebles y {ped} pedidos de "
                f"compradores) y lo cruzamos todos los días, para que encuentres comprador más rápido. "
                f"¿Te muestro cómo funciona con tus inmuebles en 15 minutos? {SALIDA}")
    return (f"{hola}, {yo}. Organizamos todo lo que se publica en los grupos de agentes de Medellín: más de "
            f"{inm} inmuebles en venta y {ped} pedidos de compradores, cruzados todos los días. "
            f"Te vi activo en los grupos y creo que te puede servir. ¿Te lo muestro en 15 minutos? {SALIDA}")


def _mas_de(n: int) -> str:
    """6.958 → "6.900"; 4.015 → "4.000": cifra redonda para "más de"."""
    paso = 100 if n >= 1000 else 10
    return f"{(int(n) // paso) * paso:,}".replace(",", ".")


def link_whatsapp(tel: str, texto: str) -> str:
    return f"https://wa.me/57{tel}?text={quote(texto)}"


def _cifras(cur) -> Dict[str, int]:
    return {
        "inmuebles": scalar(cur, "SELECT COUNT(*) FROM propiedades WHERE activa") or 0,
        "pedidos": scalar(cur, "SELECT COUNT(*) FROM pedidos") or 0,
    }


# ── tablero ──────────────────────────────────────────────────────────────────

def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _salida(a: Dict[str, Any], remitente: str, cifras: Dict[str, int]) -> Dict[str, Any]:
    out = {k: _iso(v) for k, v in a.items()}
    if a["estado"] in ("pendiente", "enviado"):
        texto = mensaje(a, remitente, cifras)
        out["mensaje"] = texto
        out["whatsapp"] = link_whatsapp(a["telefono_10"], texto)
    else:
        out["whatsapp"] = f"https://wa.me/57{a['telefono_10']}"
    return out


def enviados_hoy(cur) -> int:
    return scalar(cur, """
        SELECT COUNT(*) FROM ventas_eventos
        WHERE tipo = 'mensaje_enviado'
          AND creado_at >= date_trunc('day', NOW() AT TIME ZONE 'America/Bogota') AT TIME ZONE 'America/Bogota'
    """) or 0


def listar(estado: Optional[str] = None, fuente: Optional[str] = None, q: Optional[str] = None,
           limite: int = 50, offset: int = 0, remitente: str = "") -> Dict[str, Any]:
    cond, params = ["TRUE"], []
    if estado:
        cond.append("v.estado = %s"); params.append(estado)
    else:
        cond.append("v.estado <> 'excluido'")
    if fuente:
        cond.append("v.fuente = %s"); params.append(fuente)
    if q:
        cond.append("(v.nombre ILIKE %s OR v.telefono_10 LIKE %s OR v.inmobiliaria ILIKE %s)")
        params += [f"%{q}%", f"%{q.strip()}%", f"%{q}%"]
    from src.services import fundador_service
    with get_db() as db:
        cur = db.cursor
        orden = ("v.prioridad DESC, v.ultima_actividad DESC NULLS LAST" if estado == "pendiente"
                 else "COALESCE(v.ultimo_contacto_at, v.actualizado_at) DESC, v.prioridad DESC")
        filas = fetch_all(cur, f"""
            SELECT v.*, u.telefono_verificado, u.acceso_entregado, u.email AS cuenta_email,
                   (SELECT s.plan_codigo FROM suscripciones s WHERE s.user_id = v.user_id AND s.estado = 'activa'
                      AND s.inicio <= NOW() AND NOW() < s.gracia_hasta ORDER BY s.inicio DESC LIMIT 1) AS plan
            FROM ventas_agentes v LEFT JOIN chat_users u ON u.id = v.user_id
            WHERE {' AND '.join(cond)}
            ORDER BY {orden}
            LIMIT %s OFFSET %s
        """, (*params, limite, offset))
        total = scalar(cur, f"SELECT COUNT(*) FROM ventas_agentes v WHERE {' AND '.join(cond)}", params)
        por_estado = {r["estado"]: r["n"] for r in fetch_all(cur, "SELECT estado, COUNT(*) AS n FROM ventas_agentes GROUP BY 1")}
        cifras = _cifras(cur)
        hoy = enviados_hoy(cur)
    return {
        "agentes": [_salida(a, remitente, cifras) for a in filas],
        "total": total,
        "por_estado": por_estado,
        "enviados_hoy": hoy,
        "tope_diario": TOPE_DIARIO,
        "fundadores": fundador_service.cupos(),
    }


def _evento(cur, tel: str, tipo: str, detalle: Optional[str], admin: Optional[str]) -> None:
    cur.execute("INSERT INTO ventas_eventos (telefono_10, tipo, detalle, creado_por) VALUES (%s, %s, %s, %s)",
                (tel, tipo, detalle, admin))


def actualizar(tel: str, cambios: Dict[str, Any], admin: Optional[str] = None) -> Dict[str, Any]:
    """Cambia estado, notas o la fecha de la reunión, y deja el historial."""
    with get_db() as db:
        cur = db.cursor
        a = fetch_one(cur, "SELECT * FROM ventas_agentes WHERE telefono_10 = %s FOR UPDATE", (tel,))
        if not a:
            raise VentasError("no_encontrado", "Ese agente no está en la lista.")
        sets, params = [], []
        if "estado" in cambios:
            est = cambios["estado"]
            if est not in ESTADOS:
                raise VentasError("invalido", "Estado inválido.")
            if est != a["estado"]:
                sets.append("estado = %s"); params.append(est)
                sets.append("ultimo_contacto_at = NOW()")
                _evento(cur, tel, "estado", f"{a['estado']} → {est}", admin)
        if "notas" in cambios:
            sets.append("notas = %s"); params.append((cambios["notas"] or "").strip() or None)
        if "reunion_at" in cambios:
            sets.append("reunion_at = %s"); params.append(cambios["reunion_at"] or None)
            if cambios["reunion_at"]:
                _evento(cur, tel, "reunion", str(cambios["reunion_at"]), admin)
                if "estado" not in cambios and a["estado"] in ("pendiente", "enviado", "respondio"):
                    sets.append("estado = 'reunion'")
        if sets:
            cur.execute(f"UPDATE ventas_agentes SET {', '.join(sets)}, actualizado_at = NOW() WHERE telefono_10 = %s",
                        (*params, tel))
        db.conn.commit()
    return {"ok": True}


def marcar_enviado(tel: str, texto: Optional[str] = None, admin: Optional[str] = None) -> Dict[str, Any]:
    with get_db() as db:
        cur = db.cursor
        a = fetch_one(cur, "SELECT estado FROM ventas_agentes WHERE telefono_10 = %s FOR UPDATE", (tel,))
        if not a:
            raise VentasError("no_encontrado", "Ese agente no está en la lista.")
        if a["estado"] == "excluido":
            raise VentasError("excluido", "Este agente pidió no recibir mensajes.")
        cur.execute("""
            UPDATE ventas_agentes SET estado = CASE WHEN estado = 'pendiente' THEN 'enviado' ELSE estado END,
                   enviado_at = COALESCE(enviado_at, NOW()), ultimo_contacto_at = NOW(), actualizado_at = NOW()
            WHERE telefono_10 = %s
        """, (tel,))
        _evento(cur, tel, "mensaje_enviado", (texto or "")[:1000] or None, admin)
        hoy = enviados_hoy(cur)
        db.conn.commit()
    return {"ok": True, "enviados_hoy": hoy, "tope_diario": TOPE_DIARIO}


def recalcular(tel: str) -> Dict[str, Any]:
    with get_db() as db:
        g = calcular_gancho(db.cursor, tel)
        db.conn.commit()
    return g


def historial(tel: str) -> List[Dict[str, Any]]:
    with get_db() as db:
        filas = fetch_all(db.cursor, """
            SELECT tipo, detalle, creado_por, creado_at FROM ventas_eventos
            WHERE telefono_10 = %s ORDER BY creado_at DESC LIMIT 50
        """, (tel,))
    return [{k: _iso(v) for k, v in f.items()} for f in filas]


def hoy() -> Dict[str, List[Dict[str, Any]]]:
    """A quién llamar hoy: señales del producto sobre agentes que ya están en conversación."""
    with get_db() as db:
        cur = db.cursor
        base = """
            SELECT v.telefono_10, v.nombre, v.estado, v.user_id, v.reunion_at {extra}
            FROM ventas_agentes v {join}
            WHERE v.estado NOT IN ('excluido', 'no_interesa') {cond}
            ORDER BY {orden} LIMIT 30
        """
        reuniones = fetch_all(cur, base.format(
            extra="", join="", orden="v.reunion_at",
            cond="AND v.reunion_at >= date_trunc('day', NOW() AT TIME ZONE 'America/Bogota') AT TIME ZONE 'America/Bogota' "
                 "AND v.reunion_at < (date_trunc('day', NOW() AT TIME ZONE 'America/Bogota') + INTERVAL '2 days') AT TIME ZONE 'America/Bogota'"))
        entraron = fetch_all(cur, base.format(
            extra=", u.ultimo_login AS cuando", join="JOIN chat_users u ON u.id = v.user_id", orden="u.ultimo_login DESC",
            cond="AND v.estado IN ('enviado', 'respondio', 'reunion', 'demo_hecha') AND u.ultimo_login > NOW() - INTERVAL '3 days'"))
        abrieron = fetch_all(cur, base.format(
            extra=", MAX(d.created_at) AS cuando, COUNT(d.id) AS contactos",
            join="JOIN desbloqueos d ON d.user_id = v.user_id AND d.estado = 'vigente' AND d.created_at > NOW() - INTERVAL '3 days'",
            orden="MAX(d.created_at) DESC",
            cond="AND v.estado NOT IN ('pago') GROUP BY v.telefono_10, v.nombre, v.estado, v.user_id, v.reunion_at"))
        # Mismas reglas que suscripcion_service.ventana_lanzamiento, en una sola consulta.
        por_vencer = fetch_all(cur, f"""
            SELECT v.telefono_10, v.nombre, v.estado, v.user_id,
                   GREATEST(u.fecha_creacion, u.telefono_verificado_at, u.acceso_entregado_at)
                     + INTERVAL '{suscripciones.DIAS_LANZAMIENTO} days' AS cuando
            FROM ventas_agentes v JOIN chat_users u ON u.id = v.user_id
            WHERE v.estado NOT IN ('excluido', 'no_interesa', 'pago', 'fundador')
              AND u.telefono_verificado AND (u.origen IS DISTINCT FROM 'provision' OR u.acceso_entregado)
              AND NOT EXISTS (SELECT 1 FROM suscripciones s WHERE s.user_id = u.id)
              AND GREATEST(u.fecha_creacion, u.telefono_verificado_at, u.acceso_entregado_at)
                    + INTERVAL '{suscripciones.DIAS_LANZAMIENTO} days' BETWEEN NOW() AND NOW() + INTERVAL '2 days'
            ORDER BY cuando LIMIT 30
        """) if suscripciones.lanzamiento_activo() else []
        sin_llaves = []
        for c in fetch_all(cur, """
            SELECT DISTINCT v.telefono_10, v.nombre, v.estado, v.user_id FROM ventas_agentes v
            JOIN desbloqueos d ON d.user_id = v.user_id
            WHERE v.estado NOT IN ('excluido', 'no_interesa', 'pago', 'fundador')
        """):
            if suscripciones._saldos(cur, c["user_id"])["disponibles"] == 0:
                sin_llaves.append(c)
    lim = lambda xs: [{k: _iso(v) for k, v in x.items()} for x in xs]
    return {
        "reuniones": lim(reuniones),
        "abrieron_contactos": lim(abrieron),
        "sin_llaves": lim(sin_llaves[:30]),
        "bono_por_vencer": lim(por_vencer),
        "entraron": lim(entraron),
    }


def activar_fundador(tel: str, admin: Optional[str] = None, referencia: Optional[str] = None,
                     forzar: bool = False) -> Dict[str, Any]:
    from src.services import fundador_service
    with get_db() as db:
        a = fetch_one(db.cursor, "SELECT user_id FROM ventas_agentes WHERE telefono_10 = %s", (tel,))
    if not a or not a["user_id"]:
        raise VentasError("sin_cuenta", "Este agente todavía no tiene cuenta en Fynder: créala primero en Agentes.")
    res = fundador_service.activar(a["user_id"], admin=admin, referencia_pago=referencia, forzar=forzar)
    with get_db() as db:
        cur = db.cursor
        cur.execute("UPDATE ventas_agentes SET estado = 'fundador', ultimo_contacto_at = NOW(), actualizado_at = NOW() "
                    "WHERE telefono_10 = %s", (tel,))
        _evento(cur, tel, "fundador", "Activado" if res.get("primera_vez") else "Renovado a precio fijo", admin)
        db.conn.commit()
    return res
