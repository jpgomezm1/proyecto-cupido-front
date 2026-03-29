-- Agregar columna de presupuesto estimado para ordenamiento inteligente
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS presupuesto_estimado BIGINT;

CREATE INDEX IF NOT EXISTS idx_pedidos_presupuesto ON pedidos(presupuesto_estimado DESC NULLS LAST);
