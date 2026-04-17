-- Migration 030: ubicacion_aproximada
--
-- Los portales (Tu360/Pulppo, Wasi, Lobbie) rara vez publican la coordenada
-- exacta de la propiedad; normalmente entregan el centroide del barrio o
-- ciudad para proteger la dirección del vendedor. Este flag permite que el
-- frontend muestre el mapa con zoom ampliado y un disclaimer claro en lugar
-- de fingir un pin preciso.
--
-- Default TRUE: es la realidad estadística del inventario. Solo las
-- propiedades con coordenada colocada manualmente (manuallySet=true en Tu360)
-- deben pasar a FALSE explícitamente desde el scraper.

ALTER TABLE propiedades
    ADD COLUMN IF NOT EXISTS ubicacion_aproximada BOOLEAN DEFAULT TRUE;

COMMENT ON COLUMN propiedades.ubicacion_aproximada IS
    'TRUE cuando latitud/longitud son centroide de barrio o geocoded, no la ubicación exacta de la propiedad.';
