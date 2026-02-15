#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feedback Analyzer - Procesa feedback con AI (Claude)
Analiza texto e imagenes para generar un resumen detallado
Consume PROJECT_CONTEXT.md desde GitHub para contexto del codebase
"""

import os
import time
import traceback
import requests
from typing import List, Dict, Optional

CATEGORIA_LABELS = {
    'administrador': 'Panel de Administración',
    'busqueda_propiedades': 'Búsqueda de Propiedades',
    'ai_search': 'Búsqueda con IA',
    'general': 'General',
    'otro': 'Otro',
}

# GitHub raw URL for PROJECT_CONTEXT.md
GITHUB_CONTEXT_URL = "https://raw.githubusercontent.com/jpgomezm1/proyecto-cupido-front/main/PROJECT_CONTEXT.md"

# Cache del contexto para no descargarlo en cada request
_context_cache = {
    'content': None,
    'fetched_at': 0,
}
CACHE_TTL_SECONDS = 3600  # Refrescar cada hora


def _fetch_project_context() -> Optional[str]:
    """
    Descarga PROJECT_CONTEXT.md desde GitHub con cache de 1 hora.
    """
    now = time.time()

    # Return cached if fresh
    if _context_cache['content'] and (now - _context_cache['fetched_at']) < CACHE_TTL_SECONDS:
        return _context_cache['content']

    try:
        response = requests.get(GITHUB_CONTEXT_URL, timeout=10)
        if response.status_code == 200:
            content = response.text
            _context_cache['content'] = content
            _context_cache['fetched_at'] = now
            print(f"[FeedbackAnalyzer] PROJECT_CONTEXT.md fetched ({len(content)} chars)")
            return content
        else:
            print(f"[FeedbackAnalyzer] GitHub fetch failed: {response.status_code}")
            # Return stale cache if available
            return _context_cache['content']
    except Exception as e:
        print(f"[FeedbackAnalyzer] Error fetching context: {e}")
        return _context_cache['content']


def analyze_feedback(contenido: str, categoria: str, imagenes: List[Dict] = None) -> Optional[str]:
    """
    Analiza feedback con Claude AI para generar un resumen detallado.
    Incluye contexto del proyecto desde GitHub para mejor interpretación.

    Args:
        contenido: Texto del feedback del usuario
        categoria: Categoria del feedback
        imagenes: Lista de imagenes [{data: "base64...", nombre: "file.jpg", tipo: "image/jpeg"}]

    Returns:
        Resumen AI generado o None si falla
    """
    try:
        from anthropic import Anthropic

        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            print("[FeedbackAnalyzer] ANTHROPIC_API_KEY no configurada")
            return None

        client = Anthropic(api_key=api_key)
        model = "claude-sonnet-4-20250514"

        categoria_label = CATEGORIA_LABELS.get(categoria, categoria)

        # Fetch project context from GitHub
        project_context = _fetch_project_context()

        system_prompt = """Eres un analista de feedback para Fynder, una plataforma inmobiliaria colombiana.
Tu tarea es analizar el feedback de un usuario y generar un resumen estructurado y detallado.

Reglas:
- Escribe en español
- Se conciso pero completo
- Si hay imagenes adjuntas, describe lo que ves relevante al feedback (errores en pantalla, problemas de UI, etc.)
- Identifica el problema o sugerencia principal
- Sugiere una prioridad: baja, media, alta o urgente
- El resumen debe ser util para que un desarrollador o product manager entienda rapidamente el feedback
- Si tienes contexto del proyecto, referencia los archivos, módulos o endpoints específicos que podrían estar relacionados con el feedback

Formato de respuesta (usa exactamente estos encabezados):
**Resumen:** [1-2 frases resumiendo el feedback]
**Tipo:** [Bug / Sugerencia / Queja / Elogio / Pregunta]
**Detalle:** [Descripcion mas completa del problema o sugerencia]
**Archivos relacionados:** [Lista de archivos/módulos del codebase que podrían estar involucrados, basándote en el contexto del proyecto]
**Prioridad sugerida:** [baja / media / alta / urgente]
**Accion recomendada:** [Que deberia hacer el equipo al respecto]"""

        # Append project context to system prompt if available
        if project_context:
            system_prompt += f"\n\n---\n\nCONTEXTO DEL PROYECTO (arquitectura, módulos, endpoints, páginas):\n\n{project_context}"

        # Build message content
        content_parts = []

        # Add images first if present
        if imagenes:
            for img in imagenes:
                img_data = img.get('data', '')
                media_type = img.get('tipo', 'image/jpeg')

                # Strip data URL prefix if present
                if img_data.startswith('data:'):
                    # e.g. "data:image/jpeg;base64,/9j/4AAQ..."
                    parts = img_data.split(',', 1)
                    if len(parts) == 2:
                        img_data = parts[1]
                        # Extract media type from prefix
                        prefix = parts[0]  # "data:image/jpeg;base64"
                        if ':' in prefix and ';' in prefix:
                            media_type = prefix.split(':')[1].split(';')[0]

                content_parts.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": img_data
                    }
                })

        # Add text
        user_text = f"Categoría del feedback: {categoria_label}\n\nFeedback del usuario:\n{contenido}"
        if imagenes:
            user_text += f"\n\n[El usuario adjuntó {len(imagenes)} imagen(es)]"

        content_parts.append({
            "type": "text",
            "text": user_text
        })

        start_time = time.time()

        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {"role": "user", "content": content_parts}
            ]
        )

        ai_resumen = response.content[0].text.strip()

        # Track AI usage
        try:
            from src.core.ai_usage_tracker import get_ai_tracker
            get_ai_tracker().track_anthropic_response(
                model=model,
                usage_type='feedback_analysis',
                function_name='feedback_analyzer.analyze_feedback',
                response=response,
                start_time=start_time,
                context={
                    'categoria': categoria,
                    'contenido_length': len(contenido),
                    'num_imagenes': len(imagenes) if imagenes else 0,
                    'has_project_context': project_context is not None,
                }
            )
        except Exception as track_err:
            print(f"[FeedbackAnalyzer] Error tracking usage: {track_err}")

        print(f"[FeedbackAnalyzer] Resumen generado ({len(ai_resumen)} chars)")
        return ai_resumen

    except Exception as e:
        print(f"[FeedbackAnalyzer] Error: {e}")
        traceback.print_exc()
        return None
