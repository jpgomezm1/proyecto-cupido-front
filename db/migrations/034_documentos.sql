-- Migration 034: documentos generados (promesa de compraventa, etc.)
-- Los datos incluyen info de las partes (nombres/cédulas), así que el acceso es
-- por un share_id largo y aleatorio (no adivinable), no por id secuencial.

CREATE TABLE IF NOT EXISTS documentos_generados (
    share_id          VARCHAR(64) PRIMARY KEY,
    tipo              VARCHAR(50) NOT NULL,          -- 'promesa_compraventa'
    propiedad_id      INTEGER REFERENCES propiedades(id),
    agente_telefono   VARCHAR(30),
    datos             JSONB NOT NULL,                -- partes + términos + snapshot del inmueble
    created_at        TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documentos_agente ON documentos_generados (agente_telefono);
