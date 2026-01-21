#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para actualizar las imágenes de todas las propiedades Tu360.

Este script:
1. Obtiene todas las propiedades de Tu360 de la base de datos
2. Re-scrapea cada propiedad para obtener las imágenes actualizadas
3. Actualiza la base de datos con las nuevas URLs de imágenes

Uso:
    python scripts/update_tu360_images.py          # Ver estado sin actualizar
    python scripts/update_tu360_images.py --update # Actualizar las imágenes
    python scripts/update_tu360_images.py --code DCN-672  # Actualizar solo una propiedad
"""

import os
import sys
import argparse
import time
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import requests
import json
import re

# Cargar variables de entorno
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Colores para output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def get_connection():
    """Obtiene conexión a la base de datos."""
    if not DATABASE_URL:
        print(f"{Colors.RED}Error: DATABASE_URL no está configurada en .env{Colors.END}")
        sys.exit(1)
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def scrape_tu360_images(url: str) -> dict:
    """
    Extrae las imágenes de una propiedad de Tu360.

    Args:
        url: URL de la propiedad en Tu360

    Returns:
        Dict con imagen_principal e imagenes_urls, o None si falla
    """
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

        response = session.get(url, timeout=15)
        response.raise_for_status()
        html = response.text

        # Extraer __NEXT_DATA__
        pattern = r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>'
        match = re.search(pattern, html, re.DOTALL)

        if not match:
            return None

        data = json.loads(match.group(1))
        pictures = data.get('props', {}).get('pageProps', {}).get('property', {}).get('pictures', [])

        if not pictures:
            return None

        # Extraer URLs de imágenes
        image_urls = [p.get('url') for p in pictures if p.get('url')]

        if not image_urls:
            return None

        return {
            'imagen_principal': image_urls[0],
            'imagenes_urls': '|'.join(image_urls),
            'total_imagenes': len(image_urls)
        }

    except Exception as e:
        print(f"{Colors.RED}  Error scrapeando: {e}{Colors.END}")
        return None


def get_tu360_properties(conn, codigo=None):
    """Obtiene las propiedades de Tu360."""
    cur = conn.cursor()

    if codigo:
        query = """
            SELECT
                id,
                codigo_propiedad,
                titulo,
                url,
                imagen_principal,
                imagenes_urls,
                total_imagenes
            FROM propiedades
            WHERE fuente LIKE '%Tu360%' AND codigo_propiedad = %s
            ORDER BY id DESC
        """
        cur.execute(query, (codigo,))
    else:
        query = """
            SELECT
                id,
                codigo_propiedad,
                titulo,
                url,
                imagen_principal,
                imagenes_urls,
                total_imagenes
            FROM propiedades
            WHERE fuente LIKE '%Tu360%'
            ORDER BY id DESC
        """
        cur.execute(query)

    return cur.fetchall()


def update_property_images(conn, property_id: int, images: dict):
    """Actualiza las imágenes de una propiedad."""
    cur = conn.cursor()

    cur.execute("""
        UPDATE propiedades
        SET
            imagen_principal = %s,
            imagenes_urls = %s,
            total_imagenes = %s,
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (
        images['imagen_principal'],
        images['imagenes_urls'],
        images['total_imagenes'],
        property_id
    ))

    conn.commit()


def check_image_accessibility(url: str) -> tuple:
    """Verifica si una imagen es accesible."""
    try:
        resp = requests.head(url, timeout=5, allow_redirects=True)
        return resp.status_code == 200, resp.status_code
    except Exception as e:
        return False, str(e)


def show_status(conn, codigo=None):
    """Muestra el estado de las propiedades Tu360."""
    properties = get_tu360_properties(conn, codigo)

    print(f"\n{Colors.BOLD}{'='*80}{Colors.END}")
    print(f"{Colors.BOLD}  ESTADO DE PROPIEDADES TU360{Colors.END}")
    print(f"{Colors.BOLD}{'='*80}{Colors.END}\n")

    stats = {
        'total': len(properties),
        'with_images': 0,
        'without_images': 0,
        'accessible': 0,
        'broken': 0
    }

    for prop in properties:
        codigo = prop['codigo_propiedad']
        titulo = (prop['titulo'] or '')[:40]
        url = prop['url']
        has_main = bool(prop['imagen_principal'])
        has_urls = bool(prop['imagenes_urls'])
        total = prop['total_imagenes'] or 0

        if has_main:
            stats['with_images'] += 1
            accessible, status = check_image_accessibility(prop['imagen_principal'])
            if accessible:
                stats['accessible'] += 1
                status_icon = f"{Colors.GREEN}✓{Colors.END}"
            else:
                stats['broken'] += 1
                status_icon = f"{Colors.RED}✗ ({status}){Colors.END}"
        else:
            stats['without_images'] += 1
            status_icon = f"{Colors.YELLOW}○ (sin imagen){Colors.END}"

        print(f"{status_icon} {codigo}: {titulo}...")
        print(f"   URL: {url[:60]}...")
        print(f"   Imágenes: {total}")
        print()

    print(f"{Colors.BOLD}{'='*80}{Colors.END}")
    print(f"  Total: {stats['total']}")
    print(f"  {Colors.GREEN}Con imágenes: {stats['with_images']}{Colors.END}")
    print(f"  {Colors.YELLOW}Sin imágenes: {stats['without_images']}{Colors.END}")
    print(f"  {Colors.GREEN}Accesibles: {stats['accessible']}{Colors.END}")
    print(f"  {Colors.RED}Rotas: {stats['broken']}{Colors.END}")
    print(f"{Colors.BOLD}{'='*80}{Colors.END}\n")

    return properties


def update_all_images(conn, properties, dry_run=True):
    """Actualiza las imágenes de todas las propiedades."""
    print(f"\n{Colors.BOLD}{'='*80}{Colors.END}")
    if dry_run:
        print(f"{Colors.BOLD}  SIMULACIÓN DE ACTUALIZACIÓN (--update para aplicar){Colors.END}")
    else:
        print(f"{Colors.BOLD}  ACTUALIZANDO IMÁGENES DE TU360{Colors.END}")
    print(f"{Colors.BOLD}{'='*80}{Colors.END}\n")

    success_count = 0
    error_count = 0
    skip_count = 0

    for i, prop in enumerate(properties, 1):
        codigo = prop['codigo_propiedad']
        url = prop['url']

        print(f"[{i}/{len(properties)}] {codigo}...")

        if not url:
            print(f"  {Colors.YELLOW}⚠ Sin URL, saltando{Colors.END}")
            skip_count += 1
            continue

        # Scrape nuevas imágenes
        print(f"  Scrapeando {url[:50]}...")
        images = scrape_tu360_images(url)

        if not images:
            print(f"  {Colors.RED}✗ No se pudieron obtener imágenes{Colors.END}")
            error_count += 1
            continue

        print(f"  {Colors.GREEN}✓ Encontradas {images['total_imagenes']} imágenes{Colors.END}")

        if not dry_run:
            update_property_images(conn, prop['id'], images)
            print(f"  {Colors.GREEN}✓ Base de datos actualizada{Colors.END}")
        else:
            print(f"  {Colors.YELLOW}⚠ Dry run - no se actualizó{Colors.END}")

        success_count += 1

        # Pequeña pausa para no saturar el servidor
        time.sleep(0.5)
        print()

    print(f"{Colors.BOLD}{'='*80}{Colors.END}")
    print(f"  {Colors.GREEN}Exitosos: {success_count}{Colors.END}")
    print(f"  {Colors.RED}Errores: {error_count}{Colors.END}")
    print(f"  {Colors.YELLOW}Saltados: {skip_count}{Colors.END}")
    print(f"{Colors.BOLD}{'='*80}{Colors.END}\n")


def main():
    parser = argparse.ArgumentParser(description='Actualizar imágenes de propiedades Tu360')
    parser.add_argument('--update', action='store_true', help='Ejecutar la actualización (sin esto solo muestra estado)')
    parser.add_argument('--code', metavar='CODIGO', help='Actualizar solo una propiedad específica')

    args = parser.parse_args()

    try:
        conn = get_connection()

        # Mostrar estado actual
        properties = show_status(conn, args.code)

        if not properties:
            print(f"{Colors.YELLOW}No se encontraron propiedades Tu360{Colors.END}")
            return

        # Si se pidió actualizar
        if args.update or args.code:
            dry_run = not args.update
            update_all_images(conn, properties, dry_run=dry_run)
        else:
            print(f"\n{Colors.YELLOW}Para actualizar las imágenes, ejecuta:{Colors.END}")
            print(f"  python scripts/update_tu360_images.py --update")
            print(f"\n{Colors.YELLOW}Para actualizar solo una propiedad:{Colors.END}")
            print(f"  python scripts/update_tu360_images.py --code DCN-672 --update\n")

        conn.close()

    except psycopg2.OperationalError as e:
        print(f"\n{Colors.RED}Error de conexión a la base de datos:{Colors.END}")
        print(f"  {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}Error inesperado: {e}{Colors.END}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
