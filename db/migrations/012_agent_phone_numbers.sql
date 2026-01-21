-- Migration: 012_agent_phone_numbers
-- Description: Add telefono field to chat_users and user_id to shared_property_selections
-- Purpose: Allow dynamic phone numbers for agents in shared property links

-- ============================================================================
-- 1. Add telefono column to chat_users
-- ============================================================================

ALTER TABLE chat_users
ADD COLUMN IF NOT EXISTS telefono VARCHAR(20);

COMMENT ON COLUMN chat_users.telefono IS 'Telefono con codigo de pais (+573XXXXXXXXX)';

-- ============================================================================
-- 2. Add user_id to shared_property_selections to track who created the share
-- ============================================================================

ALTER TABLE shared_property_selections
ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES chat_users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_shared_selections_user ON shared_property_selections(user_id);

-- ============================================================================
-- 3. Assign placeholder phone to existing users (admin should replace later)
-- ============================================================================

UPDATE chat_users
SET telefono = '+57300000' || LPAD(id::text, 4, '0')
WHERE telefono IS NULL;

-- ============================================================================
-- Verification query (run after migration)
-- ============================================================================
-- SELECT id, email, nombre, telefono FROM chat_users;
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'shared_property_selections' AND column_name = 'user_id';
