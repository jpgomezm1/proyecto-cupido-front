#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para analizar los datos reales de propiedades y determinar
qué opciones deben estar disponibles en los filtros del frontend
"""

from database import DatabaseManager
import json

def analizar_datos():
    db = DatabaseManager()
    db.connect()

    print("=" * 80)
    print("ANÁLISIS DE DATOS PARA FILTROS DEL FRONTEND")
    print("=" * 80)

    # 1. CIUDADES
    print("\n1. CIUDADES DISPONIBLES:")
    print("-" * 40)
    db.cursor.execute("""
        SELECT ciudad, COUNT(*) as cantidad
        FROM propiedades
        WHERE activa = true AND ciudad IS NOT NULL
        GROUP BY ciudad
        ORDER BY cantidad DESC
    """)
    ciudades = db.cursor.fetchall()
    for row in ciudades:
        print(f"  {row['ciudad']}: {row['cantidad']} propiedades")

    # 2. ZONAS
    print("\n2. ZONAS DISPONIBLES:")
    print("-" * 40)
    db.cursor.execute("""
        SELECT zona, COUNT(*) as cantidad
        FROM propiedades
        WHERE activa = true AND zona IS NOT NULL AND zona != ''
        GROUP BY zona
        ORDER BY cantidad DESC
    """)
    zonas = db.cursor.fetchall()
    for row in zonas:
        print(f"  {row['zona']}: {row['cantidad']} propiedades")

    # 3. TIPOS DE PROPIEDAD
    print("\n3. TIPOS DE PROPIEDAD:")
    print("-" * 40)
    db.cursor.execute("""
        SELECT tipo_propiedad, COUNT(*) as cantidad
        FROM propiedades
        WHERE activa = true AND tipo_propiedad IS NOT NULL
        GROUP BY tipo_propiedad
        ORDER BY cantidad DESC
    """)
    tipos = db.cursor.fetchall()
    for row in tipos:
        print(f"  {row['tipo_propiedad']}: {row['cantidad']} propiedades")

    # 4. RANGO DE PRECIOS
    print("\n4. RANGO DE PRECIOS (COP):")
    print("-" * 40)
    db.cursor.execute("""
        SELECT
            MIN(precio) as min_precio,
            MAX(precio) as max_precio,
            AVG(precio) as avg_precio,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY precio) as percentil_25,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY precio) as percentil_50,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY precio) as percentil_75
        FROM propiedades
        WHERE activa = true AND precio IS NOT NULL
    """)
    precios = db.cursor.fetchone()
    print(f"  Mínimo: ${precios['min_precio']:,.0f}")
    print(f"  Percentil 25%: ${precios['percentil_25']:,.0f}")
    print(f"  Mediana (50%): ${precios['percentil_50']:,.0f}")
    print(f"  Promedio: ${precios['avg_precio']:,.0f}")
    print(f"  Percentil 75%: ${precios['percentil_75']:,.0f}")
    print(f"  Máximo: ${precios['max_precio']:,.0f}")

    # 5. HABITACIONES
    print("\n5. HABITACIONES:")
    print("-" * 40)
    db.cursor.execute("""
        SELECT habitaciones, COUNT(*) as cantidad
        FROM propiedades
        WHERE activa = true AND habitaciones IS NOT NULL
        GROUP BY habitaciones
        ORDER BY habitaciones
    """)
    habitaciones = db.cursor.fetchall()
    for row in habitaciones:
        print(f"  {row['habitaciones']} habitaciones: {row['cantidad']} propiedades")

    # 6. ÁREA (m²)
    print("\n6. ÁREA (m²):")
    print("-" * 40)
    db.cursor.execute("""
        SELECT
            MIN(area_construida) as min_area,
            MAX(area_construida) as max_area,
            AVG(area_construida) as avg_area,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY area_construida) as percentil_25,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY area_construida) as percentil_50,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY area_construida) as percentil_75
        FROM propiedades
        WHERE activa = true AND area_construida IS NOT NULL
    """)
    areas = db.cursor.fetchone()
    print(f"  Mínimo: {areas['min_area']:,.1f} m²")
    print(f"  Percentil 25%: {areas['percentil_25']:,.1f} m²")
    print(f"  Mediana (50%): {areas['percentil_50']:,.1f} m²")
    print(f"  Promedio: {areas['avg_area']:,.1f} m²")
    print(f"  Percentil 75%: {areas['percentil_75']:,.1f} m²")
    print(f"  Máximo: {areas['max_area']:,.1f} m²")

    # 7. ANTIGÜEDAD
    print("\n7. ANTIGÜEDAD (años):")
    print("-" * 40)
    db.cursor.execute("""
        SELECT
            CASE
                WHEN ano_construccion IS NULL THEN 'Sin información'
                WHEN ano_construccion = 0 THEN 'Nuevo/En construcción'
                WHEN ano_construccion <= 5 THEN '1-5 años'
                WHEN ano_construccion <= 10 THEN '6-10 años'
                WHEN ano_construccion <= 20 THEN '11-20 años'
                ELSE 'Más de 20 años'
            END as rango_antiguedad,
            COUNT(*) as cantidad
        FROM propiedades
        WHERE activa = true
        GROUP BY rango_antiguedad
        ORDER BY
            CASE rango_antiguedad
                WHEN 'Nuevo/En construcción' THEN 1
                WHEN '1-5 años' THEN 2
                WHEN '6-10 años' THEN 3
                WHEN '11-20 años' THEN 4
                WHEN 'Más de 20 años' THEN 5
                ELSE 6
            END
    """)
    antiguedad = db.cursor.fetchall()
    for row in antiguedad:
        print(f"  {row['rango_antiguedad']}: {row['cantidad']} propiedades")

    # 8. FUENTE
    print("\n8. FUENTE DE PROPIEDADES:")
    print("-" * 40)
    db.cursor.execute("""
        SELECT fuente, COUNT(*) as cantidad
        FROM propiedades
        WHERE activa = true AND fuente IS NOT NULL
        GROUP BY fuente
        ORDER BY cantidad DESC
    """)
    fuentes = db.cursor.fetchall()
    for row in fuentes:
        print(f"  {row['fuente']}: {row['cantidad']} propiedades")

    # 9. ESTADO/CONDICIÓN
    print("\n9. ESTADO/CONDICIÓN:")
    print("-" * 40)
    db.cursor.execute("""
        SELECT estado, COUNT(*) as cantidad
        FROM propiedades
        WHERE activa = true AND estado IS NOT NULL AND estado != ''
        GROUP BY estado
        ORDER BY cantidad DESC
    """)
    estados = db.cursor.fetchall()
    for row in estados:
        print(f"  {row['estado']}: {row['cantidad']} propiedades")

    # 10. ESTRATO
    print("\n10. ESTRATO:")
    print("-" * 40)
    db.cursor.execute("""
        SELECT estrato, COUNT(*) as cantidad
        FROM propiedades
        WHERE activa = true AND estrato IS NOT NULL
        GROUP BY estrato
        ORDER BY estrato
    """)
    estratos = db.cursor.fetchall()
    for row in estratos:
        print(f"  Estrato {row['estrato']}: {row['cantidad']} propiedades")

    print("\n" + "=" * 80)
    print("ANÁLISIS COMPLETADO")
    print("=" * 80)

    db.disconnect()

if __name__ == "__main__":
    analizar_datos()
