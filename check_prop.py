import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get('DATABASE_URL') or open('.env').read().split('DATABASE_URL=')[1].split('\n')[0].strip().strip('"').strip("'")

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor(cursor_factory=RealDictCursor)

print("=" * 70)
print("VERIFICANDO ÚLTIMAS 5 PROPIEDADES CON OWNER INFO")
print("=" * 70)

cursor.execute("""
    SELECT 
        p.codigo_propiedad,
        p.zona,
        p.agente_captador_telefono,
        a.nombre as owner_name
    FROM propiedades p
    LEFT JOIN agentes a ON a.telefono = p.agente_captador_telefono
    ORDER BY p.fecha_creacion DESC
    LIMIT 5
""")

for row in cursor.fetchall():
    tel = row['agente_captador_telefono'] or 'NULL ❌'
    name = row['owner_name'] or 'NULL ❌'
    zona = (row['zona'] or '')[:25]
    print(f"Código: {row['codigo_propiedad']} | {zona:25} | Tel: {tel} | Name: {name}")

conn.close()
