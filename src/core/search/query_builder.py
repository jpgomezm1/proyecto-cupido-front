#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Constructor de queries SQL para búsqueda de propiedades.

Este módulo se encarga de construir queries SQL basadas en criterios
de búsqueda y ejecutar búsquedas progresivas con relajación de criterios.
"""

import traceback
from typing import Dict, List, Any, Tuple

from src.db.database import DatabaseManager
from src.core.search_config import quitar_acentos


def _ubicacion_variants(ubicacion: str) -> List[str]:
    """Genera variantes con y sin acentos para matching ILIKE accent-insensitive."""
    sin_acentos = quitar_acentos(ubicacion)
    if sin_acentos.lower() != ubicacion.lower():
        return [ubicacion, sin_acentos]
    return [ubicacion]


class QueryBuilder:
    """Construye y ejecuta queries SQL para búsqueda de propiedades."""

    def build_relaxed_criteria(self, criteria: Dict[str, Any], level: int) -> Dict[str, Any]:
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
                relaxed['precio_max_ajustado'] = int(criteria['precio_max'] * 1.25)

        return relaxed

    def progressive_search(
        self,
        criteria: Dict[str, Any],
        db: DatabaseManager,
        min_results: int = 5,
        max_level: int = 4
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        """
        Búsqueda progresiva que relaja criterios hasta obtener min_results.

        Args:
            criteria: Criterios de búsqueda originales
            db: Conexión a base de datos
            min_results: Mínimo de resultados deseados
            max_level: Máximo nivel de relajación

        Returns:
            Tuple de (resultados, metadata de progresión)
        """
        search_progression = {
            'nivel_final': 0,
            'resultados_por_nivel': {},
            'relajaciones_aplicadas': []
        }

        results = []

        # Log de diagnóstico
        print(f"   Criterios clave para SQL:")
        if criteria.get('ubicaciones'):
            print(f"     - Ubicaciones: {criteria['ubicaciones']}")
        if criteria.get('precio_max'):
            print(f"     - Precio max: ${criteria['precio_max']:,}")
        if criteria.get('tipo_propiedad'):
            print(f"     - Tipo: {criteria['tipo_propiedad']}")

        for level in range(max_level + 1):
            relaxed_criteria = self.build_relaxed_criteria(criteria, level)
            sql_query, params = self.build_sql_query(relaxed_criteria)

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

                if len(results) >= min_results:
                    search_progression['nivel_final'] = level
                    search_progression['relajaciones_aplicadas'] = self.get_relaxation_descriptions(level)
                    return results, search_progression

            except Exception as e:
                print(f"⚠️  Error en nivel {level}: {e}")
                print(f"   Query: {sql_query[:200]}...")
                print(f"   Params: {list(params.keys())}")
                traceback.print_exc()
                try:
                    db.conn.rollback()
                except:
                    pass
                continue

        search_progression['nivel_final'] = max_level
        search_progression['relajaciones_aplicadas'] = self.get_relaxation_descriptions(max_level)
        return results, search_progression

    def get_relaxation_descriptions(self, level: int) -> List[str]:
        """Retorna descripciones de qué criterios se relajaron."""
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

    def build_sql_query(self, criteria: Dict[str, Any]) -> Tuple[str, Dict]:
        """
        Construye una consulta SQL basada en los criterios.

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
        AND (tipo_negocio = 'Venta' OR tipo_negocio IS NULL)
        """

        conditions = []
        params = {}

        # Filtro de precio (banda ±10% estricta)
        if criteria.get('precio_max'):
            precio_max_duro = criteria.get('precio_max_ajustado') or criteria['precio_max']
            conditions.append("precio <= %(precio_max_duro)s")
            params['precio_max_duro'] = precio_max_duro

            # Usar precio_min explícito si existe, sino precio_min_implicito (±10%)
            precio_min_duro = criteria.get('precio_min') or criteria.get('precio_min_implicito')
            if precio_min_duro:
                conditions.append("precio >= %(precio_min_duro)s")
                params['precio_min_duro'] = precio_min_duro

        # Tipo de propiedad
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

        # Ubicaciones
        # v2.13: Incluir variantes sin acentos para matching accent-insensitive
        ubicaciones_buscar = criteria.get('zonas_expandidas') or criteria.get('ubicaciones')
        if ubicaciones_buscar:
            zona_conditions = []
            param_idx = 0
            for ubicacion in ubicaciones_buscar:
                for variant in _ubicacion_variants(ubicacion):
                    zona_conditions.append(f"""(
                        zona ILIKE %(ubicacion_{param_idx})s OR
                        ciudad ILIKE %(ubicacion_{param_idx})s OR
                        direccion_completa ILIKE %(ubicacion_{param_idx})s OR
                        titulo ILIKE %(ubicacion_{param_idx})s
                    )""")
                    params[f'ubicacion_{param_idx}'] = f'%{variant}%'
                    param_idx += 1
            conditions.append(f"({' OR '.join(zona_conditions)})")

        # Habitaciones
        if criteria.get('habitaciones_min'):
            conditions.append("habitaciones >= %(habitaciones_min)s")
            params['habitaciones_min'] = criteria['habitaciones_min']

        if criteria.get('habitaciones_max'):
            conditions.append("habitaciones <= %(habitaciones_max)s")
            params['habitaciones_max'] = criteria['habitaciones_max']

        # Baños
        if criteria.get('banos_min'):
            conditions.append("banos >= %(banos_min)s")
            params['banos_min'] = criteria['banos_min']

        if criteria.get('banos_max'):
            conditions.append("banos <= %(banos_max)s")
            params['banos_max'] = criteria['banos_max']

        # Área
        if criteria.get('area_min'):
            conditions.append("area_construida >= %(area_min)s")
            params['area_min'] = criteria['area_min']

        if criteria.get('area_max'):
            conditions.append("area_construida <= %(area_max)s")
            params['area_max'] = criteria['area_max']

        # Piso
        if criteria.get('piso'):
            if criteria['piso'] == 1 or str(criteria['piso']).lower() == 'primer piso':
                conditions.append("piso = 1")
            elif isinstance(criteria['piso'], int):
                conditions.append("piso = %(piso)s")
                params['piso'] = criteria['piso']

        # v2.15: Piso mínimo/máximo (piso alto / piso bajo)
        if criteria.get('piso_min'):
            conditions.append("piso >= %(piso_min)s")
            params['piso_min'] = criteria['piso_min']

        if criteria.get('piso_max'):
            conditions.append("piso <= %(piso_max)s")
            params['piso_max'] = criteria['piso_max']

        # Parqueaderos
        if criteria.get('parqueaderos_min'):
            conditions.append("parqueaderos >= %(parqueaderos_min)s")
            params['parqueaderos_min'] = criteria['parqueaderos_min']

        # NOTA: Las amenidades NO se filtran en SQL - solo afectan el ranking
        # Esto permite mostrar más resultados y rankear los mejores primero

        if conditions:
            base_query += " AND " + " AND ".join(conditions)

        base_query += " ORDER BY total_amenidades DESC, precio ASC"
        base_query += " LIMIT 50"

        return base_query, params
