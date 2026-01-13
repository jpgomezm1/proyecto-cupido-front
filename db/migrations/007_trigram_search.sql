-- =============================================================================
-- Migración 007: Búsqueda Fuzzy con Trigrams y Geoespacial
-- =============================================================================
-- Esta migración habilita:
-- 1. Búsqueda fuzzy usando pg_trgm para encontrar ubicaciones con typos
-- 2. Índices optimizados para búsqueda por similitud
-- 3. Índice geoespacial para búsquedas por distancia
-- =============================================================================

-- Habilitar extensión pg_trgm para búsqueda fuzzy
-- Esta extensión permite calcular similitud entre strings usando trigramas
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =============================================================================
-- ÍNDICES TRIGRAM PARA BÚSQUEDA FUZZY
-- =============================================================================

-- Índice trigram en zona para búsquedas similares
-- Permite encontrar "Laureles" cuando buscan "Laurels" (typo)
CREATE INDEX IF NOT EXISTS idx_propiedades_zona_trgm
ON propiedades USING gin (zona gin_trgm_ops);

-- Índice trigram en ciudad
CREATE INDEX IF NOT EXISTS idx_propiedades_ciudad_trgm
ON propiedades USING gin (ciudad gin_trgm_ops);

-- Índice trigram en título para búsquedas en descripciones
CREATE INDEX IF NOT EXISTS idx_propiedades_titulo_trgm
ON propiedades USING gin (titulo gin_trgm_ops);

-- =============================================================================
-- ÍNDICES GEOESPACIALES
-- =============================================================================

-- Índice compuesto para búsquedas geoespaciales
-- Usado con la fórmula Haversine para calcular distancias
CREATE INDEX IF NOT EXISTS idx_propiedades_geo
ON propiedades (latitud, longitud)
WHERE latitud IS NOT NULL AND longitud IS NOT NULL;

-- =============================================================================
-- FUNCIÓN DE BÚSQUEDA POR DISTANCIA (Haversine)
-- =============================================================================

-- Función para calcular distancia en km entre dos puntos
CREATE OR REPLACE FUNCTION distancia_km(
    lat1 DECIMAL,
    lon1 DECIMAL,
    lat2 DECIMAL,
    lon2 DECIMAL
) RETURNS DECIMAL AS $$
BEGIN
    RETURN 6371 * acos(
        cos(radians(lat1)) *
        cos(radians(lat2)) *
        cos(radians(lon2) - radians(lon1)) +
        sin(radians(lat1)) *
        sin(radians(lat2))
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- =============================================================================
-- COMENTARIOS
-- =============================================================================

COMMENT ON EXTENSION pg_trgm IS 'Soporte para búsqueda fuzzy con trigramas';
COMMENT ON INDEX idx_propiedades_zona_trgm IS 'Índice para búsqueda fuzzy en zona';
COMMENT ON INDEX idx_propiedades_ciudad_trgm IS 'Índice para búsqueda fuzzy en ciudad';
COMMENT ON INDEX idx_propiedades_geo IS 'Índice para búsquedas geoespaciales';
COMMENT ON FUNCTION distancia_km IS 'Calcula distancia en km usando fórmula Haversine';

-- =============================================================================
-- VERIFICACIÓN
-- =============================================================================

-- Verificar que la extensión está instalada
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        RAISE EXCEPTION 'La extensión pg_trgm no se pudo instalar';
    END IF;
    RAISE NOTICE 'Migración 007 completada: pg_trgm y índices geoespaciales instalados';
END;
$$;
