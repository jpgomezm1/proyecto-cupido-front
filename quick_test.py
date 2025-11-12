#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test rápido de conexión con UltraMSG
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

print("=" * 80)
print("  🧪 TEST RÁPIDO DE CONEXIÓN ULTRAMSG")
print("=" * 80)

# Cargar credenciales
instance_id = os.getenv('ULTRAMSG_INSTANCE_ID')
token = os.getenv('ULTRAMSG_TOKEN')

print(f"\n📋 Credenciales:")
print(f"   Instance ID: {instance_id}")
print(f"   Token: {token}")

if not instance_id or not token:
    print("\n❌ Error: Faltan credenciales en .env")
    exit(1)

# Test 1: Verificar estado de la instancia
print("\n" + "=" * 80)
print("TEST 1: Verificar estado de la instancia")
print("=" * 80)

url = f"https://api.ultramsg.com/{instance_id}/instance/status"
params = {'token': token}

try:
    print(f"\n📡 Consultando: {url}")
    response = requests.get(url, params=params)
    print(f"📊 Status Code: {response.status_code}")
    print(f"📄 Respuesta:")
    print(response.text)

    if response.status_code == 200:
        print("\n✅ Conexión exitosa con UltraMSG API")
    else:
        print("\n⚠️  Respuesta inesperada")

except Exception as e:
    print(f"\n❌ Error: {e}")

# Test 2: Test de mensaje (solo si el usuario quiere)
print("\n" + "=" * 80)
print("TEST 2: Envío de mensaje de prueba (OPCIONAL)")
print("=" * 80)

send_test = input("\n¿Quieres enviar un mensaje de prueba? (s/n): ").lower().strip()

if send_test == 's':
    test_number = input("📱 Ingresa el número con formato internacional (+57300...): ").strip()

    if test_number:
        url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
        payload = {
            'token': token,
            'to': test_number,
            'body': '🤖 *Test Bot TU360*\n\n¡Conexión exitosa! ✅\n\nEste es un mensaje de prueba del sistema.'
        }

        try:
            print(f"\n📤 Enviando mensaje a {test_number}...")
            response = requests.post(url, data=payload)
            print(f"📊 Status Code: {response.status_code}")
            print(f"📄 Respuesta:")
            print(response.text)

            if response.status_code == 200:
                print("\n✅ Mensaje enviado correctamente")
            else:
                print("\n⚠️  Revisar respuesta de la API")

        except Exception as e:
            print(f"\n❌ Error enviando mensaje: {e}")
    else:
        print("⚠️  No se ingresó número")
else:
    print("⏭️  Test de envío omitido")

print("\n" + "=" * 80)
print("  ✅ TEST COMPLETADO")
print("=" * 80)
print("\n💡 Siguiente paso: Ejecuta 'python3 test_whatsapp.py' para tests completos")
print("   o 'python3 webhook_server.py' para iniciar el bot\n")
