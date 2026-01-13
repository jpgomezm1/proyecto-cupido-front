#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Búsqueda Inteligente de Propiedades

Este módulo expone el agente de búsqueda y sus componentes.

Uso recomendado:
    from src.core.search import PropertySearchAgent

    agent = PropertySearchAgent()
    results = agent.search("Apto en Laureles hasta 500 millones")

Componentes disponibles:
    - PropertySearchAgent: Agente principal de búsqueda con IA
    - CriteriaExtractor: Extractor de criterios usando Claude
    - QueryBuilder: Constructor de queries SQL
    - ResultRanker: Sistema de ranking de resultados
    - ResponseFormatter: Formateador de respuestas
    - search_log: Logger especializado para búsquedas

Configuración:
    - Las configuraciones de búsqueda están en search_config.py
    - La búsqueda vectorial está en vector_search.py (opcional)
"""

# Re-exportar desde el módulo original para compatibilidad
from src.core.search_agent import (
    PropertySearchAgent,
    ANTHROPIC_AVAILABLE,
    VECTOR_SEARCH_AVAILABLE,
    MODEL,
    FALLBACK_MODELS,
)

# Exportar nuevos módulos refactorizados
from src.core.search.criteria_extractor import CriteriaExtractor
from src.core.search.query_builder import QueryBuilder
from src.core.search.ranker import ResultRanker
from src.core.search.formatter import ResponseFormatter

# Re-exportar logger
from src.core.logger import get_search_logger

search_log = get_search_logger()

__all__ = [
    # Agente principal (compatibilidad)
    'PropertySearchAgent',
    'ANTHROPIC_AVAILABLE',
    'VECTOR_SEARCH_AVAILABLE',
    'MODEL',
    'FALLBACK_MODELS',
    # Nuevos módulos
    'CriteriaExtractor',
    'QueryBuilder',
    'ResultRanker',
    'ResponseFormatter',
    # Logger
    'search_log',
]
