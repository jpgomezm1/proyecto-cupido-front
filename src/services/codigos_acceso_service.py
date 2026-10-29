"""
Códigos de acceso de la beta (migración 066).

Un código activa el plan Fundador (fundador_service.activar). Se puede poner al registrarse
(registro_service.registrar valida el código ANTES de crear la cuenta, para que un código mal
escrito no deje una cuenta a medias) o después, en Mi cuenta › Plan (POST /api/chat/codigo-acceso).

  validar(codigo)          el código existe, está activo, no venció y le quedan usos
  canjear(user_id, codigo) reserva un uso (bajo lock de la fila) y activa el beneficio;
                           si la activación falla, devuelve el uso
"""

import re
from typing import Any, Dict, Optional

from src.services import fundador_service as fundador
from src.services.db import fetch_one, get_db


class CodigoError(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo, self.mensaje = codigo, mensaje


def normalizar(codigo: Optional[str]) -> str:
    """«  beta-fynder » → «BETA-FYNDER»: sin espacios y en mayúsculas."""
    return re.sub(r"\s+", "", codigo or "").upper()[:40]


def _vigente(fila: Optional[Dict[str, Any]]) -> None:
    if not fila or not fila["activo"]:
        raise CodigoError("invalido", "Ese código no existe. Revísalo o escríbenos.")
    if fila["vence_at"] and fila["vencido"]:
        raise CodigoError("vencido", "Ese código ya venció.")
    if fila["usos"] >= fila["usos_max"]:
        raise CodigoError("agotado", "Ese código ya se usó todas las veces que permitía.")


_FILA = "SELECT *, (vence_at IS NOT NULL AND vence_at < NOW()) AS vencido FROM codigos_acceso WHERE codigo = %s"


def validar(codigo: str) -> Dict[str, Any]:
    c = normalizar(codigo)
    with get_db() as db:
        fila = fetch_one(db.cursor, _FILA, (c,))
    _vigente(fila)
    return {"codigo": c, "beneficio": fila["beneficio"]}


def canjear(user_id: int, codigo: str) -> Dict[str, Any]:
    c = normalizar(codigo)
    with get_db() as db:
        cur = db.cursor
        fila = fetch_one(cur, _FILA + " FOR UPDATE", (c,))
        _vigente(fila)
        if fetch_one(cur, "SELECT 1 FROM codigos_acceso_canjes WHERE codigo = %s AND user_id = %s", (c, user_id)):
            raise CodigoError("ya_usado", "Ya usaste este código.")
        # Ya es fundador: activar() le crearía una renovación PAGA. El código no le suma nada.
        if fundador.estado_de(cur, user_id) is not None:
            raise CodigoError("ya_fundador", "Tu cuenta ya tiene el plan Fundador.")
        cur.execute("INSERT INTO codigos_acceso_canjes (codigo, user_id) VALUES (%s, %s)", (c, user_id))
        cur.execute("UPDATE codigos_acceso SET usos = usos + 1 WHERE codigo = %s", (c,))
        db.conn.commit()

    try:
        res = fundador.activar(user_id, admin=f"codigo:{c}")
    except fundador.FundadorError as e:
        with get_db() as db:     # se devuelve el uso: el código sigue sirviéndole a otro
            db.cursor.execute("DELETE FROM codigos_acceso_canjes WHERE codigo = %s AND user_id = %s", (c, user_id))
            db.cursor.execute("UPDATE codigos_acceso SET usos = GREATEST(usos - 1, 0) WHERE codigo = %s", (c,))
            db.conn.commit()
        raise CodigoError(e.codigo, e.mensaje)
    return {"ok": True, "codigo": c, "beneficio": "fundador", "hasta": res.get("hasta")}


def crear(codigo: str, usos_max: int = 1, vence_at: Optional[str] = None,
          notas: Optional[str] = None, creado_por: Optional[str] = None) -> Dict[str, Any]:
    c = normalizar(codigo)
    if not re.fullmatch(r"[A-Z0-9_-]{4,40}", c):
        raise CodigoError("invalido", "El código lleva de 4 a 40 letras, números, «-» o «_».")
    with get_db() as db:
        db.cursor.execute("""
            INSERT INTO codigos_acceso (codigo, usos_max, vence_at, notas, creado_por)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (codigo) DO NOTHING RETURNING codigo
        """, (c, usos_max, vence_at, notas, creado_por))
        if not db.cursor.fetchone():
            raise CodigoError("duplicado", f"El código {c} ya existe.")
        db.conn.commit()
    return {"codigo": c, "usos_max": usos_max, "vence_at": vence_at}
