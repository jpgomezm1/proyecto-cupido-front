#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para cargar propiedades de Wasi desde el archivo de carga inicial
1. Limpia la tabla de propiedades
2. Lee las URLs del archivo .txt
3. Scrapea cada URL y guarda en la base de datos
"""

import os
import re
import time
from database import DatabaseManager
from scrapper_wasi import WasiScraper
from datetime import datetime


def limpiar_base_datos():
    """
    Limpia todas las propiedades de la base de datos
    """
    print("=" * 80)
    print("LIMPIANDO BASE DE DATOS")
    print("=" * 80)

    db = DatabaseManager()
    db.connect()

    try:
        # Primero mostrar cuántas propiedades hay
        db.cursor.execute("SELECT COUNT(*) as count FROM propiedades")
        count = db.cursor.fetchone()['count']
        print(f"\n⚠️  Se encontraron {count} propiedades en la base de datos.")

        # Confirmar antes de borrar
        confirmacion = input("\n¿Estás seguro de que quieres ELIMINAR TODAS las propiedades? (escribe 'SI' para confirmar): ")

        if confirmacion.strip().upper() != 'SI':
            print("❌ Operación cancelada. No se eliminó ninguna propiedad.")
            db.disconnect()
            return False

        # Ejecutar TRUNCATE para limpiar completamente la tabla
        print("\n🗑️  Eliminando todas las propiedades...")
        db.cursor.execute("TRUNCATE TABLE propiedades RESTART IDENTITY CASCADE")
        db.conn.commit()

        # Verificar que se limpiaron
        db.cursor.execute("SELECT COUNT(*) as count FROM propiedades")
        count_despues = db.cursor.fetchone()['count']

        print(f"✅ Base de datos limpiada exitosamente. Propiedades restantes: {count_despues}")
        db.disconnect()
        return True

    except Exception as e:
        print(f"❌ Error limpiando la base de datos: {str(e)}")
        db.disconnect()
        return False


def leer_urls_archivo(archivo_path):
    """
    Lee las URLs del archivo .txt

    Args:
        archivo_path (str): Ruta al archivo .txt

    Returns:
        list: Lista de URLs únicas
    """
    print("\n" + "=" * 80)
    print("LEYENDO URLS DEL ARCHIVO")
    print("=" * 80)

    urls = []

    try:
        with open(archivo_path, 'r', encoding='utf-8-sig') as f:
            for linea in f:
                # Buscar URLs en cada línea
                matches = re.findall(r'https?://[^\s]+', linea)
                for url in matches:
                    # Limpiar la URL (remover caracteres extraños al final)
                    url = url.strip()
                    if url and url not in urls:
                        urls.append(url)

        print(f"\n✅ Se encontraron {len(urls)} URLs únicas en el archivo")
        return urls

    except Exception as e:
        print(f"❌ Error leyendo el archivo: {str(e)}")
        return []


def guardar_propiedad_db(data_propiedad):
    """
    Guarda una propiedad en la base de datos

    Args:
        data_propiedad (dict): Datos de la propiedad

    Returns:
        bool: True si se guardó exitosamente
    """
    db = DatabaseManager()
    db.connect()

    try:
        # Preparar los datos para inserción
        query = """
            INSERT INTO propiedades (
                url, codigo_propiedad, titulo, tipo_propiedad, precio, ciudad, zona,
                area_construida, habitaciones, banos, parqueaderos, estrato,
                ano_construccion, administracion, descripcion, direccion_completa,
                latitud, longitud, estado, caracteristicas_adicionales,
                imagen_principal, imagenes_urls, fuente, activa,
                fecha_extraccion, fecha_creacion, fecha_actualizacion
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """

        # Extraer y limpiar datos
        url = data_propiedad.get('url', '')  # URL de la propiedad (requerido)
        codigo = data_propiedad.get('codigo_propiedad') or data_propiedad.get('url', '').split('/')[-1].split('?')[0]
        titulo = data_propiedad.get('titulo', 'Sin título')
        tipo_propiedad = data_propiedad.get('tipo_propiedad', 'Apartamento')
        precio = data_propiedad.get('precio', 0)
        ciudad = data_propiedad.get('ciudad', 'Medellín')
        zona = data_propiedad.get('zona') or data_propiedad.get('barrio', 'Sin especificar')
        area = data_propiedad.get('area_construida', 0)
        habitaciones = data_propiedad.get('habitaciones', 0)
        banos = data_propiedad.get('banos', 0)
        parqueaderos = data_propiedad.get('parqueaderos', 0)
        estrato = data_propiedad.get('estrato')
        ano_construccion = data_propiedad.get('ano_construccion')
        administracion = data_propiedad.get('administracion')
        descripcion = data_propiedad.get('descripcion', '')
        direccion = data_propiedad.get('direccion_completa', '')
        latitud = data_propiedad.get('latitud')
        longitud = data_propiedad.get('longitud')
        estado = data_propiedad.get('estado', 'Disponible')

        # Amenidades como string separado por comas
        amenidades = data_propiedad.get('amenidades', [])
        if isinstance(amenidades, list):
            caracteristicas = ', '.join(amenidades) if amenidades else None
        else:
            caracteristicas = amenidades

        # Imágenes - el scraper ya las devuelve en el formato correcto
        imagen_principal = data_propiedad.get('imagen_principal')
        imagenes_urls = data_propiedad.get('imagenes_urls')

        fuente = data_propiedad.get('fuente', 'Wasi')

        valores = (
            url, codigo, titulo, tipo_propiedad, precio, ciudad, zona, area,
            habitaciones, banos, parqueaderos, estrato, ano_construccion,
            administracion, descripcion, direccion, latitud, longitud,
            estado, caracteristicas, imagen_principal, imagenes_urls,
            fuente, True  # activa = True
        )

        db.cursor.execute(query, valores)
        db.conn.commit()
        db.disconnect()
        return True

    except Exception as e:
        print(f"    ❌ Error guardando en BD: {str(e)}")
        db.disconnect()
        return False


def cargar_propiedades_desde_urls(urls):
    """
    Carga todas las propiedades desde una lista de URLs

    Args:
        urls (list): Lista de URLs de Wasi
    """
    print("\n" + "=" * 80)
    print("INICIANDO CARGA DE PROPIEDADES")
    print("=" * 80)

    scraper = WasiScraper(delay=3, verbose=True)

    exitosas = 0
    fallidas = 0

    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] Procesando: {url}")
        print("-" * 80)

        # Scrapear la propiedad
        data = scraper.extract_property_data(url)

        if data:
            # Guardar en la base de datos
            if guardar_propiedad_db(data):
                exitosas += 1
                print(f"    ✅ Propiedad guardada exitosamente ({exitosas}/{len(urls)})")
            else:
                fallidas += 1
                print(f"    ❌ Error guardando en la base de datos")
        else:
            fallidas += 1
            print(f"    ❌ Error scrapeando la propiedad")

        # Delay entre requests
        if i < len(urls):
            print(f"    ⏳ Esperando {scraper.delay} segundos...")
            time.sleep(scraper.delay)

    # Resumen final
    print("\n" + "=" * 80)
    print("RESUMEN DE CARGA")
    print("=" * 80)
    print(f"✅ Propiedades cargadas exitosamente: {exitosas}")
    print(f"❌ Propiedades fallidas: {fallidas}")
    print(f"📊 Total procesado: {len(urls)}")
    print(f"✅ Tasa de éxito: {(exitosas/len(urls)*100):.1f}%")


def main():
    """
    Función principal que ejecuta todo el proceso
    """
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 20 + "CARGA INICIAL DE PROPIEDADES WASI" + " " * 24 + "║")
    print("╚" + "═" * 78 + "╝")

    # Ruta al archivo de URLs
    archivo_urls = os.path.join(
        os.path.dirname(__file__),
        'carga_inicial',
        'Carga Inicial Wasi.txt'
    )

    if not os.path.exists(archivo_urls):
        print(f"❌ Error: No se encontró el archivo {archivo_urls}")
        return

    # Paso 1: Limpiar base de datos
    if not limpiar_base_datos():
        print("\n❌ Proceso cancelado.")
        return

    # Paso 2: Leer URLs del archivo
    urls = leer_urls_archivo(archivo_urls)

    if not urls:
        print("❌ No se encontraron URLs para procesar.")
        return

    # Paso 3: Cargar propiedades
    cargar_propiedades_desde_urls(urls)

    print("\n✅ Proceso completado!")
    print("=" * 80)


if __name__ == "__main__":
    main()
