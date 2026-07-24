-- ============================================================================
-- MIGRACIÓN 036: Motor de asignación de leads (Bloque E)
-- Fecha: 2026-07-24
-- Descripción: Tabla `leads` — cada cruce pedido↔inmueble puntuado por el motor
--   (E1) con su índice de calidad (E2). Base de los matches de agentes y del
--   tablero B2B de constructoras (E3). Aditiva; no toca datos existentes.
-- ============================================================================

CREATE TABLE IF NOT EXISTS leads (
    id SERIAL PRIMARY KEY,
    pedido_id INTEGER REFERENCES pedidos(id) ON DELETE CASCADE,
    propiedad_id INTEGER REFERENCES propiedades(id) ON DELETE CASCADE,
    score INTEGER NOT NULL DEFAULT 0,           -- puntaje bruto 0..100
    calidad SMALLINT NOT NULL DEFAULT 1,        -- índice de calidad 1..10 (E2)
    razon TEXT,                                 -- explicación legible del match
    factores JSONB,                             -- desglose del puntaje
    fuente VARCHAR(20) DEFAULT 'motor',         -- 'motor' | 'manual'
    estado VARCHAR(20) DEFAULT 'nuevo',         -- 'nuevo' | 'aceptado' | 'rechazado' (E3)
    constructora_id INTEGER,                    -- para el tablero B2B (E3), opcional
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    -- Un pedido no debe tener el mismo inmueble como lead dos veces.
    CONSTRAINT uq_leads_pedido_propiedad UNIQUE (pedido_id, propiedad_id)
);

CREATE INDEX IF NOT EXISTS idx_leads_pedido ON leads(pedido_id);
CREATE INDEX IF NOT EXISTS idx_leads_propiedad ON leads(propiedad_id);
CREATE INDEX IF NOT EXISTS idx_leads_estado ON leads(estado);
CREATE INDEX IF NOT EXISTS idx_leads_calidad ON leads(calidad DESC);
CREATE INDEX IF NOT EXISTS idx_leads_constructora ON leads(constructora_id) WHERE constructora_id IS NOT NULL;

COMMENT ON TABLE leads IS 'Leads puntuados por el motor de asignación (Bloque E). Alimenta matches de agentes y tablero B2B.';
COMMENT ON COLUMN leads.score IS 'Puntaje bruto 0..100 (determinístico, sin IA)';
COMMENT ON COLUMN leads.calidad IS 'Índice de calidad del lead 1..10 (E2)';
COMMENT ON COLUMN leads.factores IS 'Desglose JSON del puntaje (presupuesto, zona, alcobas, tipo, recencia)';
COMMENT ON COLUMN leads.estado IS 'nuevo | aceptado | rechazado (la constructora acepta/rechaza en E3)';
