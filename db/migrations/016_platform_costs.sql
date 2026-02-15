-- Migration 016: Platform Cost Definitions
-- Tabla para definir costos recurrentes de plataforma
-- Los costos se "causan solos" — se computan on-the-fly revisando active_from/active_until

CREATE TABLE IF NOT EXISTS platform_cost_definitions (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    service_name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL DEFAULT 'infrastructure',
    description TEXT,
    monthly_cost_usd NUMERIC(10, 2) NOT NULL,
    billing_cycle VARCHAR(20) NOT NULL DEFAULT 'monthly',
    active_from DATE NOT NULL DEFAULT CURRENT_DATE,
    active_until DATE,
    url VARCHAR(500),
    notes TEXT,
    CONSTRAINT valid_category CHECK (category IN (
        'messaging', 'infrastructure', 'database', 'monitoring', 'ai_api', 'other'
    )),
    CONSTRAINT valid_billing_cycle CHECK (billing_cycle IN ('monthly', 'annual')),
    CONSTRAINT valid_cost CHECK (monthly_cost_usd >= 0),
    CONSTRAINT valid_date_range CHECK (active_until IS NULL OR active_until >= active_from)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_platform_costs_active_range ON platform_cost_definitions (active_from, active_until);
CREATE INDEX IF NOT EXISTS idx_platform_costs_category ON platform_cost_definitions (category);
CREATE INDEX IF NOT EXISTS idx_platform_costs_service ON platform_cost_definitions (service_name);

-- Seed data: costos reales de la plataforma
INSERT INTO platform_cost_definitions (service_name, category, description, monthly_cost_usd, billing_cycle, active_from, url)
VALUES
    ('UltraMSG', 'messaging', 'API de WhatsApp para envio y recepcion de mensajes', 39.00, 'monthly', '2026-01-16', 'https://ultramsg.com'),
    ('Heroku Dynos', 'infrastructure', '2x Standard-1X (web + worker) con New Relic agent', 50.00, 'monthly', '2026-01-16', 'https://heroku.com'),
    ('Heroku Redis', 'infrastructure', 'Redis Mini para rate limiting y colas', 3.00, 'monthly', '2026-01-16', 'https://heroku.com')
ON CONFLICT DO NOTHING;
