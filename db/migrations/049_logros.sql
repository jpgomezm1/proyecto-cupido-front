-- 049: onboarding, misiones y rachas con llaves de premio.
--
-- Las llaves de premio entran al mismo libro de abonos (`creditos_movimientos`,
-- tipo 'premio'), así el saldo sigue derivándose de las tablas. `logros` guarda
-- cada misión o hito de racha cumplido (uno por referencia: no se paga dos veces).

ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS onboarding_at TIMESTAMPTZ;

-- Quien ya usa Fynder no ve el onboarding de primera vez.
UPDATE chat_users u SET onboarding_at = NOW()
WHERE onboarding_at IS NULL AND (
       EXISTS (SELECT 1 FROM desbloqueos d WHERE d.user_id = u.id)
    OR EXISTS (SELECT 1 FROM uso_diario d WHERE d.user_id = u.id AND d.busquedas > 0)
    OR EXISTS (SELECT 1 FROM mcp_tool_calls c WHERE c.user_id = u.id));

ALTER TABLE creditos_movimientos DROP CONSTRAINT IF EXISTS creditos_movimientos_tipo_check;
ALTER TABLE creditos_movimientos ADD CONSTRAINT creditos_movimientos_tipo_check
    CHECK (tipo IN ('prueba', 'extra', 'ajuste', 'premio'));

CREATE TABLE IF NOT EXISTS logros (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    codigo VARCHAR(30) NOT NULL,          -- 'conectar_ia' | 'consulta_ia' | 'perfil' | 'mapa' | 'racha'
    referencia VARCHAR(60) NOT NULL DEFAULT '',  -- racha: '<inicio>:<hito>'
    llaves INTEGER NOT NULL DEFAULT 0,    -- las que se abonaron (0 = insignia o tope del mes)
    con_ia BOOLEAN NOT NULL DEFAULT FALSE,  -- racha hecha desde Claude/ChatGPT (premio doble)
    visto BOOLEAN NOT NULL DEFAULT FALSE,       -- ya se celebró en la web
    avisado_mcp BOOLEAN NOT NULL DEFAULT FALSE, -- ya se le contó por el MCP
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, codigo, referencia)
);
CREATE INDEX IF NOT EXISTS idx_logros_user ON logros(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logros_sin_avisar ON logros(user_id) WHERE NOT avisado_mcp AND llaves > 0;
