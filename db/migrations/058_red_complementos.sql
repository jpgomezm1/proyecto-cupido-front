-- 058: La red de Fynder y los complementos (diseño en negocio/estrategia/complementos-y-divisa.md).
-- Idempotente. Se va ampliando por partes antes de publicarse.

-- 1. Pedidos que los agentes comparten desde Fynder (no solo los de los grupos de WhatsApp).
--    canal: 'fynder_web' | 'fynder_mcp'. estado 'retirado' = el agente dejó de compartirlo.
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES chat_users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_pedidos_user ON pedidos(user_id) WHERE user_id IS NOT NULL;
ALTER TABLE clientes_agente ADD COLUMN IF NOT EXISTS pedido_id INTEGER REFERENCES pedidos(id) ON DELETE SET NULL;

-- 2. Complementos mensuales: paquetes que se suman a cualquier plan.
--    planes.tipo 'complemento' (trabaja, marca, ambos); cada compra abre un periodo
--    de 30 días en complementos_periodos (si ya tenía uno vigente, empieza al terminar).
ALTER TABLE planes DROP CONSTRAINT IF EXISTS planes_tipo_check;
ALTER TABLE planes ADD CONSTRAINT planes_tipo_check CHECK (tipo IN ('suscripcion', 'paquete', 'fotos', 'complemento'));
-- Nacen APAGADOS; se encienden cuando el front que los muestra esté publicado.
INSERT INTO planes (codigo, nombre, precio_cop, desbloqueos_mes, orden, tipo, activo)
VALUES ('trabaja', 'Findy trabaja por ti', 30000, 0, 30, 'complemento', FALSE),
       ('marca', 'Tu marca', 25000, 0, 31, 'complemento', FALSE),
       ('ambos', 'Findy trabaja por ti + Tu marca', 45000, 0, 32, 'complemento', FALSE)
ON CONFLICT (codigo) DO NOTHING;

CREATE TABLE IF NOT EXISTS complementos_periodos (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    codigo VARCHAR(20) NOT NULL,              -- trabaja | marca | ambos
    inicio TIMESTAMPTZ NOT NULL,
    fin TIMESTAMPTZ NOT NULL,
    referencia VARCHAR(120),
    precio_cop INTEGER,
    activado_por VARCHAR(120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_complementos_user ON complementos_periodos(user_id, fin DESC);
ALTER TABLE pagos ADD COLUMN IF NOT EXISTS complemento_periodo_id BIGINT REFERENCES complementos_periodos(id);

-- 3. Compradores para tus inmuebles: alerta cuando entra un pedido que encaja con
--    un inmueble del agente. Se distingue por pedido (varios compradores, mismo inmueble).
ALTER TABLE alertas ADD COLUMN IF NOT EXISTS pedido_id INTEGER REFERENCES pedidos(id) ON DELETE CASCADE;
ALTER TABLE alertas DROP CONSTRAINT IF EXISTS alertas_tipo_check;
ALTER TABLE alertas ADD CONSTRAINT alertas_tipo_check
    CHECK (tipo IN ('nuevo_inmueble', 'baja_precio', 'sube_precio', 'comprador'));
DROP INDEX IF EXISTS ux_alertas_unica;
CREATE UNIQUE INDEX IF NOT EXISTS ux_alertas_unica
    ON alertas(user_id, COALESCE(cliente_id, 0), propiedad_id, tipo, COALESCE(precio_nuevo, 0), COALESCE(pedido_id, 0));
INSERT INTO alertas_cursor (clave, valor) VALUES ('pedidos', NOW()) ON CONFLICT (clave) DO NOTHING;

-- 4. Encargos de Findy y Findy Conecta.
--    Un encargo: "búscame el mejor inmueble para este cliente" (cliente_id) o "el
--    mejor comprador para este inmueble" (propiedad_id). El worker lo trabaja y
--    guarda las mejores contrapartes; el agente pide una presentación y, si la otra
--    parte acepta, ambos reciben el contacto (aceptación doble, Ley 1581).
CREATE TABLE IF NOT EXISTS encargos (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    tipo VARCHAR(20) NOT NULL CHECK (tipo IN ('buscar_inmueble', 'buscar_comprador')),
    cliente_id INTEGER REFERENCES clientes_agente(id) ON DELETE CASCADE,
    propiedad_id INTEGER REFERENCES propiedades(id) ON DELETE CASCADE,
    estado VARCHAR(10) NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo', 'cerrado')),
    canal VARCHAR(10) NOT NULL DEFAULT 'web',
    ultimo_run_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cerrado_at TIMESTAMPTZ,
    CHECK ((tipo = 'buscar_inmueble' AND cliente_id IS NOT NULL) OR (tipo = 'buscar_comprador' AND propiedad_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_encargos_user ON encargos(user_id, estado);
CREATE UNIQUE INDEX IF NOT EXISTS ux_encargos_activo
    ON encargos(user_id, tipo, COALESCE(cliente_id, 0), COALESCE(propiedad_id, 0)) WHERE estado = 'activo';

-- Cupos extra de encargos comprados con Fyns (30 días cada uno).
CREATE TABLE IF NOT EXISTS encargos_extra (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    hasta TIMESTAMPTZ NOT NULL,
    referencia VARCHAR(120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_encargos_extra_user ON encargos_extra(user_id, hasta);

CREATE TABLE IF NOT EXISTS encargo_matches (
    id BIGSERIAL PRIMARY KEY,
    encargo_id BIGINT NOT NULL REFERENCES encargos(id) ON DELETE CASCADE,
    contraparte_tipo VARCHAR(10) NOT NULL CHECK (contraparte_tipo IN ('propiedad', 'pedido')),
    contraparte_id INTEGER NOT NULL,
    score REAL NOT NULL,
    razones TEXT[] NOT NULL DEFAULT '{}',
    estado VARCHAR(12) NOT NULL DEFAULT 'nuevo' CHECK (estado IN ('nuevo', 'visto', 'descartado', 'presentacion')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (encargo_id, contraparte_tipo, contraparte_id)
);
CREATE INDEX IF NOT EXISTS idx_encargo_matches ON encargo_matches(encargo_id, score DESC);

CREATE TABLE IF NOT EXISTS presentaciones (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT NOT NULL REFERENCES encargo_matches(id) ON DELETE CASCADE,
    solicitante_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    receptor_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    estado VARCHAR(10) NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'aceptada', 'rechazada', 'vencida', 'fallida')),
    prioridad BOOLEAN NOT NULL DEFAULT FALSE,
    mensaje TEXT,
    desbloqueo_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    respondida_at TIMESTAMPTZ,
    UNIQUE (match_id)
);
CREATE INDEX IF NOT EXISTS idx_presentaciones_receptor ON presentaciones(receptor_id, estado, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_presentaciones_solicitante ON presentaciones(solicitante_id, created_at DESC);

-- 5. La Vitrina: cada semana, pocas oportunidades curadas (inmuebles a precio de
--    oportunidad y pedidos top). Findy propone candidatos (vitrina_candidatos), el
--    admin los aprueba y el lunes se publica la semana (vitrina_items) con 72 h de
--    exclusividad y máximo 3 agentes por contacto. vitrina_accesos: quién abrió qué
--    semana y con qué (su plan, su complemento o Fyns).
CREATE TABLE IF NOT EXISTS vitrina_candidatos (
    id BIGSERIAL PRIMARY KEY,
    tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('propiedad', 'pedido')),
    ref_id INTEGER NOT NULL,
    score REAL,
    motivo JSONB NOT NULL DEFAULT '{}'::jsonb,
    estado VARCHAR(10) NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aprobado', 'rechazado', 'publicado')),
    revisado_por VARCHAR(120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tipo, ref_id)
);
CREATE TABLE IF NOT EXISTS vitrina_items (
    id BIGSERIAL PRIMARY KEY,
    semana DATE NOT NULL,
    tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('propiedad', 'pedido')),
    ref_id INTEGER NOT NULL,
    motivo JSONB NOT NULL DEFAULT '{}'::jsonb,
    orden SMALLINT NOT NULL DEFAULT 0,
    publicada_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exclusiva_hasta TIMESTAMPTZ NOT NULL,
    UNIQUE (semana, tipo, ref_id)
);
CREATE INDEX IF NOT EXISTS idx_vitrina_items_ref ON vitrina_items(tipo, ref_id, exclusiva_hasta);
CREATE TABLE IF NOT EXISTS vitrina_accesos (
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    semana DATE NOT NULL,
    fuente VARCHAR(10) NOT NULL,          -- plan | complemento | fyns
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, semana)
);

-- 6. Tu marca, quién vio tu link e informe de captación.
--    marca_usos: piezas firmadas con la marca del agente (sin Fynder), por mes.
--    piezas_vistas: cada pieza que el agente compartió y cuántas veces la abrió su cliente.
--    informes: informes de captación generados (con su foto de los datos); informes_extra: canjeados con Fyns.
CREATE TABLE IF NOT EXISTS marca_usos (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    tipo VARCHAR(20) NOT NULL,
    ref VARCHAR(160),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_marca_usos_user ON marca_usos(user_id, created_at);

CREATE TABLE IF NOT EXISTS piezas_vistas (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    clave VARCHAR(160) NOT NULL,
    tipo VARCHAR(20) NOT NULL,
    titulo TEXT,
    vistas INTEGER NOT NULL DEFAULT 0,
    primera_vista TIMESTAMPTZ,
    ultima_vista TIMESTAMPTZ,
    avisado_at TIMESTAMPTZ,
    con_detalle BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, clave)
);
CREATE INDEX IF NOT EXISTS idx_piezas_vistas_user ON piezas_vistas(user_id, ultima_vista DESC);

CREATE TABLE IF NOT EXISTS informes (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    propiedad_id INTEGER REFERENCES propiedades(id) ON DELETE SET NULL,
    datos JSONB NOT NULL,
    fuente VARCHAR(10) NOT NULL DEFAULT 'plan',     -- plan | extra
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_informes_user ON informes(user_id, created_at);
CREATE TABLE IF NOT EXISTS informes_extra (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    cantidad INTEGER NOT NULL,
    referencia VARCHAR(120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
