#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor Flask para recibir webhooks de UltraMSG
"""

from flask import Flask, request, jsonify
import os
import json
from datetime import datetime
from whatsapp_bot import WhatsAppBot

app = Flask(__name__)

# Inicializar bot
bot = WhatsAppBot()

# Directorio para logs de webhooks
WEBHOOK_LOGS_DIR = "webhook_logs"
os.makedirs(WEBHOOK_LOGS_DIR, exist_ok=True)


def log_webhook(data: dict, response: dict):
    """Guardar log del webhook para debugging"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(WEBHOOK_LOGS_DIR, f"webhook_{timestamp}.json")

    log_data = {
        'timestamp': datetime.now().isoformat(),
        'request': data,
        'response': response
    }

    try:
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️  Error guardando log: {e}")


@app.route('/')
def home():
    """Endpoint raíz - información del servidor"""
    return jsonify({
        'status': 'running',
        'service': 'WhatsApp Bot - TU360 Property Search',
        'version': '1.0.0',
        'endpoints': {
            'webhook': '/webhook (POST)',
            'health': '/health (GET)',
            'test': '/test (POST)'
        }
    })


@app.route('/health')
def health():
    """Endpoint de health check"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'bot_initialized': bot is not None
    })


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Endpoint para recibir webhooks de UltraMSG

    UltraMSG envía los mensajes entrantes a este endpoint.
    El formato típico incluye: from, body, type, id, etc.
    """
    try:
        # Obtener datos del webhook
        webhook_data = request.get_json() if request.is_json else request.form.to_dict()

        print("\n" + "=" * 80)
        print("📨 WEBHOOK RECIBIDO")
        print("=" * 80)
        print(f"🕐 Timestamp: {datetime.now().isoformat()}")
        print(f"📋 Data: {json.dumps(webhook_data, indent=2, ensure_ascii=False)}")
        print("=" * 80 + "\n")

        # Procesar mensaje con el bot
        response = bot.handle_incoming_message(webhook_data)

        # Log del webhook
        log_webhook(webhook_data, response)

        print(f"✅ Webhook procesado: {response.get('status')}\n")

        return jsonify({
            'status': 'success',
            'processed': True,
            'response': response
        }), 200

    except Exception as e:
        print(f"❌ Error procesando webhook: {e}")
        import traceback
        traceback.print_exc()

        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/test', methods=['POST'])
def test():
    """
    Endpoint de prueba para simular un webhook
    Útil para testing sin necesidad de mensajes reales de WhatsApp
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'status': 'error',
                'message': 'No se recibieron datos'
            }), 400

        # Simular webhook
        print("\n🧪 TEST WEBHOOK SIMULADO\n")
        response = bot.handle_incoming_message(data)

        return jsonify({
            'status': 'success',
            'test': True,
            'response': response
        }), 200

    except Exception as e:
        print(f"❌ Error en test: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/send', methods=['POST'])
def send():
    """
    Endpoint para enviar mensajes manualmente (útil para testing)

    Body JSON:
    {
        "to": "+573001234567",
        "message": "Hola, esto es una prueba"
    }
    """
    try:
        data = request.get_json()

        if not data or 'to' not in data or 'message' not in data:
            return jsonify({
                'status': 'error',
                'message': 'Faltan campos requeridos: to, message'
            }), 400

        to = data['to']
        message = data['message']

        result = bot.send_message(to, message)

        return jsonify({
            'status': 'success',
            'result': result
        }), 200

    except Exception as e:
        print(f"❌ Error enviando mensaje: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/search', methods=['POST'])
def search():
    """
    Endpoint para buscar propiedades y enviar resultados

    Body JSON:
    {
        "to": "+573001234567",
        "query": "Busco apto en Laureles, 2 habitaciones, hasta 500 millones"
    }
    """
    try:
        data = request.get_json()

        if not data or 'to' not in data or 'query' not in data:
            return jsonify({
                'status': 'error',
                'message': 'Faltan campos requeridos: to, query'
            }), 400

        to = data['to']
        query = data['query']

        print(f"\n🔍 Búsqueda solicitada para: {to}")
        print(f"📝 Query: {query}\n")

        success = bot.send_search_results(to, query)

        return jsonify({
            'status': 'success' if success else 'error',
            'sent': success
        }), 200 if success else 500

    except Exception as e:
        print(f"❌ Error en búsqueda: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


if __name__ == '__main__':
    print("=" * 80)
    print("  🤖 WHATSAPP BOT SERVER - TU360 PROPERTY SEARCH")
    print("=" * 80)
    print(f"  Instance ID: {bot.instance_id}")
    print(f"  Base URL: {bot.base_url}")
    print("=" * 80)
    print("\n📋 Endpoints disponibles:")
    print("  • GET  /         - Información del servidor")
    print("  • GET  /health   - Health check")
    print("  • POST /webhook  - Recibir mensajes de WhatsApp (configurar en UltraMSG)")
    print("  • POST /test     - Test webhook simulado")
    print("  • POST /send     - Enviar mensaje manual")
    print("  • POST /search   - Buscar propiedades y enviar resultados")
    print("\n" + "=" * 80)
    print("🌐 Para exponer el servidor públicamente, usa:")
    print("   • ngrok http 5000")
    print("   • localtunnel (lt --port 5000)")
    print("   • serveo.net")
    print("=" * 80 + "\n")

    # Obtener puerto de variable de entorno o usar 5000 por defecto
    port = int(os.environ.get('PORT', 5000))

    # Correr servidor
    # debug=True solo para desarrollo
    app.run(host='0.0.0.0', port=port, debug=True)
