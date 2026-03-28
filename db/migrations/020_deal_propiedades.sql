-- ============================================
-- Migration 020: Deal Multi-Propiedades
-- ============================================
-- Permite asociar multiples propiedades a un deal
-- Un lead puede estar interesado en varias propiedades
-- ============================================

-- 1. Tabla de relacion deal <-> propiedades
CREATE TABLE IF NOT EXISTS deal_propiedades (
    id SERIAL PRIMARY KEY,
    deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    propiedad_id INTEGER NOT NULL REFERENCES propiedades(id),
    estado VARCHAR(20) DEFAULT 'interesado',  -- interesado, descartado, seleccionado
    notas TEXT,
    fecha_agregado TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(deal_id, propiedad_id)
);

-- Indices
CREATE INDEX IF NOT EXISTS idx_deal_propiedades_deal ON deal_propiedades(deal_id);
CREATE INDEX IF NOT EXISTS idx_deal_propiedades_propiedad ON deal_propiedades(propiedad_id);

-- 2. Seed: migrar propiedades existentes de deals actuales
-- Cada deal tiene un propiedad_id; lo insertamos en deal_propiedades como 'interesado'
INSERT INTO deal_propiedades (deal_id, propiedad_id, estado, fecha_agregado)
SELECT id, propiedad_id, 'interesado', fecha_creacion
FROM deals
WHERE propiedad_id IS NOT NULL
ON CONFLICT (deal_id, propiedad_id) DO NOTHING;

-- 3. Trigger para actualizar fecha_actualizacion
CREATE OR REPLACE FUNCTION update_deal_propiedad_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.fecha_actualizacion = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_deal_propiedad_timestamp ON deal_propiedades;
CREATE TRIGGER trg_update_deal_propiedad_timestamp
    BEFORE UPDATE ON deal_propiedades
    FOR EACH ROW
    EXECUTE FUNCTION update_deal_propiedad_timestamp();
