-- 070 · Encargos que aprenden: bitácora, opinión del cliente y etapa del negocio.
--
-- encargos.etapa: buscando → propuesto → visitando → negociando (y cerrado con `resultado`).
-- encargos.proxima_pregunta_at: cuándo puede Findy volver a preguntar (máximo una pendiente).
-- encargo_matches.opinion / motivos: qué le pareció la opción al cliente (le_gusta / no_le_gusta).
-- encargo_bitacora: la conversación del encargo. autor findy|agente; tipo:
--   novedad (encontró opciones), pregunta (seguimiento, con opciones), respuesta, aprendizaje
--   (cambió el perfil, con el antes y el después), nota (lo que el agente cuenta), estado.

ALTER TABLE encargos ADD COLUMN IF NOT EXISTS etapa VARCHAR(12) NOT NULL DEFAULT 'buscando'
    CHECK (etapa IN ('buscando', 'propuesto', 'visitando', 'negociando', 'cerrado'));
ALTER TABLE encargos ADD COLUMN IF NOT EXISTS resultado VARCHAR(10)
    CHECK (resultado IS NULL OR resultado IN ('ganado', 'perdido'));
ALTER TABLE encargos ADD COLUMN IF NOT EXISTS proxima_pregunta_at TIMESTAMPTZ;
ALTER TABLE encargos ADD COLUMN IF NOT EXISTS ultima_actividad_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE encargo_matches ADD COLUMN IF NOT EXISTS opinion VARCHAR(12)
    CHECK (opinion IS NULL OR opinion IN ('le_gusta', 'no_le_gusta'));
ALTER TABLE encargo_matches ADD COLUMN IF NOT EXISTS motivos TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE encargo_matches ADD COLUMN IF NOT EXISTS opinion_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS encargo_bitacora (
    id          BIGSERIAL PRIMARY KEY,
    encargo_id  BIGINT NOT NULL REFERENCES encargos(id) ON DELETE CASCADE,
    autor       VARCHAR(8)  NOT NULL CHECK (autor IN ('findy', 'agente')),
    tipo        VARCHAR(12) NOT NULL CHECK (tipo IN ('novedad', 'pregunta', 'respuesta', 'aprendizaje', 'nota', 'estado')),
    texto       TEXT NOT NULL,
    datos       JSONB NOT NULL DEFAULT '{}'::jsonb,
    respondida  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_encargo_bitacora ON encargo_bitacora(encargo_id, created_at);
CREATE INDEX IF NOT EXISTS idx_encargo_bitacora_pend ON encargo_bitacora(encargo_id) WHERE tipo = 'pregunta' AND NOT respondida;
