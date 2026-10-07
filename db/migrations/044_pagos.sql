-- 044: pagos en línea de los planes (Wompi).
--
-- Un intento de pago por fila. El agente elige plan en la web → se crea la fila
-- 'pendiente' con una referencia única → paga en el checkout de Wompi → el
-- webhook (o la verificación al volver) la confirma. Al quedar 'aprobado' se
-- activa el periodo en `suscripciones` en la misma transacción (idempotente:
-- la fila se bloquea y un pago aprobado no se vuelve a procesar).

CREATE TABLE IF NOT EXISTS pagos (
    id SERIAL PRIMARY KEY,
    referencia VARCHAR(60) NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    plan_codigo VARCHAR(20) NOT NULL REFERENCES planes(codigo),
    monto_cop INTEGER NOT NULL,                -- precio del plan al crear el pago
    pasarela VARCHAR(20) NOT NULL DEFAULT 'wompi',
    estado VARCHAR(12) NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'aprobado', 'rechazado', 'anulado', 'error')),
    transaccion_id VARCHAR(60),
    metodo VARCHAR(30),                        -- CARD, PSE, NEQUI, BANCOLOMBIA_TRANSFER…
    suscripcion_id INTEGER REFERENCES suscripciones(id),
    detalle JSONB,                             -- última respuesta de la pasarela
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pagos_user ON pagos(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pagos_estado ON pagos(estado, created_at DESC);
