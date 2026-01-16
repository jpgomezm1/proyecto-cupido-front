-- Migration: 009_chat_favorites.sql
-- Description: Tabla de favoritos para usuarios del chat
-- Date: 2026-01-15

-- Tabla de favoritos para usuarios del chat
CREATE TABLE IF NOT EXISTS chat_user_favorites (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,

    fecha_agregada TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notas TEXT,  -- Nota opcional del usuario

    -- Constraint para evitar duplicados
    UNIQUE(user_id, propiedad_id)
);

-- Indices para optimizar consultas
CREATE INDEX IF NOT EXISTS idx_chat_favorites_user ON chat_user_favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_favorites_property ON chat_user_favorites(propiedad_id);
CREATE INDEX IF NOT EXISTS idx_chat_favorites_fecha ON chat_user_favorites(fecha_agregada DESC);

-- Comentarios
COMMENT ON TABLE chat_user_favorites IS 'Propiedades guardadas como favoritas por usuarios del chat';
COMMENT ON COLUMN chat_user_favorites.user_id IS 'ID del usuario del chat (FK a chat_users)';
COMMENT ON COLUMN chat_user_favorites.propiedad_id IS 'ID de la propiedad favorita (FK a propiedades)';
COMMENT ON COLUMN chat_user_favorites.notas IS 'Nota opcional del usuario sobre la propiedad';
