"""Saca data completa de las 3 propiedades elegidas para el comparativo."""
import os
import json
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=RealDictCursor)

# IDs elegidos: 17486 (Los Balsos · grande), 2723 (Loma del Indio · vista), 12993 (Ciudad del Río · moderna)
ids = [17486, 2723, 12993]

cur.execute("SELECT * FROM propiedades WHERE id = ANY(%s) ORDER BY array_position(%s::int[], id)", (ids, ids))
rows = [dict(r) for r in cur.fetchall()]

# Save full data
out_path = os.path.join(os.path.dirname(__file__), 'props_3_final.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(rows, f, default=str, indent=2, ensure_ascii=False)

print(f'Saved {len(rows)} properties to {out_path}\n')

for r in rows:
    barrio = r.get('barrio_normalizado') or r.get('zona') or ''
    imgs = r.get('imagenes_urls', '') or ''
    img_count = r.get('total_imagenes') or 0
    print(f"=== id={r['id']} · {barrio} ===")
    print(f"  Titulo: {(r.get('titulo') or '').strip()[:100]}")
    print(f"  Precio: ${int(r.get('precio') or 0):,}")
    print(f"  m2: {r.get('area_construida')}")
    print(f"  Habs/banos/parq: {r.get('habitaciones')}h / {r.get('banos')}b / {r.get('parqueaderos') or '-'}p")
    print(f"  Piso: {r.get('piso') or '-'}")
    print(f"  Estrato: {r.get('estrato') or '-'}")
    print(f"  Anho: {r.get('ano_construccion') or '-'}")
    print(f"  Admon: ${int(r.get('administracion') or 0):,}")
    print(f"  Imagenes: {img_count}")
    print(f"  URL: {(r.get('url') or '')[:80]}")
    print(f"  Asesor: {r.get('asesor')} | {r.get('inmobiliaria')}")
    print(f"  Highlights AI: {(r.get('highlights_ai') or '')[:200]}")
    print(f"  Desc AI: {(r.get('descripcion_ai') or '')[:200]}")
    print(f"  Vista: {r.get('vista')}")
    print(f"  Amenid internas: {(r.get('amenidades_internas') or '')[:150]}")
    print(f"  Amenid externas: {(r.get('amenidades_externas') or '')[:150]}")
    print(f"  Estilo: {r.get('estilo_arquitectonico')}")
    print(f"  Target buyer: {r.get('target_buyer_profile')}")
    print()

conn.close()
