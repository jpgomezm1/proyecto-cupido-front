"""
Beneficios: qué tiene cada agente según su plan y sus complementos (migración 058).

Un solo lugar decide lo que el agente ve completo o "borroso" (ve que existe,
no el detalle) y cuántos usos le quedan de cada cosa. Diseño en
negocio/estrategia/complementos-y-divisa.md.

  Plan          encargos  vitrina    piezas marca  informes  links seguidos  compradores
  sin plan      0         borroso    0             0         0               borroso
  Visita        0         borroso    0             0         0               borroso
  Negocio       2         1 al mes   3/mes         1/mes     5/mes           detalle
  Cierre        5         semanal    10/mes        3/mes     20/mes          detalle

  Complemento "trabaja" (Findy trabaja por ti): +10 encargos, Vitrina semanal,
  compradores con detalle y prioridad en las presentaciones de Findy Conecta.
  Complemento "marca" (Tu marca): piezas con marca sin límite, 10 informes al
  mes, links seguidos sin límite. "ambos" = los dos.

Los usos del mes se cuentan en cada pieza (encargos_service, vitrina, marca…);
aquí solo están los derechos. ILIMITADO = un número grande, para comparar fácil.
"""

from datetime import timedelta
from typing import Any, Dict, List, Optional

from src.services.db import fetch_all, fetch_one, get_db, scalar

ILIMITADO = 10_000
DIAS_COMPLEMENTO = 30
_LOCK_COMPLEMENTO = 7105

# vitrina: 0 = borroso · 1 = una al mes · 4 = semanal
_PLAN: Dict[Optional[str], Dict[str, int]] = {
    None:     {"encargos": 0, "vitrina": 0, "marca_piezas": 0, "informes": 0, "links": 0, "compradores": 0},
    "basico": {"encargos": 0, "vitrina": 0, "marca_piezas": 0, "informes": 0, "links": 0, "compradores": 0},
    "medio":  {"encargos": 2, "vitrina": 1, "marca_piezas": 3, "informes": 1, "links": 5, "compradores": 1},
    "pro":    {"encargos": 5, "vitrina": 4, "marca_piezas": 10, "informes": 3, "links": 20, "compradores": 1},
}
_TRABAJA = {"encargos": 10, "vitrina": 4, "compradores": 1, "prioridad": 1}
_MARCA = {"marca_piezas": ILIMITADO, "informes": 10, "links": ILIMITADO}
COMPLEMENTOS = {"trabaja": [_TRABAJA], "marca": [_MARCA], "ambos": [_TRABAJA, _MARCA]}


class BeneficioError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def _plan_vigente(cur, user_id: int) -> Optional[Dict[str, Any]]:
    return fetch_one(cur, """
        SELECT s.plan_codigo, p.nombre, s.fin, s.gracia_hasta FROM suscripciones s JOIN planes p ON p.codigo = s.plan_codigo
        WHERE s.user_id = %s AND s.estado = 'activa' AND s.inicio <= NOW() AND NOW() < s.gracia_hasta
        ORDER BY s.inicio DESC LIMIT 1
    """, (user_id,))


def complementos_vigentes(cur, user_id: int) -> List[Dict[str, Any]]:
    return fetch_all(cur, """
        SELECT codigo, MAX(fin) AS fin FROM complementos_periodos
        WHERE user_id = %s AND inicio <= NOW() AND NOW() < fin
        GROUP BY codigo
    """, (user_id,))


def beneficios_en(cur, user_id: int) -> Dict[str, Any]:
    plan = _plan_vigente(cur, user_id)
    codigo = plan["plan_codigo"] if plan else None
    base = dict(_PLAN.get(codigo, _PLAN[None]))
    base["prioridad"] = 0
    comps = complementos_vigentes(cur, user_id)
    for c in comps:
        for extra in COMPLEMENTOS.get(c["codigo"], []):
            for k, v in extra.items():
                if k in ("encargos",):
                    base[k] = min(ILIMITADO, base.get(k, 0) + v)       # se suman
                else:
                    base[k] = max(base.get(k, 0), v)                    # el mejor
    return {
        **base,
        "plan": codigo,
        "plan_nombre": plan["nombre"] if plan else None,
        "complementos": [{"codigo": c["codigo"], "vence": c["fin"].isoformat()} for c in comps],
        "borroso": {"vitrina": base["vitrina"] == 0, "compradores": base["compradores"] == 0, "encargos": base["encargos"] == 0},
    }


def beneficios(user_id: int) -> Dict[str, Any]:
    with get_db() as db:
        return beneficios_en(db.cursor, user_id)


def activar_complemento_en(cur, user_id: int, codigo: str, referencia: Optional[str] = None,
                           admin: Optional[str] = None, precio_cop: Optional[int] = None) -> Dict[str, Any]:
    """Abre un periodo de 30 días del complemento (dentro de la transacción del caller).
    Si ya tiene uno vigente del mismo complemento, el nuevo empieza al terminar."""
    plan = fetch_one(cur, "SELECT * FROM planes WHERE codigo = %s AND tipo = 'complemento'", (codigo,))
    if not plan or codigo not in COMPLEMENTOS:
        raise BeneficioError("invalido", f"Complemento inválido: {codigo}")
    cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_LOCK_COMPLEMENTO, user_id))
    ahora = scalar(cur, "SELECT NOW()")
    fin_actual = scalar(cur, """
        SELECT MAX(fin) FROM complementos_periodos WHERE user_id = %s AND codigo = %s AND fin > NOW()
    """, (user_id, codigo))
    inicio = max(ahora, fin_actual) if fin_actual else ahora
    fin = inicio + timedelta(days=DIAS_COMPLEMENTO)
    pid = scalar(cur, """
        INSERT INTO complementos_periodos (user_id, codigo, inicio, fin, referencia, precio_cop, activado_por)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
    """, (user_id, codigo, inicio, fin, referencia, plan["precio_cop"] if precio_cop is None else precio_cop, admin))
    return {"ok": True, "periodo_id": pid, "codigo": codigo, "inicio": inicio.isoformat(), "fin": fin.isoformat()}
