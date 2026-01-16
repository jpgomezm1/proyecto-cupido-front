-- ============================================================================
-- MIGRACIÓN 008: Agregar user_id a conversaciones_busqueda
-- ============================================================================
-- Descripción: Asegura que la columna user_id exista para segregar conversaciones
-- por usuario
-- Fecha: 2025-01
-- ============================================================================

-- Verificar y agregar columna user_id si no existe
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'conversaciones_busqueda' AND column_name = 'user_id'
    ) THEN
        -- Agregar la columna
        ALTER TABLE conversaciones_busqueda
        ADD COLUMN user_id INTEGER REFERENCES chat_users(id) ON DELETE SET NULL;

        -- Crear índice para búsquedas rápidas
        CREATE INDEX IF NOT EXISTS idx_conversaciones_user_id
        ON conversaciones_busqueda(user_id);

        RAISE NOTICE 'Columna user_id agregada a conversaciones_busqueda';
    ELSE
        RAISE NOTICE 'La columna user_id ya existe en conversaciones_busqueda';
    END IF;
END $$;

-- Verificar que la tabla chat_usage_log existe
CREATE TABLE IF NOT EXISTS chat_usage_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    accion VARCHAR(50) NOT NULL,
    conversacion_id INTEGER REFERENCES conversaciones_busqueda(id) ON DELETE SET NULL,
    detalles JSONB,
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Crear índices si no existen
CREATE INDEX IF NOT EXISTS idx_conversaciones_user_id
ON conversaciones_busqueda(user_id);

CREATE INDEX IF NOT EXISTS idx_chat_usage_user
ON chat_usage_log(user_id);

CREATE INDEX IF NOT EXISTS idx_chat_usage_fecha
ON chat_usage_log(fecha DESC);

-- ============================================================================
-- VERIFICACIÓN
-- ============================================================================
-- Ejecuta esta query para verificar que todo está correcto:
-- SELECT column_name, data_type
-- FROM information_schema.columns
-- WHERE table_name = 'conversaciones_busqueda' AND column_name = 'user_id';

-- ============================================================================
-- FIN DE MIGRACIÓN
-- ============================================================================
