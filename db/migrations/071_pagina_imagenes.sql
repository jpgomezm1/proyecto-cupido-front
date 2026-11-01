-- 071: Imágenes con IA para Mi página (fondo de la portada, banners, texto con imagen, galería).
--
-- Cada imagen le cuesta a Fynder ~USD 0,05 (gpt-image-2, calidad media). Cupo propio:
--  - planes.imagenes_pagina: imágenes por periodo de cada plan; en 'prueba' es un cupo de una sola vez.
--  - pagina_imagenes_movimientos: imágenes extra (canje de Fyns, regalos); no vencen.
--  - pagina_imagenes: la biblioteca del agente. Las generadas cuentan para el cupo según `fuente`
--    (plan, prueba, extra); las que sube él (`fuente = 'subida'`) solo quedan en la biblioteca.
-- Idempotente.

ALTER TABLE planes ADD COLUMN IF NOT EXISTS imagenes_pagina INTEGER NOT NULL DEFAULT 0;

UPDATE planes SET imagenes_pagina = 3  WHERE codigo = 'prueba'   AND imagenes_pagina = 0;
UPDATE planes SET imagenes_pagina = 5  WHERE codigo = 'basico'   AND imagenes_pagina = 0;
UPDATE planes SET imagenes_pagina = 10 WHERE codigo = 'medio'    AND imagenes_pagina = 0;
UPDATE planes SET imagenes_pagina = 20 WHERE codigo = 'pro'      AND imagenes_pagina = 0;
UPDATE planes SET imagenes_pagina = 20 WHERE codigo = 'fundador' AND imagenes_pagina = 0;

CREATE TABLE IF NOT EXISTS pagina_imagenes (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    fuente VARCHAR(10) NOT NULL CHECK (fuente IN ('plan', 'prueba', 'extra', 'subida')),
    descripcion TEXT,
    estilo VARCHAR(20),
    formato VARCHAR(10),
    url TEXT,
    modelo VARCHAR(40),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pagina_imagenes_user ON pagina_imagenes(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS pagina_imagenes_movimientos (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    cantidad INTEGER NOT NULL,
    referencia VARCHAR(120),
    creado_por VARCHAR(120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pagina_imagenes_mov_user ON pagina_imagenes_movimientos(user_id);
