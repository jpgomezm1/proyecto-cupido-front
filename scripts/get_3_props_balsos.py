"""Saca propiedades en Los Balsos · rango 1.000M-1.500M para el comparativo demo."""
import os
import json
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=RealDictCursor)

cur.execute("""
    SELECT *
    FROM propiedades
    WHERE activa = TRUE
      AND (zona ILIKE '%balsos%' OR barrio_normalizado ILIKE '%balsos%' OR titulo ILIKE '%balsos%')
      AND habitaciones >= 3
      AND precio BETWEEN 1000000000 AND 1500000000
      AND imagen_principal IS NOT NULL
      AND total_imagenes >= 4
    ORDER BY precio
    LIMIT 20
""")
rows = [dict(r) for r in cur.fetchall()]

out_path = os.path.join(os.path.dirname(__file__), 'props_balsos.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(rows, f, default=str, indent=2, ensure_ascii=False)

print(f'Saved {len(rows)} properties\n')
for r in rows:
    barrio = (r.get('barrio_normalizado') or r.get('zona') or '').strip()
    precio = r.get('precio') or 0
    area = r.get('area_construida') or 0
    imgs = r.get('total_imagenes') or 0
    piso = r.get('piso') or '-'
    ano = r.get('ano_construccion') or '-'
    print(f"  id={r['id']:5} | {barrio:<28} | {area:>5.0f}m2 | {r['habitaciones']}h/{r['banos']}b | piso {piso} | {ano} | ${precio:>13,} | {imgs} imgs")

conn.close()
