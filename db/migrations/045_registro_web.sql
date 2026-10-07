-- 045: registro autogestionado en la web y verificación del celular por código.
--
-- El agente crea su cuenta en /chat/registro (origen='web') y verifica su
-- celular con un código de 6 dígitos que le llega por WhatsApp. Al verificar
-- recibe los créditos de prueba (asegurar_prueba, uno por teléfono).
-- El código se guarda solo como hash; vence a los 10 minutos y admite pocos intentos.

CREATE TABLE IF NOT EXISTS codigos_telefono (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    telefono VARCHAR(20) NOT NULL,            -- +57XXXXXXXXXX al que se envió
    codigo_hash VARCHAR(64) NOT NULL,
    intentos SMALLINT NOT NULL DEFAULT 0,
    expira_at TIMESTAMPTZ NOT NULL,
    usado_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_codigos_telefono_user ON codigos_telefono(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_codigos_telefono_tel ON codigos_telefono(telefono, created_at DESC);
