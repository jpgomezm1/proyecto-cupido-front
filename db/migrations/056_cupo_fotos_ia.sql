-- 056: Cupo de fotos con IA por plan y paquetes de fotos que se compran aparte.
--
-- Cada foto mejorada le cuesta a Fynder ~USD 0,10–0,13 (gpt-image-1, calidad
-- media, alta fidelidad). Para que siga siendo rentable:
--  - planes.fotos_ia: fotos al mes de cada plan; en 'prueba' es un cupo de una
--    sola vez; en un paquete de tipo 'fotos', cuántas fotos trae.
--  - suscripciones.fotos_ia_incluidas: el cupo que se pagó en ese periodo (un
--    cambio de cupo no afecta un periodo ya pagado). NULL = el del plan hoy.
--  - fotos_ia_movimientos: fotos compradas o regaladas; no vencen.
--  - fotos_mejoradas.fuente: de qué cupo salió cada foto (plan, prueba, extra).
-- Idempotente.

ALTER TABLE planes ADD COLUMN IF NOT EXISTS fotos_ia INTEGER NOT NULL DEFAULT 0;
ALTER TABLE planes DROP CONSTRAINT IF EXISTS planes_tipo_check;
ALTER TABLE planes ADD CONSTRAINT planes_tipo_check CHECK (tipo IN ('suscripcion', 'paquete', 'fotos'));

UPDATE planes SET fotos_ia = 3  WHERE codigo = 'prueba' AND fotos_ia = 0;
UPDATE planes SET fotos_ia = 10 WHERE codigo = 'basico' AND fotos_ia = 0;
UPDATE planes SET fotos_ia = 20 WHERE codigo = 'medio'  AND fotos_ia = 0;
UPDATE planes SET fotos_ia = 30 WHERE codigo = 'pro'    AND fotos_ia = 0;

INSERT INTO planes (codigo, nombre, precio_cop, desbloqueos_mes, fotos_ia, orden, tipo)
VALUES ('fotos_10', '10 fotos con IA', 10000, 0, 10, 20, 'fotos'),
       ('fotos_30', '30 fotos con IA', 25000, 0, 30, 21, 'fotos')
ON CONFLICT (codigo) DO NOTHING;

ALTER TABLE suscripciones ADD COLUMN IF NOT EXISTS fotos_ia_incluidas INTEGER;

CREATE TABLE IF NOT EXISTS fotos_ia_movimientos (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    cantidad INTEGER NOT NULL,
    referencia VARCHAR(120),
    creado_por VARCHAR(120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fotos_ia_mov_user ON fotos_ia_movimientos(user_id);

ALTER TABLE fotos_mejoradas ADD COLUMN IF NOT EXISTS fuente VARCHAR(10);
CREATE INDEX IF NOT EXISTS idx_fotos_mejoradas_fuente ON fotos_mejoradas(user_id, fuente, created_at);

ALTER TABLE pagos ADD COLUMN IF NOT EXISTS fotos_movimiento_id BIGINT REFERENCES fotos_ia_movimientos(id);
