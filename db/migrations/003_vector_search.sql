-- ============================================
-- Migration 003: Vector Search con pgvector
-- ============================================
-- Habilita búsqueda semántica usando embeddings
-- Incluye análisis de imágenes con Claude Vision
-- ============================================

-- 1. Habilitar extensión pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Tabla de embeddings de propiedades
-- Almacena el embedding combinado de texto + características visuales
CREATE TABLE IF NOT EXISTS property_embeddings (
    id SERIAL PRIMARY KEY,
    propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,

    -- Embedding principal (texto: título + descripción + amenidades)
    embedding vector(1536),  -- OpenAI text-embedding-3-small dimension

    -- Texto usado para generar el embedding (para debugging/regeneración)
    texto_embedding TEXT,

    -- Metadata
    modelo_embedding VARCHAR(50) DEFAULT 'text-embedding-3-small',
    fecha_generacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    version INTEGER DEFAULT 1,

    -- Índice único para evitar duplicados
    UNIQUE(propiedad_id)
);

-- 3. Tabla de análisis de imágenes
-- Almacena características extraídas con Claude Vision
CREATE TABLE IF NOT EXISTS property_image_analysis (
    id SERIAL PRIMARY KEY,
    propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,
    imagen_url TEXT NOT NULL,

    -- Análisis de Claude Vision
    descripcion_visual TEXT,           -- Descripción detallada de la imagen
    estilo_detectado VARCHAR(100),     -- Moderno, Clásico, Minimalista, etc.
    ambiente VARCHAR(100),             -- Luminoso, Acogedor, Amplio, etc.
    calidad_imagen DECIMAL(3,1),       -- Score 0-10

    -- Características detectadas (JSON array)
    caracteristicas_visibles JSONB,    -- ["cocina integral", "vista ciudad", ...]
    puntos_destacados JSONB,           -- ["Amplio balcón", "Acabados de lujo", ...]

    -- Tipo de espacio detectado
    tipo_espacio VARCHAR(50),          -- sala, cocina, habitación, baño, exterior, fachada

    -- Metadata
    es_imagen_principal BOOLEAN DEFAULT FALSE,
    fecha_analisis TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modelo_analisis VARCHAR(50) DEFAULT 'claude-3-opus',

    -- Índice único por imagen
    UNIQUE(propiedad_id, imagen_url)
);

-- 4. Tabla de resumen visual por propiedad
-- Consolida el análisis de todas las imágenes
CREATE TABLE IF NOT EXISTS property_visual_summary (
    id SERIAL PRIMARY KEY,
    propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,

    -- Resumen consolidado
    descripcion_general TEXT,          -- Resumen de todas las imágenes
    estilo_predominante VARCHAR(100),  -- Estilo más común
    ambiente_general VARCHAR(100),     -- Ambiente general
    calidad_promedio DECIMAL(3,1),     -- Promedio de calidad de imágenes

    -- Características consolidadas (sin duplicados)
    todas_caracteristicas JSONB,       -- Array único de todas las características
    todos_puntos_destacados JSONB,     -- Array único de puntos destacados

    -- Tags para búsqueda rápida
    tags_visuales TEXT[],              -- Array de tags: ['moderno', 'luminoso', 'vista']

    -- Embedding visual (opcional, para búsqueda por imagen)
    embedding_visual vector(1536),

    -- Metadata
    total_imagenes_analizadas INTEGER DEFAULT 0,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(propiedad_id)
);

-- 5. Índices para búsqueda vectorial eficiente
-- Usando IVFFlat para balance entre velocidad y precisión
CREATE INDEX IF NOT EXISTS idx_property_embeddings_vector
ON property_embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_visual_summary_embedding
ON property_visual_summary
USING ivfflat (embedding_visual vector_cosine_ops)
WITH (lists = 100);

-- 6. Índices adicionales para queries frecuentes
CREATE INDEX IF NOT EXISTS idx_image_analysis_propiedad
ON property_image_analysis(propiedad_id);

CREATE INDEX IF NOT EXISTS idx_image_analysis_tipo_espacio
ON property_image_analysis(tipo_espacio);

CREATE INDEX IF NOT EXISTS idx_visual_summary_tags
ON property_visual_summary USING GIN(tags_visuales);

-- 7. Función para búsqueda por similitud semántica
CREATE OR REPLACE FUNCTION search_properties_by_embedding(
    query_embedding vector(1536),
    match_threshold FLOAT DEFAULT 0.7,
    match_count INT DEFAULT 10
)
RETURNS TABLE (
    propiedad_id INTEGER,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        pe.propiedad_id,
        1 - (pe.embedding <=> query_embedding) as similarity
    FROM property_embeddings pe
    JOIN propiedades p ON p.id = pe.propiedad_id
    WHERE p.activa = TRUE
    AND 1 - (pe.embedding <=> query_embedding) > match_threshold
    ORDER BY pe.embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- 8. Función para búsqueda híbrida (SQL + Vector)
CREATE OR REPLACE FUNCTION hybrid_property_search(
    query_embedding vector(1536),
    p_ciudad TEXT DEFAULT NULL,
    p_tipo TEXT DEFAULT NULL,
    p_precio_min NUMERIC DEFAULT NULL,
    p_precio_max NUMERIC DEFAULT NULL,
    p_habitaciones_min INT DEFAULT NULL,
    match_count INT DEFAULT 20
)
RETURNS TABLE (
    id INTEGER,
    titulo TEXT,
    precio NUMERIC,
    ciudad TEXT,
    zona TEXT,
    tipo_propiedad TEXT,
    habitaciones INTEGER,
    similarity FLOAT,
    score_final FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.id,
        p.titulo,
        p.precio,
        p.ciudad,
        p.zona,
        p.tipo_propiedad,
        p.habitaciones,
        1 - (pe.embedding <=> query_embedding) as similarity,
        -- Score combinado: 70% similitud semántica + 30% relevancia de filtros
        (0.7 * (1 - (pe.embedding <=> query_embedding))) +
        (0.3 * CASE
            WHEN p_ciudad IS NOT NULL AND LOWER(p.ciudad) = LOWER(p_ciudad) THEN 1.0
            WHEN p_ciudad IS NOT NULL AND p.ciudad ILIKE '%' || p_ciudad || '%' THEN 0.7
            ELSE 0.5
        END) as score_final
    FROM propiedades p
    JOIN property_embeddings pe ON pe.propiedad_id = p.id
    WHERE p.activa = TRUE
    AND (p_ciudad IS NULL OR p.ciudad ILIKE '%' || p_ciudad || '%' OR p.zona ILIKE '%' || p_ciudad || '%')
    AND (p_tipo IS NULL OR p.tipo_propiedad ILIKE '%' || p_tipo || '%')
    AND (p_precio_min IS NULL OR p.precio >= p_precio_min)
    AND (p_precio_max IS NULL OR p.precio <= p_precio_max)
    AND (p_habitaciones_min IS NULL OR p.habitaciones >= p_habitaciones_min)
    ORDER BY score_final DESC, similarity DESC
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- 9. Vista para propiedades con embeddings y análisis visual
CREATE OR REPLACE VIEW v_propiedades_enriquecidas AS
SELECT
    p.*,
    pe.embedding IS NOT NULL as tiene_embedding,
    pe.fecha_generacion as fecha_embedding,
    pvs.descripcion_general as descripcion_visual,
    pvs.estilo_predominante,
    pvs.ambiente_general,
    pvs.calidad_promedio as calidad_imagenes,
    pvs.tags_visuales,
    pvs.total_imagenes_analizadas
FROM propiedades p
LEFT JOIN property_embeddings pe ON pe.propiedad_id = p.id
LEFT JOIN property_visual_summary pvs ON pvs.propiedad_id = p.id;

-- 10. Comentarios para documentación
COMMENT ON TABLE property_embeddings IS 'Embeddings vectoriales de propiedades para búsqueda semántica';
COMMENT ON TABLE property_image_analysis IS 'Análisis individual de cada imagen con Claude Vision';
COMMENT ON TABLE property_visual_summary IS 'Resumen consolidado del análisis visual de todas las imágenes';
COMMENT ON FUNCTION search_properties_by_embedding IS 'Búsqueda por similitud semántica usando embeddings';
COMMENT ON FUNCTION hybrid_property_search IS 'Búsqueda híbrida combinando filtros SQL con similitud vectorial';
