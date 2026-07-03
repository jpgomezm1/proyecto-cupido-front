-- 031_anonimizar_listings.sql
-- Soporte para anonimizar/reescribir titulo y descripcion de las propiedades
-- y evitar que el texto coincida con el de otros portales (disintermediacion).
--
-- - titulo_original / descripcion_original: respaldo del texto crudo scrapeado
--   (permite revertir y mantener el dato para busqueda interna / re-embeddings).
-- - anonimizado_at / anonimizado_version: trazabilidad del proceso de reescritura.

ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS titulo_original TEXT;
ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS descripcion_original TEXT;
ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS anonimizado_at TIMESTAMP;
ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS anonimizado_version INTEGER;

-- Indice para procesar/reanudar rapido (propiedades aun no anonimizadas)
CREATE INDEX IF NOT EXISTS idx_propiedades_anonimizado
    ON propiedades(anonimizado_at);

COMMENT ON COLUMN propiedades.titulo_original IS 'Titulo crudo scrapeado del portal de origen (respaldo previo a anonimizacion)';
COMMENT ON COLUMN propiedades.descripcion_original IS 'Descripcion cruda scrapeada del portal de origen (respaldo previo a anonimizacion)';
COMMENT ON COLUMN propiedades.anonimizado_at IS 'Fecha en que titulo/descripcion fueron reescritos para evitar coincidencia con otros portales';
COMMENT ON COLUMN propiedades.anonimizado_version IS 'Version del proceso de anonimizacion aplicado';
