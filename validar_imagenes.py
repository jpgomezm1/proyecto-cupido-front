#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para validar que las imágenes extraídas sean de alta resolución
"""

import pandas as pd
import glob
import re

print("=" * 60)
print("  VALIDACIÓN DE IMÁGENES EXTRAÍDAS")
print("=" * 60)
print()

# Buscar el CSV más reciente
csv_files = glob.glob('data/propiedades_wasi_*.csv')
if not csv_files:
    print("❌ No se encontraron archivos CSV en la carpeta data/")
    print("Ejecuta primero: python scrapper_wasi.py")
    exit(1)

latest_csv = sorted(csv_files)[-1]
print(f"📁 Archivo: {latest_csv}")
print()

# Leer CSV
df = pd.read_csv(latest_csv)

print(f"📊 Total de propiedades: {len(df)}")
print()

# Verificar columnas de imágenes
if 'total_imagenes' in df.columns:
    print("✅ Columna 'total_imagenes' encontrada")
    print(f"   • Promedio de imágenes por propiedad: {df['total_imagenes'].mean():.1f}")
    print(f"   • Mínimo: {df['total_imagenes'].min()}")
    print(f"   • Máximo: {df['total_imagenes'].max()}")
else:
    print("❌ Columna 'total_imagenes' NO encontrada")

print()

# Verificar imágenes HD
if 'imagenes_hd_count' in df.columns:
    print("✅ Columna 'imagenes_hd_count' encontrada (nueva!)")
    hd_count = df['imagenes_hd_count'].sum()
    thumb_count = df['imagenes_thumb_count'].sum() if 'imagenes_thumb_count' in df.columns else 0
    print(f"   • Total imágenes HD: {hd_count}")
    print(f"   • Total miniaturas: {thumb_count}")
    print(f"   • Ratio HD: {hd_count/(hd_count+thumb_count)*100:.1f}%")
else:
    print("⚠️  Columna 'imagenes_hd_count' NO encontrada")
    print("   (Esta columna solo aparece con el scraper mejorado)")

print()

# Analizar URLs de imágenes
if 'imagenes_urls' in df.columns and not df['imagenes_urls'].isna().all():
    print("✅ Columna 'imagenes_urls' encontrada")

    # Tomar primera propiedad con imágenes
    for idx, row in df.iterrows():
        if pd.notna(row['imagenes_urls']):
            urls = row['imagenes_urls'].split(' | ')
            first_url = urls[0]

            print(f"\n📸 Análisis de imágenes de propiedad #{idx + 1}:")
            print(f"   • Total URLs: {len(urls)}")
            print(f"   • Primera URL: {first_url[:80]}...")

            # Detectar resolución aproximada
            if 'width":156' in first_url or 'height":117' in first_url:
                print(f"   ⚠️  RESOLUCIÓN: Miniatura (156x117) - ¡NECESITA MEJORA!")
            elif 'width":979' in first_url or 'width":800' in first_url:
                print(f"   ✅ RESOLUCIÓN: Alta (979x743 o superior) - ¡PERFECTO!")
            else:
                print(f"   ℹ️  RESOLUCIÓN: No detectada automáticamente")

            break
else:
    print("❌ Columna 'imagenes_urls' vacía o no encontrada")

print()
print("=" * 60)

# Resumen final
print("\n🎯 RESUMEN:")
total_imgs = df['total_imagenes'].sum() if 'total_imagenes' in df.columns else 0
print(f"   • Total imágenes extraídas: {total_imgs}")

if 'imagenes_hd_count' in df.columns:
    hd_total = df['imagenes_hd_count'].sum()
    if hd_total > 0:
        print(f"   ✅ Extracción en ALTA RESOLUCIÓN funcionando correctamente")
    else:
        print(f"   ⚠️  No se encontraron imágenes HD (revisar scraper)")
else:
    print(f"   ℹ️  Ejecuta el scraper mejorado para obtener imágenes HD")

print()
