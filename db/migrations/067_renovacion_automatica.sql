-- 067: Renovación automática con tarjeta (débito automático, R19).
-- La tarjeta la captura el widget de Wompi (modo tokenize): Fynder solo guarda el id de la fuente de
-- pago de Wompi, la marca y los últimos 4 dígitos. Un día antes de que venza el plan, el worker cobra
-- con esa fuente (POST /v1/transactions, recurrent = true); el pago entra por pagos_service._aplicar
-- como cualquier otro. Lógica en src/services/renovacion_service.py.
-- Idempotente.

CREATE TABLE IF NOT EXISTS medios_pago (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES chat_users (id) ON DELETE CASCADE,
    pasarela            VARCHAR(20) NOT NULL DEFAULT 'wompi',
    fuente_id           BIGINT NOT NULL,                 -- payment_source de Wompi
    marca               VARCHAR(20),
    ultimos4            VARCHAR(4),
    plan_codigo         VARCHAR(20) NOT NULL REFERENCES planes (codigo),   -- el plan que renueva
    estado              VARCHAR(12) NOT NULL DEFAULT 'activa'
                        CHECK (estado IN ('activa', 'cancelada', 'fallida')),
    acepto_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),                -- autorizó el cobro mensual
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cancelada_at        TIMESTAMPTZ
);
-- Una sola renovación activa por agente.
CREATE UNIQUE INDEX IF NOT EXISTS ux_medios_pago_activa ON medios_pago (user_id) WHERE estado = 'activa';

-- Los cobros automáticos se distinguen en pagos (para reintentos y para el admin).
ALTER TABLE pagos ADD COLUMN IF NOT EXISTS automatico BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE pagos ADD COLUMN IF NOT EXISTS medio_pago_id INTEGER REFERENCES medios_pago (id);
