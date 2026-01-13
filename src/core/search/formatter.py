#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Formateador de respuestas de búsqueda.

Este módulo se encarga de formatear las respuestas de búsqueda
para diferentes canales (WhatsApp, API, etc.).
"""

from typing import Dict, List, Any

from src.core.search_config import get_zonas_expandidas


class ResponseFormatter:
    """Formatea respuestas de búsqueda para diferentes canales."""

    def generate_no_results_response(self, criteria: Dict[str, Any]) -> Dict[str, Any]:
        """
        Genera una respuesta informativa cuando no hay resultados.

        Args:
            criteria: Criterios de búsqueda aplicados

        Returns:
            Diccionario con información sobre la búsqueda sin resultados
        """
        sugerencias = self._build_suggestions(criteria)

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
            'mensaje_usuario': self.format_no_results_message(criteria, sugerencias)
        }

    def _build_suggestions(self, criteria: Dict[str, Any]) -> List[str]:
        """Construye sugerencias para ampliar la búsqueda."""
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

        return sugerencias

    def format_no_results_message(self, criteria: Dict[str, Any], sugerencias: List[str]) -> str:
        """
        Formatea el mensaje de no resultados para WhatsApp.

        Args:
            criteria: Criterios de búsqueda
            sugerencias: Lista de sugerencias

        Returns:
            Mensaje formateado
        """
        lines = []
        lines.append("No encontramos propiedades con esos criterios exactos")
        lines.append("")

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

        if sugerencias:
            lines.append("")
            lines.append("Sugerencias para encontrar opciones:")
            for i, sug in enumerate(sugerencias[:3], 1):
                lines.append(f"  {i}. {sug}")

        lines.append("")
        lines.append("Responde con nuevos criterios o escribe 'ampliar' para buscar con criterios más flexibles.")

        return "\n".join(lines)

    def format_results_for_agent(self, search_response: Dict) -> str:
        """
        Formatea los resultados de forma amigable para el agente inmobiliario.

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
            lines.extend(self._format_property(prop, i))

        if len(results) > 5:
            lines.append(f"... y {len(results) - 5} propiedades más")
            lines.append("")

        lines.append("=" * 50)

        return "\n".join(lines)

    def _format_property(self, prop: Dict, index: int) -> List[str]:
        """Formatea una propiedad individual."""
        lines = []

        score = prop.get('match_score', 0)
        lines.append(f"━━━ #{index} - Match: {score} pts ━━━")
        lines.append(f"🏠 {prop.get('titulo', 'Sin título')}")
        lines.append(f"💵 {prop.get('precio_texto', 'Precio no disponible')}")
        lines.append(f"📍 {prop.get('zona', '')} - {prop.get('ciudad', '')}")

        # Convertir valores a números de forma segura
        area = self._safe_number(prop.get('area_construida', 0), float)
        hab = self._safe_number(prop.get('habitaciones', 0), int)
        banos = self._safe_number(prop.get('banos', 0), int)
        pkdros = self._safe_number(prop.get('parqueaderos', 0), int)

        lines.append(f"📐 {area:.0f}m² | {hab} hab | {banos} baños | {pkdros} pkdros")

        if prop.get('piso'):
            lines.append(f"🏢 Piso: {prop.get('piso')}")

        if prop.get('match_reasons'):
            lines.append(f"✨ {', '.join(prop['match_reasons'][:3])}")

        if prop.get('asesor') or prop.get('telefono'):
            asesor = prop.get('asesor', 'No disponible')
            telefono = prop.get('telefono', '')
            lines.append(f"👤 {asesor} {telefono}")

        if prop.get('url'):
            lines.append(f"🔗 {prop.get('url')}")

        lines.append("")

        return lines

    def _safe_number(self, value, type_func):
        """Convierte un valor a número de forma segura."""
        if isinstance(value, (int, float)):
            return type_func(value)
        try:
            return type_func(value)
        except:
            return 0
