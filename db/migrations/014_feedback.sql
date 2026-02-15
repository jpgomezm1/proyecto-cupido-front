-- Migration 014: Tabla de Feedback
-- Sistema de feedback para usuarios de chat

CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    categoria VARCHAR(50) NOT NULL,
    -- 'administrador', 'busqueda_propiedades', 'ai_search', 'general', 'otro'
    contenido TEXT NOT NULL,
    imagenes JSONB DEFAULT '[]'::jsonb,
    -- [{data: "base64...", nombre: "file.jpg", tipo: "image/jpeg"}]
    estado VARCHAR(30) NOT NULL DEFAULT 'nuevo',
    -- 'nuevo', 'en_revision', 'resuelto', 'descartado'
    prioridad VARCHAR(20) NOT NULL DEFAULT 'media',
    -- 'baja', 'media', 'alta', 'urgente'
    notas_admin TEXT,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indices
CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_estado ON feedback(estado);
CREATE INDEX IF NOT EXISTS idx_feedback_categoria ON feedback(categoria);
CREATE INDEX IF NOT EXISTS idx_feedback_fecha_creacion ON feedback(fecha_creacion DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_estado_categoria ON feedback(estado, categoria);
