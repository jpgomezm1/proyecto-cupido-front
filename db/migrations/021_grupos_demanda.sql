-- =====================================================================
-- Migration 021: Grupos de Demanda + Tabla Pedidos
-- Agrega soporte para grupos de demanda (pedidos) separados de los
-- grupos de oferta (captación de propiedades).
-- =====================================================================

-- 1. Columna tipo en grupos_whatsapp (default 'oferta' = todos los existentes quedan igual)
ALTER TABLE grupos_whatsapp ADD COLUMN IF NOT EXISTS tipo VARCHAR(10) DEFAULT 'oferta' NOT NULL;

-- 2. Contadores para pedidos en grupos de demanda
ALTER TABLE grupos_whatsapp ADD COLUMN IF NOT EXISTS total_pedidos INTEGER DEFAULT 0;
ALTER TABLE grupos_whatsapp ADD COLUMN IF NOT EXISTS ultimo_pedido TIMESTAMP;

-- 3. Tabla de pedidos (demandas capturadas de grupos WhatsApp)
CREATE TABLE IF NOT EXISTS pedidos (
    id SERIAL PRIMARY KEY,
    grupo_id VARCHAR(100) NOT NULL,
    agente_telefono VARCHAR(30),
    agente_nombre VARCHAR(255),
    texto_pedido TEXT NOT NULL,
    mensaje_completo TEXT,
    fecha_captura TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pedidos_grupo ON pedidos(grupo_id);
CREATE INDEX IF NOT EXISTS idx_pedidos_fecha ON pedidos(fecha_captura DESC);
CREATE INDEX IF NOT EXISTS idx_pedidos_agente ON pedidos(agente_telefono);
