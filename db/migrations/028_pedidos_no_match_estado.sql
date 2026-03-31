-- Migrar pedidos con share_id='NO_MATCH' al nuevo estado 'no_match'
UPDATE pedidos SET estado = 'no_match', share_id = NULL WHERE share_id = 'NO_MATCH';
