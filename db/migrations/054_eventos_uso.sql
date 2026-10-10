-- 054 · Eventos de uso de la interfaz (app del agente).
--
-- Los mismos eventos que se mandan a PostHog (páginas vistas, búsqueda con
-- Findy, abrir un inmueble, usar una llave, guardar, publicar…) quedan también
-- en la base de Fynder, para que el tablero del admin funcione sin depender de
-- una llave de lectura de PostHog. Solo el id del agente: sin datos personales.

CREATE TABLE IF NOT EXISTS eventos_uso (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES chat_users(id) ON DELETE CASCADE,
    evento TEXT NOT NULL,
    ruta TEXT,
    props JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eventos_uso_fecha ON eventos_uso (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_eventos_uso_evento ON eventos_uso (evento, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_eventos_uso_user ON eventos_uso (user_id, created_at DESC);
