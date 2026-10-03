-- ============================================================================
-- MIGRACIÓN 040: Suscripciones y desbloqueo de contactos
-- Fecha: 2026-10-02
-- Descripción: Modelo de negocio por suscripción (tipo Apollo). Los agentes
--   (chat_users) usan gratis búsqueda y análisis; el CONTACTO de quien tiene un
--   inmueble (o de quien hizo un pedido) se desbloquea con créditos:
--     - prueba: 2 créditos al verificar el teléfono (no vencen, 1 por teléfono)
--     - planes mensuales (activación manual tras consignación)
--     - paquetes extra (manuales, no vencen)
--   El saldo NO se guarda: se deriva de suscripciones + créditos − desbloqueos.
--   Aditiva; no toca datos existentes salvo el backfill de teléfono verificado.
-- ============================================================================

-- --- chat_users: verificación de teléfono y términos ------------------------
ALTER TABLE chat_users
    ADD COLUMN IF NOT EXISTS telefono_verificado BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS telefono_verificado_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS terminos_aceptados_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS terminos_version VARCHAR(10);

-- Cuentas creadas por Fynder (precargadas / admin) traen el teléfono del propio
-- captador: se consideran verificadas. Los auto-registros del MCP (password
-- placeholder 'mcp$...') quedan sin verificar hasta que el admin lo confirme.
UPDATE chat_users
SET telefono_verificado = TRUE, telefono_verificado_at = NOW()
WHERE telefono IS NOT NULL AND telefono <> ''
  AND password_hash NOT LIKE 'mcp$%%'
  AND telefono_verificado = FALSE;

-- --- planes -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS planes (
    codigo VARCHAR(20) PRIMARY KEY,
    nombre VARCHAR(60) NOT NULL,
    precio_cop INTEGER NOT NULL DEFAULT 0,
    desbloqueos_mes INTEGER NOT NULL DEFAULT 0,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    orden SMALLINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO planes (codigo, nombre, precio_cop, desbloqueos_mes, orden) VALUES
    ('prueba', 'Prueba', 0, 0, 0),
    ('basico', 'Básico', 50000, 7, 1),
    ('medio', 'Medio', 80000, 15, 2),
    ('pro', 'Pro', 100000, 30, 3)
ON CONFLICT (codigo) DO NOTHING;

-- --- suscripciones: un periodo pagado por fila --------------------------------
CREATE TABLE IF NOT EXISTS suscripciones (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    plan_codigo VARCHAR(20) NOT NULL REFERENCES planes(codigo),
    desbloqueos_incluidos INTEGER NOT NULL,   -- copia del plan al activar
    precio_cop INTEGER NOT NULL,              -- copia del plan al activar
    inicio TIMESTAMPTZ NOT NULL,
    fin TIMESTAMPTZ NOT NULL,                 -- inicio + 30 días
    gracia_hasta TIMESTAMPTZ NOT NULL,        -- fin + 5 días
    estado VARCHAR(12) NOT NULL DEFAULT 'activa'
        CHECK (estado IN ('activa', 'cancelada')),
    referencia_pago VARCHAR(120),
    notas TEXT,
    activada_por VARCHAR(120),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_suscripciones_user ON suscripciones(user_id, inicio DESC);

-- --- créditos que no vencen (prueba, paquetes extra, ajustes) -----------------
-- Solo ABONOS: el consumo vive en `desbloqueos`.
CREATE TABLE IF NOT EXISTS creditos_movimientos (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('prueba', 'extra', 'ajuste')),
    cantidad INTEGER NOT NULL,
    telefono_10 VARCHAR(10),
    referencia VARCHAR(120),
    creado_por VARCHAR(120),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_creditos_user ON creditos_movimientos(user_id);
-- Una prueba por usuario y una por teléfono (evita farmear con correos nuevos).
CREATE UNIQUE INDEX IF NOT EXISTS ux_creditos_prueba_user
    ON creditos_movimientos(user_id) WHERE tipo = 'prueba';
CREATE UNIQUE INDEX IF NOT EXISTS ux_creditos_prueba_tel
    ON creditos_movimientos(telefono_10) WHERE tipo = 'prueba';

-- --- desbloqueos -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS desbloqueos (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('propiedad', 'pedido')),
    ref_id INTEGER NOT NULL,
    fuente_credito VARCHAR(10) NOT NULL CHECK (fuente_credito IN ('plan', 'saldo', 'gratis')),
    suscripcion_id INTEGER REFERENCES suscripciones(id),
    motivo_gratis VARCHAR(20),               -- 'propia' | 'admin'
    contacto_telefono VARCHAR(30),           -- copia para auditoría / disputas
    contacto_nombre VARCHAR(160),
    contacto_agencia VARCHAR(160),
    disponibilidad_estado VARCHAR(15),
    estado VARCHAR(12) NOT NULL DEFAULT 'vigente'
        CHECK (estado IN ('vigente', 'reembolsado')),
    canal VARCHAR(10),                       -- 'mcp' | 'web'
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_desbloqueos_user_ref ON desbloqueos(user_id, tipo, ref_id);
CREATE INDEX IF NOT EXISTS idx_desbloqueos_ref ON desbloqueos(tipo, ref_id);
CREATE INDEX IF NOT EXISTS idx_desbloqueos_suscripcion ON desbloqueos(suscripcion_id);

-- --- reportes de contacto inválido (reembolsos) ------------------------------
CREATE TABLE IF NOT EXISTS reportes_contacto (
    id BIGSERIAL PRIMARY KEY,
    desbloqueo_id BIGINT NOT NULL UNIQUE REFERENCES desbloqueos(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    motivo VARCHAR(20) NOT NULL CHECK (motivo IN
        ('numero_equivocado', 'no_contesta', 'no_es_el_agente', 'ya_no_disponible', 'otro')),
    detalle TEXT,
    reembolsado BOOLEAN NOT NULL DEFAULT FALSE,
    resuelto_at TIMESTAMPTZ,
    resolucion TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_reportes_pendientes ON reportes_contacto(created_at) WHERE resuelto_at IS NULL;

-- --- uso justo diario (búsquedas que gastan tokens nuestros) -----------------
CREATE TABLE IF NOT EXISTS uso_diario (
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    fecha DATE NOT NULL,
    busquedas INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, fecha)
);
