-- Migration 011: Sistema de Alertas y Umbrales
-- Permite configurar umbrales de alertas para métricas del sistema
-- y mantener historial de alertas disparadas

-- ============================================
-- Tabla de umbrales configurables
-- ============================================
CREATE TABLE IF NOT EXISTS alert_thresholds (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(200),
    description TEXT,
    warning_threshold NUMERIC(10, 2),
    critical_threshold NUMERIC(10, 2),
    comparison_operator VARCHAR(10) DEFAULT '>=',  -- '>=', '<=', '>', '<', '=='
    unit VARCHAR(50),  -- 'percent', 'ms', 'usd', 'count'
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Comentarios para documentación
COMMENT ON TABLE alert_thresholds IS 'Umbrales configurables para alertas del sistema';
COMMENT ON COLUMN alert_thresholds.comparison_operator IS 'Operador para comparar: >= (valor alto es malo), <= (valor bajo es malo)';

-- ============================================
-- Umbrales por defecto
-- ============================================
INSERT INTO alert_thresholds (metric_name, display_name, description, warning_threshold, critical_threshold, comparison_operator, unit) VALUES
('error_rate_percent', 'Tasa de Errores', 'Porcentaje de errores en eventos del sistema', 5, 15, '>=', 'percent'),
('ai_response_time_p95_ms', 'Tiempo Respuesta IA P95', 'Percentil 95 del tiempo de respuesta de IA', 5000, 10000, '>=', 'ms'),
('ai_cost_daily_usd', 'Costo Diario IA', 'Costo diario estimado de uso de IA', 5, 15, '>=', 'usd'),
('db_connection_time_ms', 'Tiempo Conexión BD', 'Tiempo de conexión a PostgreSQL', 100, 500, '>=', 'ms'),
('bot_success_rate', 'Tasa Éxito Bot', 'Porcentaje de mensajes procesados exitosamente', 90, 80, '<=', 'percent'),
('search_success_rate', 'Tasa Éxito Búsquedas', 'Porcentaje de búsquedas exitosas', 90, 80, '<=', 'percent'),
('redis_latency_ms', 'Latencia Redis', 'Tiempo de respuesta de Redis', 50, 200, '>=', 'ms'),
('webhook_success_rate', 'Tasa Éxito Webhooks', 'Porcentaje de webhooks procesados correctamente', 95, 85, '<=', 'percent')
ON CONFLICT (metric_name) DO NOTHING;

-- ============================================
-- Historial de alertas disparadas
-- ============================================
CREATE TABLE IF NOT EXISTS alert_history (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    metric_value NUMERIC(10, 4),
    threshold_value NUMERIC(10, 4),
    severity VARCHAR(20) NOT NULL,  -- 'warning', 'critical'
    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    context JSONB DEFAULT '{}',
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by VARCHAR(100),
    acknowledged_at TIMESTAMP
);

-- Índices para consultas eficientes
CREATE INDEX IF NOT EXISTS idx_alert_history_triggered ON alert_history(triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_history_severity ON alert_history(severity);
CREATE INDEX IF NOT EXISTS idx_alert_history_metric ON alert_history(metric_name);
CREATE INDEX IF NOT EXISTS idx_alert_history_unresolved ON alert_history(resolved_at) WHERE resolved_at IS NULL;

-- Comentarios
COMMENT ON TABLE alert_history IS 'Historial de alertas disparadas por el sistema';
COMMENT ON COLUMN alert_history.context IS 'Contexto adicional en JSON (detalles del momento de la alerta)';

-- ============================================
-- Función para actualizar updated_at automáticamente
-- ============================================
CREATE OR REPLACE FUNCTION update_alert_thresholds_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger para auto-update de updated_at
DROP TRIGGER IF EXISTS trigger_alert_thresholds_updated ON alert_thresholds;
CREATE TRIGGER trigger_alert_thresholds_updated
    BEFORE UPDATE ON alert_thresholds
    FOR EACH ROW
    EXECUTE FUNCTION update_alert_thresholds_updated_at();
