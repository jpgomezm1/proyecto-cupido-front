-- Asociar shareable link a cada pedido
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS share_id VARCHAR(50);
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS share_count INTEGER;
