#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para cargar propiedades de prueba de Pulppo en Neon
Reutiliza imágenes extraídas de Wasi para las propiedades
"""

from database import DatabaseManager
from datetime import datetime
import random
import sys

print("=" * 70)
print("  CARGA DE PROPIEDADES PULPPO - MEDELLÍN")
print("=" * 70)
print()

# Datos para generar propiedades realistas en Medellín
ZONAS_MEDELLIN = [
    "El Poblado", "Laureles", "Envigado", "Sabaneta", "Belén",
    "Estadio", "La América", "Castilla", "Robledo", "Buenos Aires"
]

BARRIOS_POR_ZONA = {
    "El Poblado": ["El Tesoro", "San Lucas", "Castropol", "Manila", "Las Palmas"],
    "Laureles": ["Laureles", "Carlos E. Restrepo", "La Castellana", "Florida Nueva"],
    "Envigado": ["Loma del Escobero", "Alcalá", "La Paz", "Zuniga", "Las Antillas"],
    "Sabaneta": ["Cañaveralejo", "Las Lomitas", "San José", "Restrepo Naranjo"],
    "Belén": ["Las Violetas", "Nogal", "La Gloria", "Altavista", "San Bernardo"],
    "Estadio": ["Aranjuez", "Manrique", "Campo Valdés", "Prado"],
    "La América": ["Calasanz", "La Floresta", "Ferrini", "Santa Mónica"],
    "Castilla": ["Castilla", "Alfonso López", "Tricentenario", "Tejelo"],
    "Robledo": ["La Pilarica", "Bello Horizonte", "Villa Flora", "Pajarito"],
    "Buenos Aires": ["Boston", "Los Conquistadores", "Loreto", "Alejandro Echavarría"]
}

TIPOS_PROPIEDAD = ["Apartamento", "Casa", "Penthouse", "Duplex"]

ESTRATOS = [3, 4, 5, 6]

# URLs de imágenes reales extraídas de Wasi (para reutilizar)
IMAGENES_DISPONIBLES = [
    # Penthouse Belén Nogal (18 imágenes HD)
    "https://image.wasi.co/eyJidWNrZXQiOiJzdGF0aWN3Iiwia2V5IjoiaW5tdWVibGVzXC9ncjIzNDk2MTUyMDI1MTAwODEwMTIxMS5qcGciLCJlZGl0cyI6eyJub3JtYWxpc2UiOnRydWUsInJvdGF0ZSI6MCwicmVzaXplIjp7IndpZHRoIjo5NzksImhlaWdodCI6NzQzLCJmaXQiOiJjb250YWluIn19fQ==",
    "https://image.wasi.co/eyJidWNrZXQiOiJzdGF0aWN3Iiwia2V5IjoiaW5tdWVibGVzXC9ncjIzNDk2NzIwMjUxMDA4MTAxMjA4LmpwZyIsImVkaXRzIjp7Im5vcm1hbGlzZSI6dHJ1ZSwicm90YXRlIjowLCJyZXNpemUiOnsid2lkdGgiOjk3OSwiaGVpZ2h0Ijo3NDMsImZpdCI6ImNvbnRhaW4ifX19",
    "https://image.wasi.co/eyJidWNrZXQiOiJzdGF0aWN3Iiwia2V5IjoiaW5tdWVibGVzXC9ncjIzNDk2MTEyMDI1MTAwODEwMTIxMC5qcGciLCJlZGl0cyI6eyJub3JtYWxpc2UiOnRydWUsInJvdGF0ZSI6MCwicmVzaXplIjp7IndpZHRoIjo5NzksImhlaWdodCI6NzQzLCJmaXQiOiJjb250YWluIn19fQ==",
    # Apartamento La Paz (19 imágenes HD)
    "https://image.wasi.co/eyJidWNrZXQiOiJzdGF0aWN3Iiwia2V5IjoiaW5tdWVibGVzXC9ncl9zZV92ZW5kZV9oZXJtb3NvX2FwYXJ0YW1lbnRvX2VfMTc2MTM5MjQxNi0xOTI0Xzc0MTIuanBlZyIsImVkaXRzIjp7Im5vcm1hbGlzZSI6dHJ1ZSwicm90YXRlIjowLCJyZXNpemUiOnsid2lkdGgiOjk3OSwiaGVpZ2h0Ijo3NDMsImZpdCI6ImNvbnRhaW4ifX19",
    "https://image.wasi.co/eyJidWNrZXQiOiJzdGF0aWN3Iiwia2V5IjoiaW5tdWVibGVzXC9ncl9zZV92ZW5kZV9oZXJtb3NvX2FwYXJ0YW1lbnRvX2VfMTc2MTM5MjMzMC0wOTc2Xzc1MzcuanBlZyIsImVkaXRzIjp7Im5vcm1hbGlzZSI6dHJ1ZSwicm90YXRlIjowLCJyZXNpemUiOnsid2lkdGgiOjk3OSwiaGVpZ2h0Ijo3NDMsImZpdCI6ImNvbnRhaW4ifX19",
]


def generar_propiedad_pulppo(index):
    """Genera datos de una propiedad de Pulppo"""

    zona = random.choice(ZONAS_MEDELLIN)
    barrio = random.choice(BARRIOS_POR_ZONA[zona])
    tipo = random.choice(TIPOS_PROPIEDAD)
    estrato = random.choice(ESTRATOS)

    # Generar características según el tipo
    if tipo == "Penthouse":
        area = random.randint(150, 300)
        habitaciones = random.randint(3, 5)
        banos = random.randint(3, 5)
        parqueaderos = random.randint(2, 4)
        precio = random.randint(800_000_000, 2_000_000_000)
    elif tipo == "Casa":
        area = random.randint(120, 400)
        habitaciones = random.randint(3, 6)
        banos = random.randint(2, 4)
        parqueaderos = random.randint(2, 4)
        precio = random.randint(400_000_000, 1_500_000_000)
    elif tipo == "Duplex":
        area = random.randint(100, 200)
        habitaciones = random.randint(2, 4)
        banos = random.randint(2, 3)
        parqueaderos = random.randint(1, 2)
        precio = random.randint(300_000_000, 900_000_000)
    else:  # Apartamento
        area = random.randint(60, 150)
        habitaciones = random.randint(2, 4)
        banos = random.randint(1, 3)
        parqueaderos = random.randint(1, 2)
        precio = random.randint(250_000_000, 800_000_000)

    # Generar código único para Pulppo
    codigo = f"PULPPO-{index:05d}"

    # Seleccionar imágenes aleatorias (3-6 imágenes por propiedad)
    num_imagenes = random.randint(3, 6)
    imagenes = random.sample(IMAGENES_DISPONIBLES, min(num_imagenes, len(IMAGENES_DISPONIBLES)))
    imagenes_urls = " | ".join(imagenes)

    # Generar amenidades
    amenidades_internas_opciones = [
        "Cocina integral", "Balcón", "Closets", "Zona de lavandería",
        "Piso en porcelanato", "Ventanas doble vidrio", "Aire acondicionado",
        "Calentador", "Gas natural", "Vestier"
    ]

    amenidades_externas_opciones = [
        "Ascensor", "Vigilancia 24h", "Portería", "Gimnasio", "Piscina",
        "Salón social", "BBQ", "Parqueadero visitantes", "Zona infantil",
        "Cancha deportiva", "Coworking", "Terraza"
    ]

    amenidades_int = " | ".join(random.sample(amenidades_internas_opciones, random.randint(4, 7)))
    amenidades_ext = " | ".join(random.sample(amenidades_externas_opciones, random.randint(5, 9)))

    # Generar descripción
    descripciones = [
        f"Hermoso {tipo.lower()} en {barrio}, {zona}. Excelente ubicación cerca a centros comerciales, colegios y vías principales.",
        f"{tipo} moderno y bien iluminado en {barrio}. Acabados de primera, zona tranquila y segura.",
        f"Espectacular {tipo.lower()} en el sector de {barrio}, {zona}. Cerca a todo lo que necesitas.",
        f"{tipo} en venta en {barrio}, excelente estado y ubicación privilegiada.",
        f"Oportunidad única! {tipo} en {barrio}, {zona}. Listo para habitar."
    ]

    descripcion = random.choice(descripciones)

    # Construir objeto de propiedad
    propiedad = {
        'codigo_propiedad': codigo,
        'fuente': 'Pulppo',
        'url': f'https://pulppo.com/propiedad/{codigo.lower()}',
        'titulo': f'{tipo} en {barrio}, {zona} - {area}m²',
        'precio': precio,
        'precio_texto': f'${precio:,} COP',
        'tipo_propiedad': tipo,
        'estado': 'Disponible',
        'pais': 'Colombia',
        'departamento': 'Antioquia',
        'ciudad': 'Medellín',
        'zona': zona,
        'direccion_completa': f'{barrio}, {zona}, Medellín',
        'latitud': 6.2442 + random.uniform(-0.05, 0.05),  # Coordenadas aleatorias cerca de Medellín
        'longitud': -75.5736 + random.uniform(-0.05, 0.05),
        'area_construida': float(area),
        'habitaciones': habitaciones,
        'banos': banos,
        'parqueaderos': parqueaderos,
        'estrato': estrato,
        'piso': random.randint(1, 15) if tipo in ["Apartamento", "Penthouse", "Duplex"] else None,
        'ano_construccion': random.randint(2010, 2024),
        'caracteristicas_adicionales': f'Estrato {estrato} | {area}m² | {habitaciones} habitaciones | {banos} baños',
        'administracion': random.randint(200_000, 600_000) if tipo != "Casa" else None,
        'predial': random.randint(800_000, 3_000_000),
        'amenidades_internas': amenidades_int,
        'amenidades_externas': amenidades_ext,
        'total_amenidades': len(amenidades_int.split(' | ')) + len(amenidades_ext.split(' | ')),
        'asesor': random.choice(['María González', 'Carlos Pérez', 'Ana Rodríguez', 'Juan Martínez', 'Laura Sánchez']),
        'telefono': f'+573{random.randint(100000000, 999999999)}',
        'inmobiliaria': 'Pulppo Colombia',
        'imagenes_urls': imagenes_urls,
        'total_imagenes': len(imagenes),
        'imagen_principal': imagenes[0],
        'imagenes_hd_count': len(imagenes),
        'imagenes_thumb_count': 0,
        'descripcion': descripcion,
        'descripcion_length': len(descripcion),
        'fecha_extraccion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    return propiedad


def main():
    """Función principal para cargar propiedades"""

    # Preguntar cuántas propiedades generar
    try:
        num_propiedades = int(input("¿Cuántas propiedades de Pulppo deseas cargar? (recomendado: 10-50): "))
        if num_propiedades < 1 or num_propiedades > 1000:
            print("⚠️  Número debe estar entre 1 y 1000")
            return
    except ValueError:
        print("❌ Debes ingresar un número válido")
        return

    print(f"\n🏗️  Generando {num_propiedades} propiedades de Pulppo en Medellín...")
    print()

    # Generar propiedades
    propiedades = []
    for i in range(1, num_propiedades + 1):
        prop = generar_propiedad_pulppo(i)
        propiedades.append(prop)
        print(f"  ✓ Generada: {prop['titulo']} - ${prop['precio']:,}")

    print(f"\n📊 Total propiedades generadas: {len(propiedades)}")
    print()

    # Confirmar antes de guardar
    confirmacion = input("¿Deseas guardar estas propiedades en Neon? (s/n): ").lower()
    if confirmacion != 's':
        print("❌ Operación cancelada")
        return

    print()
    print("💾 Conectando a Neon PostgreSQL...")

    # Guardar en base de datos
    try:
        with DatabaseManager() as db:
            db.create_tables()

            exitosas = 0
            fallidas = 0

            print(f"🗄️  Guardando propiedades en la base de datos...")
            print()

            for prop in propiedades:
                try:
                    prop_id = db.insert_property(prop)
                    if prop_id:
                        exitosas += 1
                    else:
                        fallidas += 1
                except Exception as e:
                    print(f"  ⚠️  Error al guardar {prop['codigo_propiedad']}: {e}")
                    fallidas += 1

            print()
            print("=" * 70)
            print("  RESULTADO DE LA CARGA")
            print("=" * 70)
            print()
            print(f"✅ Propiedades guardadas exitosamente: {exitosas}")
            if fallidas > 0:
                print(f"⚠️  Propiedades con errores: {fallidas}")
            print(f"📊 Total procesadas: {len(propiedades)}")
            print()

            # Obtener estadísticas
            stats = db.get_statistics()
            print("📈 ESTADÍSTICAS DE LA BASE DE DATOS:")
            print()
            print(f"  • Total propiedades: {stats.get('total_propiedades', 0)}")

            if stats.get('por_fuente'):
                print(f"  • Por fuente:")
                for fuente, total in stats['por_fuente'].items():
                    print(f"    - {fuente}: {total}")

            if stats.get('por_ciudad'):
                print(f"  • Propiedades en Medellín: {stats['por_ciudad'].get('Medellín', 0)}")

            print()
            print("=" * 70)
            print()
            print("🎉 ¡Carga completada exitosamente!")
            print()
            print("Puedes consultar las propiedades en:")
            print("  1. Neon SQL Editor")
            print("  2. Python: from database import DatabaseManager")
            print()
            print("Consulta SQL de ejemplo:")
            print("  SELECT titulo, precio, zona FROM propiedades")
            print("  WHERE fuente = 'Pulppo' ORDER BY fecha_creacion DESC;")
            print()

    except Exception as e:
        print(f"❌ Error al conectar con la base de datos: {e}")
        print()
        print("Verifica:")
        print("  1. Que DATABASE_URL esté configurada en .env")
        print("  2. Que psycopg2-binary esté instalado")
        print("  3. Que las tablas estén creadas en Neon (ejecutar schema.sql)")
        print()
        return


if __name__ == "__main__":
    main()
