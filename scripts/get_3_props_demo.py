"""Saca 3 propiedades reales de El Poblado para el comparativo demo del webinar."""
import os
import json
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=RealDictCursor)

# 3 propiedades en El Poblado, rango 800M-1000M, 3 hab, con imágenes
cur.execute("""
    SELECT
        id, codigo_propiedad, titulo, precio, precio_texto, tipo_propiedad,
        ciudad, zona, barrio_normalizado, direccion_completa,
        area_construida, habitaciones, banos, parqueaderos, estrato, piso,
        ano_construccion, administracion, vista,
        amenidades_internas, amenidades_externas, amenidades_destacadas,
        unique_selling_points, ventajas_competitivas,
        target_buyer_profile, segmento_mercado, estilo_arquitectonico,
        imagen_principal, imagenes_urls, total_imagenes,
        descripcion, descripcion_resumida, descripcion_ai, highlights_ai,
        asesor, telefono, inmobiliaria, url,
        precio_m2, walkability_score, overall_quality_score
    FROM propiedades
    WHERE activa = TRUE
      AND zona ILIKE '%poblado%'
      AND habitaciones = 3
      AND precio BETWEEN 700000000 AND 1100000000
      AND imagen_principal IS NOT NULL
      AND total_imagenes >= 1
    ORDER BY precio
    LIMIT 15
""")
rows = [dict(r) for r in cur.fetchall()]

out_path = os.path.join(os.path.dirname(__file__), 'props_demo_output.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(rows, f, default=str, indent=2, ensure_ascii=False)

print(f'Saved {len(rows)} properties to {out_path}')
print('\nQuick summary:')
for r in rows:
    barrio = (r.get('barrio_normalizado') or r.get('zona') or '').strip()
    precio = r.get('precio') or 0
    area = r.get('area_construida') or 0
    img = '[img]' if r.get('imagen_principal') else '[no img]'
    print(f"  id={r['id']:4} | {barrio:<25} | {area:>5.0f}m2 | {r['habitaciones']}h/{r['banos']}b | piso {r.get('piso') or '-'} | ${precio:>13,} | {img}")

conn.close()
