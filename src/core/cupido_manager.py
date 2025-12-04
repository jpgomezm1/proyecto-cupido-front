#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cupido Manager - Lógica central del Proyecto Cupido
Maneja detección de mensajes, captación, solicitudes y trazabilidad
"""

import re
import os
from typing import Dict, List, Tuple, Optional
from src.db.database import DatabaseManager
from dotenv import load_dotenv

load_dotenv()


class CupidoManager:
    """
    Clase principal para manejar la lógica del Proyecto Cupido
    """

    def __init__(self):
        """Inicializa el manager"""
        self.db = None

        # ID del grupo de Cupido (se obtiene de la configuración)
        self.grupo_cupido_id = os.getenv('GRUPO_CUPIDO_ID', '')

        # Contacto principal - Hernán Ríos (para TODAS las propiedades)
        self.contacto_principal = '+573187771000'
        self.nombre_contacto = 'Hernán Ríos'

    def _get_db(self):
        """Obtiene o crea conexión a la base de datos"""
        # Siempre crear nueva conexión para evitar problemas de conexión cerrada
        db = DatabaseManager()
        db.connect()
        return db

    def close(self):
        """Cierra la conexión a la base de datos"""
        if self.db:
            self.db.disconnect()
            self.db = None

    # =========================================================================
    # DETECCIÓN DE TIPO DE MENSAJE
    # =========================================================================

    def detectar_tipo_mensaje(self, mensaje: str, sender: str, is_group: bool) -> Dict:
        """
        Detecta el tipo de mensaje recibido

        Args:
            mensaje (str): Contenido del mensaje
            sender (str): Teléfono del remitente
            is_group (bool): Si el mensaje es de un grupo

        Returns:
            dict: {
                'tipo': str,  # 'solicitud_mercado', 'captacion_wasi', 'chat_normal', 'comando'
                'confianza': float,  # 0.0 - 1.0
                'data': dict  # Datos adicionales según el tipo
            }
        """
        mensaje_lower = mensaje.lower().strip()

        # 1. Detectar si es captación (tiene link de Wasi)
        wasi_link = self._extraer_link_wasi(mensaje)
        if wasi_link:
            return {
                'tipo': 'captacion_wasi',
                'confianza': 1.0,
                'data': {
                    'url': wasi_link,
                    'mensaje_completo': mensaje
                }
            }

        # 2. Detectar si es solicitud de mercado (búsqueda de propiedad)
        if self._es_solicitud_mercado(mensaje):
            return {
                'tipo': 'solicitud_mercado',
                'confianza': 0.9,
                'data': {
                    'query': mensaje
                }
            }

        # 3. Si no es ninguno de los anteriores, es chat normal
        return {
            'tipo': 'chat_normal',
            'confianza': 0.5,
            'data': {}
        }

    def _extraer_link_wasi(self, mensaje: str) -> Optional[str]:
        """
        Extrae link de Wasi del mensaje

        Args:
            mensaje (str): Mensaje completo

        Returns:
            str: URL de Wasi o None
        """
        # Patrones de URLs de Wasi
        patterns = [
            r'https?://[a-zA-Z0-9.-]*wasi\.co[^\s]*',
            r'https?://[a-zA-Z0-9.-]*\.wasi\.co[^\s]*',
            r'wasi\.co/[^\s]*'
        ]

        for pattern in patterns:
            match = re.search(pattern, mensaje, re.IGNORECASE)
            if match:
                url = match.group(0)
                # Asegurar que tenga https://
                if not url.startswith('http'):
                    url = 'https://' + url
                return url

        return None

    def _es_solicitud_mercado(self, mensaje: str) -> bool:
        """
        Determina si el mensaje es una solicitud de mercado (búsqueda de propiedad)

        Args:
            mensaje (str): Mensaje a evaluar

        Returns:
            bool: True si es solicitud de mercado
        """
        mensaje_lower = mensaje.lower().strip()

        # Debe tener longitud mínima
        if len(mensaje_lower) < 15:
            return False

        # Keywords que indican solicitud de mercado
        keywords_solicitud = [
            'busco', 'buscar', 'quiero', 'necesito', 'me interesa',
            'requiero', 'estoy buscando', 'cliente busca', 'cliente quiere'
        ]

        # Keywords de propiedades
        keywords_propiedad = [
            'apto', 'apartamento', 'casa', 'penthouse', 'duplex',
            'habitacion', 'habitaciones', 'alcoba', 'alcobas', 'cuarto',
            'millones', 'millon', 'presupuesto', 'precio',
            'laureles', 'poblado', 'envigado', 'belen', 'sabaneta',
            'parqueadero', 'balcon', 'terraza'
        ]

        # Debe contener al menos una palabra de solicitud Y una de propiedad
        tiene_solicitud = any(kw in mensaje_lower for kw in keywords_solicitud)
        tiene_propiedad = any(kw in mensaje_lower for kw in keywords_propiedad)

        return tiene_solicitud and tiene_propiedad

    # =========================================================================
    # PROCESAMIENTO DE CAPTACIÓN DE PROPIEDADES
    # =========================================================================

    def procesar_captacion_wasi(self, url_wasi: str, agente_telefono: str,
                                 mensaje_completo: str, grupo_id: str = None) -> Dict:
        """
        Procesa la captación de una propiedad desde un link de Wasi

        Args:
            url_wasi (str): URL de la propiedad en Wasi
            agente_telefono (str): Teléfono del agente que compartió
            mensaje_completo (str): Mensaje completo del grupo
            grupo_id (str): ID del grupo de WhatsApp

        Returns:
            dict: Resultado del procesamiento
        """
        print(f"\n🏠 Procesando captación de Wasi...")
        print(f"   URL: {url_wasi}")
        print(f"   Agente: {agente_telefono}")

        try:
            # 1. Scrappear la propiedad de Wasi
            from src.scrapers.wasi import WasiScraper
            scraper = WasiScraper()

            propiedad_data = scraper.extract_property_data(url_wasi)

            if not propiedad_data:
                return {
                    'success': False,
                    'error': 'No se pudo scrappear la propiedad'
                }

            # 2. Agregar información del agente captador
            propiedad_data['agente_captador_telefono'] = agente_telefono
            propiedad_data['mensaje_original_grupo'] = mensaje_completo
            propiedad_data['origen'] = 'Wasi_Captado'
            propiedad_data['grupo_origen'] = grupo_id or self.grupo_cupido_id
            propiedad_data['contacto_responsable'] = agente_telefono

            print(f"   [OK] Telefono del agente captador guardado: {agente_telefono}")
            print(f"   [OK] Origen: Wasi_Captado | Grupo: {grupo_id or self.grupo_cupido_id}")

            # 3. Guardar en base de datos
            db = self._get_db()

            try:
                # Obtener o crear agente
                agente = db.get_or_create_agente(agente_telefono)
                if agente:
                    propiedad_data['agente_captador_id'] = agente['id']

                # Insertar propiedad
                propiedad_id = db.insert_property(propiedad_data)

                if propiedad_id:
                    # Actualizar contador del agente
                    if agente:
                        db.cursor.execute(
                            "UPDATE agentes SET total_propiedades_captadas = total_propiedades_captadas + 1 WHERE id = %s",
                            (agente['id'],)
                        )
                        db.conn.commit()

                    # Log del evento
                    db.log_evento(
                        tipo_evento='Propiedad_Captada',
                        agente_telefono=agente_telefono,
                        propiedad_id=propiedad_id,
                        datos_evento={
                            'url': url_wasi,
                            'codigo': propiedad_data.get('codigo_propiedad'),
                            'titulo': propiedad_data.get('titulo')
                        },
                        mensaje_whatsapp=mensaje_completo,
                        grupo_origen=grupo_id,
                        resultado='Exitoso'
                    )

                    return {
                        'success': True,
                        'propiedad_id': propiedad_id,
                        'codigo': propiedad_data.get('codigo_propiedad'),
                        'titulo': propiedad_data.get('titulo')
                    }

                return {
                    'success': False,
                    'error': 'No se pudo guardar en la base de datos'
                }
            finally:
                db.disconnect()

        except Exception as e:
            print(f"❌ Error en captación: {e}")

            # Log del error
            db = self._get_db()
            try:
                db.log_evento(
                    tipo_evento='Propiedad_Captada',
                    agente_telefono=agente_telefono,
                    datos_evento={'url': url_wasi},
                    mensaje_whatsapp=mensaje_completo,
                    grupo_origen=grupo_id,
                    resultado='Error',
                    mensaje_error=str(e)
                )
            finally:
                db.disconnect()

            return {
                'success': False,
                'error': str(e)
            }

    # =========================================================================
    # PROCESAMIENTO DE SOLICITUDES DE MERCADO
    # =========================================================================

    def procesar_solicitud_mercado(self, query: str, agente_telefono: str,
                                     origen: str, grupo_id: str = None) -> Dict:
        """
        Procesa una solicitud de mercado (búsqueda de propiedad)

        Args:
            query (str): Query de búsqueda del agente
            agente_telefono (str): Teléfono del agente
            origen (str): 'Grupo' o 'Chat_Privado'
            grupo_id (str): ID del grupo si aplica

        Returns:
            dict: Resultado con propiedades encontradas
        """
        print(f"\n🔍 Procesando solicitud de mercado...")
        print(f"   Query: {query[:50]}...")
        print(f"   Agente: {agente_telefono}")
        print(f"   Origen: {origen}")

        try:
            # 1. Realizar búsqueda de propiedades
            from busqueda_propiedades import PropertySearchAgent
            agent = PropertySearchAgent()

            result = agent.search(query, limit=5)

            if not result['success']:
                return {
                    'success': False,
                    'error': result.get('error', 'Error en la búsqueda')
                }

            # 2. Registrar solicitud en base de datos
            db = self._get_db()

            try:
                propiedades_ids = [p['id'] for p in result['results']]

                solicitud_id = db.insert_solicitud_mercado(
                    agente_telefono=agente_telefono,
                    query_original=query,
                    origen=origen,
                    criterios_extraidos=result.get('criteria'),
                    grupo_origen=grupo_id if origen == 'Grupo' else None,
                    total_propiedades_encontradas=result['total_found'],
                    propiedades_ids=propiedades_ids
                )

                # 3. Log del evento
                db.log_evento(
                    tipo_evento='Solicitud_Mercado',
                    agente_telefono=agente_telefono,
                    solicitud_id=solicitud_id,
                    datos_evento={
                        'query': query,
                        'total_encontradas': result['total_found'],
                        'criterios': result.get('criteria')
                    },
                    mensaje_whatsapp=query,
                    grupo_origen=grupo_id if origen == 'Grupo' else None,
                    resultado='Exitoso'
                )

                return {
                    'success': True,
                    'solicitud_id': solicitud_id,
                    'propiedades': result['results'],
                    'total_found': result['total_found'],
                    'criteria': result.get('criteria')
                }
            finally:
                db.disconnect()

        except Exception as e:
            print(f"❌ Error en solicitud de mercado: {e}")

            db = self._get_db()
            try:
                db.log_evento(
                    tipo_evento='Solicitud_Mercado',
                    agente_telefono=agente_telefono,
                    datos_evento={'query': query},
                    mensaje_whatsapp=query,
                    grupo_origen=grupo_id if origen == 'Grupo' else None,
                    resultado='Error',
                    mensaje_error=str(e)
                )
            finally:
                db.disconnect()

            return {
                'success': False,
                'error': str(e)
            }

    # =========================================================================
    # PROCESAMIENTO DE SELECCIÓN DE PROPIEDADES
    # =========================================================================

    def procesar_seleccion_propiedades(self, agente_telefono: str, propiedades_seleccionadas: List[int],
                                        solicitud_id: int) -> Dict:
        """
        Procesa cuando un agente selecciona propiedades de interés

        Args:
            agente_telefono (str): Teléfono del agente
            propiedades_seleccionadas (list): Lista de IDs de propiedades seleccionadas
            solicitud_id (int): ID de la solicitud de mercado

        Returns:
            dict: Resultado del procesamiento con información de contacto
        """
        print(f"\n✅ Procesando selección de propiedades...")
        print(f"   Agente: {agente_telefono}")
        print(f"   Propiedades: {propiedades_seleccionadas}")

        try:
            db = self._get_db()

            try:
                resultados = []

                for propiedad_id in propiedades_seleccionadas:
                    # 1. Obtener propiedad con información del agente
                    propiedad = db.get_propiedad_con_agente(propiedad_id)

                    if not propiedad:
                        continue

                    # 2. Determinar teléfono del vendedor
                    # SIEMPRE usar el contacto principal (Hernán Ríos)
                    vendedor_telefono = self.contacto_principal
                    vendedor_nombre = self.nombre_contacto

                    # Tipo solo para tracking interno
                    if propiedad.get('origen') == 'Wasi_Captado':
                        tipo = 'captada'
                    else:
                        tipo = 'pulppo'

                    # 3. Registrar interacción
                    interaccion_id = db.insert_interaccion(
                        agente_comprador_telefono=agente_telefono,
                        propiedad_id=propiedad_id,
                        solicitud_mercado_id=solicitud_id,
                        agente_vendedor_telefono=vendedor_telefono if tipo == 'captada' else None
                    )

                    # 4. Log del evento
                    db.log_evento(
                        tipo_evento='Propiedad_Seleccionada',
                        agente_telefono=agente_telefono,
                        propiedad_id=propiedad_id,
                        solicitud_id=solicitud_id,
                        interaccion_id=interaccion_id,
                        datos_evento={
                            'propiedad_codigo': propiedad.get('codigo_propiedad'),
                            'tipo_origen': tipo,
                            'vendedor': vendedor_telefono
                        },
                        resultado='Exitoso'
                    )

                    resultados.append({
                        'propiedad_id': propiedad_id,
                        'interaccion_id': interaccion_id,
                        'tipo': tipo,
                        'contacto': vendedor_telefono,
                        'contacto_nombre': vendedor_nombre,
                        'propiedad': propiedad
                    })

                # 5. Actualizar estado de la solicitud
                db.cursor.execute(
                    """
                    UPDATE solicitudes_mercado
                    SET estado = 'Seleccionado', fecha_cambio_estado = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (solicitud_id,)
                )
                db.conn.commit()

                return {
                    'success': True,
                    'total_seleccionadas': len(resultados),
                    'selecciones': resultados
                }
            finally:
                db.disconnect()

        except Exception as e:
            print(f"❌ Error en selección: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    # =========================================================================
    # NOTIFICACIONES
    # =========================================================================

    def debe_notificar_vendedor(self, interaccion_id: int) -> bool:
        """
        Determina si se debe notificar al agente vendedor

        Args:
            interaccion_id (int): ID de la interacción

        Returns:
            bool: True si debe notificar
        """
        # Obtener configuración del sistema
        db = self._get_db()
        notificaciones_activas = db.get_config_valor('notificaciones_activas', 'true')

        return notificaciones_activas.lower() == 'true'

    def generar_mensaje_notificacion_vendedor(self, interaccion_id: int) -> Optional[Dict]:
        """
        Genera el mensaje de notificación para el agente vendedor

        Args:
            interaccion_id (int): ID de la interacción

        Returns:
            dict: {
                'destinatario': str,
                'mensaje': str
            }
        """
        try:
            db = self._get_db()

            # Obtener información completa de la interacción
            db.cursor.execute(
                "SELECT * FROM v_interacciones_completas WHERE id = %s",
                (interaccion_id,)
            )
            interaccion = db.cursor.fetchone()

            if not interaccion:
                return None

            # Generar mensaje
            msg = f"🎯 *¡Buenas noticias!*\n\n"
            msg += f"Un agente está interesado en tu propiedad:\n\n"
            msg += f"🏠 *{interaccion['propiedad_titulo']}*\n"
            msg += f"📍 {interaccion['ciudad']} - {interaccion['zona']}\n"
            msg += f"💰 {interaccion['precio']:,}\n\n"
            msg += f"👤 *Agente interesado:*\n"
            msg += f"📱 {interaccion['comprador_telefono']}\n\n"
            msg += f"💡 _Te sugerimos contactarlo pronto para coordinar la visita._"

            return {
                'destinatario': interaccion['vendedor_telefono'],
                'mensaje': msg
            }

        except Exception as e:
            print(f"❌ Error al generar notificación: {e}")
            return None

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
