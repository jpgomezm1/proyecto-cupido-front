"""
Authorization Server OAuth 2.1 del MCP de Fynder.

Implementa `OAuthAuthorizationServerProvider` del SDK de MCP. El SDK expone los
endpoints del protocolo (metadata, /authorize, /token, /register (DCR), /revoke);
este provider aporta el almacenamiento y la lógica, autenticando contra los
`chat_users` existentes.

Flujo:
  Claude -> /authorize (SDK) -> provider.authorize() crea un "pending" y
  redirige al login de Fynder (/oauth/login) -> el usuario entra con su correo y
  clave -> se emite un authorization code -> Claude -> /token (SDK) ->
  exchange_authorization_code() emite el access token (guardado en
  chat_user_sessions, tipo='mcp') + refresh token.

Los access tokens se validan con load_access_token() (mismo store que el resto
del MCP), así que las tools resuelven la identidad por el `subject` (user_id).
"""

import json
import os
import secrets
import time
from typing import List, Optional

from mcp.server.auth.provider import (
    OAuthAuthorizationServerProvider,
    AuthorizationParams,
    AuthorizationCode,
    RefreshToken,
    AccessToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from src.services.db import get_db, fetch_one, fetch_all

DEFAULT_SCOPES = ["fynder:use"]
_PENDING_TTL = 600           # 10 min para completar el login
_CODE_TTL = 300              # 5 min de validez del authorization code
_ACCESS_TTL = 3600           # 1 hora el access token
_REFRESH_TTL = 60 * 60 * 24 * 90  # 90 días el refresh token


def public_base_url() -> str:
    return os.getenv("MCP_PUBLIC_URL", "http://localhost:8767").rstrip("/")


class FynderOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    # ---------------- Dynamic Client Registration ----------------
    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        with get_db() as db:
            row = fetch_one(db.cursor,
                "SELECT metadata FROM oauth_clients WHERE client_id = %s", (client_id,))
        if not row or not row.get("metadata"):
            return None
        return OAuthClientInformationFull.model_validate(row["metadata"])

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        data = client_info.model_dump(mode="json")
        with get_db() as db:
            db.cursor.execute("""
                INSERT INTO oauth_clients
                    (client_id, client_secret, client_name, redirect_uris,
                     grant_types, response_types, scope, token_endpoint_auth_method, metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (client_id) DO UPDATE SET metadata = EXCLUDED.metadata
            """, (
                client_info.client_id,
                client_info.client_secret,
                data.get("client_name"),
                json.dumps([str(u) for u in (client_info.redirect_uris or [])]),
                json.dumps(data.get("grant_types")),
                json.dumps(data.get("response_types")),
                data.get("scope"),
                data.get("token_endpoint_auth_method"),
                json.dumps(data),
            ))
            db.conn.commit()

    # ---------------- Authorize ----------------
    async def authorize(self, client: OAuthClientInformationFull,
                        params: AuthorizationParams) -> str:
        """Crea una autorización pendiente y redirige al login de Fynder."""
        rid = secrets.token_urlsafe(32)
        with get_db() as db:
            db.cursor.execute("""
                INSERT INTO oauth_pending_auth
                    (rid, client_id, redirect_uri, redirect_uri_provided_explicitly,
                     code_challenge, scopes, state, resource, expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                rid, client.client_id, str(params.redirect_uri),
                params.redirect_uri_provided_explicitly, params.code_challenge,
                json.dumps(params.scopes or DEFAULT_SCOPES), params.state,
                params.resource, time.time() + _PENDING_TTL,
            ))
            db.conn.commit()
        return f"{public_base_url()}/oauth/login?rid={rid}"

    # ---------------- Authorization code ----------------
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[AuthorizationCode]:
        with get_db() as db:
            row = fetch_one(db.cursor,
                "SELECT * FROM oauth_auth_codes WHERE code = %s", (authorization_code,))
        if not row or row["client_id"] != client.client_id:
            return None
        if row["expires_at"] < time.time():
            return None
        return AuthorizationCode(
            code=row["code"],
            scopes=row["scopes"] or DEFAULT_SCOPES,
            expires_at=row["expires_at"],
            client_id=row["client_id"],
            code_challenge=row["code_challenge"],
            redirect_uri=row["redirect_uri"],
            redirect_uri_provided_explicitly=row["redirect_uri_provided_explicitly"],
            resource=row.get("resource"),
            subject=str(row["user_id"]),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        user_id = int(authorization_code.subject)
        scopes = authorization_code.scopes or DEFAULT_SCOPES
        with get_db() as db:
            # Un code es de un solo uso.
            db.cursor.execute("DELETE FROM oauth_auth_codes WHERE code = %s",
                              (authorization_code.code,))
            access = _mint_access_token(db, user_id, client.client_id, scopes)
            refresh = _mint_refresh_token(db, user_id, client.client_id, scopes)
            db.conn.commit()
        return OAuthToken(access_token=access, token_type="Bearer",
                          expires_in=_ACCESS_TTL, scope=" ".join(scopes),
                          refresh_token=refresh)

    # ---------------- Refresh token ----------------
    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[RefreshToken]:
        with get_db() as db:
            row = fetch_one(db.cursor,
                "SELECT * FROM oauth_refresh_tokens WHERE token = %s", (refresh_token,))
        if not row or row["client_id"] != client.client_id:
            return None
        if row.get("expires_at") and row["expires_at"] < int(time.time()):
            return None
        return RefreshToken(token=row["token"], client_id=row["client_id"],
                            scopes=row["scopes"] or DEFAULT_SCOPES,
                            expires_at=row.get("expires_at"),
                            subject=str(row["user_id"]))

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull,
        refresh_token: RefreshToken, scopes: List[str]
    ) -> OAuthToken:
        user_id = int(refresh_token.subject)
        use_scopes = scopes or refresh_token.scopes or DEFAULT_SCOPES
        with get_db() as db:
            # Rotación: invalida el refresh anterior y emite uno nuevo.
            db.cursor.execute("DELETE FROM oauth_refresh_tokens WHERE token = %s",
                              (refresh_token.token,))
            access = _mint_access_token(db, user_id, client.client_id, use_scopes)
            new_refresh = _mint_refresh_token(db, user_id, client.client_id, use_scopes)
            db.conn.commit()
        return OAuthToken(access_token=access, token_type="Bearer",
                          expires_in=_ACCESS_TTL, scope=" ".join(use_scopes),
                          refresh_token=new_refresh)

    # ---------------- Access token (validación en cada request) ----------------
    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        with get_db() as db:
            row = fetch_one(db.cursor, """
                SELECT s.user_id, s.oauth_client_id, s.fecha_expiracion
                FROM chat_user_sessions s
                JOIN chat_users u ON u.id = s.user_id
                WHERE s.token = %s AND s.tipo = 'mcp' AND s.activa = TRUE
                  AND (s.fecha_expiracion IS NULL OR s.fecha_expiracion > NOW())
                  AND u.activo = TRUE
            """, (token,))
        if not row:
            return None
        exp = row.get("fecha_expiracion")
        return AccessToken(
            token=token,
            client_id=row.get("oauth_client_id") or "fynder-portal",
            scopes=DEFAULT_SCOPES,
            expires_at=int(exp.timestamp()) if exp else None,
            subject=str(row["user_id"]),
        )

    async def revoke_token(self, token) -> None:
        tok = getattr(token, "token", token)
        with get_db() as db:
            db.cursor.execute(
                "UPDATE chat_user_sessions SET activa = FALSE WHERE token = %s", (tok,))
            db.cursor.execute(
                "DELETE FROM oauth_refresh_tokens WHERE token = %s", (tok,))
            db.conn.commit()


# --------------------------------------------------------------------------
# Helpers de emisión de tokens.
# --------------------------------------------------------------------------

def _mint_access_token(db, user_id: int, client_id: str, scopes: List[str]) -> str:
    token = secrets.token_urlsafe(48)
    db.cursor.execute("""
        INSERT INTO chat_user_sessions
            (token, user_id, tipo, label, oauth_client_id, activa, fecha_expiracion)
        VALUES (%s, %s, 'mcp', %s, %s, TRUE, NOW() + make_interval(secs => %s))
    """, (token, user_id, "OAuth · IA conectada", client_id, _ACCESS_TTL))
    return token


def _mint_refresh_token(db, user_id: int, client_id: str, scopes: List[str]) -> str:
    token = secrets.token_urlsafe(48)
    db.cursor.execute("""
        INSERT INTO oauth_refresh_tokens (token, client_id, user_id, scopes, expires_at)
        VALUES (%s, %s, %s, %s, %s)
    """, (token, client_id, user_id, json.dumps(scopes), int(time.time()) + _REFRESH_TTL))
    return token


# --------------------------------------------------------------------------
# API para la página de login (oauth_login.py).
# --------------------------------------------------------------------------

def load_pending(rid: str) -> Optional[dict]:
    with get_db() as db:
        row = fetch_one(db.cursor,
            "SELECT * FROM oauth_pending_auth WHERE rid = %s", (rid,))
    if not row or row["expires_at"] < time.time():
        return None
    return row


def authenticate_chat_user(email: str, password: str) -> Optional[dict]:
    """Valida credenciales contra chat_users usando crypt() de pgcrypto
    (mismo método que el login del portal)."""
    with get_db() as db:
        return fetch_one(db.cursor, """
            SELECT id, nombre, email
            FROM chat_users
            WHERE email = %s AND activo = TRUE
              AND password_hash = crypt(%s, password_hash)
        """, ((email or "").strip().lower(), password or ""))


def complete_login(rid: str, user_id: int) -> Optional[str]:
    """
    Cierra una autorización pendiente emitiendo un authorization code para el
    usuario. Devuelve la URL de redirección final (con code y state), o None si
    la pendiente no existe/expiró.
    """
    with get_db() as db:
        pending = fetch_one(db.cursor,
            "SELECT * FROM oauth_pending_auth WHERE rid = %s", (rid,))
        if not pending or pending["expires_at"] < time.time():
            return None

        code = secrets.token_urlsafe(32)
        db.cursor.execute("""
            INSERT INTO oauth_auth_codes
                (code, client_id, user_id, redirect_uri, redirect_uri_provided_explicitly,
                 code_challenge, scopes, resource, expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            code, pending["client_id"], user_id, pending["redirect_uri"],
            pending["redirect_uri_provided_explicitly"], pending["code_challenge"],
            json.dumps(pending["scopes"] or DEFAULT_SCOPES), pending.get("resource"),
            time.time() + _CODE_TTL,
        ))
        db.cursor.execute("DELETE FROM oauth_pending_auth WHERE rid = %s", (rid,))
        db.conn.commit()

    return construct_redirect_uri(
        pending["redirect_uri"], code=code, state=pending.get("state"))
