"""Saca data completa de las 3 propiedades elegidas en Los Balsos."""
import os
import json
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=RealDictCursor)

ids = [4717, 36914, 29042]

cur.execute(
    "SELECT * FROM propiedades WHERE id = ANY(%s) ORDER BY array_position(%s::int[], id)",
    (ids, ids)
)
rows = [dict(r) for r in cur.fetchall()]

out_path = os.path.join(os.path.dirname(__file__), 'props_balsos_final.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(rows, f, default=str, indent=2, ensure_ascii=False)

print(f'Saved {len(rows)} properties\n')
for r in rows:
    print(f"=== id={r['id']} ===")
    print(f"  Zona: {r.get('zona')} · barrio: {r.get('barrio_normalizado')}")
    print(f"  Titulo: {(r.get('titulo') or '').strip()[:120]}")
    print(f"  Precio: ${int(r.get('precio') or 0):,}")
    print(f"  m2: {r.get('area_construida')} | habs: {r.get('habitaciones')} | banos: {r.get('banos')} | parq: {r.get('parqueaderos')}")
    print(f"  Ano: {r.get('ano_construccion')} | estrato: {r.get('estrato')} | piso: {r.get('piso')}")
    print(f"  Admin: ${int(r.get('administracion') or 0):,}")
    print(f"  Imagenes: {r.get('total_imagenes')}")
    print(f"  URL: {(r.get('url') or '')[:90]}")
    print(f"  Highlights AI: {(r.get('highlights_ai') or '')[:350]}")
    print(f"  Desc AI: {(r.get('descripcion_ai') or '')[:400]}")
    print(f"  Amen ext: {(r.get('amenidades_externas') or '')[:200]}")
    print(f"  Amen int: {(r.get('amenidades_internas') or '')[:200]}")
    print()
conn.close()
