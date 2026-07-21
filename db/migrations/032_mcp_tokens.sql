-- Migration 032: soporte de tokens MCP sobre chat_user_sessions
-- El MCP de Fynder reutiliza chat_user_sessions como backbone de bearer tokens.
-- Se distinguen de las sesiones normales de chat con `tipo = 'mcp'` y se les
-- puede poner una etiqueta legible (ej. "Claude Desktop de Lina").

ALTER TABLE chat_user_sessions
    ADD COLUMN IF NOT EXISTS tipo VARCHAR(20) DEFAULT 'chat';

ALTER TABLE chat_user_sessions
    ADD COLUMN IF NOT EXISTS label VARCHAR(120);

COMMENT ON COLUMN chat_user_sessions.tipo IS
    'Tipo de sesión: chat (login web normal) | mcp (bearer token para el MCP).';
COMMENT ON COLUMN chat_user_sessions.label IS
    'Etiqueta legible del token MCP (dispositivo/uso), para gestión.';

CREATE INDEX IF NOT EXISTS idx_chat_user_sessions_tipo
    ON chat_user_sessions (tipo) WHERE tipo = 'mcp';
