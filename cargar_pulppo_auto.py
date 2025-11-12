#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script automático para cargar propiedades de Pulppo (sin interacción)
Ejecutar: python cargar_pulppo_auto.py
"""

from database import DatabaseManager
from datetime import datetime
import random

# CONFIGURACIÓN: Cambia este número para cargar más o menos propiedades
NUM_PROPIEDADES = 20  # Por defecto 20 propiedades

print("=" * 70)
print("  CARGA AUTOMÁTICA DE PROPIEDADES PULPPO - MEDELLÍN")
print("=" * 70)
print()
print(f"⚙️  Configuración: Se cargarán {NUM_PROPIEDADES} propiedades")
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

# URLs de imágenes HD de Wasi (reutilizadas)
IMAGENES_DISPONIBLES = [
    "https://image.wasi.co/eyJidWNrZXQiOiJzdGF0aWN3Iiwia2V5IjoiaW5tdWVibGVzXC9ncjIzNDk2MTUyMDI1MTAwODEwMTIxMS5qcGciLCJlZGl0cyI6eyJub3JtYWxpc2UiOnRydWUsInJvdGF0ZSI6MCwicmVzaXplIjp7IndpZHRoIjo5NzksImhlaWdodCI6NzQzLCJmaXQiOiJjb250YWluIn19fQ==",
    "https://image.wasi.co/eyJidWNrZXQiOiJzdGF0aWN3Iiwia2V5IjoiaW5tdWVibGVzXC9ncjIzNDk2NzIwMjUxMDA4MTAxMjA4LmpwZyIsImVkaXRzIjp7Im5vcm1hbGlzZSI6dHJ1ZSwicm90YXRlIjowLCJyZXNpemUiOnsid2lkdGgiOjk3OSwiaGVpZ2h0Ijo3NDMsImZpdCI6ImNvbnRhaW4ifX19",
    "https://image.wasi.co/eyJidWNrZXQiOiJzdGF0aWN3Iiwia2V5IjoiaW5tdWVibGVzXC9ncjIzNDk2MTEyMDI1MTAwODEwMTIxMC5qcGciLCJlZGl0cyI6eyJub3JtYWxpc2UiOnRydWUsInJvdGF0ZSI6MCwicmVzaXplIjp7IndpZHRoIjo5NzksImhlaWdodCI6NzQzLCJmaXQiOiJjb250YWluIn19fQ==",
    "https://image.wasi.co/eyJidWNrZXQiOiJzdGF0aWN3Iiwia2V5IjoiaW5tdWVibGVzXC9ncl9zZV92ZW5kZV9oZXJtb3NvX2FwYXJ0YW1lbnRvX2VfMTc2MTM5MjQxNi0xOTI0Xzc0MTIuanBlZyIsImVkaXRzIjp7Im5vcm1hbGlzZSI6dHJ1ZSwicm90YXRlIjowLCJyZXNpemUiOnsid2lkdGgiOjk3OSwiaGVpZ2h0Ijo3NDMsImZpdCI6ImNvbnRhaW4ifX19",
    "https://image.wasi.co/eyJidWNrZXQiOiJzdGF0aWN3Iiwia2V5IjoiaW5tdWVibGVzXC9ncl9zZV92ZW5kZV9oZXJtb3NvX2FwYXJ0YW1lbnRvX2VfMTc2MTM5MjMzMC0wOTc2Xzc1MzcuanBlZyIsImVkaXRzIjp7Im5vcm1hbGlzZSI6dHJ1ZSwicm90YXRlIjowLCJyZXNpemUiOnsid2lkdGgiOjk3OSwiaGVpZ2h0Ijo3NDMsImZpdCI6ImNvbnRhaW4ifX19",
]


def generar_propiedad_pulppo(index):
    """Genera datos de una propiedad de Pulppo"""
    zona = random.choice(ZONAS_MEDELLIN)
    barrio = random.choice(BARRIOS_POR_ZONA[zona])
    tipo = random.choice(TIPOS_PROPIEDAD)
    estrato = random.choice(ESTRATOS)

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
    else:
        area = random.randint(60, 150)
        habitaciones = random.randint(2, 4)
        banos = random.randint(1, 3)
        parqueaderos = random.randint(1, 2)
        precio = random.randint(250_000_000, 800_000_000)

    codigo = f"PULPPO-{index:05d}"
    num_imagenes = random.randint(3, 6)
    imagenes = random.sample(IMAGENES_DISPONIBLES, min(num_imagenes, len(IMAGENES_DISPONIBLES)))
    imagenes_urls = " | ".join(imagenes)

    amenidades_int = " | ".join(random.sample([
        "Cocina integral", "Balcón", "Closets", "Zona de lavandería",
        "Piso en porcelanato", "Ventanas doble vidrio", "Aire acondicionado",
        "Calentador", "Gas natural", "Vestier"
    ], random.randint(4, 7)))

    amenidades_ext = " | ".join(random.sample([
        "Ascensor", "Vigilancia 24h", "Portería", "Gimnasio", "Piscina",
        "Salón social", "BBQ", "Parqueadero visitantes", "Zona infantil",
        "Cancha deportiva", "Coworking", "Terraza"
    ], random.randint(5, 9)))

    descripciones = [
        f"Hermoso {tipo.lower()} en {barrio}, {zona}. Excelente ubicación cerca a centros comerciales, colegios y vías principales.",
        f"{tipo} moderno y bien iluminado en {barrio}. Acabados de primera, zona tranquila y segura.",
        f"Espectacular {tipo.lower()} en el sector de {barrio}, {zona}. Cerca a todo lo que necesitas.",
    ]

    return {
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
        'latitud': 6.2442 + random.uniform(-0.05, 0.05),
        'longitud': -75.5736 + random.uniform(-0.05, 0.05),
        'area_construida': float(area),
        'habitaciones': habitaciones,
        'banos': banos,
        'parqueaderos': parqueaderos,
        'estrato': estrato,
        'piso': random.randint(1, 15) if tipo in ["Apartamento", "Penthouse", "Duplex"] else None,
        'ano_construccion': random.randint(2010, 2024),
        'caracteristicas_adicionales': f'Estrato {estrato} | {area}m² | {habitaciones} hab | {banos} baños',
        'administracion': random.randint(200_000, 600_000) if tipo != "Casa" else None,
        'predial': random.randint(800_000, 3_000_000),
        'amenidades_internas': amenidades_int,
        'amenidades_externas': amenidades_ext,
        'total_amenidades': len(amenidades_int.split(' | ')) + len(amenidades_ext.split(' | ')),
        'asesor': random.choice(['María González', 'Carlos Pérez', 'Ana Rodríguez', 'Juan Martínez']),
        'telefono': f'+573{random.randint(100000000, 999999999)}',
        'inmobiliaria': 'Pulppo Colombia',
        'imagenes_urls': imagenes_urls,
        'total_imagenes': len(imagenes),
        'imagen_principal': imagenes[0],
        'imagenes_hd_count': len(imagenes),
        'imagenes_thumb_count': 0,
        'descripcion': random.choice(descripciones),
        'descripcion_length': len(random.choice(descripciones)),
        'fecha_extraccion': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }


# Generar propiedades
print(f"🏗️  Generando {NUM_PROPIEDADES} propiedades...")
propiedades = []
for i in range(1, NUM_PROPIEDADES + 1):
    prop = generar_propiedad_pulppo(i)
    propiedades.append(prop)
    print(f"  ✓ {prop['titulo']} - ${prop['precio']:,}")

print()
print("💾 Conectando a Neon PostgreSQL...")

# Guardar en DB
try:
    with DatabaseManager() as db:
        db.create_tables()

        exitosas = 0
        fallidas = 0

        print(f"🗄️  Guardando {len(propiedades)} propiedades...")
        print()

        for prop in propiedades:
            prop_id = db.insert_property(prop)
            if prop_id:
                exitosas += 1
            else:
                fallidas += 1

        print()
        print("=" * 70)
        print(f"✅ Propiedades guardadas: {exitosas}")
        if fallidas > 0:
            print(f"⚠️  Errores: {fallidas}")

        stats = db.get_statistics()
        print()
        print(f"📊 Total propiedades en DB: {stats.get('total_propiedades', 0)}")
        if stats.get('por_fuente'):
            for fuente, total in stats['por_fuente'].items():
                print(f"   • {fuente}: {total}")

        print()
        print("🎉 ¡Carga completada!")
        print("=" * 70)

except Exception as e:
    print(f"❌ Error: {e}")
    print("\nVerifica:")
    print("  1. DATABASE_URL en .env")
    print("  2. pip install psycopg2-binary python-dotenv")
    print("  3. Tablas creadas en Neon (schema.sql)")
