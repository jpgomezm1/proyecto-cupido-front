#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extractor de criterios de búsqueda usando Claude AI.

Este módulo se encarga de analizar mensajes en lenguaje natural
y extraer criterios estructurados de búsqueda de propiedades.
"""

import json
import time
from typing import Dict, Any

from src.core.logger import get_search_logger
from src.core.search_config import (
    calcular_rango_precio,
    get_segmento_precio,
    get_tolerancia_precio,
    detectar_perfil_comprador,
    get_zonas_expandidas,
    normalizar_zona,
    procesar_ubicacion_relativa,
)

search_log = get_search_logger()


class CriteriaExtractor:
    """Extrae criterios de búsqueda de mensajes en lenguaje natural usando Claude."""

    def __init__(self, client, model: str):
        """
        Inicializa el extractor.

        Args:
            client: Cliente de Anthropic
            model: Modelo de Claude a usar
        """
        self.client = client
        self.model = model

    def extract(self, query: str, previous_criteria: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Extrae criterios de búsqueda de un mensaje en lenguaje natural.

        Args:
            query: Mensaje del agente inmobiliario
            previous_criteria: Criterios de búsqueda previa para contexto

        Returns:
            Diccionario con criterios estructurados
        """
        # Construir contexto de búsqueda previa si existe
        previous_context = self._build_previous_context(previous_criteria)

        # Construir prompts
        system_prompt = self._build_system_prompt(previous_context)
        user_message = self._build_user_message(query)

        try:
            start_time = time.time()

            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )

            # Extraer y parsear JSON
            response_text = message.content[0].text.strip()
            criteria = self._parse_response(response_text)

            if not criteria:
                return {}

            # Enriquecer criterios
            criteria = self._enrich_criteria(criteria, query)

            elapsed_ms = (time.time() - start_time) * 1000
            search_log.log_criteria_extraction(criteria, elapsed_ms)

            return criteria

        except json.JSONDecodeError as e:
            search_log.log_error(f"Error al parsear JSON: {e}", "criteria_extraction")
            print(f"⚠️  Error al parsear JSON: {e}")
            return {}
        except Exception as e:
            search_log.log_error(str(e), "criteria_extraction")
            print(f"❌ Error al extraer criterios: {e}")
            return {}

    def _build_previous_context(self, previous_criteria: Dict[str, Any] = None) -> str:
        """Construye el contexto de búsqueda previa."""
        if not previous_criteria:
            return ""

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

        if not context_parts:
            return ""

        return f"""

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

    def _build_system_prompt(self, previous_context: str) -> str:
        """Construye el prompt del sistema."""
        return f"""Eres un asistente experto en bienes raíces en Medellín, Colombia.
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
- parqueaderos_min: Mínimo de parqueaderos
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

    def _build_user_message(self, query: str) -> str:
        """Construye el mensaje del usuario."""
        return f"""Analiza este mensaje de un agente inmobiliario y extrae los criterios de búsqueda:

```
{query}
```

Responde SOLO con el JSON de criterios."""

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parsea la respuesta de Claude."""
        # Limpiar markdown si existe
        if response_text.startswith("```json"):
            response_text = response_text.replace("```json", "").replace("```", "").strip()
        elif response_text.startswith("```"):
            response_text = response_text.replace("```", "").strip()

        return json.loads(response_text)

    def _enrich_criteria(self, criteria: Dict[str, Any], query: str) -> Dict[str, Any]:
        """Enriquece los criterios con información adicional."""
        # Detectar flexibilidad de precio
        if not criteria.get('flexibilidad_precio'):
            query_lower = query.lower()
            if 'máximo' in query_lower or 'hasta' in query_lower or 'maximo' in query_lower:
                criteria['flexibilidad_precio'] = 'estricto'
            else:
                criteria['flexibilidad_precio'] = 'normal'

        # Calcular rango de precio implícito
        if criteria.get('precio_max') and not criteria.get('precio_min'):
            precio_max = criteria['precio_max']
            flexibilidad = criteria.get('flexibilidad_precio', 'normal')
            precio_min, precio_max_ajustado = calcular_rango_precio(precio_max, flexibilidad=flexibilidad)
            criteria['precio_min_implicito'] = precio_min
            criteria['precio_max_ajustado'] = precio_max_ajustado
            criteria['segmento_precio'] = get_segmento_precio(precio_max)
            criteria['tolerancia_aplicada'] = get_tolerancia_precio(precio_max)

        # Detectar perfil de comprador
        perfil_claude = criteria.get('perfil_comprador', 'general')
        perfil_detectado = detectar_perfil_comprador(query, criteria)
        if perfil_claude == 'general' and perfil_detectado != 'general':
            criteria['perfil_comprador'] = perfil_detectado
        elif perfil_claude == 'general':
            criteria['perfil_comprador'] = perfil_detectado

        # Normalizar y expandir ubicaciones
        if criteria.get('ubicaciones'):
            criteria = self._process_locations(criteria)

        return criteria

    def _process_locations(self, criteria: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa y normaliza ubicaciones."""
        ubicaciones_normalizadas = []
        ubicaciones_geo = []

        for ubicacion in criteria['ubicaciones']:
            resultado = procesar_ubicacion_relativa(ubicacion)

            if resultado['tipo'] == 'coordenadas':
                ubicaciones_geo.append(resultado)
            elif resultado['tipo'] == 'zonas':
                for z in resultado['valor']:
                    if z not in ubicaciones_normalizadas:
                        ubicaciones_normalizadas.append(z)
            else:
                zona_normalizada = normalizar_zona(ubicacion)
                if zona_normalizada not in ubicaciones_normalizadas:
                    ubicaciones_normalizadas.append(zona_normalizada)

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

        return criteria
