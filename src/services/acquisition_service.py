"""
C1 — Provisionar cuentas de agentes (adquisición).

Dado el teléfono de un captador, arma/entrega su cuenta del portal (chat_users)
ya asociada a su inventario (las propiedades que él captó son visibles con
`list_my_properties`, scoped por los últimos 10 dígitos del teléfono). Devuelve
el acceso (email + clave temporal + link de login) que Matías entrega en el cold
WhatsApp. Reutiliza el hashing bcrypt de pgcrypto, igual que chat_users.
"""

import os
from typing import Any, Dict, List, Optional

from src.services.db import get_db, fetch_one, fetch_all
from src.services.textutils import normalize_phone, FRONTEND_URL

# Clave compartida de las cuentas pre-cargadas (pilotaje: fácil de entregar por
# WhatsApp). Sobreescribible con DEFAULT_AGENT_PASSWORD en el entorno.
DEFAULT_PASSWORD = os.getenv("DEFAULT_AGENT_PASSWORD", "Fynder2026*")


def provisionar_captador(telefono: str, email: Optional[str] = None,
                         nombre: Optional[str] = None,
                         reset_password: bool = False) -> Dict[str, Any]:
    """
    Crea (o refresca) la cuenta del portal para un captador. Devuelve el acceso
    listo para entregar. Si ya existe y `reset_password` es False, no cambia nada.
    """
    tel10 = normalize_phone(telefono)
    if not tel10:
        return {"error": f"Teléfono inválido: {telefono}"}
    tel_full = telefono if str(telefono).startswith("+") else f"+57{tel10}"
    login_url = f"{FRONTEND_URL}/chat/login"

    with get_db() as db:
        inv = fetch_one(db.cursor, """
            SELECT COUNT(*) AS n FROM propiedades
            WHERE RIGHT(REGEXP_REPLACE(COALESCE(agente_captador_telefono,''),'[^0-9]','','g'),10) = %s
        """, (tel10,))
        inventario = inv["n"] if inv else 0

        if not nombre:
            a = fetch_one(db.cursor, """
                SELECT nombre FROM agentes
                WHERE RIGHT(REGEXP_REPLACE(telefono,'[^0-9]','','g'),10) = %s LIMIT 1
            """, (tel10,))
            nombre = (a or {}).get("nombre")
        if not nombre:
            pa = fetch_one(db.cursor, """
                SELECT asesor FROM propiedades
                WHERE RIGHT(REGEXP_REPLACE(COALESCE(agente_captador_telefono,''),'[^0-9]','','g'),10) = %s
                  AND asesor IS NOT NULL AND asesor <> '' LIMIT 1
            """, (tel10,))
            nombre = (pa or {}).get("asesor")
        # Limpiar el nombre scrapeado (labels, teléfono enmascarado, "Mostrar número").
        try:
            from src.services.interes_service import _limpiar_texto_captador
            if nombre:
                nombre = _limpiar_texto_captador(nombre)
        except Exception:
            pass
        nombre = nombre or f"Agente {tel10}"

        existente = fetch_one(db.cursor, """
            SELECT id, email FROM chat_users
            WHERE RIGHT(REGEXP_REPLACE(COALESCE(telefono,''),'[^0-9]','','g'),10) = %s LIMIT 1
        """, (tel10,))

        if existente and not reset_password:
            return {"ok": True, "ya_existia": True, "email": existente["email"],
                    "nombre": nombre, "inventario": inventario, "login_url": login_url,
                    "mensaje": "El agente ya tiene cuenta activa. Usa reset_password para regenerar la clave."}

        password = DEFAULT_PASSWORD

        if existente and reset_password:
            db.cursor.execute(
                "UPDATE chat_users SET password_hash = crypt(%s, gen_salt('bf')), activo = TRUE, "
                "origen = 'provision' WHERE id = %s",
                (password, existente["id"]))
            db.conn.commit()
            email_final = existente["email"]
        else:
            email_final = (email or f"{tel10}@agentes.fynder.co").strip().lower()
            dup = fetch_one(db.cursor, "SELECT id FROM chat_users WHERE lower(email) = lower(%s)", (email_final,))
            if dup:
                return {"error": f"Ya existe una cuenta con el email {email_final}. Usa otro email."}
            db.cursor.execute("""
                INSERT INTO chat_users (email, nombre, password_hash, telefono, activo, origen, acceso_entregado)
                VALUES (%s, %s, crypt(%s, gen_salt('bf')), %s, TRUE, 'provision', FALSE)
            """, (email_final, nombre, password, tel_full))
            db.conn.commit()

        return {"ok": True, "ya_existia": False, "email": email_final,
                "password": password, "nombre": nombre, "inventario": inventario,
                "login_url": login_url,
                "mensaje": f"Cuenta lista con {inventario} inmueble(s). Entrégale email + clave "
                           f"({password}) por WhatsApp."}


# =========================================================================
# Gestión de cuentas pre-cargadas (tabla en el admin)
# =========================================================================

def listar_precargadas() -> List[Dict[str, Any]]:
    """Lista las cuentas pre-cargadas (origen='provision') con inventario y estado de entrega."""
    with get_db() as db:
        rows = fetch_all(db.cursor, """
            SELECT u.id, u.nombre, u.email, u.telefono, u.activo, u.acceso_entregado,
                   u.acceso_entregado_at, u.ultimo_login, u.fecha_creacion,
                   (SELECT COUNT(*) FROM propiedades p
                    WHERE RIGHT(REGEXP_REPLACE(COALESCE(p.agente_captador_telefono,''),'[^0-9]','','g'),10)
                        = RIGHT(REGEXP_REPLACE(COALESCE(u.telefono,''),'[^0-9]','','g'),10)) AS inventario
            FROM chat_users u
            WHERE u.origen = 'provision'
            ORDER BY u.acceso_entregado ASC, inventario DESC, u.nombre ASC
        """)
    return [dict(r) for r in rows]


def set_acceso(user_id: int, entregado: bool) -> Dict[str, Any]:
    """Marca/desmarca si a esa cuenta pre-cargada ya se le entregó el acceso."""
    with get_db() as db:
        db.cursor.execute("""
            UPDATE chat_users
            SET acceso_entregado = %s,
                acceso_entregado_at = CASE WHEN %s THEN NOW() ELSE NULL END
            WHERE id = %s AND origen = 'provision'
            RETURNING id, acceso_entregado
        """, (entregado, entregado, user_id))
        row = db.cursor.fetchone()
        if not row:
            db.conn.rollback()
            return {"error": "Cuenta no encontrada o no es pre-cargada."}
        db.conn.commit()
    return {"ok": True, "id": row["id"], "acceso_entregado": row["acceso_entregado"]}


def provisionar_lote(limit: int = 50) -> Dict[str, Any]:
    """Provisiona cuentas para los captadores con más inventario que aún no tienen cuenta."""
    with get_db() as db:
        rows = fetch_all(db.cursor, """
            SELECT MAX(agente_captador_telefono) AS telefono, COUNT(*) AS inventario,
                   RIGHT(REGEXP_REPLACE(agente_captador_telefono,'[^0-9]','','g'),10) AS tel10
            FROM propiedades
            WHERE agente_captador_telefono IS NOT NULL
              AND RIGHT(REGEXP_REPLACE(agente_captador_telefono,'[^0-9]','','g'),10) NOT IN (
                  SELECT RIGHT(REGEXP_REPLACE(COALESCE(telefono,''),'[^0-9]','','g'),10)
                  FROM chat_users WHERE telefono IS NOT NULL)
            GROUP BY tel10
            ORDER BY inventario DESC
            LIMIT %s
        """, (limit,))
    creadas = 0
    for r in rows:
        res = provisionar_captador(r["telefono"])
        if res.get("ok") and not res.get("ya_existia"):
            creadas += 1
    return {"ok": True, "creadas": creadas, "candidatos": len(rows)}
