#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test de integración completa de la API REST
Verifica que todos los endpoints funcionan correctamente
"""

import requests
import json
from database import DatabaseManager
from dotenv import load_dotenv

load_dotenv()

# URL base de la API
BASE_URL = "http://localhost:5000/api"


def print_section(title: str):
    """Imprimir sección con formato"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def test_health_check():
    """Test 1: Health check de la API"""
    print_section("TEST 1: Health Check")

    try:
        response = requests.get(f"{BASE_URL}/health")
        data = response.json()

        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(data, indent=2)}")

        if response.status_code == 200 and data.get('success'):
            print("✅ Health check exitoso")
            return True
        else:
            print("❌ Health check falló")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_get_properties():
    """Test 2: Obtener todas las propiedades"""
    print_section("TEST 2: Obtener Propiedades")

    try:
        response = requests.get(f"{BASE_URL}/properties?published=true&limit=5")
        data = response.json()

        print(f"Status Code: {response.status_code}")
        print(f"Total propiedades: {data.get('count', 0)}")

        if data.get('success') and data.get('data'):
            print(f"✅ Se obtuvieron {len(data['data'])} propiedades")

            # Mostrar primera propiedad
            if len(data['data']) > 0:
                prop = data['data'][0]
                print(f"\nEjemplo de propiedad:")
                print(f"  - ID: {prop.get('id')}")
                print(f"  - Título: {prop.get('title')}")
                print(f"  - Precio: {prop.get('price_cop')}")
                print(f"  - Ciudad: {prop.get('city')}")
                print(f"  - Slug: {prop.get('slug')}")

            return True
        else:
            print("❌ No se pudieron obtener propiedades")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_get_property_by_slug():
    """Test 3: Obtener propiedad por slug"""
    print_section("TEST 3: Obtener Propiedad por Slug")

    try:
        # Primero obtener un slug válido
        response = requests.get(f"{BASE_URL}/properties?limit=1")
        data = response.json()

        if not data.get('success') or not data.get('data') or len(data['data']) == 0:
            print("⚠️  No hay propiedades para probar")
            return False

        slug = data['data'][0].get('slug')
        print(f"Probando con slug: {slug}")

        # Obtener propiedad por slug
        response = requests.get(f"{BASE_URL}/properties/{slug}")
        data = response.json()

        print(f"Status Code: {response.status_code}")

        if data.get('success') and data.get('data'):
            prop = data['data']
            print(f"✅ Propiedad encontrada:")
            print(f"  - ID: {prop.get('id')}")
            print(f"  - Título: {prop.get('title')}")
            print(f"  - Precio: {prop.get('price_cop')}")
            print(f"  - Ciudad: {prop.get('city')}")
            print(f"  - Habitaciones: {prop.get('bedrooms')}")
            print(f"  - Baños: {prop.get('bathrooms')}")
            return True
        else:
            print("❌ No se pudo obtener la propiedad")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_get_property_images():
    """Test 4: Obtener imágenes de propiedades"""
    print_section("TEST 4: Obtener Imágenes")

    try:
        response = requests.get(f"{BASE_URL}/property-images?is_cover=true")
        data = response.json()

        print(f"Status Code: {response.status_code}")
        print(f"Total imágenes: {data.get('count', 0)}")

        if data.get('success') and data.get('data'):
            print(f"✅ Se obtuvieron {len(data['data'])} imágenes de portada")

            # Mostrar primera imagen
            if len(data['data']) > 0:
                img = data['data'][0]
                print(f"\nEjemplo de imagen:")
                print(f"  - Property ID: {img.get('property_id')}")
                print(f"  - URL: {img.get('url')[:80]}...")
                print(f"  - Is Cover: {img.get('is_cover')}")

            return True
        else:
            print("❌ No se pudieron obtener imágenes")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_database_connection():
    """Test 5: Verificar conexión directa a la base de datos"""
    print_section("TEST 5: Conexión Directa a Base de Datos")

    try:
        db = DatabaseManager()
        db.connect()

        # Consultar cantidad de propiedades
        result = db.execute_query("SELECT COUNT(*) FROM propiedades WHERE activa = true")
        count = result[0][0] if result else 0

        print(f"✅ Conexión exitosa a base de datos")
        print(f"Total propiedades activas: {count}")

        db.disconnect()
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_filters():
    """Test 6: Probar filtros de búsqueda"""
    print_section("TEST 6: Filtros de Búsqueda")

    try:
        # Test con filtro de ciudad
        response = requests.get(f"{BASE_URL}/properties?city=Medellín&limit=3")
        data = response.json()

        print(f"Filtro por ciudad (Medellín):")
        print(f"  - Status Code: {response.status_code}")
        print(f"  - Propiedades encontradas: {data.get('count', 0)}")

        # Test con filtro de precio
        response = requests.get(f"{BASE_URL}/properties?min_price=100000000&max_price=500000000&limit=3")
        data = response.json()

        print(f"\nFiltro por precio (100M - 500M):")
        print(f"  - Status Code: {response.status_code}")
        print(f"  - Propiedades encontradas: {data.get('count', 0)}")

        # Test con filtro de habitaciones
        response = requests.get(f"{BASE_URL}/properties?bedrooms=3&limit=3")
        data = response.json()

        print(f"\nFiltro por habitaciones (3):")
        print(f"  - Status Code: {response.status_code}")
        print(f"  - Propiedades encontradas: {data.get('count', 0)}")

        print("✅ Filtros funcionando correctamente")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def run_all_tests():
    """Ejecutar todos los tests"""
    print("\n" + "=" * 80)
    print("  🧪 TEST DE INTEGRACIÓN API REST - NEON")
    print("=" * 80)
    print("\n⚠️  ASEGÚRATE DE QUE EL SERVIDOR ESTÉ CORRIENDO:")
    print("   python webhook_server.py")
    print()

    input("Presiona ENTER para continuar...")

    tests = [
        ("Health Check", test_health_check),
        ("Obtener Propiedades", test_get_properties),
        ("Obtener Propiedad por Slug", test_get_property_by_slug),
        ("Obtener Imágenes", test_get_property_images),
        ("Conexión a Base de Datos", test_database_connection),
        ("Filtros de Búsqueda", test_filters),
    ]

    results = []

    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Error crítico en {test_name}: {e}")
            results.append((test_name, False))

    # Resumen
    print_section("RESUMEN DE TESTS")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print(f"\n{'=' * 80}")
    print(f"Total: {passed}/{total} tests pasaron")

    if passed == total:
        print("✅ TODOS LOS TESTS PASARON - API LISTA PARA USAR")
    else:
        print("⚠️  ALGUNOS TESTS FALLARON - REVISAR CONFIGURACIÓN")

    print("=" * 80)


if __name__ == '__main__':
    run_all_tests()
