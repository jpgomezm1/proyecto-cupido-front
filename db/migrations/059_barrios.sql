-- 059: Catálogo canónico de barrios (municipio → comuna/zona → barrio).
--
-- Hasta ahora cada inmueble traía su "zona" como la escribió el agente (1.283
-- variantes) y la mitad no traía ninguna. barrios_service asigna a cada inmueble
-- (y a cada pedido) un barrio del catálogo, por su texto, su título o sus
-- coordenadas, y deja constancia de cómo lo hizo y con qué confianza.
--  - barrios: el catálogo. tipo: barrio | sector (agrupa barrios: "El Poblado") | vereda.
--    geojson: el polígono oficial cuando lo hay (Medellín); lat/lng: su centro.
--  - barrio_alias: cada forma de escribirlo → su barrio (barrio_id NULL = no es un lugar
--    o es solo el municipio). revisado = lo confirmó el admin.
-- Idempotente.

CREATE TABLE IF NOT EXISTS barrios (
    id SERIAL PRIMARY KEY,
    municipio VARCHAR(60) NOT NULL,
    municipio_clave VARCHAR(60) NOT NULL,
    comuna VARCHAR(80),
    nombre VARCHAR(120) NOT NULL,
    clave VARCHAR(140) NOT NULL,
    tipo VARCHAR(10) NOT NULL DEFAULT 'barrio' CHECK (tipo IN ('barrio', 'sector', 'vereda')),
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    geojson JSONB,
    fuente VARCHAR(12) NOT NULL DEFAULT 'ia',
    revisado BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipio_clave, clave)
);

CREATE TABLE IF NOT EXISTS barrio_alias (
    id SERIAL PRIMARY KEY,
    municipio_clave VARCHAR(60) NOT NULL DEFAULT '',   -- '' = vale en cualquier municipio
    alias_clave VARCHAR(140) NOT NULL,
    barrio_id INTEGER REFERENCES barrios(id) ON DELETE CASCADE,
    municipio VARCHAR(60),                              -- municipio canónico (corrige "El Poblado" como ciudad)
    tipo VARCHAR(12) NOT NULL,                          -- barrio | sector | vereda | municipio | no_es_lugar
    confianza REAL NOT NULL DEFAULT 0.5,
    usos INTEGER NOT NULL DEFAULT 0,
    fuente VARCHAR(10) NOT NULL DEFAULT 'ia',
    revisado BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (municipio_clave, alias_clave)
);
CREATE INDEX IF NOT EXISTS idx_barrio_alias_revisar ON barrio_alias(revisado, confianza) WHERE NOT revisado;

-- El barrio de cada inmueble va en su propia tabla: propiedades tiene un trigger que
-- cambia fecha_actualizacion en cada UPDATE, y reasignar barrios no debe tocarla.
CREATE TABLE IF NOT EXISTS propiedad_barrio (
    propiedad_id INTEGER PRIMARY KEY REFERENCES propiedades(id) ON DELETE CASCADE,
    barrio_id INTEGER REFERENCES barrios(id) ON DELETE SET NULL,
    municipio VARCHAR(60),
    fuente VARCHAR(12),            -- texto | titulo | coordenadas | poligono | manual
    confianza REAL,
    asignado_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_propiedad_barrio_barrio ON propiedad_barrio(barrio_id);

-- Límites de las comunas (OpenStreetMap, ODbL: "© OpenStreetMap contributors").
-- Con ellos se corrige la comuna de cada barrio por su centro y se pinta el mapa por comuna.
CREATE TABLE IF NOT EXISTS comunas (
    id SERIAL PRIMARY KEY,
    municipio VARCHAR(60) NOT NULL,
    municipio_clave VARCHAR(60) NOT NULL,
    nombre VARCHAR(80) NOT NULL,       -- "14 - El Poblado", igual que barrios.comuna
    geojson JSONB NOT NULL,
    fuente VARCHAR(12) NOT NULL DEFAULT 'osm',
    UNIQUE (municipio_clave, nombre)
);

ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS barrio_ids INTEGER[];
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS barrio_at TIMESTAMPTZ;
