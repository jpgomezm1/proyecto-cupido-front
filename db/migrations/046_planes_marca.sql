-- 046: nombres de marca de los planes (oct-2026).
-- Los créditos ahora se llaman "llaves" y los planes siguen el embudo del
-- agente: Visita (7) · Negocio (15) · Cierre (30). Los códigos no cambian.
UPDATE planes SET nombre = 'Visita', updated_at = NOW() WHERE codigo = 'basico';
UPDATE planes SET nombre = 'Negocio', updated_at = NOW() WHERE codigo = 'medio';
UPDATE planes SET nombre = 'Cierre', updated_at = NOW() WHERE codigo = 'pro';
