-- 058: La red de Fynder y los complementos (diseño en negocio/estrategia/complementos-y-divisa.md).
-- Idempotente. Se va ampliando por partes antes de publicarse.

-- 1. Pedidos que los agentes comparten desde Fynder (no solo los de los grupos de WhatsApp).
--    canal: 'fynder_web' | 'fynder_mcp'. estado 'retirado' = el agente dejó de compartirlo.
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES chat_users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_pedidos_user ON pedidos(user_id) WHERE user_id IS NOT NULL;
ALTER TABLE clientes_agente ADD COLUMN IF NOT EXISTS pedido_id INTEGER REFERENCES pedidos(id) ON DELETE SET NULL;
