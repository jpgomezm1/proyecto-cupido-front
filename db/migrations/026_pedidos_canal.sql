-- Canal de procesamiento: 'manual' (humano) o 'auto' (API WhatsApp)
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS canal VARCHAR(10) DEFAULT 'manual';
