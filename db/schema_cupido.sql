-- =============================================================================
-- PROYECTO CUPIDO - SCHEMA COMPLETO CON TRAZABILIDAD
-- Base de datos: Neon PostgreSQL
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. TABLA DE AGENTES INMOBILIARIOS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agentes (
    id SERIAL PRIMARY KEY,
    telefono VARCHAR(20) UNIQUE NOT NULL, -- +573001234567
    nombre VARCHAR(200),
    numero_whatsapp VARCHAR(20), -- Por si es diferente al teléfono principal
    activo BOOLEAN DEFAULT TRUE,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Metadata
    total_propiedades_captadas INTEGER DEFAULT 0,
    total_solicitudes_realizadas INTEGER DEFAULT 0,
    total_matches_logrados INTEGER DEFAULT 0,

    CONSTRAINT chk_telefono_formato CHECK (telefono ~ '^\+57[0-9]{10}$')
);

COMMENT ON TABLE agentes IS 'Almacena información de los agentes inmobiliarios del grupo Cupido';
COMMENT ON COLUMN agentes.telefono IS 'Número de teléfono en formato internacional +57...';
COMMENT ON COLUMN agentes.total_matches_logrados IS 'Cantidad de veces que sus propiedades fueron seleccionadas por otros agentes';

-- Índices
CREATE INDEX IF NOT EXISTS idx_agentes_telefono ON agentes(telefono);
CREATE INDEX IF NOT EXISTS idx_agentes_activo ON agentes(activo);

-- -----------------------------------------------------------------------------
-- 2. MODIFICAR TABLA PROPIEDADES (agregar campos para trazabilidad)
-- -----------------------------------------------------------------------------
-- Agregar columnas nuevas a la tabla propiedades existente
ALTER TABLE propiedades
ADD COLUMN IF NOT EXISTS agente_captador_id INTEGER REFERENCES agentes(id),
ADD COLUMN IF NOT EXISTS agente_captador_telefono VARCHAR(20),
ADD COLUMN IF NOT EXISTS mensaje_original_grupo TEXT,
ADD COLUMN IF NOT EXISTS origen VARCHAR(50) DEFAULT 'Pulppo', -- 'Pulppo', 'Wasi_Captado', 'Wasi_Manual'
ADD COLUMN IF NOT EXISTS grupo_origen VARCHAR(100), -- Identificador del grupo de WhatsApp
ADD COLUMN IF NOT EXISTS contacto_responsable VARCHAR(20); -- Teléfono del responsable (agente o +573183351733)

COMMENT ON COLUMN propiedades.agente_captador_id IS 'ID del agente que captó/publicó esta propiedad en el grupo';
COMMENT ON COLUMN propiedades.agente_captador_telefono IS 'Teléfono del agente que captó esta propiedad';
COMMENT ON COLUMN propiedades.mensaje_original_grupo IS 'Mensaje original del grupo cuando se captó la propiedad';
COMMENT ON COLUMN propiedades.origen IS 'Origen: Pulppo (scraping), Wasi_Captado (grupo), Wasi_Manual';
COMMENT ON COLUMN propiedades.contacto_responsable IS 'Teléfono del responsable: agente o +573183351733 para Pulppo';

-- Índices adicionales
CREATE INDEX IF NOT EXISTS idx_propiedades_agente_captador ON propiedades(agente_captador_id);
CREATE INDEX IF NOT EXISTS idx_propiedades_origen ON propiedades(origen);

-- -----------------------------------------------------------------------------
-- 3. TABLA DE SOLICITUDES DE MERCADO (búsquedas de agentes)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS solicitudes_mercado (
    id SERIAL PRIMARY KEY,
    agente_id INTEGER REFERENCES agentes(id),
    agente_telefono VARCHAR(20) NOT NULL,

    -- Query original
    query_original TEXT NOT NULL,
    fecha_solicitud TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Contexto
    origen VARCHAR(50) NOT NULL, -- 'Grupo', 'Chat_Privado'
    grupo_origen VARCHAR(100), -- Si vino de un grupo
    mensaje_id_whatsapp VARCHAR(200), -- ID del mensaje en WhatsApp

    -- Criterios extraídos por Claude
    criterios_extraidos JSONB, -- JSON con criterios de búsqueda

    -- Resultados
    total_propiedades_encontradas INTEGER DEFAULT 0,
    propiedades_ids INTEGER[], -- Array de IDs de propiedades mostradas

    -- Estado
    estado VARCHAR(50) DEFAULT 'Pendiente_Seleccion', -- 'Pendiente_Seleccion', 'Seleccionado', 'Sin_Seleccion', 'Expirada'
    fecha_cambio_estado TIMESTAMP,

    -- Metadata
    tiempo_respuesta_ms INTEGER, -- Tiempo que tardó la búsqueda
    activa BOOLEAN DEFAULT TRUE
);

COMMENT ON TABLE solicitudes_mercado IS 'Almacena todas las solicitudes de búsqueda de propiedades realizadas por agentes';
COMMENT ON COLUMN solicitudes_mercado.origen IS 'Si la solicitud vino del grupo o de un chat privado';
COMMENT ON COLUMN solicitudes_mercado.criterios_extraidos IS 'JSON con los criterios extraídos por Claude (ubicación, precio, habitaciones, etc)';
COMMENT ON COLUMN solicitudes_mercado.estado IS 'Estado de la solicitud: si el agente ya seleccionó propiedades o no';

-- Índices
CREATE INDEX IF NOT EXISTS idx_solicitudes_agente_id ON solicitudes_mercado(agente_id);
CREATE INDEX IF NOT EXISTS idx_solicitudes_agente_telefono ON solicitudes_mercado(agente_telefono);
CREATE INDEX IF NOT EXISTS idx_solicitudes_fecha ON solicitudes_mercado(fecha_solicitud DESC);
CREATE INDEX IF NOT EXISTS idx_solicitudes_estado ON solicitudes_mercado(estado);
CREATE INDEX IF NOT EXISTS idx_solicitudes_origen ON solicitudes_mercado(origen);

-- -----------------------------------------------------------------------------
-- 4. TABLA DE INTERACCIONES / MATCHES (cuando un agente selecciona una propiedad)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interacciones (
    id SERIAL PRIMARY KEY,

    -- Agente que busca (comprador potencial)
    agente_comprador_id INTEGER REFERENCES agentes(id),
    agente_comprador_telefono VARCHAR(20) NOT NULL,

    -- Propiedad de interés
    propiedad_id INTEGER REFERENCES propiedades(id) NOT NULL,
    solicitud_mercado_id INTEGER REFERENCES solicitudes_mercado(id),

    -- Agente dueño de la propiedad (si aplica)
    agente_vendedor_id INTEGER REFERENCES agentes(id),
    agente_vendedor_telefono VARCHAR(20),

    -- Fechas y estados
    fecha_seleccion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_contacto_compartido TIMESTAMP,
    fecha_notificacion_vendedor TIMESTAMP,

    -- Estado del proceso
    estado VARCHAR(50) DEFAULT 'Seleccionado',
    -- Estados: 'Seleccionado', 'Contacto_Compartido', 'Notificado_Vendedor', 'En_Proceso', 'Cerrado_Exitoso', 'Cerrado_Sin_Resultado'

    fecha_cambio_estado TIMESTAMP,
    notas_estado TEXT,

    -- Metadata
    tipo_propiedad_origen VARCHAR(50), -- 'Pulppo', 'Wasi_Captado'
    mensaje_contacto_enviado TEXT, -- El mensaje que se envió con el contacto

    activa BOOLEAN DEFAULT TRUE
);

COMMENT ON TABLE interacciones IS 'Registra cada vez que un agente selecciona una propiedad (match)';
COMMENT ON COLUMN interacciones.estado IS 'Estado del match: desde selección hasta cierre';
COMMENT ON COLUMN interacciones.tipo_propiedad_origen IS 'Si la propiedad era de Pulppo o captada por otro agente';
COMMENT ON COLUMN interacciones.mensaje_contacto_enviado IS 'El mensaje exacto que se envió al agente con el contacto';

-- Índices
CREATE INDEX IF NOT EXISTS idx_interacciones_agente_comprador ON interacciones(agente_comprador_id);
CREATE INDEX IF NOT EXISTS idx_interacciones_agente_vendedor ON interacciones(agente_vendedor_id);
CREATE INDEX IF NOT EXISTS idx_interacciones_propiedad ON interacciones(propiedad_id);
CREATE INDEX IF NOT EXISTS idx_interacciones_solicitud ON interacciones(solicitud_mercado_id);
CREATE INDEX IF NOT EXISTS idx_interacciones_estado ON interacciones(estado);
CREATE INDEX IF NOT EXISTS idx_interacciones_fecha_seleccion ON interacciones(fecha_seleccion DESC);

-- -----------------------------------------------------------------------------
-- 5. TABLA DE EVENTOS / LOG (para auditoría completa)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eventos_log (
    id SERIAL PRIMARY KEY,
    fecha_evento TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Tipo de evento
    tipo_evento VARCHAR(100) NOT NULL,
    -- 'Mensaje_Grupo', 'Mensaje_Privado', 'Propiedad_Captada', 'Solicitud_Mercado',
    -- 'Propiedad_Seleccionada', 'Contacto_Compartido', 'Notificacion_Enviada', etc.

    -- Actores involucrados
    agente_telefono VARCHAR(20),
    agente_id INTEGER REFERENCES agentes(id),

    -- Entidades relacionadas
    propiedad_id INTEGER REFERENCES propiedades(id),
    solicitud_id INTEGER REFERENCES solicitudes_mercado(id),
    interaccion_id INTEGER REFERENCES interacciones(id),

    -- Datos del evento
    datos_evento JSONB, -- JSON con toda la información relevante del evento
    mensaje_whatsapp TEXT,
    grupo_origen VARCHAR(100),

    -- Metadata
    resultado VARCHAR(50), -- 'Exitoso', 'Error', 'Ignorado'
    mensaje_error TEXT
);

COMMENT ON TABLE eventos_log IS 'Log completo de todos los eventos del sistema para auditoría';
COMMENT ON COLUMN eventos_log.tipo_evento IS 'Tipo de evento ocurrido en el sistema';
COMMENT ON COLUMN eventos_log.datos_evento IS 'JSON con información detallada del evento';

-- Índices
CREATE INDEX IF NOT EXISTS idx_eventos_fecha ON eventos_log(fecha_evento DESC);
CREATE INDEX IF NOT EXISTS idx_eventos_tipo ON eventos_log(tipo_evento);
CREATE INDEX IF NOT EXISTS idx_eventos_agente ON eventos_log(agente_telefono);
CREATE INDEX IF NOT EXISTS idx_eventos_resultado ON eventos_log(resultado);

-- -----------------------------------------------------------------------------
-- 6. TABLA DE CONFIGURACIÓN DEL SISTEMA
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS configuracion_sistema (
    id SERIAL PRIMARY KEY,
    clave VARCHAR(100) UNIQUE NOT NULL,
    valor TEXT,
    tipo_valor VARCHAR(50), -- 'string', 'number', 'boolean', 'json', 'phone'
    descripcion TEXT,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE configuracion_sistema IS 'Configuración del sistema Cupido';

-- Insertar configuraciones iniciales
INSERT INTO configuracion_sistema (clave, valor, tipo_valor, descripcion) VALUES
('contacto_pulppo', '+573183351733', 'phone', 'Teléfono de contacto para propiedades de Pulppo'),
('grupo_cupido_id', '', 'string', 'ID del grupo de WhatsApp de Cupido'),
('tiempo_expiracion_sesion_minutos', '60', 'number', 'Tiempo en minutos para expirar sesión de selección'),
('max_propiedades_por_busqueda', '5', 'number', 'Máximo de propiedades a mostrar por búsqueda'),
('notificaciones_activas', 'true', 'boolean', 'Si se envían notificaciones a agentes vendedores')
ON CONFLICT (clave) DO NOTHING;

-- Índice
CREATE INDEX IF NOT EXISTS idx_config_clave ON configuracion_sistema(clave);

-- -----------------------------------------------------------------------------
-- 7. TRIGGERS Y FUNCIONES
-- -----------------------------------------------------------------------------

-- Función para actualizar fecha_actualizacion en agentes
CREATE OR REPLACE FUNCTION actualizar_fecha_actualizacion_agentes()
RETURNS TRIGGER AS $$
BEGIN
    NEW.fecha_actualizacion = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_actualizar_fecha_agentes ON agentes;
CREATE TRIGGER trigger_actualizar_fecha_agentes
    BEFORE UPDATE ON agentes
    FOR EACH ROW
    EXECUTE FUNCTION actualizar_fecha_actualizacion_agentes();

-- Función para actualizar contadores en agentes cuando se crea una interacción
CREATE OR REPLACE FUNCTION actualizar_contadores_agente()
RETURNS TRIGGER AS $$
BEGIN
    -- Actualizar contador del agente vendedor (sus propiedades fueron seleccionadas)
    IF NEW.agente_vendedor_id IS NOT NULL THEN
        UPDATE agentes
        SET total_matches_logrados = total_matches_logrados + 1
        WHERE id = NEW.agente_vendedor_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_actualizar_contadores ON interacciones;
CREATE TRIGGER trigger_actualizar_contadores
    AFTER INSERT ON interacciones
    FOR EACH ROW
    EXECUTE FUNCTION actualizar_contadores_agente();

-- -----------------------------------------------------------------------------
-- 8. VISTAS ÚTILES
-- -----------------------------------------------------------------------------

-- Vista: Propiedades con información del agente captador
CREATE OR REPLACE VIEW v_propiedades_con_agente AS
SELECT
    p.*,
    a.nombre as agente_nombre,
    a.telefono as agente_telefono_contacto,
    a.numero_whatsapp as agente_whatsapp
FROM propiedades p
LEFT JOIN agentes a ON p.agente_captador_id = a.id
WHERE p.activa = TRUE;

-- Vista: Dashboard de agentes con estadísticas
CREATE OR REPLACE VIEW v_dashboard_agentes AS
SELECT
    a.id,
    a.telefono,
    a.nombre,
    a.activo,
    a.fecha_registro,
    a.total_propiedades_captadas,
    a.total_solicitudes_realizadas,
    a.total_matches_logrados,
    COUNT(DISTINCT p.id) as propiedades_activas,
    COUNT(DISTINCT i.id) as interacciones_activas
FROM agentes a
LEFT JOIN propiedades p ON a.id = p.agente_captador_id AND p.activa = TRUE
LEFT JOIN interacciones i ON a.id = i.agente_vendedor_id AND i.activa = TRUE
GROUP BY a.id, a.telefono, a.nombre, a.activo, a.fecha_registro,
         a.total_propiedades_captadas, a.total_solicitudes_realizadas, a.total_matches_logrados;

-- Vista: Interacciones completas con toda la información
CREATE OR REPLACE VIEW v_interacciones_completas AS
SELECT
    i.id,
    i.fecha_seleccion,
    i.estado,
    -- Agente comprador
    ac.telefono as comprador_telefono,
    ac.nombre as comprador_nombre,
    -- Agente vendedor
    av.telefono as vendedor_telefono,
    av.nombre as vendedor_nombre,
    -- Propiedad
    p.codigo_propiedad,
    p.titulo as propiedad_titulo,
    p.precio,
    p.ciudad,
    p.zona,
    p.origen as propiedad_origen,
    -- Solicitud
    s.query_original as solicitud_original,
    s.origen as solicitud_origen
FROM interacciones i
LEFT JOIN agentes ac ON i.agente_comprador_id = ac.id
LEFT JOIN agentes av ON i.agente_vendedor_id = av.id
LEFT JOIN propiedades p ON i.propiedad_id = p.id
LEFT JOIN solicitudes_mercado s ON i.solicitud_mercado_id = s.id
WHERE i.activa = TRUE;

-- Vista: Solicitudes con resultados
CREATE OR REPLACE VIEW v_solicitudes_con_resultados AS
SELECT
    s.id,
    s.fecha_solicitud,
    s.query_original,
    s.origen,
    s.estado,
    s.total_propiedades_encontradas,
    a.telefono as agente_telefono,
    a.nombre as agente_nombre,
    COUNT(i.id) as total_propiedades_seleccionadas
FROM solicitudes_mercado s
LEFT JOIN agentes a ON s.agente_id = a.id
LEFT JOIN interacciones i ON s.id = i.solicitud_mercado_id
GROUP BY s.id, s.fecha_solicitud, s.query_original, s.origen, s.estado,
         s.total_propiedades_encontradas, a.telefono, a.nombre;

-- =============================================================================
-- FIN DEL SCHEMA
-- =============================================================================

-- Mensajes de confirmación
DO $$
BEGIN
    RAISE NOTICE '✅ Schema Proyecto Cupido creado exitosamente';
    RAISE NOTICE '📊 Tablas: agentes, propiedades (modificada), solicitudes_mercado, interacciones, eventos_log, configuracion_sistema';
    RAISE NOTICE '📈 Vistas: v_propiedades_con_agente, v_dashboard_agentes, v_interacciones_completas, v_solicitudes_con_resultados';
    RAISE NOTICE '🎯 Sistema de trazabilidad completo activado';
END $$;
