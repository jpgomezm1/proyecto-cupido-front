#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de Búsqueda Vectorial - Proyecto Cupido
Combina búsqueda SQL tradicional con similitud semántica
"""

import os
import json
from typing import List, Dict, Any, Optional, Tuple
from src.db.database import DatabaseManager
from src.core.embeddings import get_embeddings_manager, EmbeddingsManager
from dotenv import load_dotenv

load_dotenv()


class VectorSearch:
    """
    Motor de búsqueda híbrida: SQL + Vector
    Combina filtros tradicionales con similitud semántica
    """

    def __init__(self):
        self.embeddings = get_embeddings_manager()
        self.default_match_threshold = 0.5  # Umbral mínimo de similitud
        self.default_limit = 20

    def search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 20,
        use_filters: bool = True
    ) -> Dict[str, Any]:
        """
        Búsqueda híbrida: combina filtros SQL con similitud vectorial

        Args:
            query: Consulta en lenguaje natural
            filters: Filtros extraídos (ciudad, tipo, precio, etc.)
            limit: Máximo de resultados
            use_filters: Si aplicar filtros SQL además de similitud

        Returns:
            Dict con resultados y metadata
        """
        try:
            # 1. Generar embedding de la consulta
            print("🔮 Generando embedding de consulta...")
            query_embedding = self.embeddings.generate_query_embedding(query)

            if not query_embedding:
                return {
                    'success': False,
                    'error': 'No se pudo generar embedding de consulta',
                    'results': []
                }

            # 2. Ejecutar búsqueda híbrida
            print("🔍 Ejecutando búsqueda vectorial...")
            with DatabaseManager() as db:
                results = self._hybrid_search(
                    db,
                    query_embedding,
                    filters if use_filters else None,
                    limit
                )

            print(f"✅ Encontradas {len(results)} propiedades por similitud")

            return {
                'success': True,
                'results': results,
                'count': len(results),
                'search_type': 'hybrid' if use_filters else 'semantic'
            }

        except Exception as e:
            print(f"❌ Error en búsqueda vectorial: {e}")
            return {
                'success': False,
                'error': str(e),
                'results': []
            }

    def _hybrid_search(
        self,
        db: DatabaseManager,
        query_embedding: List[float],
        filters: Optional[Dict[str, Any]],
        limit: int
    ) -> List[Dict]:
        """
        Ejecuta búsqueda híbrida en la base de datos

        Args:
            db: Conexión a la base de datos
            query_embedding: Embedding de la consulta
            filters: Filtros opcionales
            limit: Límite de resultados

        Returns:
            Lista de propiedades ordenadas por score
        """
        # Convertir embedding a formato PostgreSQL
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'

        # Construir query
        query = """
        SELECT
            p.id,
            p.codigo_propiedad as slug,
            p.titulo,
            p.precio,
            p.precio_texto,
            p.tipo_propiedad,
            p.ciudad,
            p.zona,
            p.direccion_completa,
            p.area_construida,
            p.habitaciones,
            p.banos,
            p.parqueaderos,
            p.estrato,
            p.amenidades_internas,
            p.amenidades_externas,
            p.total_amenidades,
            p.imagen_principal,
            p.descripcion,
            p.fuente,
            p.telefono,
            p.asesor,
            -- Similitud vectorial
            1 - (pe.embedding <=> %(embedding)s::vector) as similarity,
            -- Datos visuales
            pvs.estilo_predominante,
            pvs.ambiente_general,
            pvs.tags_visuales,
            pvs.calidad_promedio as calidad_imagenes,
            pvs.descripcion_general as descripcion_visual
        FROM propiedades p
        LEFT JOIN property_embeddings pe ON pe.propiedad_id = p.id
        LEFT JOIN property_visual_summary pvs ON pvs.propiedad_id = p.id
        WHERE p.activa = TRUE
        AND (p.tipo_negocio = 'Venta' OR p.tipo_negocio IS NULL)
        AND pe.embedding IS NOT NULL
        """

        params = {'embedding': embedding_str}

        # Agregar filtros si existen
        if filters:
            print(f"[VectorSearch] Filtros recibidos: precio_min_implicito={filters.get('precio_min_implicito')}, precio_max_ajustado={filters.get('precio_max_ajustado')}")
            # Filtro de ubicación
            if filters.get('ubicaciones'):
                ubicaciones = filters['ubicaciones']
                if isinstance(ubicaciones, list):
                    location_conditions = []
                    for i, ub in enumerate(ubicaciones):
                        location_conditions.append(
                            f"(p.ciudad ILIKE %(ub_{i})s OR p.zona ILIKE %(ub_{i})s OR p.titulo ILIKE %(ub_{i})s)"
                        )
                        params[f'ub_{i}'] = f'%{ub}%'
                    query += f" AND ({' OR '.join(location_conditions)})"
                else:
                    query += " AND (p.ciudad ILIKE %(ubicacion)s OR p.zona ILIKE %(ubicacion)s)"
                    params['ubicacion'] = f'%{ubicaciones}%'

            # Filtro de tipo
            if filters.get('tipo_propiedad'):
                tipos = filters['tipo_propiedad']
                if isinstance(tipos, list):
                    tipo_conditions = []
                    for i, tipo in enumerate(tipos):
                        tipo_conditions.append(f"p.tipo_propiedad ILIKE %(tipo_{i})s")
                        params[f'tipo_{i}'] = f'%{tipo}%'
                    query += f" AND ({' OR '.join(tipo_conditions)})"
                else:
                    query += " AND p.tipo_propiedad ILIKE %(tipo)s"
                    params['tipo'] = f'%{tipos}%'

            # Filtro de precio
            # v2.6: Usar precio_min_implicito si existe (filtro calculado del rango ±10%)
            precio_min = filters.get('precio_min') or filters.get('precio_min_implicito')
            if precio_min:
                query += " AND p.precio >= %(precio_min)s"
                params['precio_min'] = precio_min

            # v2.6: Usar precio_max_ajustado si existe (filtro calculado del rango ±10%)
            precio_max = filters.get('precio_max_ajustado') or filters.get('precio_max')
            if precio_max:
                query += " AND p.precio <= %(precio_max)s"
                params['precio_max'] = precio_max

            # Filtro de habitaciones
            if filters.get('habitaciones_min'):
                query += " AND p.habitaciones >= %(hab_min)s"
                params['hab_min'] = filters['habitaciones_min']

            # v2.6: Filtro por área mínima
            area_min = filters.get('area_min_ajustado') or filters.get('area_min')
            if area_min:
                query += " AND p.area_construida >= %(area_min)s"
                params['area_min'] = area_min

            # v2.6: Filtro por antigüedad máxima
            if filters.get('antiguedad_max'):
                ano_minimo = 2026 - filters['antiguedad_max']
                query += " AND (p.ano_construccion >= %(ano_minimo)s OR p.ano_construccion IS NULL)"
                params['ano_minimo'] = ano_minimo

            # v2.6: Filtro por administración máxima
            if filters.get('administracion_max'):
                query += " AND (p.administracion <= %(admin_max)s OR p.administracion IS NULL)"
                params['admin_max'] = filters['administracion_max']

            # v2.6: Filtro por parqueaderos
            if filters.get('parqueaderos_min'):
                query += " AND p.parqueaderos >= %(parq_min)s"
                params['parq_min'] = filters['parqueaderos_min']

        # Ordenar por similitud + score combinado
        query += """
        ORDER BY similarity DESC
        LIMIT %(limit)s
        """
        params['limit'] = limit

        try:
            db.cursor.execute(query, params)
            rows = db.cursor.fetchall()

            results = []
            for row in rows:
                prop = dict(row)

                # Calcular score final combinado
                similarity = prop.get('similarity') or 0
                prop['match_score'] = self._calculate_combined_score(
                    similarity,
                    prop,
                    filters
                )

                # Convertir tipos para JSON
                for key, value in prop.items():
                    if hasattr(value, 'isoformat'):
                        prop[key] = value.isoformat()
                    elif isinstance(value, list):
                        continue  # Ya es lista
                    elif not isinstance(value, (int, float, str, bool, type(None))):
                        prop[key] = str(value)

                results.append(prop)

            # Ordenar por score combinado
            results.sort(key=lambda x: x.get('match_score', 0), reverse=True)

            return results

        except Exception as e:
            print(f"❌ Error en query híbrida: {e}")
            # Fallback a búsqueda sin vector
            return self._fallback_sql_search(db, filters, limit)

    def _calculate_combined_score(
        self,
        similarity: float,
        property_data: Dict,
        filters: Optional[Dict]
    ) -> float:
        """
        Calcula score combinado considerando:
        - Similitud semántica (50%)
        - Coincidencia con filtros (30%)
        - Calidad de imágenes (10%)
        - Fuente (Pulppo bonus) (10%)

        Args:
            similarity: Score de similitud vectorial
            property_data: Datos de la propiedad
            filters: Filtros de búsqueda

        Returns:
            Score combinado (0-100)
        """
        score = 0

        # 1. Similitud semántica (0-50 puntos)
        score += similarity * 50

        # 2. Coincidencia con filtros (0-30 puntos)
        filter_score = 0
        if filters:
            # Ubicación exacta
            if filters.get('ubicaciones'):
                ubicaciones = filters['ubicaciones']
                if isinstance(ubicaciones, str):
                    ubicaciones = [ubicaciones]
                for ub in ubicaciones:
                    ub_lower = ub.lower()
                    ciudad = (property_data.get('ciudad') or '').lower()
                    zona = (property_data.get('zona') or '').lower()
                    if ub_lower in ciudad or ub_lower in zona:
                        filter_score += 10
                        break

            # Tipo exacto
            if filters.get('tipo_propiedad'):
                tipos = filters['tipo_propiedad']
                if isinstance(tipos, str):
                    tipos = [tipos]
                prop_tipo = (property_data.get('tipo_propiedad') or '').lower()
                for t in tipos:
                    if t.lower() in prop_tipo:
                        filter_score += 10
                        break

            # Precio en rango
            if filters.get('precio_max'):
                precio = property_data.get('precio') or 0
                if precio <= filters['precio_max']:
                    filter_score += 5
                if filters.get('precio_min') and precio >= filters['precio_min']:
                    filter_score += 5

        score += min(filter_score, 30)

        # 3. Calidad de imágenes (0-10 puntos)
        calidad = property_data.get('calidad_imagenes')
        if calidad:
            score += min(float(calidad), 10)

        # 4. Bonus por propiedades propias (0-10 puntos)
        if property_data.get('fuente') == 'Propia':
            score += 10

        return round(score, 2)

    def _fallback_sql_search(
        self,
        db: DatabaseManager,
        filters: Optional[Dict],
        limit: int
    ) -> List[Dict]:
        """
        Búsqueda SQL tradicional como fallback
        Usado cuando no hay embeddings disponibles
        """
        query = """
        SELECT
            p.id,
            p.codigo_propiedad as slug,
            p.titulo,
            p.precio,
            p.tipo_propiedad,
            p.ciudad,
            p.zona,
            p.habitaciones,
            p.banos,
            p.parqueaderos,
            p.imagen_principal,
            p.fuente,
            0.5 as similarity
        FROM propiedades p
        WHERE p.activa = TRUE
        AND (p.tipo_negocio = 'Venta' OR p.tipo_negocio IS NULL)
        ORDER BY p.fecha_creacion DESC
        LIMIT %s
        """

        db.cursor.execute(query, (limit,))
        rows = db.cursor.fetchall()

        return [dict(row) for row in rows]

    def search_similar_properties(
        self,
        property_id: int,
        limit: int = 6
    ) -> List[Dict]:
        """
        Encuentra propiedades similares a una dada

        Args:
            property_id: ID de la propiedad de referencia
            limit: Número de resultados

        Returns:
            Lista de propiedades similares
        """
        try:
            with DatabaseManager() as db:
                # Obtener embedding de la propiedad
                db.cursor.execute("""
                    SELECT embedding
                    FROM property_embeddings
                    WHERE propiedad_id = %s
                """, (property_id,))

                result = db.cursor.fetchone()
                if not result or not result['embedding']:
                    return []

                # Buscar similares
                embedding_str = result['embedding']

                db.cursor.execute("""
                    SELECT
                        p.id,
                        p.codigo_propiedad as slug,
                        p.titulo,
                        p.precio,
                        p.tipo_propiedad,
                        p.ciudad,
                        p.zona,
                        p.habitaciones,
                        p.imagen_principal,
                        1 - (pe.embedding <=> %s::vector) as similarity
                    FROM propiedades p
                    JOIN property_embeddings pe ON pe.propiedad_id = p.id
                    WHERE p.activa = TRUE
                    AND (p.tipo_negocio = 'Venta' OR p.tipo_negocio IS NULL)
                    AND p.id != %s
                    ORDER BY pe.embedding <=> %s::vector
                    LIMIT %s
                """, (embedding_str, property_id, embedding_str, limit))

                return [dict(row) for row in db.cursor.fetchall()]

        except Exception as e:
            print(f"❌ Error buscando similares: {e}")
            return []

    def get_embedding_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas de embeddings

        Returns:
            Dict con estadísticas
        """
        try:
            with DatabaseManager() as db:
                db.cursor.execute("""
                    SELECT
                        COUNT(DISTINCT pe.propiedad_id) as propiedades_con_embedding,
                        (SELECT COUNT(*) FROM propiedades WHERE activa = TRUE) as total_propiedades,
                        (SELECT COUNT(*) FROM property_visual_summary) as propiedades_con_vision,
                        (SELECT COUNT(*) FROM property_image_analysis) as imagenes_analizadas
                """)

                stats = db.cursor.fetchone()
                return {
                    'propiedades_con_embedding': stats['propiedades_con_embedding'],
                    'total_propiedades': stats['total_propiedades'],
                    'propiedades_con_vision': stats['propiedades_con_vision'],
                    'imagenes_analizadas': stats['imagenes_analizadas'],
                    'cobertura_embeddings': round(
                        stats['propiedades_con_embedding'] / max(stats['total_propiedades'], 1) * 100, 1
                    )
                }

        except Exception as e:
            print(f"❌ Error obteniendo stats: {e}")
            return {}


# Singleton
_vector_search = None


def get_vector_search() -> VectorSearch:
    """Obtiene instancia singleton de VectorSearch"""
    global _vector_search
    if _vector_search is None:
        _vector_search = VectorSearch()
    return _vector_search
