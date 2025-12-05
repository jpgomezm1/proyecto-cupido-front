-- ============================================
-- Migration 004: Módulo de Deals/Solicitudes
-- ============================================
-- Sistema de trazabilidad de deals inmobiliarios
-- Conecta propiedades (oferta) con compradores (demanda)
-- ============================================

-- 1. Tabla de contactos/compradores potenciales
CREATE TABLE IF NOT EXISTS contactos (
    id SERIAL PRIMARY KEY,

    -- Información básica
    nombre VARCHAR(200) NOT NULL,
    telefono VARCHAR(20) NOT NULL,
    email VARCHAR(200),

    -- Origen del contacto
    origen VARCHAR(50) DEFAULT 'manual',  -- 'whatsapp', 'manual', 'web', 'referido'
    fecha_primer_contacto TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Preferencias de búsqueda (para matching futuro)
    preferencias JSONB,  -- {tipo, ubicaciones, precio_min, precio_max, habitaciones, etc}

    -- Metadata
    notas TEXT,
    activo BOOLEAN DEFAULT TRUE,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(telefono)
);

-- 2. Tabla principal de deals
CREATE TABLE IF NOT EXISTS deals (
    id SERIAL PRIMARY KEY,

    -- Código único del deal (para referencia)
    codigo VARCHAR(20) UNIQUE NOT NULL,

    -- Relaciones principales
    propiedad_id INTEGER NOT NULL REFERENCES propiedades(id),
    contacto_id INTEGER NOT NULL REFERENCES contactos(id),

    -- Agentes involucrados
    agente_vendedor_telefono VARCHAR(20),  -- Quien captó la propiedad
    agente_comprador_telefono VARCHAR(20), -- Quien trae al comprador

    -- Estado del deal (pipeline)
    estado VARCHAR(30) DEFAULT 'lead',
    -- Estados: lead, contactado, visita_agendada, visita_realizada,
    --          negociando, documentacion, cierre, ganado, perdido

    -- Fechas de transición
    fecha_lead TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_contactado TIMESTAMP,
    fecha_visita_agendada TIMESTAMP,
    fecha_visita_realizada TIMESTAMP,
    fecha_negociando TIMESTAMP,
    fecha_documentacion TIMESTAMP,
    fecha_cierre TIMESTAMP,
    fecha_resultado TIMESTAMP,

    -- Información del deal
    precio_negociado NUMERIC(15,2),  -- Puede diferir del precio de lista
    motivo_perdida VARCHAR(200),     -- Si se pierde, por qué

    -- Comisiones
    tipo_comision VARCHAR(20) DEFAULT 'matching',  -- 'captacion' (1.5%) o 'matching' (0.5%)
    porcentaje_comision DECIMAL(4,2),  -- 0.50 o 1.50
    valor_comision NUMERIC(15,2),      -- Calculado
    comision_pagada BOOLEAN DEFAULT FALSE,
    fecha_pago_comision TIMESTAMP,

    -- Origen del deal
    origen VARCHAR(50) DEFAULT 'manual',  -- 'whatsapp_auto', 'manual', 'web'
    mensaje_origen TEXT,  -- Mensaje original de WhatsApp si aplica

    -- Metadata
    prioridad VARCHAR(10) DEFAULT 'media',  -- 'alta', 'media', 'baja'
    notas TEXT,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    creado_por VARCHAR(100)  -- Usuario que creó el deal
);

-- 3. Tabla de actividades/historial del deal
CREATE TABLE IF NOT EXISTS deal_actividades (
    id SERIAL PRIMARY KEY,
    deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,

    -- Tipo de actividad
    tipo VARCHAR(50) NOT NULL,
    -- Tipos: estado_cambio, nota, llamada, mensaje, visita, documento, pago

    -- Detalles
    descripcion TEXT NOT NULL,
    estado_anterior VARCHAR(30),
    estado_nuevo VARCHAR(30),

    -- Metadata
    usuario VARCHAR(100),
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB  -- Datos adicionales según el tipo
);

-- 4. Tabla de documentos del deal
CREATE TABLE IF NOT EXISTS deal_documentos (
    id SERIAL PRIMARY KEY,
    deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,

    nombre VARCHAR(200) NOT NULL,
    tipo VARCHAR(50),  -- 'promesa', 'escritura', 'paz_y_salvo', 'otro'
    url TEXT,

    fecha_subida TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    subido_por VARCHAR(100)
);

-- 5. Índices para búsquedas frecuentes
CREATE INDEX IF NOT EXISTS idx_deals_estado ON deals(estado);
CREATE INDEX IF NOT EXISTS idx_deals_propiedad ON deals(propiedad_id);
CREATE INDEX IF NOT EXISTS idx_deals_contacto ON deals(contacto_id);
CREATE INDEX IF NOT EXISTS idx_deals_fecha ON deals(fecha_creacion DESC);
CREATE INDEX IF NOT EXISTS idx_deals_agente_vendedor ON deals(agente_vendedor_telefono);
CREATE INDEX IF NOT EXISTS idx_deals_agente_comprador ON deals(agente_comprador_telefono);
CREATE INDEX IF NOT EXISTS idx_deal_actividades_deal ON deal_actividades(deal_id);
CREATE INDEX IF NOT EXISTS idx_contactos_telefono ON contactos(telefono);

-- 6. Función para generar código único de deal
CREATE OR REPLACE FUNCTION generate_deal_code()
RETURNS TRIGGER AS $$
BEGIN
    NEW.codigo := 'DEAL-' || TO_CHAR(NOW(), 'YYMM') || '-' || LPAD(NEW.id::TEXT, 4, '0');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger para generar código automáticamente
DROP TRIGGER IF EXISTS trigger_generate_deal_code ON deals;
CREATE TRIGGER trigger_generate_deal_code
    BEFORE INSERT ON deals
    FOR EACH ROW
    WHEN (NEW.codigo IS NULL OR NEW.codigo = '')
    EXECUTE FUNCTION generate_deal_code();

-- 7. Función para calcular comisión automáticamente
CREATE OR REPLACE FUNCTION calculate_deal_commission()
RETURNS TRIGGER AS $$
DECLARE
    propiedad_fuente VARCHAR(50);
    precio NUMERIC(15,2);
BEGIN
    -- Obtener fuente de la propiedad y precio
    SELECT p.fuente, COALESCE(NEW.precio_negociado, p.precio)
    INTO propiedad_fuente, precio
    FROM propiedades p
    WHERE p.id = NEW.propiedad_id;

    -- Determinar tipo de comisión basado en la fuente
    IF propiedad_fuente IN ('Wasi_Captado', 'Tu360_Captado') THEN
        NEW.tipo_comision := 'captacion';
        NEW.porcentaje_comision := 1.50;
    ELSE
        NEW.tipo_comision := 'matching';
        NEW.porcentaje_comision := 0.50;
    END IF;

    -- Calcular valor de comisión
    NEW.valor_comision := precio * (NEW.porcentaje_comision / 100);

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger para calcular comisión
DROP TRIGGER IF EXISTS trigger_calculate_commission ON deals;
CREATE TRIGGER trigger_calculate_commission
    BEFORE INSERT OR UPDATE OF propiedad_id, precio_negociado ON deals
    FOR EACH ROW
    EXECUTE FUNCTION calculate_deal_commission();

-- 8. Función para actualizar fecha de actualización
CREATE OR REPLACE FUNCTION update_deal_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.fecha_actualizacion := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_deal_timestamp ON deals;
CREATE TRIGGER trigger_update_deal_timestamp
    BEFORE UPDATE ON deals
    FOR EACH ROW
    EXECUTE FUNCTION update_deal_timestamp();

-- 9. Vista de deals con información completa
CREATE OR REPLACE VIEW v_deals_completos AS
SELECT
    d.*,
    -- Info de propiedad
    p.titulo as propiedad_titulo,
    p.precio as propiedad_precio,
    p.tipo_propiedad,
    p.ciudad as propiedad_ciudad,
    p.zona as propiedad_zona,
    p.imagen_principal as propiedad_imagen,
    p.fuente as propiedad_fuente,
    p.habitaciones,
    p.area_construida,
    -- Info de contacto
    c.nombre as contacto_nombre,
    c.telefono as contacto_telefono,
    c.email as contacto_email,
    -- Info de agente vendedor
    av.nombre as agente_vendedor_nombre,
    -- Info de agente comprador
    ac.nombre as agente_comprador_nombre,
    -- Días en estado actual
    EXTRACT(DAY FROM NOW() - d.fecha_actualizacion)::INTEGER as dias_en_estado,
    -- Días totales
    EXTRACT(DAY FROM NOW() - d.fecha_creacion)::INTEGER as dias_totales
FROM deals d
JOIN propiedades p ON p.id = d.propiedad_id
JOIN contactos c ON c.id = d.contacto_id
LEFT JOIN agentes av ON av.telefono = d.agente_vendedor_telefono
LEFT JOIN agentes ac ON ac.telefono = d.agente_comprador_telefono;

-- 10. Vista de métricas de pipeline
CREATE OR REPLACE VIEW v_deals_pipeline_stats AS
SELECT
    estado,
    COUNT(*) as total,
    SUM(COALESCE(precio_negociado, (SELECT precio FROM propiedades WHERE id = deals.propiedad_id))) as valor_total,
    SUM(valor_comision) as comision_potencial,
    AVG(EXTRACT(DAY FROM NOW() - fecha_creacion))::INTEGER as dias_promedio
FROM deals
WHERE estado NOT IN ('ganado', 'perdido')
GROUP BY estado
ORDER BY
    CASE estado
        WHEN 'lead' THEN 1
        WHEN 'contactado' THEN 2
        WHEN 'visita_agendada' THEN 3
        WHEN 'visita_realizada' THEN 4
        WHEN 'negociando' THEN 5
        WHEN 'documentacion' THEN 6
        WHEN 'cierre' THEN 7
    END;

-- 11. Vista de comisiones
CREATE OR REPLACE VIEW v_comisiones AS
SELECT
    d.id as deal_id,
    d.codigo,
    d.estado,
    p.titulo as propiedad,
    c.nombre as comprador,
    d.tipo_comision,
    d.porcentaje_comision,
    COALESCE(d.precio_negociado, p.precio) as precio_venta,
    d.valor_comision,
    d.comision_pagada,
    d.fecha_pago_comision,
    d.fecha_creacion
FROM deals d
JOIN propiedades p ON p.id = d.propiedad_id
JOIN contactos c ON c.id = d.contacto_id
WHERE d.estado = 'ganado'
ORDER BY d.fecha_resultado DESC;

-- Comentarios
COMMENT ON TABLE deals IS 'Deals/solicitudes que conectan propiedades con compradores';
COMMENT ON TABLE contactos IS 'Compradores potenciales y sus datos de contacto';
COMMENT ON TABLE deal_actividades IS 'Historial de actividades y cambios en cada deal';
COMMENT ON VIEW v_deals_completos IS 'Vista con toda la información del deal expandida';
COMMENT ON VIEW v_deals_pipeline_stats IS 'Estadísticas del pipeline de ventas';
