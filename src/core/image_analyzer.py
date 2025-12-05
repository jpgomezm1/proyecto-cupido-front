#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Análisis de Imágenes - Proyecto Cupido
Usa Claude Vision para analizar imágenes de propiedades
"""

import os
import json
import base64
import httpx
from typing import List, Dict, Any, Optional
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()


class ImageAnalyzer:
    """
    Analiza imágenes de propiedades usando Claude Vision
    Extrae características visuales, estilo, ambiente y puntos destacados
    """

    def __init__(self):
        self.client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        self.model = "claude-sonnet-4-20250514"  # Modelo con visión
        self.max_tokens = 1500

    def analyze_image(self, image_url: str, property_context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Analiza una imagen de propiedad

        Args:
            image_url: URL de la imagen
            property_context: Contexto opcional de la propiedad (tipo, ubicación, etc.)

        Returns:
            Diccionario con análisis de la imagen
        """
        try:
            # Descargar imagen y convertir a base64
            image_data = self._download_image(image_url)
            if not image_data:
                return self._empty_analysis("No se pudo descargar la imagen")

            # Construir prompt de análisis
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_analysis_prompt(property_context)

            # Llamar a Claude Vision
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": image_data['media_type'],
                                    "data": image_data['data']
                                }
                            },
                            {
                                "type": "text",
                                "text": user_prompt
                            }
                        ]
                    }
                ],
                system=system_prompt
            )

            # Parsear respuesta JSON
            return self._parse_response(response.content[0].text)

        except Exception as e:
            print(f"❌ Error analizando imagen: {e}")
            return self._empty_analysis(str(e))

    def analyze_property_images(
        self,
        image_urls: List[str],
        property_context: Optional[Dict] = None,
        max_images: int = 5
    ) -> Dict[str, Any]:
        """
        Analiza múltiples imágenes de una propiedad y genera resumen

        Args:
            image_urls: Lista de URLs de imágenes
            property_context: Contexto de la propiedad
            max_images: Máximo de imágenes a analizar

        Returns:
            Resumen consolidado del análisis visual
        """
        if not image_urls:
            return self._empty_summary()

        # Limitar cantidad de imágenes
        urls_to_analyze = image_urls[:max_images]
        analyses = []

        print(f"📸 Analizando {len(urls_to_analyze)} imágenes...")

        for i, url in enumerate(urls_to_analyze):
            print(f"   Imagen {i + 1}/{len(urls_to_analyze)}...")
            analysis = self.analyze_image(url, property_context)
            if analysis.get('success'):
                analysis['imagen_url'] = url
                analysis['es_imagen_principal'] = (i == 0)
                analyses.append(analysis)

        if not analyses:
            return self._empty_summary()

        # Consolidar análisis
        return self._consolidate_analyses(analyses)

    def _download_image(self, url: str) -> Optional[Dict[str, str]]:
        """
        Descarga imagen y la convierte a base64

        Args:
            url: URL de la imagen

        Returns:
            Dict con 'data' (base64) y 'media_type'
        """
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, follow_redirects=True)
                response.raise_for_status()

                content_type = response.headers.get('content-type', 'image/jpeg')
                if 'jpeg' in content_type or 'jpg' in content_type:
                    media_type = 'image/jpeg'
                elif 'png' in content_type:
                    media_type = 'image/png'
                elif 'gif' in content_type:
                    media_type = 'image/gif'
                elif 'webp' in content_type:
                    media_type = 'image/webp'
                else:
                    media_type = 'image/jpeg'  # Default

                image_base64 = base64.standard_b64encode(response.content).decode('utf-8')

                return {
                    'data': image_base64,
                    'media_type': media_type
                }

        except Exception as e:
            print(f"⚠️ Error descargando imagen {url}: {e}")
            return None

    def _build_system_prompt(self) -> str:
        """Construye el prompt de sistema para análisis inmobiliario"""
        return """Eres un experto en análisis de imágenes inmobiliarias. Tu tarea es analizar imágenes de propiedades y extraer información visual relevante para compradores potenciales.

Debes identificar:
1. Tipo de espacio (sala, cocina, habitación, baño, exterior, fachada, etc.)
2. Estilo arquitectónico/decorativo (moderno, clásico, minimalista, rústico, etc.)
3. Ambiente general (luminoso, acogedor, amplio, íntimo, etc.)
4. Calidad de la imagen (1-10)
5. Características visibles importantes
6. Puntos destacados que un comprador valoraría

Responde SIEMPRE en formato JSON válido."""

    def _build_analysis_prompt(self, property_context: Optional[Dict] = None) -> str:
        """Construye el prompt de análisis"""
        context_str = ""
        if property_context:
            context_str = f"""
Contexto de la propiedad:
- Tipo: {property_context.get('tipo_propiedad', 'No especificado')}
- Ubicación: {property_context.get('zona', '')}, {property_context.get('ciudad', '')}
- Precio: {property_context.get('precio', 'No especificado')}
"""

        return f"""Analiza esta imagen de propiedad inmobiliaria.
{context_str}
Responde en el siguiente formato JSON:

{{
    "tipo_espacio": "sala | cocina | habitación | baño | exterior | fachada | otro",
    "estilo_detectado": "descripción del estilo (ej: moderno minimalista, clásico elegante)",
    "ambiente": "descripción del ambiente (ej: luminoso y espacioso, acogedor e íntimo)",
    "calidad_imagen": 8.5,
    "caracteristicas_visibles": [
        "característica 1",
        "característica 2",
        "característica 3"
    ],
    "puntos_destacados": [
        "punto destacado 1",
        "punto destacado 2"
    ],
    "descripcion_breve": "Descripción de 1-2 oraciones de lo que muestra la imagen"
}}

Sé específico y menciona elementos concretos que veas (pisos, iluminación, vistas, acabados, etc.)."""

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """
        Parsea la respuesta de Claude a JSON

        Args:
            response_text: Texto de respuesta de Claude

        Returns:
            Diccionario con el análisis
        """
        try:
            # Intentar extraer JSON de la respuesta
            import re

            # Buscar JSON en la respuesta
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                analysis = json.loads(json_match.group())
                analysis['success'] = True
                return analysis

            # Si no hay JSON, crear estructura desde texto
            return {
                'success': True,
                'tipo_espacio': 'general',
                'estilo_detectado': 'no determinado',
                'ambiente': 'no determinado',
                'calidad_imagen': 5.0,
                'caracteristicas_visibles': [],
                'puntos_destacados': [],
                'descripcion_breve': response_text[:200]
            }

        except json.JSONDecodeError as e:
            print(f"⚠️ Error parseando JSON: {e}")
            return self._empty_analysis(f"Error parsing: {e}")

    def _consolidate_analyses(self, analyses: List[Dict]) -> Dict[str, Any]:
        """
        Consolida múltiples análisis en un resumen

        Args:
            analyses: Lista de análisis individuales

        Returns:
            Resumen consolidado
        """
        if not analyses:
            return self._empty_summary()

        # Recopilar todas las características únicas
        all_caracteristicas = set()
        all_puntos = set()
        all_estilos = []
        all_ambientes = []
        calidades = []
        descripciones = []

        for analysis in analyses:
            # Características
            for c in analysis.get('caracteristicas_visibles', []):
                if c:
                    all_caracteristicas.add(c.lower().strip())

            # Puntos destacados
            for p in analysis.get('puntos_destacados', []):
                if p:
                    all_puntos.add(p)

            # Estilos
            estilo = analysis.get('estilo_detectado')
            if estilo and estilo != 'no determinado':
                all_estilos.append(estilo)

            # Ambientes
            ambiente = analysis.get('ambiente')
            if ambiente and ambiente != 'no determinado':
                all_ambientes.append(ambiente)

            # Calidad
            calidad = analysis.get('calidad_imagen')
            if calidad:
                calidades.append(float(calidad))

            # Descripción
            desc = analysis.get('descripcion_breve')
            if desc:
                descripciones.append(desc)

        # Determinar estilo y ambiente predominante
        estilo_predominante = self._get_most_common(all_estilos) or "Contemporáneo"
        ambiente_general = self._get_most_common(all_ambientes) or "Agradable"

        # Calcular calidad promedio
        calidad_promedio = sum(calidades) / len(calidades) if calidades else 5.0

        # Generar tags para búsqueda
        tags = self._generate_tags(
            all_caracteristicas,
            all_puntos,
            estilo_predominante,
            ambiente_general
        )

        # Generar descripción general
        descripcion_general = self._generate_summary_description(
            estilo_predominante,
            ambiente_general,
            list(all_puntos)[:5]
        )

        return {
            'success': True,
            'descripcion_general': descripcion_general,
            'estilo_predominante': estilo_predominante,
            'ambiente_general': ambiente_general,
            'calidad_promedio': round(calidad_promedio, 1),
            'todas_caracteristicas': list(all_caracteristicas),
            'todos_puntos_destacados': list(all_puntos),
            'tags_visuales': tags,
            'total_imagenes_analizadas': len(analyses),
            'analisis_individuales': analyses
        }

    def _get_most_common(self, items: List[str]) -> Optional[str]:
        """Obtiene el elemento más común de una lista"""
        if not items:
            return None
        from collections import Counter
        counts = Counter(items)
        return counts.most_common(1)[0][0]

    def _generate_tags(
        self,
        caracteristicas: set,
        puntos: set,
        estilo: str,
        ambiente: str
    ) -> List[str]:
        """Genera tags para búsqueda rápida"""
        tags = set()

        # Tags de estilo
        estilo_lower = estilo.lower()
        if 'modern' in estilo_lower:
            tags.add('moderno')
        if 'clásic' in estilo_lower or 'classic' in estilo_lower:
            tags.add('clásico')
        if 'minimal' in estilo_lower:
            tags.add('minimalista')
        if 'rústic' in estilo_lower:
            tags.add('rústico')
        if 'contempor' in estilo_lower:
            tags.add('contemporáneo')

        # Tags de ambiente
        ambiente_lower = ambiente.lower()
        if 'luminos' in ambiente_lower or 'luz' in ambiente_lower:
            tags.add('luminoso')
        if 'ampli' in ambiente_lower or 'espacio' in ambiente_lower:
            tags.add('amplio')
        if 'acogedor' in ambiente_lower:
            tags.add('acogedor')

        # Tags de características
        keywords = {
            'vista': ['vista', 'panorám', 'view'],
            'piscina': ['piscina', 'pool'],
            'jardín': ['jardín', 'garden', 'verde'],
            'terraza': ['terraza', 'balcón', 'balcon'],
            'cocina_integral': ['cocina integral', 'cocina abierta'],
            'acabados_lujo': ['lujo', 'premium', 'alta gama', 'porcelanato'],
            'natural': ['natural', 'madera', 'piedra'],
        }

        all_text = ' '.join(caracteristicas) + ' ' + ' '.join(puntos)
        all_text = all_text.lower()

        for tag, keywords_list in keywords.items():
            for kw in keywords_list:
                if kw in all_text:
                    tags.add(tag.replace('_', ' '))
                    break

        return list(tags)[:15]  # Máximo 15 tags

    def _generate_summary_description(
        self,
        estilo: str,
        ambiente: str,
        puntos: List[str]
    ) -> str:
        """Genera descripción resumen del análisis visual"""
        parts = [f"Propiedad con estilo {estilo.lower()} y ambiente {ambiente.lower()}."]

        if puntos:
            puntos_str = ", ".join(puntos[:3])
            parts.append(f"Destaca: {puntos_str}.")

        return " ".join(parts)

    def _empty_analysis(self, error: str = "") -> Dict[str, Any]:
        """Retorna análisis vacío"""
        return {
            'success': False,
            'error': error,
            'tipo_espacio': None,
            'estilo_detectado': None,
            'ambiente': None,
            'calidad_imagen': None,
            'caracteristicas_visibles': [],
            'puntos_destacados': [],
            'descripcion_breve': None
        }

    def _empty_summary(self) -> Dict[str, Any]:
        """Retorna resumen vacío"""
        return {
            'success': False,
            'descripcion_general': None,
            'estilo_predominante': None,
            'ambiente_general': None,
            'calidad_promedio': None,
            'todas_caracteristicas': [],
            'todos_puntos_destacados': [],
            'tags_visuales': [],
            'total_imagenes_analizadas': 0
        }


# Singleton
_image_analyzer = None


def get_image_analyzer() -> ImageAnalyzer:
    """Obtiene instancia singleton del analizador de imágenes"""
    global _image_analyzer
    if _image_analyzer is None:
        _image_analyzer = ImageAnalyzer()
    return _image_analyzer
