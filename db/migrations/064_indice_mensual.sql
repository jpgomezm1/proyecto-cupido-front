-- 064: Índice Fynder mensual (benchmark Idealista: el informe de precios que citan los medios).
-- Una foto del mercado al cierre de cada mes por zona (comunas de Medellín y municipios):
-- inmuebles en venta, precio por m² de los apartamentos, oferta nueva, bajas y pedidos de clientes.
-- La verificación de bajas existe desde oct-2026, así que el mes pasado no se puede reconstruir:
-- cada mes se guarda su foto y la variación sale contra la edición anterior.
-- El worker calcula el mes que cerró (borrador); el admin lo revisa y lo publica en /indice.
-- Idempotente.

CREATE TABLE IF NOT EXISTS indice_ediciones (
    mes DATE PRIMARY KEY,                       -- primer día del mes
    estado VARCHAR(10) NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador', 'publicado')),
    titular TEXT,
    calculado_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    publicado_at TIMESTAMPTZ,
    publicado_por VARCHAR(120)
);

CREATE TABLE IF NOT EXISTS indice_mensual (
    mes DATE NOT NULL REFERENCES indice_ediciones(mes) ON DELETE CASCADE,
    zona VARCHAR(120) NOT NULL,                 -- comuna de Medellín, municipio o 'Total'
    nivel VARCHAR(10) NOT NULL CHECK (nivel IN ('total', 'comuna', 'municipio')),
    municipio VARCHAR(80),
    activos INTEGER NOT NULL DEFAULT 0,         -- inmuebles en venta al cierre
    aptos INTEGER NOT NULL DEFAULT 0,           -- apartamentos en venta con precio y área (base del m²)
    m2_p25 NUMERIC(14, 0),
    m2_mediana NUMERIC(14, 0),
    m2_p75 NUMERIC(14, 0),
    var_m2_pct NUMERIC(6, 2),                   -- contra la edición anterior (si ambas son suficientes)
    nuevos INTEGER NOT NULL DEFAULT 0,          -- llegaron en el mes
    salieron INTEGER NOT NULL DEFAULT 0,        -- el verificador los encontró dados de baja en el mes
    pedidos INTEGER NOT NULL DEFAULT 0,         -- pedidos de clientes en el mes
    suficiente BOOLEAN NOT NULL DEFAULT FALSE,  -- 15 o más inmuebles en venta: se publica
    PRIMARY KEY (mes, zona)
);
