#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba para verificar extracción de imágenes
"""

import requests
from bs4 import BeautifulSoup

# URL de prueba
url = "https://info.wasi.co/penthouse-venta-bel%C3%A9n-nogal-medell%C3%ADn/9512913"

print("🔍 Analizando extracción de imágenes...")
print(f"URL: {url}\n")

# Hacer request
response = requests.get(url, headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})

soup = BeautifulSoup(response.content, 'lxml')

# Buscar contenedor fotorama
fotorama = soup.find('div', class_='fotorama')

if fotorama:
    print("✅ Contenedor .fotorama encontrado\n")

    # Extraer enlaces con imágenes HD
    hd_links = []
    for link in fotorama.find_all('a', href=True):
        href = link.get('href')
        if href and 'image.wasi.co' in href:
            hd_links.append(href)

    print(f"📸 Imágenes HD encontradas: {len(hd_links)}")
    print("\nPrimeras 3 URLs HD:")
    for i, url in enumerate(hd_links[:3], 1):
        print(f"  {i}. {url[:100]}...")

    # Extraer miniaturas
    thumbs = []
    for img in fotorama.find_all('img', src=True):
        src = img.get('src')
        if src and 'image.wasi.co' in src:
            thumbs.append(src)

    print(f"\n🖼️  Miniaturas encontradas: {len(thumbs)}")
    print("\nPrimera miniatura:")
    if thumbs:
        print(f"  {thumbs[0][:100]}...")

    # Comparación
    print(f"\n📊 RESUMEN:")
    print(f"  • Total imágenes HD: {len(hd_links)}")
    print(f"  • Total miniaturas: {len(thumbs)}")
    print(f"  • ✅ Extrayendo imágenes en ALTA RESOLUCIÓN")

else:
    print("❌ Contenedor .fotorama NO encontrado")
    print("Buscando alternativas...")

    # Buscar en Gallery
    gallery = soup.find('div', class_='Gallery')
    if gallery:
        print("✅ Contenedor .Gallery encontrado")
    else:
        print("❌ Contenedor .Gallery NO encontrado")

print("\n✅ Test completado")
