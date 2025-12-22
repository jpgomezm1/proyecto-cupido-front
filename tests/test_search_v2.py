#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests para el Sistema de Búsqueda v2.0
Valida los filtros duros de precio, perfiles de comprador, y nueva lógica de ranking
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import patch, MagicMock
from src.core.search_config import (
    get_segmento_precio,
    get_tolerancia_precio,
    calcular_rango_precio,
    detectar_perfil_comprador,
    get_zonas_expandidas,
    SEGMENTOS_PRECIO_COLOMBIA
)


class TestSearchConfig(unittest.TestCase):
    """Tests para la configuración de búsqueda Colombia"""

    def test_segmento_precio_vis(self):
        """VIS: hasta $200M"""
        self.assertEqual(get_segmento_precio(150_000_000), 'vis')
        self.assertEqual(get_segmento_precio(199_000_000), 'vis')

    def test_segmento_precio_accesible(self):
        """Accesible: $200M - $400M"""
        self.assertEqual(get_segmento_precio(250_000_000), 'accesible')
        self.assertEqual(get_segmento_precio(399_000_000), 'accesible')

    def test_segmento_precio_medio(self):
        """Medio: $400M - $700M"""
        self.assertEqual(get_segmento_precio(500_000_000), 'medio')
        self.assertEqual(get_segmento_precio(699_000_000), 'medio')

    def test_segmento_precio_medio_alto(self):
        """Medio-Alto: $700M - $1.200M"""
        self.assertEqual(get_segmento_precio(800_000_000), 'medio_alto')
        self.assertEqual(get_segmento_precio(1_000_000_000), 'medio_alto')
        self.assertEqual(get_segmento_precio(1_199_000_000), 'medio_alto')

    def test_segmento_precio_premium(self):
        """Premium: $1.200M - $2.500M"""
        self.assertEqual(get_segmento_precio(1_500_000_000), 'premium')
        self.assertEqual(get_segmento_precio(2_000_000_000), 'premium')

    def test_segmento_precio_lujo(self):
        """Lujo: $2.500M+"""
        self.assertEqual(get_segmento_precio(3_000_000_000), 'lujo')
        self.assertEqual(get_segmento_precio(5_000_000_000), 'lujo')


class TestRangoPrecio(unittest.TestCase):
    """Tests para el cálculo de rango de precio"""

    def test_rango_precio_1000M(self):
        """Presupuesto de $1.000M debe generar rango coherente"""
        precio_min, precio_max = calcular_rango_precio(1_000_000_000)

        # Con tolerancia de 15% para medio_alto:
        # precio_min = 1000M * 0.85 = 850M
        # precio_max = 1000M * 1.075 = 1075M (mitad de tolerancia arriba)
        self.assertGreaterEqual(precio_min, 800_000_000)
        self.assertLessEqual(precio_min, 900_000_000)
        self.assertGreaterEqual(precio_max, 1_000_000_000)
        self.assertLessEqual(precio_max, 1_100_000_000)

        # CRÍTICO: Una propiedad de $350M NUNCA debe estar en este rango
        self.assertGreater(precio_min, 350_000_000)

    def test_rango_precio_500M(self):
        """Presupuesto de $500M debe generar rango coherente"""
        precio_min, precio_max = calcular_rango_precio(500_000_000)

        # Una propiedad de $350M puede estar en rango (está al 70%)
        # Una propiedad de $100M NO debe estar en rango
        self.assertGreater(precio_min, 100_000_000)
        self.assertLess(precio_max, 600_000_000)

    def test_rango_no_incluye_segmento_diferente(self):
        """Con presupuesto de $1.000M, $350M NO debe estar en rango"""
        precio_min, precio_max = calcular_rango_precio(1_000_000_000)

        # $350M es segmento accesible, $1.000M es medio_alto
        # NO deben mezclarse
        propiedad_350M = 350_000_000
        self.assertFalse(
            precio_min <= propiedad_350M <= precio_max,
            f"Propiedad de $350M no debe estar en rango [{precio_min/1e6:.0f}M - {precio_max/1e6:.0f}M]"
        )


class TestPerfilComprador(unittest.TestCase):
    """Tests para detección de perfil de comprador"""

    def test_detectar_perfil_senior(self):
        """Detectar perfil senior por keywords"""
        query = "Busco apartamento persona mayor primer piso"
        perfil = detectar_perfil_comprador(query, {'piso': 1})
        self.assertEqual(perfil, 'senior')

    def test_detectar_perfil_familia(self):
        """Detectar perfil familia por keywords"""
        query = "Apartamento para familia con niños cerca a colegios"
        perfil = detectar_perfil_comprador(query, {})
        self.assertEqual(perfil, 'familia')

    def test_detectar_perfil_inversionista(self):
        """Detectar perfil inversionista por keywords"""
        query = "Busco para inversión con buena rentabilidad"
        perfil = detectar_perfil_comprador(query, {})
        self.assertEqual(perfil, 'inversionista')

    def test_detectar_perfil_por_criterios(self):
        """Detectar perfil senior por criterio de piso 1"""
        query = "Busco apartamento"  # Sin keywords
        perfil = detectar_perfil_comprador(query, {'piso': 1})
        self.assertEqual(perfil, 'senior')


class TestZonasExpandidas(unittest.TestCase):
    """Tests para expansión de zonas"""

    def test_zonas_expandidas_laureles(self):
        """Laureles debe expandir a zonas similares"""
        zonas = get_zonas_expandidas('Laureles')
        self.assertIn('Laureles', zonas)
        # Debe incluir zonas cercanas
        self.assertTrue(len(zonas) > 1)

    def test_zona_original_siempre_primero(self):
        """La zona original debe estar siempre primero"""
        zonas = get_zonas_expandidas('Poblado')
        self.assertEqual(zonas[0], 'Poblado')


class TestFiltrosDuros(unittest.TestCase):
    """Tests para verificar que los filtros duros funcionan"""

    def test_criterios_enriquecidos(self):
        """Verificar que los criterios se enriquecen correctamente"""
        # Simular criterios extraídos
        criteria = {
            'precio_max': 1_000_000_000,
            'ubicaciones': ['Laureles']
        }

        # Simular enriquecimiento
        if criteria.get('precio_max') and not criteria.get('precio_min'):
            precio_min, precio_max_ajustado = calcular_rango_precio(criteria['precio_max'])
            criteria['precio_min_implicito'] = precio_min
            criteria['precio_max_ajustado'] = precio_max_ajustado
            criteria['segmento_precio'] = get_segmento_precio(criteria['precio_max'])

        # Verificar que se calcularon correctamente
        self.assertIn('precio_min_implicito', criteria)
        self.assertIn('precio_max_ajustado', criteria)
        self.assertIn('segmento_precio', criteria)
        self.assertEqual(criteria['segmento_precio'], 'medio_alto')

        # El precio mínimo implícito debe excluir propiedades de $350M
        self.assertGreater(criteria['precio_min_implicito'], 350_000_000)


class TestCasoRealProblema(unittest.TestCase):
    """Test del caso real reportado: presupuesto $1.000M mostrando propiedades de $350M"""

    def test_caso_real_precio_1000M(self):
        """
        Caso real: Usuario busca con presupuesto $1.000M
        Sistema NO debe mostrar propiedades de $350M
        """
        presupuesto = 1_000_000_000
        propiedad_incorrecta = 350_000_000

        # Calcular rango con nueva lógica
        precio_min, precio_max = calcular_rango_precio(presupuesto)

        # La propiedad de $350M NO debe estar en el rango
        esta_en_rango = precio_min <= propiedad_incorrecta <= precio_max

        self.assertFalse(
            esta_en_rango,
            f"BUG: Propiedad de $350M está en rango [{precio_min/1e6:.0f}M - {precio_max/1e6:.0f}M] "
            f"cuando presupuesto es $1.000M"
        )

        # El rango debe estar aproximadamente en $850M - $1.075M
        self.assertGreaterEqual(precio_min, 800_000_000)
        self.assertLessEqual(precio_max, 1_200_000_000)


if __name__ == '__main__':
    print("=" * 60)
    print("TESTS DEL SISTEMA DE BÚSQUEDA v2.0")
    print("=" * 60)
    print()

    # Ejecutar tests
    unittest.main(verbosity=2)
