-- 061: Instagram de Fynder (@fynder) — copia del módulo de Órbita.
--
-- instagram_posts: la foto de cada publicación del canal de Instagram en Buffer. La deja
-- el worker 2 veces al día (instagram_service.sincronizar); el admin (/admin/instagram)
-- lee SOLO de aquí, porque Buffer limita las llamadas diarias a su API.
-- instagram_seguidores: Buffer no da el total de seguidores de la cuenta; se anota a mano.

CREATE TABLE IF NOT EXISTS instagram_posts (
    buffer_id       TEXT PRIMARY KEY,
    tipo            TEXT,                         -- post | story | reel
    estado          TEXT NOT NULL,                -- scheduled | sending | sent | error | draft | needs_approval
    due_at          TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ,
    link            TEXT,
    texto           TEXT,
    miniaturas      JSONB NOT NULL DEFAULT '[]'::jsonb,
    imagenes        JSONB NOT NULL DEFAULT '[]'::jsonb,   -- la imagen completa de cada asset (en un reel, su miniatura)
    n_imagenes      INTEGER NOT NULL DEFAULT 0,
    metricas        JSONB,
    metricas_at     TIMESTAMPTZ,
    error           TEXT,
    avisado_at      TIMESTAMPTZ,                  -- cuándo salió el correo de «publicado» o «falló»
    avisado_estado  TEXT,                         -- por qué estado se avisó (de error a sent vuelve a avisar)
    sincronizado_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_estado ON instagram_posts (estado);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_due ON instagram_posts (due_at);

CREATE TABLE IF NOT EXISTS instagram_seguidores (
    fecha      DATE PRIMARY KEY,                  -- un registro por día; el último del día manda
    n          INTEGER NOT NULL CHECK (n >= 0),
    creado_por TEXT,
    creado_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS instagram_config (
    clave TEXT PRIMARY KEY,                       -- p. ej. meta_seguidores
    valor TEXT NOT NULL,
    actualizado_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
