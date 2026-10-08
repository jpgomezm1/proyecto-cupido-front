-- 050: verificación de disponibilidad curada.
--
-- Separa "intenté verificar" de "verifiqué": fecha_ultima_validacion solo se
-- sella con un veredicto concluyente (vivo o muerto), así la frescura que ve el
-- agente y el acuerdo de 8 días no cuentan como verificado un timeout o un 403.
-- La rotación del worker usa fecha_ultimo_intento.
--
-- desactivada_por = 'validador' permite reactivar sola una propiedad que el
-- validador bajó y que volvió a publicarse, sin tocar las que bajó un humano.
--
-- verificaciones_disponibilidad guarda cada veredicto para medir la precisión
-- por portal y auditar un cobro.

ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS fecha_ultimo_intento TIMESTAMP;
ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS disponibilidad_motivo TEXT;
ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS desactivada_por TEXT;

UPDATE propiedades
SET fecha_ultimo_intento = fecha_ultima_validacion
WHERE fecha_ultimo_intento IS NULL AND fecha_ultima_validacion IS NOT NULL;

UPDATE propiedades
SET desactivada_por = 'validador'
WHERE NOT activa AND desactivada_por IS NULL
  AND COALESCE(validaciones_fallidas_consecutivas, 0) > 0;

CREATE INDEX IF NOT EXISTS idx_propiedades_rotacion
    ON propiedades (fecha_ultimo_intento NULLS FIRST, id) WHERE activa;

CREATE TABLE IF NOT EXISTS verificaciones_disponibilidad (
    id BIGSERIAL PRIMARY KEY,
    propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,
    veredicto TEXT NOT NULL CHECK (veredicto IN ('vivo', 'muerto', 'incierto')),
    motivo TEXT,
    status_code INTEGER,
    portal TEXT,
    origen TEXT NOT NULL DEFAULT 'worker',
    cambio TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_verif_disp_prop ON verificaciones_disponibilidad (propiedad_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_verif_disp_fecha ON verificaciones_disponibilidad (created_at DESC);

-- Fynder ya no tiene portal de constructoras: sus inmuebles de demo salen del inventario.
UPDATE propiedades
SET activa = FALSE, desactivada_por = 'constructoras_retirado', fecha_actualizacion = NOW()
WHERE fuente = 'Constructora' AND activa;
