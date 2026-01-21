#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para verificar el estado de imágenes de propiedades Tu360
"""

import os
import sys
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import requests

# Cargar variables de entorno
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def check_tu360_images():
    """Verifica las imágenes de propiedades Tu360."""
    print("\n" + "=" * 80)
    print("  VERIFICACIÓN DE IMÁGENES TU360")
    print("=" * 80 + "\n")

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()

    # Obtener todas las propiedades Tu360
    cur.execute("""
        SELECT
            id,
            codigo_propiedad,
            titulo,
            imagen_principal,
            imagenes_urls,
            total_imagenes,
            fuente
        FROM propiedades
        WHERE fuente LIKE '%Tu360%'
        ORDER BY id DESC
    """)

    properties = cur.fetchall()

    print(f"Total propiedades Tu360: {len(properties)}\n")

    stats = {
        "with_main_image": 0,
        "with_images_urls": 0,
        "without_images": 0,
        "images_accessible": 0,
        "images_broken": 0,
    }

    for prop in properties:
        codigo = prop['codigo_propiedad']
        titulo = (prop['titulo'] or '')[:40]
        imagen_principal = prop['imagen_principal']
        imagenes_urls = prop['imagenes_urls']
        total = prop['total_imagenes'] or 0

        has_main = bool(imagen_principal)
        has_urls = bool(imagenes_urls)

        if has_main:
            stats["with_main_image"] += 1
        if has_urls:
            stats["with_images_urls"] += 1
        if not has_main and not has_urls:
            stats["without_images"] += 1

        # Contar imágenes en imagenes_urls
        urls_count = len(imagenes_urls.split('|')) if imagenes_urls else 0

        # Verificar accesibilidad de la primera imagen
        image_status = "N/A"
        if imagen_principal:
            try:
                resp = requests.head(imagen_principal, timeout=5, allow_redirects=True)
                if resp.status_code == 200:
                    image_status = "✅ OK"
                    stats["images_accessible"] += 1
                else:
                    image_status = f"❌ {resp.status_code}"
                    stats["images_broken"] += 1
            except Exception as e:
                image_status = f"❌ Error: {str(e)[:20]}"
                stats["images_broken"] += 1

        status_icon = "✅" if has_main else "❌"
        print(f"{status_icon} {codigo}: {titulo}...")
        print(f"   imagen_principal: {imagen_principal[:60] if imagen_principal else 'NULL'}...")
        print(f"   imagenes_urls: {urls_count} URLs ({len(imagenes_urls) if imagenes_urls else 0} chars)")
        print(f"   total_imagenes (db): {total}")
        print(f"   Accesibilidad: {image_status}")
        print()

    # Resumen
    print("\n" + "=" * 80)
    print("  RESUMEN")
    print("=" * 80)
    print(f"  Con imagen_principal: {stats['with_main_image']}/{len(properties)}")
    print(f"  Con imagenes_urls: {stats['with_images_urls']}/{len(properties)}")
    print(f"  Sin imágenes: {stats['without_images']}/{len(properties)}")
    print(f"  Imágenes accesibles: {stats['images_accessible']}/{len(properties)}")
    print(f"  Imágenes rotas: {stats['images_broken']}/{len(properties)}")
    print("=" * 80 + "\n")

    conn.close()

    return properties


def check_specific_property(codigo: str):
    """Verifica una propiedad específica."""
    print(f"\n{'='*80}")
    print(f"  DETALLE DE PROPIEDAD: {codigo}")
    print(f"{'='*80}\n")

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM propiedades
        WHERE codigo_propiedad = %s
    """, (codigo,))

    prop = cur.fetchone()

    if not prop:
        print(f"❌ No se encontró propiedad con código: {codigo}")
        return

    print(f"ID: {prop['id']}")
    print(f"Código: {prop['codigo_propiedad']}")
    print(f"Título: {prop['titulo']}")
    print(f"Fuente: {prop['fuente']}")
    print(f"URL: {prop['url']}")
    print()
    print(f"imagen_principal: {prop['imagen_principal']}")
    print(f"total_imagenes: {prop['total_imagenes']}")
    print()

    imagenes_urls = prop['imagenes_urls']
    if imagenes_urls:
        urls = imagenes_urls.split('|')
        print(f"imagenes_urls ({len(urls)} URLs):")
        for i, url in enumerate(urls[:5], 1):
            print(f"  {i}. {url[:80]}...")
        if len(urls) > 5:
            print(f"  ... y {len(urls) - 5} más")
    else:
        print("imagenes_urls: NULL")

    # Verificar accesibilidad
    print("\n--- Verificando accesibilidad ---")
    if prop['imagen_principal']:
        try:
            resp = requests.get(prop['imagen_principal'], timeout=10, stream=True)
            content_type = resp.headers.get('content-type', 'unknown')
            content_length = resp.headers.get('content-length', 'unknown')
            print(f"imagen_principal:")
            print(f"  Status: {resp.status_code}")
            print(f"  Content-Type: {content_type}")
            print(f"  Content-Length: {content_length}")
        except Exception as e:
            print(f"imagen_principal: Error - {e}")

    conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        check_specific_property(sys.argv[1])
    else:
        check_tu360_images()
