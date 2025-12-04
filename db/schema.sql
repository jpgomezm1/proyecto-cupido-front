-- Schema para almacenar propiedades inmobiliarias
-- Base de datos: Neon PostgreSQL

-- Eliminar tabla si existe (solo para desarrollo)
-- DROP TABLE IF EXISTS propiedades;

-- Crear tabla de propiedades
CREATE TABLE IF NOT EXISTS propiedades (
    -- Identificadores
    id SERIAL PRIMARY KEY,
    codigo_propiedad VARCHAR(50) UNIQUE NOT NULL,
    fuente VARCHAR(50) NOT NULL, -- 'Wasi', 'Fincaraiz', etc.
    url TEXT NOT NULL,

    -- Información básica
    titulo TEXT,
    precio BIGINT,
    precio_texto VARCHAR(100),
    tipo_propiedad VARCHAR(50),
    estado VARCHAR(50),

    -- Ubicación
    pais VARCHAR(100),
    departamento VARCHAR(100),
    ciudad VARCHAR(100),
    zona VARCHAR(200),
    direccion_completa TEXT,
    latitud DECIMAL(10, 8),
    longitud DECIMAL(11, 8),

    -- Características físicas
    area_construida DECIMAL(10, 2),
    habitaciones INTEGER,
    banos INTEGER,
    parqueaderos INTEGER,
    estrato INTEGER,
    piso INTEGER,
    ano_construccion INTEGER,
    caracteristicas_adicionales TEXT,

    -- Costos
    administracion INTEGER,
    predial INTEGER,

    -- Amenidades
    amenidades_internas TEXT,
    amenidades_externas TEXT,
    total_amenidades INTEGER,

    -- Contacto
    asesor VARCHAR(200),
    telefono VARCHAR(50),
    inmobiliaria VARCHAR(200),

    -- Imágenes
    imagenes_urls TEXT, -- URLs separadas por |
    total_imagenes INTEGER,
    imagen_principal TEXT,
    imagenes_hd_count INTEGER,
    imagenes_thumb_count INTEGER,

    -- Descripción
    descripcion TEXT,
    descripcion_length INTEGER,

    -- Metadata
    fecha_extraccion TIMESTAMP NOT NULL,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    activa BOOLEAN DEFAULT TRUE
);

-- Índices para mejorar el rendimiento
CREATE INDEX IF NOT EXISTS idx_propiedades_codigo ON propiedades(codigo_propiedad);
CREATE INDEX IF NOT EXISTS idx_propiedades_fuente ON propiedades(fuente);
CREATE INDEX IF NOT EXISTS idx_propiedades_ciudad ON propiedades(ciudad);
CREATE INDEX IF NOT EXISTS idx_propiedades_zona ON propiedades(zona);
CREATE INDEX IF NOT EXISTS idx_propiedades_precio ON propiedades(precio);
CREATE INDEX IF NOT EXISTS idx_propiedades_tipo ON propiedades(tipo_propiedad);
CREATE INDEX IF NOT EXISTS idx_propiedades_activa ON propiedades(activa);
CREATE INDEX IF NOT EXISTS idx_propiedades_fecha_creacion ON propiedades(fecha_creacion);

-- Índice geoespacial para búsquedas por ubicación
CREATE INDEX IF NOT EXISTS idx_propiedades_ubicacion ON propiedades(latitud, longitud);

-- Función para actualizar fecha_actualizacion automáticamente
CREATE OR REPLACE FUNCTION actualizar_fecha_actualizacion()
RETURNS TRIGGER AS $$
BEGIN
    NEW.fecha_actualizacion = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger para actualizar fecha_actualizacion
DROP TRIGGER IF EXISTS trigger_actualizar_fecha ON propiedades;
CREATE TRIGGER trigger_actualizar_fecha
    BEFORE UPDATE ON propiedades
    FOR EACH ROW
    EXECUTE FUNCTION actualizar_fecha_actualizacion();

-- Comentarios en la tabla
COMMENT ON TABLE propiedades IS 'Almacena información de propiedades inmobiliarias scrapeadas de diferentes fuentes';
COMMENT ON COLUMN propiedades.fuente IS 'Fuente de la propiedad: Wasi, Fincaraiz, Properati, etc.';
COMMENT ON COLUMN propiedades.codigo_propiedad IS 'Código único de la propiedad en la fuente';
COMMENT ON COLUMN propiedades.activa IS 'Indica si la propiedad sigue activa/disponible';
COMMENT ON COLUMN propiedades.imagenes_urls IS 'URLs de imágenes separadas por |';
