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
