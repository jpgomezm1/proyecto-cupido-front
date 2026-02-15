-- Migration 017: AI Triage fields for feedback
-- Adds structured AI classification columns for quick admin triage

ALTER TABLE feedback ADD COLUMN IF NOT EXISTS ai_titulo VARCHAR(120);
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS ai_tipo VARCHAR(30);
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS ai_prioridad_sugerida VARCHAR(20);
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS ai_confianza SMALLINT;

CREATE INDEX IF NOT EXISTS idx_feedback_ai_tipo ON feedback(ai_tipo);
CREATE INDEX IF NOT EXISTS idx_feedback_prioridad ON feedback(prioridad);
