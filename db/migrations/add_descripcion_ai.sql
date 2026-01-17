-- Migration: Agregar campos para cachear descripción mejorada con AI
-- Fecha: 2026-01-16
-- Propósito: Evitar regenerar descripciones con AI en cada vista del link compartido

-- Agregar columna para descripción mejorada
ALTER TABLE propiedades
ADD COLUMN IF NOT EXISTS descripcion_ai TEXT;

-- Agregar columna para highlights (JSON array como texto)
ALTER TABLE propiedades
ADD COLUMN IF NOT EXISTS highlights_ai TEXT;

-- Agregar timestamp de cuándo se generó la descripción AI
ALTER TABLE propiedades
ADD COLUMN IF NOT EXISTS descripcion_ai_fecha TIMESTAMP;

-- Comentarios
COMMENT ON COLUMN propiedades.descripcion_ai IS 'Descripción mejorada con AI (cacheada)';
COMMENT ON COLUMN propiedades.highlights_ai IS 'Highlights generados por AI (JSON array como texto)';
COMMENT ON COLUMN propiedades.descripcion_ai_fecha IS 'Fecha de generación de la descripción AI';

-- Índice para búsquedas de propiedades sin descripción AI (para proceso batch)
CREATE INDEX IF NOT EXISTS idx_propiedades_sin_descripcion_ai
ON propiedades(id)
WHERE descripcion_ai IS NULL AND descripcion IS NOT NULL;
