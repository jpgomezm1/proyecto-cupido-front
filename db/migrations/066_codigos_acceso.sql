-- 066: Códigos de acceso (beta cerrada de nov-2026).
-- Un código que el agente pone al registrarse (o en Mi cuenta › Plan) y que le activa el plan
-- Fundador (fundador_service.activar: todo lo de Cierre gratis hasta el 15-ene, luego $50.000 fijos).
-- Se crean con scripts/crear_codigo_acceso.py; cada código tiene usos máximos y vencimiento opcional.
-- Idempotente.

CREATE TABLE IF NOT EXISTS codigos_acceso (
    codigo      VARCHAR(40) PRIMARY KEY,                 -- en mayúsculas, sin espacios
    beneficio   VARCHAR(20) NOT NULL DEFAULT 'fundador' CHECK (beneficio IN ('fundador')),
    usos_max    INTEGER NOT NULL DEFAULT 1 CHECK (usos_max > 0),
    usos        INTEGER NOT NULL DEFAULT 0 CHECK (usos >= 0),
    vence_at    TIMESTAMPTZ,
    activo      BOOLEAN NOT NULL DEFAULT TRUE,
    notas       TEXT,
    creado_por  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS codigos_acceso_canjes (
    id           SERIAL PRIMARY KEY,
    codigo       VARCHAR(40) NOT NULL REFERENCES codigos_acceso (codigo),
    user_id      INTEGER NOT NULL REFERENCES chat_users (id),
    canjeado_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (codigo, user_id)
);
