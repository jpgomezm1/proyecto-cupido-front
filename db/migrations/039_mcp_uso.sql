-- ============================================================================
-- MIGRACIÓN 039: Registro de uso de las tools del MCP
-- Fecha: 2026-10-02
-- Descripción: Tabla `mcp_tool_calls` — una fila por invocación de tool del MCP
--   (quién, qué tool, cuánto tardó, si falló). Base para medir adopción por
--   agente (suscripción) y qué tools aportan valor. Solo guarda los NOMBRES de
--   los argumentos, nunca sus valores (pueden traer cédulas, precios, etc.).
--   Aditiva; no toca datos existentes.
-- ============================================================================

CREATE TABLE IF NOT EXISTS mcp_tool_calls (
    id BIGSERIAL PRIMARY KEY,
    tool VARCHAR(80) NOT NULL,
    user_id INTEGER,                    -- chat_users.id (NULL si no autenticó)
    ok BOOLEAN NOT NULL,
    error VARCHAR(120),                 -- código de error de negocio o tipo de excepción
    duracion_ms INTEGER NOT NULL,
    argumentos TEXT[],                  -- solo nombres de argumentos usados
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_calls_created ON mcp_tool_calls(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_tool_calls_user ON mcp_tool_calls(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_tool_calls_tool ON mcp_tool_calls(tool, created_at DESC);
