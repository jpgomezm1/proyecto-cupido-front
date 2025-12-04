-- ============================================================================
-- MIGRACIÓN: Agregar campos de validación de propiedades
-- Fecha: 2025-11-16
-- Descripción: Campos para sistema de validación automática de URLs
-- ============================================================================

-- Agregar campos de validación a la tabla propiedades
ALTER TABLE propiedades
ADD COLUMN IF NOT EXISTS fecha_ultima_validacion TIMESTAMP,
ADD COLUMN IF NOT EXISTS validaciones_fallidas_consecutivas INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS validacion_bloqueada BOOLEAN DEFAULT false;

-- Comentarios explicativos
COMMENT ON COLUMN propiedades.fecha_ultima_validacion IS 'Última vez que se validó la URL de la propiedad';
COMMENT ON COLUMN propiedades.validaciones_fallidas_consecutivas IS 'Contador de fallos consecutivos (404) - se resetea en éxito';
COMMENT ON COLUMN propiedades.validacion_bloqueada IS 'True si la validación fue bloqueada (403/401) - no reintentar';

-- Índices para mejorar performance de queries de validación
CREATE INDEX IF NOT EXISTS idx_propiedades_validacion
ON propiedades(activa, fuente, fecha_ultima_validacion)
WHERE fuente IN ('Wasi_Captado', 'Tu360_Captado');

CREATE INDEX IF NOT EXISTS idx_propiedades_validacion_pendiente
ON propiedades(validaciones_fallidas_consecutivas)
WHERE activa = true AND fuente IN ('Wasi_Captado', 'Tu360_Captado');

-- Inicializar campos para propiedades existentes
UPDATE propiedades
SET
    validaciones_fallidas_consecutivas = 0,
    validacion_bloqueada = false
WHERE validaciones_fallidas_consecutivas IS NULL;

COMMENT ON INDEX idx_propiedades_validacion IS 'Índice para optimizar búsqueda de propiedades a validar';
COMMENT ON INDEX idx_propiedades_validacion_pendiente IS 'Índice para propiedades con fallos que necesitan atención';
