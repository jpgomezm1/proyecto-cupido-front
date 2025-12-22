-- ============================================================================
-- MIGRACIÓN 006: Usuarios para Vista de Chat Compartible
-- ============================================================================
-- Descripción: Sistema de usuarios y tracking de uso para la UI de chat
-- Fecha: 2024-12
-- ============================================================================

-- ============================================================================
-- EXTENSIÓN PARA ENCRIPTAR PASSWORDS
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- TABLA: chat_users
-- ============================================================================
CREATE TABLE IF NOT EXISTS chat_users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    nombre VARCHAR(200) NOT NULL,

    -- Estado
    activo BOOLEAN DEFAULT TRUE,

    -- Timestamps
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ultimo_login TIMESTAMP,

    -- Metadata
    total_sesiones INTEGER DEFAULT 0,
    total_busquedas INTEGER DEFAULT 0
);

COMMENT ON TABLE chat_users IS 'Usuarios autorizados para la vista de chat compartible';

-- ============================================================================
-- TABLA: chat_user_sessions
-- ============================================================================
CREATE TABLE IF NOT EXISTS chat_user_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    token VARCHAR(500) NOT NULL UNIQUE,

    -- Info de sesión
    ip_address VARCHAR(50),
    user_agent TEXT,

    -- Estado
    activa BOOLEAN DEFAULT TRUE,

    -- Timestamps
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_expiracion TIMESTAMP,
    ultimo_uso TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE chat_user_sessions IS 'Sesiones activas de usuarios de chat';

-- ============================================================================
-- TABLA: chat_usage_log
-- ============================================================================
CREATE TABLE IF NOT EXISTS chat_usage_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,

    -- Tipo de acción
    accion VARCHAR(50) NOT NULL, -- 'login', 'search', 'conversation_create', 'message_send'

    -- Detalles
    conversacion_id INTEGER REFERENCES conversaciones_busqueda(id) ON DELETE SET NULL,
    detalles JSONB,

    -- Timestamp
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE chat_usage_log IS 'Registro de uso de la plataforma de chat';

-- ============================================================================
-- ÍNDICES
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_chat_users_email ON chat_users(email);
CREATE INDEX IF NOT EXISTS idx_chat_users_activo ON chat_users(activo) WHERE activo = TRUE;
CREATE INDEX IF NOT EXISTS idx_chat_sessions_token ON chat_user_sessions(token);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_activa ON chat_user_sessions(activa) WHERE activa = TRUE;
CREATE INDEX IF NOT EXISTS idx_chat_usage_user ON chat_usage_log(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_usage_fecha ON chat_usage_log(fecha DESC);
CREATE INDEX IF NOT EXISTS idx_chat_usage_accion ON chat_usage_log(accion);

-- ============================================================================
-- ASOCIAR CONVERSACIONES CON USUARIOS
-- ============================================================================
-- Agregar columna user_id a conversaciones_busqueda si no existe
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'conversaciones_busqueda' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE conversaciones_busqueda ADD COLUMN user_id INTEGER REFERENCES chat_users(id) ON DELETE SET NULL;
        CREATE INDEX idx_conversaciones_user ON conversaciones_busqueda(user_id);
    END IF;
END $$;

-- ============================================================================
-- FUNCIÓN PARA VERIFICAR PASSWORD
-- ============================================================================
CREATE OR REPLACE FUNCTION verify_chat_user_password(p_email VARCHAR, p_password VARCHAR)
RETURNS TABLE (
    user_id INTEGER,
    user_nombre VARCHAR,
    user_email VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        id,
        nombre,
        email
    FROM chat_users
    WHERE email = p_email
      AND password_hash = crypt(p_password, password_hash)
      AND activo = TRUE;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- FUNCIÓN PARA REGISTRAR LOGIN
-- ============================================================================
CREATE OR REPLACE FUNCTION register_chat_login(p_user_id INTEGER)
RETURNS VOID AS $$
BEGIN
    UPDATE chat_users
    SET ultimo_login = NOW(),
        total_sesiones = total_sesiones + 1
    WHERE id = p_user_id;

    INSERT INTO chat_usage_log (user_id, accion, detalles)
    VALUES (p_user_id, 'login', '{}');
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- INSERTAR USUARIOS INICIALES
-- ============================================================================
-- Solo insertar si no existen
INSERT INTO chat_users (email, password_hash, nombre)
SELECT 'jpgomez@stayirrelevant.com', crypt('Nov2011*', gen_salt('bf')), 'Juan Pablo Gomez'
WHERE NOT EXISTS (SELECT 1 FROM chat_users WHERE email = 'jpgomez@stayirrelevant.com');

INSERT INTO chat_users (email, password_hash, nombre)
SELECT 'hernanrios@stayirrelevant.com', crypt('Nov2011*', gen_salt('bf')), 'Hernan Rios'
WHERE NOT EXISTS (SELECT 1 FROM chat_users WHERE email = 'hernanrios@stayirrelevant.com');

-- ============================================================================
-- FIN DE MIGRACIÓN
-- ============================================================================
