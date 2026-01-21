-- ============================================================================
-- Migration 013: Share Analytics
-- Tracks views, clicks, and engagement on shared property links
-- ============================================================================

-- Tabla principal de eventos de shares
CREATE TABLE IF NOT EXISTS share_events (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Identificacion del share
    share_id VARCHAR(50) NOT NULL,
    selection_id INTEGER REFERENCES shared_property_selections(id) ON DELETE CASCADE,

    -- Tipo de evento
    event_type VARCHAR(50) NOT NULL,
    -- Valores: 'share_viewed', 'property_clicked', 'whatsapp_clicked', 'phone_clicked'

    -- Contexto del share
    share_type VARCHAR(20),  -- 'agente' | 'cliente'
    property_count INTEGER,
    creator_user_id INTEGER REFERENCES chat_users(id) ON DELETE SET NULL,

    -- Tracking de visitantes (anonimo)
    visitor_id VARCHAR(64),  -- Hash anonimo del fingerprint
    session_id VARCHAR(64),

    -- Propiedad clickeada (opcional)
    property_id INTEGER REFERENCES propiedades(id) ON DELETE SET NULL,

    -- Info de dispositivo (sin PII)
    device_type VARCHAR(20),  -- 'mobile' | 'desktop' | 'tablet'
    browser VARCHAR(50),
    os VARCHAR(50),
    referrer_domain VARCHAR(255),

    -- UTM tracking
    utm_source VARCHAR(100),
    utm_medium VARCHAR(100),
    utm_campaign VARCHAR(100),

    -- Datos flexibles
    event_data JSONB DEFAULT '{}'
);

-- Indices para queries eficientes
CREATE INDEX IF NOT EXISTS idx_share_events_share_id ON share_events(share_id);
CREATE INDEX IF NOT EXISTS idx_share_events_created_at ON share_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_share_events_event_type ON share_events(event_type);
CREATE INDEX IF NOT EXISTS idx_share_events_visitor ON share_events(visitor_id);
CREATE INDEX IF NOT EXISTS idx_share_events_creator ON share_events(creator_user_id);
CREATE INDEX IF NOT EXISTS idx_share_events_selection ON share_events(selection_id);

-- Indice compuesto para deduplicacion de views por sesion
CREATE INDEX IF NOT EXISTS idx_share_events_dedup ON share_events(share_id, session_id, event_type);

-- Columnas adicionales en shared_property_selections para cache de stats
ALTER TABLE shared_property_selections
ADD COLUMN IF NOT EXISTS share_type VARCHAR(20) DEFAULT 'agente';

ALTER TABLE shared_property_selections
ADD COLUMN IF NOT EXISTS unique_visitors INTEGER DEFAULT 0;

ALTER TABLE shared_property_selections
ADD COLUMN IF NOT EXISTS total_clicks INTEGER DEFAULT 0;

ALTER TABLE shared_property_selections
ADD COLUMN IF NOT EXISTS whatsapp_clicks INTEGER DEFAULT 0;

-- Vista materializada para estadisticas diarias (opcional, para queries rapidos)
CREATE OR REPLACE VIEW v_share_analytics_daily AS
SELECT
    DATE(created_at) as date,
    event_type,
    share_type,
    COUNT(*) as total_events,
    COUNT(DISTINCT share_id) as unique_shares,
    COUNT(DISTINCT visitor_id) as unique_visitors,
    COUNT(DISTINCT session_id) as unique_sessions
FROM share_events
GROUP BY DATE(created_at), event_type, share_type
ORDER BY date DESC;

-- Vista para performance por share
CREATE OR REPLACE VIEW v_share_performance AS
SELECT
    se.share_id,
    sps.user_id as creator_user_id,
    cu.nombre as creator_name,
    sps.created_at as share_created_at,
    COUNT(*) FILTER (WHERE se.event_type = 'share_viewed') as total_views,
    COUNT(DISTINCT se.visitor_id) FILTER (WHERE se.event_type = 'share_viewed') as unique_visitors,
    COUNT(*) FILTER (WHERE se.event_type = 'property_clicked') as property_clicks,
    COUNT(*) FILTER (WHERE se.event_type = 'whatsapp_clicked') as whatsapp_clicks,
    COUNT(*) FILTER (WHERE se.event_type = 'phone_clicked') as phone_clicks,
    array_length(sps.property_ids, 1) as property_count
FROM share_events se
JOIN shared_property_selections sps ON se.share_id = sps.share_id
LEFT JOIN chat_users cu ON sps.user_id = cu.id
GROUP BY se.share_id, sps.user_id, cu.nombre, sps.created_at, sps.property_ids;

-- Comentarios para documentacion
COMMENT ON TABLE share_events IS 'Tracks all events on shared property links (views, clicks, conversions)';
COMMENT ON COLUMN share_events.event_type IS 'Type of event: share_viewed, property_clicked, whatsapp_clicked, phone_clicked';
COMMENT ON COLUMN share_events.visitor_id IS 'Anonymous hash of browser fingerprint (no PII)';
COMMENT ON COLUMN share_events.session_id IS 'Unique session identifier for deduplication';
COMMENT ON COLUMN share_events.device_type IS 'Device category: mobile, desktop, tablet';
