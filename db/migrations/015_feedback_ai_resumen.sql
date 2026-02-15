-- Migration 015: Add AI summary column to feedback table
-- The AI processes feedback text + images to generate a detailed summary

ALTER TABLE feedback ADD COLUMN IF NOT EXISTS ai_resumen TEXT;

COMMENT ON COLUMN feedback.ai_resumen IS 'AI-generated detailed summary of the feedback content and images';
