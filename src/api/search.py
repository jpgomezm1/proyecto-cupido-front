#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Blueprint para Búsqueda IA de Propiedades
Expone el agente de búsqueda inteligente para uso web
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
import traceback

from src.core.search_agent import PropertySearchAgent
from src.db.database import DatabaseManager

search_bp = Blueprint('search', __name__, url_prefix='/api')

# Instancia global del agente (se inicializa lazy)
_search_agent = None


def get_search_agent():
    """Obtiene o crea la instancia del agente de búsqueda"""
    global _search_agent
    if _search_agent is None:
        try:
            _search_agent = PropertySearchAgent()
            print("✅ Agente de búsqueda IA inicializado")
        except Exception as e:
            print(f"❌ Error inicializando agente de búsqueda: {e}")
            raise e
    return _search_agent


@search_bp.route('/search/ai', methods=['POST'])
def ai_search():
    """
    Endpoint para búsqueda con IA

    Body JSON:
    {
        "query": "Busco apartamento en Laureles, 2 habitaciones, hasta 500 millones",
        "limit": 10  // opcional, default 10
    }

    Returns:
    {
        "success": true,
        "data": {
            "criteria": { ... },  // Criterios extraídos por IA
            "results": [ ... ],   // Propiedades encontradas
            "total_found": 5,
            "elapsed_ms": 1234,
            "search_id": "abc123"
        }
    }
    """
    try:
        data = request.get_json()

        if not data or 'query' not in data:
            return jsonify({
                'success': False,
                'error': 'Se requiere el campo "query" con la consulta de búsqueda'
            }), 400

        query = data['query'].strip()
        limit = data.get('limit', 10)

        if not query:
            return jsonify({
                'success': False,
                'error': 'La consulta no puede estar vacía'
            }), 400

        if len(query) < 10:
            return jsonify({
                'success': False,
                'error': 'La consulta es muy corta. Proporciona más detalles sobre lo que buscas.'
            }), 400

        print(f"\n🔍 Búsqueda IA Web recibida:")
        print(f"   Query: {query[:100]}...")
        print(f"   Limit: {limit}")

        # Obtener agente y ejecutar búsqueda
        agent = get_search_agent()
        search_response = agent.search(query, limit=limit, sender='web')

        if not search_response.get('success'):
            return jsonify({
                'success': False,
                'error': search_response.get('error', 'Error en la búsqueda')
            }), 500

        # Enriquecer resultados con imágenes de portada
        results = search_response.get('results', [])
        enriched_results = enrich_results_with_images(results)

        return jsonify({
            'success': True,
            'data': {
                'criteria': search_response.get('criteria', {}),
                'results': enriched_results,
                'total_found': search_response.get('total_found', 0),
                'elapsed_ms': search_response.get('elapsed_ms', 0),
                'search_id': search_response.get('search_id', ''),
                'timestamp': datetime.now().isoformat()
            }
        })

    except Exception as e:
        print(f"❌ Error en búsqueda IA: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def enrich_results_with_images(results):
    """
    Enriquece los resultados con imágenes de portada desde property_images
    """
    if not results:
        return results

    try:
        property_ids = [r.get('id') for r in results if r.get('id')]
        if not property_ids:
            return results

        with DatabaseManager() as db:
            # Obtener imágenes de portada para todas las propiedades
            placeholders = ','.join(['%s'] * len(property_ids))
            query = f"""
                SELECT property_id, url
                FROM property_images
                WHERE property_id IN ({placeholders})
                AND is_cover = TRUE
            """
            db.cursor.execute(query, property_ids)
            rows = db.cursor.fetchall()

            # Crear mapa de id -> imagen
            cover_map = {}
            for row in rows:
                if isinstance(row, dict):
                    cover_map[row['property_id']] = row['url']
                else:
                    cover_map[row[0]] = row[1]

            # Agregar imagen a cada resultado
            for result in results:
                prop_id = result.get('id')
                if prop_id in cover_map:
                    result['cover_image_url'] = cover_map[prop_id]
                elif result.get('imagen_principal'):
                    result['cover_image_url'] = result['imagen_principal']
                else:
                    result['cover_image_url'] = None

    except Exception as e:
        print(f"⚠️ Error obteniendo imágenes: {e}")
        # Si falla, usar imagen_principal como fallback
        for result in results:
            if not result.get('cover_image_url'):
                result['cover_image_url'] = result.get('imagen_principal')

    return results


@search_bp.route('/search/suggestions', methods=['GET'])
def search_suggestions():
    """
    Retorna sugerencias de búsqueda para mostrar al usuario
    """
    suggestions = [
        {
            'text': 'Busco apartamento en Laureles, 2 habitaciones, hasta 500 millones',
            'category': 'Apartamentos'
        },
        {
            'text': 'Casa en El Poblado con piscina, 3 habitaciones, presupuesto 1200 millones',
            'category': 'Casas'
        },
        {
            'text': 'Apto en Envigado o Sabaneta, primer piso, 2 baños, hasta 400 millones',
            'category': 'Apartamentos'
        },
        {
            'text': 'Penthouse en Ciudad del Río con terraza, mínimo 100m2',
            'category': 'Penthouses'
        },
        {
            'text': 'Apartamento para inversión en Medellín, buena rentabilidad',
            'category': 'Inversión'
        }
    ]

    return jsonify({
        'success': True,
        'data': suggestions
    })


@search_bp.route('/search/history', methods=['GET'])
def search_history():
    """
    Retorna historial de búsquedas recientes (últimas 20)
    """
    try:
        with DatabaseManager() as db:
            query = """
                SELECT
                    id,
                    query_texto as query,
                    fecha,
                    resultados_encontrados,
                    tiempo_respuesta_ms
                FROM solicitudes_mercado
                WHERE origen = 'Web'
                ORDER BY fecha DESC
                LIMIT 20
            """
            db.cursor.execute(query)
            rows = db.cursor.fetchall()

            history = []
            for row in rows:
                if isinstance(row, dict):
                    item = dict(row)
                else:
                    item = {
                        'id': row[0],
                        'query': row[1],
                        'fecha': row[2].isoformat() if row[2] else None,
                        'resultados_encontrados': row[3],
                        'tiempo_respuesta_ms': row[4]
                    }
                history.append(item)

            return jsonify({
                'success': True,
                'data': history
            })

    except Exception as e:
        print(f"❌ Error obteniendo historial: {e}")
        return jsonify({
            'success': True,
            'data': []  # Retornar lista vacía si hay error
        })
