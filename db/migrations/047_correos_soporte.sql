-- 047: correos transaccionales, soporte desde la app y cierre de cuenta.
--
-- correos_enviados: evita repetir los correos programados (plan por vencer,
--   plan vencido): uno por (tipo, ref). ref = id de la suscripción.
-- soporte_solicitudes: mensajes que el agente manda desde Mi cuenta → Ayuda;
--   llegan por correo al buzón del equipo y el agente recibe su número de caso.
-- chat_users.eliminada_at: cuenta cerrada por el agente (datos personales borrados).

CREATE TABLE IF NOT EXISTS correos_enviados (
    id SERIAL PRIMARY KEY,
    tipo VARCHAR(40) NOT NULL,
    ref VARCHAR(80) NOT NULL,
    user_id INTEGER REFERENCES chat_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tipo, ref)
);

CREATE TABLE IF NOT EXISTS soporte_solicitudes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES chat_users(id) ON DELETE SET NULL,
    categoria VARCHAR(20) NOT NULL,
    asunto VARCHAR(160) NOT NULL,
    mensaje TEXT NOT NULL,
    estado VARCHAR(12) NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'resuelta')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_soporte_user ON soporte_solicitudes(user_id, created_at DESC);

ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS eliminada_at TIMESTAMPTZ;
