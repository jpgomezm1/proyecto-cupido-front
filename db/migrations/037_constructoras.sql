-- ============================================================================
-- MIGRACIÓN 037: Módulo B2B de constructoras (Bloque E3)
-- Fecha: 2026-07-24
-- Descripción: Entidad `constructoras` + usuarios/sesiones para su portal propio
--   (login) + vínculo de inventario (propiedades.constructora_id). Los leads ya
--   traen constructora_id (migración 036). Aditiva; no toca datos existentes.
-- Requiere pgcrypto (ya usado por chat_users para crypt/gen_salt).
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1) La constructora (empresa B2B)
CREATE TABLE IF NOT EXISTS constructoras (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL,
    nit VARCHAR(50),
    contacto_email VARCHAR(255),
    contacto_telefono VARCHAR(20),
    activa BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 2) Usuarios del portal de la constructora (login propio, bcrypt vía pgcrypto)
CREATE TABLE IF NOT EXISTS constructora_users (
    id SERIAL PRIMARY KEY,
    constructora_id INTEGER NOT NULL REFERENCES constructoras(id) ON DELETE CASCADE,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    nombre VARCHAR(200),
    activo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    ultimo_acceso TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_constructora_users_constructora ON constructora_users(constructora_id);

-- 3) Sesiones (token bearer, revocables, con expiración)
CREATE TABLE IF NOT EXISTS constructora_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES constructora_users(id) ON DELETE CASCADE,
    token VARCHAR(500) UNIQUE NOT NULL,
    activa BOOLEAN DEFAULT TRUE,
    fecha_creacion TIMESTAMP DEFAULT NOW(),
    fecha_expiracion TIMESTAMP,
    ultimo_uso TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_constructora_sessions_token ON constructora_sessions(token);

-- 4) Vínculo de inventario: una propiedad puede pertenecer a una constructora
ALTER TABLE propiedades
    ADD COLUMN IF NOT EXISTS constructora_id INTEGER REFERENCES constructoras(id);
CREATE INDEX IF NOT EXISTS idx_propiedades_constructora ON propiedades(constructora_id)
    WHERE constructora_id IS NOT NULL;

COMMENT ON COLUMN propiedades.constructora_id IS 'Constructora dueña del inmueble (inventario B2B), si aplica';
COMMENT ON TABLE constructoras IS 'Empresas constructoras (B2B) con portal propio';

-- 5) Constructora DEMO para construir/testear (sin usuarios; el usuario demo se
--    crea con scripts/seed_constructora_demo.py para no meter credenciales aquí).
INSERT INTO constructoras (nombre, nit, contacto_email, activa)
VALUES ('Conaltura (DEMO)', '900123456-7', 'contacto@conaltura-demo.com', TRUE)
ON CONFLICT DO NOTHING;
