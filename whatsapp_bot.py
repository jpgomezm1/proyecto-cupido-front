#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot de WhatsApp para búsqueda inteligente de propiedades
Integración con UltraMSG API
"""

import os
import requests
import json
import re
from typing import Dict, Any, List
from datetime import datetime
from dotenv import load_dotenv
from busqueda_propiedades import PropertySearchAgent
from cupido_manager import CupidoManager

load_dotenv()


class WhatsAppBot:
    """Bot de WhatsApp usando UltraMSG API - Proyecto Cupido"""

    def __init__(self):
        self.instance_id = os.getenv('ULTRAMSG_INSTANCE_ID')
        self.token = os.getenv('ULTRAMSG_TOKEN')
        self.base_url = f"https://api.ultramsg.com/{self.instance_id}"

        if not self.instance_id or not self.token:
            raise ValueError("❌ Faltan credenciales de UltraMSG en .env")

        # Inicializar agente de búsqueda
        self.search_agent = PropertySearchAgent()

        # Inicializar Cupido Manager
        self.cupido = CupidoManager()

        # Guardar sesiones de búsqueda (número -> propiedades)
        # En producción esto debería ser Redis o una BD
        self.user_sessions = {}

        # ID del grupo de Cupido (configurar en .env como GRUPO_CUPIDO_ID)
        self.grupo_cupido_id = os.getenv('GRUPO_CUPIDO_ID', '')

        print(f"✅ WhatsApp Bot inicializado (Proyecto Cupido)")
        print(f"   Instance ID: {self.instance_id}")
        print(f"   Base URL: {self.base_url}")
        if self.grupo_cupido_id:
            print(f"   Grupo Cupido: {self.grupo_cupido_id}")

    def send_message(self, to: str, body: str) -> Dict[str, Any]:
        """
        Enviar mensaje de WhatsApp a un número

        Args:
            to: Número de teléfono con formato internacional (ej: +573001234567)
            body: Texto del mensaje (máx 4096 caracteres)

        Returns:
            Respuesta de la API
        """
        url = f"{self.base_url}/messages/chat"

        payload = {
            'token': self.token,
            'to': to,
            'body': body
        }

        try:
            response = requests.post(url, data=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Error enviando mensaje: {e}")
            return {'error': str(e)}

    def format_property_result(self, prop: Dict[str, Any], index: int) -> str:
        """
        Formatear una propiedad para WhatsApp de forma profesional
        """
        titulo = prop.get('titulo', 'Sin título')
        precio = prop.get('precio_texto', 'Precio no disponible')
        zona = prop.get('zona', 'Zona no disponible')
        habitaciones = prop.get('habitaciones', '?')
        banos = prop.get('banos', '?')
        area = prop.get('area_construida', '?')
        estrato = prop.get('estrato', '')
        administracion = prop.get('administracion', '')
        parqueaderos = prop.get('parqueaderos', '')
        url = prop.get('url', '')

        # Amenidades
        amenidades_int = prop.get('amenidades_internas', '')
        amenidades_ext = prop.get('amenidades_externas', '')

        # Construir mensaje limpio y profesional
        msg = f"\n🏠 *OPCIÓN {index}*\n"
        msg += f"━━━━━━━━━━━━━━━━━━\n\n"

        # Título limpio
        msg += f"*{titulo}*\n\n"

        # Precio destacado
        msg += f"💰 *{precio}*\n\n"

        # Características principales
        msg += f"📋 *Características:*\n"
        msg += f"• {habitaciones} habitaciones | {banos} baños\n"
        msg += f"• Área: {area} m²\n"

        if parqueaderos:
            msg += f"• Parqueaderos: {parqueaderos}\n"

        if estrato:
            msg += f"• Estrato {estrato}\n"

        if administracion:
            try:
                admin_formatted = f"${int(administracion):,}".replace(',', '.')
                msg += f"• Administración: {admin_formatted}\n"
            except:
                pass

        # Amenidades (más compacto)
        amenidades = []
        if amenidades_int:
            amenidades.extend(amenidades_int.split(' | ')[:4])
        if amenidades_ext and len(amenidades) < 6:
            amenidades.extend(amenidades_ext.split(' | ')[:6-len(amenidades)])

        if amenidades:
            msg += f"\n✨ *Incluye:*\n"
            # Dividir en líneas de 2 amenidades
            for i in range(0, len(amenidades), 2):
                if i+1 < len(amenidades):
                    msg += f"• {amenidades[i]} • {amenidades[i+1]}\n"
                else:
                    msg += f"• {amenidades[i]}\n"

        # URL
        if url:
            msg += f"\n🔗 {url}\n"

        return msg

    def process_search_query(self, query: str, sender: str) -> str:
        """
        Procesar consulta de búsqueda y generar respuesta

        Args:
            query: Consulta en lenguaje natural
            sender: Número de teléfono del remitente

        Returns:
            Mensaje de respuesta formateado
        """
        print(f"\n📱 Procesando consulta de {sender}")
        print(f"📝 Query: {query[:100]}...")

        # Realizar búsqueda
        try:
            result = self.search_agent.search(query, limit=5)

            if not result.get('success'):
                return f"❌ Lo siento, hubo un error procesando tu búsqueda:\n{result.get('error', 'Error desconocido')}"

            criteria = result.get('criteria', {})
            properties = result.get('results', [])
            total_found = result.get('total_found', 0)

            # Construir respuesta más limpia
            response = "✅ *Búsqueda completada*\n\n"

            # Mostrar criterios de forma compacta
            response += "🔍 *Tu búsqueda:*\n"

            if criteria.get('ubicaciones'):
                response += f"📍 {', '.join(criteria['ubicaciones'])}\n"
            if criteria.get('tipo_propiedad'):
                tipo = criteria['tipo_propiedad']
                habs = ""
                if criteria.get('habitaciones_min'):
                    habs = f" • {criteria['habitaciones_min']}"
                    if criteria.get('habitaciones_max') and criteria['habitaciones_max'] != criteria['habitaciones_min']:
                        habs += f"-{criteria['habitaciones_max']}"
                    habs += " hab"
                response += f"🏠 {tipo}{habs}\n"
            if criteria.get('precio_max'):
                precio_max = f"${criteria['precio_max']:,}".replace(',', '.')
                response += f"💰 Hasta {precio_max}\n"

            if not properties:
                response += "\n😔 No encontramos propiedades con estos criterios.\n\n"
                response += "💡 *Intenta:*\n"
                response += "• Ampliar presupuesto\n"
                response += "• Buscar en zonas cercanas\n"
                response += "• Reducir requisitos\n"
                return response

            response += f"\n📊 *{total_found} propiedades encontradas*\n"
            response += f"Te muestro las mejores {len(properties)} opciones:\n"

            # Enviar cada propiedad como mensaje separado (para no exceder límite)
            return response

        except Exception as e:
            print(f"❌ Error en búsqueda: {e}")
            import traceback
            traceback.print_exc()
            return f"❌ Lo siento, ocurrió un error inesperado:\n{str(e)}"

    def send_search_results(self, to: str, query: str) -> bool:
        """
        Realizar búsqueda y enviar resultados al usuario

        Args:
            to: Número de WhatsApp del destinatario
            query: Consulta de búsqueda

        Returns:
            True si se enviaron correctamente, False en caso contrario
        """
        try:
            # Realizar búsqueda
            result = self.search_agent.search(query, limit=5)

            if not result.get('success'):
                error_msg = f"❌ Error en búsqueda:\n{result.get('error', 'Error desconocido')}"
                self.send_message(to, error_msg)
                return False

            # Enviar mensaje inicial con criterios
            initial_response = self.process_search_query(query, to)
            self.send_message(to, initial_response)

            # Enviar cada propiedad en mensaje separado
            properties = result.get('results', [])

            if properties:
                # Guardar propiedades en la sesión del usuario
                self.user_sessions[to] = {
                    'properties': properties,
                    'query': query,
                    'timestamp': datetime.now().isoformat()
                }

                for i, prop in enumerate(properties, 1):
                    prop_msg = self.format_property_result(prop, i)
                    self.send_message(to, prop_msg)

                # Mensaje final con opciones de selección
                final_msg = f"\n━━━━━━━━━━━━━━━━━━\n\n"
                final_msg += f"✅ ¡Listo! Te envié {len(properties)} opciones.\n\n"
                final_msg += f"📝 *¿Cuáles te interesan para ofrecerle a tu cliente?*\n\n"
                final_msg += f"Responde con el número o números de las opciones que te gustan:\n\n"

                # Listar opciones de forma clara
                for i in range(1, len(properties) + 1):
                    final_msg += f"• *{i}* - Para la opción {i}\n"

                final_msg += f"• *Ninguna* - Si no te convence ninguna\n"
                final_msg += f"• *Todas* - Si te interesan todas\n\n"
                final_msg += f"_Ejemplos: \"1\", \"1 y 3\", \"todas\", \"ninguna\"_"

                self.send_message(to, final_msg)

            return True

        except Exception as e:
            print(f"❌ Error enviando resultados: {e}")
            import traceback
            traceback.print_exc()

            error_msg = f"❌ Lo siento, ocurrió un error:\n{str(e)}"
            self.send_message(to, error_msg)
            return False

    def send_search_results_cupido(self, to: str, propiedades: List[Dict], solicitud_id: int) -> bool:
        """
        Enviar resultados de búsqueda con integración Proyecto Cupido
        Incluye información de contacto según el origen de la propiedad

        Args:
            to: Número de WhatsApp del destinatario
            propiedades: Lista de propiedades encontradas
            solicitud_id: ID de la solicitud de mercado en la DB

        Returns:
            True si se enviaron correctamente
        """
        try:
            # Mensaje inicial
            initial_msg = f"🔍 *Resultados de tu búsqueda*\n\n"
            initial_msg += f"✅ Encontré {len(propiedades)} propiedades que coinciden con lo que buscas:\n"

            self.send_message(to, initial_msg)

            # Guardar propiedades en la sesión
            self.user_sessions[to] = {
                'properties': propiedades,
                'solicitud_id': solicitud_id,
                'timestamp': datetime.now().isoformat()
            }

            # Enviar cada propiedad
            for i, prop in enumerate(propiedades, 1):
                prop_msg = self.format_property_result(prop, i)
                self.send_message(to, prop_msg)

            # Mensaje final con opciones
            final_msg = f"\n━━━━━━━━━━━━━━━━━━\n\n"
            final_msg += f"✅ ¡Listo! Te envié {len(propiedades)} opciones.\n\n"
            final_msg += f"📝 *¿Cuáles te interesan?*\n\n"
            final_msg += f"Responde con los números de las que quieras contactar:\n\n"

            for i in range(1, len(propiedades) + 1):
                final_msg += f"• *{i}* - Para la opción {i}\n"

            final_msg += f"• *Ninguna* - Si no te convence ninguna\n"
            final_msg += f"• *Todas* - Si te interesan todas\n\n"
            final_msg += f"_Ejemplos: \"1\", \"1 y 3\", \"todas\", \"ninguna\"_"

            self.send_message(to, final_msg)

            return True

        except Exception as e:
            print(f"❌ Error enviando resultados Cupido: {e}")
            import traceback
            traceback.print_exc()
            return False

    def parse_selection(self, message: str, total_options: int) -> List[int]:
        """
        Parsear la selección del usuario

        Args:
            message: Mensaje del usuario
            total_options: Total de opciones disponibles

        Returns:
            Lista de números seleccionados, o lista vacía si es "ninguna"
        """
        message_lower = message.lower().strip()

        # Caso especial: ninguna
        if 'ninguna' in message_lower or 'ninguno' in message_lower:
            return []

        # Caso especial: todas
        if 'todas' in message_lower or 'todos' in message_lower or 'all' in message_lower:
            return list(range(1, total_options + 1))

        # Extraer números del mensaje
        numbers = re.findall(r'\d+', message)
        selected = []

        for num_str in numbers:
            try:
                num = int(num_str)
                if 1 <= num <= total_options:
                    if num not in selected:
                        selected.append(num)
            except:
                continue

        return sorted(selected)

    def handle_property_selection(self, sender: str, message: str) -> Dict[str, Any]:
        """
        Procesar selección de propiedades

        Args:
            sender: Número del usuario
            message: Mensaje con la selección

        Returns:
            Diccionario con el resultado
        """
        # Verificar si hay una sesión activa
        if sender not in self.user_sessions:
            return {
                'status': 'no_session',
                'message': None
            }

        session = self.user_sessions[sender]
        properties = session['properties']
        total_options = len(properties)

        # Parsear selección
        selected = self.parse_selection(message, total_options)

        if not selected and 'ninguna' not in message.lower():
            # No se entendió la selección
            return {
                'status': 'invalid_selection',
                'message': None
            }

        # Ninguna propiedad
        if not selected:
            response = "👌 Entendido, ninguna de estas propiedades te interesa.\n\n"
            response += "🔍 ¿Quieres hacer otra búsqueda con criterios diferentes?\n"
            response += "Escríbeme qué necesitas."

            self.send_message(sender, response)

            # Limpiar sesión
            del self.user_sessions[sender]

            return {
                'status': 'none_selected',
                'selected': [],
                'message': 'ninguna'
            }

        # Propiedades seleccionadas
        selected_properties = [properties[i-1] for i in selected]

        # Obtener IDs de propiedades seleccionadas
        propiedades_ids = [prop.get('id') for prop in selected_properties if prop.get('id')]

        # Mensaje de confirmación
        response = f"✅ *Perfecto!* Seleccionaste {len(selected)} propiedad"
        response += "es" if len(selected) > 1 else ""
        response += ":\n\n"

        for i, prop_idx in enumerate(selected, 1):
            prop = properties[prop_idx - 1]
            titulo = prop.get('titulo', 'Sin título')[:50]
            precio = prop.get('precio_texto', 'N/A')
            response += f"*{prop_idx}.* {titulo}\n"
            response += f"   💰 {precio}\n\n"

        self.send_message(sender, response)

        # ===================================================================
        # INTEGRACIÓN CUPIDO: Procesar selección y obtener información de contacto
        # ===================================================================

        solicitud_id = session.get('solicitud_id')

        # Procesar selección con Cupido Manager
        result = self.cupido.procesar_seleccion_propiedades(
            agente_telefono=sender,
            propiedades_seleccionadas=propiedades_ids,
            solicitud_id=solicitud_id
        )

        if result['success']:
            # Enviar información de contacto para cada propiedad
            msg_contacto = f"📞 *Información de contacto*\n\n"

            for seleccion in result['selecciones']:
                propiedad = seleccion['propiedad']
                tipo = seleccion['tipo']
                contacto = seleccion['contacto']
                nombre = seleccion['contacto_nombre']

                titulo = propiedad.get('titulo', 'Sin título')[:40]

                msg_contacto += f"🏠 *{titulo}*\n"

                if tipo == 'captada':
                    msg_contacto += f"📱 Contactar a: *{nombre}*\n"
                    msg_contacto += f"   Teléfono: {contacto}\n"
                    msg_contacto += f"   _(Propiedad captada por este agente)_\n\n"

                    # Notificar al agente vendedor
                    if self.cupido.debe_notificar_vendedor(seleccion['interaccion_id']):
                        notif = self.cupido.generar_mensaje_notificacion_vendedor(seleccion['interaccion_id'])
                        if notif:
                            self.send_message(notif['destinatario'], notif['mensaje'])
                            print(f"✉️  Notificación enviada a {notif['destinatario']}")

                else:  # Pulppo
                    msg_contacto += f"📱 Contactar a: *Pulppo*\n"
                    msg_contacto += f"   Teléfono: {contacto}\n"
                    msg_contacto += f"   _(Propiedad de nuestra base de datos)_\n\n"

            msg_contacto += f"💡 _Coordina con ellos para hacer el proceso de visita y cierre._"

            self.send_message(sender, msg_contacto)

        # Limpiar sesión
        del self.user_sessions[sender]

        return {
            'status': 'selected',
            'selected': selected,
            'properties': selected_properties
        }

    def handle_incoming_message(self, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Manejar mensaje entrante desde webhook

        Args:
            webhook_data: Datos del webhook de UltraMSG

        Returns:
            Respuesta procesada
        """
        try:
            # UltraMSG envía los datos dentro de 'data'
            # Extraer el objeto 'data' si existe
            if 'data' in webhook_data:
                message_data = webhook_data['data']
            else:
                message_data = webhook_data

            # Extraer información del webhook
            sender = message_data.get('from', '')
            to = message_data.get('to', '')
            message_body = message_data.get('body', '')
            message_type = message_data.get('type', 'chat')
            event_type = webhook_data.get('event_type', '')

            print(f"\n📩 Mensaje recibido de: {sender}")
            print(f"📝 Contenido: {message_body[:100]}...")
            print(f"📋 Tipo: {message_type}")
            print(f"📋 Evento: {event_type}")

            # Ignorar eventos que no son mensajes nuevos
            if event_type not in ['message_received', '']:
                print(f"⚠️  Ignorando evento tipo: {event_type}")
                return {'status': 'ignored', 'reason': 'not_message_received'}

            # Ignorar mensajes propios (fromMe)
            if message_data.get('fromMe') or message_data.get('self'):
                print(f"⚠️  Ignorando mensaje propio")
                return {'status': 'ignored', 'reason': 'own_message'}

            # Detectar si es mensaje de grupo
            is_group_message = '@g.us' in sender or '@g.us' in to
            grupo_id = sender if '@g.us' in sender else (to if '@g.us' in to else None)

            # Si es mensaje de grupo, solo procesar si es el grupo de Cupido
            if is_group_message:
                if not self.grupo_cupido_id or grupo_id != self.grupo_cupido_id:
                    print(f"⚠️  Ignorando mensaje de grupo (no es grupo Cupido)")
                    return {'status': 'ignored', 'reason': 'group_message_not_cupido'}

                print(f"✅ Mensaje del grupo Cupido - procesando...")
                # Extraer teléfono del participante del mensaje
                # En UltraMSG el participante viene en 'author', no en 'participant'
                author = message_data.get('author', '')
                if author and '@c.us' in author:
                    sender = author.replace('@c.us', '')
                    if not sender.startswith('+'):
                        sender = '+' + sender
                    print(f"   👤 Participante identificado: {sender}")
                else:
                    print(f"⚠️  No se pudo identificar participante en grupo")
                    print(f"   author recibido: {author}")
                    return {'status': 'ignored', 'reason': 'no_participant_info'}

            # UltraMSG envía el número con @c.us, quitarlo
            if '@c.us' in sender:
                sender = sender.replace('@c.us', '')

            # Convertir a formato internacional si es necesario
            if not sender.startswith('+'):
                sender = '+' + sender

            # Ignorar mensajes que no son de texto
            if message_type != 'chat':
                print(f"⚠️  Tipo de mensaje no soportado: {message_type}")
                return {'status': 'ignored', 'reason': 'unsupported_type'}

            # Ignorar mensajes vacíos (pero permitir comandos cortos como "hola", "hi", etc.)
            if not message_body or len(message_body.strip()) < 1:
                print(f"⚠️  Mensaje vacío, ignorando")
                return {'status': 'ignored', 'reason': 'empty_message'}

            # Comandos especiales
            message_lower = message_body.lower().strip()

            if message_lower in ['hola', 'hi', 'hello', 'inicio', 'empezar']:
                welcome_msg = "👋 *¡Hola! Bienvenido al Buscador Inteligente de Propiedades TU360*\n\n"
                welcome_msg += "🏠 Puedo ayudarte a encontrar la propiedad perfecta para ti.\n\n"
                welcome_msg += "📝 *¿Cómo funciona?*\n"
                welcome_msg += "Solo envíame un mensaje con lo que buscas. Por ejemplo:\n\n"
                welcome_msg += "_\"Busco apto en Laureles, 2 habitaciones, hasta 500 millones\"_\n\n"
                welcome_msg += "o\n\n"
                welcome_msg += "_\"Casa en Envigado, 3 alcobas, con jardín y parqueadero\"_\n\n"
                welcome_msg += "💬 Cuéntame qué necesitas y yo me encargo del resto!"

                self.send_message(sender, welcome_msg)
                return {'status': 'welcome_sent'}

            if message_lower in ['ayuda', 'help', '?']:
                help_msg = "❓ *AYUDA - Buscador de Propiedades*\n\n"
                help_msg += "📋 *Puedo entender criterios como:*\n\n"
                help_msg += "📍 Ubicación: Laureles, Poblado, Envigado, etc.\n"
                help_msg += "🏠 Tipo: Apartamento, Casa, Penthouse, Duplex\n"
                help_msg += "💰 Presupuesto: \"hasta 500 millones\", \"entre 300 y 600\"\n"
                help_msg += "🛏️ Habitaciones: \"2 alcobas\", \"3 habitaciones\"\n"
                help_msg += "📐 Área: \"80m² o más\"\n"
                help_msg += "🌟 Amenidades: piscina, gimnasio, portería, etc.\n\n"
                help_msg += "💡 *Ejemplo:*\n"
                help_msg += "_Apto en Laureles o Poblado, 2 habitaciones, hasta 600 millones, con parqueadero_"

                self.send_message(sender, help_msg)
                return {'status': 'help_sent'}

            # =====================================================================
            # FLUJO PROYECTO CUPIDO - DETECCIÓN INTELIGENTE DE TIPO DE MENSAJE
            # =====================================================================

            # 1. Verificar si el usuario tiene una sesión activa (está seleccionando propiedades)
            if sender in self.user_sessions and not is_group_message:
                # Intentar procesar como selección de propiedades
                selection_result = self.handle_property_selection(sender, message_body)

                if selection_result['status'] in ['selected', 'none_selected']:
                    return selection_result

                # Si no se entendió la selección pero hay números, asumir que es selección
                if re.search(r'\d+', message_body) or 'todas' in message_lower or 'ninguna' in message_lower:
                    return selection_result

            # 2. Usar Cupido Manager para detectar tipo de mensaje
            deteccion = self.cupido.detectar_tipo_mensaje(message_body, sender, is_group_message)

            print(f"🔍 Tipo detectado: {deteccion['tipo']} (confianza: {deteccion['confianza']})")

            # 3. CASO: Captación de propiedad (link de Wasi)
            if deteccion['tipo'] == 'captacion_wasi':
                url_wasi = deteccion['data']['url']
                print(f"📥 Captando propiedad de Wasi: {url_wasi}")

                # Procesar captación
                result = self.cupido.procesar_captacion_wasi(
                    url_wasi=url_wasi,
                    agente_telefono=sender,
                    mensaje_completo=message_body,
                    grupo_id=grupo_id if is_group_message else None
                )

                if result['success']:
                    # Si es del grupo, enviar confirmación al agente por privado
                    if is_group_message:
                        msg_confirm = f"✅ *Propiedad captada exitosamente*\n\n"
                        msg_confirm += f"🏠 {result.get('titulo', 'Sin título')}\n"
                        msg_confirm += f"📝 Código: {result.get('codigo', 'N/A')}\n\n"
                        msg_confirm += f"La propiedad ha sido agregada al sistema y está disponible para búsquedas."

                        self.send_message(sender, msg_confirm)

                    return {
                        'status': 'captacion_exitosa',
                        'propiedad_id': result['propiedad_id']
                    }
                else:
                    # Error en captación
                    if is_group_message:
                        msg_error = f"⚠️ No pude procesar la propiedad de Wasi.\n\n"
                        msg_error += f"Error: {result.get('error', 'Desconocido')}"
                        self.send_message(sender, msg_error)

                    return {
                        'status': 'captacion_error',
                        'error': result.get('error')
                    }

            # 4. CASO: Solicitud de mercado (búsqueda de propiedad)
            elif deteccion['tipo'] == 'solicitud_mercado':
                query = deteccion['data']['query']
                origen = 'Grupo' if is_group_message else 'Chat_Privado'

                print(f"🔍 Procesando solicitud de mercado (origen: {origen})")

                # Procesar solicitud de mercado
                result = self.cupido.procesar_solicitud_mercado(
                    query=query,
                    agente_telefono=sender,
                    origen=origen,
                    grupo_id=grupo_id if is_group_message else None
                )

                if result['success']:
                    # Si es del grupo, responder por privado
                    destinatario = sender

                    if is_group_message:
                        # Confirmar en el grupo que se está procesando
                        msg_grupo = "✅ ¡Entendido! Te envío las opciones por privado."
                        # Nota: En producción necesitarías enviar al grupo, por ahora solo al privado

                    # Enviar resultados por privado
                    self.send_search_results_cupido(
                        destinatario,
                        result['propiedades'],
                        result['solicitud_id']
                    )

                    return {
                        'status': 'solicitud_procesada',
                        'solicitud_id': result['solicitud_id'],
                        'total_found': result['total_found']
                    }
                else:
                    msg_error = f"⚠️ Error en la búsqueda: {result.get('error')}"
                    self.send_message(sender, msg_error)

                    return {
                        'status': 'solicitud_error',
                        'error': result.get('error')
                    }

            # 5. CASO: Chat normal (no es captación ni solicitud)
            else:
                # Solo responder en chats privados
                if not is_group_message:
                    help_msg = "🤔 No entendí tu mensaje.\n\n"
                    help_msg += "📋 *Puedo ayudarte con:*\n\n"
                    help_msg += "1️⃣ *Buscar propiedades*\n"
                    help_msg += "   Ejemplo: _Busco apto en Laureles, 2 habitaciones_\n\n"
                    help_msg += "2️⃣ *Captar propiedades*\n"
                    help_msg += "   Comparte un link de Wasi\n\n"
                    help_msg += "Escribe *ayuda* para más información."

                    self.send_message(sender, help_msg)

                return {'status': 'chat_normal'}

        except Exception as e:
            print(f"❌ Error manejando mensaje entrante: {e}")
            import traceback
            traceback.print_exc()

            # Intentar enviar mensaje de error al usuario
            try:
                if sender:
                    error_msg = "❌ Lo siento, hubo un error procesando tu mensaje. Por favor intenta de nuevo."
                    self.send_message(sender, error_msg)
            except:
                pass

            return {
                'status': 'error',
                'error': str(e)
            }


if __name__ == "__main__":
    # Test rápido de envío
    print("🧪 Test de WhatsApp Bot")

    try:
        bot = WhatsAppBot()

        # Número de prueba (cambiar por tu número)
        test_number = input("📱 Ingresa número de WhatsApp para test (formato +57300...): ")

        if test_number:
            # Mensaje de bienvenida
            print("\n📤 Enviando mensaje de prueba...")
            result = bot.send_message(
                test_number,
                "🤖 *Test Bot TU360*\n\n¡Hola! Este es un mensaje de prueba del bot de búsqueda de propiedades. ¿Está funcionando? ✅"
            )
            print(f"✅ Resultado: {result}")
        else:
            print("⚠️  No se ingresó número de prueba")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
