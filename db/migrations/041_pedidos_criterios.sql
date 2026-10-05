-- ============================================================================
-- MIGRACIÓN 041: Criterios estructurados de los pedidos
-- Fecha: 2026-10-04
-- Descripción: Los pedidos son texto libre ("desde San Lucas hasta Loma de las
--   Brujas, 3 alcobas con baño, mínimo 120 m², NO dúplex"). Claude Haiku los
--   convierte en criterios (tipo, zonas, presupuesto, habitaciones, área,
--   exigencias, exclusiones) para emparejar inmueble -> compradores con un
--   puntaje explicable (Findy en modo "Tengo un inmueble" y la tool del MCP
--   find_buyers_for_property). Aditiva; no toca datos existentes.
-- ============================================================================

ALTER TABLE pedidos
    ADD COLUMN IF NOT EXISTS criterios JSONB,
    ADD COLUMN IF NOT EXISTS criterios_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_pedidos_fecha_captura ON pedidos(fecha_captura DESC);
