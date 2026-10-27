-- 063: Valorador para propietarios (benchmark Idealista, negocio/estrategia/benchmark-idealista.md).
-- El propietario valora su inmueble gratis en /valorar (o en la página de un agente) y, si quiere
-- vender o arrendar, deja su WhatsApp, lo confirma con un código y autoriza el tratamiento de datos.
--  - Desde Fynder: el contacto lo abren máximo 3 agentes, con una llave cada uno (desbloqueos.tipo = 'valoracion').
--  - Desde la página de un agente (agente_id): el contacto es solo de ese agente y no le cuesta llave.
-- Idempotente.

CREATE TABLE IF NOT EXISTS valoraciones (
    id BIGSERIAL PRIMARY KEY,
    token VARCHAR(40) NOT NULL UNIQUE,              -- para seguir el recorrido sin cuenta
    agente_id INTEGER REFERENCES chat_users(id) ON DELETE SET NULL,  -- valorador de un agente
    -- El inmueble
    tipo_propiedad VARCHAR(40) NOT NULL,
    barrio_id INTEGER REFERENCES barrios(id),
    barrio VARCHAR(120),
    comuna VARCHAR(120),
    municipio VARCHAR(80),
    area NUMERIC(10, 2) NOT NULL,
    habitaciones SMALLINT,
    banos SMALLINT,
    resultado JSONB NOT NULL,                       -- lo que vio: rangos, muestra y nivel
    -- El propietario (solo si quiere que lo contacten)
    intencion VARCHAR(10) CHECK (intencion IN ('vender', 'arrendar', 'ambos')),
    plazo VARCHAR(12) CHECK (plazo IN ('ya', '3_meses', '6_meses', 'explorando')),
    nombre VARCHAR(120),
    telefono VARCHAR(20),
    codigo_hash VARCHAR(64),
    codigo_expira_at TIMESTAMPTZ,
    codigo_intentos SMALLINT NOT NULL DEFAULT 0,
    codigos_enviados SMALLINT NOT NULL DEFAULT 0,
    consentimiento_at TIMESTAMPTZ,
    consentimiento_version VARCHAR(20),
    verificada_at TIMESTAMPTZ,                      -- desde aquí la ven los agentes
    retirada_at TIMESTAMPTZ,                        -- el propietario pidió que no lo contacten
    token_retiro VARCHAR(40) UNIQUE,
    estado VARCHAR(12) NOT NULL DEFAULT 'valorada'
        CHECK (estado IN ('valorada', 'pendiente', 'activa', 'retirada')),
    desde VARCHAR(60),                              -- origen (utm) como en el registro
    ip_hash VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_valoraciones_activas ON valoraciones(verificada_at DESC) WHERE estado = 'activa';
CREATE INDEX IF NOT EXISTS idx_valoraciones_agente ON valoraciones(agente_id) WHERE agente_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_valoraciones_telefono ON valoraciones(telefono) WHERE telefono IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_valoraciones_ip ON valoraciones(ip_hash, created_at);

-- El contacto del propietario se abre como cualquier otro: con un desbloqueo.
ALTER TABLE desbloqueos DROP CONSTRAINT IF EXISTS desbloqueos_tipo_check;
ALTER TABLE desbloqueos ADD CONSTRAINT desbloqueos_tipo_check
    CHECK (tipo IN ('propiedad', 'pedido', 'valoracion'));
