#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API de Transcripción de Voz - Proyecto Cupido
Utiliza OpenAI Whisper para convertir audio a texto
"""

from flask import Blueprint, jsonify, request
from flask_cors import CORS
import os
import time
import tempfile
import traceback

transcribe_bp = Blueprint('transcribe', __name__, url_prefix='/api')

# Habilitar CORS para este blueprint
CORS(transcribe_bp, supports_credentials=True)


@transcribe_bp.route('/transcribe', methods=['POST'])
def transcribe_audio():
    """
    POST /api/transcribe

    Transcribe audio a texto usando OpenAI Whisper

    Body (multipart/form-data):
    - audio: archivo de audio (webm, mp3, wav, m4a, etc.)

    Returns:
    {
        "success": true,
        "data": {
            "text": "Texto transcrito del audio"
        }
    }
    """
    try:
        # Cargar API key dinámicamente (por si cambió)
        api_key = os.getenv('OPENAI_API_KEY')

        # Verificar que hay API key
        if not api_key:
            return jsonify({
                'success': False,
                'error': 'OpenAI API key no configurada'
            }), 500

        # Debug: mostrar primeros caracteres de la key
        print(f"[Transcribe] Usando API key: {api_key[:20]}...{api_key[-4:]}")

        # Verificar que se envió un archivo
        if 'audio' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No se encontró archivo de audio'
            }), 400

        audio_file = request.files['audio']

        if audio_file.filename == '':
            return jsonify({
                'success': False,
                'error': 'Archivo de audio vacío'
            }), 400

        print(f"[Transcribe] Recibido archivo: {audio_file.filename}, tipo: {audio_file.content_type}")

        # Guardar archivo temporalmente
        # Whisper soporta: mp3, mp4, mpeg, mpga, m4a, wav, webm
        suffix = '.webm'
        if audio_file.filename:
            ext = os.path.splitext(audio_file.filename)[1]
            if ext:
                suffix = ext

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            audio_file.save(tmp_file.name)
            tmp_path = tmp_file.name

        try:
            # Importar OpenAI
            from openai import OpenAI

            client = OpenAI(api_key=api_key)

            # Prompt con contexto inmobiliario para mejorar precisión
            context_prompt = (
                "Transcripción de búsqueda de propiedades inmobiliarias en Colombia. "
                "Términos comunes: apartamento, apto, casa, Laureles, El Poblado, Envigado, "
                "Sabaneta, Belén, Robledo, habitaciones, baños, parqueadero, piscina, "
                "gimnasio, millones, metros cuadrados, arriendo, venta, estrato."
            )

            # Get file size to estimate duration
            file_size = os.path.getsize(tmp_path)
            # Estimate duration: WebM audio ~12KB/second
            estimated_duration = file_size / 12000

            start_time = time.time()

            # Transcribir con el modelo más preciso
            with open(tmp_path, 'rb') as audio:
                transcript = client.audio.transcriptions.create(
                    model="gpt-4o-mini-transcribe",
                    file=audio,
                    language="es",
                    prompt=context_prompt
                )

            # Track AI usage
            from src.core.ai_usage_tracker import get_ai_tracker
            get_ai_tracker().track_whisper(
                model='gpt-4o-mini-transcribe',
                function_name='transcribe.transcribe_audio',
                audio_duration_seconds=estimated_duration,
                start_time=start_time,
                context={'file_size': file_size, 'file_type': suffix}
            )

            transcribed_text = transcript.text.strip()
            print(f"[Transcribe] Texto transcrito: {transcribed_text[:100]}...")

            return jsonify({
                'success': True,
                'data': {
                    'text': transcribed_text
                }
            }), 200

        finally:
            # Limpiar archivo temporal
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        print(f"[Transcribe] Error: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
