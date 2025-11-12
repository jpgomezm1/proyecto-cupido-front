#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de diagnóstico de la base de datos
"""

from database import DatabaseManager

print("Diagnosticando base de datos...")
print()

try:
    with DatabaseManager() as db:
        # Contar registros
        db.cursor.execute("SELECT COUNT(*) as total FROM propiedades")
        result = db.cursor.fetchone()
        total = result['total'] if isinstance(result, dict) else result[0]
        print(f"✅ Total propiedades: {total}")
        print()

        # Ver una propiedad completa
        db.cursor.execute("SELECT * FROM propiedades LIMIT 1")
        row = db.cursor.fetchone()

        if row:
            print("📊 Primera propiedad encontrada:")
            print(f"   Tipo de resultado: {type(row)}")
            print()

            if isinstance(row, dict):
                print("📊 Contenido (primeros 10 campos):")
                for key, value in list(row.items())[:10]:
                    value_str = str(value)[:100] if value else 'None'
                    print(f"   {key}: {value_str}")
            else:
                print("📊 Row es una tupla:")
                columns = [desc[0] for desc in db.cursor.description]
                for i, (col, val) in enumerate(zip(columns[:10], row[:10])):
                    value_str = str(val)[:100] if val else 'None'
                    print(f"   {col}: {value_str}")
        else:
            print("⚠️  No hay propiedades en la base de datos")

        print()

        # Ver por fuente
        db.cursor.execute("SELECT fuente, COUNT(*) as total FROM propiedades GROUP BY fuente")
        print("📈 Por fuente:")
        for row in db.cursor.fetchall():
            if isinstance(row, dict):
                print(f"   • {row['fuente']}: {row['total']}")
            else:
                print(f"   • {row[0]}: {row[1]}")
        print()

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
