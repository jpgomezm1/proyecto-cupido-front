#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Testing para el Sistema de Validación Automática
Prueba la lógica de validación sin hacer requests reales
"""

import sys
import os
from datetime import datetime
from dotenv import load_dotenv
from database import DatabaseManager

load_dotenv()


class TestValidacion:
    """
    Suite de tests para validar el sistema de validación automática
    """

    def __init__(self):
        self.db = DatabaseManager()
        self.test_results = []
        self.test_propiedad_id = None

    def setup(self):
        """Prepara el entorno de testing"""
        print("\n" + "="*80)
        print("  SETUP - PREPARANDO ENTORNO DE TESTING")
        print("="*80)

        self.db.connect()

        # Crear propiedad de prueba si no existe
        self.db.cursor.execute("""
            SELECT id FROM propiedades
            WHERE codigo_propiedad = 'TEST_VALIDACION_001'
        """)

        result = self.db.cursor.fetchone()

        if result:
            self.test_propiedad_id = result['id']
            print(f"[OK] Usando propiedad de prueba existente: {self.test_propiedad_id}")
        else:
            # Crear nueva propiedad de prueba
            self.db.cursor.execute("""
                INSERT INTO propiedades (
                    codigo_propiedad, fuente, titulo, tipo_propiedad,
                    precio, ciudad, url, activa, fecha_extraccion
                ) VALUES (
                    'TEST_VALIDACION_001', 'Tu360_Captado', 'Apartamento Test Validacion',
                    'Apartamento', 300000000, 'Medellin',
                    'https://httpstat.us/200', TRUE, CURRENT_TIMESTAMP
                )
                RETURNING id
            """)

            result = self.db.cursor.fetchone()
            self.test_propiedad_id = result['id']
            self.db.conn.commit()

            print(f"[OK] Propiedad de prueba creada: {self.test_propiedad_id}")

        print("="*80 + "\n")

    def teardown(self):
        """Limpia después de los tests"""
        print("\n" + "="*80)
        print("  TEARDOWN - LIMPIANDO ENTORNO DE TESTING")
        print("="*80)

        # NO eliminamos la propiedad de prueba para poder revisar resultados
        # Si quieres limpiar, descomenta las siguientes líneas:
        # self.db.cursor.execute("DELETE FROM propiedades WHERE id = %s", (self.test_propiedad_id,))
        # self.db.conn.commit()
        # print(f"[OK] Propiedad de prueba eliminada: {self.test_propiedad_id}")

        self.db.disconnect()
        print("="*80 + "\n")

    def record_test(self, test_name: str, passed: bool, message: str = ""):
        """Registra el resultado de un test"""
        status = "[PASS]" if passed else "[FAIL]"
        result = {
            'test': test_name,
            'passed': passed,
            'message': message,
            'timestamp': datetime.now()
        }
        self.test_results.append(result)

        print(f"\n{status} {test_name}")
        if message:
            print(f"      {message}")

    def get_propiedad_estado(self):
        """Obtiene el estado actual de la propiedad de prueba"""
        # Check if validation columns exist
        self.db.cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'propiedades'
            AND column_name IN ('validaciones_fallidas_consecutivas', 'validacion_bloqueada', 'fecha_ultima_validacion')
        """)

        existing_cols = [row['column_name'] for row in self.db.cursor.fetchall()]
        has_validation_cols = len(existing_cols) == 3

        if has_validation_cols:
            self.db.cursor.execute("""
                SELECT activa, validaciones_fallidas_consecutivas, validacion_bloqueada,
                       fecha_ultima_validacion
                FROM propiedades
                WHERE id = %s
            """, (self.test_propiedad_id,))
        else:
            # Fallback if validation columns don't exist yet
            self.db.cursor.execute("""
                SELECT activa
                FROM propiedades
                WHERE id = %s
            """, (self.test_propiedad_id,))
            result = self.db.cursor.fetchone()
            if result:
                result['validaciones_fallidas_consecutivas'] = 0
                result['validacion_bloqueada'] = False
                result['fecha_ultima_validacion'] = None

        return self.db.cursor.fetchone()

    def reset_propiedad(self):
        """Resetea la propiedad de prueba a estado inicial"""
        # Check if validation columns exist
        self.db.cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'propiedades'
            AND column_name IN ('validaciones_fallidas_consecutivas', 'validacion_bloqueada', 'fecha_ultima_validacion')
        """)

        existing_cols = [row['column_name'] for row in self.db.cursor.fetchall()]
        has_validation_cols = len(existing_cols) == 3

        if has_validation_cols:
            self.db.cursor.execute("""
                UPDATE propiedades
                SET activa = TRUE,
                    validaciones_fallidas_consecutivas = 0,
                    validacion_bloqueada = FALSE,
                    fecha_ultima_validacion = NULL
                WHERE id = %s
            """, (self.test_propiedad_id,))
        else:
            self.db.cursor.execute("""
                UPDATE propiedades
                SET activa = TRUE
                WHERE id = %s
            """, (self.test_propiedad_id,))

        self.db.conn.commit()

    # ================================================================================
    # TESTS
    # ================================================================================

    def test_01_propiedad_existe_200(self):
        """Test 1: Propiedad existe (HTTP 200) - debe mantenerse activa"""
        self.reset_propiedad()

        from validar_propiedades_activas import PropertyValidator
        validator = PropertyValidator()

        estado_antes = self.get_propiedad_estado()

        # Simular validación exitosa (200)
        propiedad = {
            'id': self.test_propiedad_id,
            'activa': True,
            'validaciones_fallidas_consecutivas': 0
        }

        accion = validator.procesar_resultado_validacion(self.db, propiedad, 200, 'OK')
        self.db.conn.commit()

        estado_despues = self.get_propiedad_estado()

        passed = (
            accion == 'mantener_activa' and
            estado_despues['activa'] == True and
            estado_despues['validaciones_fallidas_consecutivas'] == 0
        )

        self.record_test(
            'Propiedad existe (200)',
            passed,
            f"Accion: {accion}, Activa: {estado_despues['activa']}, Fallos: {estado_despues['validaciones_fallidas_consecutivas']}"
        )

    def test_02_primer_fallo_404(self):
        """Test 2: Primer fallo 404 - debe incrementar contador pero mantener activa"""
        self.reset_propiedad()

        from validar_propiedades_activas import PropertyValidator
        validator = PropertyValidator()

        propiedad = {
            'id': self.test_propiedad_id,
            'activa': True,
            'validaciones_fallidas_consecutivas': 0
        }

        accion = validator.procesar_resultado_validacion(self.db, propiedad, 404, 'Not Found')
        self.db.conn.commit()

        estado = self.get_propiedad_estado()

        passed = (
            accion == 'mantener_activa' and
            estado['activa'] == True and
            estado['validaciones_fallidas_consecutivas'] == 1
        )

        self.record_test(
            'Primer fallo 404',
            passed,
            f"Accion: {accion}, Activa: {estado['activa']}, Fallos: {estado['validaciones_fallidas_consecutivas']}"
        )

    def test_03_segundo_fallo_404_desactivar(self):
        """Test 3: Segundo fallo 404 consecutivo - debe desactivar"""
        self.reset_propiedad()

        from validar_propiedades_activas import PropertyValidator
        validator = PropertyValidator()

        # Simular que ya tiene 1 fallo
        self.db.cursor.execute("""
            UPDATE propiedades
            SET validaciones_fallidas_consecutivas = 1
            WHERE id = %s
        """, (self.test_propiedad_id,))
        self.db.conn.commit()

        propiedad = {
            'id': self.test_propiedad_id,
            'activa': True,
            'validaciones_fallidas_consecutivas': 1
        }

        accion = validator.procesar_resultado_validacion(self.db, propiedad, 404, 'Not Found')
        self.db.conn.commit()

        estado = self.get_propiedad_estado()

        passed = (
            accion == 'desactivar' and
            estado['activa'] == False and
            estado['validaciones_fallidas_consecutivas'] == 2
        )

        self.record_test(
            'Segundo fallo 404 (desactivar)',
            passed,
            f"Accion: {accion}, Activa: {estado['activa']}, Fallos: {estado['validaciones_fallidas_consecutivas']}"
        )

    def test_04_410_desactivar_inmediato(self):
        """Test 4: HTTP 410 (Gone) - debe desactivar inmediatamente"""
        self.reset_propiedad()

        from validar_propiedades_activas import PropertyValidator
        validator = PropertyValidator()

        propiedad = {
            'id': self.test_propiedad_id,
            'activa': True,
            'validaciones_fallidas_consecutivas': 0
        }

        accion = validator.procesar_resultado_validacion(self.db, propiedad, 410, 'Gone')
        self.db.conn.commit()

        estado = self.get_propiedad_estado()

        passed = (
            accion == 'desactivar' and
            estado['activa'] == False
        )

        self.record_test(
            'HTTP 410 Gone (desactivar inmediato)',
            passed,
            f"Accion: {accion}, Activa: {estado['activa']}"
        )

    def test_05_reactivacion_automatica(self):
        """Test 5: Reactivación automática - propiedad inactiva vuelve a estar disponible"""
        self.reset_propiedad()

        from validar_propiedades_activas import PropertyValidator
        validator = PropertyValidator()

        # Simular que la propiedad está inactiva
        self.db.cursor.execute("""
            UPDATE propiedades
            SET activa = FALSE,
                validaciones_fallidas_consecutivas = 2
            WHERE id = %s
        """, (self.test_propiedad_id,))
        self.db.conn.commit()

        propiedad = {
            'id': self.test_propiedad_id,
            'activa': False,
            'validaciones_fallidas_consecutivas': 2
        }

        # La URL ahora responde 200
        accion = validator.procesar_resultado_validacion(self.db, propiedad, 200, 'OK')
        self.db.conn.commit()

        estado = self.get_propiedad_estado()

        passed = (
            accion == 'reactivar' and
            estado['activa'] == True and
            estado['validaciones_fallidas_consecutivas'] == 0
        )

        self.record_test(
            'Reactivación automática',
            passed,
            f"Accion: {accion}, Activa: {estado['activa']}, Fallos: {estado['validaciones_fallidas_consecutivas']}"
        )

    def test_06_bloqueo_403(self):
        """Test 6: HTTP 403 (Forbidden) - debe marcar como bloqueada"""
        self.reset_propiedad()

        from validar_propiedades_activas import PropertyValidator
        validator = PropertyValidator()

        propiedad = {
            'id': self.test_propiedad_id,
            'activa': True,
            'validaciones_fallidas_consecutivas': 0
        }

        accion = validator.procesar_resultado_validacion(self.db, propiedad, 403, 'Forbidden')
        self.db.conn.commit()

        estado = self.get_propiedad_estado()

        passed = (
            accion == 'bloquear' and
            estado['validacion_bloqueada'] == True
        )

        self.record_test(
            'HTTP 403 (bloqueo)',
            passed,
            f"Accion: {accion}, Bloqueada: {estado['validacion_bloqueada']}"
        )

    def test_07_error_temporal_500(self):
        """Test 7: HTTP 500 (Server Error) - no debe contar como fallo"""
        self.reset_propiedad()

        from validar_propiedades_activas import PropertyValidator
        validator = PropertyValidator()

        propiedad = {
            'id': self.test_propiedad_id,
            'activa': True,
            'validaciones_fallidas_consecutivas': 0
        }

        accion = validator.procesar_resultado_validacion(self.db, propiedad, 500, 'Internal Server Error')
        self.db.conn.commit()

        estado = self.get_propiedad_estado()

        passed = (
            accion == 'error_temporal' and
            estado['activa'] == True and
            estado['validaciones_fallidas_consecutivas'] == 0
        )

        self.record_test(
            'HTTP 500 (error temporal)',
            passed,
            f"Accion: {accion}, Activa: {estado['activa']}, Fallos: {estado['validaciones_fallidas_consecutivas']}"
        )

    def test_08_filtro_busqueda(self):
        """Test 8: Verificar que búsqueda filtra propiedades inactivas"""
        # Desactivar propiedad de prueba
        self.db.cursor.execute("""
            UPDATE propiedades
            SET activa = FALSE
            WHERE id = %s
        """, (self.test_propiedad_id,))
        self.db.conn.commit()

        # Buscar la propiedad
        self.db.cursor.execute("""
            SELECT id FROM propiedades
            WHERE id = %s AND activa = TRUE
        """, (self.test_propiedad_id,))

        result = self.db.cursor.fetchone()

        # Reactivar para no afectar otros tests
        self.db.cursor.execute("""
            UPDATE propiedades
            SET activa = TRUE
            WHERE id = %s
        """, (self.test_propiedad_id,))
        self.db.conn.commit()

        passed = (result is None)

        self.record_test(
            'Filtro de búsqueda (activa = TRUE)',
            passed,
            f"Propiedad inactiva {'NO' if passed else 'SÍ'} aparece en búsqueda"
        )

    def print_summary(self):
        """Imprime resumen de todos los tests"""
        print("\n" + "="*80)
        print("  RESUMEN DE TESTS")
        print("="*80)

        total = len(self.test_results)
        passed = sum(1 for r in self.test_results if r['passed'])
        failed = total - passed

        print(f"Total tests:     {total}")
        print(f"Pasados:         {passed}")
        print(f"Fallados:        {failed}")
        print(f"Tasa de éxito:   {(passed/total*100):.1f}%")

        if failed > 0:
            print("\nTests fallados:")
            for r in self.test_results:
                if not r['passed']:
                    print(f"  - {r['test']}: {r['message']}")

        print("="*80 + "\n")

        return failed == 0


def main():
    """Función principal"""
    test_suite = TestValidacion()

    try:
        test_suite.setup()

        # Ejecutar todos los tests
        test_suite.test_01_propiedad_existe_200()
        test_suite.test_02_primer_fallo_404()
        test_suite.test_03_segundo_fallo_404_desactivar()
        test_suite.test_04_410_desactivar_inmediato()
        test_suite.test_05_reactivacion_automatica()
        test_suite.test_06_bloqueo_403()
        test_suite.test_07_error_temporal_500()
        test_suite.test_08_filtro_busqueda()

        # Resumen
        all_passed = test_suite.print_summary()

        if all_passed:
            print("\n✅ TODOS LOS TESTS PASARON\n")
            return 0
        else:
            print("\n❌ ALGUNOS TESTS FALLARON\n")
            return 1

    except Exception as e:
        print(f"\n❌ Error durante testing: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        test_suite.teardown()


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
