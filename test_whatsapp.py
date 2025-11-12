#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de prueba para el bot de WhatsApp
"""

from whatsapp_bot import WhatsAppBot
import json


def test_send_message():
    """Test básico de envío de mensaje"""
    print("=" * 80)
    print("  TEST 1: ENVÍO DE MENSAJE SIMPLE")
    print("=" * 80)

    bot = WhatsAppBot()

    # Solicitar número de prueba
    test_number = input("\n📱 Ingresa tu número de WhatsApp (formato +573001234567): ").strip()

    if not test_number:
        print("❌ No se ingresó número")
        return False

    print(f"\n📤 Enviando mensaje de prueba a {test_number}...")

    message = """🤖 *Bot TU360 - Test de Conexión*

¡Hola! 👋

Este es un mensaje de prueba del sistema de búsqueda inteligente de propiedades.

Si recibes este mensaje, ¡la conexión está funcionando correctamente! ✅

Próximamente podrás hacer búsquedas de propiedades desde WhatsApp."""

    result = bot.send_message(test_number, message)

    print("\n📋 Resultado:")
    print(json.dumps(result, indent=2))

    return result.get('sent') == 'true' or 'id' in result


def test_search_and_send():
    """Test de búsqueda y envío de resultados"""
    print("\n" + "=" * 80)
    print("  TEST 2: BÚSQUEDA Y ENVÍO DE RESULTADOS")
    print("=" * 80)

    bot = WhatsAppBot()

    test_number = input("\n📱 Ingresa tu número de WhatsApp (formato +573001234567): ").strip()

    if not test_number:
        print("❌ No se ingresó número")
        return False

    # Query de prueba
    query = """Busco apto cliente tu 360 en ciudad del Río o Laureles
Persona mayor primer piso. 2 o 3 habitaciones.
Con portería.
Presupuesto 1000 millones."""

    print(f"\n📝 Query de prueba:")
    print(f"   {query}")
    print(f"\n🔍 Realizando búsqueda y enviando resultados...")

    success = bot.send_search_results(test_number, query)

    if success:
        print("\n✅ Búsqueda completada y resultados enviados")
    else:
        print("\n❌ Error en la búsqueda o envío")

    return success


def test_webhook_simulation():
    """Simular recepción de webhook"""
    print("\n" + "=" * 80)
    print("  TEST 3: SIMULACIÓN DE WEBHOOK")
    print("=" * 80)

    bot = WhatsAppBot()

    # Simular datos de webhook de UltraMSG
    webhook_data = {
        'from': '+573001234567',  # Cambiar por tu número
        'body': 'Busco apartamento en Laureles, 2 habitaciones, hasta 500 millones',
        'type': 'chat',
        'id': 'test_message_123',
        'time': '1234567890'
    }

    print(f"\n📨 Simulando webhook con datos:")
    print(json.dumps(webhook_data, indent=2))

    print(f"\n⚙️  Procesando...")

    response = bot.handle_incoming_message(webhook_data)

    print(f"\n📋 Respuesta del bot:")
    print(json.dumps(response, indent=2))

    return response.get('status') == 'success'


def main():
    """Menú principal de tests"""
    print("\n")
    print("=" * 80)
    print("  🧪 SUITE DE TESTS - WHATSAPP BOT TU360")
    print("=" * 80)
    print("\n¿Qué test deseas ejecutar?\n")
    print("  1. Test de envío de mensaje simple")
    print("  2. Test de búsqueda y envío de resultados")
    print("  3. Test de simulación de webhook")
    print("  4. Ejecutar todos los tests")
    print("  0. Salir")

    choice = input("\n👉 Selecciona una opción (0-4): ").strip()

    if choice == '1':
        test_send_message()
    elif choice == '2':
        test_search_and_send()
    elif choice == '3':
        test_webhook_simulation()
    elif choice == '4':
        print("\n🚀 Ejecutando todos los tests...\n")
        results = []
        results.append(("Envío simple", test_send_message()))
        results.append(("Búsqueda completa", test_search_and_send()))
        results.append(("Webhook simulado", test_webhook_simulation()))

        print("\n" + "=" * 80)
        print("  📊 RESUMEN DE TESTS")
        print("=" * 80)
        for name, result in results:
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"  {status} - {name}")
        print("=" * 80 + "\n")
    elif choice == '0':
        print("👋 Saliendo...")
    else:
        print("❌ Opción no válida")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Interrumpido por usuario")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
