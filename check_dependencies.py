#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para verificar dependencias del Wasi Scraper
"""

import sys

print("=" * 60)
print("  VERIFICACIÓN DE DEPENDENCIAS - WASI SCRAPER")
print("=" * 60)
print()

# Lista de dependencias requeridas
dependencies = {
    'requests': 'requests',
    'bs4': 'beautifulsoup4',
    'pandas': 'pandas',
    'lxml': 'lxml',
    'openpyxl': 'openpyxl',
    'tqdm': 'tqdm'
}

missing = []
installed = []

print("Verificando módulos de Python...\n")

for module, package in dependencies.items():
    try:
        __import__(module)
        print(f"✓ {package:<20} - INSTALADO")
        installed.append(package)
    except ImportError:
        print(f"✗ {package:<20} - FALTA")
        missing.append(package)

print()
print("=" * 60)
print(f"Resumen: {len(installed)}/{len(dependencies)} módulos instalados")
print("=" * 60)
print()

if missing:
    print("⚠️  FALTAN LAS SIGUIENTES DEPENDENCIAS:")
    print()
    for package in missing:
        print(f"  • {package}")
    print()
    print("Para instalarlas, ejecuta uno de estos comandos:")
    print()
    print("Opción 1 - Con entorno virtual (Recomendado):")
    print("  ./setup.sh")
    print()
    print("Opción 2 - Instalación directa:")
    print("  pip3 install --user " + " ".join(missing))
    print()
    print("Opción 3 - Todas las dependencias:")
    print("  pip3 install --user -r requirements.txt")
    print()
    sys.exit(1)
else:
    print("✅ TODAS LAS DEPENDENCIAS ESTÁN INSTALADAS")
    print()
    print("¡Puedes ejecutar el scraper con:")
    print("  python3 scrapper_wasi.py")
    print()
    sys.exit(0)
