-- 068: «Te conectamos» con llave (R20).
-- Un pedido cuyo autor no está en Fynder no se puede abrir con llave (Ley 1581: no hay autorización
-- para dar su celular). El agente paga 1 llave y Fynder le pide permiso a quien pidió y los presenta.
--   · La llave se gasta como cualquier contacto: una fila de desbloqueos (tipo 'pedido', vigente) SIN
--     contacto todavía; al aceptar se le pone el contacto y aparece en Contactos.
--   · Si quien pidió rechaza o no responde en 48 h, el desbloqueo pasa a 'reembolsado' (vuelve la llave).
-- Lógica en src/services/conexiones_service.py; el equipo la atiende en Admin › Conexiones.
-- Idempotente.

CREATE TABLE IF NOT EXISTS conexiones (
    id             SERIAL PRIMARY KEY,
    desbloqueo_id  INTEGER NOT NULL UNIQUE REFERENCES desbloqueos (id) ON DELETE CASCADE,
    user_id        INTEGER NOT NULL REFERENCES chat_users (id) ON DELETE CASCADE,
    pedido_id      INTEGER NOT NULL REFERENCES pedidos (id) ON DELETE CASCADE,
    estado         VARCHAR(15) NOT NULL DEFAULT 'pendiente'
                   CHECK (estado IN ('pendiente', 'aceptada', 'rechazada', 'sin_respuesta')),
    vence_at       TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '48 hours',
    resuelta_at    TIMESTAMPTZ,
    resuelta_por   TEXT,
    nota           TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conexiones_pendientes ON conexiones (vence_at) WHERE estado = 'pendiente';
CREATE INDEX IF NOT EXISTS idx_conexiones_user ON conexiones (user_id, created_at DESC);
