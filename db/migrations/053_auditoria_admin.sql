-- 053 · Auditoría de acciones sensibles del admin.
--
-- Verificar un teléfono da control sobre el inventario de ese número ("mis
-- propiedades", desbloqueos gratis por "propio"); regenerar una clave entrega
-- una cuenta. Ambas cosas las hace un admin a mano, sin prueba: queda registro
-- de quién lo hizo, cuándo y sobre qué cuenta.

CREATE TABLE IF NOT EXISTS auditoria_admin (
    id BIGSERIAL PRIMARY KEY,
    admin_email TEXT,
    accion TEXT NOT NULL,          -- telefono_verificado | telefono_cambiado | clave_regenerada | claves_rotadas
    user_id INTEGER REFERENCES chat_users(id) ON DELETE SET NULL,
    detalle JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auditoria_admin_user ON auditoria_admin (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auditoria_admin_fecha ON auditoria_admin (created_at DESC);
