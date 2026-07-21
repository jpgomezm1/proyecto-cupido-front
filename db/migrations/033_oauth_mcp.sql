-- Migration 033: OAuth 2.1 para el MCP de Fynder
-- El MCP actúa como Authorization Server (via el SDK de MCP). Estas tablas
-- guardan clientes (Dynamic Client Registration), autorizaciones pendientes
-- (mientras el usuario hace login en Fynder), códigos de autorización y refresh
-- tokens. Los ACCESS tokens se reutilizan de chat_user_sessions (tipo='mcp').

CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id                   VARCHAR(255) PRIMARY KEY,
    client_secret               VARCHAR(255),
    client_name                 VARCHAR(255),
    redirect_uris               JSONB NOT NULL,
    grant_types                 JSONB,
    response_types              JSONB,
    scope                       TEXT,
    token_endpoint_auth_method  VARCHAR(50),
    metadata                    JSONB,
    created_at                  TIMESTAMP DEFAULT NOW()
);

-- Autorización en curso: se crea cuando Claude manda al usuario a /authorize y
-- lo redirigimos al login de Fynder. Guarda todo para poder emitir el code al
-- volver del login.
CREATE TABLE IF NOT EXISTS oauth_pending_auth (
    rid                                 VARCHAR(64) PRIMARY KEY,
    client_id                           VARCHAR(255) NOT NULL,
    redirect_uri                        TEXT NOT NULL,
    redirect_uri_provided_explicitly    BOOLEAN DEFAULT TRUE,
    code_challenge                      VARCHAR(255) NOT NULL,
    scopes                              JSONB,
    state                               TEXT,
    resource                            TEXT,
    expires_at                          DOUBLE PRECISION NOT NULL,
    created_at                          TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oauth_auth_codes (
    code                                VARCHAR(255) PRIMARY KEY,
    client_id                           VARCHAR(255) NOT NULL,
    user_id                             INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    redirect_uri                        TEXT NOT NULL,
    redirect_uri_provided_explicitly    BOOLEAN DEFAULT TRUE,
    code_challenge                      VARCHAR(255) NOT NULL,
    scopes                              JSONB,
    resource                            TEXT,
    expires_at                          DOUBLE PRECISION NOT NULL,
    created_at                          TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
    token       VARCHAR(255) PRIMARY KEY,
    client_id   VARCHAR(255) NOT NULL,
    user_id     INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    scopes      JSONB,
    expires_at  BIGINT,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oauth_pending_expires ON oauth_pending_auth (expires_at);
CREATE INDEX IF NOT EXISTS idx_oauth_codes_expires ON oauth_auth_codes (expires_at);

-- Los access tokens OAuth se emiten sobre chat_user_sessions (tipo='mcp').
-- Guardamos el client_id OAuth para poder reconstruir el AccessToken.
ALTER TABLE chat_user_sessions ADD COLUMN IF NOT EXISTS oauth_client_id VARCHAR(255);
