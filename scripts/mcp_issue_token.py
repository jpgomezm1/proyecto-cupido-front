#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Emite un bearer token MCP para un agente (chat_user).

El token es una sesión en `chat_user_sessions` con `tipo='mcp'`. Se usa como
bearer en el conector de Claude (local o remoto). No caduca por defecto (o se le
puede dar días de expiración).

Uso:
    python scripts/mcp_issue_token.py --email agente@correo.com --label "Claude Desktop"
    python scripts/mcp_issue_token.py --user-id 4 --dias 365
    python scripts/mcp_issue_token.py --list            # lista tokens MCP activos
    python scripts/mcp_issue_token.py --revoke <token>  # desactiva un token
"""

import argparse
import secrets
import sys

sys.path.insert(0, ".")
from src.services.db import get_db, fetch_one, fetch_all  # noqa: E402


def _find_user(cur, email=None, user_id=None):
    if user_id:
        return fetch_one(cur, "SELECT id, email, nombre, telefono FROM chat_users WHERE id = %s AND activo = TRUE", (user_id,))
    if email:
        return fetch_one(cur, "SELECT id, email, nombre, telefono FROM chat_users WHERE email = %s AND activo = TRUE", (email,))
    return None


def issue(email=None, user_id=None, label=None, dias=None):
    with get_db() as db:
        user = _find_user(db.cursor, email, user_id)
        if not user:
            print(f"[ERROR] No se encontró un chat_user activo (email={email}, id={user_id})")
            return 1

        token = secrets.token_urlsafe(64)
        exp_clause = "NOW() + make_interval(days => %s)" if dias else "NULL"
        params = [token, user["id"], label or "MCP token"]
        if dias:
            params.append(dias)

        db.cursor.execute(f"""
            INSERT INTO chat_user_sessions (token, user_id, tipo, label, activa, fecha_expiracion)
            VALUES (%s, %s, 'mcp', %s, TRUE, {exp_clause})
        """, params)
        db.conn.commit()

        print("=" * 70)
        print(f"  Token MCP emitido para: {user['nombre']} <{user['email']}>")
        print(f"  Teléfono (scoping): {user['telefono']}")
        print(f"  Expira: {'en ' + str(dias) + ' días' if dias else 'no expira'}")
        print("=" * 70)
        print("\nBEARER TOKEN (guárdalo, no se vuelve a mostrar):\n")
        print(f"  {token}\n")
        print("Local (Claude Desktop):  export FYNDER_MCP_TOKEN=<token>")
        print("Remoto (Claude.ai):      Authorization: Bearer <token>")
        return 0


def list_tokens():
    with get_db() as db:
        rows = fetch_all(db.cursor, """
            SELECT s.id, s.label, s.fecha_creacion, s.fecha_expiracion, s.ultimo_uso,
                   u.nombre, u.email
            FROM chat_user_sessions s JOIN chat_users u ON u.id = s.user_id
            WHERE s.tipo = 'mcp' AND s.activa = TRUE
            ORDER BY s.fecha_creacion DESC
        """)
        if not rows:
            print("No hay tokens MCP activos.")
            return 0
        for r in rows:
            print(f"  #{r['id']:>4}  {r['nombre']:<28} {r['label'] or '':<20} "
                  f"últ.uso={r['ultimo_uso']}  exp={r['fecha_expiracion'] or 'nunca'}")
        return 0


def revoke(token):
    with get_db() as db:
        db.cursor.execute(
            "UPDATE chat_user_sessions SET activa = FALSE WHERE token = %s AND tipo = 'mcp'", (token,))
        n = db.cursor.rowcount
        db.conn.commit()
        print(f"{'Revocado' if n else 'No se encontró'} el token ({n} fila).")
        return 0


def main():
    ap = argparse.ArgumentParser(description="Emite/gestiona tokens MCP de Fynder")
    ap.add_argument("--email")
    ap.add_argument("--user-id", type=int)
    ap.add_argument("--label")
    ap.add_argument("--dias", type=int, help="días de expiración (default: no expira)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--revoke", metavar="TOKEN")
    args = ap.parse_args()

    if args.list:
        return list_tokens()
    if args.revoke:
        return revoke(args.revoke)
    if not (args.email or args.user_id):
        ap.error("indica --email o --user-id (o usa --list / --revoke)")
    return issue(args.email, args.user_id, args.label, args.dias)


if __name__ == "__main__":
    raise SystemExit(main())
