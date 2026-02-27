-- Migration 018: Agregar tipo_negocio a propiedades
-- Distingue entre Venta y Arriendo para filtrar arriendos de búsquedas
-- Los arriendos se guardan en BD pero NUNCA aparecen en resultados de búsqueda

-- 1. Agregar columna
ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS tipo_negocio VARCHAR(20) DEFAULT 'Venta';

-- 2. Crear índice para filtrado rápido
CREATE INDEX IF NOT EXISTS idx_propiedades_tipo_negocio ON propiedades (tipo_negocio);

-- 3. Backfill: reclasificar arriendos existentes con heurísticas
-- Regla: si cumple CUALQUIERA de estas condiciones → es arriendo
UPDATE propiedades
SET tipo_negocio = 'Arriendo'
WHERE tipo_negocio = 'Venta'  -- Solo reclasificar los que están como Venta por default
AND (
    -- Heurística 1: título contiene palabras clave de arriendo
    titulo ILIKE '%arriendo%'
    OR titulo ILIKE '%se arrienda%'
    OR titulo ILIKE '%en arriendo%'
    OR titulo ILIKE '%arrendamiento%'

    -- Heurística 2: precio_texto contiene indicadores de arriendo
    OR precio_texto ILIKE '%mensual%'
    OR precio_texto ILIKE '%/mes%'
    OR precio_texto ILIKE '%arriendo%'

    -- Heurística 3: URL contiene rutas de arriendo
    OR url ILIKE '%/arriendo%'
    OR url ILIKE '%/rent%'
    OR url ILIKE '%/alquiler%'

    -- Heurística 4: precio muy bajo (ventas nunca están bajo 5M COP)
    OR (precio IS NOT NULL AND precio > 0 AND precio < 5000000)

    -- Heurística 5: descripción contiene términos de arriendo
    OR descripcion ILIKE '%canon de arriendo%'
    OR descripcion ILIKE '%canon mensual%'
    OR descripcion ILIKE '%se arrienda%'
);
