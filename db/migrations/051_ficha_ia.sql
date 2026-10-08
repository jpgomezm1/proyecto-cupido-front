-- 051: ficha estructurada de cada inmueble, completada con IA.
--
-- Más de la mitad del inventario activo llega sin tipo, zona o habitaciones en
-- columnas (los portales lo dejan en el título, la descripción o el link). Esta
-- tabla guarda la ficha normalizada que usa el buscador, sin tocar los datos
-- originales de `propiedades`: el buscador lee COALESCE(original, ficha).
--
-- `caracteristicas` usa un vocabulario controlado (ver ficha_service.CARACTERISTICAS)
-- para poder filtrar y puntuar preferencias ("terraza", "vista", "estudio"…).
-- `fuente_hash` permite rehacer la ficha cuando cambia el texto o el precio.

CREATE TABLE IF NOT EXISTS propiedades_ficha (
    propiedad_id     INTEGER PRIMARY KEY REFERENCES propiedades(id) ON DELETE CASCADE,
    tipo             TEXT,
    negocio          TEXT,
    barrio           TEXT,
    ciudad           TEXT,
    habitaciones     SMALLINT,
    banos            SMALLINT,
    parqueaderos     SMALLINT,
    area_m2          NUMERIC,
    area_lote_m2     NUMERIC,
    piso             SMALLINT,
    estrato          SMALLINT,
    ano_construccion SMALLINT,
    administracion   BIGINT,
    estado           TEXT,
    caracteristicas  TEXT[] NOT NULL DEFAULT '{}',
    resumen          TEXT,
    fuente_hash      TEXT NOT NULL,
    modelo           TEXT,
    version          SMALLINT NOT NULL DEFAULT 1,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ficha_tipo ON propiedades_ficha (tipo);
CREATE INDEX IF NOT EXISTS idx_ficha_ciudad_barrio ON propiedades_ficha (ciudad, barrio);
CREATE INDEX IF NOT EXISTS idx_ficha_caracteristicas ON propiedades_ficha USING gin (caracteristicas);
