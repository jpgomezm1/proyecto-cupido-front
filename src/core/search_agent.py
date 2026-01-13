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
    # v2.1: Nuevas funciones de normalización
    ZONA_CANONICA,
    LANDMARKS_A_ZONAS,
    LANDMARKS_COORDENADAS,
    normalizar_zona,
    procesar_ubicacion_relativa,
    inferir_zona_de_direccion,
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

    def _extract_search_criteria(self, query: str, previous_criteria: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Usa Claude para extraer criterios de búsqueda de un mensaje en lenguaje natural
        MEJORADO v2.1: Soporta contexto de búsquedas previas para refinamiento iterativo

        Args:
            query: Mensaje del agente inmobiliario (puede ser informal/WhatsApp)
            previous_criteria: Criterios de búsqueda previa para contexto (opcional)

        Returns:
            Diccionario con criterios estructurados
        """

        # Construir contexto de búsqueda previa si existe
        previous_context = ""
        if previous_criteria:
            context_parts = []
            if previous_criteria.get('ubicaciones'):
                context_parts.append(f"- Zonas: {', '.join(previous_criteria['ubicaciones'])}")
            if previous_criteria.get('tipo_propiedad'):
                context_parts.append(f"- Tipo: {previous_criteria['tipo_propiedad']}")
            if previous_criteria.get('precio_max'):
                context_parts.append(f"- Presupuesto máximo: ${previous_criteria['precio_max']:,} COP")
            if previous_criteria.get('precio_min'):
                context_parts.append(f"- Presupuesto mínimo: ${previous_criteria['precio_min']:,} COP")
            if previous_criteria.get('habitaciones_min'):
                habs = f"{previous_criteria['habitaciones_min']}"
                if previous_criteria.get('habitaciones_max') and previous_criteria['habitaciones_max'] != previous_criteria['habitaciones_min']:
                    habs += f"-{previous_criteria['habitaciones_max']}"
                context_parts.append(f"- Habitaciones: {habs}")
            if previous_criteria.get('banos_min'):
                context_parts.append(f"- Baños mínimo: {previous_criteria['banos_min']}")
            if previous_criteria.get('area_min') or previous_criteria.get('area_max'):
                area = ""
                if previous_criteria.get('area_min'):
                    area += f"desde {previous_criteria['area_min']}m²"
                if previous_criteria.get('area_max'):
                    area += f" hasta {previous_criteria['area_max']}m²"
                context_parts.append(f"- Área: {area.strip()}")
            if previous_criteria.get('amenidades_requeridas'):
                context_parts.append(f"- Amenidades: {', '.join(previous_criteria['amenidades_requeridas'])}")
            if previous_criteria.get('perfil_comprador') and previous_criteria['perfil_comprador'] != 'general':
                context_parts.append(f"- Perfil: {previous_criteria['perfil_comprador']}")

            if context_parts:
                previous_context = f"""

CONTEXTO DE BÚSQUEDA ANTERIOR (IMPORTANTE):
El usuario ya realizó una búsqueda con estos criterios:
{chr(10).join(context_parts)}

REGLAS DE REFINAMIENTO:
1. Si el usuario menciona un criterio EXPLÍCITAMENTE en su nuevo mensaje, USA ESE VALOR (sobrescribe el anterior)
2. Si el usuario NO menciona un criterio, MANTÉN EL VALOR ANTERIOR
3. Expresiones de refinamiento:
   - "más barato", "menos precio" → reduce precio_max en 15-20%
   - "más caro", "mayor presupuesto" → aumenta precio_max en 15-20%
   - "más grande" → aumenta area_min o habitaciones_min
   - "más pequeño" → reduce area_max o habitaciones_max
   - "otra zona", "diferente sector" → REEMPLAZA ubicaciones
   - "también en X" → AGREGA X a ubicaciones existentes
4. Si el mensaje es muy corto (ej: "con piscina", "3 habitaciones"), es un REFINAMIENTO - mantén los demás criterios

IMPORTANTE: Incluye TODOS los criterios (anteriores + nuevos/modificados) en tu respuesta JSON."""

        system_prompt = f"""Eres un asistente experto en bienes raíces en Medellín, Colombia.
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

UBICACIONES CANÓNICAS EN ÁREA METROPOLITANA DE MEDELLÍN:
IMPORTANTE: Siempre usa estos nombres exactos (canónicos) para las ubicaciones:

MEDELLÍN:
- El Poblado (NO usar: "Poblado", "Santa María Poblado", "Altos del Poblado")
- Laureles (NO usar: "Comuna 11 Laureles")
- Belén (NO usar: "Belen" sin tilde)
- Estadio, Conquistadores, Floresta, Calasanz, Robledo
- Ciudad del Río (NO usar: "Ciudad del Rio" sin tilde)
- Castropol, Lalinde, Manila, San Lucas, Los Balsos
- Loma de los Bernal (NO usar: "Belén Loma de los Bernal")
- Guayabal, Suramericana (NO usar: "Suramerica")

ENVIGADO:
- Loma del Escobero (NO usar: "El Escobero", "Escobero")
- Zúñiga, La Paz, El Dorado, El Esmeraldal
- Las Antillas, Alcalá, La Cuenca, El Trianón
- Las Orquídeas, Camino Verde, Cumbres
- Las Palmas (incluye Alto de las Palmas, Variante)

SABANETA: Aves María, Mayorca, La Doctora, Calle Larga, San José, Asdesillas
ITAGÜÍ: Ditaires, Santa María, Pilsen
BELLO: Niquía, Cabañas, París
RIONEGRO: Llanogrande, San Antonio de Pereira, Pontezuela
LA ESTRELLA, EL RETIRO, LA CEJA

UBICACIONES RELATIVAS - IMPORTANTE:
Si el usuario menciona "cerca a [lugar]", conviértelo a las zonas correspondientes:
- "cerca a la Universidad de Medellín" → ["Laureles", "Estadio", "Belén"]
- "cerca al segundo parque de Laureles" → ["Laureles"]
- "cerca a Santafé/Oviedo/El Tesoro" → ["El Poblado"]
- "cerca a EAFIT" → ["El Poblado", "Manila"]
- "cerca a Mayorca" → ["Sabaneta"]
- "cerca al metro [estación]" → zonas cercanas a esa estación

Si no puedes determinar la zona exacta de una ubicación relativa, usa la ciudad como fallback.

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
{previous_context}
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

            # ===== ENRIQUECIMIENTO POST-EXTRACCIÓN v2.1 =====

            # 0. Detectar flexibilidad de precio PRIMERO (afecta cálculo de rango)
            if not criteria.get('flexibilidad_precio'):
                query_lower = query.lower()
                if 'máximo' in query_lower or 'hasta' in query_lower or 'maximo' in query_lower:
                    criteria['flexibilidad_precio'] = 'estricto'
                else:
                    criteria['flexibilidad_precio'] = 'normal'

            # 1. Calcular rango de precio implícito si solo hay precio_max
            if criteria.get('precio_max') and not criteria.get('precio_min'):
                precio_max = criteria['precio_max']
                flexibilidad = criteria.get('flexibilidad_precio', 'normal')
                precio_min, precio_max_ajustado = calcular_rango_precio(precio_max, flexibilidad=flexibilidad)
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

            # 3. Normalizar y expandir ubicaciones v2.1
            if criteria.get('ubicaciones'):
                ubicaciones_normalizadas = []
                ubicaciones_geo = []  # Para búsquedas geoespaciales

                for ubicacion in criteria['ubicaciones']:
                    # Procesar ubicaciones relativas ("cerca a X")
                    resultado = procesar_ubicacion_relativa(ubicacion)

                    if resultado['tipo'] == 'coordenadas':
                        # Guardar para búsqueda geoespacial
                        ubicaciones_geo.append(resultado)
                    elif resultado['tipo'] == 'zonas':
                        # Agregar zonas del landmark
                        for z in resultado['valor']:
                            if z not in ubicaciones_normalizadas:
                                ubicaciones_normalizadas.append(z)
                    else:
                        # Normalizar zona normal
                        zona_normalizada = normalizar_zona(ubicacion)
                        if zona_normalizada not in ubicaciones_normalizadas:
                            ubicaciones_normalizadas.append(zona_normalizada)

                # Guardar ubicaciones normalizadas
                criteria['ubicaciones'] = ubicaciones_normalizadas
                if ubicaciones_geo:
                    criteria['ubicaciones_geo'] = ubicaciones_geo

                # Expandir zonas similares
                zonas_expandidas = []
                for zona in ubicaciones_normalizadas:
                    expandidas = get_zonas_expandidas(zona)
                    for z in expandidas:
                        if z not in zonas_expandidas:
                            zonas_expandidas.append(z)
                criteria['zonas_expandidas'] = zonas_expandidas

            # (flexibilidad_precio ya se detectó en paso 0)

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

    def _build_relaxed_criteria(self, criteria: Dict[str, Any], level: int) -> Dict[str, Any]:
        """
        Construye criterios relajados según el nivel de búsqueda.
        Protege PRECIO y UBICACIÓN como los más importantes.

        Niveles:
        0 = Exacta (usa criterios originales)
        1 = Relaja área (±35%) y parqueaderos (-1)
        2 = + Relaja baños (±1)
        3 = + Relaja habitaciones (±1), ignora parqueaderos
        4 = + Relaja precio ligeramente (+10% máximo)
        """
        relaxed = criteria.copy()

        if level >= 1:
            # Área: expandir de ±20% a ±35%
            if criteria.get('area_min') or criteria.get('area_max'):
                area_min = criteria.get('area_min', 0)
                area_max = criteria.get('area_max', area_min)
                area_base = (area_min + area_max) / 2 if area_min else area_max
                if area_base > 0:
                    relaxed['area_min'] = int(area_base * 0.65)
                    relaxed['area_max'] = int(area_base * 1.35)

            # Parqueaderos: -1 del mínimo
            if criteria.get('parqueaderos_min') and criteria['parqueaderos_min'] > 1:
                relaxed['parqueaderos_min'] = criteria['parqueaderos_min'] - 1

        if level >= 2:
            # Baños: ±1
            if criteria.get('banos_min') and criteria['banos_min'] > 1:
                relaxed['banos_min'] = criteria['banos_min'] - 1
            if criteria.get('banos_max'):
                relaxed['banos_max'] = criteria['banos_max'] + 1

        if level >= 3:
            # Área: expandir aún más a ±40%
            if criteria.get('area_min') or criteria.get('area_max'):
                area_min = criteria.get('area_min', 0)
                area_max = criteria.get('area_max', area_min)
                area_base = (area_min + area_max) / 2 if area_min else area_max
                if area_base > 0:
                    relaxed['area_min'] = int(area_base * 0.60)
                    relaxed['area_max'] = int(area_base * 1.40)

            # Habitaciones: ±1
            if criteria.get('habitaciones_min') and criteria['habitaciones_min'] > 1:
                relaxed['habitaciones_min'] = criteria['habitaciones_min'] - 1
            if criteria.get('habitaciones_max'):
                relaxed['habitaciones_max'] = criteria['habitaciones_max'] + 1

            # Parqueaderos: ignorar completamente
            relaxed.pop('parqueaderos_min', None)

        if level >= 4:
            # Precio: +10% sobre el máximo ajustado (ÚLTIMO RECURSO)
            if criteria.get('precio_max_ajustado'):
                relaxed['precio_max_ajustado'] = int(criteria['precio_max_ajustado'] * 1.10)
            elif criteria.get('precio_max'):
                # Si no hay ajustado, aplicar 10% extra sobre el max
                relaxed['precio_max_ajustado'] = int(criteria['precio_max'] * 1.25)

        return relaxed

    def _progressive_search(
        self,
        criteria: Dict[str, Any],
        db: DatabaseManager,
        min_results: int = 5,
        max_level: int = 4
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Búsqueda progresiva que relaja criterios hasta obtener min_results.
        Protege PRECIO y UBICACIÓN como los factores más importantes.

        Args:
            criteria: Criterios de búsqueda originales
            db: Conexión a base de datos
            min_results: Mínimo de resultados deseados (default 5)
            max_level: Máximo nivel de relajación (default 4)

        Returns:
            Tuple de (resultados, metadata de progresión)
        """
        search_progression = {
            'nivel_final': 0,
            'resultados_por_nivel': {},
            'relajaciones_aplicadas': []
        }

        results = []

        # Log de diagnóstico: mostrar criterios clave
        print(f"   Criterios clave para SQL:")
        if criteria.get('ubicaciones'):
            print(f"     - Ubicaciones: {criteria['ubicaciones']}")
        if criteria.get('precio_max'):
            print(f"     - Precio max: ${criteria['precio_max']:,}")
        if criteria.get('tipo_propiedad'):
            print(f"     - Tipo: {criteria['tipo_propiedad']}")

        for level in range(max_level + 1):
            # Construir criterios relajados para este nivel
            relaxed_criteria = self._build_relaxed_criteria(criteria, level)

            # Construir y ejecutar query
            sql_query, params = self._build_sql_query(relaxed_criteria)

            # Log de diagnóstico en nivel 0
            if level == 0:
                print(f"   Query SQL (nivel 0): {sql_query[:300]}...")
                print(f"   Params: {params}")

            try:
                db.cursor.execute(sql_query, params)
                columns = [desc[0] for desc in db.cursor.description]
                rows = db.cursor.fetchall()

                results = []
                for row in rows:
                    if isinstance(row, dict):
                        prop = dict(row)
                    else:
                        prop = dict(zip(columns, row))

                    # Convertir tipos para JSON
                    for key, value in prop.items():
                        if hasattr(value, 'isoformat'):
                            prop[key] = value.isoformat()
                        elif not isinstance(value, (int, float, str, bool, type(None))):
                            prop[key] = str(value)
                    results.append(prop)

                search_progression['resultados_por_nivel'][level] = len(results)

                level_name = ['exacta', 'área/parq', 'baños', 'habitaciones', 'precio'][level]
                print(f"   Nivel {level} ({level_name}): {len(results)} resultados")

                # Si tenemos suficientes resultados, parar
                if len(results) >= min_results:
                    search_progression['nivel_final'] = level
                    search_progression['relajaciones_aplicadas'] = self._get_relaxation_descriptions(level)
                    return results, search_progression

            except Exception as e:
                print(f"⚠️  Error en nivel {level}: {e}")
                print(f"   Query: {sql_query[:200]}...")
                print(f"   Params: {list(params.keys())}")
                import traceback
                traceback.print_exc()
                # Rollback para limpiar la transacción fallida
                try:
                    db.conn.rollback()
                except:
                    pass
                continue

        # Si llegamos aquí, devolver lo que tengamos del último nivel
        search_progression['nivel_final'] = max_level
        search_progression['relajaciones_aplicadas'] = self._get_relaxation_descriptions(max_level)
        return results, search_progression

    def _get_relaxation_descriptions(self, level: int) -> List[str]:
        """Retorna descripciones de qué criterios se relajaron"""
        descriptions = []
        if level >= 1:
            descriptions.append("área ±35%")
            descriptions.append("parqueaderos -1")
        if level >= 2:
            descriptions.append("baños ±1")
        if level >= 3:
            descriptions.append("área ±40%")
            descriptions.append("habitaciones ±1")
            descriptions.append("parqueaderos ignorados")
        if level >= 4:
            descriptions.append("precio +10%")
        return descriptions

    def _build_sql_query(self, criteria: Dict[str, Any]) -> tuple:
        """
        Construye una consulta SQL basada en los criterios extraídos.

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

        # ========== FILTROS DE PRECIO ==========

        # Filtro de precio máximo (siempre se aplica)
        if criteria.get('precio_max'):
            # Usar precio_max_ajustado si existe (incluye tolerancia del 15%)
            precio_max_duro = criteria.get('precio_max_ajustado') or criteria['precio_max']
            conditions.append("precio <= %(precio_max_duro)s")
            params['precio_max_duro'] = precio_max_duro

            # Precio mínimo SOLO si el usuario lo especificó explícitamente
            # NO usar precio_min_implicito como filtro duro (es muy restrictivo)
            if criteria.get('precio_min'):
                conditions.append("precio >= %(precio_min_duro)s")
                params['precio_min_duro'] = criteria['precio_min']

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
        # Usa solo ILIKE para compatibilidad (sin funciones avanzadas)
        ubicaciones_buscar = criteria.get('zonas_expandidas') or criteria.get('ubicaciones')
        if ubicaciones_buscar:
            zona_conditions = []
            for i, ubicacion in enumerate(ubicaciones_buscar):
                # Búsqueda con ILIKE (compatible con todas las instalaciones PostgreSQL)
                zona_conditions.append(f"""(
                    zona ILIKE %(ubicacion_{i})s OR
                    ciudad ILIKE %(ubicacion_{i})s OR
                    direccion_completa ILIKE %(ubicacion_{i})s OR
                    titulo ILIKE %(ubicacion_{i})s
                )""")
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

        # Filtro por parqueaderos (NUEVO v2.1)
        if criteria.get('parqueaderos_min'):
            conditions.append("parqueaderos >= %(parqueaderos_min)s")
            params['parqueaderos_min'] = criteria['parqueaderos_min']

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

    # NOTA v2.1: _fallback_search() fue reemplazado por _progressive_search()
    # que implementa relajación progresiva por niveles protegiendo precio y ubicación

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

    def search(self, query: str, limit: int = 10, sender: str = None,
               previous_criteria: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Búsqueda principal: procesa consulta en lenguaje natural y retorna propiedades
        MEJORADO v2.1: Soporta contexto de búsquedas previas para refinamiento iterativo

        Args:
            query: Mensaje del agente inmobiliario
            limit: Número máximo de resultados a retornar
            sender: Teléfono del remitente (para logging)
            previous_criteria: Criterios de búsqueda previa para contexto (opcional)

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
        if previous_criteria:
            print()
            print("📋 Contexto previo detectado:")
            if previous_criteria.get('ubicaciones'):
                print(f"   - Zonas: {', '.join(previous_criteria['ubicaciones'])}")
            if previous_criteria.get('tipo_propiedad'):
                print(f"   - Tipo: {previous_criteria['tipo_propiedad']}")
            if previous_criteria.get('precio_max'):
                print(f"   - Presupuesto: ${previous_criteria['precio_max']:,}")
        print()

        # Paso 1: Extraer criterios con Claude (con contexto previo si existe)
        print("🧠 Analizando criterios con Claude...")
        criteria = self._extract_search_criteria(query, previous_criteria)

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

        # Paso 3: Búsqueda PROGRESIVA v2.1 (relaja criterios hasta obtener mínimo 5 resultados)
        # Protege PRECIO y UBICACIÓN como los factores más importantes
        print("🔍 Buscando en base de datos (búsqueda progresiva)...")
        search_progression = {}
        try:
            sql_start = time.time()
            with DatabaseManager() as db:
                results, search_progression = self._progressive_search(
                    criteria,
                    db,
                    min_results=5,
                    max_level=4
                )

                sql_elapsed = (time.time() - sql_start) * 1000
                search_log.log_sql_query("progressive_search", {}, sql_elapsed)

                print(f"📊 Propiedades encontradas: {len(results)}")
                if search_progression.get('nivel_final', 0) > 0:
                    print(f"   Nivel de relajación: {search_progression['nivel_final']}")
                    print(f"   Criterios relajados: {', '.join(search_progression.get('relajaciones_aplicadas', []))}")

                # Si no hay resultados después de todos los niveles
                search_type = 'exacta' if search_progression.get('nivel_final', 0) == 0 else 'progresiva'
                if len(results) == 0:
                    print("ℹ️  Sin resultados incluso con criterios relajados")
                    total_elapsed = (time.time() - total_start) * 1000
                    search_log.log_results(0, 0, total_elapsed)
                    no_results_response = self._generate_no_results_response(criteria)
                    no_results_response['search_id'] = search_id
                    no_results_response['elapsed_ms'] = total_elapsed
                    no_results_response['criteria'] = criteria
                    no_results_response['search_type'] = 'sin_resultados'
                    no_results_response['search_progression'] = search_progression
                    return no_results_response

        except Exception as e:
            search_log.log_error(str(e), 'progressive_search')
            print(f"❌ Error en búsqueda progresiva: {e}")
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

        # Paso 5: Formatear respuesta con metadata adicional v2.1
        return {
            'success': True,
            'criteria': criteria,
            'total_found': len(results),
            'results': results,
            'timestamp': datetime.now().isoformat(),
            'search_id': search_id,
            'search_type': search_type,
            'search_progression': search_progression,  # v2.1: Info de relajación progresiva
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
