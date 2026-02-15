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
    calcular_rango_area,  # v2.2: Tolerancia de área -5%/+20%
    calcular_rango_habitaciones,  # v2.3: Tolerancia de habitaciones con flexibilidad
    detectar_perfil_comprador,
    get_zonas_expandidas,
    get_ciudad_de_zona,
    get_ciudades_de_zonas,
    get_pesos_perfil,
    get_amenidades_preferidas,
    AMENIDADES_SEGURIDAD,
    AMENIDADES_FAMILIA,
    AMENIDADES_LUJO,
    AMENIDADES_ACCESIBILIDAD,
    MIN_SCORE_PARA_MOSTRAR,  # v2.3: Umbral de calidad mínima
    # v2.1: Nuevas funciones de normalización
    ZONA_CANONICA,
    LANDMARKS_A_ZONAS,
    LANDMARKS_COORDENADAS,
    normalizar_zona,
    procesar_ubicacion_relativa,
    inferir_zona_de_direccion,
    # v2.4: Variaciones de zona para SQL
    get_variaciones_zona,
    # v2.8: Normalización de texto
    normalizar_texto_busqueda,
)

# v2.4: Importar funciones de prioridad
from src.core.search_state import (
    get_priority_weight,
    is_hard_filter,
    PRIORITY_WEIGHTS,
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
MODEL = "claude-sonnet-4-20250514"  # Modelo por defecto (Claude Sonnet 4)

# Modelos alternativos en orden de preferencia (solo modelos activos)
FALLBACK_MODELS = [
    "claude-sonnet-4-20250514",     # Claude Sonnet 4 (más reciente)
    "claude-3-5-sonnet-20241022",   # Claude 3.5 Sonnet v2
    "claude-3-5-haiku-20241022",    # Claude 3.5 Haiku (más económico)
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

        # v2.8: Normalizar texto (corregir typos comunes) antes de enviar a Claude
        query = normalizar_texto_busqueda(query)

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

REGLAS DE REFINAMIENTO (MUY IMPORTANTE - SIGUE ESTAS REGLAS EXACTAMENTE):
1. Si el usuario menciona un criterio EXPLÍCITAMENTE en su nuevo mensaje, USA ESE VALOR (sobrescribe el anterior)
2. Si el usuario NO menciona un criterio, DEBES MANTENER EL VALOR ANTERIOR en tu respuesta JSON
3. Expresiones de refinamiento:
   - "más barato", "menos precio", "más baratas" → reduce precio_max en 15-20%
   - "más caro", "mayor presupuesto" → aumenta precio_max en 15-20%
   - "más grande" → aumenta area_min o habitaciones_min
   - "más pequeño" → reduce area_max o habitaciones_max
   - "otra zona", "diferente sector" → REEMPLAZA ubicaciones
   - "también en X" → AGREGA X a ubicaciones existentes
4. Si el mensaje es muy corto (ej: "con piscina", "3 habitaciones", "más baratas"), es un REFINAMIENTO parcial

*** CRÍTICO - PRESERVACIÓN DE CRITERIOS ***
Cuando el mensaje es un REFINAMIENTO (mensaje corto que solo modifica UN aspecto):
- DEBES incluir TODOS los criterios del contexto anterior en tu respuesta JSON
- Ejemplo: Si el contexto tiene ubicaciones=["Laureles"], tipo="Apartamento", precio_max=500000000, habitaciones_min=2,
  y el usuario dice "más baratas":
  TU RESPUESTA DEBE SER: {{"ubicaciones": ["Laureles"], "tipo_propiedad": "Apartamento", "precio_max": 400000000, "habitaciones_min": 2, "habitaciones_max": 2}}
- Ejemplo: Si el usuario dice "3 habitaciones":
  TU RESPUESTA DEBE SER: {{"ubicaciones": ["Laureles"], "tipo_propiedad": "Apartamento", "precio_max": 500000000, "habitaciones_min": 3, "habitaciones_max": 3}}
- NUNCA retornes SOLO el criterio modificado - SIEMPRE incluye TODOS los criterios del contexto anterior

IMPORTANTE: Incluye TODOS los criterios (anteriores + nuevos/modificados) en tu respuesta JSON."""

        system_prompt = f"""Eres un asistente experto en bienes raíces en Medellín, Colombia.
Tu tarea es analizar mensajes de agentes inmobiliarios y extraer los criterios de búsqueda de propiedades.

Debes extraer y estructurar la siguiente información cuando esté disponible:
- ubicaciones: Lista de zonas/barrios mencionados (ej: ["Laureles", "Ciudad del Río"])
- tipo_propiedad: Tipo (Apartamento, Casa, Penthouse, Duplex, Local, Oficina)
- precio_min: Precio mínimo en COP (número). Si no se menciona explícitamente, NO incluir.
- precio_max: Precio máximo en COP (número). Este es el presupuesto del cliente.
- habitaciones_min: Mínimo de habitaciones
- habitaciones_max: Máximo de habitaciones
  REGLAS DE EXTRACCIÓN (MUY IMPORTANTE):
  * "2 habitaciones", "de 2 alcobas", "con 2 cuartos" → habitaciones_min=2, habitaciones_max=2 (NÚMERO EXACTO)
  * "2 o 3 habitaciones" → habitaciones_min=2, habitaciones_max=3 (RANGO)
  * "hasta 2 habitaciones" → habitaciones_max=2 (SIN habitaciones_min - puede ser menos)
  * "máximo 3 alcobas" → habitaciones_max=3 (SIN habitaciones_min - puede ser menos)
  * "mínimo 2 habitaciones", "al menos 2" → habitaciones_min=2 (SIN habitaciones_max - puede ser más)
  * IMPORTANTE: Cuando el usuario dice un número SIN palabras como "hasta", "máximo", "al menos", "mínimo",
    significa que quiere EXACTAMENTE ese número, entonces usa habitaciones_min=X, habitaciones_max=X
- banos_min: Mínimo de baños
- banos_max: Máximo de baños (si dice "máximo 2 baños" entonces banos_max=2)
- tipo_propiedad: Tipo de propiedad. IMPORTANTE: Cuando el usuario menciona múltiples tipos con "o", extraer como LISTA:
  * "Apartamento en Laureles" → "Apartamento"
  * "Duplex o apartaestudio" → ["Duplex", "Apartaestudio"]
  * "Casa o apartamento" → ["Casa", "Apartamento"]
- area_min: Área mínima en m²
- area_max: Área máxima en m²
- piso: Número de piso específico (1 para primer piso)
- antiguedad_max: Años máximos de antigüedad (ej: "no mayor a 20 años" → 20, "máximo 15 años" → 15)
- administracion_max: Valor máximo de administración en COP (ej: "admon no mayor a 550000" → 550000)
- parqueaderos_min: Mínimo de parqueaderos/garajes requeridos
- cuarto_util: true si se requiere cuarto útil/depósito
- amenidades_requeridas: Lista de amenidades importantes (ej: ["portería", "piscina", "balcón", "vigilancia 24h", "unidad cerrada"])
- caracteristicas_especiales: Características mencionadas (ej: "baño en cada habitación", "buen estado", "remodelado")
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

DESAMBIGUACIÓN PRECIO vs ÁREA (MUY IMPORTANTE):
- "X millones" SIEMPRE es precio, NUNCA área. Ejemplo: "360 millones" → precio_max = 360,000,000
- "X m2", "X m²", "X metros cuadrados" SIEMPRE es área. Ejemplo: "80 m2" → area_min = 80
- Un número solo seguido de "millones" o "mill" es precio
- Un número solo sin unidad en contexto de precio ("hasta 500", "presupuesto 360") es precio en millones

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

ENVIGADO (MUY IMPORTANTE - estos son barrios de Envigado, NO de Medellín):
- La Abadía, El Esmeraldal, Cumbres, Otra Parte (zona baja de Envigado)
- Loma del Escobero, Las Palmas (zona alta de Envigado)
- Zúñiga, La Paz, El Dorado, La Frontera
- Las Antillas, Alcalá, La Cuenca, El Trianón
- Las Orquídeas, Camino Verde, Loma del Chocho
- Jardines, La Sebastiana, San José, Centro Envigado

NOTA IMPORTANTE SOBRE UBICACIONES MÚLTIPLES:
Si el usuario menciona barrios de DIFERENTES ciudades en la misma búsqueda, incluir TODOS:
- "Castropol hasta Abadía y Esmeraldal" → ["Castropol", "La Abadía", "El Esmeraldal"]
  (Castropol es El Poblado/Medellín, La Abadía y El Esmeraldal son Envigado)
- "Poblado o Envigado parte baja" → ["El Poblado", "La Abadía", "El Esmeraldal", "Cumbres"]

UBICACIONES SEPARADAS POR GUIÓN (MUY IMPORTANTE):
Cuando el usuario usa guión (-) para separar ubicaciones, son DOS ubicaciones diferentes:
- "Envigado-El Poblado" → ["Envigado", "El Poblado"] (dos zonas separadas)
- "Medellín-Sabaneta" → ["Medellín", "Sabaneta"] (dos ciudades separadas)
- "Laureles-Estadio" → ["Laureles", "Estadio"] (dos barrios separados)
- "Envigado-Sabaneta" → ["Envigado", "Sabaneta"] (dos ciudades separadas)
NUNCA interpretes el guión como parte del nombre de una zona. SIEMPRE sepáralas en ubicaciones individuales.

SUB-BARRIOS DE EL POBLADO (IMPORTANTE - mantener como ubicación independiente):
Estos son sub-barrios dentro de El Poblado. Cuando el usuario los mencione, úsalos TAL CUAL como ubicación,
NO los conviertas a "El Poblado":
- Patio Bonito, Las Vegas, Las Lomas, La Concha, Provenza
- Los González, El Campestre, Alejandría, La Aguacatala, Villa Carlota
- Santa María de los Ángeles
Ejemplo: "apartamento en Las Vegas" → ubicaciones: ["Las Vegas"] (NO ["El Poblado"])
Ejemplo: "Patio Bonito" → ubicaciones: ["Patio Bonito"]

SUB-BARRIOS DE LAURELES (mantener como ubicación independiente):
- Lorena

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
- "Parqueadero", "garaje" = parking (parqueaderos_min)
- "Cuarto útil", "útil", "depósito" = depósito (cuarto_util: true)
- "Baño en cada habitación" = característica especial
- "Portería", "vigilancia", "vigilancia 24 horas", "24 horas" = amenidades de seguridad
- "Unidad cerrada", "conjunto cerrado" = conjunto residencial con seguridad
- "Unidad completa" = conjunto con todas las amenidades
- "Buen estado", "en buen estado" = característica especial
- "Negociables", "negociable" = flexibilidad_precio: "flexible"
- "Recursos propios" = nota sobre forma de pago
- "Admon", "administración" = administracion_max si menciona valor máximo
- "No mayor a X años", "máximo X años de construido" = antiguedad_max
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

            # Track AI usage
            from src.core.ai_usage_tracker import get_ai_tracker
            get_ai_tracker().track_anthropic_response(
                model=self.model,
                usage_type='search_criteria_extraction',
                function_name='PropertySearchAgent._extract_search_criteria',
                response=message,
                start_time=start_time,
                context={'query': query[:500]}
            )

            # Extraer el JSON de la respuesta
            response_text = message.content[0].text.strip()

            # Limpiar markdown si existe
            if response_text.startswith("```json"):
                response_text = response_text.replace("```json", "").replace("```", "").strip()
            elif response_text.startswith("```"):
                response_text = response_text.replace("```", "").strip()

            criteria = json.loads(response_text)

            # ===== ENRIQUECIMIENTO POST-EXTRACCIÓN v2.3 =====

            # 0.0 v2.3: Asegurar que tipo_propiedad maneje patrones "X o Y"
            if criteria.get('tipo_propiedad'):
                tipo = criteria['tipo_propiedad']
                if isinstance(tipo, str):
                    # Si contiene " o ", dividir en lista
                    if ' o ' in tipo.lower():
                        tipos = [t.strip().title() for t in re.split(r'\s+o\s+', tipo, flags=re.IGNORECASE)]
                        criteria['tipo_propiedad'] = tipos
                    # Si contiene coma, dividir en lista
                    elif ',' in tipo:
                        tipos = [t.strip().title() for t in tipo.split(',')]
                        criteria['tipo_propiedad'] = tipos

            # 0. Detectar flexibilidad de precio PRIMERO (afecta cálculo de rango)
            if not criteria.get('flexibilidad_precio'):
                query_lower = query.lower()
                if 'máximo' in query_lower or 'hasta' in query_lower or 'maximo' in query_lower:
                    criteria['flexibilidad_precio'] = 'estricto'
                else:
                    criteria['flexibilidad_precio'] = 'normal'

            # 0.5 v2.3: Detectar flexibilidad de habitaciones
            # "hasta 2 habitaciones", "máximo 3 alcobas" → estricto (no mostrar más)
            query_lower = query.lower()

            # Detectar si el usuario usó "hasta", "máximo" para habitaciones
            usa_tope_habitaciones = bool(re.search(
                r'(?:hasta|máximo|maximo|no\s+más\s+de|no\s+mas\s+de|como\s+máximo|como\s+maximo)\s+\d+\s*(?:habitacion|alcoba|cuarto|hab)',
                query_lower
            ))

            if not criteria.get('flexibilidad_habitaciones'):
                # Patrones estrictos: "hasta X hab", "maximo X hab", "no más de X"
                if usa_tope_habitaciones:
                    criteria['flexibilidad_habitaciones'] = 'estricto'
                else:
                    criteria['flexibilidad_habitaciones'] = 'normal'

            # v2.5 CRÍTICO: Inferir habitaciones_min cuando el usuario especifica un número exacto
            # Si Claude solo extrajo habitaciones_max pero el usuario NO usó "hasta/máximo",
            # significa que quiere al menos ese número de habitaciones
            if criteria.get('habitaciones_max') and not criteria.get('habitaciones_min'):
                if not usa_tope_habitaciones:
                    # "2 habitaciones" sin "hasta" → quiere al menos 2
                    criteria['habitaciones_min'] = criteria['habitaciones_max']
                    print(f"[DEBUG] v2.5: Inferido habitaciones_min={criteria['habitaciones_min']} porque usuario dijo número exacto sin 'hasta/máximo'")

            # 1. Calcular rango de precio implícito si solo hay precio_max
            if criteria.get('precio_max') and not criteria.get('precio_min'):
                precio_max = criteria['precio_max']
                flexibilidad = criteria.get('flexibilidad_precio', 'normal')
                precio_min, precio_max_ajustado = calcular_rango_precio(precio_max, flexibilidad=flexibilidad)
                criteria['precio_min_implicito'] = precio_min
                criteria['precio_max_ajustado'] = precio_max_ajustado
                criteria['segmento_precio'] = get_segmento_precio(precio_max)
                criteria['tolerancia_aplicada'] = get_tolerancia_precio(precio_max)

            # 1.5 v2.2: Calcular rango de área con tolerancia -5%/+20%
            if criteria.get('area_min') or criteria.get('area_max'):
                area_min_ajustado, area_max_ajustado = calcular_rango_area(
                    criteria.get('area_min'),
                    criteria.get('area_max')
                )
                if area_min_ajustado:
                    criteria['area_min_ajustado'] = area_min_ajustado
                if area_max_ajustado:
                    criteria['area_max_ajustado'] = area_max_ajustado

            # 1.6 v2.3: Calcular rango de habitaciones con tolerancia ±1
            # Permite que propiedades "cercanas" pasen el filtro SQL
            # y sean evaluadas por el scoring
            # EXCEPCIÓN: Si flexibilidad='estricto', respeta el máximo exacto
            if criteria.get('habitaciones_min') or criteria.get('habitaciones_max'):
                hab_min_filtro, hab_max_filtro = calcular_rango_habitaciones(
                    criteria.get('habitaciones_min'),
                    criteria.get('habitaciones_max'),
                    flexibilidad=criteria.get('flexibilidad_habitaciones', 'normal')
                )
                if hab_min_filtro:
                    criteria['habitaciones_min_filtro'] = hab_min_filtro
                if hab_max_filtro:
                    criteria['habitaciones_max_filtro'] = hab_max_filtro

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
                # v2.8: Pre-procesar ubicaciones separadas por guión
                # "Envigado-El Poblado" → ["Envigado", "El Poblado"]
                ubicaciones_expandidas = []
                for ub in criteria['ubicaciones']:
                    if isinstance(ub, str) and '-' in ub:
                        partes = [p.strip() for p in ub.split('-') if p.strip()]
                        if len(partes) >= 2:
                            ubicaciones_expandidas.extend(partes)
                            print(f"[DEBUG] v2.8: Ubicación con guión dividida: '{ub}' → {partes}")
                        else:
                            ubicaciones_expandidas.append(ub)
                    else:
                        ubicaciones_expandidas.append(ub)
                criteria['ubicaciones'] = ubicaciones_expandidas

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
            # Área: expandir a -15%/+35% (más relajado que el -5%/+20% inicial)
            if criteria.get('area_min') or criteria.get('area_max'):
                area_min = criteria.get('area_min', 0)
                area_max = criteria.get('area_max', area_min)
                area_base = (area_min + area_max) / 2 if area_min else area_max
                if area_base > 0:
                    relaxed_min = int(area_base * 0.85)  # -15%
                    relaxed_max = int(area_base * 1.35)  # +35%
                    relaxed['area_min'] = relaxed_min
                    relaxed['area_max'] = relaxed_max
                    # v2.2: También actualizar valores ajustados para que SQL los use
                    relaxed['area_min_ajustado'] = relaxed_min
                    relaxed['area_max_ajustado'] = relaxed_max

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
            # Área: expandir aún más a -25%/+45%
            if criteria.get('area_min') or criteria.get('area_max'):
                area_min = criteria.get('area_min', 0)
                area_max = criteria.get('area_max', area_min)
                area_base = (area_min + area_max) / 2 if area_min else area_max
                if area_base > 0:
                    relaxed_min = int(area_base * 0.75)  # -25%
                    relaxed_max = int(area_base * 1.45)  # +45%
                    relaxed['area_min'] = relaxed_min
                    relaxed['area_max'] = relaxed_max
                    # v2.2: También actualizar valores ajustados
                    relaxed['area_min_ajustado'] = relaxed_min
                    relaxed['area_max_ajustado'] = relaxed_max

            # Habitaciones: ±1 adicional (sobre la tolerancia base)
            if criteria.get('habitaciones_min') and criteria['habitaciones_min'] > 1:
                hab_min_relajado = criteria['habitaciones_min'] - 1
                relaxed['habitaciones_min'] = hab_min_relajado
                # v2.2: También actualizar valores de filtro
                relaxed['habitaciones_min_filtro'] = max(1, hab_min_relajado - 1)
            if criteria.get('habitaciones_max'):
                hab_max_relajado = criteria['habitaciones_max'] + 1
                relaxed['habitaciones_max'] = hab_max_relajado
                relaxed['habitaciones_max_filtro'] = hab_max_relajado + 1

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
        Búsqueda progresiva con relajación escalonada.

        ORDEN DE RELAJACIÓN:
        1. Primero relaja UBICACIÓN (zona exacta → ciudad → zonas expandidas)
        2. Luego relaja otros criterios (área, baños, habitaciones, precio)

        Args:
            criteria: Criterios de búsqueda originales
            db: Conexión a base de datos
            min_results: Mínimo de resultados deseados (default 5)
            max_level: Máximo nivel de relajación de otros criterios (default 4)

        Returns:
            Tuple de (resultados, metadata de progresión)
        """
        search_progression = {
            'nivel_final': 0,
            'ubicacion_level': 0,
            'resultados_por_nivel': {},
            'relajaciones_aplicadas': [],
            'ubicacion_relajada': False,
            'mensaje_ubicacion': None
        }

        results = []
        ubicaciones_originales = criteria.get('ubicaciones', [])

        # Log de diagnóstico: mostrar criterios clave
        print(f"   Criterios clave para SQL:")
        if ubicaciones_originales:
            print(f"     - Ubicaciones: {ubicaciones_originales}")
            ciudades = get_ciudades_de_zonas(ubicaciones_originales)
            if ciudades:
                print(f"     - Ciudades inferidas: {ciudades}")
        if criteria.get('precio_max'):
            print(f"     - Precio max: ${criteria['precio_max']:,}")
            print(f"     - precio_min_implicito: {criteria.get('precio_min_implicito')}")
            print(f"     - precio_max_ajustado: {criteria.get('precio_max_ajustado')}")
        if criteria.get('tipo_propiedad'):
            print(f"     - Tipo: {criteria['tipo_propiedad']}")
        if criteria.get('habitaciones_min') or criteria.get('habitaciones_max'):
            print(f"     - Habitaciones: min={criteria.get('habitaciones_min')}, max={criteria.get('habitaciones_max')}")
            print(f"     - hab_min_filtro: {criteria.get('habitaciones_min_filtro')}, hab_max_filtro: {criteria.get('habitaciones_max_filtro')}")

        # ========== FASE 1: RELAJACIÓN DE UBICACIÓN ==========
        # Intentar primero con diferentes niveles de ubicación ANTES de relajar otros criterios

        ubicacion_levels = [0, 1, 2]  # 0=zona exacta, 1=ciudad, 2=zonas expandidas
        ubicacion_names = ['zona exacta', 'ciudad', 'zonas similares']

        for ub_level in ubicacion_levels:
            # Construir query con ubicación relajada pero otros criterios exactos
            sql_query, params = self._build_sql_query(criteria, ubicacion_level=ub_level)

            # Log de diagnóstico
            if ub_level == 0:
                print(f"   Query SQL (zona exacta): {sql_query[:300]}...")
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

                search_progression['resultados_por_nivel'][f'ub_{ub_level}'] = len(results)
                print(f"   Ubicación nivel {ub_level} ({ubicacion_names[ub_level]}): {len(results)} resultados")

                # v2.9: Log de distribución geográfica de resultados
                if results and ub_level == 0:
                    ciudades_esperadas = set(c for c in get_ciudades_de_zonas(ubicaciones_originales) if c)
                    ciudades_en_resultados = {}
                    for r in results:
                        c = r.get('ciudad', 'Sin ciudad')
                        ciudades_en_resultados[c] = ciudades_en_resultados.get(c, 0) + 1
                    fuera_de_zona = {c: n for c, n in ciudades_en_resultados.items()
                                     if c not in ciudades_esperadas and c != 'Sin ciudad'}
                    search_log.info(f"[GEO] Distribución: {ciudades_en_resultados}")
                    if fuera_de_zona:
                        search_log.warning(f"[GEO] Propiedades fuera de zona detectadas: {fuera_de_zona} (serán penalizadas en ranking)")

                # Si tenemos suficientes resultados, parar
                if len(results) >= min_results:
                    search_progression['nivel_final'] = 0
                    search_progression['ubicacion_level'] = ub_level
                    if ub_level > 0:
                        search_progression['ubicacion_relajada'] = True
                        ciudades = get_ciudades_de_zonas(ubicaciones_originales)
                        if ub_level == 1 and ciudades:
                            search_progression['mensaje_ubicacion'] = f"Ampliando búsqueda a toda {', '.join(ciudades)}"
                        elif ub_level == 2:
                            search_progression['mensaje_ubicacion'] = "Incluyendo zonas similares"
                    return results, search_progression

            except Exception as e:
                print(f"⚠️  Error en ubicación nivel {ub_level}: {e}")
                import traceback
                traceback.print_exc()
                try:
                    db.conn.rollback()
                except:
                    pass
                continue

        # ========== FASE 2: RELAJACIÓN DE OTROS CRITERIOS ==========
        # Si no encontramos suficientes con ubicación relajada, ahora relajamos otros criterios
        # Usamos ubicacion_level=1 (ciudad) como base

        print(f"   Pasando a relajar otros criterios...")

        for level in range(1, max_level + 1):
            # Construir criterios relajados para este nivel
            relaxed_criteria = self._build_relaxed_criteria(criteria, level)

            # Usar ubicacion_level=1 (ciudad) para tener más cobertura
            sql_query, params = self._build_sql_query(relaxed_criteria, ubicacion_level=1)

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

                    for key, value in prop.items():
                        if hasattr(value, 'isoformat'):
                            prop[key] = value.isoformat()
                        elif not isinstance(value, (int, float, str, bool, type(None))):
                            prop[key] = str(value)
                    results.append(prop)

                search_progression['resultados_por_nivel'][f'rel_{level}'] = len(results)

                level_name = ['', 'área/parq', 'baños', 'habitaciones', 'precio'][level]
                print(f"   Nivel {level} ({level_name}): {len(results)} resultados")

                if len(results) >= min_results:
                    search_progression['nivel_final'] = level
                    search_progression['ubicacion_level'] = 1
                    search_progression['ubicacion_relajada'] = True
                    search_progression['relajaciones_aplicadas'] = self._get_relaxation_descriptions(level)
                    ciudades = get_ciudades_de_zonas(ubicaciones_originales)
                    if ciudades:
                        search_progression['mensaje_ubicacion'] = f"Búsqueda en {', '.join(ciudades)}"
                    return results, search_progression

            except Exception as e:
                print(f"⚠️  Error en nivel {level}: {e}")
                import traceback
                traceback.print_exc()
                try:
                    db.conn.rollback()
                except:
                    pass
                continue

        # Si llegamos aquí, devolver lo que tengamos
        search_progression['nivel_final'] = max_level
        search_progression['ubicacion_level'] = 1
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

    def _build_sql_query(self, criteria: Dict[str, Any], ubicacion_level: int = 0) -> tuple:
        """
        Construye una consulta SQL basada en los criterios extraídos.

        Args:
            criteria: Diccionario de criterios de búsqueda
            ubicacion_level: Nivel de búsqueda de ubicación
                0 = Solo zonas exactas
                1 = Solo ciudad (ampliando desde zona)
                2 = Zonas expandidas (zonas similares)

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
        # v2.2: Filtro estricto ±10% del presupuesto
        # Si el usuario dice "$500M", solo mostrar propiedades entre $450M y $550M

        if criteria.get('precio_max'):
            precio_max = criteria['precio_max']

            # v2.6: Recalcular rangos de precio si faltan
            # Esto garantiza que siempre se aplique el filtro de precio correcto
            if not criteria.get('precio_min_implicito') or not criteria.get('precio_max_ajustado'):
                flexibilidad = criteria.get('flexibilidad_precio', 'normal')
                precio_min_calc, precio_max_calc = calcular_rango_precio(precio_max, flexibilidad=flexibilidad)
                criteria['precio_min_implicito'] = precio_min_calc
                criteria['precio_max_ajustado'] = precio_max_calc
                print(f"[DEBUG] v2.6: Recalculado rango precio: ${precio_min_calc/1_000_000:.0f}M - ${precio_max_calc/1_000_000:.0f}M")

            # Usar precio_max_ajustado (incluye tolerancia del +10%)
            precio_max_duro = criteria.get('precio_max_ajustado') or precio_max
            conditions.append("precio <= %(precio_max_duro)s")
            params['precio_max_duro'] = precio_max_duro

            # v2.2: SIEMPRE aplicar precio mínimo (-10% del presupuesto)
            # Usar precio_min explícito si existe, sino usar precio_min_implicito
            precio_min_duro = criteria.get('precio_min') or criteria.get('precio_min_implicito')
            if precio_min_duro:
                conditions.append("precio >= %(precio_min_duro)s")
                params['precio_min_duro'] = precio_min_duro
                print(f"[DEBUG] v2.6: Aplicando filtro precio: ${precio_min_duro/1_000_000:.0f}M - ${precio_max_duro/1_000_000:.0f}M")

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

        # ========== FILTRO DE UBICACIÓN ESCALONADO ==========
        # v2.4: Ahora usa variaciones de zona para encontrar más propiedades

        ubicaciones_originales = criteria.get('ubicaciones', [])

        if ubicaciones_originales:
            if ubicacion_level == 0:
                # NIVEL 0: Zonas con variaciones, RESTRINGIDAS por ciudad
                # v2.9: Previene cross-city matching (ej: "San José" existe en Envigado Y Sabaneta)
                zona_conditions = []
                param_idx = 0

                for ubicacion in ubicaciones_originales:
                    variaciones = get_variaciones_zona(ubicacion)
                    ciudad_de_zona = get_ciudad_de_zona(ubicacion)

                    # Match directo por nombre de ubicación (zona o ciudad)
                    direct_conditions = []
                    direct_conditions.append(f"zona ILIKE %(ub_direct_{param_idx})s")
                    direct_conditions.append(f"ciudad ILIKE %(ub_direct_{param_idx})s")
                    params[f'ub_direct_{param_idx}'] = f'%{ubicacion}%'
                    param_idx += 1

                    # Sub-zona variaciones CON restricción de ciudad
                    if ciudad_de_zona and len(variaciones) > 1:
                        sub_zone_conditions = []
                        for var in variaciones:
                            # Saltar la ubicación principal (ya cubierta arriba)
                            if var.lower() == ubicacion.lower():
                                continue
                            sub_zone_conditions.append(f"zona ILIKE %(ub_var_{param_idx})s")
                            params[f'ub_var_{param_idx}'] = f'%{var}%'
                            param_idx += 1

                        if sub_zone_conditions:
                            # Variaciones solo matchean si la ciudad es correcta
                            params[f'ub_city_{param_idx}'] = f'%{ciudad_de_zona}%'
                            direct_conditions.append(
                                f"(({' OR '.join(sub_zone_conditions)}) AND ciudad ILIKE %(ub_city_{param_idx})s)"
                            )
                            param_idx += 1

                    zona_conditions.append(f"({' OR '.join(direct_conditions)})")

                if zona_conditions:
                    conditions.append(f"({' OR '.join(zona_conditions)})")
                    search_log.info(f"[GEO] Level 0 filtro: {len(ubicaciones_originales)} ubicaciones, ciudades esperadas: {[get_ciudad_de_zona(u) for u in ubicaciones_originales]}")

            elif ubicacion_level == 1:
                # NIVEL 1: Buscar por ciudad (ampliando desde zonas específicas)
                ciudades = get_ciudades_de_zonas(ubicaciones_originales)
                if ciudades:
                    ciudad_conditions = []
                    for i, ciudad in enumerate(ciudades):
                        ciudad_conditions.append(f"ciudad ILIKE %(ciudad_{i})s")
                        params[f'ciudad_{i}'] = f'%{ciudad}%'
                    conditions.append(f"({' OR '.join(ciudad_conditions)})")
                else:
                    # Si no encontramos ciudades, usar zonas originales
                    zona_conditions = []
                    for i, ubicacion in enumerate(ubicaciones_originales):
                        zona_conditions.append(f"ciudad ILIKE %(ubicacion_{i})s")
                        params[f'ubicacion_{i}'] = f'%{ubicacion}%'
                    conditions.append(f"({' OR '.join(zona_conditions)})")

            elif ubicacion_level >= 2:
                # NIVEL 2+: Zonas expandidas (zonas similares) CON restricción de ciudad
                # v2.9: Restringir zonas expandidas a ciudades esperadas
                zonas_expandidas = criteria.get('zonas_expandidas', ubicaciones_originales)
                ciudades_esperadas = get_ciudades_de_zonas(ubicaciones_originales)
                zona_conditions = []
                param_idx = 0
                for ubicacion in zonas_expandidas:
                    zona_conditions.append(f"zona ILIKE %(ub_exp_{param_idx})s")
                    params[f'ub_exp_{param_idx}'] = f'%{ubicacion}%'
                    param_idx += 1
                # Agregar ciudades originales como match directo
                for ubicacion in ubicaciones_originales:
                    zona_conditions.append(f"ciudad ILIKE %(ub_exp_{param_idx})s")
                    params[f'ub_exp_{param_idx}'] = f'%{ubicacion}%'
                    param_idx += 1
                if ciudades_esperadas:
                    ciudad_constraint = []
                    for i, c in enumerate(ciudades_esperadas):
                        ciudad_constraint.append(f"ciudad ILIKE %(ub_exp_city_{i})s")
                        params[f'ub_exp_city_{i}'] = f'%{c}%'
                    conditions.append(f"(({' OR '.join(zona_conditions)}) AND ({' OR '.join(ciudad_constraint)}))")
                else:
                    conditions.append(f"({' OR '.join(zona_conditions)})")

        # Filtro por habitaciones (v2.2: con tolerancia ±1 para permitir near-matches)
        # Usa valores de filtro tolerantes, el scoring diferenciará exactos vs cercanos
        hab_min_filtro = criteria.get('habitaciones_min_filtro') or criteria.get('habitaciones_min')
        hab_max_filtro = criteria.get('habitaciones_max_filtro') or criteria.get('habitaciones_max')

        if hab_min_filtro:
            conditions.append("habitaciones >= %(hab_min_filtro)s")
            params['hab_min_filtro'] = hab_min_filtro

        if hab_max_filtro:
            conditions.append("habitaciones <= %(hab_max_filtro)s")
            params['hab_max_filtro'] = hab_max_filtro

        # Filtro por baños (MEJORADO v2.0: ahora incluye banos_max)
        if criteria.get('banos_min'):
            conditions.append("banos >= %(banos_min)s")
            params['banos_min'] = criteria['banos_min']

        if criteria.get('banos_max'):
            conditions.append("banos <= %(banos_max)s")
            params['banos_max'] = criteria['banos_max']

        # Filtro por área (v2.2: con tolerancia -5%/+20%)
        # Usar valores ajustados si existen, sino los originales
        area_min_filtro = criteria.get('area_min_ajustado') or criteria.get('area_min')
        area_max_filtro = criteria.get('area_max_ajustado') or criteria.get('area_max')

        if area_min_filtro:
            conditions.append("area_construida >= %(area_min_filtro)s")
            params['area_min_filtro'] = area_min_filtro

        if area_max_filtro:
            conditions.append("area_construida <= %(area_max_filtro)s")
            params['area_max_filtro'] = area_max_filtro

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

        # v2.6: Filtro por antigüedad máxima
        if criteria.get('antiguedad_max'):
            ano_minimo = 2026 - criteria['antiguedad_max']  # Año actual - años máximos
            conditions.append("(ano_construccion >= %(ano_minimo)s OR ano_construccion IS NULL)")
            params['ano_minimo'] = ano_minimo

        # v2.6: Filtro por administración máxima
        if criteria.get('administracion_max'):
            conditions.append("(administracion <= %(admin_max)s OR administracion IS NULL)")
            params['admin_max'] = criteria['administracion_max']

        # NOTA: Las amenidades NO se filtran en SQL - solo afectan el ranking
        # Esto permite mostrar más resultados y rankear los mejores primero

        # Agregar condiciones a la query
        if conditions:
            base_query += " AND " + " AND ".join(conditions)

        # v2.5: Ordenar por precio primero (propiedades dentro del presupuesto primero)
        # Amenidades como desempate secundario
        base_query += " ORDER BY precio ASC, total_amenidades DESC"

        # Limitar resultados (más para ranking posterior)
        base_query += " LIMIT 50"

        return base_query, params

    def _rank_results(self, results: List[Dict], criteria: Dict[str, Any]) -> List[Dict]:
        """
        Rankea los resultados según qué tan bien coinciden con los criterios
        MEJORADO v2.4: Scoring con pesos de prioridad dinámicos

        Args:
            results: Lista de propiedades encontradas
            criteria: Criterios de búsqueda originales

        Returns:
            Lista rankeada con score de coincidencia (0-100 normalizado)
        """
        perfil_comprador = criteria.get('perfil_comprador', 'general')
        pesos_perfil = get_pesos_perfil(perfil_comprador)
        amenidades_preferidas = get_amenidades_preferidas(perfil_comprador)

        # v2.4: Obtener pesos de prioridad (si el usuario seleccionó una)
        # Si no hay prioridad seleccionada, usa pesos balanceados
        peso_zona = get_priority_weight(criteria, 'zona')
        peso_precio = get_priority_weight(criteria, 'precio')
        peso_habitaciones = get_priority_weight(criteria, 'habitaciones')

        # Verificar si hay filtros duros (criterios que no se pueden relajar)
        zona_es_dura = is_hard_filter(criteria, 'zona')
        precio_es_duro = is_hard_filter(criteria, 'precio')
        habitaciones_es_duro = is_hard_filter(criteria, 'habitaciones')

        for result in results:
            score = 0
            reasons = []
            match_details = {
                'precio': 'no_evaluado',
                'ubicacion': 'no_evaluado',
                'habitaciones': 'no_evaluado',
                'amenidades': 'no_evaluado'
            }

            # ===== SCORING CON PESOS DE PRIORIDAD v2.4 =====

            # 1. PRECIO - Peso dinámico según prioridad
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
                    ratio = precio / precio_max
                    if 0.70 <= ratio <= 0.90:
                        score += peso_precio  # Usa peso dinámico
                        match_details['precio'] = 'ideal'
                        reasons.append(f"Precio ideal ({ratio*100:.0f}% del presupuesto)")
                    elif ratio <= 0.70:
                        score += int(peso_precio * 0.67)  # 67% del peso
                        match_details['precio'] = 'bajo'
                        reasons.append("Precio bajo el presupuesto")
                    else:
                        score += int(peso_precio * 0.80)  # 80% del peso
                        match_details['precio'] = 'limite'
                        reasons.append("Precio cerca del límite")
                elif precio > precio_max:
                    # Penalizar propiedades fuera del rango
                    # Si precio es filtro duro, penalización severa
                    penalizacion = -50 if precio_es_duro else -20
                    score += penalizacion
                    match_details['precio'] = 'excede'

            # 2. UBICACIÓN - Coincidencia exacta vs zona expandida (peso dinámico v2.4)
            # v2.9: Validación geográfica por ciudad para evitar cross-city matches
            if criteria.get('ubicaciones'):
                zona = (result.get('zona') or '').lower()
                ciudad = (result.get('ciudad') or '').lower()
                direccion = (result.get('direccion_completa') or '').lower()
                titulo = (result.get('titulo') or '').lower()

                # v2.9: Verificar que la propiedad esté en una ciudad esperada
                ciudades_esperadas = [c.lower() for c in get_ciudades_de_zonas(criteria['ubicaciones']) if c]
                ciudad_correcta = any(ce in ciudad for ce in ciudades_esperadas) if ciudades_esperadas else True

                ubicacion_match = False
                for ubicacion in criteria['ubicaciones']:
                    ub_lower = ubicacion.lower()
                    if ub_lower in zona or ub_lower in titulo:
                        score += peso_zona
                        match_details['ubicacion'] = 'exacta'
                        reasons.append(f"Ubicación exacta: {result.get('zona', ubicacion)}")
                        ubicacion_match = True
                        break

                # Si no hay match exacto, verificar zonas expandidas
                if not ubicacion_match and criteria.get('zonas_expandidas'):
                    for zona_exp in criteria['zonas_expandidas']:
                        if zona_exp.lower() in zona or zona_exp.lower() in titulo:
                            score += int(peso_zona * 0.53)
                            match_details['ubicacion'] = 'cercana'
                            reasons.append(f"Zona cercana: {result.get('zona')}")
                            ubicacion_match = True
                            break

                # v2.9: Penalizar propiedades de ciudad incorrecta (cross-city match)
                if not ciudad_correcta:
                    score -= 50
                    match_details['ubicacion'] = 'ciudad_incorrecta'
                    reasons.append(f"Ciudad incorrecta: {result.get('ciudad')} (esperadas: {', '.join(ciudades_esperadas)})")
                # Si zona es filtro duro y no hubo match, penalizar severamente
                elif not ubicacion_match and zona_es_dura:
                    score -= 40
                    match_details['ubicacion'] = 'no_coincide'

            # 3. HABITACIONES - v2.4: Scoring con peso dinámico según prioridad
            if criteria.get('habitaciones_min') or criteria.get('habitaciones_max'):
                hab = result.get('habitaciones', 0)
                if not isinstance(hab, (int, float)):
                    try:
                        hab = int(hab)
                    except:
                        hab = 0

                # Valores originales del usuario (no los de filtro)
                hab_min_ideal = criteria.get('habitaciones_min', 0)
                hab_max_ideal = criteria.get('habitaciones_max', hab_min_ideal if hab_min_ideal else 99)

                # Calcular el número "óptimo" de habitaciones
                # Si el usuario dijo "3 habitaciones" → óptimo = 3
                # Si dijo "2-3 habitaciones" → óptimo = 2.5 (promedio)
                if hab_min_ideal and hab_max_ideal and hab_max_ideal != 99:
                    hab_optimo = (hab_min_ideal + hab_max_ideal) / 2
                else:
                    hab_optimo = hab_min_ideal if hab_min_ideal else hab_max_ideal

                # Diferencia con el óptimo
                diferencia = abs(hab - hab_optimo)

                if hab_min_ideal <= hab <= hab_max_ideal:
                    # CASO 1: Dentro del rango exacto solicitado
                    if diferencia == 0 or (hab == hab_min_ideal or hab == hab_max_ideal):
                        score += peso_habitaciones  # Match perfecto - peso dinámico
                        match_details['habitaciones'] = 'perfecto'
                        reasons.append(f"✓ {hab} hab (exacto)")
                    else:
                        score += int(peso_habitaciones * 0.78)  # ~78% para dentro del rango
                        match_details['habitaciones'] = 'rango'
                        reasons.append(f"{hab} hab")
                elif diferencia <= 1:
                    # CASO 2: A ±1 del rango
                    # v2.5: Distinguir entre MENOS y MÁS habitaciones
                    if hab < hab_min_ideal:
                        # MENOS habitaciones: SIEMPRE penalizar (duro o no)
                        # Esto NO debería pasar con el filtro SQL corregido, pero por seguridad:
                        score -= 30
                        match_details['habitaciones'] = 'insuficiente'
                        reasons.append(f"⚠ {hab} hab (necesitas {hab_min_ideal})")
                    else:
                        # MÁS habitaciones: bonus reducido (propiedad más grande OK)
                        if habitaciones_es_duro:
                            score += int(peso_habitaciones * 0.5)  # 50% si es duro
                        else:
                            score += int(peso_habitaciones * 0.7)  # 70% si no es duro
                        match_details['habitaciones'] = 'extra'
                        reasons.append(f"{hab} hab (+1 extra)")
                elif hab > hab_max_ideal:
                    # CASO 3: Más habitaciones de las pedidas (+2 o más)
                    if habitaciones_es_duro:
                        score -= 30  # Penalización severa si es filtro duro
                        match_details['habitaciones'] = 'excede_duro'
                    else:
                        score += int(peso_habitaciones * 0.11)  # Pequeño bonus
                        match_details['habitaciones'] = 'excede'
                    reasons.append(f"{hab} hab (+{int(hab - hab_max_ideal)})")
                else:
                    # CASO 4: Menos habitaciones de las pedidas (-2 o más)
                    # Penalización más severa si es filtro duro
                    penalizacion = -40 if habitaciones_es_duro else -15
                    score += penalizacion
                    match_details['habitaciones'] = 'insuficiente'
                    reasons.append(f"⚠ {hab} hab ({int(hab - hab_min_ideal)})")

            # 4. BAÑOS - Ahora incluye max
            if criteria.get('banos_min') or criteria.get('banos_max'):
                banos = result.get('banos')
                if banos is None:
                    banos = 0
                elif not isinstance(banos, (int, float)):
                    try:
                        banos = int(banos)
                    except:
                        banos = 0

                banos_min = criteria.get('banos_min') or 0
                banos_max = criteria.get('banos_max') or 99

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

    def _generate_quality_suggestions(self, criteria: Dict[str, Any], mejores_resultados: List[Dict]) -> List[str]:
        """
        Genera sugerencias cuando los resultados no cumplen el umbral de calidad
        v2.3: Nuevas sugerencias basadas en comparación con resultados encontrados

        Args:
            criteria: Criterios de búsqueda aplicados
            mejores_resultados: Los mejores 3 resultados (aunque con score bajo)

        Returns:
            Lista de sugerencias para el usuario
        """
        sugerencias = []

        if mejores_resultados:
            mejor = mejores_resultados[0]

            # Comparar habitaciones
            if criteria.get('habitaciones_max'):
                hab_resultado = mejor.get('habitaciones', 0)
                if isinstance(hab_resultado, str):
                    try:
                        hab_resultado = int(hab_resultado)
                    except:
                        hab_resultado = 0
                if hab_resultado > criteria['habitaciones_max']:
                    sugerencias.append(f"Ampliar a {hab_resultado} habitaciones (encontramos opciones)")

            # Comparar ubicación
            if criteria.get('ubicaciones'):
                zona_resultado = mejor.get('zona', '')
                if zona_resultado and not any(ub.lower() in zona_resultado.lower() for ub in criteria['ubicaciones']):
                    sugerencias.append(f"Considerar zona {zona_resultado}")

            # Comparar precio
            if criteria.get('precio_max'):
                precio_resultado = mejor.get('precio', 0)
                if isinstance(precio_resultado, str):
                    try:
                        precio_resultado = float(precio_resultado.replace(',', '').replace('$', ''))
                    except:
                        precio_resultado = 0
                if precio_resultado > criteria['precio_max']:
                    diferencia = ((precio_resultado / criteria['precio_max']) - 1) * 100
                    if diferencia <= 20:
                        sugerencias.append(f"Aumentar presupuesto un {diferencia:.0f}% (${precio_resultado/1_000_000:.0f}M)")

        # Sugerencias genéricas
        if criteria.get('ubicaciones') and len(criteria['ubicaciones']) == 1:
            zonas_expandidas = criteria.get('zonas_expandidas', [])
            otras_zonas = [z for z in zonas_expandidas if z not in criteria['ubicaciones']]
            if otras_zonas:
                sugerencias.append(f"Ampliar a zonas similares: {', '.join(otras_zonas[:2])}")

        if criteria.get('precio_max') and len(sugerencias) < 3:
            precio_sugerido = int(criteria['precio_max'] * 1.15)
            if not any('presupuesto' in s.lower() for s in sugerencias):
                sugerencias.append(f"Aumentar presupuesto a ${precio_sugerido/1_000_000:.0f}M")

        if criteria.get('amenidades_requeridas') and len(criteria['amenidades_requeridas']) > 2:
            sugerencias.append("Reducir amenidades requeridas")

        return sugerencias[:3]

    def _format_quality_no_results_message(self, criteria: Dict[str, Any], mejores_resultados: List[Dict], mejor_score: int) -> str:
        """
        Formatea el mensaje cuando hay resultados pero con score muy bajo
        v2.3: Mensaje específico para baja calidad de coincidencia

        Args:
            criteria: Criterios aplicados
            mejores_resultados: Los mejores resultados encontrados
            mejor_score: Score del mejor resultado

        Returns:
            Mensaje formateado para WhatsApp
        """
        lines = []
        lines.append("No encontramos propiedades que coincidan bien con tus criterios")
        lines.append("")

        # Mostrar qué se buscó
        lines.append("Criterios aplicados:")
        if criteria.get('ubicaciones'):
            lines.append(f"  - Zona: {', '.join(criteria['ubicaciones'])}")
        if criteria.get('tipo_propiedad'):
            tipo = criteria['tipo_propiedad']
            if isinstance(tipo, list):
                tipo = ' o '.join(tipo)
            lines.append(f"  - Tipo: {tipo}")
        if criteria.get('precio_max'):
            precio_min = criteria.get('precio_min_implicito', 0)
            lines.append(f"  - Precio: ${precio_min/1_000_000:.0f}M - ${criteria['precio_max']/1_000_000:.0f}M")
        if criteria.get('habitaciones_min') or criteria.get('habitaciones_max'):
            hab_min = criteria.get('habitaciones_min', '')
            hab_max = criteria.get('habitaciones_max', '')
            if hab_min and hab_max:
                lines.append(f"  - Habitaciones: {hab_min}-{hab_max}")
            elif hab_max:
                lines.append(f"  - Habitaciones: hasta {hab_max}")
            else:
                lines.append(f"  - Habitaciones: {hab_min}+")

        # Sugerencias
        sugerencias = self._generate_quality_suggestions(criteria, mejores_resultados)
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

        # v2.5: PRESERVAR campos de configuración del sistema de búsqueda
        # Estos campos vienen de apply_priority_weights() cuando el usuario
        # selecciona una prioridad (incluyendo "Confío en Findy")
        if previous_criteria:
            SYSTEM_CONFIG_FIELDS = [
                'hard_filters',
                'priority_weights',
                'selected_priority',
                'search_state',
                # v2.6: Campos calculados de filtros SQL (CRÍTICOS)
                'precio_min_implicito',
                'precio_max_ajustado',
                'habitaciones_min_filtro',
                'habitaciones_max_filtro',
                'flexibilidad_precio',
                'flexibilidad_habitaciones',
                'segmento_precio',
                'tolerancia_aplicada',
            ]
            for field in SYSTEM_CONFIG_FIELDS:
                # v2.6: Usar 'is not None' para preservar valores como 0
                if field in previous_criteria and previous_criteria[field] is not None:
                    criteria[field] = previous_criteria[field]
                    if field == 'hard_filters':
                        print(f"   📌 Hard filters preservados: {previous_criteria[field]}")
                    elif field == 'precio_min_implicito':
                        print(f"   💰 Rango precio preservado: ${previous_criteria.get('precio_min_implicito', 0)/1_000_000:.0f}M - ${previous_criteria.get('precio_max_ajustado', 0)/1_000_000:.0f}M")

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
                if search_progression.get('ubicacion_relajada'):
                    print(f"   Ubicación relajada: {search_progression.get('mensaje_ubicacion')}")
                if search_progression.get('nivel_final', 0) > 0:
                    print(f"   Nivel de relajación: {search_progression['nivel_final']}")
                    print(f"   Criterios relajados: {', '.join(search_progression.get('relajaciones_aplicadas', []))}")

                # Determinar tipo de búsqueda
                ubicacion_level = search_progression.get('ubicacion_level', 0)
                nivel_final = search_progression.get('nivel_final', 0)
                if ubicacion_level == 0 and nivel_final == 0:
                    search_type = 'exacta'
                elif ubicacion_level > 0 and nivel_final == 0:
                    search_type = 'ubicacion_ampliada'
                else:
                    search_type = 'progresiva'
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

            # v2.3: Filtrar por umbral de calidad mínima
            # Si los mejores resultados tienen score muy bajo, es mejor decir "no encontrado"
            mejor_score = results[0].get('match_score', 0) if results else 0

            if mejor_score < MIN_SCORE_PARA_MOSTRAR:
                print(f"⚠️  Mejor score ({mejor_score}) bajo umbral mínimo ({MIN_SCORE_PARA_MOSTRAR})")
                total_elapsed = (time.time() - total_start) * 1000
                search_log.log_results(len(results), 0, total_elapsed)

                return {
                    'success': True,
                    'results': [],
                    'total_found': 0,
                    'search_type': 'sin_resultados_calidad',
                    'no_results_reason': 'Las propiedades encontradas no coinciden suficientemente con los criterios',
                    'mejor_score_encontrado': mejor_score,
                    'criterios_aplicados': {
                        'ubicaciones': criteria.get('ubicaciones', []),
                        'tipo': criteria.get('tipo_propiedad', 'No especificado'),
                        'precio_rango': f"${criteria.get('precio_min_implicito', 0)/1_000_000:.0f}M - ${criteria.get('precio_max', 0)/1_000_000:.0f}M" if criteria.get('precio_max') else 'No especificado',
                        'habitaciones': f"{criteria.get('habitaciones_min', '?')}-{criteria.get('habitaciones_max', '?')}",
                    },
                    'sugerencias': self._generate_quality_suggestions(criteria, results[:3]),
                    'mensaje_usuario': self._format_quality_no_results_message(criteria, results[:3], mejor_score),
                    'criteria': criteria,
                    'search_id': search_id,
                    'elapsed_ms': total_elapsed
                }

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
        if search_response.get('search_type') in ['sin_resultados', 'sin_resultados_calidad']:
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

        # Indicador de tipo de búsqueda y ubicación
        search_type = search_response.get('search_type', 'principal')
        search_progression = search_response.get('search_progression', {})

        # Mostrar si la ubicación fue ampliada
        if search_progression.get('ubicacion_relajada'):
            mensaje_ub = search_progression.get('mensaje_ubicacion', '')
            if mensaje_ub:
                lines.append("")
                lines.append(f"ℹ️ {mensaje_ub}")

        # Mostrar si otros criterios fueron relajados
        if search_type == 'progresiva' and search_progression.get('relajaciones_aplicadas'):
            relajaciones = search_progression['relajaciones_aplicadas']
            lines.append(f"   (Criterios flexibilizados: {', '.join(relajaciones[:2])})")

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
