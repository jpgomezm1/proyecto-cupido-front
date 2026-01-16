-- ============================================================================
-- Migration 010: AI Usage Tracking
-- Tracks token consumption, costs, and performance metrics for all AI models
-- ============================================================================

-- Main AI usage tracking table
CREATE TABLE IF NOT EXISTS ai_usage_log (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Provider and model identification
    provider VARCHAR(50) NOT NULL,           -- 'anthropic' | 'openai'
    model VARCHAR(100) NOT NULL,             -- e.g., 'claude-3-5-sonnet-20241022'
    usage_type VARCHAR(100) NOT NULL,        -- e.g., 'search_extraction', 'transcription'
    application VARCHAR(50) NOT NULL,        -- 'cupido_backend' | 'tu360_frontend'
    function_name VARCHAR(200),              -- Source function/method name

    -- Token usage (for text models)
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,

    -- For audio transcription (Whisper)
    audio_duration_seconds NUMERIC(10, 2),

    -- Cost estimation (in USD)
    estimated_cost_usd NUMERIC(10, 6),

    -- Performance metrics
    response_time_ms INTEGER,

    -- Status
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,

    -- Context (flexible JSONB for user_id, property_id, conversation_id, etc.)
    context JSONB DEFAULT '{}',

    -- Constraints
    CONSTRAINT valid_provider CHECK (provider IN ('anthropic', 'openai')),
    CONSTRAINT valid_application CHECK (application IN ('cupido_backend', 'tu360_frontend'))
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_ai_usage_created_at ON ai_usage_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_usage_provider ON ai_usage_log(provider);
CREATE INDEX IF NOT EXISTS idx_ai_usage_model ON ai_usage_log(model);
CREATE INDEX IF NOT EXISTS idx_ai_usage_usage_type ON ai_usage_log(usage_type);
CREATE INDEX IF NOT EXISTS idx_ai_usage_application ON ai_usage_log(application);
CREATE INDEX IF NOT EXISTS idx_ai_usage_success ON ai_usage_log(success);

-- Composite index for date-based analytics
CREATE INDEX IF NOT EXISTS idx_ai_usage_date ON ai_usage_log(DATE(created_at));

-- GIN index for JSONB context queries
CREATE INDEX IF NOT EXISTS idx_ai_usage_context ON ai_usage_log USING GIN (context);

-- Daily aggregation view for dashboard
CREATE OR REPLACE VIEW v_ai_usage_daily_summary AS
SELECT
    DATE(created_at) as date,
    provider,
    model,
    usage_type,
    application,
    COUNT(*) as total_calls,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_calls,
    SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed_calls,
    SUM(COALESCE(input_tokens, 0)) as total_input_tokens,
    SUM(COALESCE(output_tokens, 0)) as total_output_tokens,
    SUM(COALESCE(total_tokens, 0)) as total_tokens,
    SUM(COALESCE(estimated_cost_usd, 0)) as total_cost_usd,
    AVG(response_time_ms)::INTEGER as avg_response_time_ms,
    SUM(COALESCE(audio_duration_seconds, 0)) as total_audio_seconds
FROM ai_usage_log
GROUP BY DATE(created_at), provider, model, usage_type, application
ORDER BY date DESC, total_calls DESC;

-- Monthly cost summary view
CREATE OR REPLACE VIEW v_ai_usage_monthly_costs AS
SELECT
    DATE_TRUNC('month', created_at) as month,
    provider,
    model,
    SUM(COALESCE(estimated_cost_usd, 0)) as total_cost_usd,
    SUM(COALESCE(total_tokens, 0)) as total_tokens,
    COUNT(*) as total_calls,
    AVG(response_time_ms)::INTEGER as avg_response_time_ms
FROM ai_usage_log
WHERE success = TRUE
GROUP BY DATE_TRUNC('month', created_at), provider, model
ORDER BY month DESC, total_cost_usd DESC;

-- Comments for documentation
COMMENT ON TABLE ai_usage_log IS 'Tracks all AI model usage (tokens, costs, performance) across Python backend and TypeScript frontend';
COMMENT ON COLUMN ai_usage_log.provider IS 'AI provider: anthropic or openai';
COMMENT ON COLUMN ai_usage_log.model IS 'Model identifier (e.g., claude-3-5-sonnet-20241022, gpt-4o-mini-transcribe)';
COMMENT ON COLUMN ai_usage_log.usage_type IS 'Type of AI usage: search_extraction, image_analysis, transcription, embeddings, property_chat, etc.';
COMMENT ON COLUMN ai_usage_log.application IS 'Source application: cupido_backend or tu360_frontend';
COMMENT ON COLUMN ai_usage_log.context IS 'Flexible JSONB for additional context: user_id, conversation_id, property_id, query, etc.';
COMMENT ON COLUMN ai_usage_log.audio_duration_seconds IS 'Duration in seconds for audio transcription (Whisper charges by duration)';
COMMENT ON COLUMN ai_usage_log.estimated_cost_usd IS 'Estimated cost in USD based on model pricing';
