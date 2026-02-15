#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feedback Analyzer - Procesa feedback con AI (Claude)
Analiza texto e imagenes para generar un resumen estructurado con triage AI
Consume PROJECT_CONTEXT.md desde GitHub para contexto del codebase
"""

import os
import json
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

TIPOS_VALIDOS = {'Bug', 'Mejora', 'Pregunta', 'Queja', 'Elogio'}
PRIORIDADES_VALIDAS = {'baja', 'media', 'alta', 'urgente'}

# GitHub raw URL for PROJECT_CONTEXT.md
GITHUB_CONTEXT_URL = "https://raw.githubusercontent.com/jpgomezm1/proyecto-cupido-front/dev-patus/PROJECT_CONTEXT.md"

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


def _parse_json_response(text: str) -> Optional[dict]:
    """Parse JSON from Claude response, handling markdown fences."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try stripping markdown fences
    if '```' in text:
        try:
            json_str = text.split('```')[1]
            if json_str.startswith('json'):
                json_str = json_str[4:]
            return json.loads(json_str.strip())
        except (json.JSONDecodeError, IndexError):
            pass

    return None


def _build_legacy_resumen(result: dict) -> str:
    """Build legacy text format from structured result for ai_resumen backwards compat."""
    parts = []
    if result.get('resumen'):
        parts.append(f"**Resumen:** {result['resumen']}")
    if result.get('tipo'):
        parts.append(f"**Tipo:** {result['tipo']}")
    if result.get('detalle'):
        parts.append(f"**Detalle:** {result['detalle']}")
    if result.get('archivos_relacionados'):
        parts.append(f"**Archivos relacionados:** {result['archivos_relacionados']}")
    if result.get('prioridad_sugerida'):
        parts.append(f"**Prioridad sugerida:** {result['prioridad_sugerida']}")
    if result.get('accion_recomendada'):
        parts.append(f"**Accion recomendada:** {result['accion_recomendada']}")
    return '\n'.join(parts)


def analyze_feedback(contenido: str, categoria: str, imagenes: List[Dict] = None) -> Optional[dict]:
    """
    Analiza feedback con Claude AI para generar un triage estructurado.

    Args:
        contenido: Texto del feedback del usuario
        categoria: Categoria del feedback
        imagenes: Lista de imagenes [{data: "base64...", nombre: "file.jpg", tipo: "image/jpeg"}]

    Returns:
        Dict con campos estructurados o None si falla:
        {
            "titulo": str,
            "tipo": str,
            "prioridad_sugerida": str,
            "confianza": int,
            "resumen": str,
            "detalle": str,
            "archivos_relacionados": str,
            "accion_recomendada": str,
            "resumen_legacy": str  # backwards-compat text format
        }
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
Tu tarea es analizar el feedback de un usuario y generar un triage estructurado en formato JSON.

Reglas:
- Escribe en español
- Se conciso pero completo
- Si hay imagenes adjuntas, describe lo que ves relevante al feedback (errores en pantalla, problemas de UI, etc.)
- Identifica el problema o sugerencia principal
- Si tienes contexto del proyecto, referencia los archivos, módulos o endpoints específicos que podrían estar relacionados

RESPONDE UNICAMENTE con un JSON valido (sin markdown fences, sin texto adicional) con esta estructura exacta:

{
  "titulo": "Titulo corto descriptivo del feedback (max 100 caracteres)",
  "tipo": "Bug | Mejora | Pregunta | Queja | Elogio",
  "prioridad_sugerida": "baja | media | alta | urgente",
  "confianza": 85,
  "resumen": "1-2 frases resumiendo el feedback",
  "detalle": "Descripcion completa del problema o sugerencia",
  "archivos_relacionados": "Lista de archivos/módulos del codebase que podrían estar involucrados",
  "accion_recomendada": "Que deberia hacer el equipo al respecto"
}

Reglas para cada campo:
- titulo: Maximo 100 caracteres, debe ser descriptivo y accionable (ej: "Filtro de precio no aplica al buscar propiedades")
- tipo: EXACTAMENTE uno de: Bug, Mejora, Pregunta, Queja, Elogio
- prioridad_sugerida: EXACTAMENTE uno de: baja, media, alta, urgente
- confianza: Numero entero de 1 a 100 indicando tu confianza en la clasificación
- resumen: 1-2 frases concisas
- detalle: Descripcion mas completa
- archivos_relacionados: Archivos del codebase relevantes, o "No determinado" si no tienes contexto
- accion_recomendada: Accion concreta para el equipo"""

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

        raw_text = response.content[0].text.strip()

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

        # Parse JSON response
        result = _parse_json_response(raw_text)
        if not result:
            print(f"[FeedbackAnalyzer] Failed to parse JSON, falling back to text")
            # Return a minimal structured result with the raw text as legacy
            return {
                'titulo': None,
                'tipo': None,
                'prioridad_sugerida': None,
                'confianza': None,
                'resumen_legacy': raw_text,
            }

        # Validate and sanitize fields
        if result.get('tipo') not in TIPOS_VALIDOS:
            result['tipo'] = None

        if result.get('prioridad_sugerida') not in PRIORIDADES_VALIDAS:
            result['prioridad_sugerida'] = None

        # Clamp confianza to 1-100
        confianza = result.get('confianza')
        if isinstance(confianza, (int, float)):
            result['confianza'] = max(1, min(100, int(confianza)))
        else:
            result['confianza'] = None

        # Truncate titulo to 120 chars
        if result.get('titulo'):
            result['titulo'] = result['titulo'][:120]

        # Generate legacy text format for ai_resumen backwards compat
        result['resumen_legacy'] = _build_legacy_resumen(result)

        print(f"[FeedbackAnalyzer] Triage: tipo={result.get('tipo')}, "
              f"prioridad={result.get('prioridad_sugerida')}, "
              f"confianza={result.get('confianza')}")
        return result

    except Exception as e:
        print(f"[FeedbackAnalyzer] Error: {e}")
        traceback.print_exc()
        return None
