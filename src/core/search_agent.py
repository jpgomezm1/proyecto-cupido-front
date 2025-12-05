#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Búsqueda Inteligente de Propiedades
Usa Claude API (Anthropic) para procesar consultas en lenguaje natural
y encontrar propiedades que coincidan con los criterios de los agentes inmobiliarios
"""

import os
import re
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("⚠️  Módulo 'anthropic' no instalado. Ejecuta: pip install anthropic")

from src.db.database import DatabaseManager
from src.core.logger import get_search_logger, log_execution_time

# Importar búsqueda vectorial (opcional)
try:
    from src.core.vector_search import get_vector_search
    VECTOR_SEARCH_AVAILABLE = True
except ImportError:
    VECTOR_SEARCH_AVAILABLE = False
    print("ℹ️  Búsqueda vectorial no disponible (ejecutar scripts/process_properties_vectors.py)")

# Cargar variables de entorno
load_dotenv()

# Logger especializado para búsquedas
search_log = get_search_logger()

# Configuración
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
MODEL = "claude-3-5-sonnet-20241022"  # Modelo por defecto

# Modelos alternativos en orden de preferencia
FALLBACK_MODELS = [
    "claude-3-5-sonnet-20241022",
    "claude-3-5-sonnet-20240620",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
    "claude-3-haiku-20240307"
]


class PropertySearchAgent:
    """Agente de búsqueda de propiedades usando Claude"""

    def __init__(self, api_key: str = None, model: str = None):
        """Inicializa el agente con la API key de Anthropic"""
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("El módulo 'anthropic' no está instalado")

        self.api_key = api_key or ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY no configurada en .env")

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model or self._detect_available_model()
        self.db = None

    def _detect_available_model(self) -> str:
        """Detecta el primer modelo disponible de la lista"""
        for model in FALLBACK_MODELS:
            try:
                # Hacer una llamada de prueba mínima
                test_response = self.client.messages.create(
                    model=model,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "test"}]
                )
                print(f"[OK] Usando modelo: {model}")
                return model
            except anthropic.NotFoundError:
                continue
            except Exception as e:
                # Otros errores (rate limit, etc.) - el modelo existe
                print(f"[WARN] Modelo {model} existe pero error: {e}")
                return model

        # Si ninguno funciona, usar el primero como fallback
        print(f"[WARN] No se pudo detectar modelo, usando: {FALLBACK_MODELS[0]}")
        return FALLBACK_MODELS[0]

    def _extract_search_criteria(self, query: str) -> Dict[str, Any]:
        """
        Usa Claude para extraer criterios de búsqueda de un mensaje en lenguaje natural

        Args:
            query: Mensaje del agente inmobiliario (puede ser informal/WhatsApp)

        Returns:
            Diccionario con criterios estructurados
        """

        system_prompt = """Eres un asistente experto en bienes raíces en Medellín, Colombia.
Tu tarea es analizar mensajes de agentes inmobiliarios y extraer los criterios de búsqueda de propiedades.

Debes extraer y estructurar la siguiente información cuando esté disponible:
- ubicaciones: Lista de zonas/barrios mencionados (ej: ["Laureles", "Ciudad del Río"])
- tipo_propiedad: Tipo (Apartamento, Casa, Penthouse, Duplex)
- precio_min: Precio mínimo en COP (número)
- precio_max: Precio máximo en COP (número)
- habitaciones_min: Mínimo de habitaciones
- habitaciones_max: Máximo de habitaciones
- banos_min: Mínimo de baños
- area_min: Área mínima en m²
- area_max: Área máxima en m²
- piso: Número de piso específico o "primer piso"
- amenidades_requeridas: Lista de amenidades importantes (ej: ["portería", "piscina", "balcón"])
- caracteristicas_especiales: Características mencionadas (ej: "baño en cada habitación", "estudio")
- urgencia: Si se menciona "urgente", "ya", "rápido"
- notas: Cualquier otra información relevante

IMPORTANTE:
- Los precios en mensajes colombianos como "1000 millones" = 1,000,000,000 COP
- "800 millones" = 800,000,000 COP
- "Hasta $800 millones" significa precio_max = 800,000,000
- Ubicaciones en Medellín: El Poblado, Laureles, Envigado, Sabaneta, Belén, etc.
- "Baño en cada habitación" o "cada una con baño" = característica importante
- "Primer piso" = piso: 1
- "Portería", "vigilancia" son amenidades de seguridad

Responde SOLO con un JSON válido, sin texto adicional."""

        user_message = f"""Analiza este mensaje de un agente inmobiliario y extrae los criterios de búsqueda:

```
{query}
```

Responde SOLO con el JSON de criterios."""

        try:
            start_time = time.time()

            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_message}
                ]
            )

            # Extraer el JSON de la respuesta
            response_text = message.content[0].text.strip()

            # Limpiar markdown si existe
            if response_text.startswith("```json"):
                response_text = response_text.replace("```json", "").replace("```", "").strip()
            elif response_text.startswith("```"):
                response_text = response_text.replace("```", "").strip()

            criteria = json.loads(response_text)

            elapsed_ms = (time.time() - start_time) * 1000
            search_log.log_criteria_extraction(criteria, elapsed_ms)

            return criteria

        except json.JSONDecodeError as e:
            search_log.log_error(f"Error al parsear JSON: {e}", "criteria_extraction")
            print(f"⚠️  Error al parsear JSON: {e}")
            print(f"Respuesta: {response_text}")
            return {}
        except Exception as e:
            search_log.log_error(str(e), "criteria_extraction")
            print(f"❌ Error al extraer criterios: {e}")
            return {}

    def _build_sql_query(self, criteria: Dict[str, Any]) -> tuple:
        """
        Construye una consulta SQL basada en los criterios extraídos

        Args:
            criteria: Diccionario de criterios de búsqueda

        Returns:
            Tupla (query_sql, params)
        """

        base_query = """
        SELECT
            id, id::text as slug, codigo_propiedad, fuente, url, titulo, precio, precio_texto,
            tipo_propiedad, estado, ciudad, zona, direccion_completa,
            area_construida, habitaciones, banos, parqueaderos, estrato, piso,
            ano_construccion, administracion, predial,
            amenidades_internas, amenidades_externas, total_amenidades,
            asesor, telefono, inmobiliaria, imagen_principal, total_imagenes,
            descripcion, fecha_creacion
        FROM propiedades
        WHERE activa = TRUE
        """

        conditions = []
        params = {}

        # Filtro por ubicaciones (zonas, ciudad, dirección o título)
        if criteria.get('ubicaciones'):
            ubicaciones = criteria['ubicaciones']
            zona_conditions = []
            for i, ubicacion in enumerate(ubicaciones):
                # Buscar en zona, ciudad, dirección Y título (más flexible)
                zona_conditions.append(
                    f"(zona ILIKE %(ubicacion_{i})s OR "
                    f"ciudad ILIKE %(ubicacion_{i})s OR "
                    f"direccion_completa ILIKE %(ubicacion_{i})s OR "
                    f"titulo ILIKE %(ubicacion_{i})s)"
                )
                params[f'ubicacion_{i}'] = f'%{ubicacion}%'
            conditions.append(f"({' OR '.join(zona_conditions)})")

        # Filtro por tipo de propiedad (puede ser string o lista)
        if criteria.get('tipo_propiedad'):
            tipos = criteria['tipo_propiedad']
            if isinstance(tipos, list):
                tipo_conditions = []
                for i, tipo in enumerate(tipos):
                    tipo_conditions.append(f"tipo_propiedad ILIKE %(tipo_{i})s")
                    params[f'tipo_{i}'] = f'%{tipo}%'
                conditions.append(f"({' OR '.join(tipo_conditions)})")
            else:
                conditions.append("tipo_propiedad ILIKE %(tipo_propiedad)s")
                params['tipo_propiedad'] = f"%{tipos}%"

        # Filtro por rango de precio
        if criteria.get('precio_min'):
            conditions.append("precio >= %(precio_min)s")
            params['precio_min'] = criteria['precio_min']

        if criteria.get('precio_max'):
            conditions.append("precio <= %(precio_max)s")
            params['precio_max'] = criteria['precio_max']

        # Filtro por habitaciones
        if criteria.get('habitaciones_min'):
            conditions.append("habitaciones >= %(habitaciones_min)s")
            params['habitaciones_min'] = criteria['habitaciones_min']

        if criteria.get('habitaciones_max'):
            conditions.append("habitaciones <= %(habitaciones_max)s")
            params['habitaciones_max'] = criteria['habitaciones_max']

        # Filtro por baños
        if criteria.get('banos_min'):
            conditions.append("banos >= %(banos_min)s")
            params['banos_min'] = criteria['banos_min']

        # Filtro por área
        if criteria.get('area_min'):
            conditions.append("area_construida >= %(area_min)s")
            params['area_min'] = criteria['area_min']

        if criteria.get('area_max'):
            conditions.append("area_construida <= %(area_max)s")
            params['area_max'] = criteria['area_max']

        # Filtro por piso
        if criteria.get('piso'):
            if criteria['piso'] == 1 or str(criteria['piso']).lower() == 'primer piso':
                conditions.append("piso = 1")
            elif isinstance(criteria['piso'], int):
                conditions.append("piso = %(piso)s")
                params['piso'] = criteria['piso']

        # Filtro por amenidades
        if criteria.get('amenidades_requeridas'):
            amenidades = criteria['amenidades_requeridas']
            for i, amenidad in enumerate(amenidades):
                conditions.append(
                    f"(amenidades_internas ILIKE %(amenidad_{i})s OR amenidades_externas ILIKE %(amenidad_{i})s)"
                )
                params[f'amenidad_{i}'] = f'%{amenidad}%'

        # Agregar condiciones a la query
        if conditions:
            base_query += " AND " + " AND ".join(conditions)

        # Ordenar por relevancia (más amenidades primero, luego por precio)
        base_query += " ORDER BY total_amenidades DESC, precio ASC"

        # Limitar resultados
        base_query += " LIMIT 20"

        return base_query, params

    def _rank_results(self, results: List[Dict], criteria: Dict[str, Any]) -> List[Dict]:
        """
        Rankea los resultados según qué tan bien coinciden con los criterios
        Versión mejorada que usa campos AI enriquecidos

        Args:
            results: Lista de propiedades encontradas
            criteria: Criterios de búsqueda originales

        Returns:
            Lista rankeada con score de coincidencia
        """

        for result in results:
            score = 0
            reasons = []

            # ===== SCORING BASADO EN AI ENRICHMENT =====

            # 1. Overall Quality Score (base score from AI)
            overall_quality = result.get('overall_quality_score', 50)
            if isinstance(overall_quality, (int, float)):
                # Usar el quality score de AI como base (normalizado a 0-20 pts)
                score += int(overall_quality * 0.2)
                if overall_quality >= 80:
                    reasons.append(f"Calidad excepcional ({overall_quality}/100)")
                elif overall_quality >= 70:
                    reasons.append(f"Alta calidad ({overall_quality}/100)")

            # 2. Target Buyer Profile Match
            if criteria.get('target_buyer_profile'):
                target_profiles = result.get('target_buyer_profile', [])
                if isinstance(target_profiles, list):
                    for profile in criteria['target_buyer_profile']:
                        if any(profile.lower() in tp.lower() for tp in target_profiles):
                            score += 15
                            reasons.append(f"Ideal para: {profile}")
                            break

            # 3. Segmento de mercado adecuado
            segmento = result.get('segmento_mercado', '')
            if criteria.get('precio_max'):
                precio_max = criteria['precio_max']
                # Dar bonus si el segmento es apropiado al presupuesto
                if precio_max >= 1_000_000_000 and segmento in ['Lujo', 'Premium']:
                    score += 10
                    reasons.append(f"Segmento {segmento}")
                elif 400_000_000 <= precio_max < 1_000_000_000 and segmento in ['Premium', 'Medio-Alto']:
                    score += 10
                    reasons.append(f"Segmento {segmento}")
                elif precio_max < 400_000_000 and segmento in ['Medio', 'Accesible']:
                    score += 10
                    reasons.append(f"Segmento {segmento}")

            # ===== SCORING TRADICIONAL MEJORADO =====

            # 4. Coincidencia de ubicación (ahora con barrio normalizado)
            if criteria.get('ubicaciones'):
                zona = result.get('zona') or ''
                barrio_norm = result.get('barrio_normalizado') or ''
                direccion = result.get('direccion_completa') or ''

                for ubicacion in criteria['ubicaciones']:
                    if (ubicacion.lower() in zona.lower() or
                        ubicacion.lower() in barrio_norm.lower() or
                        ubicacion.lower() in direccion.lower()):
                        score += 12
                        reasons.append(f"Ubicación: {barrio_norm or zona}")
                        break

            # 5. Walkability score (bonus si es alto)
            walkability = result.get('walkability_score', 0)
            if isinstance(walkability, (int, float)) and walkability >= 8:
                score += 5
                reasons.append(f"Excelente ubicación (walkability: {walkability}/10)")

            # 6. Coincidencia de tipo (puede ser string o lista)
            if criteria.get('tipo_propiedad'):
                tipo_prop = (result.get('tipo_propiedad') or '').lower()
                tipos_buscar = criteria['tipo_propiedad']
                if isinstance(tipos_buscar, list):
                    if any(t.lower() in tipo_prop for t in tipos_buscar):
                        score += 5
                        reasons.append(f"Tipo: {result.get('tipo_propiedad')}")
                elif tipos_buscar.lower() in tipo_prop:
                    score += 5
                    reasons.append(f"Tipo: {result.get('tipo_propiedad')}")

            # 7. Precio comparativo (usar análisis AI)
            precio_comp = result.get('precio_comparativo_zona', '')
            if 'debajo' in precio_comp.lower() or 'oportunidad' in precio_comp.lower():
                score += 10
                reasons.append("Excelente precio para la zona")
            elif 'competitivo' in precio_comp.lower():
                score += 5

            # 8. Coincidencia de precio (mejor si está en el rango ideal)
            precio = result.get('precio', 0)
            if isinstance(precio, str):
                try:
                    precio = float(precio.replace(',', '').replace('$', '').replace(' ', ''))
                except:
                    precio = 0

            if criteria.get('precio_max'):
                if precio <= criteria['precio_max'] * 0.9:  # 10% bajo el máximo
                    score += 8
                    reasons.append("Precio dentro del presupuesto")
                elif precio <= criteria['precio_max']:
                    score += 5

            # 9. Coincidencia de habitaciones exacta
            if criteria.get('habitaciones_min') or criteria.get('habitaciones_max'):
                hab = result.get('habitaciones', 0)
                if not isinstance(hab, (int, float)):
                    try:
                        hab = int(hab)
                    except:
                        hab = 0

                if criteria.get('habitaciones_min') and hab == criteria['habitaciones_min']:
                    score += 7
                    reasons.append(f"{hab} habitaciones (exacto)")
                elif criteria.get('habitaciones_min') and hab >= criteria['habitaciones_min']:
                    score += 3

            # 10. Amenidades inteligentes (usar flags de AI)
            # Si el usuario busca para familia
            if criteria.get('amenidades_requeridas'):
                for amenidad in criteria['amenidades_requeridas']:
                    amenidad_lower = amenidad.lower()

                    # Check AI flags
                    if 'familia' in amenidad_lower or 'niños' in amenidad_lower or 'niño' in amenidad_lower:
                        if result.get('amenidades_familia'):
                            score += 10
                            reasons.append("Ideal para familias")

                    if 'mascota' in amenidad_lower or 'pet' in amenidad_lower or 'perro' in amenidad_lower:
                        if result.get('amenidades_mascota_friendly'):
                            score += 8
                            reasons.append("Pet-friendly")

                    if 'lujo' in amenidad_lower or 'premium' in amenidad_lower:
                        if result.get('amenidades_lujo'):
                            score += 8
                            reasons.append("Amenidades de lujo")

                    if 'seguridad' in amenidad_lower or 'portería' in amenidad_lower or 'vigilancia' in amenidad_lower:
                        if result.get('amenidades_seguridad'):
                            score += 7
                            reasons.append("Alta seguridad")

                    # Check tradicional
                    amenidades_int = result.get('amenidades_internas') or ''
                    amenidades_ext = result.get('amenidades_externas') or ''
                    amenidades_prop = (amenidades_int + ' ' + amenidades_ext).lower()

                    if amenidad.lower() in amenidades_prop:
                        score += 6
                        reasons.append(f"Tiene: {amenidad}")

            # 11. Piso preferido
            if criteria.get('piso'):
                if result.get('piso') == criteria['piso']:
                    score += 8
                    reasons.append(f"Piso {criteria['piso']}")

            # 12. Estado de conservación (bonus por excelente estado)
            estado_cons = result.get('estado_conservacion', '')
            if estado_cons in ['Nuevo', 'Excelente', 'A estrenar']:
                score += 4
                reasons.append(f"Estado: {estado_cons}")

            # 13. Unique Selling Points (bonus por puntos únicos)
            usps = result.get('unique_selling_points', [])
            if isinstance(usps, list) and len(usps) >= 3:
                score += 5
                reasons.append("Características únicas")

            # 14. Rentabilidad para inversionistas
            if criteria.get('es_inversionista'):
                rentabilidad = result.get('valor_rentabilidad_estimada', 0)
                if isinstance(rentabilidad, (int, float)) and rentabilidad >= 4.0:
                    score += 12
                    reasons.append(f"Rentabilidad: {rentabilidad}%")

            # 15. AI Confidence (penalizar si la confianza es muy baja)
            ai_confidence = result.get('ai_confidence_score', 1.0)
            if isinstance(ai_confidence, (int, float)) and ai_confidence < 0.5:
                score = int(score * 0.9)  # Reducir 10% si confianza es baja

            # 16. Más amenidades = mejor
            total_amenidades = result.get('total_amenidades', 0)
            if not isinstance(total_amenidades, (int, float)):
                try:
                    total_amenidades = int(total_amenidades)
                except:
                    total_amenidades = 0

            if total_amenidades > 15:
                score += 4
                reasons.append(f"{total_amenidades} amenidades")

            result['match_score'] = score
            result['match_reasons'] = reasons

        # Ordenar por score descendente
        results.sort(key=lambda x: x.get('match_score', 0), reverse=True)

        return results

    def _fallback_search(self, criteria: Dict[str, Any], db: DatabaseManager) -> List[Dict]:
        """
        Búsqueda relajada si la búsqueda principal no retorna resultados
        Intenta primero con ubicación relajada, luego sin ubicación si no hay resultados
        """

        # Construir query relajada - usa id como slug para links compartibles
        base_query = """
        SELECT
            id, id::text as slug, codigo_propiedad, fuente, url, titulo, precio, precio_texto,
            tipo_propiedad, estado, ciudad, zona, direccion_completa,
            area_construida, habitaciones, banos, parqueaderos, estrato, piso,
            ano_construccion, administracion, predial,
            amenidades_internas, amenidades_externas, total_amenidades,
            asesor, telefono, inmobiliaria, imagen_principal, total_imagenes,
            descripcion, fecha_creacion
        FROM propiedades
        WHERE activa = TRUE
        """

        conditions = []
        params = {}

        # PRIMERO: Intentar con ubicación relajada (buscar ciudad en lugar de zona específica)
        # Mapeo de zonas/barrios a ciudades para búsqueda relajada
        zona_ciudad_map = {
            # Sabaneta
            'sabaneta': 'Sabaneta',
            'rodeo alto': 'Sabaneta',
            'suramerica': 'Sabaneta',
            'mayorca': 'Sabaneta',
            # Envigado
            'envigado': 'Envigado',
            'zuñiga': 'Envigado',
            'la paz': 'Envigado',
            # Itagüí
            'itagui': 'Itagüí',
            'itagüí': 'Itagüí',
            # Bello
            'bello': 'Bello',
            'bello horizonte': 'Bello',
            'niquia': 'Bello',
            # La Estrella
            'la estrella': 'La Estrella',
            # Caldas
            'caldas': 'Caldas',
            # Medellín - Barrios populares
            'poblado': 'Medellín',
            'laureles': 'Medellín',
            'belen': 'Medellín',
            'belén': 'Medellín',
            'calasanz': 'Medellín',
            'robledo': 'Medellín',
            'floresta': 'Medellín',
            'estadio': 'Medellín',
            'conquistadores': 'Medellín',
            'suramericana': 'Medellín',
            'carlos e restrepo': 'Medellín',
            'san javier': 'Medellín',
            'la america': 'Medellín',
            'la américa': 'Medellín',
            'simon bolivar': 'Medellín',
            'simón bolívar': 'Medellín',
            'alfonso lopez': 'Medellín',
            'alfonso lópez': 'Medellín',
            'francisco antonio zea': 'Medellín',
            'san german': 'Medellín',
            'san germán': 'Medellín',
            'gratamira': 'Medellín',
            'aranjuez': 'Medellín',
            'manrique': 'Medellín',
            'campo valdes': 'Medellín',
            'campo valdés': 'Medellín',
            'boston': 'Medellín',
            'buenos aires': 'Medellín',
            'guayabal': 'Medellín',
            'trinidad': 'Medellín',
            'prado': 'Medellín',
            'centro': 'Medellín',
            'castilla': 'Medellín',
            'doce de octubre': 'Medellín',
            '12 de octubre': 'Medellín',
            'pedregal': 'Medellín',
            'santa monica': 'Medellín',
            'santa mónica': 'Medellín',
        }

        # Si hay ubicaciones, buscar en ciudad correspondiente
        if criteria.get('ubicaciones'):
            ciudades_buscar = set()
            zonas_originales = []

            for ubicacion in criteria['ubicaciones']:
                ubicacion_lower = ubicacion.lower()
                zonas_originales.append(ubicacion)

                # Buscar la ciudad correspondiente
                for zona_key, ciudad in zona_ciudad_map.items():
                    if zona_key in ubicacion_lower:
                        ciudades_buscar.add(ciudad)
                        break

            # Si encontramos ciudades, buscar por ciudad O por zona original (más flexible)
            if ciudades_buscar:
                location_conditions = []

                # Buscar por ciudad
                for i, ciudad in enumerate(ciudades_buscar):
                    location_conditions.append(f"ciudad ILIKE %(ciudad_{i})s")
                    params[f'ciudad_{i}'] = f'%{ciudad}%'

                # También buscar por zona/título original (por si está escrito diferente)
                for i, zona in enumerate(zonas_originales):
                    location_conditions.append(
                        f"(zona ILIKE %(zona_orig_{i})s OR titulo ILIKE %(zona_orig_{i})s)"
                    )
                    params[f'zona_orig_{i}'] = f'%{zona}%'

                conditions.append(f"({' OR '.join(location_conditions)})")

        # Tipo de propiedad (puede ser string o lista)
        if criteria.get('tipo_propiedad'):
            tipos = criteria['tipo_propiedad']
            if isinstance(tipos, list):
                tipo_conditions = []
                for i, tipo in enumerate(tipos):
                    tipo_conditions.append(f"tipo_propiedad ILIKE %(tipo_fb_{i})s")
                    params[f'tipo_fb_{i}'] = f'%{tipo}%'
                conditions.append(f"({' OR '.join(tipo_conditions)})")
            else:
                conditions.append("tipo_propiedad ILIKE %(tipo_propiedad)s")
                params['tipo_propiedad'] = f"%{tipos}%"

        # Precio máximo relajado al 130% (no tan amplio como antes)
        if criteria.get('precio_max'):
            conditions.append("precio <= %(precio_max_relajado)s")
            params['precio_max_relajado'] = criteria['precio_max'] * 1.3

        # Habitaciones mínimas relajadas (acepta 1 menos)
        if criteria.get('habitaciones_min') and criteria['habitaciones_min'] > 1:
            conditions.append("habitaciones >= %(habitaciones_min_relajado)s")
            params['habitaciones_min_relajado'] = criteria['habitaciones_min'] - 1

        # Agregar condiciones
        if conditions:
            base_query += " AND " + " AND ".join(conditions)

        # Ordenar por precio y amenidades
        base_query += " ORDER BY precio ASC, total_amenidades DESC LIMIT 20"

        try:
            db.cursor.execute(base_query, params)
            columns = [desc[0] for desc in db.cursor.description]
            rows = db.cursor.fetchall()

            results = []
            for row in rows:
                # Si row ya es un diccionario (RealDictRow), convertirlo a dict normal
                if isinstance(row, dict):
                    prop = dict(row)
                else:
                    # Si es tupla, zip con columnas
                    prop = dict(zip(columns, row))

                # Convertir tipos para JSON
                for key, value in prop.items():
                    if hasattr(value, 'isoformat'):
                        prop[key] = value.isoformat()
                    elif isinstance(value, (int, float, str, bool, type(None))):
                        continue
                    else:
                        prop[key] = str(value)
                results.append(prop)

            return results

        except Exception as e:
            print(f"⚠️  Error en búsqueda fallback: {e}")
            return []

    def _minimal_fallback_search(self, criteria: Dict[str, Any], db: DatabaseManager) -> List[Dict]:
        """
        Búsqueda mínima: solo tipo de propiedad + ciudad
        Ignora precio, habitaciones y amenidades
        Sirve para verificar si hay ALGUNA propiedad disponible en la zona
        """
        base_query = """
        SELECT
            id, id::text as slug, codigo_propiedad, fuente, url, titulo, precio, precio_texto,
            tipo_propiedad, estado, ciudad, zona, direccion_completa,
            area_construida, habitaciones, banos, parqueaderos, estrato, piso,
            ano_construccion, administracion, predial,
            amenidades_internas, amenidades_externas, total_amenidades,
            asesor, telefono, inmobiliaria, imagen_principal, total_imagenes,
            descripcion, fecha_creacion
        FROM propiedades
        WHERE activa = TRUE
        """

        conditions = []
        params = {}

        # Solo tipo de propiedad (puede ser lista)
        if criteria.get('tipo_propiedad'):
            tipos = criteria['tipo_propiedad']
            if isinstance(tipos, list):
                tipo_conditions = []
                for i, tipo in enumerate(tipos):
                    tipo_conditions.append(f"tipo_propiedad ILIKE %(tipo_min_{i})s")
                    params[f'tipo_min_{i}'] = f'%{tipo}%'
                conditions.append(f"({' OR '.join(tipo_conditions)})")
            else:
                conditions.append("tipo_propiedad ILIKE %(tipo_propiedad)s")
                params['tipo_propiedad'] = f"%{tipos}%"

        # Buscar en TODAS las ciudades mencionadas (usando el mapeo expandido)
        zona_ciudad_map = {
            'calasanz': 'Medellín', 'robledo': 'Medellín', 'floresta': 'Medellín',
            'bello horizonte': 'Bello', 'bello': 'Bello', 'alfonso lopez': 'Medellín',
            'alfonso lópez': 'Medellín', 'francisco antonio zea': 'Medellín',
            'san german': 'Medellín', 'san germán': 'Medellín', 'gratamira': 'Medellín',
            'laureles': 'Medellín', 'poblado': 'Medellín', 'envigado': 'Envigado',
            'sabaneta': 'Sabaneta', 'itagui': 'Itagüí', 'itagüí': 'Itagüí',
        }

        if criteria.get('ubicaciones'):
            ciudades_buscar = set()
            zonas_originales = []

            for ubicacion in criteria['ubicaciones']:
                ubicacion_lower = ubicacion.lower()
                zonas_originales.append(ubicacion)

                # Buscar la ciudad correspondiente
                for zona_key, ciudad in zona_ciudad_map.items():
                    if zona_key in ubicacion_lower:
                        ciudades_buscar.add(ciudad)
                        break

            if ciudades_buscar or zonas_originales:
                location_conditions = []

                # Buscar por ciudad
                for i, ciudad in enumerate(ciudades_buscar):
                    location_conditions.append(f"ciudad ILIKE %(ciudad_min_{i})s")
                    params[f'ciudad_min_{i}'] = f'%{ciudad}%'

                # También buscar por zona/título original
                for i, zona in enumerate(zonas_originales):
                    location_conditions.append(
                        f"(zona ILIKE %(zona_min_{i})s OR titulo ILIKE %(zona_min_{i})s)"
                    )
                    params[f'zona_min_{i}'] = f'%{zona}%'

                if location_conditions:
                    conditions.append(f"({' OR '.join(location_conditions)})")

        # Si no hay ninguna condición, buscar todo
        if conditions:
            base_query += " AND " + " AND ".join(conditions)

        base_query += " ORDER BY precio ASC LIMIT 10"

        try:
            db.cursor.execute(base_query, params)
            columns = [desc[0] for desc in db.cursor.description]
            rows = db.cursor.fetchall()

            results = []
            for row in rows:
                if isinstance(row, dict):
                    prop = dict(row)
                else:
                    prop = dict(zip(columns, row))

                for key, value in prop.items():
                    if hasattr(value, 'isoformat'):
                        prop[key] = value.isoformat()
                    elif isinstance(value, (int, float, str, bool, type(None))):
                        continue
                    else:
                        prop[key] = str(value)
                results.append(prop)

            return results

        except Exception as e:
            print(f"⚠️  Error en búsqueda mínima: {e}")
            return []

    def search(self, query: str, limit: int = 10, sender: str = None) -> Dict[str, Any]:
        """
        Búsqueda principal: procesa consulta en lenguaje natural y retorna propiedades

        Args:
            query: Mensaje del agente inmobiliario
            limit: Número máximo de resultados a retornar
            sender: Teléfono del remitente (para logging)

        Returns:
            Diccionario con criterios, resultados y metadatos
        """
        # Iniciar tracking de la búsqueda
        search_id = search_log.start_search(query, sender)
        total_start = time.time()

        print("=" * 80)
        print("  BÚSQUEDA INTELIGENTE DE PROPIEDADES")
        print("=" * 80)
        print()
        print("📝 Consulta:")
        print(f"   {query[:200]}...")
        print()

        # Paso 1: Extraer criterios con Claude
        print("🧠 Analizando criterios con Claude...")
        criteria = self._extract_search_criteria(query)

        if not criteria:
            search_log.log_error('No se pudieron extraer criterios de búsqueda', 'criteria_extraction')
            return {
                'success': False,
                'error': 'No se pudieron extraer criterios de búsqueda',
                'criteria': {},
                'results': []
            }

        print("✅ Criterios extraídos:")
        print(json.dumps(criteria, indent=2, ensure_ascii=False))
        print()

        # Paso 2: Intentar búsqueda vectorial primero (si está disponible)
        vector_results = []
        if VECTOR_SEARCH_AVAILABLE:
            try:
                print("🔮 Intentando búsqueda vectorial...")
                vector_search = get_vector_search()
                vector_response = vector_search.search(query, criteria, limit=limit)

                if vector_response.get('success') and vector_response.get('results'):
                    vector_results = vector_response['results']
                    print(f"✅ Búsqueda vectorial encontró: {len(vector_results)} propiedades")

                    # Si tenemos resultados vectoriales, usarlos directamente
                    if len(vector_results) >= 3:
                        # Log de resultados
                        total_elapsed = (time.time() - total_start) * 1000
                        search_log.log_results(len(vector_results), min(len(vector_results), limit), total_elapsed)

                        return {
                            'success': True,
                            'criteria': criteria,
                            'results': vector_results[:limit],
                            'total_found': len(vector_results),
                            'search_type': 'vector'
                        }
                    else:
                        print("ℹ️  Pocos resultados vectoriales, complementando con SQL...")

            except Exception as e:
                print(f"⚠️  Error en búsqueda vectorial: {e}")
                print("   Fallback a búsqueda SQL tradicional...")

        # Paso 3: Búsqueda SQL tradicional (fallback o complementaria)
        print("🔍 Buscando en base de datos (SQL)...")
        sql_query, params = self._build_sql_query(criteria)

        # Paso 3: Ejecutar búsqueda en DB
        try:
            sql_start = time.time()
            with DatabaseManager() as db:
                db.cursor.execute(sql_query, params)
                columns = [desc[0] for desc in db.cursor.description]
                rows = db.cursor.fetchall()

                sql_elapsed = (time.time() - sql_start) * 1000
                search_log.log_sql_query(sql_query, params, sql_elapsed)

                results = []
                for row in rows:
                    # Si row ya es un diccionario (RealDictRow), convertirlo a dict normal
                    if isinstance(row, dict):
                        prop = dict(row)
                    else:
                        # Si es tupla, zip con columnas
                        prop = dict(zip(columns, row))

                    # Convertir tipos para JSON
                    for key, value in prop.items():
                        if hasattr(value, 'isoformat'):  # datetime
                            prop[key] = value.isoformat()
                        elif isinstance(value, (int, float, str, bool, type(None))):
                            continue
                        else:
                            prop[key] = str(value)
                    results.append(prop)

                print(f"📊 Propiedades encontradas: {len(results)}")

                # Si no hay resultados, intentar búsqueda más relajada
                if len(results) == 0:
                    print("⚠️  Sin resultados con todos los criterios. Intentando búsqueda relajada...")
                    results = self._fallback_search(criteria, db)
                    print(f"📊 Búsqueda relajada encontró: {len(results)} propiedades")

                    # Si aún no hay resultados, buscar solo por tipo y ciudad (ignorar precio/habitaciones)
                    if len(results) == 0:
                        print("⚠️  Intentando búsqueda mínima (solo tipo + ubicación)...")
                        results = self._minimal_fallback_search(criteria, db)
                        print(f"📊 Búsqueda mínima encontró: {len(results)} propiedades")

        except Exception as e:
            search_log.log_error(str(e), 'sql_execution')
            print(f"❌ Error en búsqueda DB: {e}")
            return {
                'success': False,
                'error': str(e),
                'criteria': criteria,
                'results': []
            }

        print()

        # Paso 4: Rankear resultados
        if results:
            print("⭐ Rankeando resultados...")
            rank_start = time.time()
            results = self._rank_results(results, criteria)
            results = results[:limit]

            rank_elapsed = (time.time() - rank_start) * 1000
            top_scores = [{'id': r.get('id'), 'score': r.get('match_score', 0)} for r in results[:5]]
            search_log.log_ranking(top_scores, rank_elapsed)

        # Log de resultados finales
        total_elapsed = (time.time() - total_start) * 1000
        search_log.log_results(len(results), min(len(results), limit), total_elapsed)

        # Paso 5: Formatear respuesta
        return {
            'success': True,
            'criteria': criteria,
            'total_found': len(results),
            'results': results,
            'timestamp': datetime.now().isoformat(),
            'search_id': search_id,
            'elapsed_ms': total_elapsed
        }

    def format_results_for_agent(self, search_response: Dict) -> str:
        """
        Formatea los resultados de forma amigable para el agente inmobiliario

        Args:
            search_response: Respuesta de la búsqueda

        Returns:
            Texto formateado para WhatsApp/mensaje
        """

        if not search_response.get('success'):
            return f"❌ Error: {search_response.get('error', 'Error desconocido')}"

        results = search_response.get('results', [])
        criteria = search_response.get('criteria', {})

        if not results:
            return "😔 No se encontraron propiedades que coincidan con los criterios."

        # Construir mensaje
        lines = []
        lines.append("🏠 PROPIEDADES ENCONTRADAS")
        lines.append("=" * 50)
        lines.append("")

        # Resumen de búsqueda
        lines.append("📋 Criterios de búsqueda:")
        if criteria.get('ubicaciones'):
            lines.append(f"   📍 Ubicación: {', '.join(criteria['ubicaciones'])}")
        if criteria.get('tipo_propiedad'):
            lines.append(f"   🏢 Tipo: {criteria['tipo_propiedad']}")
        if criteria.get('precio_max'):
            precio_max = criteria['precio_max'] / 1_000_000
            lines.append(f"   💰 Hasta: ${precio_max:.0f}M")
        if criteria.get('habitaciones_min'):
            lines.append(f"   🛏️  Habitaciones: {criteria['habitaciones_min']}+")
        lines.append("")
        lines.append(f"✅ {len(results)} propiedades coinciden")
        lines.append("")

        # Listar propiedades (top 5)
        for i, prop in enumerate(results[:5], 1):
            score = prop.get('match_score', 0)
            lines.append(f"━━━ #{i} - Match: {score} pts ━━━")
            lines.append(f"🏠 {prop.get('titulo', 'Sin título')}")
            lines.append(f"💵 {prop.get('precio_texto', 'Precio no disponible')}")
            lines.append(f"📍 {prop.get('zona', '')} - {prop.get('ciudad', '')}")

            # Convertir valores a números de forma segura
            area = prop.get('area_construida', 0)
            if not isinstance(area, (int, float)):
                try:
                    area = float(area)
                except:
                    area = 0

            hab = prop.get('habitaciones', 0)
            if not isinstance(hab, (int, float)):
                try:
                    hab = int(hab)
                except:
                    hab = 0

            banos = prop.get('banos', 0)
            if not isinstance(banos, (int, float)):
                try:
                    banos = int(banos)
                except:
                    banos = 0

            pkdros = prop.get('parqueaderos', 0)
            if not isinstance(pkdros, (int, float)):
                try:
                    pkdros = int(pkdros)
                except:
                    pkdros = 0

            lines.append(f"📐 {area:.0f}m² | "
                        f"{hab} hab | "
                        f"{banos} baños | "
                        f"{pkdros} pkdros")

            if prop.get('piso'):
                lines.append(f"🏢 Piso: {prop.get('piso')}")

            # Razones de coincidencia
            if prop.get('match_reasons'):
                lines.append(f"✨ {', '.join(prop['match_reasons'][:3])}")

            # Contacto
            if prop.get('asesor') or prop.get('telefono'):
                asesor = prop.get('asesor', 'No disponible')
                telefono = prop.get('telefono', '')
                lines.append(f"👤 {asesor} {telefono}")

            # URL
            if prop.get('url'):
                lines.append(f"🔗 {prop.get('url')}")

            lines.append("")

        if len(results) > 5:
            lines.append(f"... y {len(results) - 5} propiedades más")
            lines.append("")

        lines.append("=" * 50)

        return "\n".join(lines)


def main():
    """Función principal para pruebas"""

    # Verificar API Key
    if not os.getenv('ANTHROPIC_API_KEY'):
        print("❌ Error: ANTHROPIC_API_KEY no configurada en .env")
        print()
        print("Agrega a tu archivo .env:")
        print("ANTHROPIC_API_KEY=tu_api_key_aqui")
        print()
        print("Obtén tu API key en: https://console.anthropic.com/")
        return

    # Crear agente
    try:
        agent = PropertySearchAgent()
    except Exception as e:
        print(f"❌ Error al crear agente: {e}")
        return

    # Consultas de prueba (ejemplos reales del usuario)
    test_queries = [
        """Busco apto cliente tu 360 en ciudad del Río o Laureles
Persona mayor primer piso. 2 o 3 habitaciones.
Con portería.
Presupuesto 1000 millones.
Rocío Escudero Vega
3103721706""",

        """Busco para una cliente de tu 360inmobiliario
Súper compradora !!!!!!!!

Hasta $800 millones
Apartamento de dos alcobas CADA UNA CON BAÑO.
BALCON
Baño social
Ojalá con un estudio o que la alcoba principal sea amplia
80 m2 o más
Ojalá unidad con piscina
Directo por favor !
LE GUSTA :
Loma de san Julián
Loma del encierro
Castropol
Lalinde""",

        """APTO EL TRIANON EL DORADO LA CUENCA LAS ANTILLAS ALCALA

✅500.000 MILLONES
 3 HABITACIONES
Ojala unidad completa

Soy Sandra Echeverri Asesora inmobiliaria
📲Contáctame:
Cel :3235075028"""
    ]

    # Ejecutar búsqueda con primera consulta
    print("\n")
    print("🚀 Ejecutando búsqueda de prueba...")
    print()

    query = test_queries[0]

    search_response = agent.search(query, limit=10)

    # Mostrar resultados formateados
    print()
    print(agent.format_results_for_agent(search_response))

    # Guardar resultados en JSON
    output_file = f"busqueda_resultado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(search_response, f, indent=2, ensure_ascii=False)

    print()
    print(f"💾 Resultados guardados en: {output_file}")
    print()


if __name__ == "__main__":
    main()
