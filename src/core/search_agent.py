#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Búsqueda Inteligente de Propiedades v2.0
Usa Claude API (Anthropic) para procesar consultas en lenguaje natural
y encontrar propiedades que coincidan con los criterios de los agentes inmobiliarios

MEJORAS v2.0:
- Filtros duros de precio que nunca se relajan (±15% del presupuesto)
- Detección automática de perfil de comprador
- Scoring inteligente por perfil
- Búsqueda vectorial como protagonista
- Explicabilidad en resultados
"""

import os
import re
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dotenv import load_dotenv

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("⚠️  Módulo 'anthropic' no instalado. Ejecuta: pip install anthropic")

from src.db.database import DatabaseManager
from src.core.logger import get_search_logger, log_execution_time

# Importar configuración de búsqueda Colombia
from src.core.search_config import (
    SEGMENTOS_PRECIO_COLOMBIA,
    TOLERANCIA_PRECIO_POR_SEGMENTO,
    PERFILES_COMPRADOR,
    ZONA_A_CIUDAD,
    ZONAS_SIMILARES,
    DEFAULT_SEARCH_CONFIG,
    get_segmento_precio,
    get_tolerancia_precio,
    calcular_rango_precio,
    detectar_perfil_comprador,
    get_zonas_expandidas,
    get_pesos_perfil,
    get_amenidades_preferidas,
    AMENIDADES_SEGURIDAD,
    AMENIDADES_FAMILIA,
    AMENIDADES_LUJO,
    AMENIDADES_ACCESIBILIDAD,
)

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
        MEJORADO v2.0: Extrae perfil de comprador, banos_max, y más contexto

        Args:
            query: Mensaje del agente inmobiliario (puede ser informal/WhatsApp)

        Returns:
            Diccionario con criterios estructurados
        """

        system_prompt = """Eres un asistente experto en bienes raíces en Medellín, Colombia.
Tu tarea es analizar mensajes de agentes inmobiliarios y extraer los criterios de búsqueda de propiedades.

Debes extraer y estructurar la siguiente información cuando esté disponible:
- ubicaciones: Lista de zonas/barrios mencionados (ej: ["Laureles", "Ciudad del Río"])
- tipo_propiedad: Tipo (Apartamento, Casa, Penthouse, Duplex, Local, Oficina)
- precio_min: Precio mínimo en COP (número). Si no se menciona explícitamente, NO incluir.
- precio_max: Precio máximo en COP (número). Este es el presupuesto del cliente.
- habitaciones_min: Mínimo de habitaciones
- habitaciones_max: Máximo de habitaciones (si dice "2 o 3" entonces min=2, max=3)
- banos_min: Mínimo de baños
- banos_max: Máximo de baños (si dice "máximo 2 baños" entonces banos_max=2)
- area_min: Área mínima en m²
- area_max: Área máxima en m²
- piso: Número de piso específico (1 para primer piso)
- amenidades_requeridas: Lista de amenidades importantes (ej: ["portería", "piscina", "balcón"])
- caracteristicas_especiales: Características mencionadas (ej: "baño en cada habitación", "estudio")
- perfil_comprador: Detectar el perfil del comprador basado en el mensaje:
  * "familia" - Si menciona familia, niños, hijos, colegios
  * "inversionista" - Si menciona inversión, rentabilidad, arriendo
  * "senior" - Si menciona persona mayor, tercera edad, primer piso por accesibilidad
  * "joven_profesional" - Si menciona soltero, moderno, cerca al trabajo
  * "general" - Si no hay indicadores claros
- urgencia: true/false si se menciona "urgente", "ya", "rápido", "compradora lista"
- flexibilidad_precio: "estricto" si dice "máximo", "hasta"; "flexible" si dice "alrededor de", "más o menos"
- notas: Cualquier otra información relevante (nombre del cliente, contacto, etc.)

IMPORTANTE - CONVERSIÓN DE PRECIOS COLOMBIANOS:
- "1000 millones" = 1,000,000,000 COP (mil millones)
- "800 millones" = 800,000,000 COP
- "500 millones" = 500,000,000 COP
- "Hasta $800 millones" significa precio_max = 800,000,000
- "Presupuesto 1000 millones" significa precio_max = 1,000,000,000
- "Entre 500 y 800" significa precio_min = 500,000,000, precio_max = 800,000,000

UBICACIONES EN ÁREA METROPOLITANA DE MEDELLÍN:
- Medellín: El Poblado, Laureles, Belén, Estadio, Conquistadores, Floresta, Calasanz, Robledo, Ciudad del Río, Castropol, Lalinde
- Envigado: Zúñiga, La Paz, El Portal, Las Antillas, El Dorado, Alcalá, La Cuenca, El Trianón
- Sabaneta: Aves María, Mayorca, La Doctora
- Itagüí: Ditaires, Santa María
- Bello: Niquía, París

DETECCIÓN DE PERFIL:
- "Persona mayor", "primer piso por accesibilidad" → perfil_comprador: "senior"
- "Familia con niños", "cerca a colegios" → perfil_comprador: "familia"
- "Para inversión", "rentabilidad" → perfil_comprador: "inversionista"

TÉRMINOS COLOMBIANOS:
- "Alcoba" = habitación
- "Parqueadero" = garaje
- "Cuarto útil" = depósito
- "Baño en cada habitación" = característica importante
- "Portería", "vigilancia" = amenidades de seguridad
- "Unidad completa" = conjunto residencial con todas las amenidades

Responde SOLO con un JSON válido, sin texto adicional ni markdown."""

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

            # ===== ENRIQUECIMIENTO POST-EXTRACCIÓN v2.0 =====

            # 1. Calcular rango de precio implícito si solo hay precio_max
            if criteria.get('precio_max') and not criteria.get('precio_min'):
                precio_max = criteria['precio_max']
                precio_min, precio_max_ajustado = calcular_rango_precio(precio_max)
                criteria['precio_min_implicito'] = precio_min
                criteria['precio_max_ajustado'] = precio_max_ajustado
                criteria['segmento_precio'] = get_segmento_precio(precio_max)
                criteria['tolerancia_aplicada'] = get_tolerancia_precio(precio_max)

            # 2. Detectar/confirmar perfil de comprador
            perfil_claude = criteria.get('perfil_comprador', 'general')
            perfil_detectado = detectar_perfil_comprador(query, criteria)
            # Si Claude detectó algo específico, usarlo; si no, usar nuestro detector
            if perfil_claude == 'general' and perfil_detectado != 'general':
                criteria['perfil_comprador'] = perfil_detectado
            elif perfil_claude == 'general':
                criteria['perfil_comprador'] = perfil_detectado

            # 3. Expandir zonas similares si hay ubicaciones
            if criteria.get('ubicaciones'):
                zonas_expandidas = []
                for zona in criteria['ubicaciones']:
                    expandidas = get_zonas_expandidas(zona)
                    for z in expandidas:
                        if z not in zonas_expandidas:
                            zonas_expandidas.append(z)
                criteria['zonas_expandidas'] = zonas_expandidas

            # 4. Normalizar flexibilidad de precio
            if not criteria.get('flexibilidad_precio'):
                # Por defecto, si dice "hasta" o "máximo" es estricto
                query_lower = query.lower()
                if 'máximo' in query_lower or 'hasta' in query_lower or 'maximo' in query_lower:
                    criteria['flexibilidad_precio'] = 'estricto'
                else:
                    criteria['flexibilidad_precio'] = 'normal'

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

    def _build_sql_query(self, criteria: Dict[str, Any], use_hard_filters: bool = True) -> tuple:
        """
        Construye una consulta SQL basada en los criterios extraídos
        MEJORADO v2.0: Filtros duros de precio que nunca se relajan

        Args:
            criteria: Diccionario de criterios de búsqueda
            use_hard_filters: Si usar filtros duros de precio (default True)

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

        # ========== FILTROS DUROS (NUNCA SE RELAJAN) ==========

        # FILTRO DURO #1: Rango de precio con tolerancia del segmento
        if use_hard_filters and criteria.get('precio_max'):
            # Usar precio_min implícito calculado (±tolerancia del segmento)
            precio_min_duro = criteria.get('precio_min_implicito') or criteria.get('precio_min')
            precio_max_duro = criteria.get('precio_max_ajustado') or criteria['precio_max']

            # Si hay precio_min explícito del usuario, usarlo
            if criteria.get('precio_min'):
                precio_min_duro = criteria['precio_min']

            if precio_min_duro:
                conditions.append("precio >= %(precio_min_duro)s")
                params['precio_min_duro'] = precio_min_duro

            conditions.append("precio <= %(precio_max_duro)s")
            params['precio_max_duro'] = precio_max_duro

        elif criteria.get('precio_max'):
            # Fallback sin filtros duros (para búsquedas relajadas)
            conditions.append("precio <= %(precio_max)s")
            params['precio_max'] = criteria['precio_max']

        # FILTRO DURO #2: Tipo de propiedad (puede ser string o lista)
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

        # ========== FILTROS FLEXIBLES ==========

        # Filtro por ubicaciones (zonas, ciudad, dirección o título)
        # Incluye zonas expandidas si están disponibles
        ubicaciones_buscar = criteria.get('zonas_expandidas') or criteria.get('ubicaciones')
        if ubicaciones_buscar:
            zona_conditions = []
            for i, ubicacion in enumerate(ubicaciones_buscar):
                # Buscar en zona, ciudad, dirección Y título (más flexible)
                zona_conditions.append(
                    f"(zona ILIKE %(ubicacion_{i})s OR "
                    f"ciudad ILIKE %(ubicacion_{i})s OR "
                    f"direccion_completa ILIKE %(ubicacion_{i})s OR "
                    f"titulo ILIKE %(ubicacion_{i})s)"
                )
                params[f'ubicacion_{i}'] = f'%{ubicacion}%'
            conditions.append(f"({' OR '.join(zona_conditions)})")

        # Filtro por habitaciones
        if criteria.get('habitaciones_min'):
            conditions.append("habitaciones >= %(habitaciones_min)s")
            params['habitaciones_min'] = criteria['habitaciones_min']

        if criteria.get('habitaciones_max'):
            conditions.append("habitaciones <= %(habitaciones_max)s")
            params['habitaciones_max'] = criteria['habitaciones_max']

        # Filtro por baños (MEJORADO v2.0: ahora incluye banos_max)
        if criteria.get('banos_min'):
            conditions.append("banos >= %(banos_min)s")
            params['banos_min'] = criteria['banos_min']

        if criteria.get('banos_max'):
            conditions.append("banos <= %(banos_max)s")
            params['banos_max'] = criteria['banos_max']

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

        # Filtro por amenidades (ahora es opcional, no elimina resultados)
        # Las amenidades se usan más para ranking que para filtrado duro
        # Solo aplicar si hay pocas amenidades requeridas (máx 2)
        if criteria.get('amenidades_requeridas'):
            amenidades = criteria['amenidades_requeridas']
            if len(amenidades) <= 2:  # Solo filtrar si son pocas
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

        # Limitar resultados (más para ranking posterior)
        base_query += " LIMIT 50"

        return base_query, params

    def _rank_results(self, results: List[Dict], criteria: Dict[str, Any]) -> List[Dict]:
        """
        Rankea los resultados según qué tan bien coinciden con los criterios
        MEJORADO v2.0: Scoring por perfil de comprador y explicabilidad

        Args:
            results: Lista de propiedades encontradas
            criteria: Criterios de búsqueda originales

        Returns:
            Lista rankeada con score de coincidencia (0-100 normalizado)
        """
        perfil_comprador = criteria.get('perfil_comprador', 'general')
        pesos_perfil = get_pesos_perfil(perfil_comprador)
        amenidades_preferidas = get_amenidades_preferidas(perfil_comprador)

        for result in results:
            score = 0
            reasons = []
            match_details = {
                'precio': 'no_evaluado',
                'ubicacion': 'no_evaluado',
                'habitaciones': 'no_evaluado',
                'amenidades': 'no_evaluado'
            }

            # ===== SCORING POR PERFIL DE COMPRADOR v2.0 =====

            # 1. PRECIO - Evaluación detallada
            precio = result.get('precio', 0)
            if isinstance(precio, str):
                try:
                    precio = float(precio.replace(',', '').replace('$', '').replace(' ', ''))
                except:
                    precio = 0

            if criteria.get('precio_max') and precio > 0:
                precio_max = criteria['precio_max']
                precio_min = criteria.get('precio_min_implicito') or criteria.get('precio_min') or 0

                # Calcular qué tan bien encaja el precio
                if precio_min <= precio <= precio_max:
                    # Precio en rango ideal
                    rango = precio_max - precio_min if precio_min else precio_max
                    # Mejor si está en el 70-90% del presupuesto (ni muy barato ni muy caro)
                    ratio = precio / precio_max
                    if 0.70 <= ratio <= 0.90:
                        score += 15
                        match_details['precio'] = 'ideal'
                        reasons.append(f"Precio ideal ({ratio*100:.0f}% del presupuesto)")
                    elif ratio <= 0.70:
                        score += 10
                        match_details['precio'] = 'bajo'
                        reasons.append("Precio bajo el presupuesto")
                    else:
                        score += 12
                        match_details['precio'] = 'limite'
                        reasons.append("Precio cerca del límite")
                elif precio > precio_max:
                    # Penalizar propiedades fuera del rango (no deberían llegar aquí con filtros duros)
                    score -= 20
                    match_details['precio'] = 'excede'

            # 2. UBICACIÓN - Coincidencia exacta vs zona expandida
            if criteria.get('ubicaciones'):
                zona = (result.get('zona') or '').lower()
                ciudad = (result.get('ciudad') or '').lower()
                direccion = (result.get('direccion_completa') or '').lower()
                titulo = (result.get('titulo') or '').lower()

                ubicacion_match = False
                for ubicacion in criteria['ubicaciones']:
                    ub_lower = ubicacion.lower()
                    if ub_lower in zona or ub_lower in titulo:
                        score += 15
                        match_details['ubicacion'] = 'exacta'
                        reasons.append(f"Ubicación exacta: {result.get('zona', ubicacion)}")
                        ubicacion_match = True
                        break

                # Si no hay match exacto, verificar zonas expandidas
                if not ubicacion_match and criteria.get('zonas_expandidas'):
                    for zona_exp in criteria['zonas_expandidas']:
                        if zona_exp.lower() in zona or zona_exp.lower() in titulo:
                            score += 8
                            match_details['ubicacion'] = 'cercana'
                            reasons.append(f"Zona cercana: {result.get('zona')}")
                            break

            # 3. HABITACIONES - Exacto vs rango
            if criteria.get('habitaciones_min') or criteria.get('habitaciones_max'):
                hab = result.get('habitaciones', 0)
                if not isinstance(hab, (int, float)):
                    try:
                        hab = int(hab)
                    except:
                        hab = 0

                hab_min = criteria.get('habitaciones_min', 0)
                hab_max = criteria.get('habitaciones_max', 99)

                if hab_min <= hab <= hab_max:
                    if hab == hab_min or (hab_max and hab == hab_max):
                        score += 10
                        match_details['habitaciones'] = 'exacto'
                        reasons.append(f"{hab} habitaciones (exacto)")
                    else:
                        score += 7
                        match_details['habitaciones'] = 'rango'
                        reasons.append(f"{hab} habitaciones")
                elif hab > hab_max:
                    score -= 5  # Penalizar si excede el máximo
                    match_details['habitaciones'] = 'excede'

            # 4. BAÑOS - Ahora incluye max
            if criteria.get('banos_min') or criteria.get('banos_max'):
                banos = result.get('banos', 0)
                if not isinstance(banos, (int, float)):
                    try:
                        banos = int(banos)
                    except:
                        banos = 0

                banos_min = criteria.get('banos_min', 0)
                banos_max = criteria.get('banos_max', 99)

                if banos_min <= banos <= banos_max:
                    score += 5
                    reasons.append(f"{banos} baños")
                elif banos > banos_max:
                    score -= 3  # Penalizar si excede

            # 5. PISO - Crítico para perfil senior
            if criteria.get('piso'):
                piso_buscado = criteria['piso']
                piso_prop = result.get('piso')

                peso_piso = pesos_perfil.get('primer_piso', 1.0) if piso_buscado == 1 else 1.0

                if piso_prop == piso_buscado:
                    score += int(10 * peso_piso)
                    reasons.append(f"Piso {piso_buscado} (requerido)")
                elif piso_buscado == 1 and piso_prop and piso_prop > 1:
                    # Para seniors, no primer piso es muy malo
                    if perfil_comprador == 'senior':
                        score -= 15
                        reasons.append("No es primer piso (requerido)")

            # ===== SCORING POR PERFIL ESPECÍFICO =====

            # 6. Amenidades según perfil
            amenidades_int = (result.get('amenidades_internas') or '').lower()
            amenidades_ext = (result.get('amenidades_externas') or '').lower()
            amenidades_prop = amenidades_int + ' ' + amenidades_ext

            amenidades_encontradas = []
            for amenidad in amenidades_preferidas:
                if amenidad.lower() in amenidades_prop:
                    amenidades_encontradas.append(amenidad)
                    score += 3  # Bonus por cada amenidad preferida del perfil

            if amenidades_encontradas:
                match_details['amenidades'] = 'match'
                reasons.append(f"Amenidades ideales: {', '.join(amenidades_encontradas[:3])}")

            # 7. Amenidades requeridas explícitamente
            if criteria.get('amenidades_requeridas'):
                for amenidad in criteria['amenidades_requeridas']:
                    if amenidad.lower() in amenidades_prop:
                        score += 5
                        if f"Tiene: {amenidad}" not in reasons:
                            reasons.append(f"Tiene: {amenidad}")

            # 8. Seguridad - Importante para familias y seniors
            if perfil_comprador in ['familia', 'senior']:
                tiene_seguridad = any(s in amenidades_prop for s in AMENIDADES_SEGURIDAD)
                if tiene_seguridad:
                    score += int(5 * pesos_perfil.get('seguridad', 1.0))
                    reasons.append("Alta seguridad")

            # ===== SCORING ADICIONAL =====

            # 9. Segmento de mercado adecuado
            segmento = result.get('segmento_mercado', '')
            if criteria.get('precio_max'):
                precio_max = criteria['precio_max']
                if precio_max >= 1_000_000_000 and segmento in ['Lujo', 'Premium']:
                    score += 8
                    reasons.append(f"Segmento {segmento}")
                elif 400_000_000 <= precio_max < 1_000_000_000 and segmento in ['Premium', 'Medio-Alto']:
                    score += 8
                    reasons.append(f"Segmento {segmento}")
                elif precio_max < 400_000_000 and segmento in ['Medio', 'Accesible']:
                    score += 8
                    reasons.append(f"Segmento {segmento}")

            # 10. Tipo de propiedad
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

            # 11. Estado de conservación
            estado_cons = result.get('estado_conservacion', '')
            if estado_cons in ['Nuevo', 'Excelente', 'A estrenar']:
                score += 4
                reasons.append(f"Estado: {estado_cons}")

            # 12. Rentabilidad para inversionistas
            if perfil_comprador == 'inversionista' or criteria.get('es_inversionista'):
                rentabilidad = result.get('valor_rentabilidad_estimada', 0)
                if isinstance(rentabilidad, (int, float)) and rentabilidad >= 4.0:
                    score += int(12 * pesos_perfil.get('rentabilidad', 1.0))
                    reasons.append(f"Rentabilidad: {rentabilidad}%")

            # 13. Total amenidades bonus
            total_amenidades = result.get('total_amenidades', 0)
            if not isinstance(total_amenidades, (int, float)):
                try:
                    total_amenidades = int(total_amenidades)
                except:
                    total_amenidades = 0

            if total_amenidades > 15:
                score += 4
                reasons.append(f"{total_amenidades} amenidades")

            # ===== NORMALIZACIÓN Y GUARDADO =====

            # Normalizar score a 0-100
            score = max(0, min(100, score))

            result['match_score'] = score
            result['match_reasons'] = reasons[:5]  # Máximo 5 razones para no saturar
            result['match_details'] = match_details
            result['perfil_aplicado'] = perfil_comprador

        # Ordenar por score descendente
        results.sort(key=lambda x: x.get('match_score', 0), reverse=True)

        return results

    def _fallback_search(self, criteria: Dict[str, Any], db: DatabaseManager) -> List[Dict]:
        """
        Búsqueda relajada si la búsqueda principal no retorna resultados
        MEJORADO v2.0: MANTIENE filtros de precio (solo relaja ±20%)

        Relaja:
        - Ubicación: Expande a toda la ciudad
        - Habitaciones: -1 del mínimo
        - Amenidades: Ignora

        NUNCA relaja:
        - Precio: Mantiene dentro del segmento (máx ±20%)
        - Tipo de propiedad: Mantiene exacto
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

        # ===== FILTROS DUROS (SE MANTIENEN) =====

        # PRECIO: Relajar pero MANTENER en segmento (máx ±20%)
        if criteria.get('precio_max'):
            precio_max = criteria['precio_max']
            # Precio mínimo: 30% abajo del presupuesto (más relajado que búsqueda principal)
            precio_min_relajado = int(precio_max * 0.70)
            # Precio máximo: 20% arriba del presupuesto
            precio_max_relajado = int(precio_max * 1.20)

            conditions.append("precio >= %(precio_min_relajado)s")
            params['precio_min_relajado'] = precio_min_relajado

            conditions.append("precio <= %(precio_max_relajado)s")
            params['precio_max_relajado'] = precio_max_relajado

        # TIPO DE PROPIEDAD: Mantener exacto
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

        # ===== FILTROS RELAJADOS =====

        # UBICACIÓN: Expandir a ciudad completa usando el mapeo de search_config
        if criteria.get('ubicaciones'):
            ciudades_buscar = set()
            zonas_originales = []

            for ubicacion in criteria['ubicaciones']:
                ubicacion_lower = ubicacion.lower()
                zonas_originales.append(ubicacion)

                # Usar el mapeo centralizado de search_config
                ciudad = ZONA_A_CIUDAD.get(ubicacion_lower)
                if ciudad:
                    ciudades_buscar.add(ciudad)

            # Buscar por ciudad O zona original
            if ciudades_buscar or zonas_originales:
                location_conditions = []

                for i, ciudad in enumerate(ciudades_buscar):
                    location_conditions.append(f"ciudad ILIKE %(ciudad_{i})s")
                    params[f'ciudad_{i}'] = f'%{ciudad}%'

                for i, zona in enumerate(zonas_originales):
                    location_conditions.append(
                        f"(zona ILIKE %(zona_orig_{i})s OR titulo ILIKE %(zona_orig_{i})s)"
                    )
                    params[f'zona_orig_{i}'] = f'%{zona}%'

                conditions.append(f"({' OR '.join(location_conditions)})")

        # HABITACIONES: Relajar -1 del mínimo
        if criteria.get('habitaciones_min') and criteria['habitaciones_min'] > 1:
            conditions.append("habitaciones >= %(habitaciones_min_relajado)s")
            params['habitaciones_min_relajado'] = criteria['habitaciones_min'] - 1

        # Agregar condiciones
        if conditions:
            base_query += " AND " + " AND ".join(conditions)

        base_query += " ORDER BY precio ASC, total_amenidades DESC LIMIT 30"

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

                # Marcar como resultado de búsqueda relajada
                prop['busqueda_relajada'] = True
                results.append(prop)

            return results

        except Exception as e:
            print(f"⚠️  Error en búsqueda fallback: {e}")
            return []

    def _generate_no_results_response(self, criteria: Dict[str, Any]) -> Dict[str, Any]:
        """
        Genera una respuesta informativa cuando no hay resultados
        NUEVO v2.0: En lugar de mostrar propiedades irrelevantes, explicamos por qué
        """
        # Construir mensaje de sugerencias
        sugerencias = []

        if criteria.get('ubicaciones'):
            zonas = criteria['ubicaciones']
            zonas_expandidas = []
            for zona in zonas:
                expandidas = get_zonas_expandidas(zona)
                zonas_expandidas.extend([z for z in expandidas if z not in zonas])
            if zonas_expandidas:
                sugerencias.append(f"Ampliar zona a: {', '.join(zonas_expandidas[:3])}")

        if criteria.get('precio_max'):
            precio_sugerido = int(criteria['precio_max'] * 1.2)
            sugerencias.append(f"Aumentar presupuesto a ${precio_sugerido/1_000_000:.0f}M")

        if criteria.get('habitaciones_min') and criteria['habitaciones_min'] > 2:
            sugerencias.append(f"Considerar {criteria['habitaciones_min'] - 1} habitaciones")

        if criteria.get('amenidades_requeridas') and len(criteria['amenidades_requeridas']) > 2:
            sugerencias.append("Reducir amenidades requeridas")

        return {
            'success': True,
            'results': [],
            'total_found': 0,
            'no_results_reason': 'No encontramos propiedades que cumplan todos los criterios',
            'criterios_aplicados': {
                'ubicaciones': criteria.get('ubicaciones', []),
                'tipo': criteria.get('tipo_propiedad', 'No especificado'),
                'precio_rango': f"${criteria.get('precio_min_implicito', 0)/1_000_000:.0f}M - ${criteria.get('precio_max', 0)/1_000_000:.0f}M" if criteria.get('precio_max') else 'No especificado',
                'habitaciones': f"{criteria.get('habitaciones_min', '?')}-{criteria.get('habitaciones_max', '?')}",
            },
            'sugerencias': sugerencias,
            'mensaje_usuario': self._format_no_results_message(criteria, sugerencias)
        }

    def _format_no_results_message(self, criteria: Dict[str, Any], sugerencias: List[str]) -> str:
        """
        Formatea el mensaje de no resultados para WhatsApp
        NUEVO v2.0: Mensaje informativo en lugar de mostrar propiedades irrelevantes
        """
        lines = []
        lines.append("No encontramos propiedades con esos criterios exactos")
        lines.append("")

        # Mostrar qué se buscó
        lines.append("Criterios aplicados:")
        if criteria.get('ubicaciones'):
            lines.append(f"  - Zona: {', '.join(criteria['ubicaciones'])}")
        if criteria.get('tipo_propiedad'):
            lines.append(f"  - Tipo: {criteria['tipo_propiedad']}")
        if criteria.get('precio_max'):
            precio_min = criteria.get('precio_min_implicito', 0)
            lines.append(f"  - Precio: ${precio_min/1_000_000:.0f}M - ${criteria['precio_max']/1_000_000:.0f}M")
        if criteria.get('habitaciones_min'):
            hab_max = criteria.get('habitaciones_max', criteria['habitaciones_min'])
            lines.append(f"  - Habitaciones: {criteria['habitaciones_min']}-{hab_max}")

        # Sugerencias
        if sugerencias:
            lines.append("")
            lines.append("Sugerencias para encontrar opciones:")
            for i, sug in enumerate(sugerencias[:3], 1):
                lines.append(f"  {i}. {sug}")

        lines.append("")
        lines.append("Responde con nuevos criterios o escribe 'ampliar' para buscar con criterios más flexibles.")

        return "\n".join(lines)

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

                # FLUJO MEJORADO v2.0: Si no hay resultados, usar fallback CON filtros de precio
                search_type = 'principal'
                if len(results) == 0:
                    print("⚠️  Sin resultados con todos los criterios. Intentando búsqueda relajada...")
                    results = self._fallback_search(criteria, db)
                    search_type = 'relajada'
                    print(f"📊 Búsqueda relajada encontró: {len(results)} propiedades")

                    # v2.0: Si TAMPOCO hay resultados en fallback, NO mostrar propiedades irrelevantes
                    # En su lugar, generar respuesta informativa
                    if len(results) == 0:
                        print("ℹ️  Sin resultados incluso con criterios relajados")
                        total_elapsed = (time.time() - total_start) * 1000
                        search_log.log_results(0, 0, total_elapsed)
                        no_results_response = self._generate_no_results_response(criteria)
                        no_results_response['search_id'] = search_id
                        no_results_response['elapsed_ms'] = total_elapsed
                        no_results_response['criteria'] = criteria
                        no_results_response['search_type'] = 'sin_resultados'
                        return no_results_response

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

        # Paso 5: Formatear respuesta con metadata adicional v2.0
        return {
            'success': True,
            'criteria': criteria,
            'total_found': len(results),
            'results': results,
            'timestamp': datetime.now().isoformat(),
            'search_id': search_id,
            'search_type': search_type,
            'perfil_comprador': criteria.get('perfil_comprador', 'general'),
            'segmento_precio': criteria.get('segmento_precio'),
            'elapsed_ms': total_elapsed
        }

    def format_results_for_agent(self, search_response: Dict) -> str:
        """
        Formatea los resultados de forma amigable para el agente inmobiliario
        MEJORADO v2.0: Mayor explicabilidad y contexto

        Args:
            search_response: Respuesta de la búsqueda

        Returns:
            Texto formateado para WhatsApp/mensaje
        """

        if not search_response.get('success'):
            return f"Error: {search_response.get('error', 'Error desconocido')}"

        results = search_response.get('results', [])
        criteria = search_response.get('criteria', {})

        # Manejar respuesta de sin resultados
        if search_response.get('search_type') == 'sin_resultados':
            return search_response.get('mensaje_usuario', 'No se encontraron propiedades.')

        if not results:
            return "No se encontraron propiedades que coincidan con los criterios."

        # Construir mensaje mejorado v2.0
        lines = []

        # Header con perfil detectado
        perfil = criteria.get('perfil_comprador', 'general')
        perfil_emoji = {
            'familia': '👨‍👩‍👧',
            'senior': '👴',
            'inversionista': '📈',
            'joven_profesional': '💼',
            'general': '🏠'
        }.get(perfil, '🏠')

        lines.append(f"{perfil_emoji} PROPIEDADES ENCONTRADAS")
        lines.append("=" * 40)

        # Resumen de criterios aplicados
        lines.append("")
        lines.append("Criterios aplicados:")
        if criteria.get('ubicaciones'):
            lines.append(f"  Zona: {', '.join(criteria['ubicaciones'])}")
        if criteria.get('tipo_propiedad'):
            lines.append(f"  Tipo: {criteria['tipo_propiedad']}")
        if criteria.get('precio_max'):
            precio_min = criteria.get('precio_min_implicito', 0)
            lines.append(f"  Precio: ${precio_min/1_000_000:.0f}M - ${criteria['precio_max']/1_000_000:.0f}M")
        if criteria.get('habitaciones_min'):
            hab_max = criteria.get('habitaciones_max', '')
            if hab_max:
                lines.append(f"  Habitaciones: {criteria['habitaciones_min']}-{hab_max}")
            else:
                lines.append(f"  Habitaciones: {criteria['habitaciones_min']}+")
        if criteria.get('piso') == 1:
            lines.append("  Piso: Primer piso")

        # Indicador de tipo de búsqueda
        search_type = search_response.get('search_type', 'principal')
        if search_type == 'relajada':
            lines.append("")
            lines.append("(Resultados con criterios ampliados)")

        lines.append("")
        lines.append(f"{len(results)} propiedades encontradas")
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
