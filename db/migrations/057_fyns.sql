-- 057: Fyns, la divisa de Fynder.
--
-- Se ganan usando Fynder (mucho más desde la IA del agente, vía MCP) y se canjean
-- por llaves, fotos con IA y, más adelante, complementos. Reemplazan las llaves de
-- premio de rachas y misiones (los logros viejos conservan sus llaves).
--  - logros.fyns: cuántos Fyns pagó cada logro (0 = insignia o tope del mes).
--  - fyns_movimientos: el saldo (+ lo ganado, − lo canjeado). No vencen.
--  - planes.fyns_tope_mes: cuántos Fyns se pueden ganar al mes según el plan
--    (el de 'prueba' aplica a quien no tiene plan).
-- Idempotente.

ALTER TABLE logros ADD COLUMN IF NOT EXISTS fyns INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_logros_fyns_sin_avisar ON logros(user_id) WHERE NOT avisado_mcp AND fyns > 0;

CREATE TABLE IF NOT EXISTS fyns_movimientos (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    cantidad INTEGER NOT NULL,                 -- + ganado, − canjeado
    motivo VARCHAR(30) NOT NULL,               -- 'logro' | 'canje' | 'ajuste'
    referencia VARCHAR(120),                   -- logro:<id> | <producto canjeado>
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fyns_mov_user ON fyns_movimientos(user_id, created_at DESC);

ALTER TABLE planes ADD COLUMN IF NOT EXISTS fyns_tope_mes INTEGER NOT NULL DEFAULT 0;
UPDATE planes SET fyns_tope_mes = 150 WHERE codigo = 'prueba' AND fyns_tope_mes = 0;
UPDATE planes SET fyns_tope_mes = 300 WHERE codigo = 'basico' AND fyns_tope_mes = 0;
UPDATE planes SET fyns_tope_mes = 450 WHERE codigo = 'medio'  AND fyns_tope_mes = 0;
UPDATE planes SET fyns_tope_mes = 600 WHERE codigo = 'pro'    AND fyns_tope_mes = 0;
