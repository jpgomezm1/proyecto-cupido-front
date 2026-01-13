"""Script rápido para ver qué propiedades hay en la base de datos"""
import os
from dotenv import load_dotenv
from src.db.database import DatabaseManager

load_dotenv()

db = DatabaseManager()
db.connect()

try:
    # Ver todas las propiedades activas
    db.cursor.execute("""
        SELECT id, tipo_propiedad, ciudad, zona, habitaciones, precio, titulo
        FROM propiedades
        WHERE activa = TRUE
        ORDER BY ciudad, tipo_propiedad
        LIMIT 50
    """)

    rows = db.cursor.fetchall()

    print(f"\n📊 Total propiedades activas: {len(rows)}\n")
    print("=" * 100)

    for row in rows:
        precio_fmt = f"${row['precio']:,.0f}" if row['precio'] else "Sin precio"
        print(f"ID: {row['id']:3} | {row['tipo_propiedad']:<15} | {row['ciudad']:<15} | {row['zona']:<20} | {row['habitaciones']} hab | {precio_fmt}")

    # Estadísticas
    db.cursor.execute("""
        SELECT
            ciudad,
            COUNT(*) as total,
            MIN(precio) as precio_min,
            MAX(precio) as precio_max
        FROM propiedades
        WHERE activa = TRUE
        GROUP BY ciudad
        ORDER BY total DESC
    """)

    print("\n\n📈 Estadísticas por ciudad:")
    print("=" * 80)
    for row in db.cursor.fetchall():
        precio_min = f"${row['precio_min']:,.0f}" if row['precio_min'] else "N/A"
        precio_max = f"${row['precio_max']:,.0f}" if row['precio_max'] else "N/A"
        print(f"{row['ciudad']:<20} | {row['total']:3} propiedades | Precio: {precio_min} - {precio_max}")

    # Tipos de propiedad
    db.cursor.execute("""
        SELECT tipo_propiedad, COUNT(*) as total
        FROM propiedades
        WHERE activa = TRUE
        GROUP BY tipo_propiedad
        ORDER BY total DESC
    """)

    print("\n\n🏠 Tipos de propiedad:")
    print("=" * 40)
    for row in db.cursor.fetchall():
        print(f"{row['tipo_propiedad']:<20} | {row['total']:3}")

finally:
    db.disconnect()
