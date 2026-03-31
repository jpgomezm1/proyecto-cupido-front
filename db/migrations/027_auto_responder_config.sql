-- Config key-value para settings del sistema
CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Auto-responder habilitado por defecto
INSERT INTO system_config (key, value) VALUES ('auto_responder_enabled', 'true')
ON CONFLICT (key) DO NOTHING;
