-- ============================================================================
-- MIGRACIÓN 052: Clientes del agente, alertas de cruce, cambios de precio y
--                llave suelta
-- Fecha: 2026-10-08
-- Aditiva: no cambia ni borra nada existente.
--
--  - cambios_precio: el validador de links ahora lee el precio en el portal de
--    origen; cada diferencia queda aquí (aplicada o no: un precio absurdo o uno
--    que el dueño editó en Fynder se registra pero no se aplica).
--  - planes.tipo: 'paquete' = llaves sueltas que se compran sin suscripción y
--    no vencen. Nace el producto 'llave' (1 llave).
--  - clientes_agente / cliente_inmuebles: los compradores de cada agente, su
--    perfil (el mismo "pedido" estructurado del buscador v3) y su selección.
--  - conversaciones_busqueda.cliente_id: una búsqueda de Findy hecha para un cliente.
--  - alertas: "entró algo para tu cliente" y "bajó de precio algo que guardaste",
--    en la app y en un resumen por correo (chat_users.alertas_correo).
-- ============================================================================

CREATE TABLE IF NOT EXISTS cambios_precio (
    id BIGSERIAL PRIMARY KEY,
    propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,
    precio_anterior BIGINT,
    precio_nuevo BIGINT NOT NULL,
    aplicado BOOLEAN NOT NULL DEFAULT TRUE,
    motivo VARCHAR(40),                 -- NULL | 'editado_por_agente' | 'sospechoso'
    origen VARCHAR(20),                 -- revalidacion | desbloqueo | visita | admin
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cambios_precio_prop ON cambios_precio(propiedad_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cambios_precio_fecha ON cambios_precio(created_at DESC) WHERE aplicado;

ALTER TABLE planes ADD COLUMN IF NOT EXISTS tipo VARCHAR(12) NOT NULL DEFAULT 'suscripcion';
ALTER TABLE planes DROP CONSTRAINT IF EXISTS planes_tipo_check;
ALTER TABLE planes ADD CONSTRAINT planes_tipo_check CHECK (tipo IN ('suscripcion', 'paquete'));
INSERT INTO planes (codigo, nombre, precio_cop, desbloqueos_mes, orden, tipo)
VALUES ('llave', 'Llave suelta', 12000, 1, 9, 'paquete')
ON CONFLICT (codigo) DO NOTHING;
ALTER TABLE pagos ADD COLUMN IF NOT EXISTS movimiento_id BIGINT REFERENCES creditos_movimientos(id);

CREATE TABLE IF NOT EXISTS clientes_agente (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    nombre VARCHAR(120) NOT NULL,
    telefono VARCHAR(30),
    proposito VARCHAR(12) CHECK (proposito IN ('vivir', 'invertir', 'otro')),
    plazo VARCHAR(12) CHECK (plazo IN ('ya', '3_meses', '6_meses', 'sin_afan')),
    estado VARCHAR(10) NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo', 'en_pausa', 'cerrado')),
    alertas BOOLEAN NOT NULL DEFAULT TRUE,
    notas TEXT,
    perfil JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_clientes_agente_user ON clientes_agente(user_id, estado, updated_at DESC);

CREATE TABLE IF NOT EXISTS cliente_inmuebles (
    cliente_id INTEGER NOT NULL REFERENCES clientes_agente(id) ON DELETE CASCADE,
    propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,
    estado VARCHAR(12) NOT NULL DEFAULT 'sugerido'
        CHECK (estado IN ('sugerido', 'enviado', 'le_gusta', 'visita', 'descartado')),
    nota TEXT,
    origen VARCHAR(10) NOT NULL DEFAULT 'manual' CHECK (origen IN ('manual', 'busqueda', 'alerta')),
    score REAL,
    razones TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (cliente_id, propiedad_id)
);
CREATE INDEX IF NOT EXISTS idx_cliente_inmuebles_prop ON cliente_inmuebles(propiedad_id);

ALTER TABLE conversaciones_busqueda
    ADD COLUMN IF NOT EXISTS cliente_id INTEGER REFERENCES clientes_agente(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS alertas (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    cliente_id INTEGER REFERENCES clientes_agente(id) ON DELETE CASCADE,
    tipo VARCHAR(16) NOT NULL CHECK (tipo IN ('nuevo_inmueble', 'baja_precio', 'sube_precio')),
    propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,
    score REAL,
    razones TEXT[] NOT NULL DEFAULT '{}',
    precio_anterior BIGINT,
    precio_nuevo BIGINT,
    leida_at TIMESTAMPTZ,
    correo_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_alertas_unica
    ON alertas(user_id, COALESCE(cliente_id, 0), propiedad_id, tipo, COALESCE(precio_nuevo, 0));
CREATE INDEX IF NOT EXISTS idx_alertas_user ON alertas(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alertas_correo ON alertas(user_id) WHERE correo_at IS NULL AND leida_at IS NULL;

ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS alertas_correo BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS alertas_correo_at TIMESTAMPTZ;

-- Hasta dónde ya revisó el job de alertas (inmuebles nuevos y cambios de precio).
CREATE TABLE IF NOT EXISTS alertas_cursor (
    clave VARCHAR(30) PRIMARY KEY,
    valor TIMESTAMPTZ NOT NULL
);
INSERT INTO alertas_cursor (clave, valor) VALUES
    ('inmuebles', NOW()), ('precios', NOW())
ON CONFLICT (clave) DO NOTHING;

-- Página pública del agente (getfynder.com/a/<slug>) y su logo en las piezas.
ALTER TABLE chat_users
    ADD COLUMN IF NOT EXISTS pagina_slug VARCHAR(40),
    ADD COLUMN IF NOT EXISTS pagina_activa BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS pagina_bio TEXT,
    ADD COLUMN IF NOT EXISTS pagina_zonas TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS logo_url TEXT,
    ADD COLUMN IF NOT EXISTS foto_url TEXT,
    ADD COLUMN IF NOT EXISTS marca_nombre VARCHAR(80);
CREATE UNIQUE INDEX IF NOT EXISTS ux_chat_users_pagina_slug ON chat_users(LOWER(pagina_slug)) WHERE pagina_slug IS NOT NULL;

-- Fotos mejoradas con IA (cupo mensual por agente).
CREATE TABLE IF NOT EXISTS fotos_mejoradas (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,
    url_original TEXT NOT NULL,
    url_mejorada TEXT,
    aplicada BOOLEAN NOT NULL DEFAULT FALSE,
    modelo VARCHAR(40),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fotos_mejoradas_user ON fotos_mejoradas(user_id, created_at DESC);
