#!/bin/bash

echo "================================================================================"
echo "  🤖 INICIANDO BOT DE WHATSAPP - TU360 PROPERTY SEARCH"
echo "================================================================================"
echo ""
echo "📋 Verificando configuración..."

# Verificar si existe .env
if [ ! -f .env ]; then
    echo "❌ Error: Archivo .env no encontrado"
    echo "   Copia .env.example a .env y configura las credenciales"
    exit 1
fi

echo "✅ Archivo .env encontrado"

# Verificar dependencias
echo ""
echo "📦 Verificando dependencias..."
python3 -c "import flask, requests, anthropic, psycopg2" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "⚠️  Algunas dependencias faltan"
    echo "📥 Instalando dependencias..."
    pip3 install -r requirements.txt --break-system-packages --ignore-installed
fi

echo "✅ Dependencias verificadas"
echo ""
echo "================================================================================"
echo "  🚀 INICIANDO SERVIDOR WEBHOOK"
echo "================================================================================"
echo ""
echo "📌 El servidor se iniciará en http://0.0.0.0:5000"
echo "📌 Endpoint webhook: http://0.0.0.0:5000/webhook"
echo ""
echo "🌐 Para exponer públicamente, usa en otra terminal:"
echo "   ngrok http 5000"
echo ""
echo "⚠️  Presiona Ctrl+C para detener el servidor"
echo ""
echo "================================================================================"
echo ""

python3 webhook_server.py
