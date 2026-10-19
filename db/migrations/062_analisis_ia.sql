-- 062: Modo Análisis de Findy (web): Findy con herramientas de mercado y respuesta con
-- componentes (OpenUI). Cada análisis le cuesta a Fynder ~USD 0,08–0,12 (Claude + 2–5
-- herramientas), así que tiene cupo propio, aparte del uso justo de la Búsqueda:
--  - planes.analisis_ia: análisis al mes de cada plan; en 'prueba' es un cupo de una sola vez.
--  - analisis_ia_movimientos: análisis extra (canje de Fyns, regalos); no vencen.
--  - analisis_ia: cada análisis, de qué cupo salió y lo que costó (tokens y USD).
-- Idempotente.

ALTER TABLE planes ADD COLUMN IF NOT EXISTS analisis_ia INTEGER NOT NULL DEFAULT 0;

UPDATE planes SET analisis_ia = 5  WHERE codigo = 'prueba'   AND analisis_ia = 0;
UPDATE planes SET analisis_ia = 15 WHERE codigo = 'basico'   AND analisis_ia = 0;
UPDATE planes SET analisis_ia = 30 WHERE codigo = 'medio'    AND analisis_ia = 0;
UPDATE planes SET analisis_ia = 60 WHERE codigo = 'pro'      AND analisis_ia = 0;
UPDATE planes SET analisis_ia = 60 WHERE codigo = 'fundador' AND analisis_ia = 0;

CREATE TABLE IF NOT EXISTS analisis_ia_movimientos (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    cantidad INTEGER NOT NULL,
    referencia VARCHAR(120),
    creado_por VARCHAR(120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_analisis_mov_user ON analisis_ia_movimientos(user_id);

CREATE TABLE IF NOT EXISTS analisis_ia (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    conversacion_id INTEGER,
    fuente VARCHAR(10) NOT NULL CHECK (fuente IN ('plan', 'prueba', 'extra')),
    estado VARCHAR(10) NOT NULL DEFAULT 'en_curso' CHECK (estado IN ('en_curso', 'ok', 'error')),
    pregunta TEXT,
    modelo VARCHAR(60),
    herramientas JSONB,
    tokens_entrada INTEGER,
    tokens_salida INTEGER,
    tokens_cache INTEGER,
    costo_usd NUMERIC(10, 5),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    terminado_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_analisis_ia_user ON analisis_ia(user_id, fuente, created_at);
