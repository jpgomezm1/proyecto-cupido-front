-- Migration 019: Agregar correo personal para notificaciones
-- El email de login (email) es asignado por admin y no se puede cambiar
-- correo_personal es el email real del agente, editable por el usuario

ALTER TABLE chat_users ADD COLUMN IF NOT EXISTS correo_personal VARCHAR(255);
