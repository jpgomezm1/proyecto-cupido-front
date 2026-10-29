-- 069 · Mi página: diseño (plantilla, color, secciones…) y sus cifras.
--
-- chat_users.pagina_config: lo que el agente elige en el editor (pagina_agente_service.normalizar).
-- pagina_eventos: contadores por día de la página pública (visitas, toques a WhatsApp, inmuebles
-- abiertos, valorador) y los usos del asistente con IA ('ia'), que tiene tope diario.

ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS pagina_config JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS pagina_eventos (
    user_id  INTEGER NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    dia      DATE    NOT NULL,
    tipo     TEXT    NOT NULL CHECK (tipo IN ('visita', 'whatsapp', 'inmueble', 'valorar', 'ia')),
    n        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, dia, tipo)
);
