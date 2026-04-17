-- =============================================================================
-- Migration 029: Normalizar chat_users.telefono a formato +57XXXXXXXXXX
-- =============================================================================
-- Problema:
--   chat_users.telefono se guardaba tal cual lo escribia el admin (ej "3001234567"),
--   mientras que propiedades.agente_captador_telefono se guarda siempre como
--   "+57XXXXXXXXXX" (normalizado en los scrape endpoints). Esto causaba que la
--   vista "Mis Propiedades" en el chat de Fynder filtrara OUT las propiedades
--   del usuario, porque al comparar solo digitos "3001234567" != "573001234567".
--
-- Efecto:
--   Los usuarios subian propiedades correctamente (se guardaban en DB) pero
--   al refrescar no las veian. Parece bug de persistencia pero es de filtrado.
--
-- Solucion:
--   1. Normalizar retroactivamente los telefonos ya almacenados.
--   2. El backend ya usa src/utils/phone.normalize_colombia_phone() al
--      crear/actualizar chat_users desde esta migracion en adelante.
-- =============================================================================

BEGIN;

UPDATE chat_users
SET telefono = CASE
    -- Ya normalizado: +57XXXXXXXXXX (13 chars)
    WHEN telefono ~ '^\+57[0-9]{10}$' THEN telefono

    -- Trae + pero con otro formato/pais: no tocar (respetar internacional)
    WHEN telefono LIKE '+%' THEN telefono

    -- 57 + 10 digitos (sin +, solo country code): agregar +
    WHEN regexp_replace(telefono, '\D', '', 'g') ~ '^57[0-9]{10}$'
        THEN '+' || regexp_replace(telefono, '\D', '', 'g')

    -- 10 digitos (celular/fijo colombiano sin country code): agregar +57
    WHEN regexp_replace(telefono, '\D', '', 'g') ~ '^[0-9]{10}$'
        THEN '+57' || regexp_replace(telefono, '\D', '', 'g')

    -- 0 + 10 digitos: quitar el 0 y agregar +57
    WHEN regexp_replace(telefono, '\D', '', 'g') ~ '^0[0-9]{10}$'
        THEN '+57' || substring(regexp_replace(telefono, '\D', '', 'g') from 2)

    -- Formato no reconocido: dejar tal cual (evitar corromper data)
    ELSE telefono
END
WHERE telefono IS NOT NULL AND trim(telefono) <> '';

-- Log para verificar cuantas filas quedaron bien normalizadas
DO $$
DECLARE
    total_con_tel INTEGER;
    normalizados INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_con_tel
    FROM chat_users WHERE telefono IS NOT NULL AND trim(telefono) <> '';

    SELECT COUNT(*) INTO normalizados
    FROM chat_users WHERE telefono ~ '^\+57[0-9]{10}$';

    RAISE NOTICE 'chat_users con telefono: %, normalizados a +57: %',
                 total_con_tel, normalizados;
END $$;

COMMIT;
