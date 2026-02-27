#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Módulo de base de datos para guardar propiedades en Neon PostgreSQL
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql
import os
from dotenv import load_dotenv
from datetime import datetime

# Cargar variables de entorno
load_dotenv()


class DatabaseManager:
    """Clase para manejar la conexión y operaciones con la base de datos"""

    def __init__(self):
        """Inicializa la conexión a la base de datos"""
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL no está definida en el archivo .env")

        self.conn = None
        self.cursor = None

    def connect(self):
        """Establece conexión con la base de datos"""
        try:
            self.conn = psycopg2.connect(self.database_url)
            self.cursor = self.conn.cursor(cursor_factory=RealDictCursor)
            print("[OK] Conexion a Neon PostgreSQL establecida")
            return True
        except Exception as e:
            print(f"[ERROR] Error al conectar con la base de datos: {e}")
            return False

    def disconnect(self):
        """Cierra la conexión con la base de datos"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        print("[OK] Conexion cerrada")

    def __enter__(self):
        """Permite usar DatabaseManager con 'with' statement"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Cierra la conexión al salir del 'with' statement"""
        if exc_type is not None:
            # Hubo una excepción, hacer rollback
            if self.conn:
                self.conn.rollback()
        self.disconnect()
        return False  # No suprimir excepciones

    def create_tables(self):
        """Crea las tablas si no existen"""
        try:
            with open('schema.sql', 'r', encoding='utf-8') as f:
                schema = f.read()
            self.cursor.execute(schema)
            self.conn.commit()
            print("✅ Tablas creadas/verificadas correctamente")
            return True
        except Exception as e:
            print(f"❌ Error al crear tablas: {e}")
            self.conn.rollback()
            return False

    def insert_property(self, property_data):
        """
        Inserta una propiedad en la base de datos (con soporte para campos AI)

        Args:
            property_data (dict): Diccionario con los datos de la propiedad

        Returns:
            int: ID de la propiedad insertada o None si hubo error
        """
        try:
            # Campos básicos (siempre presentes)
            basic_fields = [
                'codigo_propiedad', 'fuente', 'url',
                'titulo', 'precio', 'precio_texto', 'tipo_propiedad', 'estado',
                'pais', 'departamento', 'ciudad', 'zona', 'direccion_completa',
                'latitud', 'longitud',
                'area_construida', 'habitaciones', 'banos', 'parqueaderos',
                'estrato', 'piso', 'ano_construccion', 'caracteristicas_adicionales',
                'administracion', 'predial',
                'amenidades_internas', 'amenidades_externas', 'total_amenidades',
                'asesor', 'telefono', 'inmobiliaria',
                'imagenes_urls', 'total_imagenes', 'imagen_principal',
                'imagenes_hd_count', 'imagenes_thumb_count',
                'descripcion', 'descripcion_length',
                'fecha_extraccion',
                # Campos de captación (quién envió la propiedad)
                'origen', 'agente_captador_telefono', 'grupo_origen', 'mensaje_original_grupo',
                # Tipo de negocio (Venta/Arriendo)
                'tipo_negocio'
            ]

            # Campos AI enriquecidos (opcionales)
            ai_fields = [
                'barrio_normalizado', 'distancia_metro_mas_cercano_m',
                'puntos_interes_cercanos', 'walkability_score',
                'precio_m2', 'precio_comparativo_zona', 'valor_rentabilidad_estimada',
                'segmento_mercado', 'descripcion_resumida', 'keywords_extraidas',
                'estilo_arquitectonico', 'estado_conservacion', 'target_buyer_profile',
                'amenidades_destacadas', 'amenidades_lujo', 'amenidades_familia',
                'amenidades_mascota_friendly', 'amenidades_seguridad',
                'overall_quality_score', 'recommended_for', 'unique_selling_points',
                'ventajas_competitivas', 'desventajas',
                'ai_analysis_version', 'ai_analysis_timestamp', 'ai_confidence_score',
                'ai_model_used', 'ai_processing_time_ms',
                'iluminacion_natural', 'ventilacion', 'vista', 'nivel_ruido',
                'accesibilidad_movilidad_reducida'
            ]

            # Determinar qué campos están presentes en property_data
            available_fields = [f for f in basic_fields + ai_fields if f in property_data]

            # Construir query dinámicamente
            fields_str = ', '.join(available_fields)
            placeholders = ', '.join([f'%({f})s' for f in available_fields])

            # Construir cláusula UPDATE para ON CONFLICT
            update_clauses = ', '.join([f'{f} = EXCLUDED.{f}' for f in available_fields if f != 'codigo_propiedad'])

            query = f"""
                INSERT INTO propiedades ({fields_str})
                VALUES ({placeholders})
                ON CONFLICT (codigo_propiedad)
                DO UPDATE SET
                    {update_clauses},
                    fecha_actualizacion = CURRENT_TIMESTAMP
                RETURNING id;
            """

            self.cursor.execute(query, property_data)
            result = self.cursor.fetchone()
            self.conn.commit()

            property_id = result['id'] if result else None
            codigo = property_data.get('codigo_propiedad', 'N/A')
            has_ai = 'ai_analysis_version' in property_data
            emoji = "🤖" if has_ai else "✅"
            print(f"{emoji} Propiedad {codigo} guardada en DB (ID: {property_id})")
            return property_id

        except psycopg2.IntegrityError as e:
            self.conn.rollback()
            print(f"⚠️  Propiedad ya existe: {property_data.get('codigo_propiedad')}")
            return None
        except Exception as e:
            self.conn.rollback()
            print(f"❌ Error al insertar propiedad: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_property_by_code(self, codigo_propiedad):
        """Obtiene una propiedad por su código"""
        try:
            query = "SELECT * FROM propiedades WHERE codigo_propiedad = %s"
            self.cursor.execute(query, (codigo_propiedad,))
            return self.cursor.fetchone()
        except Exception as e:
            print(f"❌ Error al obtener propiedad: {e}")
            return None

    def get_all_properties(self, limit=None, fuente=None):
        """
        Obtiene todas las propiedades

        Args:
            limit (int): Límite de resultados
            fuente (str): Filtrar por fuente (Wasi, Fincaraiz, etc.)
        """
        try:
            query = "SELECT * FROM propiedades WHERE activa = TRUE AND (tipo_negocio = 'Venta' OR tipo_negocio IS NULL)"
            params = []

            if fuente:
                query += " AND fuente = %s"
                params.append(fuente)

            query += " ORDER BY fecha_creacion DESC"

            if limit:
                query += " LIMIT %s"
                params.append(limit)

            self.cursor.execute(query, params)
            return self.cursor.fetchall()
        except Exception as e:
            print(f"❌ Error al obtener propiedades: {e}")
            return []

    def get_statistics(self):
        """Obtiene estadísticas de la base de datos"""
        try:
            stats = {}

            # Total de propiedades
            self.cursor.execute("SELECT COUNT(*) as total FROM propiedades WHERE activa = TRUE")
            stats['total_propiedades'] = self.cursor.fetchone()['total']

            # Por fuente
            self.cursor.execute("""
                SELECT fuente, COUNT(*) as total
                FROM propiedades
                WHERE activa = TRUE
                GROUP BY fuente
            """)
            stats['por_fuente'] = {row['fuente']: row['total'] for row in self.cursor.fetchall()}

            # Por ciudad
            self.cursor.execute("""
                SELECT ciudad, COUNT(*) as total
                FROM propiedades
                WHERE activa = TRUE AND ciudad IS NOT NULL
                GROUP BY ciudad
                ORDER BY total DESC
                LIMIT 10
            """)
            stats['por_ciudad'] = {row['ciudad']: row['total'] for row in self.cursor.fetchall()}

            # Precio promedio
            self.cursor.execute("""
                SELECT AVG(precio) as promedio, MIN(precio) as minimo, MAX(precio) as maximo
                FROM propiedades
                WHERE activa = TRUE AND precio IS NOT NULL
            """)
            precios = self.cursor.fetchone()
            stats['precios'] = {
                'promedio': float(precios['promedio']) if precios['promedio'] else 0,
                'minimo': precios['minimo'],
                'maximo': precios['maximo']
            }

            return stats
        except Exception as e:
            print(f"❌ Error al obtener estadísticas: {e}")
            return {}

    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()

    # =========================================================================
    # MÉTODOS ESPECÍFICOS DEL PROYECTO CUPIDO
    # =========================================================================

    def get_or_create_agente(self, telefono, nombre=None):
        """
        Obtiene un agente por teléfono o lo crea si no existe.
        Si el agente existe pero no tiene nombre y se proporciona uno, lo actualiza.

        Args:
            telefono (str): Teléfono en formato +57...
            nombre (str): Nombre opcional del agente

        Returns:
            dict: Datos del agente
        """
        try:
            # Intentar obtener el agente
            self.cursor.execute(
                "SELECT * FROM agentes WHERE telefono = %s",
                (telefono,)
            )
            agente = self.cursor.fetchone()

            if agente:
                # Si el agente existe pero no tiene nombre y se proporciona uno, actualizarlo
                if nombre and not agente.get('nombre'):
                    self.cursor.execute(
                        "UPDATE agentes SET nombre = %s WHERE telefono = %s RETURNING *",
                        (nombre, telefono)
                    )
                    agente = self.cursor.fetchone()
                    self.conn.commit()
                    print(f"✅ Agente actualizado con nombre: {telefono} -> {nombre}")
                return agente

            # Si no existe, crearlo
            self.cursor.execute(
                """
                INSERT INTO agentes (telefono, nombre)
                VALUES (%s, %s)
                RETURNING *
                """,
                (telefono, nombre)
            )
            agente = self.cursor.fetchone()
            self.conn.commit()
            print(f"✅ Agente creado: {telefono}" + (f" ({nombre})" if nombre else ""))
            return agente

        except Exception as e:
            self.conn.rollback()
            print(f"❌ Error al obtener/crear agente: {e}")
            return None

    def insert_solicitud_mercado(self, agente_telefono, query_original, origen,
                                  criterios_extraidos=None, grupo_origen=None,
                                  total_propiedades_encontradas=0, propiedades_ids=None):
        """
        Registra una solicitud de mercado (búsqueda de propiedad)

        Args:
            agente_telefono (str): Teléfono del agente
            query_original (str): Query original del agente
            origen (str): 'Grupo' o 'Chat_Privado'
            criterios_extraidos (dict): Criterios extraídos por Claude
            grupo_origen (str): ID del grupo si aplica
            total_propiedades_encontradas (int): Total de propiedades encontradas
            propiedades_ids (list): Lista de IDs de propiedades mostradas

        Returns:
            int: ID de la solicitud creada
        """
        try:
            # Obtener o crear agente
            agente = self.get_or_create_agente(agente_telefono)
            agente_id = agente['id'] if agente else None

            # Convertir criterios a JSON
            import json
            criterios_json = json.dumps(criterios_extraidos) if criterios_extraidos else None

            query = """
                INSERT INTO solicitudes_mercado (
                    agente_id, agente_telefono, query_original, origen,
                    criterios_extraidos, grupo_origen, total_propiedades_encontradas,
                    propiedades_ids
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id;
            """

            self.cursor.execute(query, (
                agente_id, agente_telefono, query_original, origen,
                criterios_json, grupo_origen, total_propiedades_encontradas,
                propiedades_ids or []
            ))

            result = self.cursor.fetchone()
            self.conn.commit()

            solicitud_id = result['id'] if result else None
            print(f"✅ Solicitud de mercado registrada (ID: {solicitud_id})")

            # Actualizar contador en agente
            if agente_id:
                self.cursor.execute(
                    "UPDATE agentes SET total_solicitudes_realizadas = total_solicitudes_realizadas + 1 WHERE id = %s",
                    (agente_id,)
                )
                self.conn.commit()

            return solicitud_id

        except Exception as e:
            self.conn.rollback()
            print(f"❌ Error al insertar solicitud de mercado: {e}")
            return None

    def insert_interaccion(self, agente_comprador_telefono, propiedad_id,
                           solicitud_mercado_id=None, agente_vendedor_telefono=None):
        """
        Registra una interacción (cuando un agente selecciona una propiedad)

        Args:
            agente_comprador_telefono (str): Teléfono del agente que busca
            propiedad_id (int): ID de la propiedad seleccionada
            solicitud_mercado_id (int): ID de la solicitud de mercado
            agente_vendedor_telefono (str): Teléfono del agente dueño (si aplica)

        Returns:
            int: ID de la interacción creada
        """
        try:
            # Obtener agente comprador
            agente_comprador = self.get_or_create_agente(agente_comprador_telefono)
            agente_comprador_id = agente_comprador['id'] if agente_comprador else None

            # Obtener agente vendedor si existe
            agente_vendedor_id = None
            if agente_vendedor_telefono:
                agente_vendedor = self.get_or_create_agente(agente_vendedor_telefono)
                agente_vendedor_id = agente_vendedor['id'] if agente_vendedor else None

            # Obtener origen de la propiedad
            self.cursor.execute(
                "SELECT origen FROM propiedades WHERE id = %s",
                (propiedad_id,)
            )
            prop_result = self.cursor.fetchone()
            tipo_origen = prop_result['origen'] if prop_result else 'Pulppo'

            query = """
                INSERT INTO interacciones (
                    agente_comprador_id, agente_comprador_telefono,
                    propiedad_id, solicitud_mercado_id,
                    agente_vendedor_id, agente_vendedor_telefono,
                    tipo_propiedad_origen
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id;
            """

            self.cursor.execute(query, (
                agente_comprador_id, agente_comprador_telefono,
                propiedad_id, solicitud_mercado_id,
                agente_vendedor_id, agente_vendedor_telefono,
                tipo_origen
            ))

            result = self.cursor.fetchone()
            self.conn.commit()

            interaccion_id = result['id'] if result else None
            print(f"✅ Interacción registrada (ID: {interaccion_id})")

            return interaccion_id

        except Exception as e:
            self.conn.rollback()
            print(f"❌ Error al insertar interacción: {e}")
            return None

    def update_interaccion_estado(self, interaccion_id, nuevo_estado, notas=None):
        """
        Actualiza el estado de una interacción

        Args:
            interaccion_id (int): ID de la interacción
            nuevo_estado (str): Nuevo estado
            notas (str): Notas opcionales
        """
        try:
            query = """
                UPDATE interacciones
                SET estado = %s, fecha_cambio_estado = CURRENT_TIMESTAMP, notas_estado = %s
                WHERE id = %s
            """
            self.cursor.execute(query, (nuevo_estado, notas, interaccion_id))
            self.conn.commit()
            print(f"✅ Estado de interacción {interaccion_id} actualizado a: {nuevo_estado}")
            return True
        except Exception as e:
            self.conn.rollback()
            print(f"❌ Error al actualizar estado: {e}")
            return False

    def log_evento(self, tipo_evento, agente_telefono=None, propiedad_id=None,
                   solicitud_id=None, interaccion_id=None, datos_evento=None,
                   mensaje_whatsapp=None, grupo_origen=None, resultado='Exitoso',
                   mensaje_error=None):
        """
        Registra un evento en el log para auditoría

        Args:
            tipo_evento (str): Tipo de evento
            agente_telefono (str): Teléfono del agente involucrado
            propiedad_id (int): ID de propiedad relacionada
            solicitud_id (int): ID de solicitud relacionada
            interaccion_id (int): ID de interacción relacionada
            datos_evento (dict): Datos adicionales del evento
            mensaje_whatsapp (str): Mensaje de WhatsApp relacionado
            grupo_origen (str): ID del grupo si aplica
            resultado (str): 'Exitoso', 'Error', 'Ignorado'
            mensaje_error (str): Mensaje de error si aplica
        """
        try:
            # Obtener agente_id si existe
            agente_id = None
            if agente_telefono:
                agente = self.get_or_create_agente(agente_telefono)
                agente_id = agente['id'] if agente else None

            # Convertir datos a JSON
            import json
            datos_json = json.dumps(datos_evento, ensure_ascii=False) if datos_evento else None

            query = """
                INSERT INTO eventos_log (
                    tipo_evento, agente_telefono, agente_id,
                    propiedad_id, solicitud_id, interaccion_id,
                    datos_evento, mensaje_whatsapp, grupo_origen,
                    resultado, mensaje_error
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """

            self.cursor.execute(query, (
                tipo_evento, agente_telefono, agente_id,
                propiedad_id, solicitud_id, interaccion_id,
                datos_json, mensaje_whatsapp, grupo_origen,
                resultado, mensaje_error
            ))

            self.conn.commit()
            return True

        except Exception as e:
            self.conn.rollback()
            print(f"⚠️  Error al registrar evento en log: {e}")
            return False

    def get_propiedad_con_agente(self, propiedad_id):
        """
        Obtiene una propiedad con información del agente captador

        Args:
            propiedad_id (int): ID de la propiedad

        Returns:
            dict: Datos de la propiedad con información del agente
        """
        try:
            self.cursor.execute(
                "SELECT * FROM v_propiedades_con_agente WHERE id = %s",
                (propiedad_id,)
            )
            return self.cursor.fetchone()
        except Exception as e:
            print(f"❌ Error al obtener propiedad con agente: {e}")
            return None

    def get_config_valor(self, clave, default=None):
        """
        Obtiene un valor de configuración del sistema

        Args:
            clave (str): Clave de configuración
            default: Valor por defecto si no existe

        Returns:
            str: Valor de la configuración
        """
        try:
            self.cursor.execute(
                "SELECT valor FROM configuracion_sistema WHERE clave = %s",
                (clave,)
            )
            result = self.cursor.fetchone()
            return result['valor'] if result else default
        except Exception as e:
            print(f"⚠️  Error al obtener configuración: {e}")
            return default


# Función helper para uso rápido
def save_properties_to_db(properties_list):
    """
    Guarda una lista de propiedades en la base de datos

    Args:
        properties_list (list): Lista de diccionarios con datos de propiedades

    Returns:
        tuple: (exitosas, fallidas)
    """
    exitosas = 0
    fallidas = 0

    with DatabaseManager() as db:
        if not db.create_tables():
            print("❌ No se pudieron crear las tablas")
            return 0, len(properties_list)

        for prop in properties_list:
            if db.insert_property(prop):
                exitosas += 1
            else:
                fallidas += 1

    return exitosas, fallidas
