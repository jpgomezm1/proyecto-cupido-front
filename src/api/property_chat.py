"""
API para el asistente de chat de propiedades - Hernán Ríos AI
"""
from flask import Blueprint, request, jsonify
import os
import json
from anthropic import Anthropic
from src.db.database import DatabaseManager

property_chat_bp = Blueprint('property_chat', __name__)

# Initialize Anthropic client
client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

def get_property_context(property_id: int) -> dict:
    """
    Obtiene todo el contexto de una propiedad incluyendo:
    - Datos básicos de la propiedad
    - Análisis visual de imágenes
    - Resumen visual generado por AI
    """
    db = DatabaseManager()
    db.connect()

    try:
        # 1. Datos básicos de la propiedad
        property_query = """
            SELECT
                p.id,
                p.codigo_propiedad as slug,
                p.titulo as title,
                p.tipo_propiedad as type,
                p.precio as price_cop,
                p.ciudad as city,
                p.barrio_normalizado as barrio,
                p.zona as zone,
                p.area_construida as area_m2,
                p.habitaciones as bedrooms,
                p.banos as bathrooms,
                p.parqueaderos as parking,
                p.estrato as stratum,
                p.ano_construccion as age_years,
                p.administracion as admin_fee_cop,
                p.descripcion as description,
                p.direccion_completa as address,
                p.estado as condition,
                p.amenidades_internas as features_internal,
                p.amenidades_externas as features_external,
                p.amenidades_destacadas as features_highlighted,
                p.fuente as source,
                p.descripcion_resumida as summary,
                p.unique_selling_points,
                p.ventajas_competitivas,
                p.target_buyer_profile,
                p.iluminacion_natural,
                p.vista,
                p.overall_quality_score
            FROM propiedades p
            WHERE p.id = %s
        """
        db.cursor.execute(property_query, (property_id,))
        property_row = db.cursor.fetchone()

        if not property_row:
            return None

        # RealDictCursor returns dict-like rows
        property_data = dict(property_row)

        # 2. Resumen visual generado por AI
        visual_summary_query = """
            SELECT
                descripcion_general,
                todas_caracteristicas,
                todos_puntos_destacados,
                ambiente_general,
                estilo_predominante,
                tags_visuales
            FROM property_visual_summary
            WHERE propiedad_id = %s
        """
        db.cursor.execute(visual_summary_query, (property_id,))
        visual_summary_row = db.cursor.fetchone()

        visual_summary = None
        if visual_summary_row:
            visual_summary = {
                'summary_text': visual_summary_row['descripcion_general'],
                'key_features': visual_summary_row['todas_caracteristicas'],
                'highlights': visual_summary_row['todos_puntos_destacados'],
                'overall_impression': visual_summary_row['ambiente_general'],
                'style': visual_summary_row['estilo_predominante'],
                'tags': visual_summary_row['tags_visuales']
            }

        # 3. Análisis de imágenes individuales
        image_analysis_query = """
            SELECT
                imagen_url,
                descripcion_visual,
                tipo_espacio,
                caracteristicas_visibles,
                puntos_destacados,
                calidad_imagen,
                ambiente
            FROM property_image_analysis
            WHERE propiedad_id = %s
            ORDER BY calidad_imagen DESC
            LIMIT 10
        """
        db.cursor.execute(image_analysis_query, (property_id,))
        image_rows = db.cursor.fetchall()

        image_analyses = []
        for row in image_rows:
            image_analyses.append({
                'image_url': row['imagen_url'],
                'analysis': row['descripcion_visual'],
                'room_type': row['tipo_espacio'],
                'features': row['caracteristicas_visibles'],
                'highlights': row['puntos_destacados'],
                'quality': row['calidad_imagen'],
                'ambiance': row['ambiente']
            })

        return {
            'property': property_data,
            'visual_summary': visual_summary,
            'image_analyses': image_analyses
        }

    finally:
        db.disconnect()


def build_system_prompt(context: dict) -> str:
    """Construye el system prompt para Hernán Ríos AI"""

    property_data = context['property']
    visual_summary = context.get('visual_summary')
    image_analyses = context.get('image_analyses', [])

    # Formatear precio
    price = property_data.get('price_cop')
    price_formatted = f"${price:,.0f} COP" if price else "No especificado"

    # Formatear administración
    admin = property_data.get('admin_fee_cop')
    admin_formatted = f"${admin:,.0f} COP/mes" if admin else "No especificada"

    # Combinar todas las amenidades
    features_parts = []
    if property_data.get('features_internal'):
        features_parts.append(property_data['features_internal'])
    if property_data.get('features_external'):
        features_parts.append(property_data['features_external'])
    if property_data.get('features_highlighted'):
        features_parts.append(property_data['features_highlighted'])
    features_text = " | ".join(features_parts) if features_parts else "No especificadas"

    # Construir información de imágenes
    image_insights = ""
    if image_analyses:
        image_insights = "\n\n### Lo que muestran las fotos:\n"
        for img in image_analyses[:5]:
            if img.get('analysis'):
                image_insights += f"- {img['analysis']}\n"

    # Resumen visual
    visual_info = ""
    if visual_summary:
        key_features = visual_summary.get('key_features') or ''
        highlights = visual_summary.get('highlights') or ''
        tags = visual_summary.get('tags') or ''

        visual_info = f"""

### Análisis Visual de la Propiedad:
{visual_summary.get('summary_text', '')}

**Características visuales:** {key_features}

**Puntos destacados:** {highlights}

**Ambiente/Impresión general:** {visual_summary.get('overall_impression', 'N/A')}

**Estilo predominante:** {visual_summary.get('style', 'N/A')}

**Tags visuales:** {tags}
"""

    # Información adicional de AI
    ai_info = ""
    if property_data.get('summary'):
        ai_info += f"\n### Resumen AI:\n{property_data['summary']}\n"
    if property_data.get('unique_selling_points'):
        ai_info += f"\n### Puntos únicos de venta:\n{property_data['unique_selling_points']}\n"
    if property_data.get('ventajas_competitivas'):
        ai_info += f"\n### Ventajas competitivas:\n{property_data['ventajas_competitivas']}\n"
    if property_data.get('target_buyer_profile'):
        ai_info += f"\n### Perfil de comprador ideal:\n{property_data['target_buyer_profile']}\n"

    system_prompt = f"""Eres Hernán Ríos AI, el asistente virtual del asesor inmobiliario Hernán Ríos. Tu objetivo es ayudar a los clientes potenciales respondiendo preguntas sobre esta propiedad específica.

## Tu Personalidad:
- Amable, profesional y conocedor del mercado inmobiliario de Medellín y el Valle de Aburrá
- Respondes de forma concisa pero completa
- Si no tienes información sobre algo específico, lo indicas honestamente
- Siempre tratas de ser útil y orientar al cliente
- Usas un tono cercano pero profesional
- Puedes responder en español o inglés según el idioma del usuario

## Información de la Propiedad:

### Datos Básicos:
- **Título:** {property_data.get('title', 'N/A')}
- **Tipo:** {property_data.get('type', 'N/A')}
- **Precio:** {price_formatted}
- **Ubicación:** {property_data.get('barrio', 'N/A')}, {property_data.get('city', 'N/A')}
- **Dirección:** {property_data.get('address', 'No especificada')}
- **Zona:** {property_data.get('zone', 'N/A')}

### Características Físicas:
- **Área construida:** {property_data.get('area_m2', 'N/A')} m²
- **Habitaciones:** {property_data.get('bedrooms', 'N/A')}
- **Baños:** {property_data.get('bathrooms', 'N/A')}
- **Parqueaderos:** {property_data.get('parking', 'N/A')}
- **Estrato:** {property_data.get('stratum', 'N/A')}
- **Año de construcción:** {property_data.get('age_years', 'N/A')}
- **Estado:** {property_data.get('condition', 'N/A')}
- **Iluminación natural:** {property_data.get('iluminacion_natural', 'N/A')}
- **Vista:** {property_data.get('vista', 'N/A')}
- **Calidad general:** {property_data.get('overall_quality_score', 'N/A')}/10

### Costos Adicionales:
- **Administración:** {admin_formatted}

### Características y Amenidades:
{features_text}

### Descripción:
{property_data.get('description', 'No disponible')}
{ai_info}
{visual_info}
{image_insights}

## Instrucciones:
1. Responde SOLO sobre esta propiedad específica
2. Si preguntan algo que no sabes, sugiere contactar directamente a Hernán Ríos
3. Si preguntan sobre precio negociable, indica que eso debe conversarse directamente con Hernán
4. Si preguntan por visitas, indica que pueden agendar contactando a Hernán por WhatsApp
5. Mantén respuestas concisas (máximo 3-4 oraciones por punto)
6. Puedes mencionar detalles de las fotos cuando sea relevante
7. Si preguntan sobre el barrio o zona, usa tu conocimiento general de Medellín/Antioquia

## Contacto de Hernán Ríos:
- WhatsApp: +57 318 777 1000
- Experiencia: 15+ años en el mercado inmobiliario"""

    return system_prompt


@property_chat_bp.route('/api/properties/<int:property_id>/chat', methods=['POST'])
def chat_with_property(property_id: int):
    """
    Endpoint para chatear sobre una propiedad específica

    Body:
    {
        "message": "string - pregunta del usuario",
        "history": [{"role": "user"|"assistant", "content": "string"}] - historial opcional
    }
    """
    try:
        data = request.get_json()

        if not data or 'message' not in data:
            return jsonify({
                'success': False,
                'error': 'Se requiere el campo "message"'
            }), 400

        user_message = data['message'].strip()
        history = data.get('history', [])

        if not user_message:
            return jsonify({
                'success': False,
                'error': 'El mensaje no puede estar vacío'
            }), 400

        # Limitar longitud del mensaje
        if len(user_message) > 500:
            user_message = user_message[:500]

        # Obtener contexto de la propiedad
        context = get_property_context(property_id)

        if not context:
            return jsonify({
                'success': False,
                'error': 'Propiedad no encontrada'
            }), 404

        # Construir system prompt
        system_prompt = build_system_prompt(context)

        # Construir mensajes para Claude
        messages = []

        # Agregar historial (máximo últimos 10 mensajes)
        for msg in history[-10:]:
            if msg.get('role') in ['user', 'assistant'] and msg.get('content'):
                messages.append({
                    'role': msg['role'],
                    'content': msg['content']
                })

        # Agregar mensaje actual
        messages.append({
            'role': 'user',
            'content': user_message
        })

        import time
        start_time = time.time()

        # Llamar a Claude
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=system_prompt,
            messages=messages
        )

        # Track AI usage
        from src.core.ai_usage_tracker import get_ai_tracker
        get_ai_tracker().track_anthropic_response(
            model='claude-sonnet-4-20250514',
            usage_type='property_chat',
            function_name='property_chat.chat_with_property',
            response=response,
            start_time=start_time,
            context={'property_id': property_id, 'history_length': len(history)}
        )

        assistant_message = response.content[0].text

        return jsonify({
            'success': True,
            'data': {
                'message': assistant_message,
                'property_id': property_id
            }
        })

    except Exception as e:
        print(f"Error en chat: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Error al procesar la solicitud'
        }), 500


@property_chat_bp.route('/api/properties/<slug>/chat-by-slug', methods=['POST'])
def chat_with_property_by_slug(slug: str):
    """
    Endpoint alternativo usando slug en lugar de ID
    """
    try:
        # Obtener property_id desde slug
        db = DatabaseManager()
        db.connect()

        try:
            db.cursor.execute("SELECT id FROM properties WHERE slug = %s", (slug,))
            row = db.cursor.fetchone()

            if not row:
                return jsonify({
                    'success': False,
                    'error': 'Propiedad no encontrada'
                }), 404

            property_id = row[0]
        finally:
            db.disconnect()

        # Reutilizar la lógica existente
        data = request.get_json() or {}
        data['_property_id'] = property_id

        # Llamar a la función principal
        return chat_with_property(property_id)

    except Exception as e:
        print(f"Error en chat by slug: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Error al procesar la solicitud'
        }), 500


@property_chat_bp.route('/api/properties/<int:property_id>/chat-context', methods=['GET'])
def get_chat_context(property_id: int):
    """
    Endpoint para obtener el contexto disponible de una propiedad
    Útil para debugging y verificar qué información tiene el AI
    """
    try:
        context = get_property_context(property_id)

        if not context:
            return jsonify({
                'success': False,
                'error': 'Propiedad no encontrada'
            }), 404

        # Simplificar respuesta para no exponer todo
        summary = {
            'property_title': context['property'].get('title'),
            'has_visual_summary': context.get('visual_summary') is not None,
            'image_analyses_count': len(context.get('image_analyses', [])),
            'has_description': bool(context['property'].get('description')),
            'features_count': len(context['property'].get('features', []) or [])
        }

        return jsonify({
            'success': True,
            'data': summary
        })

    except Exception as e:
        print(f"Error getting context: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Error al obtener contexto'
        }), 500
