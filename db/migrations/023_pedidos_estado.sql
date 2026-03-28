-- =====================================================================
-- Migration 023: Campo estado para pedidos (pendiente → en_proceso → procesado)
-- Reemplaza el boolean procesado por un flujo de 3 etapas
-- =====================================================================

ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS estado VARCHAR(15) DEFAULT 'pendiente' NOT NULL;

-- Migrar datos existentes del boolean al nuevo campo
UPDATE pedidos SET estado = 'procesado' WHERE procesado = true AND estado = 'pendiente';
