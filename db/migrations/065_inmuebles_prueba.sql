-- 065: Inmuebles de prueba (cuentas con origen 'prueba_ui').
-- Sirven para probar Mis inmuebles, compradores, ficha y compartir sin que les aparezcan a los
-- agentes reales: las búsquedas, el Inventario, el mapa, las alertas de cruce, la Vitrina y los
-- comparables los excluyen; su dueño y el admin sí los ven. Los crea scripts/crear_inmuebles_prueba.py.
-- ADD COLUMN con DEFAULT constante no reescribe la tabla ni dispara trigger_actualizar_fecha.
-- Idempotente.

ALTER TABLE propiedades ADD COLUMN IF NOT EXISTS es_prueba BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_propiedades_es_prueba ON propiedades (id) WHERE es_prueba;
