-- 043: seguimiento de cada contacto desbloqueado (módulo Contactos).
-- Un registro por desbloqueo: en qué va el negocio, una nota y cuándo volver a
-- escribirle. Sin registro = "por_contactar".
CREATE TABLE IF NOT EXISTS contacto_seguimiento (
    desbloqueo_id BIGINT PRIMARY KEY REFERENCES desbloqueos(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    estado VARCHAR(20) NOT NULL DEFAULT 'por_contactar'
        CHECK (estado IN ('por_contactar', 'contactado', 'visita', 'negociando', 'cerrado', 'descartado')),
    nota TEXT,
    recordatorio DATE,
    estado_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contacto_seguimiento_user ON contacto_seguimiento (user_id, recordatorio);
