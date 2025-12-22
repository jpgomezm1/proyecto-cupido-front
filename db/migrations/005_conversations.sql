-- ============================================================================
-- MIGRACIÓN 005: Sistema de Conversaciones Persistentes
-- ============================================================================
-- Descripción: Tablas para guardar conversaciones de búsqueda tipo ChatGPT
-- Fecha: 2024-12
-- ============================================================================

-- ============================================================================
-- TABLA: conversaciones_busqueda
-- ============================================================================
-- Almacena las conversaciones de búsqueda de propiedades

CREATE TABLE IF NOT EXISTS conversaciones_busqueda (
    id SERIAL PRIMARY KEY,

    -- Identificación
    nombre VARCHAR(200) NOT NULL DEFAULT 'Nueva Conversación',

    -- Estado acumulado de la búsqueda
    criterios_acumulados JSONB DEFAULT '{}',

    -- Metadata
    total_mensajes INTEGER DEFAULT 0,
    total_propiedades_mostradas INTEGER DEFAULT 0,

    -- Estado
    activa BOOLEAN DEFAULT TRUE,

    -- Timestamps
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Comentarios
COMMENT ON TABLE conversaciones_busqueda IS 'Conversaciones de búsqueda persistentes tipo ChatGPT';
COMMENT ON COLUMN conversaciones_busqueda.criterios_acumulados IS 'Criterios de búsqueda acumulados entre mensajes (JSON)';
COMMENT ON COLUMN conversaciones_busqueda.activa IS 'Soft delete - FALSE significa eliminada';

-- ============================================================================
-- TABLA: mensajes_conversacion
-- ============================================================================
-- Almacena los mensajes de cada conversación (usuario y asistente)

CREATE TABLE IF NOT EXISTS mensajes_conversacion (
    id SERIAL PRIMARY KEY,

    -- Relación con conversación
    conversacion_id INTEGER NOT NULL REFERENCES conversaciones_busqueda(id) ON DELETE CASCADE,

    -- Contenido del mensaje
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,

    -- Criterios (para mensajes de búsqueda)
    criterios_mensaje JSONB,          -- Criterios extraídos de ESTE mensaje
    criterios_acumulados JSONB,       -- Estado acumulado DESPUÉS de este mensaje

    -- Resultados (para mensajes del asistente)
    propiedades_ids INTEGER[],        -- IDs de propiedades mostradas
    total_resultados INTEGER DEFAULT 0,
    tiempo_respuesta_ms INTEGER,

    -- Resultados completos para UI
    search_response JSONB,            -- Respuesta completa de búsqueda

    -- Timestamp
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Comentarios
COMMENT ON TABLE mensajes_conversacion IS 'Mensajes individuales de cada conversación de búsqueda';
COMMENT ON COLUMN mensajes_conversacion.role IS 'user = mensaje del usuario, assistant = respuesta del sistema';
COMMENT ON COLUMN mensajes_conversacion.criterios_mensaje IS 'Criterios extraídos solo de este mensaje';
COMMENT ON COLUMN mensajes_conversacion.criterios_acumulados IS 'Criterios acumulados después de procesar este mensaje';
COMMENT ON COLUMN mensajes_conversacion.search_response IS 'Respuesta completa de búsqueda incluyendo propiedades rankeadas';

-- ============================================================================
-- ÍNDICES
-- ============================================================================

-- Índices para conversaciones
CREATE INDEX IF NOT EXISTS idx_conversaciones_fecha_actualizacion
    ON conversaciones_busqueda(fecha_actualizacion DESC);
CREATE INDEX IF NOT EXISTS idx_conversaciones_activa
    ON conversaciones_busqueda(activa) WHERE activa = TRUE;
CREATE INDEX IF NOT EXISTS idx_conversaciones_fecha_creacion
    ON conversaciones_busqueda(fecha_creacion DESC);

-- Índices para mensajes
CREATE INDEX IF NOT EXISTS idx_mensajes_conversacion_id
    ON mensajes_conversacion(conversacion_id);
CREATE INDEX IF NOT EXISTS idx_mensajes_fecha
    ON mensajes_conversacion(fecha_creacion);
CREATE INDEX IF NOT EXISTS idx_mensajes_role
    ON mensajes_conversacion(role);

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Función para actualizar fecha_actualizacion y contadores
CREATE OR REPLACE FUNCTION actualizar_conversacion_on_mensaje()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE conversaciones_busqueda
    SET
        fecha_actualizacion = CURRENT_TIMESTAMP,
        total_mensajes = total_mensajes + 1,
        total_propiedades_mostradas = total_propiedades_mostradas + COALESCE(NEW.total_resultados, 0),
        criterios_acumulados = COALESCE(NEW.criterios_acumulados, criterios_acumulados)
    WHERE id = NEW.conversacion_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger después de insertar mensaje
DROP TRIGGER IF EXISTS trigger_actualizar_conversacion ON mensajes_conversacion;
CREATE TRIGGER trigger_actualizar_conversacion
    AFTER INSERT ON mensajes_conversacion
    FOR EACH ROW
    EXECUTE FUNCTION actualizar_conversacion_on_mensaje();

-- ============================================================================
-- VISTAS
-- ============================================================================

-- Vista de conversaciones con resumen
CREATE OR REPLACE VIEW v_conversaciones_resumen AS
SELECT
    c.id,
    c.nombre,
    c.total_mensajes,
    c.total_propiedades_mostradas,
    c.criterios_acumulados,
    c.fecha_creacion,
    c.fecha_actualizacion,
    -- Último mensaje
    (SELECT content FROM mensajes_conversacion
     WHERE conversacion_id = c.id
     ORDER BY fecha_creacion DESC LIMIT 1) as ultimo_mensaje,
    -- Tiempo desde última actualización
    CASE
        WHEN c.fecha_actualizacion > NOW() - INTERVAL '1 hour'
            THEN 'Hace ' || EXTRACT(MINUTE FROM NOW() - c.fecha_actualizacion)::INTEGER || ' min'
        WHEN c.fecha_actualizacion > NOW() - INTERVAL '24 hours'
            THEN 'Hace ' || EXTRACT(HOUR FROM NOW() - c.fecha_actualizacion)::INTEGER || ' horas'
        ELSE TO_CHAR(c.fecha_actualizacion, 'DD Mon')
    END as tiempo_relativo
FROM conversaciones_busqueda c
WHERE c.activa = TRUE
ORDER BY c.fecha_actualizacion DESC;

-- ============================================================================
-- FUNCIONES ÚTILES
-- ============================================================================

-- Función para obtener conversación completa con mensajes
CREATE OR REPLACE FUNCTION get_conversacion_completa(p_conversacion_id INTEGER)
RETURNS TABLE (
    conversacion_id INTEGER,
    conversacion_nombre VARCHAR,
    criterios_acumulados JSONB,
    mensaje_id INTEGER,
    mensaje_role VARCHAR,
    mensaje_content TEXT,
    mensaje_criterios JSONB,
    mensaje_resultados INTEGER,
    mensaje_search_response JSONB,
    mensaje_fecha TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id,
        c.nombre,
        c.criterios_acumulados,
        m.id,
        m.role,
        m.content,
        m.criterios_mensaje,
        m.total_resultados,
        m.search_response,
        m.fecha_creacion
    FROM conversaciones_busqueda c
    LEFT JOIN mensajes_conversacion m ON m.conversacion_id = c.id
    WHERE c.id = p_conversacion_id AND c.activa = TRUE
    ORDER BY m.fecha_creacion ASC;
END;
$$ LANGUAGE plpgsql;

-- Función para auto-generar nombre de conversación
CREATE OR REPLACE FUNCTION auto_nombre_conversacion(p_criterios JSONB)
RETURNS VARCHAR AS $$
DECLARE
    v_nombre VARCHAR := '';
    v_tipo VARCHAR;
    v_ubicacion VARCHAR;
    v_precio VARCHAR;
BEGIN
    -- Tipo de propiedad
    v_tipo := p_criterios->>'tipo_propiedad';
    IF v_tipo IS NOT NULL THEN
        v_nombre := INITCAP(v_tipo);
    END IF;

    -- Ubicación
    IF p_criterios->'ubicaciones' IS NOT NULL AND jsonb_array_length(p_criterios->'ubicaciones') > 0 THEN
        v_ubicacion := p_criterios->'ubicaciones'->>0;
        IF v_nombre != '' THEN v_nombre := v_nombre || ' '; END IF;
        v_nombre := v_nombre || v_ubicacion;
    END IF;

    -- Precio
    IF (p_criterios->>'precio_max')::NUMERIC IS NOT NULL THEN
        v_precio := (((p_criterios->>'precio_max')::NUMERIC) / 1000000)::INTEGER || 'M';
        IF v_nombre != '' THEN v_nombre := v_nombre || ' '; END IF;
        v_nombre := v_nombre || '$' || v_precio;
    END IF;

    -- Default si está vacío
    IF v_nombre = '' THEN
        v_nombre := 'Búsqueda ' || TO_CHAR(NOW(), 'DD Mon HH24:MI');
    END IF;

    RETURN v_nombre;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- DATOS DE EJEMPLO (opcional, comentar en producción)
-- ============================================================================

-- INSERT INTO conversaciones_busqueda (nombre, criterios_acumulados) VALUES
-- ('Apto Laureles 2 hab', '{"tipo_propiedad": "Apartamento", "ubicaciones": ["Laureles"], "habitaciones_min": 2, "precio_max": 500000000}'),
-- ('Casa El Poblado piscina', '{"tipo_propiedad": "Casa", "ubicaciones": ["El Poblado"], "amenidades_requeridas": ["piscina"], "precio_max": 1200000000}');

-- ============================================================================
-- FIN DE MIGRACIÓN
-- ============================================================================
