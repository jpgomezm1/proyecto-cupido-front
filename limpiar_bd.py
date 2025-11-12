#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script simple para limpiar la base de datos de propiedades
"""

from database import DatabaseManager


def limpiar_base_datos():
    """
    Limpia todas las propiedades de la base de datos
    """
    print("\n" + "=" * 80)
    print("LIMPIANDO BASE DE DATOS DE PROPIEDADES")
    print("=" * 80)

    db = DatabaseManager()
    db.connect()

    try:
        # Primero mostrar cuántas propiedades hay
        db.cursor.execute("SELECT COUNT(*) as count FROM propiedades")
        count = db.cursor.fetchone()['count']
        print(f"\n⚠️  Se encontraron {count} propiedades en la base de datos.")

        if count == 0:
            print("✅ La base de datos ya está vacía.")
            db.disconnect()
            return

        # Confirmar antes de borrar
        print("\n⚠️  ADVERTENCIA: Esta acción NO se puede deshacer!")
        confirmacion = input("¿Estás seguro de que quieres ELIMINAR TODAS las propiedades? (escribe 'SI' para confirmar): ")

        if confirmacion.strip().upper() != 'SI':
            print("\n❌ Operación cancelada. No se eliminó ninguna propiedad.")
            db.disconnect()
            return

        # Ejecutar TRUNCATE para limpiar completamente la tabla
        print("\n🗑️  Eliminando todas las propiedades...")
        db.cursor.execute("TRUNCATE TABLE propiedades RESTART IDENTITY CASCADE")
        db.conn.commit()

        # Verificar que se limpiaron
        db.cursor.execute("SELECT COUNT(*) as count FROM propiedades")
        count_despues = db.cursor.fetchone()['count']

        print(f"\n✅ Base de datos limpiada exitosamente!")
        print(f"   Propiedades antes: {count}")
        print(f"   Propiedades ahora: {count_despues}")

        db.disconnect()

    except Exception as e:
        print(f"\n❌ Error limpiando la base de datos: {str(e)}")
        db.disconnect()


if __name__ == "__main__":
    limpiar_base_datos()
    print("\n" + "=" * 80)
