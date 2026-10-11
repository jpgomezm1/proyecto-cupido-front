-- 055: locks de jobs con vencimiento (reemplazan pg_try_advisory_lock, que se
-- quedaba tomado con el pooler de Neon). El código también la crea si falta.
CREATE TABLE IF NOT EXISTS job_locks (
    nombre TEXT PRIMARY KEY,
    hasta TIMESTAMPTZ NOT NULL
);
