-- 048: áreas que el agente dibuja y guarda en el mapa de mercado
-- (su zona de captación, el radio de un cliente…). Polígono GeoJSON [[lng, lat], …] cerrado.
CREATE TABLE IF NOT EXISTS mapa_areas (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    nombre VARCHAR(60) NOT NULL,
    color VARCHAR(7) NOT NULL DEFAULT '#2AE38C',
    poligono JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mapa_areas_user ON mapa_areas(user_id, created_at DESC);
