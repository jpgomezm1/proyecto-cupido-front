-- ============================================================================
-- MIGRACIÓN 035: Encender el embudo — flujo interés → PUNTAS → Hernán (Bloque A)
-- Fecha: 2026-07-24
-- Descripción: Agrega a `interacciones` las columnas que faltan para registrar
--   un interés end-to-end (A3) y soportar las PUNTAS (A2). No borra ni muta
--   datos existentes; todo es aditivo e idempotente.
-- ============================================================================

-- 1) Columnas nuevas en `interacciones`
ALTER TABLE interacciones
    -- Puerta por la que entró el interés: 'MCP' (agente autoservicio),
    -- 'UI' (portal), 'WhatsApp' (Matías desde el admin / grupo).
    ADD COLUMN IF NOT EXISTS fuente VARCHAR(20) DEFAULT 'MCP',
    -- Vínculo opcional al pedido de demanda que originó el interés
    -- (interacciones ya tiene solicitud_mercado_id; los pedidos son otra tabla).
    ADD COLUMN IF NOT EXISTS pedido_id INTEGER REFERENCES pedidos(id),
    -- Referencia libre del cliente comprador que da el agente (no es contacto de agente).
    ADD COLUMN IF NOT EXISTS cliente_ref VARCHAR(200),
    -- Balde 2: preguntas para el dueño que se escalan a Hernán junto con las puntas.
    ADD COLUMN IF NOT EXISTS preguntas TEXT,
    -- Snapshot del resultado de la verificación de disponibilidad (B1) al momento
    -- de escalar: 'disponible' | '404' | 'vendido' | 'desconocido'.
    ADD COLUMN IF NOT EXISTS disponibilidad_estado VARCHAR(20),
    -- Marca de tiempo cuando se enviaron las PUNTAS a Hernán (A2).
    ADD COLUMN IF NOT EXISTS fecha_puntas_enviadas TIMESTAMP;

COMMENT ON COLUMN interacciones.fuente IS 'Puerta de entrada del interés: MCP | UI | WhatsApp';
COMMENT ON COLUMN interacciones.pedido_id IS 'Pedido de demanda (tabla pedidos) que originó el interés, si aplica';
COMMENT ON COLUMN interacciones.cliente_ref IS 'Referencia libre del cliente comprador dada por el agente';
COMMENT ON COLUMN interacciones.preguntas IS 'Balde 2: preguntas para el dueño escaladas a Hernán';
COMMENT ON COLUMN interacciones.disponibilidad_estado IS 'Snapshot de verificación (B1): disponible | 404 | vendido | desconocido';
COMMENT ON COLUMN interacciones.fecha_puntas_enviadas IS 'Cuándo se enviaron las PUNTAS a Hernán (A2)';

-- 2) Índices de apoyo para reconstruir el embudo y evitar duplicados obvios
CREATE INDEX IF NOT EXISTS idx_interacciones_estado ON interacciones(estado);
CREATE INDEX IF NOT EXISTS idx_interacciones_propiedad ON interacciones(propiedad_id);
CREATE INDEX IF NOT EXISTS idx_interacciones_pedido ON interacciones(pedido_id);

-- 3) Estados del pipeline (el campo `estado` es VARCHAR libre, sin CHECK).
--    Estados vigentes tras esta migración:
--      'Seleccionado'            → interés registrado (A3)
--      'Puntas_Enviadas'         → PUNTAS enviadas a Hernán (A2)      [NUEVO]
--      'Visita_Agendada'         → Hernán coordinó la visita          [NUEVO]
--      'Contacto_Compartido'     (legado)
--      'Notificado_Vendedor'     (legado)
--      'En_Proceso'              (legado)
--      'Cerrado_Exitoso'         → cierre confirmado
--      'Cerrado_Sin_Resultado'   → no prosperó
--    Los estados nuevos no requieren cambios de esquema (solo se documentan aquí).

-- 4) Contador de "match logrado": moverlo del INSERT al CIERRE real.
--    Antes, el trigger sumaba total_matches_logrados en cada INSERT con
--    agente_vendedor_id — pero ahora insertamos en cada INTERÉS (estado
--    'Seleccionado'), que NO es un cierre. Por el Principio 1 ("trazabilidad =
--    cierre, no declaración"), el match se cuenta solo al pasar a
--    'Cerrado_Exitoso'. `interacciones` está vacía, así que no hay backfill.
CREATE OR REPLACE FUNCTION actualizar_contadores_agente()
RETURNS TRIGGER AS $$
BEGIN
    -- Cuenta un match para el agente vendedor (captador) SOLO cuando la
    -- interacción se cierra con éxito, y solo en la transición hacia ese estado
    -- (no en cada UPDATE posterior).
    IF NEW.estado = 'Cerrado_Exitoso'
       AND (TG_OP = 'INSERT' OR OLD.estado IS DISTINCT FROM 'Cerrado_Exitoso')
       AND NEW.agente_vendedor_id IS NOT NULL THEN
        UPDATE agentes
        SET total_matches_logrados = total_matches_logrados + 1
        WHERE id = NEW.agente_vendedor_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_actualizar_contadores ON interacciones;
CREATE TRIGGER trigger_actualizar_contadores
    AFTER INSERT OR UPDATE ON interacciones
    FOR EACH ROW
    EXECUTE FUNCTION actualizar_contadores_agente();
