-- ============================================================================
-- MIGRACIÓN 038: Cuentas pre-cargadas por captador (C1 · gestión de acceso)
-- Fecha: 2026-07-24
-- Descripción: Marca las cuentas de chat_users provisionadas por Fynder
--   (origen='provision') y agrega el control de "acceso entregado" para que
--   Matías cheque a quién ya le pasó las credenciales. Aditiva.
-- ============================================================================

ALTER TABLE chat_users
    ADD COLUMN IF NOT EXISTS origen VARCHAR(30),                    -- 'provision' = cuenta pre-cargada
    ADD COLUMN IF NOT EXISTS acceso_entregado BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS acceso_entregado_at TIMESTAMP;

COMMENT ON COLUMN chat_users.origen IS 'Procedencia de la cuenta: provision = pre-cargada por captador (C1)';
COMMENT ON COLUMN chat_users.acceso_entregado IS 'True si Matías ya entregó las credenciales al agente';

CREATE INDEX IF NOT EXISTS idx_chat_users_origen ON chat_users(origen) WHERE origen IS NOT NULL;
