#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de ranking de propiedades.

Este módulo se encarga de rankear los resultados de búsqueda
según qué tan bien coinciden con los criterios del comprador.
"""

from typing import Dict, List, Any

from src.core.search_config import (
    get_pesos_perfil,
    get_amenidades_preferidas,
    AMENIDADES_SEGURIDAD,
)


class ResultRanker:
    """Rankea resultados de búsqueda según criterios y perfil del comprador."""

    def rank(self, results: List[Dict], criteria: Dict[str, Any]) -> List[Dict]:
        """
        Rankea los resultados según qué tan bien coinciden con los criterios.

        Args:
            results: Lista de propiedades encontradas
            criteria: Criterios de búsqueda originales

        Returns:
            Lista rankeada con score de coincidencia (0-100)
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

            # 1. PRECIO
            score, reasons, match_details = self._score_precio(
                result, criteria, score, reasons, match_details
            )

            # 2. UBICACIÓN
            score, reasons, match_details = self._score_ubicacion(
                result, criteria, score, reasons, match_details
            )

            # 3. HABITACIONES
            score, reasons, match_details = self._score_habitaciones(
                result, criteria, score, reasons, match_details
            )

            # 4. BAÑOS
            score, reasons = self._score_banos(result, criteria, score, reasons)

            # 5. PISO
            score, reasons = self._score_piso(
                result, criteria, score, reasons, perfil_comprador, pesos_perfil
            )

            # 6. AMENIDADES POR PERFIL
            score, reasons, match_details = self._score_amenidades_perfil(
                result, amenidades_preferidas, score, reasons, match_details
            )

            # 7. AMENIDADES REQUERIDAS
            score, reasons = self._score_amenidades_requeridas(
                result, criteria, score, reasons
            )

            # 8. SEGURIDAD
            score, reasons = self._score_seguridad(
                result, perfil_comprador, pesos_perfil, score, reasons
            )

            # 9. SEGMENTO DE MERCADO
            score, reasons = self._score_segmento(result, criteria, score, reasons)

            # 10. TIPO DE PROPIEDAD
            score, reasons = self._score_tipo(result, criteria, score, reasons)

            # 11. ESTADO DE CONSERVACIÓN
            score, reasons = self._score_estado(result, score, reasons)

            # 12. RENTABILIDAD
            score, reasons = self._score_rentabilidad(
                result, criteria, perfil_comprador, pesos_perfil, score, reasons
            )

            # 13. TOTAL AMENIDADES
            score, reasons = self._score_total_amenidades(result, score, reasons)

            # Normalizar y guardar
            score = max(0, min(100, score))
            result['match_score'] = score
            result['match_reasons'] = reasons[:5]
            result['match_details'] = match_details
            result['perfil_aplicado'] = perfil_comprador

        # Ordenar por score descendente
        results.sort(key=lambda x: x.get('match_score', 0), reverse=True)
        return results

    def _score_precio(self, result, criteria, score, reasons, match_details):
        """Evalúa el precio."""
        precio = result.get('precio', 0)
        if isinstance(precio, str):
            try:
                precio = float(precio.replace(',', '').replace('$', '').replace(' ', ''))
            except:
                precio = 0

        if criteria.get('precio_max') and precio > 0:
            precio_max = criteria['precio_max']
            precio_min = criteria.get('precio_min_implicito') or criteria.get('precio_min') or 0

            if precio_min <= precio <= precio_max:
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
                score -= 20
                match_details['precio'] = 'excede'

        return score, reasons, match_details

    def _score_ubicacion(self, result, criteria, score, reasons, match_details):
        """Evalúa la ubicación."""
        if not criteria.get('ubicaciones'):
            return score, reasons, match_details

        zona = (result.get('zona') or '').lower()
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

        if not ubicacion_match and criteria.get('zonas_expandidas'):
            for zona_exp in criteria['zonas_expandidas']:
                if zona_exp.lower() in zona or zona_exp.lower() in titulo:
                    score += 8
                    match_details['ubicacion'] = 'cercana'
                    reasons.append(f"Zona cercana: {result.get('zona')}")
                    break

        return score, reasons, match_details

    def _score_habitaciones(self, result, criteria, score, reasons, match_details):
        """Evalúa las habitaciones."""
        if not (criteria.get('habitaciones_min') or criteria.get('habitaciones_max')):
            return score, reasons, match_details

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
            score -= 5
            match_details['habitaciones'] = 'excede'

        return score, reasons, match_details

    def _score_banos(self, result, criteria, score, reasons):
        """Evalúa los baños."""
        if not (criteria.get('banos_min') or criteria.get('banos_max')):
            return score, reasons

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
            score -= 3

        return score, reasons

    def _score_piso(self, result, criteria, score, reasons, perfil_comprador, pesos_perfil):
        """Evalúa el piso."""
        if not criteria.get('piso'):
            return score, reasons

        piso_buscado = criteria['piso']
        piso_prop = result.get('piso')
        peso_piso = pesos_perfil.get('primer_piso', 1.0) if piso_buscado == 1 else 1.0

        if piso_prop == piso_buscado:
            score += int(10 * peso_piso)
            reasons.append(f"Piso {piso_buscado} (requerido)")
        elif piso_buscado == 1 and piso_prop and piso_prop > 1:
            if perfil_comprador == 'senior':
                score -= 15
                reasons.append("No es primer piso (requerido)")

        return score, reasons

    def _score_amenidades_perfil(self, result, amenidades_preferidas, score, reasons, match_details):
        """Evalúa amenidades según el perfil."""
        amenidades_int = (result.get('amenidades_internas') or '').lower()
        amenidades_ext = (result.get('amenidades_externas') or '').lower()
        amenidades_prop = amenidades_int + ' ' + amenidades_ext

        amenidades_encontradas = []
        for amenidad in amenidades_preferidas:
            if amenidad.lower() in amenidades_prop:
                amenidades_encontradas.append(amenidad)
                score += 3

        if amenidades_encontradas:
            match_details['amenidades'] = 'match'
            reasons.append(f"Amenidades ideales: {', '.join(amenidades_encontradas[:3])}")

        return score, reasons, match_details

    def _score_amenidades_requeridas(self, result, criteria, score, reasons):
        """Evalúa amenidades requeridas explícitamente."""
        if not criteria.get('amenidades_requeridas'):
            return score, reasons

        amenidades_int = (result.get('amenidades_internas') or '').lower()
        amenidades_ext = (result.get('amenidades_externas') or '').lower()
        amenidades_prop = amenidades_int + ' ' + amenidades_ext

        for amenidad in criteria['amenidades_requeridas']:
            if amenidad.lower() in amenidades_prop:
                score += 5
                if f"Tiene: {amenidad}" not in reasons:
                    reasons.append(f"Tiene: {amenidad}")

        return score, reasons

    def _score_seguridad(self, result, perfil_comprador, pesos_perfil, score, reasons):
        """Evalúa seguridad para familias y seniors."""
        if perfil_comprador not in ['familia', 'senior']:
            return score, reasons

        amenidades_int = (result.get('amenidades_internas') or '').lower()
        amenidades_ext = (result.get('amenidades_externas') or '').lower()
        amenidades_prop = amenidades_int + ' ' + amenidades_ext

        tiene_seguridad = any(s in amenidades_prop for s in AMENIDADES_SEGURIDAD)
        if tiene_seguridad:
            score += int(5 * pesos_perfil.get('seguridad', 1.0))
            reasons.append("Alta seguridad")

        return score, reasons

    def _score_segmento(self, result, criteria, score, reasons):
        """Evalúa el segmento de mercado."""
        segmento = result.get('segmento_mercado', '')
        if not criteria.get('precio_max'):
            return score, reasons

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

        return score, reasons

    def _score_tipo(self, result, criteria, score, reasons):
        """Evalúa el tipo de propiedad."""
        if not criteria.get('tipo_propiedad'):
            return score, reasons

        tipo_prop = (result.get('tipo_propiedad') or '').lower()
        tipos_buscar = criteria['tipo_propiedad']

        if isinstance(tipos_buscar, list):
            if any(t.lower() in tipo_prop for t in tipos_buscar):
                score += 5
                reasons.append(f"Tipo: {result.get('tipo_propiedad')}")
        elif tipos_buscar.lower() in tipo_prop:
            score += 5
            reasons.append(f"Tipo: {result.get('tipo_propiedad')}")

        return score, reasons

    def _score_estado(self, result, score, reasons):
        """Evalúa el estado de conservación."""
        estado_cons = result.get('estado_conservacion', '')
        if estado_cons in ['Nuevo', 'Excelente', 'A estrenar']:
            score += 4
            reasons.append(f"Estado: {estado_cons}")
        return score, reasons

    def _score_rentabilidad(self, result, criteria, perfil_comprador, pesos_perfil, score, reasons):
        """Evalúa rentabilidad para inversionistas."""
        if perfil_comprador != 'inversionista' and not criteria.get('es_inversionista'):
            return score, reasons

        rentabilidad = result.get('valor_rentabilidad_estimada', 0)
        if isinstance(rentabilidad, (int, float)) and rentabilidad >= 4.0:
            score += int(12 * pesos_perfil.get('rentabilidad', 1.0))
            reasons.append(f"Rentabilidad: {rentabilidad}%")

        return score, reasons

    def _score_total_amenidades(self, result, score, reasons):
        """Evalúa el total de amenidades."""
        total_amenidades = result.get('total_amenidades', 0)
        if not isinstance(total_amenidades, (int, float)):
            try:
                total_amenidades = int(total_amenidades)
            except:
                total_amenidades = 0

        if total_amenidades > 15:
            score += 4
            reasons.append(f"{total_amenidades} amenidades")

        return score, reasons
