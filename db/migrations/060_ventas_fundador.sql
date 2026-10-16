-- 060: lanzamiento comercial (nov-2026)
--
-- 1. Plan Fundador: 20 cupos, todo lo de Cierre. Gratis hasta el 15-ene-2027 y luego
--    $50.000 fijos mientras siga suscrito sin cortes. No está a la venta (activo = false):
--    solo lo activa el admin (fundador_service).
-- 2. Doble de llaves el primer mes para quien se suscribe en sus primeros 7 días
--    (suscripciones.bono_lanzamiento = llaves extra de ese periodo).
-- 3. Ventas: la lista de agentes a contactar por la línea de WhatsApp de ventas
--    (solo outbound para conseguir una reunión), con su estado y su historial.

INSERT INTO planes (codigo, nombre, tipo, precio_cop, desbloqueos_mes, fotos_ia, fyns_tope_mes, activo, orden)
VALUES ('fundador', 'Fundador', 'suscripcion', 50000, 30, 30, 600, FALSE, 4)
ON CONFLICT (codigo) DO NOTHING;

ALTER TABLE suscripciones ADD COLUMN IF NOT EXISTS bono_lanzamiento INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS ventas_agentes (
    telefono_10        VARCHAR(10) PRIMARY KEY,
    nombre             TEXT,
    inmobiliaria       TEXT,
    user_id            INTEGER REFERENCES chat_users(id) ON DELETE SET NULL,
    fuente             VARCHAR(12) NOT NULL DEFAULT 'capturado'
                       CHECK (fuente IN ('capturado', 'hernan', 'pauta', 'referido', 'otro')),
    estado             VARCHAR(16) NOT NULL DEFAULT 'pendiente'
                       CHECK (estado IN ('pendiente', 'enviado', 'respondio', 'reunion', 'demo_hecha',
                                         'fundador', 'pago', 'no_interesa', 'excluido')),
    prioridad          INTEGER NOT NULL DEFAULT 0,
    inmuebles_activos  INTEGER NOT NULL DEFAULT 0,
    pedidos_90d        INTEGER NOT NULL DEFAULT 0,
    ultima_actividad   TIMESTAMPTZ,
    gancho             JSONB,          -- datos del mensaje: tipo, conteos, inmueble o pedido de referencia
    gancho_at          TIMESTAMPTZ,
    reunion_at         TIMESTAMPTZ,
    enviado_at         TIMESTAMPTZ,
    ultimo_contacto_at TIMESTAMPTZ,
    notas              TEXT,
    creado_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actualizado_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ventas_agentes_estado ON ventas_agentes (estado, prioridad DESC);
CREATE INDEX IF NOT EXISTS idx_ventas_agentes_user ON ventas_agentes (user_id);

CREATE TABLE IF NOT EXISTS ventas_eventos (
    id          SERIAL PRIMARY KEY,
    telefono_10 VARCHAR(10) NOT NULL REFERENCES ventas_agentes(telefono_10) ON DELETE CASCADE,
    tipo        VARCHAR(24) NOT NULL,   -- estado, nota, mensaje_enviado, reunion, fundador…
    detalle     TEXT,
    creado_por  VARCHAR(120),
    creado_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ventas_eventos_tel ON ventas_eventos (telefono_10, creado_at DESC);
CREATE INDEX IF NOT EXISTS idx_ventas_eventos_dia ON ventas_eventos (creado_at) WHERE tipo = 'mensaje_enviado';
