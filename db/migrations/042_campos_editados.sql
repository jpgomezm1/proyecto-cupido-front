-- ============================================================================
-- MIGRACIÓN 042: Ediciones del agente que sobreviven a la recaptura
-- Fecha: 2026-10-05
-- Descripción: El agente dueño (celular verificado) ahora edita título,
--   descripción, precio, cifras, ubicación, amenidades y fotos de sus inmuebles
--   desde Mis propiedades. Si el inmueble vino de Wasi/Lobbie y alguien vuelve a
--   compartir el link, el upsert de la captura sobrescribía todo: ahora respeta
--   los campos listados en `campos_editados`. Aditiva.
-- ============================================================================

ALTER TABLE propiedades
    ADD COLUMN IF NOT EXISTS campos_editados TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS editado_por_agente_at TIMESTAMPTZ;
