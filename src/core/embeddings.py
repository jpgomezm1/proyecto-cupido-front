#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Embeddings - Proyecto Cupido
Genera embeddings vectoriales usando OpenAI text-embedding-3-small
"""

import os
import json
from typing import List, Dict, Any, Optional
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class EmbeddingsManager:
    """
    Gestiona la generación de embeddings para propiedades
    Usa OpenAI text-embedding-3-small (1536 dimensiones)
    """

    def __init__(self):
        self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        self.model = "text-embedding-3-small"
        self.dimensions = 1536

    def generate_embedding(self, text: str) -> List[float]:
        """
        Genera un embedding para un texto dado

        Args:
            text: Texto a vectorizar

        Returns:
            Lista de floats representando el embedding (1536 dimensiones)
        """
        if not text or not text.strip():
            return []

        try:
            # Limpiar y truncar texto (máximo ~8000 tokens para el modelo)
            clean_text = self._clean_text(text)

            response = self.client.embeddings.create(
                model=self.model,
                input=clean_text,
                dimensions=self.dimensions
            )

            return response.data[0].embedding

        except Exception as e:
            print(f"❌ Error generando embedding: {e}")
            return []

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Genera embeddings para múltiples textos en batch
        Más eficiente que llamadas individuales

        Args:
            texts: Lista de textos a vectorizar

        Returns:
            Lista de embeddings
        """
        if not texts:
            return []

        try:
            # Limpiar textos
            clean_texts = [self._clean_text(t) for t in texts if t and t.strip()]

            if not clean_texts:
                return []

            response = self.client.embeddings.create(
                model=self.model,
                input=clean_texts,
                dimensions=self.dimensions
            )

            return [item.embedding for item in response.data]

        except Exception as e:
            print(f"❌ Error generando embeddings en batch: {e}")
            return []

    def build_property_text(self, property_data: Dict[str, Any]) -> str:
        """
        Construye el texto optimizado para embedding de una propiedad
        Combina título, descripción, características y metadata

        Args:
            property_data: Diccionario con datos de la propiedad

        Returns:
            Texto optimizado para embedding
        """
        parts = []

        # 1. Título (peso alto)
        titulo = property_data.get('titulo') or ''
        if titulo:
            parts.append(f"Propiedad: {titulo}")

        # 2. Tipo y ubicación (peso alto)
        tipo = property_data.get('tipo_propiedad') or ''
        ciudad = property_data.get('ciudad') or ''
        zona = property_data.get('zona') or ''

        if tipo:
            parts.append(f"Tipo: {tipo}")
        if ciudad and zona:
            parts.append(f"Ubicación: {zona}, {ciudad}")
        elif ciudad:
            parts.append(f"Ciudad: {ciudad}")

        # 3. Características principales
        caracteristicas = []

        habitaciones = property_data.get('habitaciones')
        if habitaciones:
            caracteristicas.append(f"{habitaciones} habitaciones")

        banos = property_data.get('banos')
        if banos:
            caracteristicas.append(f"{banos} baños")

        parqueaderos = property_data.get('parqueaderos')
        if parqueaderos:
            caracteristicas.append(f"{parqueaderos} parqueaderos")

        area = property_data.get('area_construida')
        if area:
            caracteristicas.append(f"{area} m² construidos")

        estrato = property_data.get('estrato')
        if estrato:
            caracteristicas.append(f"estrato {estrato}")

        if caracteristicas:
            parts.append(f"Características: {', '.join(caracteristicas)}")

        # 4. Precio (normalizado para contexto)
        precio = property_data.get('precio')
        if precio:
            if precio >= 1_000_000_000:
                precio_texto = f"{precio / 1_000_000_000:.1f} mil millones"
            elif precio >= 1_000_000:
                precio_texto = f"{precio / 1_000_000:.0f} millones"
            else:
                precio_texto = f"{precio:,.0f}"
            parts.append(f"Precio: {precio_texto} COP")

        # 5. Amenidades internas
        amenidades_internas = property_data.get('amenidades_internas') or ''
        if amenidades_internas:
            parts.append(f"Amenidades internas: {amenidades_internas}")

        # 6. Amenidades externas
        amenidades_externas = property_data.get('amenidades_externas') or ''
        if amenidades_externas:
            parts.append(f"Amenidades externas: {amenidades_externas}")

        # 7. Descripción (peso medio-alto)
        descripcion = property_data.get('descripcion') or ''
        if descripcion:
            # Truncar descripción si es muy larga
            desc_truncada = descripcion[:1500] if len(descripcion) > 1500 else descripcion
            parts.append(f"Descripción: {desc_truncada}")

        # 8. Características adicionales
        caracteristicas_adicionales = property_data.get('caracteristicas_adicionales') or ''
        if caracteristicas_adicionales:
            parts.append(f"Características adicionales: {caracteristicas_adicionales}")

        # 9. Análisis visual (si existe)
        descripcion_visual = property_data.get('descripcion_visual') or ''
        if descripcion_visual:
            parts.append(f"Análisis visual: {descripcion_visual}")

        estilo = property_data.get('estilo_predominante') or ''
        if estilo:
            parts.append(f"Estilo: {estilo}")

        ambiente = property_data.get('ambiente_general') or ''
        if ambiente:
            parts.append(f"Ambiente: {ambiente}")

        tags_visuales = property_data.get('tags_visuales') or []
        if tags_visuales:
            if isinstance(tags_visuales, list):
                parts.append(f"Tags: {', '.join(tags_visuales)}")
            else:
                parts.append(f"Tags: {tags_visuales}")

        return "\n".join(parts)

    def generate_query_embedding(self, query: str) -> List[float]:
        """
        Genera embedding para una consulta de búsqueda
        Optimizado para queries en lenguaje natural

        Args:
            query: Consulta del usuario

        Returns:
            Embedding de la consulta
        """
        # Enriquecer la query con contexto inmobiliario
        enriched_query = f"Búsqueda de propiedad inmobiliaria: {query}"
        return self.generate_embedding(enriched_query)

    def _clean_text(self, text: str) -> str:
        """
        Limpia y normaliza texto para embedding

        Args:
            text: Texto a limpiar

        Returns:
            Texto limpio
        """
        if not text:
            return ""

        # Remover caracteres especiales excesivos
        import re
        text = re.sub(r'\s+', ' ', text)  # Múltiples espacios a uno
        text = re.sub(r'[^\w\s\.,;:\-\(\)$%°²³áéíóúñÁÉÍÓÚÑ]', '', text)

        # Truncar si es muy largo (OpenAI tiene límite de tokens)
        max_chars = 8000
        if len(text) > max_chars:
            text = text[:max_chars]

        return text.strip()

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        Calcula similitud coseno entre dos vectores

        Args:
            vec1: Primer vector
            vec2: Segundo vector

        Returns:
            Similitud coseno (0-1)
        """
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        import math

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)


# Singleton para reutilizar cliente
_embeddings_manager = None


def get_embeddings_manager() -> EmbeddingsManager:
    """Obtiene instancia singleton del manager de embeddings"""
    global _embeddings_manager
    if _embeddings_manager is None:
        _embeddings_manager = EmbeddingsManager()
    return _embeddings_manager
