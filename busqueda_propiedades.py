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
from datetime import datetime
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("⚠️  Módulo 'anthropic' no instalado. Ejecuta: pip install anthropic")

from database import DatabaseManager

# Cargar variables de entorno
load_dotenv()

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
                print(f"✅ Usando modelo: {model}")
                return model
            except anthropic.NotFoundError:
                continue
            except Exception as e:
                # Otros errores (rate limit, etc.) - el modelo existe
                print(f"⚠️  Modelo {model} existe pero error: {e}")
                return model

        # Si ninguno funciona, usar el primero como fallback
        print(f"⚠️  No se pudo detectar modelo, usando: {FALLBACK_MODELS[0]}")
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

            return criteria

        except json.JSONDecodeError as e:
            print(f"⚠️  Error al parsear JSON: {e}")
            print(f"Respuesta: {response_text}")
            return {}
        except Exception as e:
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
            id, codigo_propiedad, fuente, url, titulo, precio, precio_texto,
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

        # Filtro por ubicaciones (zonas, dirección o título)
        if criteria.get('ubicaciones'):
            ubicaciones = criteria['ubicaciones']
            zona_conditions = []
            for i, ubicacion in enumerate(ubicaciones):
                # Buscar en zona, dirección Y título (para propiedades captadas de Wasi)
                zona_conditions.append(
                    f"(zona ILIKE %(ubicacion_{i})s OR "
                    f"direccion_completa ILIKE %(ubicacion_{i})s OR "
                    f"titulo ILIKE %(ubicacion_{i})s)"
                )
                params[f'ubicacion_{i}'] = f'%{ubicacion}%'
            conditions.append(f"({' OR '.join(zona_conditions)})")

        # Filtro por tipo de propiedad
        if criteria.get('tipo_propiedad'):
            conditions.append("tipo_propiedad ILIKE %(tipo_propiedad)s")
            params['tipo_propiedad'] = f"%{criteria['tipo_propiedad']}%"

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

        Args:
            results: Lista de propiedades encontradas
            criteria: Criterios de búsqueda originales

        Returns:
            Lista rankeada con score de coincidencia
        """

        for result in results:
            score = 0
            reasons = []

            # Coincidencia de ubicación
            if criteria.get('ubicaciones'):
                zona = result.get('zona') or ''
                direccion = result.get('direccion_completa') or ''
                for ubicacion in criteria['ubicaciones']:
                    if ubicacion.lower() in zona.lower() or \
                       ubicacion.lower() in direccion.lower():
                        score += 10
                        reasons.append(f"Ubicación: {ubicacion}")
                        break

            # Coincidencia de tipo
            if criteria.get('tipo_propiedad'):
                tipo_prop = result.get('tipo_propiedad') or ''
                if criteria['tipo_propiedad'].lower() in tipo_prop.lower():
                    score += 5
                    reasons.append(f"Tipo: {result.get('tipo_propiedad')}")

            # Coincidencia de precio (mejor si está en el rango ideal)
            precio = result.get('precio', 0)
            # Convertir a número si es string
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

            # Coincidencia de habitaciones exacta
            if criteria.get('habitaciones_min') or criteria.get('habitaciones_max'):
                hab = result.get('habitaciones', 0)
                # Asegurar que sea número
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

            # Coincidencia de amenidades
            amenidades_int = result.get('amenidades_internas') or ''
            amenidades_ext = result.get('amenidades_externas') or ''
            amenidades_prop = (amenidades_int + ' ' + amenidades_ext).lower()

            if criteria.get('amenidades_requeridas'):
                for amenidad in criteria['amenidades_requeridas']:
                    if amenidad.lower() in amenidades_prop:
                        score += 6
                        reasons.append(f"Tiene: {amenidad}")

            # Piso preferido
            if criteria.get('piso'):
                if result.get('piso') == criteria['piso']:
                    score += 8
                    reasons.append(f"Piso {criteria['piso']}")

            # Más amenidades = mejor
            total_amenidades = result.get('total_amenidades', 0)
            # Asegurar que sea número
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
        Usa solo los criterios más importantes (ubicación, tipo, precio)
        """

        # Construir query relajada - solo criterios esenciales
        base_query = """
        SELECT
            id, codigo_propiedad, fuente, url, titulo, precio, precio_texto,
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

        # Solo tipo de propiedad (si existe)
        if criteria.get('tipo_propiedad'):
            conditions.append("tipo_propiedad ILIKE %(tipo_propiedad)s")
            params['tipo_propiedad'] = f"%{criteria['tipo_propiedad']}%"

        # Solo precio máximo (si existe) - relajado al 150%
        if criteria.get('precio_max'):
            conditions.append("precio <= %(precio_max_relajado)s")
            params['precio_max_relajado'] = criteria['precio_max'] * 1.5

        # Solo habitaciones mínimas (si existe) - acepta 1 menos
        if criteria.get('habitaciones_min') and criteria['habitaciones_min'] > 1:
            conditions.append("habitaciones >= %(habitaciones_min_relajado)s")
            params['habitaciones_min_relajado'] = criteria['habitaciones_min'] - 1

        # Si no hay condiciones, buscar todo del tipo
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

    def search(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """
        Búsqueda principal: procesa consulta en lenguaje natural y retorna propiedades

        Args:
            query: Mensaje del agente inmobiliario
            limit: Número máximo de resultados a retornar

        Returns:
            Diccionario con criterios, resultados y metadatos
        """

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
            return {
                'success': False,
                'error': 'No se pudieron extraer criterios de búsqueda',
                'criteria': {},
                'results': []
            }

        print("✅ Criterios extraídos:")
        print(json.dumps(criteria, indent=2, ensure_ascii=False))
        print()

        # Paso 2: Construir consulta SQL
        print("🔍 Buscando en base de datos...")
        sql_query, params = self._build_sql_query(criteria)

        # Paso 3: Ejecutar búsqueda en DB
        try:
            with DatabaseManager() as db:
                db.cursor.execute(sql_query, params)
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

        except Exception as e:
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
            results = self._rank_results(results, criteria)
            results = results[:limit]

        # Paso 5: Formatear respuesta
        return {
            'success': True,
            'criteria': criteria,
            'total_found': len(results),
            'results': results,
            'timestamp': datetime.now().isoformat()
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
