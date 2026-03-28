-- =====================================================================
-- Migration 022: Campos de procesamiento para pedidos
-- Agrega texto_formateado (AI-processed) y procesado (checkbox)
-- =====================================================================

ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS texto_formateado TEXT;
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS procesado BOOLEAN DEFAULT false;
